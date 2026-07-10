"""
Algorithm-backed AI Lab experiment modes for board-based compose/review flows.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from itertools import combinations
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from openai import AsyncOpenAI

from core.a_star_solver import AStarSolver
from core.config import settings
from core.models import (
    AIExperimentRequest,
    AIExperimentResponse,
    BoardAsset,
    BetaStep,
    FinalRoute,
    Hold,
    HoldType,
    Limb,
    RecipeItem,
    RouteReviewSuggestion,
    RouteReviewViolation,
)
from core.standard_board import query_standard_routes
from core.validator import PhysicsValidator


HOLD_DIFFICULTY = {
    HoldType.JUG: 18.0,
    HoldType.PINCH: 52.0,
    HoldType.SLOPER: 62.0,
    HoldType.CRIMP: 72.0,
    HoldType.POCKET: 82.0,
    HoldType.FOOT: 50.0,
}
GRADE_CUTOFFS = [38.98, 54.15, 56.23, 61.55, 64.22, 65.97, 68.73, 71.9, 74.77, 79.17]
GRADE_ORDER = [f"V{index}" for index in range(11)]
SUGGESTION_GROUP_LABELS = {
    "must_fix": "必须修",
    "should_fix": "建议修",
    "optional": "可选优化",
}


def _hold_ids(holds: Sequence[Hold]) -> set[str]:
    return {hold.id for hold in holds}


def _x_index(hold: Hold) -> int:
    return ord(hold.x.upper()) - ord("A")


def _grade_number(grade: str | None) -> int:
    try:
        return int(str(grade or "V3").upper().replace("V", ""))
    except ValueError:
        return 3


def _grade_from_score(score: float) -> str:
    for index, cutoff in enumerate(GRADE_CUTOFFS):
        if score <= cutoff:
            return GRADE_ORDER[index]
    return GRADE_ORDER[-1]


def _route_signature(holds: Sequence[Hold]) -> str:
    return "|".join(sorted(hold.id for hold in holds))


def _dedupe_holds(holds: Iterable[Hold]) -> List[Hold]:
    seen: set[str] = set()
    deduped: List[Hold] = []
    for hold in holds:
        if hold.id in seen:
            continue
        seen.add(hold.id)
        deduped.append(hold)
    return deduped


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


def _standard_reference(target_grade: str) -> Dict[str, float]:
    routes = query_standard_routes(difficulty=target_grade, sort="score_desc", limit=50).routes
    if not routes:
        routes = query_standard_routes(sort="score_desc", limit=50).routes
    if not routes:
        return {"hold_count": 8.0, "x_span": 5.0, "difficulty_score": 58.0}
    return {
        "hold_count": sum(route.features.hold_count for route in routes) / len(routes),
        "x_span": sum(route.features.x_span for route in routes) / len(routes),
        "difficulty_score": sum(float(route.difficulty_score or 0.0) for route in routes) / len(routes),
    }


def _board_metrics(holds: Sequence[Hold], target_grade: str = "V3") -> Dict[str, Any]:
    ordered = _dedupe_holds(holds)
    if not ordered:
        return {
            "valid_for_climb": False,
            "hard_failures": ["empty_route"],
            "review_reasons": ["路线为空"],
            "hold_count": 0,
            "quality_score": 0.0,
            "difficulty_score": None,
            "predicted_v_grade": None,
            "grade_delta": None,
            "risk_score": 100.0,
        }

    x_values = [_x_index(hold) for hold in ordered]
    y_values = [hold.y for hold in ordered]
    sorted_y = sorted(set(y_values))
    max_vertical_gap = max((upper - lower for lower, upper in zip(sorted_y, sorted_y[1:])), default=0)
    start_holds = [hold for hold in ordered if hold.is_start]
    start_hands = [hold for hold in start_holds if hold.hold_type != HoldType.FOOT]
    start_feet = [hold for hold in start_holds if hold.hold_type == HoldType.FOOT]
    low_hands = [hold for hold in ordered if hold.y <= 5 and hold.hold_type != HoldType.FOOT]
    top_holds = [hold for hold in ordered if hold.y >= 16 and hold.hold_type != HoldType.FOOT]
    foot_holds = [hold for hold in ordered if hold.hold_type == HoldType.FOOT]
    hand_holds = [hold for hold in ordered if hold.hold_type != HoldType.FOOT]
    x_span = max(x_values) - min(x_values) + 1 if x_values else 0
    y_span = max(y_values) - min(y_values) + 1 if y_values else 0

    failures: List[str] = []
    reasons: List[str] = []
    if len(start_hands) < 2:
        failures.append("start_hand_count_lt_2")
        reasons.append("明确手起点少于 2 个")
    if not start_feet and not foot_holds:
        failures.append("no_foothold")
        reasons.append("缺少可用脚点")
    if len(top_holds) < 1:
        failures.append("end_count_lt_1")
        reasons.append("Y16-Y18 缺少非脚点终点")
    if not 6 <= len(ordered) <= 14:
        failures.append("hold_count_out_of_range")
        reasons.append("岩点总数不在 6-14 个的可控范围")
    if max_vertical_gap > 5:
        failures.append("vertical_gap_gt_5")
        reasons.append("纵向相邻层级断档超过 5")
    if x_span <= 2:
        failures.append("ladder_x_span_too_narrow")
        reasons.append("横向跨度过窄，接近梯子线")

    hold_count_score = 18.0 * max(0.0, 1.0 - abs(len(ordered) - 8) / 6.0)
    width_score = 20.0 * min(1.0, max(0, x_span - 2) / 6.0)
    height_score = 18.0 * min(1.0, y_span / 16.0)
    gap_score = 20.0 * max(0.0, 1.0 - max(0, max_vertical_gap - 3) / 4.0)
    start_finish_score = 16.0 if len(start_hands) >= 2 and top_holds else 6.0
    foot_score = 8.0 * min(1.0, max(1, len(foot_holds)) / 3.0)
    quality_score = round(max(0.0, min(100.0, hold_count_score + width_score + height_score + gap_score + start_finish_score + foot_score)), 2)

    sequence = sorted(hand_holds, key=lambda hold: (hold.y, _x_index(hold)))
    move_scores: List[float] = []
    for previous, current in zip(sequence, sequence[1:]):
        dx = abs(_x_index(current) - _x_index(previous))
        dy = abs(current.y - previous.y)
        distance = math.hypot(dx, dy * 1.15)
        hold_demand = HOLD_DIFFICULTY.get(current.hold_type, 55.0)
        foot_support = 72.0 if not foot_holds else min(82.0, 22.0 + min(abs(_x_index(foot) - _x_index(current)) + max(0, current.y - foot.y) for foot in foot_holds) * 6.0)
        body_tension = min(100.0, dx * 8.0 + max(0, dy - 3) * 8.0 + foot_support * 0.18)
        move_scores.append(distance * 8.5 + hold_demand * 0.24 + foot_support * 0.18 + body_tension * 0.20)

    if move_scores:
        sorted_moves = sorted(move_scores, reverse=True)
        crux = sum(sorted_moves[:2]) / min(2, len(sorted_moves))
        sustained = sum(sorted_moves[: max(1, math.ceil(len(sorted_moves) * 0.5))]) / max(1, math.ceil(len(sorted_moves) * 0.5))
        average = sum(move_scores) / len(move_scores)
        pressure = max(move_scores[0], move_scores[-1])
        difficulty_score = round(max(0.0, min(100.0, crux * 0.45 + sustained * 0.25 + average * 0.15 + pressure * 0.10 + _grade_number(target_grade) * 0.6)), 2)
        predicted_grade = _grade_from_score(difficulty_score)
        grade_delta = _grade_number(predicted_grade) - _grade_number(target_grade)
    else:
        difficulty_score = None
        predicted_grade = None
        grade_delta = None

    risk_score = len(failures) * 22.0
    risk_score += 12.0 if max_vertical_gap > 4 else 0.0
    risk_score += 10.0 if len(foot_holds) < 2 else 0.0
    risk_score += min(20.0, abs(grade_delta or 0) * 5.0)
    risk_score = round(min(100.0, risk_score), 2)

    notes: List[str] = []
    if x_span >= 7:
        notes.append("横向跨度较大")
    if max_vertical_gap >= 5:
        notes.append("存在纵向断档")
    if foot_holds:
        notes.append(f"包含 {len(foot_holds)} 个脚点")
    if difficulty_score is not None and abs(grade_delta or 0) >= 2:
        notes.append("预测难度与目标难度存在明显差异")
    if not notes:
        notes.append("结构分布较均衡")

    return {
        "valid_for_climb": not failures,
        "hard_failures": failures,
        "review_reasons": reasons,
        "hold_count": len(ordered),
        "start_count": len(start_holds),
        "start_hand_count": len(start_hands),
        "start_foot_count": len(start_feet),
        "foot_count": len(foot_holds),
        "top_count": len(top_holds),
        "x_span": x_span,
        "y_span": y_span,
        "max_vertical_gap": max_vertical_gap,
        "quality_score": quality_score,
        "difficulty_score": difficulty_score,
        "predicted_v_grade": predicted_grade,
        "target_v_grade": target_grade,
        "grade_delta": grade_delta,
        "risk_score": risk_score,
        "algorithm_notes": notes,
    }


def _choose_start_holds(holds: Sequence[Hold]) -> List[Hold]:
    explicit = [hold for hold in holds if hold.is_start]
    if explicit:
        return sorted(explicit, key=lambda hold: (hold.hold_type == HoldType.FOOT, hold.y, hold.x))[:4]
    low = sorted(holds, key=lambda hold: (hold.y, hold.x))
    feet = [hold for hold in low if hold.hold_type == HoldType.FOOT][:2]
    hands = [hold for hold in low if hold.hold_type != HoldType.FOOT][:2]
    return feet + hands


def _choose_top_hold(holds: Sequence[Hold]) -> Optional[Hold]:
    top_holds = [hold for hold in holds if hold.y >= 16 and hold.hold_type != HoldType.FOOT]
    if not top_holds:
        return None
    return sorted(top_holds, key=lambda hold: (hold.hold_type != HoldType.JUG, -hold.y, abs(_x_index(hold) - 5)))[0]


def _sample_evenly(holds: Sequence[Hold], count: int) -> List[Hold]:
    if count <= 0 or not holds:
        return []
    if len(holds) <= count:
        return list(holds)
    step = (len(holds) - 1) / max(1, count - 1)
    return [holds[round(index * step)] for index in range(count)]


def _target_grade_mids(starts: List[Hold], pool: List[Hold], top: Hold, target_grade: str) -> List[Hold]:
    if not pool:
        return []
    candidate_pool = sorted(
        pool,
        key=lambda hold: (
            abs(HOLD_DIFFICULTY.get(hold.hold_type, 50.0) - (34 + _grade_number(target_grade) * 5)),
            hold.y,
            abs(_x_index(hold) - 5),
        ),
    )[:10]
    best_mids: List[Hold] = []
    best_score: tuple[float, float, float] | None = None
    max_count = min(7, len(candidate_pool))
    for count in range(3, max_count + 1):
        for combo in combinations(candidate_pool, count):
            mids = sorted(combo, key=lambda hold: (hold.y, _x_index(hold)))
            metrics = _board_metrics(starts + mids + [top], target_grade)
            if not metrics.get("valid_for_climb"):
                continue
            score = (
                abs(float(metrics.get("grade_delta") or 0.0)),
                -float(metrics.get("quality_score") or 0.0),
                abs(float(metrics.get("difficulty_score") or 0.0) - (50 + _grade_number(target_grade) * 2.5)),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_mids = mids
    return best_mids or _sample_evenly(sorted(pool, key=lambda hold: (hold.y, _x_index(hold))), min(5, len(pool)))


def _compose_strategy_holds(board_holds: List[Hold], target_grade: str, strategy: Literal["best_quality", "target_grade", "different_style"]) -> List[Hold]:
    starts = _choose_start_holds(board_holds)
    top = _choose_top_hold(board_holds)
    if not starts or not top:
        return []

    occupied = {hold.id for hold in starts}
    occupied.add(top.id)
    pool = [
        hold
        for hold in board_holds
        if hold.id not in occupied and hold.hold_type != HoldType.FOOT and 4 <= hold.y <= 16
    ]
    target_number = _grade_number(target_grade)
    if strategy == "best_quality":
        mid_count = max(3, min(7, len(pool)))
    elif strategy == "target_grade":
        mid_count = max(3, min(5, 6 - min(target_number, 6) // 3, len(pool)))
    else:
        mid_count = max(3, min(5, len(pool)))

    if strategy == "best_quality":
        mids = _sample_evenly(sorted(pool, key=lambda hold: (hold.y, abs(_x_index(hold) - 5), HOLD_DIFFICULTY.get(hold.hold_type, 50.0))), mid_count)
    elif strategy == "target_grade":
        mids = _target_grade_mids(starts, pool, top, target_grade)
    else:
        left = sorted([hold for hold in pool if _x_index(hold) <= 5], key=lambda hold: (hold.y, _x_index(hold)))
        right = sorted([hold for hold in pool if _x_index(hold) > 5], key=lambda hold: (hold.y, -_x_index(hold)))
        alternating = []
        for index in range(max(len(left), len(right))):
            if index < len(left):
                alternating.append(left[index])
            if index < len(right):
                alternating.append(right[index])
        mids = _sample_evenly(alternating, mid_count)

    route_holds = _dedupe_holds(starts + mids + [top])
    for hold in route_holds:
        if hold.id in {start.id for start in starts}:
            hold.is_start = True
    return route_holds


def _beta_from_holds(holds: Sequence[Hold]) -> List[BetaStep]:
    starts = [hold for hold in holds if hold.is_start]
    hand_cycle = [Limb.LH, Limb.RH]
    foot_cycle = [Limb.LF, Limb.RF]
    steps: List[BetaStep] = []
    for index, hold in enumerate([hold for hold in starts if hold.hold_type != HoldType.FOOT]):
        steps.append(BetaStep(step=0, limb=hand_cycle[index % 2], hold_id=hold.id, intent="Start"))
    for index, hold in enumerate([hold for hold in starts if hold.hold_type == HoldType.FOOT]):
        steps.append(BetaStep(step=0, limb=foot_cycle[index % 2], hold_id=hold.id, intent="Start foot"))

    move_index = 1
    middle = [hold for hold in holds if hold not in starts]
    middle.sort(key=lambda hold: (hold.y, _x_index(hold)))
    for hold in middle:
        is_top = hold.y >= 16 and hold.hold_type != HoldType.FOOT
        steps.append(BetaStep(step=move_index, limb=hand_cycle[move_index % 2], hold_id=hold.id, intent="Top" if is_top else "Move", is_top=is_top))
        move_index += 1
    return steps


def _route_with_board_metadata(route: FinalRoute, request: AIExperimentRequest) -> FinalRoute:
    board = request.board
    return route.model_copy(
        update={
            "board_spec": board.board_spec,
            "difficulty": request.target_difficulty or board.difficulty or "V3",
            "source_type": "ai-generated",
            "visibility": board.visibility,
            "tags": list(dict.fromkeys([*board.tags, "ai-lab"])),
            "owner_id": board.owner_id,
        }
    )


def _candidate_record(label: str, route: FinalRoute, metrics: Dict[str, Any], source: str, target_grade: str) -> Dict[str, Any]:
    return {
        "label": label,
        "label_text": {
            "best_quality": "质量优先",
            "target_grade": "难度匹配",
            "different_style": "风格变化",
        }.get(label, label),
        "route_name": route.route_name,
        "source": source,
        "quality_score": metrics.get("quality_score"),
        "difficulty_score": metrics.get("difficulty_score"),
        "predicted_v_grade": metrics.get("predicted_v_grade"),
        "grade_delta": metrics.get("grade_delta"),
        "target_v_grade": target_grade,
        "risk_score": metrics.get("risk_score"),
        "hold_count": metrics.get("hold_count"),
        "reuse_rate": metrics.get("reuse_rate"),
        "valid_for_climb": metrics.get("valid_for_climb"),
        "notes": metrics.get("algorithm_notes", []),
    }


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
            temperature=0.35,
            timeout=30,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception as exc:
        print(f"LLM enrichment failed, using deterministic fallback: {exc}")
        return None


async def compose_route_from_board(request: AIExperimentRequest) -> AIExperimentResponse:
    target_grade = request.target_difficulty or request.board.difficulty or "V3"
    reference = _standard_reference(target_grade)
    board_holds = _infer_start_flags(request.board.placed_holds)
    source_ids = _hold_ids(request.board.placed_holds)
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    validator = PhysicsValidator()
    raw_candidates: List[Tuple[str, str, List[Hold], List[BetaStep]]] = []

    astar_candidate, report = solver.solve(board_holds, _board_budget(board_holds))
    if astar_candidate:
        raw_candidates.append(("best_quality", "a_star", astar_candidate.placed_holds, astar_candidate.beta_sequence))

    for label in ("best_quality", "target_grade", "different_style"):
        strategy_holds = _compose_strategy_holds([hold.model_copy() for hold in board_holds], target_grade, label)  # type: ignore[arg-type]
        if strategy_holds:
            raw_candidates.append((label, "local_strategy", strategy_holds, _beta_from_holds(strategy_holds)))

    selected: Dict[str, Tuple[FinalRoute, Dict[str, Any], str]] = {}
    seen_signatures: set[str] = set()
    for label, source, holds, beta in raw_candidates:
        signature = _route_signature(holds)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        metrics = _board_metrics(holds, target_grade)
        ok, baseline_message = validator.validate_baseline(holds)
        metrics["valid_for_climb"] = bool(metrics.get("valid_for_climb")) and ok
        metrics["baseline_message"] = baseline_message
        metrics["reuse_rate"] = round(len(_hold_ids(holds) & source_ids) / len(source_ids), 3) if source_ids else 1.0
        metrics["standard_reference"] = reference
        if not metrics["valid_for_climb"]:
            continue
        route_name = {
            "best_quality": "AI Lab 重组：质量优先",
            "target_grade": "AI Lab 重组：难度匹配",
            "different_style": "AI Lab 重组：风格变化",
        }.get(label, "AI Lab 重组路线")
        commentary = (
            f"本地算法从当前岩板中重组路线，质量分 {metrics['quality_score']}，"
            f"预测难度 {metrics.get('predicted_v_grade') or '-'}，复用率 {metrics['reuse_rate'] * 100:.1f}%。"
        )
        route = _route_with_board_metadata(
            FinalRoute(route_name=route_name, setter_commentary=commentary, placed_holds=holds, beta_sequence=beta),
            request,
        )
        score = (
            float(metrics.get("quality_score") or 0.0),
            -abs(int(metrics.get("grade_delta") or 0)),
            -float(metrics.get("risk_score") or 0.0),
            float(metrics.get("reuse_rate") or 0.0),
        )
        current = selected.get(label)
        current_score = (
            float(current[1].get("quality_score") or 0.0),
            -abs(int(current[1].get("grade_delta") or 0)),
            -float(current[1].get("risk_score") or 0.0),
            float(current[1].get("reuse_rate") or 0.0),
        ) if current else None
        if not current or score > current_score:
            selected[label] = (route, metrics, source)

    if not selected:
        board_metrics = _board_metrics(request.board.placed_holds, target_grade)
        return AIExperimentResponse(
            mode="compose_route",
            selected_routes=[],
            failure_suggestion=f"当前岩板无法重组出通过基础验证的路线：{report.get('reason', '本地候选未通过验证')}",
            board=request.board,
            analysis_summary="当前岩板结构不足，AI Lab 未生成可载入候选。",
            metrics=board_metrics,
            applied_constraints=["基础可攀验证", "目标难度匹配", "标准板优质结构参考"],
            algorithm_notes=board_metrics.get("algorithm_notes", []),
        )

    order = ["best_quality", "target_grade", "different_style"]
    final_items = [selected[label] for label in order if label in selected][:3]
    selected_routes = [item[0] for item in final_items]
    candidate_routes = [_candidate_record(order[index], route, metrics, source, target_grade) for index, (route, metrics, source) in enumerate(final_items)]
    metrics = {
        "candidate_count": len(candidate_routes),
        "target_v_grade": target_grade,
        "standard_reference": reference,
        "best_quality_score": max(float(item[1].get("quality_score") or 0.0) for item in final_items),
        "closest_grade_delta": min(abs(int(item[1].get("grade_delta") or 0)) for item in final_items),
    }

    llm_enriched = False
    llm_result = await _llm_json(
        "You are a senior indoor climbing route setter. Only rewrite names/commentary for the provided algorithm-selected routes. Return JSON with optional route_names object and summary.",
        {
            "mode": "compose_route",
            "user_requirements": request.user_requirements,
            "metrics": metrics,
            "candidate_routes": candidate_routes,
        },
    )
    if llm_result:
        llm_enriched = True
        route_names = llm_result.get("route_names") if isinstance(llm_result.get("route_names"), dict) else {}
        for record, route in zip(candidate_routes, selected_routes):
            label = str(record["label"])
            if route_names.get(label):
                route.route_name = str(route_names[label])
            if llm_result.get("summary"):
                route.setter_commentary = f"{route.setter_commentary} {str(llm_result['summary'])}"

    return AIExperimentResponse(
        mode="compose_route",
        selected_routes=selected_routes,
        board=request.board,
        analysis_summary=f"本地算法生成 {len(selected_routes)} 条可攀候选，最接近目标难度偏差 {metrics['closest_grade_delta']} 级。",
        metrics=metrics,
        candidate_routes=candidate_routes,
        applied_constraints=["基础可攀验证", "A* 动作搜索", "标准板优质结构参考", "目标难度偏差排序"],
        algorithm_notes=["候选路线不会覆盖原岩板", "LLM 只用于文案润色，不参与候选排序"],
        llm_enriched=llm_enriched,
    )


def _suggestion(title: str, detail: str, group: Literal["must_fix", "should_fix", "optional"], hold_ids: Optional[List[str]] = None, candidate_route: Optional[FinalRoute] = None) -> RouteReviewSuggestion:
    return RouteReviewSuggestion(title=title, detail=detail, group=group, hold_ids=hold_ids or [], candidate_route=candidate_route)


def _candidate_route_for_fix(board: BoardAsset, target_grade: str, label: str = "target_grade") -> Optional[FinalRoute]:
    holds = _compose_strategy_holds(_infer_start_flags([hold.model_copy() for hold in board.placed_holds]), target_grade, label)  # type: ignore[arg-type]
    if not holds:
        return None
    return FinalRoute(
        route_name="AI Lab 修复候选",
        setter_commentary="根据当前岩板自动生成的候选版本，用于预览修复方向，不会覆盖原岩板。",
        source_type="ai-generated",
        visibility=board.visibility,
        tags=list(dict.fromkeys([*board.tags, "ai-lab-review"])),
        difficulty=target_grade,
        board_spec=board.board_spec,
        placed_holds=holds,
        beta_sequence=_beta_from_holds(holds),
    )


def _deterministic_review(board: BoardAsset, target_grade: str) -> tuple[List[RouteReviewViolation], List[RouteReviewSuggestion], str, Dict[str, Any]]:
    validator = PhysicsValidator()
    metrics = _board_metrics(board.placed_holds, target_grade)
    violations: List[RouteReviewViolation] = []
    suggestions: List[RouteReviewSuggestion] = []
    candidate_fix = _candidate_route_for_fix(board, target_grade)

    failure_messages = {
        "start_hand_count_lt_2": "明确手起点少于 2 个",
        "no_foothold": "缺少可用脚点",
        "end_count_lt_1": "Y16-Y18 缺少非脚点终点",
        "hold_count_out_of_range": "岩点总数不在合理范围",
        "vertical_gap_gt_5": "纵向断档超过 5",
        "ladder_x_span_too_narrow": "横向跨度过窄，接近梯子线",
    }
    for code in metrics.get("hard_failures", []):
        violations.append(RouteReviewViolation(code=code, message=failure_messages.get(code, code)))
        group: Literal["must_fix", "should_fix", "optional"] = "must_fix" if code in {"start_hand_count_lt_2", "end_count_lt_1", "vertical_gap_gt_5"} else "should_fix"
        detail = "建议使用 AI Lab 重组生成候选版本；结构性问题不要只做文字标注。"
        if code == "start_hand_count_lt_2":
            detail = "补足两个明确手起点，再派生或保留低位脚点。"
        elif code == "no_foothold":
            detail = "补充低位脚点，避免起步完全依赖拉力。"
        elif code == "vertical_gap_gt_5":
            detail = "在断档区间增加中段点，或直接重组路线。"
        suggestions.append(_suggestion(failure_messages.get(code, code), detail, group, candidate_route=candidate_fix if group == "must_fix" else None))

    hold_ids = _hold_ids(board.placed_holds)
    missing_beta_targets = [step.hold_id for step in board.beta_sequence if step.hold_id not in hold_ids]
    if missing_beta_targets:
        unique_missing = sorted(set(missing_beta_targets))
        violations.append(RouteReviewViolation(code="missing_beta_hold", message=f"Beta 序列引用了不存在的岩点：{', '.join(unique_missing)}", hold_ids=unique_missing))
        suggestions.append(_suggestion("修正 Beta 引用", "删除失效动作，或在对应坐标重新放置岩点后再保存。", "must_fix", unique_missing))

    if board.beta_sequence:
        ok, message = validator.validate_beta_balance(board.beta_sequence, board.placed_holds)
        if not ok:
            violations.append(RouteReviewViolation(code="beta_balance", message=message))
            suggestions.append(_suggestion("降低身体横向扭转", "优先调整脚点高度和左右分布，避免连续高脚或手脚中轴偏移过大。", "should_fix"))

        consecutive_hand_moves = 0
        max_consecutive_hand_moves = 0
        for step in board.beta_sequence:
            if step.limb in {Limb.LH, Limb.RH}:
                consecutive_hand_moves += 1
            else:
                consecutive_hand_moves = 0
            max_consecutive_hand_moves = max(max_consecutive_hand_moves, consecutive_hand_moves)
        metrics["max_consecutive_hand_moves"] = max_consecutive_hand_moves
        if max_consecutive_hand_moves >= 4:
            suggestions.append(_suggestion("补充脚步推进", "Beta 中存在连续手动，建议在 crux 前后安排脚步移动，降低纯拉力段。", "should_fix"))
    else:
        suggestions.append(_suggestion("补充 Beta 序列", "当前岩板没有动作序列。先标记起步、核心移动和完攀动作，审查会更准确。", "optional"))

    if metrics.get("difficulty_score") is not None and abs(int(metrics.get("grade_delta") or 0)) >= 2:
        suggestions.append(
            _suggestion(
                "复核标称难度",
                f"系统预测 {metrics.get('predicted_v_grade')}，与目标 {target_grade} 相差 {metrics.get('grade_delta')} 级。",
                "should_fix",
            )
        )

    if metrics.get("foot_count", 0) < 2:
        suggestions.append(_suggestion("增加脚点支撑", "脚点数量偏少，容易让线路变成纯上肢拉力。", "should_fix", candidate_route=candidate_fix))

    if not suggestions:
        suggestions.append(_suggestion("保留当前结构", "当前线路没有明显硬伤，可以优先做风格微调或补充更完整 Beta。", "optional"))

    must_fix_count = sum(1 for item in suggestions if item.group == "must_fix")
    should_fix_count = sum(1 for item in suggestions if item.group == "should_fix")
    if must_fix_count:
        risk_level = "high"
    elif should_fix_count or violations:
        risk_level = "medium"
    else:
        risk_level = "low"
    return violations, suggestions, risk_level, metrics


async def review_board_route(request: AIExperimentRequest) -> AIExperimentResponse:
    target_grade = request.target_difficulty or request.board.difficulty or "V3"
    violations, suggestions, risk_level, metrics = _deterministic_review(request.board, target_grade)
    summary = "当前路线通过基础可攀检查。" if risk_level == "low" else "当前路线存在需要处理的结构或动作风险。"

    llm_enriched = False
    llm_result = await _llm_json(
        "You are a senior indoor climbing route setter. Only rewrite review_summary using the provided algorithmic findings. Return JSON with review_summary only.",
        {
            "mode": "review_route",
            "user_requirements": request.user_requirements,
            "risk_level": risk_level,
            "metrics": metrics,
            "violations": [violation.model_dump(mode="json") for violation in violations],
            "suggestions": [suggestion.model_dump(mode="json", exclude={"candidate_route"}) for suggestion in suggestions],
        },
    )
    if llm_result and llm_result.get("review_summary"):
        llm_enriched = True
        summary = str(llm_result["review_summary"])

    grouped_counts = Counter(suggestion.group for suggestion in suggestions)
    return AIExperimentResponse(
        mode="review_route",
        review_summary=summary,
        violations=violations,
        suggestions=suggestions,
        risk_level=risk_level,
        board=request.board,
        analysis_summary=f"{SUGGESTION_GROUP_LABELS['must_fix']} {grouped_counts.get('must_fix', 0)} 条，{SUGGESTION_GROUP_LABELS['should_fix']} {grouped_counts.get('should_fix', 0)} 条，{SUGGESTION_GROUP_LABELS['optional']} {grouped_counts.get('optional', 0)} 条。",
        metrics=metrics,
        applied_constraints=["起终点规范", "岩点数量", "纵向断档", "梯子线", "Beta 引用", "动作平衡"],
        algorithm_notes=metrics.get("algorithm_notes", []),
        llm_enriched=llm_enriched,
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
