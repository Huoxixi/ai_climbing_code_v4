"""
Algorithm-backed AI experiment modes for board-based compose/review flows.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from itertools import combinations
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from openai import AsyncOpenAI

from core.a_star_solver import AStarSolver
from core.board_readiness import apply_board_readiness
from core.config import settings
from core.models import (
    AIExperimentRequest,
    AIExperimentResponse,
    AIExperimentCandidateTrace,
    AIExperimentCheck,
    AIExperimentExplanation,
    AIExperimentScoreItem,
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
from core.moonboard_grading import (
    DEFAULT_FONT_GRADE,
    FONT_GRADES,
    assess_equivalent_grade,
    grade_number,
    hold_transfer_demand,
    load_grade_model,
    normalize_font_grade,
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
SUGGESTION_GROUP_LABELS = {
    "must_fix": "必须修",
    "should_fix": "建议修",
    "optional": "可选优化",
}
GENERATION_GOAL_LABELS = {
    "quality_first": "质量优先",
    "grade_match": "目标难度优先",
    "style_variation": "动作风格多样",
}
REVIEW_FOCUS_LABELS = {
    "overall": "综合检查",
    "footholds": "脚点检查",
    "difficulty": "难度检查",
    "beta_sequence": "动作顺序检查",
}
CHINESE_CHARACTER_PATTERN = re.compile(r"[\u4e00-\u9fff]")
LATIN_CHARACTER_PATTERN = re.compile(r"[A-Za-z]")
ALLOWED_TECHNICAL_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:AI|Beta|LH|RH|LF|RF)\b|\b(?:6B\+?|6C\+?|7A\+?|7B\+?|7C\+?|8A\+?|8B\+?)\b|\b[A-Z]{1,2}\d{1,2}\b"
)
EXPLANATION_SCHEMA_VERSION = "ai-explanation-v2"
RULESET_VERSION = "ai-lab-rules-v2"
REFERENCE_NOTE = "同难度优质标准线路的平均结构仅用于结果对照，当前不参与候选评分或排序。"
STRATEGY_LABELS = {
    "best_quality": "质量优先",
    "target_grade": "难度匹配",
    "different_style": "风格变化",
}


def _plain_chinese_text(value: Any, *, allow_technical_tokens: bool = True) -> Optional[str]:
    """Accept only customer-facing Chinese copy; reject accidental English replies."""
    text = str(value or "").strip()
    if not text or not CHINESE_CHARACTER_PATTERN.search(text):
        return None
    text_to_check = ALLOWED_TECHNICAL_TOKEN_PATTERN.sub("", text) if allow_technical_tokens else text
    if LATIN_CHARACTER_PATTERN.search(text_to_check):
        return None
    return text


def _hold_ids(holds: Sequence[Hold]) -> set[str]:
    return {hold.id for hold in holds}


def _x_index(hold: Hold) -> int:
    return ord(hold.x.upper()) - ord("A")


def _grade_number(grade: str | None) -> int:
    return grade_number(grade or DEFAULT_FONT_GRADE)


def _grade_from_score(score: float) -> str:
    return FONT_GRADES[max(0, min(len(FONT_GRADES) - 1, round(score / 100 * (len(FONT_GRADES) - 1))))]


def _route_signature(holds: Sequence[Hold]) -> str:
    return "|".join(sorted(hold.id for hold in holds))


def _input_fingerprint(request: AIExperimentRequest, target_grade: str) -> str:
    payload = {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "mode": request.mode,
        "generation_goal": request.generation_goal,
        "review_focus": request.review_focus,
        "target_grade": target_grade,
        "climber_height_cm": request.climber_height_cm,
        "climber_span_cm": request.climber_span_cm,
        "board_spec": request.board.board_spec.model_dump(mode="json") if request.board.board_spec else None,
        "holds": [
            hold.model_dump(mode="json")
            for hold in sorted(request.board.placed_holds, key=lambda item: item.id)
        ],
        "beta": [
            step.model_dump(mode="json")
            for step in sorted(
                request.board.beta_sequence,
                key=lambda item: (item.step, item.limb.value, item.hold_id),
            )
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _score_breakdown(metrics: Dict[str, Any], holds: Sequence[Hold]) -> List[AIExperimentScoreItem]:
    hold_count = int(metrics.get("hold_count") or 0)
    x_span = int(metrics.get("x_span") or 0)
    y_span = int(metrics.get("y_span") or 0)
    max_vertical_gap = int(metrics.get("max_vertical_gap") or 0)
    start_hand_count = int(metrics.get("start_hand_count") or 0)
    top_count = int(metrics.get("top_count") or 0)
    foot_count = int(metrics.get("foot_count") or 0)
    start_ids = [hold.id for hold in holds if hold.is_start and hold.hold_type != HoldType.FOOT]
    top_ids = [hold.id for hold in holds if hold.y >= 16 and hold.hold_type != HoldType.FOOT]
    foot_ids = [hold.id for hold in holds if hold.hold_type == HoldType.FOOT]

    raw_scores = [
        18.0 * max(0.0, 1.0 - abs(hold_count - 8) / 6.0),
        20.0 * min(1.0, max(0, x_span - 2) / 6.0),
        18.0 * min(1.0, y_span / 16.0),
        20.0 * max(0.0, 1.0 - max(0, max_vertical_gap - 3) / 4.0),
        16.0 if start_hand_count and top_count else 6.0,
        8.0 * min(1.0, max(1, foot_count) / 3.0),
    ]
    rounded = [round(value, 2) for value in raw_scores]
    target_total = float(metrics.get("quality_score") or 0.0)
    rounded[-1] = round(rounded[-1] + target_total - sum(rounded), 2)

    definitions = [
        ("hold_count", "岩点数量", 18.0, f"{hold_count} 个", "6–14 个，8 个得分最高", "岩点数量接近 8 个时得分更高。", []),
        ("horizontal_span", "横向展开", 20.0, f"{x_span} 列", "至少 3 列，8 列及以上满分", "横向展开过窄容易形成梯子式线路。", []),
        ("vertical_coverage", "纵向覆盖", 18.0, f"{y_span} 排", "覆盖 16 排得满分", "线路覆盖高度越完整，越接近完整上攀路径。", []),
        ("vertical_continuity", "纵向连续性", 20.0, f"最大断档 {max_vertical_gap} 排", "3 排以内满分，超过 5 排失败", "相邻岩点层级断档越小，动作衔接越连续。", []),
        ("start_finish", "起点与终点", 16.0, f"{start_hand_count} 个手起点，{top_count} 个终点", "至少 1 个手起点和 1 个高位终点", "起点和终点都明确时获得完整分值。", start_ids + top_ids),
        ("foot_support", "脚点支撑", 8.0, f"{foot_count} 个脚点", "3 个脚点得满分", "脚点越充足，越能避免线路过度依赖上肢拉力。", foot_ids),
    ]
    return [
        AIExperimentScoreItem(
            id=item_id,
            label=label,
            score=score,
            max_score=max_score,
            observed=observed,
            threshold=threshold,
            explanation=explanation,
            related_hold_ids=related_hold_ids,
        )
        for score, (item_id, label, max_score, observed, threshold, explanation, related_hold_ids) in zip(rounded, definitions)
    ]


def _rule_checks(
    metrics: Dict[str, Any],
    holds: Sequence[Hold],
    beta_sequence: Sequence[BetaStep],
    violations: Sequence[RouteReviewViolation] = (),
    *,
    review_mode: bool = False,
    review_focus: str = "overall",
) -> List[AIExperimentCheck]:
    violation_map = {item.code: item for item in violations}
    failure_codes = set(metrics.get("hard_failures") or [])
    hold_ids = _hold_ids(holds)
    start_hand_ids = [hold.id for hold in holds if hold.is_start and hold.hold_type != HoldType.FOOT]
    foot_ids = [hold.id for hold in holds if hold.hold_type == HoldType.FOOT]
    top_ids = [hold.id for hold in holds if hold.y >= 16 and hold.hold_type != HoldType.FOOT]
    missing_beta_ids = sorted({step.hold_id for step in beta_sequence if step.hold_id not in hold_ids})

    def status_for(code: str) -> Literal["pass", "fail"]:
        return "fail" if code in failure_codes else "pass"

    checks = [
        AIExperimentCheck(
            id="board_spec",
            label="岩板规格",
            status="pass",
            observed="11×18，40°",
            threshold="仅支持 11×18，40°",
            explanation="当前岩板处于已校准的 AI 实验适用范围。",
        ),
        AIExperimentCheck(
            id="hold_count",
            label="岩点数量",
            status=status_for("hold_count_out_of_range"),
            observed=f"{int(metrics.get('hold_count') or 0)} 个",
            threshold="6–14 个",
            explanation="数量超出范围时，路线结构不进入有效候选。",
        ),
        AIExperimentCheck(
            id="start_hands",
            label="手起点",
            status=status_for("start_hand_count_lt_1"),
            observed=f"{int(metrics.get('start_hand_count') or 0)} 个",
            threshold="至少 1 个",
            explanation="单手起点可以按双手匹配处理，但必须有明确的低位手起点。",
            related_hold_ids=start_hand_ids,
        ),
        AIExperimentCheck(
            id="foot_support",
            label="脚点支撑",
            status="fail" if "no_foothold" in failure_codes else ("warning" if int(metrics.get("foot_count") or 0) < 2 else "pass"),
            observed=f"{int(metrics.get('foot_count') or 0)} 个",
            threshold="至少 1 个，建议 2 个以上",
            explanation="脚点不足会增加纯上肢拉力和起步不稳定风险。",
            related_hold_ids=foot_ids,
        ),
        AIExperimentCheck(
            id="top_hold",
            label="高位终点",
            status=status_for("end_count_lt_1"),
            observed=f"{int(metrics.get('top_count') or 0)} 个",
            threshold="Y16–Y18 至少 1 个非脚点",
            explanation="终点必须位于最后三排，并且能够作为手部完攀动作。",
            related_hold_ids=top_ids,
        ),
        AIExperimentCheck(
            id="vertical_gap",
            label="纵向连续性",
            status=status_for("vertical_gap_gt_5"),
            observed=f"最大断档 {int(metrics.get('max_vertical_gap') or 0)} 排",
            threshold="不超过 5 排",
            explanation="过大的纵向断档会导致动作无法连续连接。",
        ),
        AIExperimentCheck(
            id="horizontal_span",
            label="横向展开",
            status=status_for("ladder_x_span_too_narrow"),
            observed=f"{int(metrics.get('x_span') or 0)} 列",
            threshold="至少 3 列",
            explanation="横向跨度过窄时，路线更接近单一直上梯子线。",
        ),
    ]

    action_checks_enabled = review_focus in {"overall", "footholds", "beta_sequence"}
    hand_sequence_check_enabled = review_focus in {"overall", "beta_sequence"}
    difficulty_check_enabled = review_focus in {"overall", "difficulty"}

    if review_mode and not action_checks_enabled:
        beta_reference_status: Literal["pass", "warning", "fail", "not_run"] = "not_run"
        beta_reference_observed = f"当前重点：{REVIEW_FOCUS_LABELS.get(review_focus, review_focus)}"
        beta_reference_explanation = "本次专项审核不执行动作引用检查；切换到综合检查或动作顺序检查可执行。"
    elif not beta_sequence:
        beta_reference_status: Literal["pass", "warning", "fail", "not_run"] = "not_run"
        beta_reference_observed = "未设置 Beta"
        beta_reference_explanation = "没有动作序列，因此不能检查动作引用。"
    elif missing_beta_ids:
        beta_reference_status = "fail"
        beta_reference_observed = f"缺失 {len(missing_beta_ids)} 个岩点"
        beta_reference_explanation = "Beta 引用了当前岩板中不存在的岩点。"
    else:
        beta_reference_status = "pass"
        beta_reference_observed = f"{len(beta_sequence)} 个动作均可定位"
        beta_reference_explanation = "每个动作都能对应到当前岩板岩点。"
    checks.append(
        AIExperimentCheck(
            id="beta_references",
            label="Beta 岩点引用",
            status=beta_reference_status,
            observed=beta_reference_observed,
            threshold="每个动作都引用现有岩点",
            explanation=beta_reference_explanation,
            related_hold_ids=missing_beta_ids,
        )
    )

    if review_mode and not action_checks_enabled:
        balance_status: Literal["pass", "warning", "fail", "not_run"] = "not_run"
        balance_observed = f"当前重点：{REVIEW_FOCUS_LABELS.get(review_focus, review_focus)}"
        balance_explanation = "本次专项审核不执行身体平衡检查。"
    elif not beta_sequence or missing_beta_ids:
        balance_status: Literal["pass", "warning", "fail", "not_run"] = "not_run"
        balance_observed = "未执行"
        balance_explanation = "Beta 不完整，不能给出完整身体平衡结论。"
    elif not review_mode:
        balance_status = "not_run"
        balance_observed = "候选生成阶段"
        balance_explanation = "候选生成只验证基本可攀性，完整身体平衡需要进入审核模式。"
    elif "beta_balance" in violation_map:
        balance_status = "fail"
        balance_observed = "未通过"
        balance_explanation = violation_map["beta_balance"].message
    else:
        balance_status = "pass"
        balance_observed = "通过"
        balance_explanation = "动作顺序已通过当前身体平衡规则检查。"
    checks.append(
        AIExperimentCheck(
            id="beta_balance",
            label="Beta 身体平衡",
            status=balance_status,
            observed=balance_observed,
            threshold="动作引用完整且平衡检查通过",
            explanation=balance_explanation,
            related_hold_ids=list((metrics.get("beta_balance_evidence") or {}).get("related_hold_ids") or []),
        )
    )

    max_consecutive_hand_moves = metrics.get("max_consecutive_hand_moves")
    if not review_mode or not hand_sequence_check_enabled or max_consecutive_hand_moves is None:
        hand_sequence_status: Literal["pass", "warning", "fail", "not_run"] = "not_run"
        hand_sequence_observed = "未执行"
        hand_sequence_explanation = "需要完整 Beta，并选择综合、脚点或动作顺序重点后才能检查。"
    else:
        hand_sequence_status = "warning" if int(max_consecutive_hand_moves) >= 4 else "pass"
        hand_sequence_observed = f"最多连续 {int(max_consecutive_hand_moves)} 次手部动作"
        hand_sequence_explanation = "连续手部动作过多时，线路可能缺少脚步推进并增加纯拉力负担。"
    checks.append(
        AIExperimentCheck(
            id="hand_move_sequence",
            label="连续手部动作",
            status=hand_sequence_status,
            observed=hand_sequence_observed,
            threshold="少于 4 次连续手部动作",
            explanation=hand_sequence_explanation,
            related_hold_ids=list(metrics.get("consecutive_hand_hold_ids") or []),
        )
    )

    grade_delta = metrics.get("grade_delta")
    grade_status: Literal["pass", "warning", "fail", "not_run"] = (
        "not_run"
        if grade_delta is None or (review_mode and not difficulty_check_enabled)
        else ("warning" if abs(int(grade_delta)) >= 2 else "pass")
    )
    grade_observed = (
        f"当前重点：{REVIEW_FOCUS_LABELS.get(review_focus, review_focus)}"
        if review_mode and not difficulty_check_enabled
        else f"预测 {metrics.get('predicted_grade') or '无结果'}，偏差 {grade_delta if grade_delta is not None else '-'} 级"
    )
    checks.append(
        AIExperimentCheck(
            id="difficulty_match",
            label="目标难度匹配",
            status=grade_status,
            observed=grade_observed,
            threshold="与目标相差少于 2 级",
            explanation="MoonBoard 等效难度来自固定版本模型，结果需结合可信度和校准状态理解。",
        )
    )
    return checks


def _uncertainties(metrics: Dict[str, Any]) -> List[str]:
    items = [
        "难度估算当前没有使用完整且经复核的 Beta，动作顺序可信度不会计入等级结论。"
        if "Beta 不完整" in str(item)
        else str(item)
        for item in (metrics.get("difficulty_reasons") or [])
    ]
    if metrics.get("beta_evaluation_status") == "incomplete":
        items.append("Beta 缺失或引用不完整，本次不能给出动作结论。")
    if metrics.get("movement_validation_status") == "not_run":
        items.append("候选 Beta 是便于讨论的动作草案，尚未执行完整身体平衡检查。")
    if metrics.get("risk_assessment_status") == "partial":
        items.append("当前只计算结构风险，未检查的动作风险不能视为安全。")
    if metrics.get("calibration_status") != "ready":
        items.append("当前难度模型仍处于校准中，不能作为真人终审结论。")
    if metrics.get("confidence_tier") == "low":
        items.append("当前等效难度为低可信结果。")
    return list(dict.fromkeys(item for item in items if item))


def _risk_breakdown(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    failure_labels = {
        "start_hand_count_lt_1": "缺少明确手起点",
        "no_foothold": "没有可用脚点",
        "end_count_lt_1": "缺少高位终点",
        "hold_count_out_of_range": "岩点数量超出范围",
        "vertical_gap_gt_5": "纵向断档超过 5 排",
        "ladder_x_span_too_narrow": "横向展开过窄",
    }
    items: List[Dict[str, Any]] = [
        {
            "id": f"hard_failure:{code}",
            "label": failure_labels.get(code, code),
            "points": 22.0,
            "explanation": "基本可攀性硬性条件未通过。",
        }
        for code in metrics.get("hard_failures", [])
    ]
    if int(metrics.get("max_vertical_gap") or 0) > 4:
        items.append({"id": "large_vertical_gap", "label": "纵向衔接紧张", "points": 12.0, "explanation": "最大纵向断档超过 4 排。"})
    if int(metrics.get("foot_count") or 0) < 2:
        items.append({"id": "limited_footholds", "label": "脚点不足", "points": 10.0, "explanation": "少于 2 个脚点，纯上肢负担可能增加。"})
    grade_delta = abs(int(metrics.get("grade_delta") or 0))
    if grade_delta and metrics.get("difficulty_check_enabled", True):
        items.append(
            {
                "id": "grade_delta",
                "label": "目标难度偏差",
                "points": float(min(20, grade_delta * 5)),
                "explanation": f"预测难度与目标相差 {grade_delta} 级，每级计 5 分，上限 20 分。",
            }
        )
    if float(metrics.get("beta_balance_risk_points") or 0):
        items.append(
            {
                "id": "beta_balance",
                "label": "Beta 身体平衡未通过",
                "points": float(metrics["beta_balance_risk_points"]),
                "explanation": str(metrics.get("beta_balance_message") or "动作顺序未通过身体平衡检查。"),
            }
        )
    if float(metrics.get("hand_sequence_risk_points") or 0):
        items.append(
            {
                "id": "hand_move_sequence",
                "label": "连续手部动作偏多",
                "points": float(metrics["hand_sequence_risk_points"]),
                "explanation": f"最多连续 {int(metrics.get('max_consecutive_hand_moves') or 0)} 次手部动作。",
            }
        )
    if float(metrics.get("beta_reference_risk_points") or 0):
        items.append(
            {
                "id": "beta_references",
                "label": "Beta 引用失效",
                "points": float(metrics["beta_reference_risk_points"]),
                "explanation": "动作序列引用了当前岩板中不存在的岩点。",
            }
        )
    raw_total = sum(float(item["points"]) for item in items)
    final_total = float(metrics.get("risk_score") or 0.0)
    if raw_total > final_total:
        items.append(
            {
                "id": "risk_cap",
                "label": "风险分上限",
                "points": round(final_total - raw_total, 2),
                "explanation": "总风险分最高记为 100。",
            }
        )
    return items


def _explanation(
    request: AIExperimentRequest,
    target_grade: str,
    metrics: Dict[str, Any],
    holds: Sequence[Hold],
    beta_sequence: Sequence[BetaStep],
    *,
    candidate_trace: Sequence[AIExperimentCandidateTrace] = (),
    violations: Sequence[RouteReviewViolation] = (),
    llm_enriched: bool = False,
    review_mode: bool = False,
) -> AIExperimentExplanation:
    model_version = str(load_grade_model().get("version") or "unknown")
    return AIExperimentExplanation(
        schema_version=EXPLANATION_SCHEMA_VERSION,
        decision_sources=[
            {"name": "候选与规则判断", "source": "本地确定性规则", "role": "生成候选、检查结构并决定排序"},
            {"name": "等效难度", "source": f"固定难度模型 {model_version}", "role": "根据坐标结构和岩点负荷估算 Font 等级"},
            {
                "name": "中文说明",
                "source": "大模型润色" if llm_enriched else "本地中文模板",
                "role": "只调整名称和说明，不改变评分、风险、难度或候选顺序",
            },
        ],
        input_summary={
            "board_name": request.board.route_name or "未命名岩板",
            "mode": request.mode,
            "target_grade": target_grade,
            "generation_goal": GENERATION_GOAL_LABELS[request.generation_goal],
            "review_focus": REVIEW_FOCUS_LABELS[request.review_focus],
            "hold_count": len(request.board.placed_holds),
            "beta_count": len(request.board.beta_sequence),
            "beta_complete": (
                metrics.get("review_scope") == "full_beta"
                if review_mode
                else bool(beta_sequence) and metrics.get("movement_validation_status") != "not_run"
            ),
        },
        input_fingerprint=_input_fingerprint(request, target_grade),
        score_breakdown=_score_breakdown(metrics, holds),
        risk_breakdown=_risk_breakdown(metrics),
        checks=_rule_checks(
            metrics,
            holds,
            beta_sequence,
            violations,
            review_mode=review_mode,
            review_focus=request.review_focus,
        ),
        candidate_trace=list(candidate_trace),
        uncertainties=_uncertainties(metrics),
        versions={
            "ruleset": RULESET_VERSION,
            "grade_model": model_version,
            "explanation_schema": EXPLANATION_SCHEMA_VERSION,
        },
        reference_note=REFERENCE_NOTE if request.mode == "compose_route" else None,
    )


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

def _board_metrics(holds: Sequence[Hold], target_grade: str = DEFAULT_FONT_GRADE) -> Dict[str, Any]:
    ordered = _dedupe_holds(holds)
    if not ordered:
        return {
            "valid_for_climb": False,
            "hard_failures": ["empty_route"],
            "review_reasons": ["路线为空"],
            "hold_count": 0,
            "quality_score": 0.0,
            "difficulty_score": None,
            "predicted_grade": None,
            "confidence_tier": "low",
            "calibration_status": "uncalibrated",
            "difficulty_reasons": ["路线为空，无法估算难度"],
            "grade_delta": None,
            "risk_score": 100.0,
            "structural_risk_score": 100.0,
            "risk_scope": "structure_only",
            "risk_assessment_status": "partial",
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
    if len(start_hands) < 1:
        failures.append("start_hand_count_lt_1")
        reasons.append("缺少明确手起点")
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
    start_finish_score = 16.0 if start_hands and top_holds else 6.0
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
    else:
        difficulty_score = None

    end_hold = max(top_holds, key=lambda hold: hold.y, default=None)
    start_ids = {hold.id for hold in start_holds}
    end_ids = {end_hold.id} if end_hold else set()
    from core.simulation import get_hold_profiles

    transfer_profiles = {profile.variant_id: profile for profile in get_hold_profiles()}
    assessment = assess_equivalent_grade(
        {
            "start": [hold.id for hold in start_holds],
            "mid": [hold.id for hold in ordered if hold.id not in start_ids | end_ids],
            "end": list(end_ids),
        },
        board_spec={"columns": 11, "rows": 18, "angle_degrees": 40},
        hold_demands=[
            hold_transfer_demand(hold.hold_type, hold.rotation, transfer_profiles.get(hold.variant))
            for hold in ordered
        ],
        hold_confidences=[
            float(getattr(transfer_profiles.get(hold.variant), "confidence", 0.65))
            for hold in ordered
        ],
        beta_complete=False,
    )
    predicted_grade = assessment["predicted_grade"]
    grade_delta_value = (
        int(round(float(assessment["grade_score"]))) - grade_number(target_grade)
        if predicted_grade and assessment.get("grade_score") is not None
        else None
    )

    risk_score = len(failures) * 22.0
    risk_score += 12.0 if max_vertical_gap > 4 else 0.0
    risk_score += 10.0 if len(foot_holds) < 2 else 0.0
    risk_score += min(20.0, abs(grade_delta_value or 0) * 5.0)
    risk_score = round(min(100.0, risk_score), 2)

    notes: List[str] = []
    if x_span >= 7:
        notes.append("横向跨度较大")
    if max_vertical_gap >= 5:
        notes.append("存在纵向断档")
    if foot_holds:
        notes.append(f"包含 {len(foot_holds)} 个脚点")
    if difficulty_score is not None and abs(grade_delta_value or 0) >= 2:
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
        "predicted_grade": predicted_grade,
        "target_grade": target_grade,
        "grade_delta": grade_delta_value,
        "difficulty_confidence": assessment["difficulty_confidence"],
        "confidence_tier": assessment["confidence_tier"],
        "calibration_status": assessment["calibration_status"],
        "difficulty_reasons": assessment.get("difficulty_reasons", []),
        "risk_score": risk_score,
        "structural_risk_score": risk_score,
        "risk_scope": "structure_only",
        "risk_assessment_status": "partial",
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
        # A style-variation candidate must actually change the layout. Keeping
        # every middle hold would merely repackage the source board.
        mid_count = min(3, len(pool))

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
            "difficulty": request.target_difficulty or board.difficulty or DEFAULT_FONT_GRADE,
            "source_type": "ai-generated",
            "visibility": board.visibility,
            "tags": list(dict.fromkeys([*board.tags, "ai-lab"])),
            "owner_id": board.owner_id,
        }
    )


def _metric_snapshot(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "structural_quality": metrics.get("quality_score"),
        "predicted_grade": metrics.get("predicted_grade"),
        "grade_delta": metrics.get("grade_delta"),
        "structural_risk": metrics.get("structural_risk_score", metrics.get("risk_score")),
        "hold_count": metrics.get("hold_count"),
        "horizontal_span": metrics.get("x_span"),
        "vertical_span": metrics.get("y_span"),
        "max_vertical_gap": metrics.get("max_vertical_gap"),
        "foot_count": metrics.get("foot_count"),
    }


def _candidate_change_evidence(
    source_holds: Sequence[Hold],
    candidate_holds: Sequence[Hold],
    strategy: str,
) -> Dict[str, Any]:
    source_by_id = {hold.id: hold for hold in source_holds}
    candidate_by_id = {hold.id: hold for hold in candidate_holds}
    retained = sorted(source_by_id.keys() & candidate_by_id.keys())
    removed = sorted(source_by_id.keys() - candidate_by_id.keys())
    added = sorted(candidate_by_id.keys() - source_by_id.keys())
    strategy_reason = {
        "best_quality": "保留纵向分布较均匀的岩点，使结构分、跨度和连续性更稳定。",
        "target_grade": "保留更接近目标难度负荷的中段岩点，并优先缩小等级偏差。",
        "different_style": "减少中段岩点并交替选择左右区域，使草案与原线路形成可见差异。",
    }.get(strategy, "根据固定组合规则筛选岩点。")
    return {
        "retained_hold_ids": retained,
        "removed_hold_ids": removed,
        "added_hold_ids": added,
        "strategy_reason": strategy_reason,
        "hold_decisions": [
            {
                "hold_id": hold_id,
                "decision": "removed",
                "reason_code": f"{strategy}:not_selected",
                "reason": strategy_reason,
            }
            for hold_id in removed
        ],
    }


def _candidate_record(
    label: str,
    route: FinalRoute,
    metrics: Dict[str, Any],
    source: str,
    target_grade: str,
    *,
    source_holds: Sequence[Hold],
    source_metrics: Dict[str, Any],
    selection_mode: Literal["requested_goal", "fallback", "alternative"],
    fallback_reason: str = "",
) -> Dict[str, Any]:
    reuse_rate = float(metrics.get("reuse_rate") or 0)
    reuse_tier = "optimal" if reuse_rate >= 0.7 else ("pass" if reuse_rate >= 0.4 else "large_change")
    reuse_tier_label = {
        "optimal": "最优复用",
        "pass": "通过复用标准",
        "large_change": "较大改动",
    }[reuse_tier]
    selection_intro = {
        "requested_goal": f"与所选“{STRATEGY_LABELS.get(label, label)}”策略一致。",
        "fallback": f"请求目标没有可展示候选，系统按固定顺序回退到“{STRATEGY_LABELS.get(label, label)}”。{fallback_reason}",
        "alternative": "作为第二个不同且通过结构检查的备选草案。",
    }[selection_mode]
    return {
        "label": label,
        "label_text": STRATEGY_LABELS.get(label, label),
        "route_name": route.route_name,
        "source": source,
        "quality_score": metrics.get("quality_score"),
        "difficulty_score": metrics.get("difficulty_score"),
        "predicted_grade": metrics.get("predicted_grade"),
        "grade_delta": metrics.get("grade_delta"),
        "target_grade": target_grade,
        "difficulty_confidence": metrics.get("difficulty_confidence"),
        "confidence_tier": metrics.get("confidence_tier"),
        "calibration_status": metrics.get("calibration_status"),
        "risk_score": metrics.get("risk_score"),
        "structural_risk_score": metrics.get("structural_risk_score", metrics.get("risk_score")),
        "risk_scope": "structure_only",
        "risk_assessment_status": "partial",
        "movement_validation_status": "not_run",
        "hold_count": metrics.get("hold_count"),
        "reuse_rate": metrics.get("reuse_rate"),
        "reuse_tier": reuse_tier,
        "reuse_tier_label": reuse_tier_label,
        "valid_for_climb": metrics.get("valid_for_climb"),
        "notes": metrics.get("algorithm_notes", []),
        "difficulty_reasons": metrics.get("difficulty_reasons", []),
        "score_breakdown": [item.model_dump(mode="json") for item in _score_breakdown(metrics, route.placed_holds)],
        "checks": [
            item.model_dump(mode="json")
            for item in _rule_checks(metrics, route.placed_holds, route.beta_sequence)
        ],
        "selection_mode": selection_mode,
        "selection_basis": [
            selection_intro,
            f"结构质量 {metrics.get('quality_score')} / 100。",
            f"预测 {metrics.get('predicted_grade')}，与目标 {target_grade} 相差 {abs(int(metrics.get('grade_delta') or 0))} 级。",
            f"复用原岩点 {reuse_rate * 100:.0f}%，属于“{reuse_tier_label}”。",
            "动作草案尚未执行完整身体平衡检查，不能据此判断最终安全性或流畅性。",
        ],
        "change_evidence": _candidate_change_evidence(source_holds, route.placed_holds, label),
        "before_after": {
            "before": _metric_snapshot(source_metrics),
            "after": _metric_snapshot(metrics),
        },
        "why_selected": (
            f"{selection_intro}"
            f"结构质量 {metrics.get('quality_score')}，"
            f"与目标难度偏差 {abs(int(metrics.get('grade_delta') or 0))} 级，"
            f"结构风险 {metrics.get('risk_score')}，"
            f"复用率 {reuse_rate * 100:.0f}%。动作风险尚未评估。"
        ),
    }


async def _llm_json(system_prompt: str, payload: dict) -> dict | None:
    if not settings.api_key or not settings.base_url:
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
    request.board = apply_board_readiness(request.board)
    if not request.board.ai_eligible:
        detail = "；".join(request.board.readiness_issues) or "AI 实验仅支持通过完整性检查的 11×18 岩板"
        raise ValueError(f"当前岩板不能进入 AI 实验：{detail}")
    target_grade = request.target_difficulty or request.board.difficulty or DEFAULT_FONT_GRADE
    reference = _standard_reference(target_grade)
    board_holds = _infer_start_flags(request.board.placed_holds)
    source_ids = _hold_ids(request.board.placed_holds)
    solver = AStarSolver(request.climber_height_cm, request.climber_span_cm)
    validator = PhysicsValidator()
    raw_candidates: List[Tuple[str, str, List[Hold], List[BetaStep]]] = []
    candidate_trace: List[AIExperimentCandidateTrace] = []

    astar_candidate, report = solver.solve(board_holds, _board_budget(board_holds))
    if astar_candidate:
        raw_candidates.append(("best_quality", "a_star", astar_candidate.placed_holds, astar_candidate.beta_sequence))
    else:
        candidate_trace.append(
            AIExperimentCandidateTrace(
                strategy="best_quality",
                strategy_label=STRATEGY_LABELS["best_quality"],
                source="a_star",
                status="failed_validation",
                reason_code="solver_no_candidate",
                reason=_plain_chinese_text(report.get("reason")) or "动作顺序搜索没有找到可用候选。",
            )
        )

    for label in ("best_quality", "target_grade", "different_style"):
        strategy_holds = _compose_strategy_holds([hold.model_copy() for hold in board_holds], target_grade, label)  # type: ignore[arg-type]
        if strategy_holds:
            raw_candidates.append((label, "local_strategy", strategy_holds, _beta_from_holds(strategy_holds)))

    selected: Dict[str, Tuple[FinalRoute, Dict[str, Any], str]] = {}
    # A recombination must differ from the source layout as well as from the
    # other candidates. Returning the source board under a new name is not a
    # valid candidate.
    seen_signatures: set[str] = {_route_signature(request.board.placed_holds)}
    for label, source, holds, beta in raw_candidates:
        signature = _route_signature(holds)
        if signature in seen_signatures:
            candidate_trace.append(
                AIExperimentCandidateTrace(
                    strategy=label,
                    strategy_label=STRATEGY_LABELS.get(label, label),
                    source=source,
                    status="duplicate",
                    reason_code="duplicate_layout",
                    reason="候选岩点布局与原岩板或先前候选相同。",
                    signature=signature,
                )
            )
            continue
        seen_signatures.add(signature)
        metrics = _board_metrics(holds, target_grade)
        metrics["movement_validation_status"] = "not_run"
        metrics["risk_scope"] = "structure_only"
        metrics["risk_assessment_status"] = "partial"
        ok, baseline_message = validator.validate_baseline(holds, target_grade=target_grade)
        metrics["valid_for_climb"] = bool(metrics.get("valid_for_climb")) and ok
        metrics["baseline_message"] = baseline_message
        metrics["reuse_rate"] = round(len(_hold_ids(holds) & source_ids) / len(source_ids), 3) if source_ids else 1.0
        metrics["standard_reference"] = reference
        if not metrics["valid_for_climb"]:
            reasons = list(metrics.get("review_reasons") or [])
            if not ok and baseline_message:
                reasons.append(str(baseline_message))
            candidate_trace.append(
                AIExperimentCandidateTrace(
                    strategy=label,
                    strategy_label=STRATEGY_LABELS.get(label, label),
                    source=source,
                    status="failed_validation",
                    reason_code="rule_validation_failed",
                    reason="；".join(dict.fromkeys(reasons)) or "候选未通过基本可攀性检查。",
                    signature=signature,
                    metrics={
                        "quality_score": metrics.get("quality_score"),
                        "predicted_grade": metrics.get("predicted_grade"),
                        "risk_score": metrics.get("risk_score"),
                        "reuse_rate": metrics.get("reuse_rate"),
                        "failure_codes": metrics.get("hard_failures", []),
                    },
                )
            )
            continue
        route_name = {
            "best_quality": "AI 实验室重组：质量优先",
            "target_grade": "AI 实验室重组：难度匹配",
            "different_style": "AI 实验室重组：风格变化",
        }.get(label, "AI 实验室重组路线")
        commentary = (
            f"本地算法从当前岩板中生成结构草案，结构质量 {metrics['quality_score']}，"
            f"MoonBoard 等效难度 {metrics.get('predicted_grade') or '-'}，复用率 {metrics['reuse_rate'] * 100:.1f}%。"
            "动作顺序用于讨论，仍需定线者复核和试爬。"
        )
        route = _route_with_board_metadata(
            FinalRoute(route_name=route_name, setter_commentary=commentary, placed_holds=holds, beta_sequence=beta),
            request,
        ).model_copy(
            update={
                "difficulty": normalize_font_grade(metrics.get("predicted_grade")) or target_grade,
                "predicted_grade": metrics.get("predicted_grade"),
                "grade_origin": "transferred",
                "difficulty_confidence": metrics.get("difficulty_confidence"),
                "confidence_tier": metrics.get("confidence_tier") or "low",
                "calibration_status": metrics.get("calibration_status") or "calibrating",
            }
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
        candidate_trace.append(
            AIExperimentCandidateTrace(
                strategy=label,
                strategy_label=STRATEGY_LABELS.get(label, label),
                source=source,
                status="rejected",
                reason_code="not_in_final_selection",
                reason="候选已通过检查，最终根据所选实验目标和候选排名决定是否展示。",
                signature=signature,
                metrics={
                    "quality_score": metrics.get("quality_score"),
                    "predicted_grade": metrics.get("predicted_grade"),
                    "grade_delta": metrics.get("grade_delta"),
                    "risk_score": metrics.get("risk_score"),
                    "reuse_rate": metrics.get("reuse_rate"),
                },
            )
        )

    if not selected:
        board_metrics = _board_metrics(request.board.placed_holds, target_grade)
        solver_reason = _plain_chinese_text(report.get("reason")) or "没有找到同时满足岩点数量、起终点和动作连续性的候选"
        return AIExperimentResponse(
            mode="compose_route",
            selected_routes=[],
            failure_suggestion=f"当前岩板暂时无法生成可用候选：{solver_reason}。",
            board=request.board,
            analysis_summary="当前岩板结构不足，AI 实验室未生成可载入候选。",
            metrics=board_metrics,
            applied_constraints=["基本完整性检查", "目标难度匹配"],
            algorithm_notes=[*board_metrics.get("algorithm_notes", []), REFERENCE_NOTE],
            explanation=_explanation(
                request,
                target_grade,
                board_metrics,
                request.board.placed_holds,
                request.board.beta_sequence,
                candidate_trace=candidate_trace,
            ),
        )

    preferred_label = {
        "quality_first": "best_quality",
        "grade_match": "target_grade",
        "style_variation": "different_style",
    }[request.generation_goal]
    order = [preferred_label, *[label for label in ("best_quality", "target_grade", "different_style") if label != preferred_label]]
    # The client renders the original board beside at most two distinct,
    # validated alternatives. Never pad this list by copying a candidate.
    final_items = [(label, *selected[label]) for label in order if label in selected][:2]
    selected_routes = [item[1] for item in final_items]
    source_metrics = _board_metrics(request.board.placed_holds, target_grade)
    preferred_failures = [
        trace.reason
        for trace in candidate_trace
        if trace.strategy == preferred_label and trace.status in {"duplicate", "failed_validation"}
    ]
    fallback_reason = "；".join(dict.fromkeys(preferred_failures))
    candidate_routes = []
    selection_modes: Dict[str, Literal["requested_goal", "fallback", "alternative"]] = {}
    for rank, (label, route, item_metrics, source) in enumerate(final_items, start=1):
        if rank > 1:
            selection_mode: Literal["requested_goal", "fallback", "alternative"] = "alternative"
        elif label == preferred_label:
            selection_mode = "requested_goal"
        else:
            selection_mode = "fallback"
        signature = _route_signature(route.placed_holds)
        selection_modes[signature] = selection_mode
        candidate_routes.append(
            _candidate_record(
                label,
                route,
                item_metrics,
                source,
                target_grade,
                source_holds=request.board.placed_holds,
                source_metrics=source_metrics,
                selection_mode=selection_mode,
                fallback_reason=fallback_reason if selection_mode == "fallback" else "",
            )
        )
    selected_signatures = {
        _route_signature(route.placed_holds): rank
        for rank, route in enumerate(selected_routes, start=1)
    }
    for trace in candidate_trace:
        if trace.signature in selected_signatures:
            trace.status = "selected"
            trace.selected_rank = selected_signatures[trace.signature]
            selection_mode = selection_modes.get(trace.signature, "alternative")
            if selection_mode == "requested_goal":
                trace.reason_code = "selected_for_requested_goal"
                trace.reason = f"通过结构检查，并与“{GENERATION_GOAL_LABELS[request.generation_goal]}”目标一致。"
            elif selection_mode == "fallback":
                trace.reason_code = "selected_as_fallback"
                trace.reason = (
                    f"请求的“{GENERATION_GOAL_LABELS[request.generation_goal]}”策略没有可展示候选"
                    f"（{fallback_reason or '未生成不同且通过检查的布局'}），因此按固定顺序回退到"
                    f"“{trace.strategy_label}”草案。"
                )
            else:
                trace.reason_code = "selected_as_alternative"
                trace.reason = "作为第二个不同且通过结构检查的备选草案展示。"
    metrics = {
        "candidate_count": len(candidate_routes),
        "generation_goal": request.generation_goal,
        "target_grade": target_grade,
        "standard_reference": reference,
        "best_quality_score": max(float(item[2].get("quality_score") or 0.0) for item in final_items),
        "closest_grade_delta": min(abs(int(item[2].get("grade_delta") or 0)) for item in final_items),
    }

    llm_enriched = False
    llm_result = await _llm_json(
        """
