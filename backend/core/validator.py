
"""
backend/core/validator.py
"""

import math
from typing import List, Tuple, Dict, Set
from core.models import Hold, HoldType, BetaStep, Limb

class PhysicsValidator:
    """
    攀岩物理规则引擎 (极速初筛器)
    负责对批量生成的路线进行快速物理校验，淘汰绝大部分不合理的路线。
    """
    def __init__(self):
        self.GRID_WIDTH = 11  # A-K
        self.GRID_HEIGHT = 18 # 1-18
        self.GRID_SPACING = 0.2 # 每个网格的物理间距 (米)

    def _coord_to_meters(self, x_label: str, y_label: int) -> Tuple[float, float]:
        x_idx = ord(x_label.upper()) - ord('A')
        y_idx = y_label - 1
        return (x_idx * self.GRID_SPACING, y_idx * self.GRID_SPACING)

    def _get_x_idx(self, hold: Hold) -> int:
        return ord(hold.x.upper()) - ord('A')

    def validate_baseline(self, holds: List[Hold], target_grade: str = "6B+") -> Tuple[bool, str]:
        """
        对路线进行极速初筛。
        """
        if not holds:
            return False, "路线为空，不合法。"

        holds_map: Dict[str, Hold] = {hold.id: hold for hold in holds}

        # 规则 1: 底部(Y:1-4)点不足2个，顶部(Y:16-18)没有点。
        start_zone_holds = [h for h in holds if 1 <= h.y <= 4]
        top_zone_holds = [h for h in holds if 16 <= h.y <= 18]

        if len(start_zone_holds) < 2:
            return False, "底部(Y:1-4)岩点少于2个，无法起步。"
        if not top_zone_holds:
            return False, "顶部(Y:16-18)没有岩点，无法完攀。"

        # 规则 2: 任意相邻两层岩点 Y 轴跨度 > 5 格 (绝对真空区)。
        # 首先获取所有 hold 的 Y 坐标，并排序
        sorted_y_coords = sorted(list(set(h.y for h in holds)))
        if len(sorted_y_coords) > 1:
            for i in range(len(sorted_y_coords) - 1):
                if sorted_y_coords[i+1] - sorted_y_coords[i] > 5:
                    return False, f"相邻Y轴层级 {sorted_y_coords[i]} 和 {sorted_y_coords[i+1]} 之间跨度过大 (>{5}格)，存在绝对真空区。"

        # 规则 3: 任意 2x2 极小区域内包含 >= 4 个点 (拓扑过度拥挤)。
        # 将 holds 转换为 (x_idx, y) 方便计算
        hold_coords: Set[Tuple[int, int]] = set()
        x_indices = set()
        for hold in holds:
            x_idx = ord(hold.x.upper()) - ord('A')
            hold_coords.add((x_idx, hold.y))
            x_indices.add(x_idx)

        for x_base in range(self.GRID_WIDTH - 1):
            for y_base in range(self.GRID_HEIGHT - 1):
                # 定义 2x2 区域的四个角
                count = 0
                if (x_base, y_base) in hold_coords: count += 1
                if (x_base + 1, y_base) in hold_coords: count += 1
                if (x_base, y_base + 1) in hold_coords: count += 1
                if (x_base + 1, y_base + 1) in hold_coords: count += 1
                
                if count >= 4:
                    return False, f"({chr(ord('A')+x_base)}{y_base+1}) 附近的 2x2 区域过度拥挤 (>=4个点)。"

        # 规则 5: 抱石精神 (No Ladder Rule)
        if len(x_indices) <= 2:
            return False, "路线过于垂直，违反“No Ladder Rule”。"
            
        return True, "初筛通过：路线符合基本的物理布局规则。"

    def validate_beta_balance(self, beta_sequence: List[BetaStep], holds: List[Hold]) -> Tuple[bool, str]:
        """
        后验动作平衡检查：拦截“脚步跨到对侧上方导致身体过横”的 Beta。
        """
        if not beta_sequence:
            return True, "无动作序列，跳过平衡检查。"

        holds_map: Dict[str, Hold] = {h.id: h for h in holds}
        contacts: Dict[Limb, str] = {}
        cross_high_step_count = 0
        torso_offset_samples: List[float] = []
        last_move: Tuple[Limb, str] | None = None
        top_seen = False

        for step in sorted(beta_sequence, key=lambda item: item.step):
            target = holds_map.get(step.hold_id)
            if not target:
                return False, f"动作 {step.step} 引用了不存在的岩点 {step.hold_id}。"
            if step.limb in {Limb.LH, Limb.RH} and target.hold_type == HoldType.FOOT:
                return False, f"动作 {step.step} 将手移动到脚点 {step.hold_id}。"
            if last_move == (step.limb, step.hold_id):
                return False, f"动作 {step.step} 与上一动作重复，没有产生新的接触状态。"
            last_move = (step.limb, step.hold_id)
            contacts[step.limb] = step.hold_id
            top_seen = top_seen or step.is_top

            # 兼容旧数据中已经保存的完整接触快照；缺失时使用顺序动作重建。
            lh = holds_map.get(step.lh or contacts.get(Limb.LH, ""))
            rh = holds_map.get(step.rh or contacts.get(Limb.RH, ""))
            lf = holds_map.get(step.lf or contacts.get(Limb.LF, ""))
            rf = holds_map.get(step.rf or contacts.get(Limb.RF, ""))

            if not (lh and rh and (lf or rf)):
                continue

            lh_x, rh_x = self._get_x_idx(lh), self._get_x_idx(rh)
            available_feet = [foot for foot in (lf, rf) if foot]
            hand_center = (lh_x + rh_x) / 2.0
            foot_center = sum(self._get_x_idx(foot) for foot in available_feet) / len(available_feet)
            torso_offset_samples.append(abs(hand_center - foot_center))

            # 对侧上方高踩（或同列上方高踩）计数
            if lf and rf:
                lf_x, rf_x = self._get_x_idx(lf), self._get_x_idx(rf)
                if (lf_x >= rf_x and lf.y > rf.y) or (abs(lf_x - rf_x) <= 1 and lf.y >= rf.y + 2):
                    cross_high_step_count += 1
                if (rf_x <= lf_x and rf.y > lf.y) or (abs(lf_x - rf_x) <= 1 and rf.y >= lf.y + 2):
                    cross_high_step_count += 1

        avg_torso_offset = (sum(torso_offset_samples) / len(torso_offset_samples)) if torso_offset_samples else 0.0

        if cross_high_step_count >= 2:
            return False, "动作序列存在多次对侧上方高踩，身体横向扭转过大。"

        if avg_torso_offset > 1.8:
            return False, f"动作序列手脚中轴偏移过大（平均偏移 {avg_torso_offset:.2f} 列）。"

        if not top_seen:
            return False, "动作序列缺少明确的登顶动作。"

        if not torso_offset_samples:
            return False, "动作序列无法重建两手和至少一脚的稳定接触状态。"

        return True, f"通过动作平衡检查：已重建 {len(torso_offset_samples)} 个可评估接触状态。"
