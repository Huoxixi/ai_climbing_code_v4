
"""
backend/core/a_star_solver.py
"""

import math
import heapq
from typing import List, Dict, Tuple, Optional, Set
from core.models import Hold, HoldType, Limb, BetaStep, RouteCandidate

class State:
    """A* 搜索中的单个状态节点"""
    def __init__(self, limbs: Dict[Limb, Optional[Hold]], g_cost: float, h_cost: float, step_count: int, sequence: List[BetaStep], inventory_left: Dict[HoldType, int], last_moved_limb: Optional[Limb] = None, limb_idle_steps: Dict[Limb, int] = None, consecutive_hand_moves: int = 0, y_progress_since_foot_move: float = 0.0):
        self.limbs = limbs
        self.g_cost = g_cost
        self.h_cost = h_cost
        self.step_count = step_count
        self.sequence = sequence
        self.inventory_left = inventory_left
        self.last_moved_limb = last_moved_limb
        self.limb_idle_steps = limb_idle_steps or {l: 0 for l in Limb}
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

    def to_dict(self) -> Dict[str, Optional[str]]:
        """导出当前肢体状态 ID"""
        # 严格检查，确保 rf 不会因为 limbs.get 失败而消失
        res = {
            "lh": self.limbs.get(Limb.LH).id if self.limbs.get(Limb.LH) else None,
            "rh": self.limbs.get(Limb.RH).id if self.limbs.get(Limb.RH) else None,
            "lf": self.limbs.get(Limb.LF).id if self.limbs.get(Limb.LF) else None,
            "rf": self.limbs.get(Limb.RF).id if self.limbs.get(Limb.RF) else None,
        }
        return res