你是一名经验丰富的室内攀岩定线员。请只根据系统已经选出的候选线路，润色线路名称和说明，
不得改变难度、风险、岩点、动作顺序或候选排序。

所有面向用户的文字必须使用通俗、简短的简体中文，让没有攀岩算法知识的客户也能看懂。
不要写英文句子，不要堆砌算法术语。Font 等级、Beta、AI、左右手脚缩写和岩点坐标可以保留。
线路名称使用 2 至 10 个中文字符，不使用英文名称。

只返回 JSON：
{"route_names":{"best_quality":"中文名称","target_grade":"中文名称","different_style":"中文名称"},"summary":"一到两句通俗中文说明"}
""".strip(),
        {
            "mode": "compose_route",
            "generation_goal": GENERATION_GOAL_LABELS[request.generation_goal],
            "metrics": metrics,
            "candidate_routes": candidate_routes,
        },
    )
    if llm_result:
        route_names = llm_result.get("route_names") if isinstance(llm_result.get("route_names"), dict) else {}
        summary = _plain_chinese_text(llm_result.get("summary"))
        for record, route in zip(candidate_routes, selected_routes):
            label = str(record["label"])
            route_name = _plain_chinese_text(route_names.get(label), allow_technical_tokens=False)
            if route_name:
                route.route_name = route_name
                llm_enriched = True
            if summary:
                route.setter_commentary = f"{route.setter_commentary} {summary}"
                llm_enriched = True

    return AIExperimentResponse(
        mode="compose_route",
        selected_routes=selected_routes,
        board=request.board,
        analysis_summary=(
            f"本地算法生成 {len(selected_routes)} 条结构候选草案，最接近目标难度偏差 {metrics['closest_grade_delta']} 级。"
            + ("请求目标没有形成可展示候选，首个结果来自固定回退策略。" if candidate_routes[0]["selection_mode"] == "fallback" else "")
        ),
        metrics=metrics,
        candidate_routes=candidate_routes,
        applied_constraints=["11×18 规格", "基本完整性检查", "动作顺序搜索", f"生成目标：{GENERATION_GOAL_LABELS[request.generation_goal]}"],
        algorithm_notes=[
            "候选路线不会覆盖原岩板",
            "结果是定线讨论草案，不替代真人复核与试爬",
            "候选风险分只覆盖结构规则，未检查的动作风险不视为安全",
            "AI 只润色中文名称和说明，不参与候选排序",
            REFERENCE_NOTE,
        ],
        llm_enriched=llm_enriched,
        explanation=_explanation(
            request,
            target_grade,
            final_items[0][2],
            selected_routes[0].placed_holds,
            selected_routes[0].beta_sequence,
            candidate_trace=candidate_trace,
            llm_enriched=llm_enriched,
        ),
    )


def _suggestion(
    title: str,
    detail: str,
    group: Literal["must_fix", "should_fix", "optional"],
    hold_ids: Optional[List[str]] = None,
    candidate_route: Optional[FinalRoute] = None,
    *,
    reason_code: str,
    observed: str,
    threshold: str,
    expected_effect: str,
    beta_steps: Optional[List[int]] = None,
    confidence: Literal["low", "medium", "high"] = "medium",
    evidence_status: Literal["measured", "estimated", "not_measured"] = "measured",
) -> RouteReviewSuggestion:
    return RouteReviewSuggestion(
        title=title,
        detail=detail,
        group=group,
        hold_ids=hold_ids or [],
        candidate_route=candidate_route,
        reason_code=reason_code,
        observed=observed,
        threshold=threshold,
        expected_effect=expected_effect,
        beta_steps=beta_steps or [],
        confidence=confidence,
        evidence_status=evidence_status,
    )


def _candidate_route_for_fix(board: BoardAsset, target_grade: str, label: str = "target_grade") -> Optional[FinalRoute]:
    holds = _compose_strategy_holds(_infer_start_flags([hold.model_copy() for hold in board.placed_holds]), target_grade, label)  # type: ignore[arg-type]
    if not holds:
        return None
    return FinalRoute(
        route_name="AI 实验室修复候选",
        setter_commentary="根据当前岩板自动生成的结构修复草案，不会覆盖原岩板；动作顺序仍需定线者复核和试爬。",
        source_type="ai-generated",
        visibility=board.visibility,
        tags=list(dict.fromkeys([*board.tags, "ai-lab-review"])),
        difficulty=target_grade,
        board_spec=board.board_spec,
        placed_holds=holds,
        beta_sequence=_beta_from_holds(holds),
    )


def _beta_balance_evidence(beta_sequence: Sequence[BetaStep], holds: Sequence[Hold]) -> Dict[str, Any]:
    holds_map = {hold.id: hold for hold in holds}
    contacts: Dict[Limb, str] = {}
    torso_offsets: List[float] = []
    evaluated_steps: List[int] = []
    evidence_hold_ids: set[str] = set()
    cross_high_step_count = 0
    cross_steps: set[int] = set()

    for step in sorted(beta_sequence, key=lambda item: item.step):
        target = holds_map.get(step.hold_id)
        if not target:
            continue
        contacts[step.limb] = step.hold_id
        lh = holds_map.get(step.lh or contacts.get(Limb.LH, ""))
        rh = holds_map.get(step.rh or contacts.get(Limb.RH, ""))
        lf = holds_map.get(step.lf or contacts.get(Limb.LF, ""))
        rf = holds_map.get(step.rf or contacts.get(Limb.RF, ""))
        if not (lh and rh and (lf or rf)):
            continue
        available_feet = [foot for foot in (lf, rf) if foot]
        hand_center = (_x_index(lh) + _x_index(rh)) / 2.0
        foot_center = sum(_x_index(foot) for foot in available_feet) / len(available_feet)
        torso_offsets.append(abs(hand_center - foot_center))
        evaluated_steps.append(step.step)
        evidence_hold_ids.update([lh.id, rh.id, *[foot.id for foot in available_feet]])
        if lf and rf:
            lf_x, rf_x = _x_index(lf), _x_index(rf)
            before = cross_high_step_count
            if (lf_x >= rf_x and lf.y > rf.y) or (abs(lf_x - rf_x) <= 1 and lf.y >= rf.y + 2):
                cross_high_step_count += 1
            if (rf_x <= lf_x and rf.y > lf.y) or (abs(lf_x - rf_x) <= 1 and rf.y >= lf.y + 2):
                cross_high_step_count += 1
            if cross_high_step_count > before:
                cross_steps.add(step.step)

    return {
        "cross_high_step_count": cross_high_step_count,
        "average_torso_offset_columns": round(sum(torso_offsets) / len(torso_offsets), 2) if torso_offsets else None,
        "evaluated_contact_states": len(torso_offsets),
        "related_hold_ids": sorted(evidence_hold_ids),
        "related_beta_steps": sorted(cross_steps or set(evaluated_steps)),
    }


def _consecutive_hand_evidence(beta_sequence: Sequence[BetaStep]) -> Dict[str, Any]:
    current_steps: List[BetaStep] = []
    longest_steps: List[BetaStep] = []
    for step in sorted(beta_sequence, key=lambda item: item.step):
        if step.limb in {Limb.LH, Limb.RH}:
            current_steps.append(step)
            if len(current_steps) > len(longest_steps):
                longest_steps = list(current_steps)
        else:
            current_steps = []
    return {
        "count": len(longest_steps),
        "beta_steps": sorted({step.step for step in longest_steps}),
        "hold_ids": list(dict.fromkeys(step.hold_id for step in longest_steps)),
    }


def _deterministic_review(
    board: BoardAsset,
    target_grade: str,
    review_focus: Literal["overall", "footholds", "difficulty", "beta_sequence"] = "overall",
) -> tuple[List[RouteReviewViolation], List[RouteReviewSuggestion], str, Dict[str, Any]]:
    validator = PhysicsValidator()
    metrics = _board_metrics(board.placed_holds, target_grade)
    violations: List[RouteReviewViolation] = []
    suggestions: List[RouteReviewSuggestion] = []
    candidate_fix = _candidate_route_for_fix(board, target_grade)
    action_checks_enabled = review_focus in {"overall", "footholds", "beta_sequence"}
    hand_sequence_check_enabled = review_focus in {"overall", "beta_sequence"}
    difficulty_check_enabled = review_focus in {"overall", "difficulty"}
    foothold_check_enabled = review_focus in {"overall", "footholds"}
    metrics["review_focus"] = review_focus
    metrics["action_checks_enabled"] = action_checks_enabled
    metrics["hand_sequence_check_enabled"] = hand_sequence_check_enabled
    metrics["difficulty_check_enabled"] = difficulty_check_enabled
    metrics["focus_applied_rules"] = ["基本结构"]
    if action_checks_enabled:
        metrics["focus_applied_rules"].extend(["Beta 引用", "身体平衡"])
    if hand_sequence_check_enabled:
        metrics["focus_applied_rules"].append("连续手部动作")
    if difficulty_check_enabled:
        metrics["focus_applied_rules"].append("目标难度偏差")
    if foothold_check_enabled:
        metrics["focus_applied_rules"].append("脚点数量与支撑")

    failure_messages = {
        "start_hand_count_lt_1": "缺少明确手起点",
        "no_foothold": "缺少可用脚点",
        "end_count_lt_1": "Y16-Y18 缺少非脚点终点",
        "hold_count_out_of_range": "岩点总数不在合理范围",
        "vertical_gap_gt_5": "纵向断档超过 5",
        "ladder_x_span_too_narrow": "横向跨度过窄，接近梯子线",
    }
    failure_evidence = {
        "start_hand_count_lt_1": ("0 个明确手起点", "至少 1 个明确手起点", "补足起步接触条件"),
        "no_foothold": ("0 个脚点", "至少 1 个脚点，建议 2 个以上", "降低起步纯拉力负担"),
        "end_count_lt_1": ("Y16–Y18 无非脚点终点", "至少 1 个高位终点", "补足明确完攀动作"),
        "hold_count_out_of_range": (f"{metrics.get('hold_count', 0)} 个岩点", "6–14 个", "回到当前结构规则的可控范围"),
        "vertical_gap_gt_5": (f"最大断档 {metrics.get('max_vertical_gap', 0)} 排", "不超过 5 排", "恢复中段动作连续性"),
        "ladder_x_span_too_narrow": (f"横向覆盖 {metrics.get('x_span', 0)} 列", "至少 3 列", "增加横向移动空间"),
    }
    for code in metrics.get("hard_failures", []):
        violations.append(RouteReviewViolation(code=code, message=failure_messages.get(code, code)))
        group: Literal["must_fix", "should_fix", "optional"] = "must_fix" if code in {"start_hand_count_lt_1", "end_count_lt_1", "vertical_gap_gt_5"} else "should_fix"
        detail = "建议使用 AI 实验室重组生成候选版本；结构性问题不要只做文字标注。"
        if code == "start_hand_count_lt_1":
            detail = "补充一个或两个明确手起点；单起点按双手匹配处理。"
        elif code == "no_foothold":
            detail = "补充低位脚点，避免起步完全依赖拉力。"
        elif code == "vertical_gap_gt_5":
            detail = "在断档区间增加中段点，或直接重组路线。"
        observed, threshold, expected_effect = failure_evidence.get(code, ("规则未通过", "通过基本结构检查", "消除结构性失败"))
        suggestions.append(
            _suggestion(
                failure_messages.get(code, code),
                detail,
                group,
                candidate_route=candidate_fix if group == "must_fix" else None,
                reason_code=code,
                observed=observed,
                threshold=threshold,
                expected_effect=expected_effect,
                confidence="high",
            )
        )

    hold_ids = _hold_ids(board.placed_holds)
    missing_beta_targets = [step.hold_id for step in board.beta_sequence if step.hold_id not in hold_ids]
    unique_missing = sorted(set(missing_beta_targets))
    beta_balance_ok: Optional[bool] = None
    if action_checks_enabled and unique_missing:
        violations.append(RouteReviewViolation(code="missing_beta_hold", message=f"Beta 序列引用了不存在的岩点：{', '.join(unique_missing)}", hold_ids=unique_missing))
        suggestions.append(
            _suggestion(
                "修正 Beta 引用",
                "删除失效动作，或在对应坐标重新放置岩点后再保存。",
                "must_fix",
                unique_missing,
                reason_code="missing_beta_hold",
                observed=f"{len(unique_missing)} 个动作目标无法定位",
                threshold="所有动作都引用当前岩板岩点",
                expected_effect="恢复动作证据的可定位性，允许继续执行身体平衡检查",
                beta_steps=sorted({step.step for step in board.beta_sequence if step.hold_id in unique_missing}),
                confidence="high",
            )
        )
        metrics["beta_reference_risk_points"] = 22.0

    if action_checks_enabled and board.beta_sequence and not unique_missing:
        beta_balance_ok, message = validator.validate_beta_balance(board.beta_sequence, board.placed_holds)
        balance_evidence = _beta_balance_evidence(board.beta_sequence, board.placed_holds)
        metrics["beta_balance_evidence"] = balance_evidence
        metrics["beta_balance_message"] = message
        if not beta_balance_ok:
            violations.append(RouteReviewViolation(code="beta_balance", message=message))
            observed_parts = [f"对侧高踩 {balance_evidence['cross_high_step_count']} 次"]
            if balance_evidence["average_torso_offset_columns"] is not None:
                observed_parts.append(f"手脚中轴平均偏移 {balance_evidence['average_torso_offset_columns']} 列")
            suggestions.append(
                _suggestion(
                    "降低身体横向扭转",
                    "优先调整证据步骤中的脚点高度和左右分布，再重新运行动作顺序检查。",
                    "should_fix",
                    balance_evidence["related_hold_ids"],
                    reason_code="beta_balance",
                    observed="，".join(observed_parts),
                    threshold="对侧高踩少于 2 次，手脚中轴平均偏移不超过 1.8 列",
                    expected_effect="减少横向扭转，并让 Beta 重新通过身体平衡规则",
                    beta_steps=balance_evidence["related_beta_steps"],
                    confidence="medium",
                )
            )
            metrics["beta_balance_risk_points"] = 20.0

        if hand_sequence_check_enabled:
            hand_evidence = _consecutive_hand_evidence(board.beta_sequence)
            metrics["max_consecutive_hand_moves"] = hand_evidence["count"]
            metrics["consecutive_hand_hold_ids"] = hand_evidence["hold_ids"]
            metrics["consecutive_hand_beta_steps"] = hand_evidence["beta_steps"]
            if hand_evidence["count"] >= 4:
                metrics["hand_sequence_risk_points"] = float(min(15, 6 + (hand_evidence["count"] - 3) * 3))
                suggestions.append(
                    _suggestion(
                        "补充脚步推进",
                        "在连续手部动作段中插入一次有效脚步，或调整手点顺序，随后重新检查。",
                        "should_fix",
                        hand_evidence["hold_ids"],
                        reason_code="consecutive_hand_moves",
                        observed=f"连续 {hand_evidence['count']} 次手部动作",
                        threshold="少于 4 次连续手部动作",
                        expected_effect="减少纯拉力段，并建立可复核的脚步推进节奏",
                        beta_steps=hand_evidence["beta_steps"],
                        confidence="high",
                    )
                )
    elif action_checks_enabled and not board.beta_sequence:
        suggestions.append(
            _suggestion(
                "补充 Beta 序列",
                "先标记起步、核心移动和完攀动作，再执行动作检查。",
                "optional",
                reason_code="beta_missing",
                observed="0 个 Beta 动作",
                threshold="至少包含起步、核心移动和明确完攀动作",
                expected_effect="让系统能够检查动作引用、连续手部动作和身体平衡",
                confidence="high",
                evidence_status="not_measured",
            )
        )

    if difficulty_check_enabled and metrics.get("difficulty_score") is not None and abs(int(metrics.get("grade_delta") or 0)) >= 2:
        suggestions.append(
            _suggestion(
                "复核标称难度",
                f"系统预测 {metrics.get('predicted_grade')}，与目标 {target_grade} 相差 {metrics.get('grade_delta')} 级。",
                "should_fix",
                reason_code="difficulty_mismatch",
                observed=f"预测 {metrics.get('predicted_grade')}，偏差 {metrics.get('grade_delta')} 级",
                threshold="与目标难度相差少于 2 级",
                expected_effect="使标称等级与当前固定模型的等效难度回到相邻档位",
                confidence=metrics.get("confidence_tier") if metrics.get("confidence_tier") in {"low", "medium", "high"} else "low",
                evidence_status="estimated",
            )
        )

    if foothold_check_enabled and 0 < metrics.get("foot_count", 0) < 2:
        foot_ids = sorted(hold.id for hold in board.placed_holds if hold.hold_type == HoldType.FOOT)
        suggestions.append(
            _suggestion(
                "增加脚点支撑",
                "增加一个低位或中段脚点，避免线路过度依赖上肢拉力。",
                "should_fix",
                foot_ids,
                candidate_route=candidate_fix,
                reason_code="limited_footholds",
                observed=f"{metrics.get('foot_count', 0)} 个脚点",
                threshold="至少 2 个脚点，3 个获得完整结构分",
                expected_effect="降低纯拉力风险，并提高脚点支撑结构分",
                confidence="high",
            )
        )

    if not suggestions:
        suggestions.append(
            _suggestion(
                "保留当前结构",
                f"“{REVIEW_FOCUS_LABELS[review_focus]}”没有发现超过当前阈值的问题，可继续由定线者复核和试爬。",
                "optional",
                reason_code="no_focused_issue",
                observed="所选重点检查均未触发建议",
                threshold="所有已执行规则通过",
                expected_effect="无需自动修改，保留现有线路作为讨论版本",
                confidence="medium",
            )
        )

    if not action_checks_enabled:
        metrics["beta_evaluation_status"] = "not_run"
        metrics["review_scope"] = "layout_and_difficulty" if difficulty_check_enabled else "layout_only"
    elif not board.beta_sequence or unique_missing:
        metrics["beta_evaluation_status"] = "incomplete"
        metrics["review_scope"] = "layout_only"
    else:
        metrics["beta_evaluation_status"] = "passed" if beta_balance_ok else "failed"
        metrics["review_scope"] = "full_beta"

    action_risk_points = (
        float(metrics.get("beta_reference_risk_points") or 0)
        + float(metrics.get("beta_balance_risk_points") or 0)
        + float(metrics.get("hand_sequence_risk_points") or 0)
    )
    structural_risk_points = float(metrics.get("structural_risk_score") or 0)
    if not difficulty_check_enabled:
        structural_risk_points -= min(20.0, abs(int(metrics.get("grade_delta") or 0)) * 5.0)
    metrics["risk_score"] = round(min(100.0, max(0.0, structural_risk_points) + action_risk_points), 2)
    metrics["risk_scope"] = (
        "structure_and_action"
        if action_checks_enabled
        else ("structure_and_difficulty" if difficulty_check_enabled else "structure_only")
    )
    metrics["risk_assessment_status"] = (
        "complete"
        if not action_checks_enabled or (bool(board.beta_sequence) and not unique_missing)
        else "partial"
    )

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
    request.board = apply_board_readiness(request.board)
    spec = request.board.board_spec
    columns = int((spec.columns if spec else None) or (spec.cols if spec else None) or 11)
    rows = int((spec.rows if spec else None) or 18)
    angle = int((spec.angle_degrees if spec else None) or 40)
    if columns != 11 or rows != 18 or angle != 40:
        raise ValueError("当前岩板不能进入 AI 审核：AI 实验只支持 11×18、40° 岩板")
    target_grade = request.target_difficulty or request.board.difficulty or DEFAULT_FONT_GRADE
    violations, suggestions, risk_level, metrics = _deterministic_review(
        request.board,
        target_grade,
        request.review_focus,
    )
    review_scope = metrics.get("review_scope", "layout_only")
    if risk_level == "low":
        summary = f"“{REVIEW_FOCUS_LABELS[request.review_focus]}”没有发现超过当前阈值的问题。"
    else:
        summary = f"“{REVIEW_FOCUS_LABELS[request.review_focus]}”发现需要定线者处理或复核的问题。"
    if metrics.get("risk_assessment_status") == "partial":
        summary = f"当前仅完成部分检查，未执行的动作风险不能视为安全。{summary}"

    llm_enriched = False
    llm_result = await _llm_json(
        """
