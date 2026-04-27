
"""
backend/core/a_star_solver.py
"""

import math
import heapq
from typing import List, Dict, Tuple, Optional, Set
from core.models import Hold, HoldType, Limb, BetaStep, RouteCandidate

class State:
    """A* 搜索中的单个状态节点"""
    def __init__(self, limbs: Dict[Limb, Optional[Hold]], g_cost: float, h_cost: float, step_count: int, sequence: List[BetaStep], inventory_left: Dict[HoldType, int], last_moved_limb: Optional[Limb] = None, moves_since_foot_move: int = 0, consecutive_hand_moves: int = 0, y_progress_since_foot_move: float = 0.0):
        self.limbs = limbs
        self.g_cost = g_cost
        self.h_cost = h_cost
        self.step_count = step_count
        self.sequence = sequence
        self.inventory_left = inventory_left
        self.last_moved_limb = last_moved_limb
        self.moves_since_foot_move = moves_since_foot_move
        self.consecutive_hand_moves = consecutive_hand_moves
        self.y_progress_since_foot_move = y_progress_since_foot_move

    @property
    def f_cost(self) -> float:
        return self.g_cost + self.h_cost

    def __lt__(self, other: 'State'):
        return self.f_cost < other.f_cost

    @property
    def max_y(self) -> int:
        """计算当前状态到达的最高 Y 坐标"""
        current_max_y = 0
        for limb, hold in self.limbs.items():
            if hold:
                current_max_y = max(current_max_y, hold.y)
        return current_max_y

