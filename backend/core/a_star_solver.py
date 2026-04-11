
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
        
        # 岩点难度权重表
        self.HOLD_COST_WEIGHTS = {
            HoldType.JUG: 1.0,
            HoldType.FOOT: 1.5,
            HoldType.PINCH: 3.0,
            HoldType.CRIMP: 4.0,
            HoldType.SLOPER: 5.0,
            HoldType.POCKET: 6.0
        }

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
        return [h for h in holds if 1 <= h.y <= 4]

    def _get_top_holds(self, holds: List[Hold]) -> List[Hold]:
        return [h for h in holds if 16 <= h.y <= 18]

    def solve(self, placed_holds: List[Hold]) -> Optional[RouteCandidate]:
        """
        核心的 A* 寻路和评估逻辑。
        如果成功完攀，返回带有具体信息的 RouteCandidate。
        如果失败，返回 None。
        """
        if not placed_holds: return None

        start_holds = self._get_start_holds(placed_holds)
        top_holds = self._get_top_holds(placed_holds)

        if len(start_holds) < 2 or not top_holds: return None

        # 为了简化，我们假设起步时，左右手各抓一个最低的Jug点
        start_jugs = sorted([h for h in start_holds if h.hold_type == HoldType.JUG], key=lambda h: h.y)
        if len(start_jugs) < 1: return None
        
        lh_start = start_jugs[0]
        rh_start = start_jugs[1] if len(start_jugs) > 1 else start_jugs[0]
        
        initial_limbs = {Limb.LH: lh_start, Limb.RH: rh_start, Limb.LF: None, Limb.RF: None}
        
        initial_state = State(
            limbs=initial_limbs,
            g_cost=0.0,
            h_cost=0.0, # 简化启发式
            step_count=0,
            sequence=[
                BetaStep(step=1, limb=Limb.LH, hold_id=lh_start.id, intent="Start LH"),
                BetaStep(step=2, limb=Limb.RH, hold_id=rh_start.id, intent="Start RH")
            ]
        )

        open_list = [initial_state]
        closed_set = set() # 简单防重：记录(LH_id, RH_id)
        
        max_iterations = 2000 # 防止死循环
        iterations = 0

        best_cost = float('inf')
        best_flow = 0.0
        best_sequence: List[BetaStep] = []
        crux_step = None
        max_single_step_cost = 0.0

        while open_list and iterations < max_iterations:
            iterations += 1
            current = heapq.heappop(open_list)
            
            # 状态防重 (简化版)
            lh_id = current.limbs[Limb.LH].id if current.limbs[Limb.LH] else "None"
            rh_id = current.limbs[Limb.RH].id if current.limbs[Limb.RH] else "None"
            state_key = f"{lh_id}-{rh_id}"
            if state_key in closed_set: continue
            closed_set.add(state_key)

            # 检查完攀
            lh_hold = current.limbs[Limb.LH]
            rh_hold = current.limbs[Limb.RH]
            
            is_top = False
            if lh_hold and lh_hold in top_holds: is_top = True
            if rh_hold and rh_hold in top_holds: is_top = True

            if is_top:
                # 给最后一步打上 is_top=True 标记
                if current.sequence:
                    current.sequence[-1].is_top = True
                
                # 记录成功路线（可以考虑返回 cost 最小的那条，此处简化为找到的第一条）
                candidate = RouteCandidate(
                    placed_holds=placed_holds,
                    beta_sequence=current.sequence,
                    total_cost=current.g_cost,
                    flow_score=100.0 / (current.g_cost + 1.0), # 简单换算
                    crux_step=f"最难动作代价为 {max_single_step_cost:.1f}" if max_single_step_cost > 0 else "无明显难点"
                )
                return candidate

            # 生成子节点 (仅考虑移动手)
            for target_hold in placed_holds:
                for limb in [Limb.LH, Limb.RH]:
                    # 不能移到自己正抓着的点
                    if current.limbs[limb] and current.limbs[limb].id == target_hold.id: continue
                    
                    # 另一只手
                    other_limb = Limb.RH if limb == Limb.LH else Limb.LH
                    other_hold = current.limbs[other_limb]
                    
                    if not other_hold: continue # 单手情况太复杂，先跳过
                    
                    # 物理校验 1：左右手跨度
                    hand_dist = self._distance(target_hold, other_hold)
                    if hand_dist > self.span_m: continue
                    
                    # 物理校验 2: 垂直距离过大 (简单模拟手脚拉伸)
                    if abs(target_hold.y - other_hold.y) * self.GRID_SPACING > self.height_m * 0.8: continue

                    # 计算 Cost
                    dist_cost = self._calculate_distance_cost(hand_dist, self.span_m)
                    hold_type_cost = self.HOLD_COST_WEIGHTS.get(target_hold.hold_type, 1.0)
                    
                    # Flow Cost: 惩罚连续同侧移动
                    flow_penalty = 0.0
                    if current.sequence and len(current.sequence) >= 2:
                        last_move_limb = current.sequence[-1].limb
                        if last_move_limb == limb:
                            flow_penalty = 15.0 # 连续动同一侧手很累

                    step_cost = dist_cost + hold_type_cost + flow_penalty
                    
                    if step_cost > max_single_step_cost:
                        max_single_step_cost = step_cost

                    new_g_cost = current.g_cost + step_cost
                    
                    # 简单启发：离顶部越近，h_cost越小
                    h_cost = (18 - target_hold.y) * 2.0 

                    new_limbs = current.limbs.copy()
                    new_limbs[limb] = target_hold
                    
                    new_sequence = current.sequence.copy()
                    new_sequence.append(BetaStep(
                        step=current.step_count + 1,
                        limb=limb,
                        hold_id=target_hold.id,
                        intent=f"Move {limb.value} to {target_hold.hold_type.value}"
                    ))

                    new_state = State(
                        limbs=new_limbs,
                        g_cost=new_g_cost,
                        h_cost=h_cost,
                        step_count=current.step_count + 1,
                        sequence=new_sequence
                    )
                    heapq.heappush(open_list, new_state)

        return None # 无法完攀
