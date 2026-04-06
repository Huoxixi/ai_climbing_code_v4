# backend/validator.py
import math
from typing import List, Tuple, Dict
from models import ClimberProfile, BetaStep, HoldBase

class PhysicsValidator:
    """
    攀岩物理规则引擎 (动态造物主版本)
    负责拦截 LLM 生成的反人类动作以及不合理的岩点摆放
    """
    def __init__(self, climber: ClimberProfile):
        self.climber = climber
        # 假设标准岩板孔位间距为 20cm (0.2米)，用于将 A-K/1-18 转化为物理距离
        self.GRID_SPACING = 0.2 

    def _coord_to_meters(self, x_label: str, y_label: int) -> Tuple[float, float]:
        """将 A-K, 1-18 的网格坐标转化为物理米数"""
        x_idx = ord(x_label.upper()) - ord('A')
        y_idx = y_label - 1 # 假设第1排底部为 0 米
        return (x_idx * self.GRID_SPACING, y_idx * self.GRID_SPACING)

    def _calc_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """计算两点间的欧氏距离(米)"""
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    def validate_route(self, placed_holds: List[HoldBase], sequence: List[BetaStep]) -> Tuple[bool, str]:
        """
        核心校验：同时校验岩点的放置布局与动作序列
        """
        # --- 阶段一：校验空间布局逻辑 ---
        placed_ids = set()
        holds_map: Dict[str, Tuple[float, float]] = {}
        
        for hold in placed_holds:
            if hold.id in placed_ids:
                return False, f"空间重叠错误：孔位 {hold.id} 上被重复放置了多个岩点！"
            placed_ids.add(hold.id)
            # 动态生成本次路线的物理坐标地图
            holds_map[hold.id] = self._coord_to_meters(hold.x, hold.y)

        # --- 阶段二：校验攀爬动作逻辑 ---
        current_limbs = {"LH": None, "RH": None, "LF": None, "RF": None}
        span_m = self.climber.span_cm / 100.0
        height_m = self.climber.height_cm / 100.0

        for i, step in enumerate(sequence):
            # 1. 空点拦截：大模型让你抓的这个孔位上，它之前有没有放点？
            if step.hold_id not in holds_map:
                return False, f"第 {step.step} 步逻辑错误：目标孔位 {step.hold_id} 上是空的，没有拧岩点！"
            
            # 更新肢体坐标
            target_coord = holds_map[step.hold_id]
            current_limbs[step.limb.value] = target_coord

            # 2. 臂展极限校验
            if current_limbs["LH"] and current_limbs["RH"]:
                hand_dist = self._calc_distance(current_limbs["LH"], current_limbs["RH"])
                if hand_dist > span_m:
                    return False, f"第 {step.step} 步物理错误：左右手跨度 {hand_dist:.2f}米，超过了臂展极限 ({span_m:.2f}米)。"

            # 3. 身高延展极限校验
            active_hands = [coord for limb, coord in current_limbs.items() if limb in ["LH", "RH"] and coord]
            active_feet = [coord for limb, coord in current_limbs.items() if limb in ["LF", "RF"] and coord]
            
            if active_hands and active_feet:
                max_hand_y = max(coord[1] for coord in active_hands)
                min_foot_y = min(coord[1] for coord in active_feet)
                stretch_dist = max_hand_y - min_foot_y
                
                # 宽容系数 1.15
                if stretch_dist > height_m * 1.15:
                    return False, f"第 {step.step} 步物理错误：手脚上下拉伸 {stretch_dist:.2f}米，超出身高极限。"

        return True, "造物主定线方案校验完美通过：布局无冲突，动作在生理极限内。"