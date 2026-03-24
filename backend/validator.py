import math
from typing import List, Tuple, Dict
from models import ClimberProfile, RouteStep, Hold

class PhysicsValidator:
    """
    攀岩物理规则引擎 (核心裁判系统)
    负责拦截 LLM 生成的反人类/超常规物理动作
    """
    def __init__(self, climber: ClimberProfile, holds_db: List[Hold]):
        self.climber = climber
        # 将岩点列表转化为 Hash Map，实现 O(1) 的极速坐标查询
        self.holds_map: Dict[str, Tuple[float, float]] = {
            hold.hold_id: (hold.x_m, hold.y_m) for hold in holds_db
        }

    def _calc_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """计算两点间的欧氏距离(米)"""
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    def validate_sequence(self, sequence: List[RouteStep]) -> Tuple[bool, str]:
        """
        校验一整套攀爬序列是否合法
        返回格式: (是否通过校验, 错误详情/成功日志)
        """
        # 初始化四肢当前所在的坐标 (None 表示悬空或尚未起步)
        current_limbs = {"LH": None, "RH": None, "LF": None, "RF": None}
        
        # 将厘米转化为米，方便与坐标系统一计算
        span_m = self.climber.span_cm / 100.0
        height_m = self.climber.height_cm / 100.0

        for i, step in enumerate(sequence):
            # 1. 幻觉拦截：检查大模型生成的岩点是否存在于数据库中
            if step.hold_id not in self.holds_map:
                return False, f"第 {step.step} 步物理错误：目标岩点 {step.hold_id} 在岩壁面上不存在（发生幻觉）。"
            
            # 更新该肢体的当前位置
            target_coord = self.holds_map[step.hold_id]
            current_limbs[step.limb] = target_coord

            # 2. 臂展极限校验 (检查左右手绝对距离)
            if current_limbs["LH"] and current_limbs["RH"]:
                hand_dist = self._calc_distance(current_limbs["LH"], current_limbs["RH"])
                if hand_dist > span_m:
                    return False, f"第 {step.step} 步物理错误：左右手跨度达到 {hand_dist:.2f} 米，超过了攀爬者臂展极限 ({span_m:.2f} 米)。"

            # 3. 身高延展极限校验 (检查最高的手与最低的脚之间的距离)
            active_hands = [coord for limb, coord in current_limbs.items() if limb in ["LH", "RH"] and coord]
            active_feet = [coord for limb, coord in current_limbs.items() if limb in ["LF", "RF"] and coord]
            
            if active_hands and active_feet:
                max_hand_y = max(coord[1] for coord in active_hands)
                min_foot_y = min(coord[1] for coord in active_feet)
                stretch_dist = max_hand_y - min_foot_y
                
                # 允许一定程度的踮脚和身体拉伸，设定宽容系数为 1.15
                if stretch_dist > height_m * 1.15:
                    return False, f"第 {step.step} 步物理错误：手脚上下拉伸达到 {stretch_dist:.2f} 米，超出身高延展极限。"

        return True, "全序列物理校验通过。动作合理。"