class AStarSolver:
    """A* 物理评分引擎"""
    def __init__(self, climber_height_cm: int, climber_span_cm: int):
        self.height_m = climber_height_cm / 100.0
        self.span_m = climber_span_cm / 100.0
        self.GRID_SPACING = 0.2
        self.GRID_HEIGHT = 18
        self.GRID_WIDTH = 11
        
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

    def _get_center_of_gravity(self, limbs: Dict[Limb, Optional[Hold]]) -> Optional[Tuple[float, float]]:
        """计算身体重心 (Center of Gravity)"""
        points = []
        for limb, hold in limbs.items():
            if hold:
                points.append(self._coord_to_meters(hold.x, hold.y))
        
        if not points:
            return None
        
        cg_x = sum(p[0] for p in points) / len(points)
        cg_y = sum(p[1] for p in points) / len(points)
        return (cg_x, cg_y)

    def _calculate_reach_cost(self, cg: Tuple[float, float], target_hold: Hold, moving_limb: Limb, min_foot_y_m: float = 0.0) -> float:
        """
        以预测重心为核心，计算动态触达区间的代价。
        引入蹬地系数 (Push Factor) 支持蓄力逻辑。
        """
        target_pos = self._coord_to_meters(target_hold.x, target_hold.y)
        dist_from_cg = math.sqrt((target_pos[0] - cg[0])**2 + (target_pos[1] - cg[1])**2)

        is_hand = moving_limb in [Limb.LH, Limb.RH]
        reach_limit = self.span_m * 0.8 if is_hand else self.height_m * 0.45
        sweet_spot_dist = reach_limit * 0.7

        ratio = dist_from_cg / reach_limit
        
        # 1. 软化截断
        base_cost = 0.0
        if ratio > 1.0:
            base_cost = 150.0 + (ratio - 1.0) * 1000.0
        else:
            base_cost = 10.0 * ((dist_from_cg - sweet_spot_dist) ** 2)
            if ratio > 0.9:
                base_cost += 50.0 + (ratio - 0.9) * 1000

        # 2. 蹬地动力学 (Push Factor) - 仅对手部动作生效
        if is_hand:
            # 重心到最低支撑脚的垂直距离
            cg_to_foot_dist = cg[1] - min_foot_y_m
            # 蹬地系数：重心越低（蜷缩），系数越小(甚至小于1.0)，手向上伸展更容易
            # 重心越高（拉直），系数越大
            # 这里的 0.8m 是一个基准高度差
            push_factor = 1.0 + (cg_to_foot_dist - 0.8) * 1.5
            push_factor = max(0.5, min(3.0, push_factor)) 
            return base_cost * push_factor
        
        return base_cost

    def _calculate_body_position_cost(self, limbs: Dict[Limb, Optional[Hold]]) -> float:
        """
        根据身体姿态计算代价。优化 U 型曲线支持「蜷缩蓄力」。
        """
        def get_hold(limb): return limbs.get(limb)
        def get_y(limb): return get_hold(limb).y if get_hold(limb) else 0

        active_feet_y = [y for y in [get_y(Limb.LF), get_y(Limb.RF)] if y > 0]
        if not active_feet_y: return 0.0

        max_hand_y = max(get_y(Limb.LH), get_y(Limb.RH))
        if max_hand_y == 0: return 0.0
        min_foot_y = min(active_feet_y)
        
        body_span = float(max_hand_y - min_foot_y)
        
        lower_bound = 4.0
        upper_bound = (self.height_m * 1.25) / self.GRID_SPACING
        
        # 动态 U 型曲线：将最优跨度(mid_point)向低跨度偏移，鼓励蓄力
        # 原 mid_point 约 7.5，现将其向 5-6 格引导
        mid_point = lower_bound + (upper_bound - lower_bound) * 0.35 
        
        scaling_factor = 5.0
        cost = scaling_factor * ((body_span - mid_point) ** 2)
        
        # 如果 body_span 在 4-5 之间，虽然接近红线，但由于是蓄力态，给予额外宽容
        if 4.0 <= body_span <= 5.5:
            cost *= 0.6

        return cost

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
        
        body_span = max_hand_y - min_foot_y
        max_extension_units = (self.height_m * 1.25) / self.GRID_SPACING

        if body_span < 4:
            return False, "身体过度蜷缩"
        
        if body_span > max_extension_units:
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

            # V7 逻辑：在 A* 开始前，预先扣除起步点所消耗的配额
            initial_inventory = inventory_budget.copy()
            for hold in active_limbs.values():
                initial_inventory[hold.hold_type] = initial_inventory.get(hold.hold_type, 0) - 1
            
            # 如果任何岩点类型的配额变为负数，则这是一个无效的起步姿态
            if any(count < 0 for count in initial_inventory.values()):
                continue

            start_sequence = [BetaStep(step=0, limb=limb, hold_id=hold.id, intent="") for limb, hold in active_limbs.items()]
            initial_state = State(
                limbs=initial_limbs, 
                g_cost=0.0, 
                h_cost=0.0, 
                step_count=0, 
                sequence=start_sequence, 
                inventory_left=initial_inventory,
                last_moved_limb=None
            )
            break

        if not initial_state:
            return failure_report("无法构造合法的起步姿态")

        open_list = [initial_state]
        closed_set = set()
        max_iterations = 10000 
        iterations = 0
        max_single_step_cost = 0.0
        best_state_so_far: Optional[State] = None
        
        kinematic_failure_counts = {}

        while open_list and iterations < max_iterations:
            iterations += 1
            current = heapq.heappop(open_list)
            
            # 更新最高高度和最佳状态
            current_max_y = current.max_y
            max_y_reached = max(max_y_reached, current_max_y)
            if best_state_so_far is None or current_max_y > best_state_so_far.max_y:
                best_state_so_far = current

            ids = tuple(sorted((l.name, h.id) for l, h in current.limbs.items() if h))
            if ids in closed_set: continue
            closed_set.add(ids)

            # 检查完攀：双手 Match 在同一个顶峰点
            lh_hold = current.limbs.get(Limb.LH)
            rh_hold = current.limbs.get(Limb.RH)
            if lh_hold and rh_hold and lh_hold.id == rh_hold.id and lh_hold in top_holds:
                final_sequence = current.sequence
                used_hold_ids = {step.hold_id for step in final_sequence}
                final_holds = [h for h in board_holds if h.id in used_hold_ids]

                # V10: 长度软上限 (Soft Cap)
                if len(final_holds) > 15:
                    current.g_cost += (len(final_holds) - 15) * 10.0

                # 计算配额违规
                quota_violations = {}
                from collections import Counter
                final_counts = Counter(h.hold_type for h in final_holds)
                
                initial_recipe_counts = inventory_budget
                
                for ht, count in final_counts.items():
                    required = initial_recipe_counts.get(ht, 0)
                    if count > required:
                        quota_violations[ht] = count - required

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
                    crux_step=f"最大动作代价: {max_single_step_cost:.1f}",
                    quota_violations=quota_violations,
                ), {"reason": "成功", "max_y": 18, "rule_violation": None}

            # --- V9: 弹簧蓄力驱动的子节点生成 ---
            current_cg = self._get_center_of_gravity(current.limbs)
            if not current_cg: continue

            for limb in Limb:
                is_hand_move = limb in [Limb.LH, Limb.RH]
                
                if is_hand_move and current.consecutive_hand_moves >= 1 and current.last_moved_limb == limb:
                    continue 
                if is_hand_move and current.y_progress_since_foot_move <= 0 and current.consecutive_hand_moves >= 2:
                    continue

                for target_hold in board_holds:
                    current_limb_hold = current.limbs.get(limb)
                    if current_limb_hold:
                        dist = self._distance(current_limb_hold, target_hold)
                        dist_limit = 1.1 if is_hand_move else 0.8
                        if dist > dist_limit: continue
                    
                    if current_limb_hold and current_limb_hold.id == target_hold.id: continue
                    if target_hold.hold_type == HoldType.FOOT and is_hand_move: continue
                    
                    new_limbs = current.limbs.copy()
                    new_limbs[limb] = target_hold

                    is_kinematic, reason = self._check_kinematics(new_limbs)
                    if not is_kinematic:
                        kinematic_failure_counts[reason] = kinematic_failure_counts.get(reason, 0) + 1
                        continue
                    
                    body_pos_cost = self._calculate_body_position_cost(new_limbs)
                    total_penalty = 0
                    
                    is_new_hold = not any(h and h.id == target_hold.id for h in current.limbs.values())
                    new_inventory = current.inventory_left.copy()
                    if is_new_hold:
                        if new_inventory.get(target_hold.hold_type, 0) > 0:
                            total_penalty -= 40.0  # 大幅提升配方奖励
                        else:
                            total_penalty += 100.0
                        new_inventory[target_hold.hold_type] = new_inventory.get(target_hold.hold_type, 0) - 1

                    prev_y_m = self._coord_to_meters(current.limbs[limb].x, current.limbs[limb].y)[1] if current.limbs[limb] else current_cg[1]
                    target_y_m = self._coord_to_meters(target_hold.x, target_hold.y)[1]
                    y_progress = target_y_m - prev_y_m

                    if y_progress <= 0:
                        total_penalty += 40.0
                    
                    # 消除步数税反噬：如果动作使用了新点（且在配额内），则豁免本次动作的步数惩罚
                    if not (is_new_hold and new_inventory.get(target_hold.hold_type, -1) >= 0):
                        total_penalty += current.step_count * 0.2

                    y_progress_since_foot_move = (current.y_progress_since_foot_move + y_progress) if is_hand_move else 0
                    if y_progress_since_foot_move > 0.6: 
                        total_penalty += 20.0

                    predicted_cg = self._get_center_of_gravity(new_limbs)
                    min_foot_y_m = min(self._coord_to_meters(h.x, h.y)[1] for h in new_limbs.values() if h and h.hold_type == HoldType.FOOT) if any(h and h.hold_type == HoldType.FOOT for h in new_limbs.values()) else 0
                    
                    reach_cost = self._calculate_reach_cost(predicted_cg, target_hold, limb, min_foot_y_m)
                    hold_type_cost = self.HOLD_COST_WEIGHTS.get(target_hold.hold_type, 1.0)
                    rotation_penalty = self._calculate_rotation_penalty(target_hold)
                    
                    step_cost = reach_cost + hold_type_cost + rotation_penalty + total_penalty + body_pos_cost
                    if step_cost > max_single_step_cost: max_single_step_cost = step_cost
                    
                    new_sequence = current.sequence[:]
                    new_sequence.append(BetaStep(step=current.step_count + 1, limb=limb, hold_id=target_hold.id, intent="Move"))
                    
                    highest_hand_hold = max((h for h in new_limbs.values() if h and h.hold_type != HoldType.FOOT), key=lambda h: self._coord_to_meters(h.x, h.y)[1], default=None)
                    
                    h_cost = 0.0
                    if highest_hand_hold and top_holds:
                        dist_to_top = min(self._distance(highest_hand_hold, top) for top in top_holds)
                        h_cost += dist_to_top * 35.0

                    h_cost += (self.GRID_HEIGHT * self.GRID_SPACING - predicted_cg[1]) * 15.0
                    
                    new_consecutive_hand_moves = (current.consecutive_hand_moves + 1) if is_hand_move else 0

                    heapq.heappush(open_list, State(
                        limbs=new_limbs,
                        g_cost=current.g_cost + step_cost,
                        h_cost=h_cost,
                        step_count=current.step_count + 1,
                        sequence=new_sequence,
                        inventory_left=new_inventory,
                        last_moved_limb=limb,
                        consecutive_hand_moves=new_consecutive_hand_moves,
                        y_progress_since_foot_move=y_progress_since_foot_move
                    ))

        if best_state_so_far and max_y_reached >= 16:
            # 如果是因为迭代耗尽而退出，但我们找到了一个不错的未完成路径
            best_sequence = best_state_so_far.sequence
            used_hold_ids = {step.hold_id for step in best_sequence}
            final_holds = [h for h in board_holds if h.id in used_hold_ids]
            
            # 部分成功也需要计算配额
            quota_violations = {}
            from collections import Counter
            final_counts = Counter(h.hold_type for h in final_holds)
            initial_recipe_counts = inventory_budget
            for ht, count in final_counts.items():
                required = initial_recipe_counts.get(ht, 0)
                if count > required:
                    quota_violations[ht] = count - required
            
            partial_candidate = RouteCandidate(
                placed_holds=final_holds,
                beta_sequence=best_sequence,
                total_cost=best_state_so_far.g_cost,
                flow_score=0, # 未完攀，没有 flow score
                crux_step=f"最高点: Y={max_y_reached}",
                quota_violations=quota_violations
            )
            return partial_candidate, {"reason": "未完攀，显示已知最高路径", "max_y": max_y_reached, "rule_violation": None}

        most_common_violation = max(kinematic_failure_counts, key=kinematic_failure_counts.get) if kinematic_failure_counts else "无"
        return failure_report(f"A* 搜索超时 ({max_iterations} 次迭代)", most_common_violation)
