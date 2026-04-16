
"""
backend/core/a_star_solver.py
"""

import math
import heapq
from typing import List, Dict, Tuple, Optional, Set
from core.models import Hold, HoldType, Limb, BetaStep, RouteCandidate

class State:
    """A* 搜索中的单个状态节点"""
    def __init__(self, limbs: Dict[Limb, Optional[Hold]], g_cost: float, h_cost: float, step_count: int, sequence: List[BetaStep]):
        self.limbs = limbs
        self.g_cost = g_cost
        self.h_cost = h_cost
        self.step_count = step_count
        self.sequence = sequence

    @property
    def f_cost(self) -> float:
        return self.g_cost + self.h_cost

    def __lt__(self, other: 'State'):
        return self.f_cost < other.f_cost

class AStarSolver:
    """A* 物理评分引擎"""
    def __init__(self, climber_height_cm: int, climber_span_cm: int):
        self.height_m = climber_height_cm / 100.0
        self.span_m = climber_span_cm / 100.0
        self.GRID_SPACING = 0.2
        
        # 岩点难度权重表 (V2 难度校准)
        self.HOLD_COST_WEIGHTS = {
            HoldType.JUG: 1.0,
            HoldType.FOOT: 1.2,
            HoldType.PINCH: 4.0,
            HoldType.CRIMP: 5.5,
            HoldType.SLOPER: 6.5,
            HoldType.POCKET: 8.0
        }

    def _calculate_rotation_penalty(self, hold: Hold) -> float:
        """根据岩点类型和旋转角度计算抓握难度惩罚。"""
        angle = hold.rotation % 360
        
        # 对 Sloper 和 Jug 这种对方向敏感的岩点增加惩罚
        if hold.hold_type in [HoldType.SLOPER, HoldType.JUG]:
            if 135 <= angle <= 225: # 向下
                return 15.0
            elif 45 <= angle < 135 or 225 < angle <= 315: # 侧向
                return 7.0
        
        # 对 Crimp, Pinch 这种边缘发力的点，竖直或水平最好
        if hold.hold_type in [HoldType.CRIMP, HoldType.PINCH]:
            is_vertical = 75 <= angle <= 105 or 255 <= angle <= 285
            is_horizontal = (0 <= angle <= 15 or 345 <= angle <= 360) or (165 <= angle <= 195)
            if not (is_vertical or is_horizontal):
                return 5.0 # 斜向 Crimp 难度增加

        return 0.0

    def _coord_to_meters(self, x_label: str, y_label: int) -> Tuple[float, float]:
        x_idx = ord(x_label.upper()) - ord('A')
        y_idx = y_label - 1
        return (x_idx * self.GRID_SPACING, y_idx * self.GRID_SPACING)

    def _distance(self, h1: Hold, h2: Hold) -> float:
        p1 = self._coord_to_meters(h1.x, h1.y)
        p2 = self._coord_to_meters(h2.x, h2.y)
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    def _calculate_distance_cost(self, dist_m: float, limit_m: float) -> float:
        """
        计算距离代价：距离越接近极限的 60% 代价越低，超过 90% 代价剧增。
        这里使用一个简单的二次函数模拟这种趋势。
        """
        ratio = dist_m / limit_m
        if ratio > 1.0:
             return 9999.0 # 理论上达不到
        elif ratio > 0.9:
            return 50.0 + (ratio - 0.9) * 1000 # 剧增
        else:
            # 假设 0.6 是最佳距离 (Cost 最低)
            return 5.0 * ((ratio - 0.6) ** 2)

    def _get_start_holds(self, holds: List[Hold]) -> List[Hold]:
        return [h for h in holds if 1 <= h.y <= 6]

    def _get_top_holds(self, holds: List[Hold]) -> List[Hold]:
        return [h for h in holds if 17 <= h.y <= 18]

    def _is_cross_body(self, limbs: Dict[Limb, Optional[Hold]]) -> bool:
        """检查身体是否过度打结/交叉 (肢体防结)"""
        def get_x_idx(h): return ord(h.x.upper()) - ord('A') if h else None
        
        lx, rx = get_x_idx(limbs[Limb.LH]), get_x_idx(limbs[Limb.RH])
        lfx, rfx = get_x_idx(limbs[Limb.LF]), get_x_idx(limbs[Limb.RF])
        
        # 左侧肢体的 X 坐标需在右侧肢体的左侧或同列
        if lx is not None and rx is not None and lx > rx: return True
        if lfx is not None and rfx is not None and lfx > rfx: return True
        return False

    def solve(self, placed_holds: List[Hold]) -> Optional[RouteCandidate]:
        if not placed_holds: return None

        start_holds = self._get_start_holds(placed_holds)
        top_holds = self._get_top_holds(placed_holds)

        # 1. 寻找合法起步点 (3-4点起步)
        # 起步脚 Y: 1-2, 起步手 Y: 3-6
        start_hands = [h for h in start_holds if 3 <= h.y <= 6 and h.hold_type != HoldType.FOOT]
        start_feet = [h for h in start_holds if 1 <= h.y <= 2]

        if len(start_hands) < 1 or len(start_feet) < 1: return None

        # 选取最底部的点作为起步
        lh_start = start_hands[0]
        rh_start = start_hands[1] if len(start_hands) > 1 else start_hands[0]
        lf_start = start_feet[0]
        rf_start = start_feet[1] if len(start_feet) > 1 else start_feet[0]

        initial_limbs = {Limb.LH: lh_start, Limb.RH: rh_start, Limb.LF: lf_start, Limb.RF: rf_start}
        
        # 初始 beta 序列 (Step 0)
        start_sequence = []
        for limb, hold in initial_limbs.items():
            start_sequence.append(BetaStep(step=0, limb=limb, hold_id=hold.id, intent=""))

        initial_state = State(
            limbs=initial_limbs,
            g_cost=0.0,
            h_cost=0.0,
            step_count=0,
            sequence=start_sequence
        )

        open_list = [initial_state]
        closed_set = set()
        max_iterations = 3000
        iterations = 0
        max_single_step_cost = 0.0

        while open_list and iterations < max_iterations:
            iterations += 1
            current = heapq.heappop(open_list)
            
            # 状态防重 (4肢组合)
            ids = [current.limbs[l].id if current.limbs[l] else "None" for l in Limb]
            state_key = "-".join(ids)
            if state_key in closed_set: continue
            closed_set.add(state_key)

            # 检查完攀：双手 Match 在同一个顶峰点
            lh_hold = current.limbs[Limb.LH]
            rh_hold = current.limbs[Limb.RH]
            if lh_hold and rh_hold and lh_hold.id == rh_hold.id and lh_hold in top_holds:
                current.sequence[-1].is_top = True
                return RouteCandidate(
                    placed_holds=placed_holds,
                    beta_sequence=current.sequence,
                    total_cost=current.g_cost,
                    flow_score=100.0 / (current.g_cost + 1.0),
                    crux_step=f"最大动作代价: {max_single_step_cost:.1f}"
                )

            # 生成子节点：尝试移动 LH, RH, LF, RF
            for limb in Limb:
                for target_hold in placed_holds:
                    # 规则 0: 不能移动到当前所在点
                    if current.limbs[limb] and current.limbs[limb].id == target_hold.id: continue
                    # 规则 1: Foot 类型岩点不能分给手
                    if target_hold.hold_type == HoldType.FOOT and limb in [Limb.LH, Limb.RH]: continue
                    # 规则 2: 时序防撞 - 脚不能踩当前手正抓着的点
                    if limb in [Limb.LF, Limb.RF]:
                        if (current.limbs[Limb.LH] and target_hold.id == current.limbs[Limb.LH].id) or \
                           (current.limbs[Limb.RH] and target_hold.id == current.limbs[Limb.RH].id):
                            continue

                    new_limbs = current.limbs.copy()
                    new_limbs[limb] = target_hold

                    # 物理红线校验 (The Box & Constraints)
                    def get_y(l): return new_limbs[l].y if new_limbs[l] else 0
                    def get_x(l): return ord(new_limbs[l].x.upper()) - ord('A') if new_limbs[l] else 0
                    
                    ly, ry, lfy, rfy = get_y(Limb.LH), get_y(Limb.RH), get_y(Limb.LF), get_y(Limb.RF)
                    lx, rx, lfx, rfx = get_x(Limb.LH), get_x(Limb.RH), get_x(Limb.LF), get_x(Limb.RF)

                    # 1. 肢体防结
                    if self._is_cross_body(new_limbs): continue
                    # 2. 手必须高于脚 3-6 格
                    max_hand_y = max(ly, ry)
                    min_foot_y = min(lfy, rfy)
                    if not (3 <= (max_hand_y - min_foot_y) <= 8): continue
                    # 3. 跨度警报 (人体撕裂)
                    if (max_hand_y - min_foot_y) > 9: continue
                    # 4. 横向跨度限制
                    if abs(lx - rx) > 7: continue # 左右手 <= 7 (放宽)
                    if abs(lfx - rfx) > 5: continue # 双脚 <= 5 (放宽)

                    # 计算代价
                    prev_hold = current.limbs[limb]
                    dist_to_prev = self._distance(target_hold, prev_hold) if prev_hold else 0.5
                    
                    # 距离代价 (V2 优化版)
                    # 鼓励更有冲刺感的动作
                    limit_m = self.span_m * 0.8 if limb in [Limb.LH, Limb.RH] else self.height_m * 0.5
                    dist_cost = self._calculate_distance_cost(dist_to_prev, limit_m)

                    # 岩点自身难度
                    hold_type_cost = self.HOLD_COST_WEIGHTS.get(target_hold.hold_type, 1.0)
                    rotation_penalty = self._calculate_rotation_penalty(target_hold)
                    
                    # 惩罚连续移动同一肢体 (减弱惩罚)
                    flow_penalty = 5.0 if current.sequence and current.sequence[-1].limb == limb else 0.0
                    
                    # 鼓励横向移动 (x_diff)
                    x_diff = abs(get_x(limb) - (ord(prev_hold.x.upper()) - ord('A') if prev_hold else get_x(limb)))
                    x_diff_bonus = -2.0 * x_diff if x_diff > 2 else 0.0
                    
                    step_cost = dist_cost + hold_type_cost + rotation_penalty + flow_penalty + x_diff_bonus
                    if step_cost > max_single_step_cost: max_single_step_cost = step_cost

                    new_sequence = current.sequence.copy()
                    intent = "向上推进" if target_hold.y > (current.limbs[limb].y if current.limbs[limb] else 0) else "调整姿态"
                    if target_hold.y >= 17: intent = "右手完攀锁定" if limb == Limb.RH else "左手完攀锁定"
                    
                    new_sequence.append(BetaStep(
                        step=current.step_count + 1,
                        limb=limb,
                        hold_id=target_hold.id,
                        intent=intent
                    ))

                    h_cost = (18 - max_hand_y) * 5.0
                    heapq.heappush(open_list, State(
                        limbs=new_limbs,
                        g_cost=current.g_cost + step_cost,
                        h_cost=h_cost,
                        step_count=current.step_count + 1,
                        sequence=new_sequence
                    ))

        return None