class AStarSolver:
    """A* 物理评分引擎"""
    def __init__(self, climber_height_cm: int, climber_span_cm: int):
        self.height_m = climber_height_cm / 100.0
        self.span_m = climber_span_cm / 100.0
        self.GRID_SPACING = 0.2
        self.GRID_HEIGHT = 18
        self.GRID_WIDTH = 11

        # 稳定性参数：用于抑制“大字型横向发力”和“双脚上下断层”
        self.SOFT_HAND_SPAN_LIMIT = 4
        self.SOFT_FOOT_SPAN_LIMIT = 2
        self.SOFT_FOOT_VERTICAL_GAP_LIMIT = 2
        self.HARD_FOOT_VERTICAL_GAP_LIMIT = 5
        self.MAX_FOOT_MOVE_VERTICAL_DELTA = 3
        
        # 岩点难度权重表 (V2 难度校准)
        self.HOLD_COST_WEIGHTS = {
            HoldType.JUG: 1.0,
            HoldType.FOOT: 1.2,
            HoldType.PINCH: 4.0,
            HoldType.CRIMP: 5.5,
            HoldType.SLOPER: 6.5,
            HoldType.POCKET: 8.0
        }

    def _get_x_idx(self, hold: Optional[Hold]) -> int:
        return ord(hold.x.upper()) - ord('A') if hold else -1

    def _get_body_midline_x(self, limbs: Dict[Limb, Optional[Hold]]) -> float:
        """用双手中心近似身体中线；若手点缺失，则回退到双脚中心。"""
        lh, rh = limbs.get(Limb.LH), limbs.get(Limb.RH)
        if lh and rh:
            return (self._get_x_idx(lh) + self._get_x_idx(rh)) / 2.0

        lf, rf = limbs.get(Limb.LF), limbs.get(Limb.RF)
        if lf and rf:
            return (self._get_x_idx(lf) + self._get_x_idx(rf)) / 2.0

        return (self.GRID_WIDTH - 1) / 2.0

    def _is_contralateral_high_step(
        self,
        current_limbs: Dict[Limb, Optional[Hold]],
        moving_limb: Limb,
        target_hold: Hold
    ) -> bool:
        """
        拦截“同侧脚跨到对侧脚上方/同列上方”的高踩动作。
        该动作会显著诱发身体过横与骨盆偏转。
        """
        if moving_limb not in [Limb.LF, Limb.RF] or target_hold.hold_type != HoldType.FOOT:
            return False

        other_limb = Limb.RF if moving_limb == Limb.LF else Limb.LF
        other_foot = current_limbs.get(other_limb)
        if not other_foot:
            return False

        target_x = self._get_x_idx(target_hold)
        other_x = self._get_x_idx(other_foot)

        if moving_limb == Limb.LF and target_x >= other_x and target_hold.y > other_foot.y:
            return True
        if moving_limb == Limb.RF and target_x <= other_x and target_hold.y > other_foot.y:
            return True

        # 同列/近邻列上方高踩同样容易造成明显横向扭转
        if abs(target_x - other_x) <= 1 and target_hold.y >= other_foot.y + 2:
            return True

        return False

    def _calculate_torsional_penalty(self, limbs: Dict[Limb, Optional[Hold]]) -> float:
        """惩罚身体中轴偏移与脚点对侧高踩导致的扭转姿态。"""
        lh, rh = limbs.get(Limb.LH), limbs.get(Limb.RH)
        lf, rf = limbs.get(Limb.LF), limbs.get(Limb.RF)

        if not (lh and rh and lf and rf):
            return 0.0

        penalty = 0.0
        lx, rx = self._get_x_idx(lf), self._get_x_idx(rf)
        hand_center = (self._get_x_idx(lh) + self._get_x_idx(rh)) / 2.0
        foot_center = (lx + rx) / 2.0

        center_offset = abs(hand_center - foot_center)
        if center_offset > 1.0:
            penalty += ((center_offset - 1.0) ** 2) * 35.0

        # 左脚不应长期跑到中线右侧，右脚不应长期跑到中线左侧
        if lx > hand_center + 0.5:
            penalty += ((lx - (hand_center + 0.5)) ** 2) * 45.0
        if rx < hand_center - 0.5:
            penalty += (((hand_center - 0.5) - rx) ** 2) * 45.0

        # “某只脚踩到另一只脚上方近列”会显著增大扭转成本
        if abs(lx - rx) <= 1 and abs(lf.y - rf.y) >= 2:
            penalty += (abs(lf.y - rf.y) - 1) * 18.0

        return penalty

    def _calculate_lateral_and_foot_stability_penalty(self, limbs: Dict[Limb, Optional[Hold]]) -> float:
        """
        对“未超红线但明显难发力”的姿态进行软惩罚：
        1) 手部横向开距过大
        2) 脚部横向开距过大
        3) 双脚上下高差过大
        4) 手脚过近（压缩位形，不利于发力）
        5) 同侧手脚堆叠（LH-LF / RH-RF）
        6) 双脚站位过窄
        7) 身体中轴偏移 / 对侧高踩扭转
        """
        penalty = 0.0
        lh, rh = limbs.get(Limb.LH), limbs.get(Limb.RH)
        lf, rf = limbs.get(Limb.LF), limbs.get(Limb.RF)

        def _grid_distance(h1: Hold, h2: Hold) -> float:
            dx = self._get_x_idx(h1) - self._get_x_idx(h2)
            dy = h1.y - h2.y
            return math.sqrt(dx * dx + dy * dy)

        if lh and rh:
            hand_span = abs(self._get_x_idx(lh) - self._get_x_idx(rh))
            if hand_span > self.SOFT_HAND_SPAN_LIMIT:
                penalty += ((hand_span - self.SOFT_HAND_SPAN_LIMIT) ** 2) * 18.0

        if lf and rf:
            foot_span = abs(self._get_x_idx(lf) - self._get_x_idx(rf))
            foot_vertical_gap = abs(lf.y - rf.y)

            if foot_span > self.SOFT_FOOT_SPAN_LIMIT:
                penalty += ((foot_span - self.SOFT_FOOT_SPAN_LIMIT) ** 2) * 20.0

            if foot_vertical_gap > self.SOFT_FOOT_VERTICAL_GAP_LIMIT:
                penalty += ((foot_vertical_gap - self.SOFT_FOOT_VERTICAL_GAP_LIMIT) ** 2) * 28.0

            # 低脚滞后越明显，越不稳定
            low_foot_lag = max(lf.y, rf.y) - min(lf.y, rf.y)
            if low_foot_lag > 3:
                penalty += (low_foot_lag - 3) * 12.0

            # 双脚过窄会导致站姿发力受限（尤其在两脚几乎同高时）
            if foot_span < 1:
                penalty += 28.0
            elif foot_span < 2:
                penalty += 10.0

            if foot_span <= 1 and foot_vertical_gap <= 1:
                penalty += 18.0

        # 手脚过近惩罚：减少“抱团”姿态
        hands = [h for h in [lh, rh] if h]
        feet = [f for f in [lf, rf] if f]
        for hand in hands:
            for foot in feet:
                hand_foot_dist = _grid_distance(hand, foot)
                if hand_foot_dist < 1.6:
                    penalty += ((1.6 - hand_foot_dist) ** 2) * 55.0

                # 同列近贴额外惩罚：垂直近贴会限制蹬伸空间
                col_gap = abs(self._get_x_idx(hand) - self._get_x_idx(foot))
                row_gap = abs(hand.y - foot.y)
                if col_gap == 0 and row_gap <= 2:
                    penalty += (3 - row_gap) * 12.0

        # 同侧手脚过近（局部堆叠）惩罚
        if lh and lf:
            same_side_gap_left = abs(lh.y - lf.y)
            if same_side_gap_left < 3:
                penalty += (3 - same_side_gap_left) * 16.0

        if rh and rf:
            same_side_gap_right = abs(rh.y - rf.y)
            if same_side_gap_right < 3:
                penalty += (3 - same_side_gap_right) * 16.0

        penalty += self._calculate_torsional_penalty(limbs)
        return penalty

    def _is_two_point_compression(self, limbs: Dict[Limb, Optional[Hold]]) -> bool:
        """
        判定是否处于“双手同点 + 双脚同点，且手脚分居两个点”的压缩姿态。
        即 4 肢总共只占 2 个实体点。
        """
        lh, rh = limbs.get(Limb.LH), limbs.get(Limb.RH)
        lf, rf = limbs.get(Limb.LF), limbs.get(Limb.RF)

        if not (lh and rh and lf and rf):
            return False

        hands_matched = lh.id == rh.id
        feet_matched = lf.id == rf.id
        if not (hands_matched and feet_matched):
            return False

        # 手脚同点在运动学中本就非法，这里保底再防御一次
        return lh.id != lf.id

    def _calculate_two_point_compression_penalty(
        self,
        limbs: Dict[Limb, Optional[Hold]],
        step_count: int,
        top_hold_ids: Set[str]
    ) -> float:
        """
        对“双手同点 + 双脚同点”的两点压缩姿态施加软惩罚。
        设计原则：
        - 起步阶段仅轻惩罚（避免明显降低成线率）
        - 顶点双手 Match 不惩罚（避免误伤完攀）
        - 中段高惩罚（显著降低站不稳姿态概率）
        """
        if not self._is_two_point_compression(limbs):
            return 0.0

        lh, rh = limbs.get(Limb.LH), limbs.get(Limb.RH)
        is_top_match = bool(lh and rh and lh.id == rh.id and lh.id in top_hold_ids)
        if is_top_match:
            return 0.0

        # 起步阶段保留弹性，避免伤及完攀成功率
        if step_count <= 1:
            return 90.0

        # 中段强抑制：随步数略增，鼓励尽快脱离双双 Match
        return 240.0 + min(80.0, step_count * 2.0)

    def _has_better_lower_foothold(
        self,
        current_limbs: Dict[Limb, Optional[Hold]],
        moving_limb: Limb,
        target_hold: Hold,
        candidate_holds: List[Hold]
    ) -> bool:
        """
        如果当前要踩更高脚点，但存在“更接近中线且更稳定”的过渡脚点，
        则优先该过渡脚点（返回 True 表示应放弃当前高点候选）。
        """
        if moving_limb not in [Limb.LF, Limb.RF] or target_hold.hold_type != HoldType.FOOT:
            return False

        current_foot = current_limbs.get(moving_limb)
        if not current_foot or target_hold.y <= current_foot.y:
            return False

        other_limb = Limb.RF if moving_limb == Limb.LF else Limb.LF
        other_foot = current_limbs.get(other_limb)
        body_midline_x = self._get_body_midline_x(current_limbs)

        target_x = self._get_x_idx(target_hold)
        target_horizontal_gap = abs(target_x - self._get_x_idx(other_foot)) if other_foot else 999
        target_vertical_gap = abs(target_hold.y - other_foot.y) if other_foot else 999
        target_midline_dist = abs(target_x - body_midline_x)

        # 左脚应偏中线左侧，右脚应偏中线右侧
        side_bias = -0.25 if moving_limb == Limb.LF else 0.25
        preferred_x = body_midline_x + side_bias
        target_side_dist = abs(target_x - preferred_x)

        for candidate in candidate_holds:
            if candidate.hold_type != HoldType.FOOT:
                continue
            if candidate.id in {target_hold.id, current_foot.id}:
                continue

            # 必须是“比当前脚更高，且不高于目标脚”的稳定中继点
            if not (current_foot.y < candidate.y <= target_hold.y):
                continue

            test_limbs = current_limbs.copy()
            test_limbs[moving_limb] = candidate
            is_valid, _ = self._check_kinematics(test_limbs)
            if not is_valid:
                continue

            if self._is_contralateral_high_step(current_limbs, moving_limb, candidate):
                continue

            if not other_foot:
                return True

            candidate_x = self._get_x_idx(candidate)
            candidate_horizontal_gap = abs(candidate_x - self._get_x_idx(other_foot))
            candidate_vertical_gap = abs(candidate.y - other_foot.y)
            candidate_midline_dist = abs(candidate_x - body_midline_x)
            candidate_side_dist = abs(candidate_x - preferred_x)

            horizontal_better = candidate_horizontal_gap <= target_horizontal_gap
            vertical_better = candidate_vertical_gap <= target_vertical_gap + 1
            midline_better = candidate_midline_dist + 0.25 <= target_midline_dist
            side_better = candidate_side_dist + 0.25 <= target_side_dist

            if horizontal_better and vertical_better and (midline_better or side_better):
                return True

        return False

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
        return [h for h in holds if 16 <= h.y <= 18 and h.hold_type != HoldType.FOOT]

    def _within_reach(
        self,
        limbs: Dict[Limb, Optional[Hold]],
        moving_limb: Limb,
        target_hold: Hold,
    ) -> bool:
        """Apply the product's fixed body-size reach gate before expanding a state."""
        center = self._get_center_of_gravity(limbs)
        if center is None:
            return False
        target_x, target_y = self._coord_to_meters(target_hold.x, target_hold.y)
        limit = self.span_m * 0.8 if moving_limb in (Limb.LH, Limb.RH) else self.height_m * 0.45
        return math.hypot(target_x - center[0], target_y - center[1]) <= limit

    @staticmethod
    def _reason_code(reason: Optional[str]) -> str:
        return {
            "交叉手": "crossed_hands",
            "交叉脚": "crossed_feet",
            "脚不能等于或高于手": "foot_not_below_hands",
            "身体过度伸展": "body_extension_exceeded",
            "身体过度蜷缩": "body_compression_exceeded",
            "双脚离地": "unstable_support",
            "手脚同点": "shared_hand_foot_hold",
            "手部横向跨度过大": "hand_span_exceeded",
            "脚部横向跨度过大": "foot_span_exceeded",
            "脚部上下跨度过大": "foot_vertical_span_exceeded",
        }.get(reason or "", "static_kinematics_failed")

    def validate_static_beta(self, beta_sequence: List[BetaStep], holds: List[Hold]) -> Tuple[bool, Dict]:
        """Replay a Beta using the same hard gates used by A*.

        The returned report is safe for the public explanation layer: it contains
        rule outcomes and evidence codes, but never exposes hidden model reasoning.
        """
        holds_by_id = {hold.id: hold for hold in holds}
        ordered = sorted(enumerate(beta_sequence), key=lambda item: (item[1].step, item[0]))
        start_steps = [step for _, step in ordered if step.step == 0]
        move_steps = [step for _, step in ordered if step.step > 0]
        limbs: Dict[Limb, Optional[Hold]] = {limb: None for limb in Limb}

        for step in start_steps:
            target = holds_by_id.get(step.hold_id)
            if target is None:
                return False, {
                    "reason_code": "missing_hold_reference",
                    "reason": f"动作引用了不存在的岩点 {step.hold_id}。",
                }
            limbs[step.limb] = target
            for limb, hold_id in (
                (Limb.LH, step.lh),
                (Limb.RH, step.rh),
                (Limb.LF, step.lf),
                (Limb.RF, step.rf),
            ):
                if hold_id and hold_id in holds_by_id:
                    limbs[limb] = holds_by_id[hold_id]

        active_hands = [limbs[Limb.LH], limbs[Limb.RH]]
        active_feet = [limbs[Limb.LF], limbs[Limb.RF]]
        if not all(active_hands) or not any(active_feet):
            return False, {
                "reason_code": "unstable_support",
                "reason": "起步状态必须有两手和至少一脚稳定接触。",
            }
        valid, reason = self._check_kinematics(limbs)
        if not valid:
            return False, {
                "reason_code": self._reason_code(reason),
                "reason": f"起步状态未通过静态门禁：{reason}。",
            }

        last_moved_limb: Optional[Limb] = None
        consecutive_hand_moves = 0
        evaluated_states = 1
        for step in move_steps:
            target = holds_by_id.get(step.hold_id)
            if target is None:
                return False, {
                    "reason_code": "missing_hold_reference",
                    "reason": f"动作引用了不存在的岩点 {step.hold_id}。",
                }
            if step.limb == last_moved_limb:
                return False, {
                    "reason_code": "repeated_limb_move",
                    "reason": "同一肢体不得连续重复移动。",
                }

            is_hand_move = step.limb in (Limb.LH, Limb.RH)
            consecutive_hand_moves = consecutive_hand_moves + 1 if is_hand_move else 0
            if consecutive_hand_moves > 2:
                return False, {
                    "reason_code": "too_many_hand_moves",
                    "reason": "连续手部动作超过 2 次，缺少有效脚步推进。",
                }
            if not self._within_reach(limbs, step.limb, target):
                return False, {
                    "reason_code": "reach_exceeded",
                    "reason": "目标岩点超过当前身高或臂展对应的静态触达范围。",
                }

            previous = limbs.get(step.limb)
            if (
                not is_hand_move
                and previous
                and target.y - previous.y > self.MAX_FOOT_MOVE_VERTICAL_DELTA
            ):
                return False, {
                    "reason_code": "high_step_exceeded",
                    "reason": "单次抬脚超过 3 排。",
                }
            if not is_hand_move and self._is_contralateral_high_step(limbs, step.limb, target):
                return False, {
                    "reason_code": "contralateral_high_step",
                    "reason": "检测到禁止的对侧上方高踩。",
                }

            limbs[step.limb] = target
            valid, reason = self._check_kinematics(limbs)
            if not valid:
                return False, {
                    "reason_code": self._reason_code(reason),
                    "reason": f"第 {step.step} 步未通过静态门禁：{reason}。",
                }
            last_moved_limb = step.limb
            evaluated_states += 1

        top_ids = {hold.id for hold in self._get_top_holds(holds)}
        left_hand = limbs.get(Limb.LH)
        right_hand = limbs.get(Limb.RH)
        if not (
            left_hand
            and right_hand
            and left_hand.id == right_hand.id
            and left_hand.id in top_ids
        ):
            return False, {
                "reason_code": "no_static_top_path",
                "reason": "动作路径没有在 Y16–Y18 的非脚点完成双手登顶。",
            }

        return True, {
            "reason_code": "static_movement_passed",
            "reason": "完整动作路径通过静态人体工学门禁。",
            "evaluated_states": evaluated_states,
            "passed_rules": [
                "no_crossed_hands",
                "no_crossed_feet",
                "feet_below_hands",
                "body_size_reach",
                "body_extension",
                "foot_step_height",
                "stable_support",
                "movement_sequence",
                "double_hand_top",
            ],
            "body_profile": {
                "height_cm": round(self.height_m * 100),
                "span_cm": round(self.span_m * 100),
                "hand_reach_limit_m": round(self.span_m * 0.8, 2),
                "foot_reach_limit_m": round(self.height_m * 0.45, 2),
            },
        }

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

        # 拒绝手脚同时在一个点
        hands = [h for h in [lh, rh] if h]
        feet = [f for f in [lf, rf] if f]
        for h in hands:
            for f in feet:
                if h.id == f.id:
                    return False, "手脚同点"

        if lh and rh and lh.id != rh.id and get_x_idx(Limb.LH) > get_x_idx(Limb.RH): 
            return False, "交叉手"
        
        if lf and rf and lf.id != rf.id and get_x_idx(Limb.LF) > get_x_idx(Limb.RF): 
            return False, "交叉脚"

        active_feet_y = [y for y in [get_y(Limb.LF), get_y(Limb.RF)] if y > 0]
        if not active_feet_y: 
            return False, "双脚离地"
        
        min_hand_y = min(get_y(Limb.LH), get_y(Limb.RH)) if get_hold(Limb.LH) and get_hold(Limb.RH) else (get_y(Limb.LH) or get_y(Limb.RH))
        max_foot_y = max(active_feet_y)
        if max_foot_y >= min_hand_y: 
            return False, "脚不能等于或高于手"

        max_hand_y = max(get_y(Limb.LH), get_y(Limb.RH))
        min_foot_y = min(active_feet_y)
        
        body_span = max_hand_y - min_foot_y
        max_extension_units = (self.height_m * 1.25) / self.GRID_SPACING

        if body_span > max_extension_units:
            return False, "身体过度伸展"

        if lh and rh and abs(get_x_idx(Limb.LH) - get_x_idx(Limb.RH)) > 6: 
            return False, "手部横向跨度过大"
        if lf and rf and abs(get_x_idx(Limb.LF) - get_x_idx(Limb.RF)) > 4: 
            return False, "脚部横向跨度过大"
        if lf and rf and abs(get_y(Limb.LF) - get_y(Limb.RF)) > self.HARD_FOOT_VERTICAL_GAP_LIMIT:
            return False, "脚部上下跨度过大"

        return True, None

    def solve(self, board_holds: List[Hold], inventory_budget: Dict[HoldType, int] = None) -> Tuple[Optional[RouteCandidate], Dict]:
        max_y_reached = 0

        # 配方预算是硬约束：若未提供，按空预算处理（即不允许新增任何点）
        inventory_budget = inventory_budget or {}

        def get_quota_violations(final_holds: List[Hold]) -> Dict[HoldType, int]:
            """统计最终路线中各类型岩点是否超出配额。"""
            quota_violations = {}
            from collections import Counter

            final_counts = Counter(h.hold_type for h in final_holds)
            for ht, count in final_counts.items():
                required = inventory_budget.get(ht, 0)
                if count > required:
                    quota_violations[ht] = count - required
            return quota_violations
        
        def failure_report(reason: str, rule: Optional[str] = None):
            return None, {"reason": reason, "max_y": max_y_reached, "rule_violation": rule}

        if not board_holds:
            return failure_report("传入的板为空")

        all_holds_map = {h.id: h for h in board_holds}
        top_holds = self._get_top_holds(board_holds)
        top_hold_ids = {h.id for h in top_holds}
        if not top_holds:
            return failure_report("没有找到完攀点")

        # 获取所有预设的起步点 (由 generator 严格生成并标记)
        start_holds = [h for h in board_holds if h.is_start]
        start_hands = sorted([h for h in start_holds if h.hold_type != HoldType.FOOT], key=lambda h: h.y)
        start_feet = sorted([h for h in start_holds if h.hold_type == HoldType.FOOT], key=lambda h: h.y)

        if len(start_hands) < 1 or len(start_feet) < 1:
            return failure_report("未找到合法的起步点标记配置")

        initial_state = None
        initial_limbs = {}

        # 严格按照 generator 的 5 种起步模板还原分配
        # 如果只有 1 个手点，必然是模式 1（双手同点）
        if len(start_hands) == 1:
            initial_limbs[Limb.LH] = start_hands[0]
            initial_limbs[Limb.RH] = start_hands[0]
        elif len(start_hands) >= 2:
            # 区分左右手，x 坐标小的为左手
            h1, h2 = start_hands[0], start_hands[1]
            lh, rh = (h1, h2) if ord(h1.x) <= ord(h2.x) else (h2, h1)
            initial_limbs[Limb.LH] = lh
            initial_limbs[Limb.RH] = rh

        # 如果只有 1 个脚点，必然是模式 2（双脚同点）
        if len(start_feet) == 1:
            initial_limbs[Limb.LF] = start_feet[0]
            initial_limbs[Limb.RF] = start_feet[0]
        elif len(start_feet) >= 2:
            # 区分左右脚，x 坐标小的为左脚
            f1, f2 = start_feet[0], start_feet[1]
            lf, rf = (f1, f2) if ord(f1.x) <= ord(f2.x) else (f2, f1)
            initial_limbs[Limb.LF] = lf
            initial_limbs[Limb.RF] = rf

        is_kinematic, _ = self._check_kinematics(initial_limbs)
        if is_kinematic:
            active_limbs = {l: h for l, h in initial_limbs.items() if h}
            if len(active_limbs) >= 3:
                # V7 逻辑：在 A* 开始前，预先扣除起步点所消耗的配额
                initial_inventory = inventory_budget.copy()
                unique_start_holds = {hold.id: hold for hold in active_limbs.values()}.values()
                for hold in unique_start_holds:
                    initial_inventory[hold.hold_type] = initial_inventory.get(hold.hold_type, 0) - 1
                
                # 如果任何岩点类型的配额变为负数，则这是一个无效的起步姿态
                if not any(count < 0 for count in initial_inventory.values()):
                    # 在起步 Step 中也记录全肢体状态
                    start_sequence = []
                    for limb, hold in active_limbs.items():
                        step_obj = BetaStep(
                            step=0, 
                            limb=limb, 
                            hold_id=hold.id, 
                            intent="Start",
                            lh=initial_limbs.get(Limb.LH).id if initial_limbs.get(Limb.LH) else None,
                            rh=initial_limbs.get(Limb.RH).id if initial_limbs.get(Limb.RH) else None,
                            lf=initial_limbs.get(Limb.LF).id if initial_limbs.get(Limb.LF) else None,
                            rf=initial_limbs.get(Limb.RF).id if initial_limbs.get(Limb.RF) else None
                        )
                        start_sequence.append(step_obj)
                        
                    initial_state = State(
                        limbs=initial_limbs, 
                        g_cost=0.0, 
                        h_cost=0.0, 
                        step_count=0, 
                        sequence=start_sequence, 
                        inventory_left=initial_inventory,
                        last_moved_limb=None,
                        limb_idle_steps={l: 0 for l in Limb}
                    )

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

            # 优化存储：确保 closed_set 记录的状态包含 (肢体配置, 剩余配方) 的元组
            # 目的：防止 AI 在相同的岩点组合上反复进行无效的换手/换脚尝试
            limb_config = tuple(sorted((l.name, h.id) for l, h in current.limbs.items() if h))
            inventory_config = tuple(sorted(current.inventory_left.items()))
            state_hash = (limb_config, inventory_config)
            
            if state_hash in closed_set: continue
            closed_set.add(state_hash)

            # 检查完攀：双手 Match 在同一个顶峰点
            lh_hold = current.limbs.get(Limb.LH)
            rh_hold = current.limbs.get(Limb.RH)
            if lh_hold and rh_hold and lh_hold.id == rh_hold.id and lh_hold in top_holds:
                final_sequence = current.sequence
                used_hold_ids = {step.hold_id for step in final_sequence}
                final_holds = [h for h in board_holds if h.id in used_hold_ids]

                # 最终防线：一旦超配额，直接丢弃该完攀状态，继续搜索其他合法路径
                quota_violations = get_quota_violations(final_holds)
                if quota_violations:
                    continue

                # V10: 长度软上限 (Soft Cap)
                if len(final_holds) > 15:
                    current.g_cost += (len(final_holds) - 15) * 10.0

                # 赋予极高的完攀奖励 (Finishing Lust)
                current.g_cost -= 5000.0

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
                ), {"reason": "成功", "max_y": lh_hold.y, "rule_violation": None}

            # --- V9: 弹簧蓄力驱动的子节点生成 ---
            current_cg = self._get_center_of_gravity(current.limbs)
            if not current_cg: continue
            current_is_two_point = self._is_two_point_compression(current.limbs)

            for limb in Limb:
                is_hand_move = limb in [Limb.LH, Limb.RH]
                current_limb_hold = current.limbs.get(limb)
                
                if current.last_moved_limb == limb:
                    continue
                # V12 动态核心：以重心 (CG) 为锚点进行大范围扫描，物理判定后置
                max_reach = self.span_m * 1.5 # 设定一个极大的扫描半径
                cg_x_m, cg_y_m = current_cg
                
                potential_holds = []
                for h in board_holds:
                    h_x_m, h_y_m = self._coord_to_meters(h.x, h.y)
                    # 快速过滤掉绝对不可能的点
                    if abs(h_x_m - cg_x_m) > max_reach or abs(h_y_m - cg_y_m) > max_reach:
                        continue
                    potential_holds.append(h)

                for target_hold in potential_holds:
                    if current_limb_hold and current_limb_hold.id == target_hold.id: continue
                    if target_hold.hold_type == HoldType.FOOT and is_hand_move: continue
                    if not self._within_reach(current.limbs, limb, target_hold):
                        kinematic_failure_counts["触达超限"] = kinematic_failure_counts.get("触达超限", 0) + 1
                        continue
                    if is_hand_move and current.consecutive_hand_moves >= 2:
                        kinematic_failure_counts["连续手部动作过多"] = kinematic_failure_counts.get("连续手部动作过多", 0) + 1
                        continue

                    # 单次脚步上提硬限制：脚在一次移动中，垂直上升不能超过 4 格
                    if (
                        (not is_hand_move)
                        and current_limb_hold
                        and (target_hold.y - current_limb_hold.y) > self.MAX_FOOT_MOVE_VERTICAL_DELTA
                    ):
                        continue

                    # 强拦截：禁止脚步跨到对侧脚的上方/近列上方，避免身体过横
                    if (not is_hand_move) and self._is_contralateral_high_step(current.limbs, limb, target_hold):
                        continue

                    # 低位已确定脚点优先：存在更低且可稳定的脚点时，跳过更高脚点
                    if (not is_hand_move) and self._has_better_lower_foothold(current.limbs, limb, target_hold, potential_holds):
                        continue
                    
                    new_limbs = current.limbs.copy()
                    new_limbs[limb] = target_hold

                    is_kinematic, reason = self._check_kinematics(new_limbs)
                    if not is_kinematic:
                        kinematic_failure_counts[reason] = kinematic_failure_counts.get(reason, 0) + 1
                        continue

                    new_is_two_point = self._is_two_point_compression(new_limbs)
                    two_point_penalty = self._calculate_two_point_compression_penalty(
                        new_limbs,
                        current.step_count + 1,
                        top_hold_ids
                    )
                    
                    body_pos_cost = self._calculate_body_position_cost(new_limbs)
                    stability_penalty = self._calculate_lateral_and_foot_stability_penalty(new_limbs)
                    total_penalty = 0

                    # 脱离“两点压缩态”奖励：鼓励尽快恢复到 >=3 点支撑结构
                    if current_is_two_point and not new_is_two_point:
                        total_penalty -= 35.0
                    
                    is_new_hold = not any(h and h.id == target_hold.id for h in current.limbs.values())
                    new_inventory = current.inventory_left.copy()
                    if is_new_hold:
                        remaining = new_inventory.get(target_hold.hold_type, 0)
                        # 硬约束：禁止在配额耗尽后继续引入新岩点
                        if remaining <= 0:
                            continue
                        total_penalty -= 40.0  # 配额内使用新点奖励
                        new_inventory[target_hold.hold_type] = remaining - 1

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

                    # 肢体静止惩罚 (Lazy Penalty)
                    for l in Limb:
                        if l != limb and current.limb_idle_steps[l] >= 3:
                            total_penalty += 10.0
                    
                    # 交替移动奖励 (Alternating Reward)
                    is_foot_move = limb in [Limb.LF, Limb.RF]
                    if is_foot_move and current.last_moved_limb in [Limb.LF, Limb.RF] and current.last_moved_limb != limb:
                        total_penalty -= 5.0

                    predicted_cg = self._get_center_of_gravity(new_limbs)
                    
                    active_feet = [new_limbs.get(Limb.LF), new_limbs.get(Limb.RF)]
                    active_feet = [f for f in active_feet if f]
                    min_foot_y_m = min(self._coord_to_meters(f.x, f.y)[1] for f in active_feet) if active_feet else 0
                    
                    reach_cost = self._calculate_reach_cost(predicted_cg, target_hold, limb, min_foot_y_m)
                    hold_type_cost = self.HOLD_COST_WEIGHTS.get(target_hold.hold_type, 1.0)
                    rotation_penalty = self._calculate_rotation_penalty(target_hold)
                    
                    step_cost = reach_cost + hold_type_cost + rotation_penalty + total_penalty + body_pos_cost
                    if step_cost > max_single_step_cost: max_single_step_cost = step_cost
                    
                    new_sequence = current.sequence[:]
                    # 抓取当前所有肢体位置，确保 rf 等数据不丢失
                    limb_state = {
                        "lh": new_limbs.get(Limb.LH).id if new_limbs.get(Limb.LH) else None,
                        "rh": new_limbs.get(Limb.RH).id if new_limbs.get(Limb.RH) else None,
                        "lf": new_limbs.get(Limb.LF).id if new_limbs.get(Limb.LF) else None,
                        "rf": new_limbs.get(Limb.RF).id if new_limbs.get(Limb.RF) else None,
                    }
                    new_sequence.append(BetaStep(
                        step=current.step_count + 1, 
                        limb=limb, 
                        hold_id=target_hold.id, 
                        intent="Move",
                        **limb_state
                    ))
                    
                    active_hands = [new_limbs.get(Limb.LH), new_limbs.get(Limb.RH)]
                    active_hands = [h for h in active_hands if h]
                    highest_hand_hold = max(active_hands, key=lambda h: self._coord_to_meters(h.x, h.y)[1], default=None)
                    
                    # 启发式函数演进：引入「协同重力」 (h_cost)
                    # 修改公式：h_cost = (左手至顶距离 + 右手至顶距离) * 权重 + (重心至顶垂直距离) * 权重
                    h_cost = 0.0
                    if top_holds:
                        lh_hold = new_limbs.get(Limb.LH)
                        rh_hold = new_limbs.get(Limb.RH)
                        
                        dist_lh = min(self._distance(lh_hold, top) for top in top_holds) if lh_hold else self.GRID_HEIGHT * self.GRID_SPACING
                        dist_rh = min(self._distance(rh_hold, top) for top in top_holds) if rh_hold else self.GRID_HEIGHT * self.GRID_SPACING
                        
                        # V12 核心修正：移除权重爆炸，回归距离本质
                        current_y_max = max(h.y for h in new_limbs.values() if h) # 保留 current_y_max 用于提脚奖励
                        hand_weight = 20.0
                        cg_weight = 10.0
                            
                        h_cost = (dist_lh + dist_rh) * hand_weight
                        h_cost += (self.GRID_HEIGHT * self.GRID_SPACING - predicted_cg[1]) * cg_weight
                        
                        # 引入脚部引导：强迫 AI 提升留在底部的脚
                        # 将 None 视为高度 0，强制双脚都必须上墙并提升高度
                        lf_y = new_limbs.get(Limb.LF).y if new_limbs.get(Limb.LF) else 0
                        rf_y = new_limbs.get(Limb.RF).y if new_limbs.get(Limb.RF) else 0
                        min_foot_y = min(lf_y, rf_y)
                        # 脚部高度的惩罚系数大幅提高
                        h_cost += (self.GRID_HEIGHT * self.GRID_SPACING - min_foot_y * self.GRID_SPACING) * (cg_weight * 2.0)

                    # 完攀奖金 (Match Bonus)
                    if lh_hold and rh_hold and lh_hold.id == rh_hold.id and lh_hold in top_holds:
                        step_cost -= 2000.0

                    # 动作合理性：奖励「重心推进」而非「肢体跨越」
                    # 重心奖励：如果动作导致重心（CG）向上移动，给予小额奖励（-5.0）
                    if predicted_cg[1] > current_cg[1] + 0.01: # 稍微显著的移动
                        step_cost -= 5.0
                    
                    # --- 高位提脚奖励 (High-Level Foot Move Reward) ---
                    # 当身在高处且身体跨度较大时，只要向上提脚，就给予巨额代金券
                    if not is_hand_move and y_progress > 0:
                        current_max_y = max(h.y for h in current.limbs.values() if h)
                        current_body_span = max(h.y for h in current.limbs.values() if h) - min(h.y for h in current.limbs.values() if h)
                        if current_max_y > 8: # V12 修正：下调提脚奖励门槛
                            # 跨度越大，提脚奖励越高
                            span_bonus = max(0, (current_body_span - 6) * 15.0)
                            step_cost -= (30.0 + span_bonus)

                        # 优先补低脚：如果移动的是当前较低的一只脚并向上提，额外奖励
                        current_lf = current.limbs.get(Limb.LF)
                        current_rf = current.limbs.get(Limb.RF)
                        if current_lf and current_rf:
                            lower_foot_limb = Limb.LF if current_lf.y <= current_rf.y else Limb.RF
                            if limb == lower_foot_limb:
                                step_cost -= 15.0

                    # 双脚支撑奖金：当两只脚都处于 Y > 1 的活跃状态时，降低整体动作代价
                    lf_hold = new_limbs.get(Limb.LF)
                    rf_hold = new_limbs.get(Limb.RF)
                    if lf_hold and rf_hold and lf_hold.y > 1 and rf_hold.y > 1:
                        step_cost *= 0.8 # 20% 的动作代价减免

                    # 将稳定性惩罚在末端统一加回，避免被前面的奖励完全抵消
                    step_cost += stability_penalty + two_point_penalty

                    new_consecutive_hand_moves = (current.consecutive_hand_moves + 1) if is_hand_move else 0
                    new_limb_idle_steps = {l: (0 if l == limb else current.limb_idle_steps[l] + 1) for l in Limb}

                    heapq.heappush(open_list, State(
                        limbs=new_limbs,
                        g_cost=current.g_cost + step_cost,
                        h_cost=h_cost,
                        step_count=current.step_count + 1,
                        sequence=new_sequence,
                        inventory_left=new_inventory,
                        last_moved_limb=limb,
                        limb_idle_steps=new_limb_idle_steps,
                        consecutive_hand_moves=new_consecutive_hand_moves,
                        y_progress_since_foot_move=y_progress_since_foot_move
                    ))

        if best_state_so_far and max_y_reached >= 16:
            return failure_report("没有找到完整静态完攀路径", "无静态完攀路径")

        most_common_violation = max(kinematic_failure_counts, key=kinematic_failure_counts.get) if kinematic_failure_counts else "无"
        return failure_report(f"A* 搜索超时 ({max_iterations} 次迭代)", most_common_violation)
