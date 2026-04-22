
"""
backend/core/a_star_solver.py
"""

import math
import heapq
from typing import List, Dict, Tuple, Optional, Set
from core.models import Hold, HoldType, Limb, BetaStep, RouteCandidate

class State:
    """A* 搜索中的单个状态节点"""
    def __init__(self, limbs: Dict[Limb, Optional[Hold]], g_cost: float, h_cost: float, step_count: int, sequence: List[BetaStep], last_moved_limb: Optional[Limb] = None):
        self.limbs = limbs
        self.g_cost = g_cost
        self.h_cost = h_cost
        self.step_count = step_count
        self.sequence = sequence
        self.last_moved_limb = last_moved_limb

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
        return [h for h in holds if 1 <= h.y <= 8]

    def _get_top_holds(self, holds: List[Hold]) -> List[Hold]:
        return [h for h in holds if h.y == 18]

    def _check_kinematics(self, limbs: Dict[Limb, Optional[Hold]]) -> Tuple[bool, Optional[str]]:
        """
        替代 _is_cross_body，并整合所有运动学红线校验。
        返回 (True, None) 表示校验通过, (False, "原因") 表示违反物理规则。
        """
        def get_hold(limb): return limbs.get(limb)
        def get_y(limb): return get_hold(limb).y if get_hold(limb) else 0
        def get_x_idx(limb): return ord(get_hold(limb).x.upper()) - ord('A') if get_hold(limb) else -1

        lh, rh = get_hold(Limb.LH), get_hold(Limb.RH)
        lf, rf = get_hold(Limb.LF), get_hold(Limb.RF)

        if lh and rh and lh.id != rh.id and get_x_idx(Limb.LH) > get_x_idx(Limb.RH): 
            return False, "交叉手"
        
        if lf and rf and lf.id != rf.id and get_x_idx(Limb.LF) > get_x_idx(Limb.RF): 
            return False, "交叉脚"

        active_feet_y = [y for y in [get_y(Limb.LF), get_y(Limb.RF)] if y > 0]
        if not active_feet_y: 
            return False, "双脚离地"
        
        min_hand_y = min(get_y(Limb.LH), get_y(Limb.RH)) if get_hold(Limb.LH) and get_hold(Limb.RH) else (get_y(Limb.LH) or get_y(Limb.RH))
        max_foot_y = max(active_feet_y)
        if max_foot_y > min_hand_y: 
            return False, "脚高于手"

        max_hand_y = max(get_y(Limb.LH), get_y(Limb.RH))
        min_foot_y = min(active_feet_y)
        if not (3 <= (max_hand_y - min_foot_y) <= 6): 
            return False, "核心区失衡"
        
        if (max_hand_y - min_foot_y) > 9: 
            return False, "身体过度伸展"

        if lh and rh and abs(get_x_idx(Limb.LH) - get_x_idx(Limb.RH)) > 6: 
            return False, "手部横向跨度过大"
        if lf and rf and abs(get_x_idx(Limb.LF) - get_x_idx(Limb.RF)) > 4: 
            return False, "脚部横向跨度过大"

        return True, None

    def solve(self, board_holds: List[Hold], inventory_budget: Dict[HoldType, int] = None) -> Tuple[Optional[RouteCandidate], Dict]:
        max_y_reached = 0
        
        def failure_report(reason: str, rule: Optional[str] = None):
            return None, {"reason": reason, "max_y": max_y_reached, "rule_violation": rule}

        if not board_holds:
            return failure_report("传入的板为空")

        all_holds_map = {h.id: h for h in board_holds}
        top_holds = self._get_top_holds(board_holds)
        if not top_holds:
            return failure_report("没有找到完攀点")

        start_hands = sorted([h for h in board_holds if h.y <= 8 and h.hold_type != HoldType.FOOT], key=lambda h: h.y)
        start_feet = sorted([h for h in board_holds if h.y <= 4], key=lambda h: h.y)

        if len(start_hands) < 1 or len(start_feet) < 1:
            return failure_report("起步区手点或脚点数量不足")

        from itertools import combinations
        possible_starts = []
        # 兼容双手同点起步
        if len(start_hands) == 1:
            for feet_combo in combinations(start_feet, 1):
                possible_starts.append(((start_hands[0], start_hands[0]), feet_combo))
            for feet_combo in combinations(start_feet, 2):
                 possible_starts.append(((start_hands[0], start_hands[0]), feet_combo))

        for hands in combinations(start_hands, 2):
            for feet_combo in combinations(start_feet, 1):
                possible_starts.append((hands, feet_combo))
            for feet_combo in combinations(start_feet, 2):
                possible_starts.append((hands, feet_combo))

        initial_state = None
        for hands, feet in possible_starts:
            lh, rh = (hands[0], hands[1]) if ord(hands[0].x) <= ord(hands[1].x) else (hands[1], hands[0])
            
            if not all(h.y > f.y for h in hands for f in feet): continue
            if len(feet) == 2 and abs(ord(feet[0].x) - ord(feet[1].x)) > 3: continue

            initial_limbs = {Limb.LH: lh, Limb.RH: rh}
            if len(feet) == 1:
                initial_limbs.update({Limb.LF: feet[0], Limb.RF: None})
            else:
                lf, rf = (feet[0], feet[1]) if ord(feet[0].x) <= ord(feet[1].x) else (feet[1], feet[0])
                initial_limbs.update({Limb.LF: lf, Limb.RF: rf})

            is_kinematic, _ = self._check_kinematics(initial_limbs)
            if not is_kinematic: continue
            
            active_limbs = {l: h for l, h in initial_limbs.items() if h}
            if len(active_limbs) < 3: continue

            start_sequence = [BetaStep(step=0, limb=limb, hold_id=hold.id, intent="") for limb, hold in active_limbs.items()]
            initial_state = State(limbs=initial_limbs, g_cost=0.0, h_cost=0.0, step_count=0, sequence=start_sequence, last_moved_limb=None)
            break

        if not initial_state:
            return failure_report("无法构造合法的起步姿态")

        open_list = [initial_state]
        closed_set = set()
        max_iterations = 5000
        iterations = 0
        max_single_step_cost = 0.0
        
        kinematic_failure_counts = {}

        while open_list and iterations < max_iterations:
            iterations += 1
            current = heapq.heappop(open_list)
            
            # 更新最高高度
            current_max_y = 0
            for limb, hold in current.limbs.items():
                if hold:
                    current_max_y = max(current_max_y, hold.y)
            max_y_reached = max(max_y_reached, current_max_y)
            
            ids = tuple(sorted((l.name, h.id) for l, h in current.limbs.items() if h))
            if ids in closed_set: continue
            closed_set.add(ids)

            # 检查完攀：双手 Match 在同一个顶峰点
            lh_hold = current.limbs.get(Limb.LH)
            rh_hold = current.limbs.get(Limb.RH)
            if lh_hold and rh_hold and lh_hold.id == rh_hold.id and lh_hold in top_holds:
                final_sequence = current.sequence
                
                # 精准提取路径点
                used_hold_ids = {step.hold_id for step in final_sequence}
                final_holds = [h for h in board_holds if h.id in used_hold_ids]

                # 校验最终路线岩点数量
                if not (5 <= len(final_holds) <= 15):
                    return failure_report(f"最终路线岩点数不在 5-15 之间 (实际: {len(final_holds)})")

                has_top = False
                for step in reversed(final_sequence):
                    if not has_top and all_holds_map.get(step.hold_id) in top_holds:
                        step.is_top = True
                        has_top = True
                    else:
                        step.is_top = False
                
                return RouteCandidate(
                    placed_holds=final_holds,
                    beta_sequence=final_sequence,
                    total_cost=current.g_cost,
                    flow_score=100.0 / (current.g_cost + 1.0),
                    crux_step=f"最大动作代价: {max_single_step_cost:.1f}"
                ), {"reason": "成功", "max_y": 18, "rule_violation": None}

            # 生成子节点
            for limb in Limb:
                for target_hold in board_holds:
                    if current.limbs.get(limb) and current.limbs[limb].id == target_hold.id: continue
                    if target_hold.hold_type == HoldType.FOOT and limb in [Limb.LH, Limb.RH]: continue
                    
                    # 规则：时序防撞 - 脚不能踩当前手正抓着的点
                    if limb in [Limb.LF, Limb.RF]:
                        if (current.limbs.get(Limb.LH) and target_hold.id == current.limbs[Limb.LH].id) or \
                           (current.limbs.get(Limb.RH) and target_hold.id == current.limbs[Limb.RH].id):
                            continue

                    new_limbs = current.limbs.copy()
                    new_limbs[limb] = target_hold

                    # 物理红线校验
                    def get_y(l): return new_limbs.get(l).y if new_limbs.get(l) else 0
                    def get_x(l): return ord(new_limbs.get(l).x) if new_limbs.get(l) else -1
                    
                    ly, ry = get_y(Limb.LH), get_y(Limb.RH)
                    lfy, rfy = get_y(Limb.LF), get_y(Limb.RF)
                    
                    active_feet_y = [y for y in [lfy, rfy] if y > 0]
                    if not active_feet_y: continue # 不能双脚离地

                    max_hand_y = max(ly, ry) if ly > 0 or ry > 0 else 0
                    min_foot_y = min(active_feet_y)

                    is_kinematic, reason = self._check_kinematics(new_limbs)
                    if not is_kinematic:
                        kinematic_failure_counts[reason] = kinematic_failure_counts.get(reason, 0) + 1
                        continue
                    
                    # --- V6 核心逻辑：引入稳定性、交替性和动作合理性惩罚 ---
                    
                    # 1. 稳定性强化
                    stability_penalty = 0
                    active_feet = [h for l, h in new_limbs.items() if l in [Limb.LF, Limb.RF] and h]
                    if len(active_feet) == 1:
                        stability_penalty += 15.0  # 单脚站立惩罚
                    elif len(active_feet) == 2:
                        foot_dist = self._distance(active_feet[0], active_feet[1])
                        if foot_dist < 0.2:
                            stability_penalty += 10.0 # 双脚间距过小惩罚

                    # 2. 手部交替流
                    fatigue_penalty = 0
                    if current.last_moved_limb and current.last_moved_limb == limb and limb in [Limb.LH, Limb.RH]:
                        fatigue_penalty = 20.0 # 单手死磕惩罚

                    # 3. Match 逻辑检查
                    match_penalty = 0
                    is_match = any(h and h.id == target_hold.id for l, h in current.limbs.items() if l != limb)
                    if is_match and target_hold.hold_type != HoldType.JUG:
                        match_penalty = 25.0 # 在非 Jug 点 Match 难度极高
                        
                    # 计算代价
                    prev_hold = current.limbs.get(limb)
                    dist_to_prev = self._distance(target_hold, prev_hold) if prev_hold else 0.5
                    limit_m = self.span_m * 0.8 if limb in [Limb.LH, Limb.RH] else self.height_m * 0.5
                    dist_cost = self._calculate_distance_cost(dist_to_prev, limit_m)

                    hold_type_cost = self.HOLD_COST_WEIGHTS.get(target_hold.hold_type, 1.0)
                    rotation_penalty = self._calculate_rotation_penalty(target_hold)
                    
                    step_cost = dist_cost + hold_type_cost + rotation_penalty + stability_penalty + fatigue_penalty + match_penalty
                    
                    if step_cost > max_single_step_cost: max_single_step_cost = step_cost

                    new_sequence = current.sequence.copy()
                    
                    # 意图描述
                    prev_y = prev_hold.y if prev_hold else 0
                    intent_map = {
                        (True, True): "向右上方转移重心", (True, False): "向左上方转移重心",
                        (False, True): "向右调整姿态", (False, False): "向左调整姿态"
                    }
                    is_upward = target_hold.y > prev_y
                    is_rightward = ord(target_hold.x) > (ord(prev_hold.x) if prev_hold else -1)
                    intent = intent_map.get((is_upward, is_rightward), "调整姿态")
                    if target_hold in top_holds: intent = f"{limb.value}完攀锁定"

                    new_sequence.append(BetaStep(
                        step=current.step_count + 1, limb=limb, hold_id=target_hold.id, intent=intent
                    ))

                    # 启发函数：鼓励向上，并加入手部交替奖励
                    h_cost = (18 - max_hand_y) * 3.5
                    if limb in [Limb.LH, Limb.RH]:
                        other_hand = Limb.RH if limb == Limb.LH else Limb.LH
                        if new_limbs.get(other_hand) and get_y(limb) < get_y(other_hand):
                            h_cost -= 5.0 # 鼓励移动较低的那只手
                            
                    heapq.heappush(open_list, State(
                        limbs=new_limbs,
                        g_cost=current.g_cost + step_cost,
                        h_cost=h_cost,
                        step_count=current.step_count + 1,
                        sequence=new_sequence,
                        last_moved_limb=limb
                    ))

        most_common_violation = max(kinematic_failure_counts, key=kinematic_failure_counts.get) if kinematic_failure_counts else "无"
        return failure_report(f"A* 搜索超时 ({max_iterations} 次迭代)", most_common_violation)
