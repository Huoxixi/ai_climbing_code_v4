
"""
backend/core/validator.py
"""

import math
from typing import List, Tuple, Dict, Set
from core.models import Hold, HoldType

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

    def validate_baseline(self, holds: List[Hold]) -> Tuple[bool, str]:
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

        # 规则 3: 起步和完攀区必须包含 Jug (大把手防摔保护)。
        if not any(h.hold_type == HoldType.JUG for h in start_zone_holds):
            return False, "起步区(Y:1-4)必须至少包含一个Jug大把手。"
        if not any(h.hold_type == HoldType.JUG for h in top_zone_holds):
            return False, "完攀区(Y:16-18)必须至少包含一个Jug大把手。"

        # 规则 4: 任意 2x2 极小区域内包含 >= 4 个点 (拓扑过度拥挤)。
        # 将 holds 转换为 (x_idx, y) 方便计算
        hold_coords: Set[Tuple[int, int]] = set()
        for hold in holds:
            x_idx = ord(hold.x.upper()) - ord('A')
            hold_coords.add((x_idx, hold.y))

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

        return True, "初筛通过：路线符合基本的物理布局规则。"
