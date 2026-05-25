"""
AI Lab experiment modes for the redesigned board studio.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict, List

from openai import AsyncOpenAI

from core.a_star_solver import AStarSolver
from core.config import settings
from core.models import (
    AIExperimentRequest,
    AIExperimentResponse,
    BoardAsset,
    FinalRoute,
    Hold,
    HoldType,
    RecipeItem,
    RouteReviewSuggestion,
    RouteReviewViolation,
)
from core.validator import PhysicsValidator


def _hold_ids(holds: List[Hold]) -> set[str]:
    return {hold.id for hold in holds}


def _infer_start_flags(holds: List[Hold]) -> List[Hold]:
    copied = [hold.model_copy() for hold in holds]
    if any(hold.is_start for hold in copied):
        return copied

    sorted_holds = sorted(copied, key=lambda hold: (hold.y, hold.x))
    feet = [hold for hold in sorted_holds if hold.hold_type == HoldType.FOOT][:2]
    hands = [hold for hold in sorted_holds if hold.hold_type != HoldType.FOOT][:2]
    for hold in feet + hands:
        hold.is_start = True
    return copied


def _board_budget(holds: List[Hold]) -> Dict[HoldType, int]:
    counts = Counter(hold.hold_type for hold in holds)
    return {hold_type: count for hold_type, count in counts.items()}


def _route_with_board_metadata(route: FinalRoute, request: AIExperimentRequest) -> FinalRoute:
    board = request.board
    return route.model_copy(
        update={
            "board_spec": board.board_spec,
            "difficulty": request.target_difficulty or board.difficulty or "V3",
            "source_type": "ai-generated",
            "visibility": board.visibility,
            "tags": board.tags,
            "owner_id": board.owner_id,
        }
    )


async def _llm_json(system_prompt: str, payload: dict) -> dict | None:
    if not settings.api_key:
        return None

    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
    try:
        response = await client.chat.completions.create(
            model=settings.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            timeout=30,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception as exc:
        print(f"LLM enrichment failed, using deterministic fallback: {exc}")
        return None


async def compose_route_from_board(request: AIExperimentRequest) -> AIExperimentResponse:
    holds = _infer_start_flags(request.board.placed_holds)
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    candidate, report = solver.solve(holds, _board_budget(holds))

    if not candidate:
        return AIExperimentResponse(
            mode="compose_route",
            selected_routes=[],
            failure_suggestion=f"当前岩板无法组合出完整路线：{report.get('reason', 'unknown')}",
            board=request.board,
        )

    route_name = "当前岩板重组路线"
    commentary = "基于当前岩板已有岩点，通过 A* 动作搜索重新组合出一条可行路线。"
    llm_result = await _llm_json(
        "You are a senior indoor climbing route setter. Return JSON with route_name and setter_commentary only.",
        {
            "mode": "compose_route",
            "user_requirements": request.user_requirements,
            "difficulty": request.target_difficulty or request.board.difficulty,
            "holds": [hold.model_dump(mode="json") for hold in candidate.placed_holds],
            "beta_sequence": [step.model_dump(mode="json") for step in candidate.beta_sequence],
        },
    )
    if llm_result:
        route_name = str(llm_result.get("route_name") or route_name)
        commentary = str(llm_result.get("setter_commentary") or commentary)

    final_route = FinalRoute(
        route_name=route_name,
        setter_commentary=commentary,
        placed_holds=candidate.placed_holds,
        beta_sequence=candidate.beta_sequence,
    )
    return AIExperimentResponse(
        mode="compose_route",
        selected_routes=[_route_with_board_metadata(final_route, request)],
        board=request.board,
    )


def _deterministic_review(board: BoardAsset) -> tuple[List[RouteReviewViolation], List[RouteReviewSuggestion], str]:
    validator = PhysicsValidator()
    violations: List[RouteReviewViolation] = []
    suggestions: List[RouteReviewSuggestion] = []

    ok, message = validator.validate_baseline(board.placed_holds)
    if not ok:
        violations.append(RouteReviewViolation(code="baseline_layout", message=message))
        suggestions.append(
            RouteReviewSuggestion(
                title="调整基础布局",
                detail="优先补齐起步区、顶部完攀区和中段连续性，再重新检查动作链。",
            )
        )

    hold_ids = _hold_ids(board.placed_holds)
    missing_beta_targets = [step.hold_id for step in board.beta_sequence if step.hold_id not in hold_ids]
    if missing_beta_targets:
        unique_missing = sorted(set(missing_beta_targets))
        violations.append(
            RouteReviewViolation(
                code="missing_beta_hold",
                message=f"Beta 序列引用了不存在的岩点：{', '.join(unique_missing)}",
                hold_ids=unique_missing,
            )
        )
        suggestions.append(
            RouteReviewSuggestion(
                title="修正 Beta 引用",
                detail="删除失效动作，或在对应坐标重新放置岩点后再保存。",
                hold_ids=unique_missing,
            )
        )

    if board.beta_sequence:
        ok, message = validator.validate_beta_balance(board.beta_sequence, board.placed_holds)
        if not ok:
            violations.append(RouteReviewViolation(code="beta_balance", message=message))
            suggestions.append(
                RouteReviewSuggestion(
                    title="降低身体横向扭转",
                    detail="优先调整脚点高度和左右分布，避免连续高脚或手脚中轴偏移过大。",
                )
            )

    if not board.beta_sequence:
        suggestions.append(
            RouteReviewSuggestion(
                title="补充 Beta 序列",
                detail="当前岩板没有动作序列。先标记起步、核心移动和完攀动作，审查结果会更准确。",
            )
        )

    if len(violations) >= 2:
        risk_level = "high"
    elif violations:
        risk_level = "medium"
    else:
        risk_level = "low"
    return violations, suggestions, risk_level


async def review_board_route(request: AIExperimentRequest) -> AIExperimentResponse:
    violations, suggestions, risk_level = _deterministic_review(request.board)
    summary = "当前路线通过基础可行性检查。" if not violations else "当前路线存在可行性风险，需要调整后再试攀。"

    llm_result = await _llm_json(
        (
            "You are a senior indoor climbing route setter. Review the route without changing it. "
            "Return JSON with review_summary and suggestions array of objects with title, detail, hold_ids."
        ),
        {
            "mode": "review_route",
            "user_requirements": request.user_requirements,
            "risk_level": risk_level,
            "violations": [violation.model_dump(mode="json") for violation in violations],
            "board": request.board.model_dump(mode="json"),
        },
    )
    if llm_result:
        summary = str(llm_result.get("review_summary") or summary)
        llm_suggestions = llm_result.get("suggestions")
        if isinstance(llm_suggestions, list):
            suggestions = [
                RouteReviewSuggestion(
                    title=str(item.get("title") or "修改建议"),
                    detail=str(item.get("detail") or ""),
                    hold_ids=list(item.get("hold_ids") or []),
                )
                for item in llm_suggestions
                if isinstance(item, dict)
            ] or suggestions

    return AIExperimentResponse(
        mode="review_route",
        review_summary=summary,
        violations=violations,
        suggestions=suggestions,
        risk_level=risk_level,
        board=request.board,
    )


async def run_ai_experiment(request: AIExperimentRequest) -> AIExperimentResponse:
    if request.mode == "review_route":
        return await review_board_route(request)
    return await compose_route_from_board(request)


def board_to_legacy_request(board: BoardAsset) -> dict:
    counts = Counter(hold.hold_type for hold in board.placed_holds)
    return {
        "climber_height_cm": 175,
        "climber_span_cm": 175,
        "target_difficulty": board.difficulty or "V3",
        "special_requirements": "",
        "recipe": {
            hold_type.value: RecipeItem(count=count, variant="random").model_dump()
            for hold_type, count in counts.items()
        },
    }
