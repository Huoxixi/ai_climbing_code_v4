"""Business readiness rules shared by persistence and AI experiments.

The checks intentionally distinguish a recoverable draft from a route that is
complete enough for deterministic review. Only the 11x18 board is AI-capable.
"""

from __future__ import annotations

import re
from typing import Dict, List

from core.models import BoardAsset, Hold, HoldType, Limb


def _board_dimensions(board: BoardAsset) -> tuple[int, int]:
    spec = board.board_spec
    return (
        int((spec.columns if spec else None) or (spec.cols if spec else None) or 11),
        int((spec.rows if spec else None) or 18),
    )


def _coordinate_is_valid(hold: Hold, columns: int, rows: int) -> bool:
    match = re.fullmatch(r"([A-Z]+)(\d+)", str(hold.id).upper())
    if not match:
        return False
    x_label, y_text = match.groups()
    if len(x_label) != 1:
        return False
    x_index = ord(x_label) - ord("A")
    return 0 <= x_index < columns and 1 <= int(y_text) <= rows and hold.x.upper() == x_label and hold.y == int(y_text)


def evaluate_board_readiness(board: BoardAsset) -> Dict[str, object]:
    columns, rows = _board_dimensions(board)
    issues: List[str] = []
    warnings: List[str] = []
    holds = board.placed_holds
    hold_by_id = {hold.id: hold for hold in holds}

    if not board.route_name.strip():
        issues.append("请填写线路名称")
    if len(hold_by_id) != len(holds):
        issues.append("存在重复坐标的岩点")
    if not 6 <= len(holds) <= 14:
        issues.append("线路需包含 6–14 个岩点")

    invalid_coords = [hold.id for hold in holds if not _coordinate_is_valid(hold, columns, rows)]
    if invalid_coords:
        issues.append(f"岩点坐标超出当前岩板：{', '.join(invalid_coords[:4])}")

    start_hands = [hold for hold in holds if hold.is_start and hold.hold_type != HoldType.FOOT and hold.y <= 5]
    start_feet = [hold for hold in holds if hold.is_start and hold.hold_type == HoldType.FOOT and hold.y <= 5]
    if not start_hands:
        issues.append("至少标记一个 Y1–Y5 手部起点，单点可双手匹配")
    if not start_feet:
        issues.append("至少标记一个 Y1–Y5 起步脚点")

    top_steps = [step for step in board.beta_sequence if step.is_top]
    valid_top_steps = [
        step
        for step in top_steps
        if step.hold_id in hold_by_id
        and hold_by_id[step.hold_id].hold_type != HoldType.FOOT
        and hold_by_id[step.hold_id].y >= max(1, rows - 2)
    ]
    if not valid_top_steps:
        issues.append("Beta 需在岩板最后三排标记一个非脚点登顶动作")

    missing_targets = sorted({step.hold_id for step in board.beta_sequence if step.hold_id not in hold_by_id})
    if missing_targets:
        issues.append(f"Beta 引用了不存在的岩点：{', '.join(missing_targets[:4])}")
    if not board.beta_sequence:
        issues.append("请补充 Beta 动作序列")
    elif not any(step.intent.lower() not in {"start", "start foot"} and not step.is_top for step in board.beta_sequence):
        issues.append("Beta 至少需要一个起步后的移动动作")

    seen_step_numbers: set[int] = set()
    limb_contacts: Dict[Limb, str] = {}
    for step in board.beta_sequence:
        simultaneous_start = step.step == 0 and step.intent.lower() in {"start", "start foot"}
        if step.step in seen_step_numbers and not simultaneous_start:
            issues.append("Beta 动作编号不能重复")
            break
        seen_step_numbers.add(step.step)
        if step.hold_id in hold_by_id:
            if step.limb in {Limb.LH, Limb.RH} and hold_by_id[step.hold_id].hold_type == HoldType.FOOT:
                issues.append(f"手部动作不能使用脚点 {step.hold_id}")
                break
            limb_contacts[step.limb] = step.hold_id

    if board.beta_sequence and not (
        Limb.LH in limb_contacts
        and Limb.RH in limb_contacts
        and (Limb.LF in limb_contacts or Limb.RF in limb_contacts)
    ):
        issues.append("Beta 需能重建双手和至少一只脚的接触状态")

    ready = not issues
    angle = int(board.board_spec.angle_degrees if board.board_spec else 0)
    ai_eligible = ready and columns == 11 and rows == 18 and angle == 40
    if ready and not ai_eligible:
        warnings.append("当前规格仅支持手工定线，MoonBoard 等效评级与 AI 实验只支持 11×18、40° 岩板")

    return {
        "workflow_status": "ready_for_review" if ready else "draft",
        "readiness_issues": issues,
        "readiness_warnings": warnings,
        "ai_eligible": ai_eligible,
    }


def apply_board_readiness(board: BoardAsset) -> BoardAsset:
    return board.model_copy(update=evaluate_board_readiness(board))