你是一名经验丰富的室内攀岩定线员。请只根据系统给出的检查结果，改写一段审核总结，
不得增加系统没有发现的问题，也不得改变风险等级。

总结必须使用通俗、简短的简体中文，让非技术客户知道“哪里有问题、为什么、下一步怎么改”。
不要写英文句子，不要使用复杂算法术语。Font 等级、Beta、AI、左右手脚缩写和岩点坐标可以保留。
控制在 120 个汉字以内。

只返回 JSON：{"review_summary":"通俗中文总结"}
""".strip(),
        {
            "mode": "review_route",
            "review_focus": REVIEW_FOCUS_LABELS[request.review_focus],
            "risk_level": risk_level,
            "metrics": metrics,
            "violations": [violation.model_dump(mode="json") for violation in violations],
            "suggestions": [suggestion.model_dump(mode="json", exclude={"candidate_route"}) for suggestion in suggestions],
        },
    )
    chinese_review_summary = _plain_chinese_text(llm_result.get("review_summary")) if llm_result else None
    if chinese_review_summary:
        llm_enriched = True
        summary = chinese_review_summary

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
        applied_constraints=[
            "11×18、40° 适用范围",
            *metrics.get("focus_applied_rules", []),
            f"审核重点：{REVIEW_FOCUS_LABELS[request.review_focus]}",
        ],
        algorithm_notes=[
            *metrics.get("algorithm_notes", []),
            "审核用于发现明显结构或动作问题，不替代真人复核与试爬",
            "未执行的专项检查会标为未检查，不参与风险结论",
        ],
        llm_enriched=llm_enriched,
        explanation=_explanation(
            request,
            target_grade,
            metrics,
            request.board.placed_holds,
            request.board.beta_sequence,
            violations=violations,
            llm_enriched=llm_enriched,
            review_mode=True,
        ),
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
        "target_difficulty": board.difficulty or DEFAULT_FONT_GRADE,
        "special_requirements": "",
        "recipe": {
            hold_type.value: RecipeItem(count=count, variant="random").model_dump()
            for hold_type, count in counts.items()
        },
    }
