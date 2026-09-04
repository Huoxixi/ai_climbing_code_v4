"""Purposeful fixed-route search for the climbing simulation.

The solver treats route holds as an allowed contact set. Intermediate holds are
optional, and the lexicographic search prefers fewer movements before posture
and fatigue costs.
"""

from __future__ import annotations

import heapq
import itertools
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from core.models import ClimberProfile, Hold, HoldPhysicsProfile, HoldType, StandardBoardRouteDetail
from core.simulation_physics import (
    BodyDimensions,
    DynamicEvaluation,
    MAX_STATIC_JOINT_SPEED,
    PoseEvaluation,
    StateEvaluation,
    contact_point,
    coord,
    evaluate_pose_contacts,
    evaluate_state,
    evaluate_state_candidates,
    normal_bend_is_valid,
    reachable_from_root,
    solve_dynamic_trajectory,
    validate_static_pose_transition,
)


LIMB_KEYS = ("lh", "rh", "lf", "rf")
HAND_KEYS = ("lh", "rh")
FOOT_KEYS = ("lf", "rf")
State = Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]
MAX_FOOT_MOVE_ROWS = 4
DEFAULT_SEARCH_BUDGET = 25_000


def state_dict(state: State) -> Dict[str, Optional[str]]:
    return dict(zip(LIMB_KEYS, state))


def state_tuple(contacts: Dict[str, Optional[str]]) -> State:
    return tuple(contacts.get(key) for key in LIMB_KEYS)  # type: ignore[return-value]


@dataclass
class MotionAction:
    limb: str
    target_id: str
    action_type: str = "static_move"
    purpose: str = ""
    dynamic: bool = False
    moving_limbs: Tuple[str, ...] = field(default_factory=tuple)
    technique: str = "direct_reach"
    support_limbs: Tuple[str, ...] = field(default_factory=tuple)
    drive_limbs: Tuple[str, ...] = field(default_factory=tuple)
    preparation_required: bool = False
    duration_seconds: float = 0.0
    to_state: Optional[State] = None
    dynamic_evaluation: Optional[DynamicEvaluation] = None
    support_evaluation: Optional[StateEvaluation] = None
    preparation_pose: Optional[PoseEvaluation] = None


@dataclass
class BetaPath:
    start_state: State
    actions: List[MotionAction]
    states: List[State]
    evaluations: List[StateEvaluation]
    fatigue: float
    peak_stress: float
    dynamic_action_count: int = 0

    @property
    def signature(self) -> Tuple[Tuple[str, str, str], ...]:
        return tuple((action.action_type, action.limb, action.target_id) for action in self.actions)


@dataclass
class SearchOutcome:
    paths: List[BetaPath]
    search_complete: bool
    expanded_states: int
    rejection_counts: Counter
    frontier_paths: List[BetaPath]


@dataclass
class SolveOutcome:
    solution_mode: str
    paths: List[BetaPath]
    search_complete: bool
    expanded_states: int
    rejection_counts: Counter
    dynamic_feasibility_score: float = 0.0


@dataclass
class StaticTransition:
    next_state: State
    landing: StateEvaluation
    support: StateEvaluation
    adjustment_penalty: float
    fatigue_increment: float
    purpose: str
    technique: str
    support_limbs: Tuple[str, ...]
    drive_limbs: Tuple[str, ...]
    preparation_required: bool
    duration_seconds: float


@dataclass(order=True)
class _QueueNode:
    priority: Tuple[int, int, int, float, float, int]
    state: State = field(compare=False)
    start_state: State = field(compare=False)
    actions: List[MotionAction] = field(compare=False, default_factory=list)
    states: List[State] = field(compare=False, default_factory=list)
    evaluations: List[StateEvaluation] = field(compare=False, default_factory=list)
    penalty: float = field(compare=False, default=0.0)
    fatigue: float = field(compare=False, default=0.0)
    peak_stress: float = field(compare=False, default=0.0)
    dynamic_action_count: int = field(compare=False, default=0)
    waste_count: int = field(compare=False, default=0)
    hand_cycles: int = field(compare=False, default=0)
    consecutive_hands: int = field(compare=False, default=0)
    prepared_by_foot: bool = field(compare=False, default=False)
    last_limb: Optional[str] = field(compare=False, default=None)


class RouteSimulationSolver:
    def __init__(
        self,
        detail: StandardBoardRouteDetail,
        profile: ClimberProfile,
        hold_profiles: Dict[str, HoldPhysicsProfile],
        search_budget: int = DEFAULT_SEARCH_BUDGET,
    ):
        self.detail = detail
        self.profile = profile
        self.body_dimensions = BodyDimensions.from_profile(profile)
        self.hold_profiles = hold_profiles
        self.search_budget = search_budget
        self.setup = {hold.id: hold for hold in detail.board_setup}
        self.allowed_ids = self._ordered_unique(
            detail.roles.get("start", []) + detail.roles.get("mid", []) + detail.roles.get("end", [])
        )
        self.allowed_set = set(self.allowed_ids)
        self.end_ids = self._ordered_unique(detail.roles.get("end", []))
        self.hand_targets = [
            hold_id
            for hold_id in self.allowed_ids
            if self.setup.get(hold_id) and self.setup[hold_id].hold_type != HoldType.FOOT
        ]
        self.foot_targets = list(self.allowed_ids)
        self._state_cache: Dict[State, StateEvaluation] = {}
        self._candidate_cache: Dict[State, List[StateEvaluation]] = {}
        self._transition_cache: Dict[
            Tuple[State, str, str, str, bool, int, bool],
            Optional[StaticTransition],
        ] = {}
        self._transition_rejections: Dict[
            Tuple[State, str, str, str, bool, int, bool],
            str,
        ] = {}

    @staticmethod
    def _ordered_unique(values: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _physics_for(self, hold: Hold) -> Optional[HoldPhysicsProfile]:
        if hold.variant in self.hold_profiles:
            return self.hold_profiles[hold.variant]
        return next((item for item in self.hold_profiles.values() if item.hold_type == hold.hold_type), None)

    def evaluate(self, state: State) -> StateEvaluation:
        if state not in self._state_cache:
            self._state_cache[state] = evaluate_state(state_dict(state), self.profile, self.setup, self.hold_profiles)
        return self._state_cache[state]

    def _all_candidates(self, state: State) -> List[StateEvaluation]:
        if state not in self._candidate_cache:
            self._candidate_cache[state] = evaluate_state_candidates(
                state_dict(state),
                self.profile,
                self.setup,
                self.hold_profiles,
                limit=6,
            )
        return self._candidate_cache[state]

    def evaluate_candidates(self, state: State) -> List[StateEvaluation]:
        return self._all_candidates(state)[:4]

    def _continuous_candidates(
        self,
        state: State,
        previous_pose: PoseEvaluation,
    ) -> List[StateEvaluation]:
        candidates = []
        for evaluation in self._all_candidates(state):
            pelvis_shift = float(np.linalg.norm(evaluation.pose.hip - previous_pose.hip))
            shoulder_shift = float(np.linalg.norm(evaluation.pose.shoulder - previous_pose.shoulder))
            depth_shift = abs(
                evaluation.pose.shoulder_wall_distance - previous_pose.shoulder_wall_distance
            ) + abs(evaluation.pose.hip_wall_distance - previous_pose.hip_wall_distance)
            if pelvis_shift > 0.72 or shoulder_shift > 0.72 or depth_shift > 0.32:
                continue
            bend_change_cost = 6.0 * sum(
                previous_pose.bend_directions.get(limb)
                != evaluation.pose.bend_directions.get(limb)
                for limb in LIMB_KEYS
            )
            continuity_cost = (
                pelvis_shift * 9.0
                + shoulder_shift * 7.0
                + depth_shift * 5.0
                + bend_change_cost
            )
            candidates.append((continuity_cost + evaluation.pose.posture_cost, evaluation))
        candidates.sort(key=lambda item: (item[0], item[1].pose.pose_id))
        return [evaluation for _, evaluation in candidates[:6]]

    def _start_states(self) -> List[State]:
        marker = self.detail.validation.get("marker_summary", {})
        start_hands = self._ordered_unique(marker.get("start_hands", []))
        start_feet = self._ordered_unique(marker.get("start_feet", []))
        if not start_hands or not start_feet:
            return []
        if len(start_hands) == 1:
            hand_assignments = [(start_hands[0], start_hands[0])]
        else:
            hand_assignments = list(itertools.permutations(start_hands[:2], 2))
        if len(start_feet) == 1:
            foot_assignments = [(start_feet[0], None), (None, start_feet[0])]
        else:
            foot_assignments = list(itertools.permutations(start_feet[:2], 2))
        candidates = [
            (hands[0], hands[1], feet[0], feet[1])
            for hands in hand_assignments
            for feet in foot_assignments
        ]
        valid = [state for state in candidates if self._state_contact_rules(state) is None and self.evaluate(state).valid]
        return sorted(valid, key=lambda state: self.evaluate(state).pose.posture_cost)

    def _state_contact_rules(self, state: State) -> Optional[str]:
        contacts = state_dict(state)
        for hold_id in contacts.values():
            if hold_id and hold_id not in self.allowed_set:
                return "线路外岩点"
        for key in HAND_KEYS:
            hold_id = contacts.get(key)
            if hold_id and self.setup.get(hold_id) and self.setup[hold_id].hold_type == HoldType.FOOT:
                return "手部使用了专用脚点"
            if hold_id and self.setup.get(hold_id):
                physics = self._physics_for(self.setup[hold_id])
                if physics and physics.usable_by == "foot":
                    return "手部使用了仅供脚使用的岩点"
        for key in FOOT_KEYS:
            hold_id = contacts.get(key)
            if hold_id and self.setup.get(hold_id):
                physics = self._physics_for(self.setup[hold_id])
                if physics and physics.usable_by == "hand":
                    return "脚部使用了仅供手使用的岩点"
        if not any(contacts.get(key) for key in HAND_KEYS):
            return "缺少手部接触"
        if not any(contacts.get(key) for key in FOOT_KEYS):
            return "缺少脚部接触"
        if (
            contacts.get("lh")
            and contacts.get("rh")
            and contacts["lh"] != contacts["rh"]
            and contact_point(contacts["lh"], "lh", self.setup, self.hold_profiles)[0]
            > contact_point(contacts["rh"], "rh", self.setup, self.hold_profiles)[0] + 1e-6
        ):
            return "左右手交叉"
        if (
            contacts.get("lf")
            and contacts.get("rf")
            and contacts["lf"] != contacts["rf"]
            and contact_point(contacts["lf"], "lf", self.setup, self.hold_profiles)[0]
            > contact_point(contacts["rf"], "rf", self.setup, self.hold_profiles)[0] + 1e-6
        ):
            return "左右脚交叉"
        return None

    def _is_goal(self, state: State) -> bool:
        contacts = state_dict(state)
        if not self.end_ids:
            return False
        if len(self.end_ids) == 1:
            return contacts["lh"] == self.end_ids[0] and contacts["rh"] == self.end_ids[0]
        return {contacts["lh"], contacts["rh"]} == set(self.end_ids[:2])

    def _limb_lengths(self, limb: str) -> Tuple[float, float]:
        if limb in HAND_KEYS:
            return (
                self.body_dimensions.upper_arm,
                self.body_dimensions.forearm_hand,
            )
        return self.body_dimensions.thigh, self.body_dimensions.shin

    @staticmethod
    def _root_key(limb: str) -> str:
        return {
            "lh": "left_shoulder",
            "rh": "right_shoulder",
            "lf": "left_hip",
            "rf": "right_hip",
        }[limb]

    def _purpose_for(self, limb: str, previous: Optional[str], target_id: str, state: State) -> str:
        if limb in HAND_KEYS and target_id in self.end_ids:
            other = "rh" if limb == "lh" else "lh"
            if state_dict(state).get(other) == target_id:
                return "双手匹配并控制终点"
            return "直接推进到终点"
        if limb in FOOT_KEYS:
            return "建立下一步脚撑"
        if previous and int(target_id[1:]) <= int(previous[1:]):
            return "调整身体位置"
        return "直接推进手点"

    def _reject_transition(
        self,
        cache_key: Tuple[State, str, str, str, bool, int, bool],
        reason: str,
    ) -> None:
        self._transition_cache[cache_key] = None
        self._transition_rejections[cache_key] = reason

    def _foot_contributes(
        self,
        contacts: Dict[str, Optional[str]],
        next_contacts: Dict[str, Optional[str]],
        limb: str,
        current: StateEvaluation,
        landing: StateEvaluation,
    ) -> bool:
        previous = contacts.get(limb)
        target_id = next_contacts.get(limb)
        if not target_id:
            return False
        if not previous:
            return len({value for value in next_contacts.values() if value}) > len(
                {value for value in contacts.values() if value}
            )
        previous_point = contact_point(previous, limb, self.setup, self.hold_profiles)
        target_point = contact_point(target_id, limb, self.setup, self.hold_profiles)
        if target_point[1] >= previous_point[1] + 0.19:
            return True
        previous_row = int(previous[1:])
        target_row = int(target_id[1:])
        for future_id in self.foot_targets:
            future_row = int(future_id[1:])
            if not 0 < future_row - target_row <= MAX_FOOT_MOVE_ROWS:
                continue
            if future_row - previous_row > MAX_FOOT_MOVE_ROWS:
                return True
        hand_points = [
            contact_point(hold_id, key, self.setup, self.hold_profiles)
            for key, hold_id in contacts.items()
            if key in HAND_KEYS and hold_id
        ]
        if hand_points:
            hand_center_x = float(np.mean([point[0] for point in hand_points]))
            if abs(target_point[0] - hand_center_x) + 0.06 < abs(previous_point[0] - hand_center_x):
                return True
        if landing.stress + 0.03 < current.stress:
            return True
        if landing.pose.posture_cost + 0.7 < current.pose.posture_cost:
            return True
        if landing.load.peak_ratio + 0.05 < current.load.peak_ratio:
            return True
        other = "rf" if limb == "lf" else "lf"
        other_hold = contacts.get(other)
        if other_hold:
            other_point = contact_point(other_hold, other, self.setup, self.hold_profiles)
            old_gap = abs(previous_point[1] - other_point[1])
            new_gap = abs(target_point[1] - other_point[1])
            if new_gap + 0.10 < old_gap:
                return True
        return False

    def _technique_for(
        self,
        limb: str,
        previous: Optional[str],
        target_id: str,
        landing: StateEvaluation,
        is_match: bool,
        preparation_required: bool,
    ) -> str:
        if is_match:
            return "hand_match" if limb in HAND_KEYS else "foot_match"
        if limb in HAND_KEYS:
            if preparation_required:
                return "leg_drive_reach"
            if previous and abs(ord(target_id[0]) - ord(previous[0])) >= 2:
                return "weight_shift_reach"
            return "direct_reach"

        vertical_rows = int(target_id[1:]) - int(previous[1:]) if previous else 0
        knee_angle = landing.pose.joint_angles.get(limb, 180.0)
        hip_point = landing.pose.roots.get(limb)
        target = contact_point(target_id, limb, self.setup, self.hold_profiles)
        side = -1.0 if limb == "lf" else 1.0
        outside_hip = bool(hip_point is not None and (target[0] - hip_point[0]) * side > 0.12)
        if vertical_rows >= 2 and knee_angle <= 82.0:
            return "drop_knee"
        if outside_hip and abs(landing.pose.torso_angle_degrees) >= 8.0:
            return "backstep"
        if vertical_rows >= 2 and hip_point is not None and landing.pose.hip[1] > target[1] + 0.12:
            return "rock_over"
        if vertical_rows >= 2:
            return "high_step"
        return "step_up"

    def _transition(
        self,
        state: State,
        limb: str,
        target_id: str,
        current_evaluation: Optional[StateEvaluation] = None,
        prepared_by_foot: bool = False,
        consecutive_hands: int = 0,
        full_validation: bool = False,
    ) -> Optional[StaticTransition]:
        current = current_evaluation or self.evaluate(state)
        cache_key = (
            state,
            current.pose.pose_id,
            limb,
            target_id,
            prepared_by_foot,
            consecutive_hands,
            full_validation,
        )
        if cache_key in self._transition_cache:
            return self._transition_cache[cache_key]
        contacts = state_dict(state)
        previous = contacts.get(limb)
        if not target_id or target_id not in self.allowed_set or previous == target_id:
            self._reject_transition(cache_key, "duplicate_or_outside_target")
            return None
        target_hold = self.setup.get(target_id)
        if not target_hold:
            self._reject_transition(cache_key, "missing_target_hold")
            return None
        if limb in HAND_KEYS and target_hold.hold_type == HoldType.FOOT:
            self._reject_transition(cache_key, "hand_on_foot_only_hold")
            return None
        if limb in FOOT_KEYS:
            if previous and int(target_id[1:]) - int(previous[1:]) > MAX_FOOT_MOVE_ROWS:
                self._reject_transition(cache_key, "foot_move_over_four_rows")
                return None
        first, second = self._limb_lengths(limb)
        movement_distance = (
            float(
                np.linalg.norm(
                    contact_point(target_id, limb, self.setup, self.hold_profiles)
                    - contact_point(previous, limb, self.setup, self.hold_profiles)
                )
            )
            if previous
            else 0.0
        )
        movement_limit = (
            self.profile.arm_span_cm / 100.0 * 0.78
            if limb in HAND_KEYS
            else (first + second) * 1.28
        )
        if movement_distance > movement_limit:
            self._reject_transition(cache_key, "limb_transfer_too_far")
            return None

        support_contacts = dict(contacts)
        support_contacts[limb] = None
        support_state = state_tuple(support_contacts)
        if self._state_contact_rules(support_state) is not None:
            self._reject_transition(cache_key, "insufficient_support")
            return None
        current_support = evaluate_pose_contacts(
            support_contacts,
            current.pose,
            self.profile,
            self.setup,
            self.hold_profiles,
        )
        support_candidates = [current_support] if current_support.valid else []
        support_candidates.extend(
            candidate
            for candidate in self._continuous_candidates(support_state, current.pose)
            if candidate.pose.pose_id != current.pose.pose_id
        )
        support_candidates = support_candidates[:6]
        if not support_candidates:
            self._reject_transition(cache_key, "support_pose_invalid")
            return None

        next_contacts = dict(contacts)
        next_contacts[limb] = target_id
        next_state = state_tuple(next_contacts)
        contact_rejection = self._state_contact_rules(next_state)
        if contact_rejection is not None:
            self._reject_transition(cache_key, f"contact_rule:{contact_rejection}")
            return None
        pose_pairs: List[Tuple[float, float, StateEvaluation, StateEvaluation]] = []
        for support_candidate in support_candidates:
            root_point = support_candidate.pose.joints[self._root_key(limb)]
            root = np.array([root_point.x, root_point.y], dtype=float)
            reachable, reach_ratio = reachable_from_root(
                root,
                target_id,
                first,
                second,
                limb,
                self.setup,
                self.hold_profiles,
            )
            if not reachable:
                continue
            for landing_candidate in self._continuous_candidates(
                next_state,
                support_candidate.pose,
            ):
                score = (
                    support_candidate.pose.posture_cost
                    + landing_candidate.pose.posture_cost
                    + landing_candidate.stress * 6.0
                    + reach_ratio * 2.0
                )
                pose_pairs.append(
                    (
                        score,
                        reach_ratio,
                        support_candidate,
                        landing_candidate,
                    )
                )
        if not pose_pairs:
            self._reject_transition(cache_key, "target_unreachable_from_support")
            return None
        pose_pairs.sort(
            key=lambda item: (
                item[0],
                item[2].pose.pose_id,
                item[3].pose.pose_id,
            )
        )
        pose_pairs = pose_pairs[:24]
        is_match = (
            (limb in HAND_KEYS and next_contacts.get("lh") == next_contacts.get("rh"))
            or (limb in FOOT_KEYS and next_contacts.get("lf") == next_contacts.get("rf"))
        )
        vertical_rows = int(target_id[1:]) - int(previous[1:]) if previous else 0
        if limb in HAND_KEYS and not is_match and consecutive_hands >= 2:
            self._reject_transition(cache_key, "hand_streak_requires_foot")
            return None
        selected_pair: Optional[
            Tuple[float, StateEvaluation, StateEvaluation, float, bool, float, str]
        ] = None
        pair_rejection = "landing_pose_invalid"
        for _, reach_ratio, support_candidate, landing_candidate in pose_pairs:
            reach_ratio_landing = landing_candidate.pose.extensions.get(limb, 0.0)
            needs_preparation = (
                limb in HAND_KEYS
                and not is_match
                and (
                    vertical_rows >= 3
                    or reach_ratio_landing > 0.82
                    or landing_candidate.load.peak_ratio > 0.90
                    or landing_candidate.load.residual > 0.08
                )
            )
            if needs_preparation and not prepared_by_foot:
                pair_rejection = "major_hand_move_requires_foot"
                continue
            candidate_technique = self._technique_for(
                limb,
                previous,
                target_id,
                landing_candidate,
                is_match,
                needs_preparation,
            )
            if any(
                not normal_bend_is_valid(landing_candidate.pose, hand_limb)
                for hand_limb in HAND_KEYS
            ):
                pair_rejection = "elbow_bend_direction"
                continue
            if (
                limb in FOOT_KEYS
                and candidate_technique
                not in {"backstep", "drop_knee", "rock_over"}
                and not normal_bend_is_valid(landing_candidate.pose, limb)
            ):
                candidate_technique = (
                    "drop_knee" if vertical_rows >= 2 else "backstep"
                )
            if limb in FOOT_KEYS and not self._foot_contributes(
                contacts,
                next_contacts,
                limb,
                current,
                landing_candidate,
            ):
                pair_rejection = "foot_move_has_no_contribution"
                continue
            candidate_pose_shift = float(
                np.linalg.norm(landing_candidate.pose.hip - current.pose.hip)
            )
            support_shift = float(
                np.linalg.norm(support_candidate.pose.hip - current.pose.hip)
            )
            candidate_duration = (
                0.95 + movement_distance * 0.72 + candidate_pose_shift * 0.9
            )
            if needs_preparation:
                candidate_duration += 0.28
            candidate_duration = max(
                candidate_duration,
                support_shift / (0.42 * 0.46 + 1e-9),
                candidate_pose_shift / 0.46,
            )
            phase_pairs = (
                (current.pose, support_candidate.pose, 0.42),
                (support_candidate.pose, landing_candidate.pose, 0.58),
            )
            for first_pose, second_pose, phase_fraction in phase_pairs:
                largest_joint_shift = max(
                    (
                        float(
                            np.linalg.norm(
                                np.array(
                                    [
                                        second_pose.joints[key].x - first_joint.x,
                                        second_pose.joints[key].y - first_joint.y,
                                        (second_pose.joints[key].z or 0.0)
                                        - (first_joint.z or 0.0),
                                    ],
                                    dtype=float,
                                )
                            )
                        )
                        for key, first_joint in first_pose.joints.items()
                        if key in second_pose.joints
                    ),
                    default=0.0,
                )
                candidate_duration = max(
                    candidate_duration,
                    largest_joint_shift
                    / max(MAX_STATIC_JOINT_SPEED * phase_fraction * 0.92, 1e-6),
                )
            # Fixed-length IK follows a curved joint path between key poses,
            # so reserve a small timing margin beyond endpoint displacement.
            candidate_duration = min(
                6.0,
                max(0.9, candidate_duration) * 1.6,
            )
            transition_valid, transition_reason = validate_static_pose_transition(
                current,
                support_candidate,
                landing_candidate,
                contacts,
                next_contacts,
                limb,
                self.profile,
                self.setup,
                self.hold_profiles,
                candidate_duration,
                sample_hz=30.0 if full_validation else 0.0,
            )
            if not transition_valid:
                pair_rejection = f"transition:{transition_reason}"
                continue
            selected_pair = (
                reach_ratio,
                support_candidate,
                landing_candidate,
                reach_ratio_landing,
                needs_preparation,
                candidate_duration,
                candidate_technique,
            )
            break
        if selected_pair is None:
            self._reject_transition(cache_key, pair_rejection)
            return None
        (
            support_reach_ratio,
            support_evaluation,
            landing,
            landing_reach_ratio,
            preparation_required,
            duration_seconds,
            technique,
        ) = selected_pair
        pose_shift = float(np.linalg.norm(landing.pose.hip - current.pose.hip))

        reach_transition_penalty = max(0.0, min(support_reach_ratio, landing_reach_ratio + 0.12) - 0.82) * 18.0
        downward_rows = max(0, int(previous[1:]) - int(target_id[1:])) if previous else 0
        same_hold_contacts = sum(1 for value in next_state if value == target_id)
        hand_foot_match = (
            same_hold_contacts > 1
            and any(next_contacts.get(key) == target_id for key in HAND_KEYS)
            and any(next_contacts.get(key) == target_id for key in FOOT_KEYS)
        )
        adjustment_penalty = (
            landing.pose.posture_cost
            + landing.stress * 8.0
            + movement_distance * 2.5
            + reach_transition_penalty
            + downward_rows * 6.0
            + (12.0 if hand_foot_match else 0.0)
            + pose_shift * 4.0
            + landing.pose.shoulder_wall_distance * 2.0
            + landing.pose.hip_wall_distance
        )
        fatigue_increment = (
            0.012 * duration_seconds + max(0.0, landing.stress - 0.55) * 0.04
        ) * (
            112.0 - self.profile.capabilities.endurance
        ) / 62.0
        purpose = self._purpose_for(limb, previous, target_id, state)
        support_limbs = tuple(key for key in LIMB_KEYS if key != limb and contacts.get(key))
        drive_limbs = (
            tuple(key for key in FOOT_KEYS if contacts.get(key))
            if limb in HAND_KEYS
            else tuple(key for key in FOOT_KEYS if key != limb and contacts.get(key))
        )
        result = StaticTransition(
            next_state=next_state,
            landing=landing,
            support=support_evaluation,
            adjustment_penalty=adjustment_penalty,
            fatigue_increment=fatigue_increment,
            purpose=purpose,
            technique=technique,
            support_limbs=support_limbs,
            drive_limbs=drive_limbs,
            preparation_required=preparation_required,
            duration_seconds=duration_seconds,
        )
        self._transition_cache[cache_key] = result
        return result

    def _targets_for_limb(self, limb: str, state: State) -> Sequence[str]:
        contacts = state_dict(state)
        current = contacts.get(limb)
        targets = self.hand_targets if limb in HAND_KEYS else self.foot_targets
        current_row = int(current[1:]) if current else 1
        other_same_kind = {
            "lh": contacts.get("rh"),
            "rh": contacts.get("lh"),
            "lf": contacts.get("rf"),
            "rf": contacts.get("lf"),
        }[limb]
        other_x = (
            contact_point(other_same_kind, limb, self.setup, self.hold_profiles)[0]
            if other_same_kind
            else None
        )
        filtered = []
        for target in targets:
            if target == current:
                continue
            if current:
                transfer_distance = float(
                    np.linalg.norm(
                        contact_point(target, limb, self.setup, self.hold_profiles)
                        - contact_point(current, limb, self.setup, self.hold_profiles)
                    )
                )
                first, second = self._limb_lengths(limb)
                transfer_limit = (
                    self.profile.arm_span_cm / 100.0 * 0.78
                    if limb in HAND_KEYS
                    else (first + second) * 1.28
                )
                if transfer_distance > transfer_limit:
                    continue
            target_row = int(target[1:])
            if limb in HAND_KEYS:
                if target_row < current_row - 1:
                    continue
            else:
                if target_row < current_row - 1 or target_row - current_row > MAX_FOOT_MOVE_ROWS:
                    continue
            target_x = contact_point(target, limb, self.setup, self.hold_profiles)[0]
            if other_x is not None and target != other_same_kind:
                if limb in {"lh", "lf"} and target_x > other_x + 1e-6:
                    continue
                if limb in {"rh", "rf"} and target_x < other_x - 1e-6:
                    continue
            filtered.append(target)
        ordered = sorted(
            filtered,
            key=lambda target: (
                0 if target in self.end_ids and limb in HAND_KEYS else 1,
                -int(target[1:]) if limb in HAND_KEYS else abs(int(target[1:]) - int(current[1:])) if current else int(target[1:]),
                target,
            ),
        )
        return ordered[:5] if limb in HAND_KEYS else ordered[:4]

    def _frontier_value(self, state: State) -> Tuple[float, float]:
        hands = [coord(value) for value in state[:2] if value]
        highest = max((point[1] for point in hands), default=0.0)
        if not self.end_ids or not hands:
            return highest, 0.0
        distance = min(
            float(np.linalg.norm(coord(end_id) - hand))
            for end_id in self.end_ids
            for hand in hands
        )
        return highest, -distance

    def _node_path(self, node: _QueueNode) -> BetaPath:
        return BetaPath(
            start_state=node.start_state,
            actions=node.actions,
            states=node.states,
            evaluations=node.evaluations,
            fatigue=node.fatigue,
            peak_stress=node.peak_stress,
            dynamic_action_count=node.dynamic_action_count,
        )

    @staticmethod
    def _path_order_key(path: BetaPath) -> Tuple[int, int, int, float, float]:
        hand_cycles = sum(
            action.limb in HAND_KEYS and action.action_type != "match"
            for action in path.actions
        )
        waste = 0
        seen_by_limb: Dict[str, set[str]] = {key: set() for key in LIMB_KEYS}
        for state in path.states[:1]:
            for index, limb in enumerate(LIMB_KEYS):
                if state[index]:
                    seen_by_limb[limb].add(state[index])  # type: ignore[arg-type]
        for action in path.actions:
            if action.target_id in seen_by_limb[action.limb]:
                waste += 1
            seen_by_limb[action.limb].add(action.target_id)
        return waste, hand_cycles, len(path.actions), path.peak_stress, path.fatigue

    def search_static(
        self,
        initial_paths: Optional[List[BetaPath]] = None,
        max_solutions: int = 3,
        budget: Optional[int] = None,
    ) -> SearchOutcome:
        rejection_counts: Counter = Counter()
        open_list: List[_QueueNode] = []
        counter = itertools.count()
        if initial_paths is None:
            for start_state in self._start_states():
                for evaluation in self.evaluate_candidates(start_state):
                    heapq.heappush(
                        open_list,
                        _QueueNode(
                            priority=(0, 0, 0, evaluation.pose.posture_cost, 0.0, next(counter)),
                            state=start_state,
                            start_state=start_state,
                            states=[start_state],
                            evaluations=[evaluation],
                            peak_stress=evaluation.stress,
                            prepared_by_foot=True,
                        ),
                    )
        else:
            for path in initial_paths:
                current_state = path.states[-1]
                hand_cycles = sum(
                    action.limb in HAND_KEYS and action.action_type != "match"
                    for action in path.actions
                )
                consecutive_hands = 0
                for action in reversed(path.actions):
                    if action.limb not in HAND_KEYS or action.action_type == "match":
                        break
                    consecutive_hands += 1
                waste_count = self._path_order_key(path)[0]
                prepared_by_foot = False
                for action in reversed(path.actions):
                    if action.limb in FOOT_KEYS:
                        prepared_by_foot = True
                        break
                    if action.action_type != "match":
                        break
                heapq.heappush(
                    open_list,
                    _QueueNode(
                        priority=(
                            waste_count,
                            hand_cycles,
                            len(path.actions),
                            path.peak_stress * 8.0,
                            path.fatigue,
                            next(counter),
                        ),
                        state=current_state,
                        start_state=path.start_state,
                        actions=list(path.actions),
                        states=list(path.states),
                        evaluations=list(path.evaluations),
                        penalty=path.peak_stress * 8.0,
                        fatigue=path.fatigue,
                        peak_stress=path.peak_stress,
                        dynamic_action_count=path.dynamic_action_count,
                        waste_count=waste_count,
                        hand_cycles=hand_cycles,
                        consecutive_hands=consecutive_hands,
                        prepared_by_foot=prepared_by_foot,
                        last_limb=path.actions[-1].limb if path.actions else None,
                    ),
                )
        if not open_list:
            rejection_counts["invalid_start"] += 1
            return SearchOutcome([], True, 0, rejection_counts, [])

        best_cost: Dict[
            Tuple[State, str, int, int, bool, Optional[str]],
            Tuple[int, int, int, float, float],
        ] = {}
        solutions: List[BetaPath] = []
        signatures: set[Tuple[Tuple[str, str, str], ...]] = set()
        frontier_nodes: List[_QueueNode] = []
        expanded = 0
        effective_budget = budget or self.search_budget
        first_goal_hand_cycles: Optional[int] = None

        while open_list and expanded < effective_budget:
            node = heapq.heappop(open_list)
            steps = len(node.actions)
            if first_goal_hand_cycles is not None and node.hand_cycles > first_goal_hand_cycles + 1:
                break
            current_pose_id = node.evaluations[-1].pose.pose_id
            cost_key = (
                node.state,
                current_pose_id,
                node.dynamic_action_count,
                node.consecutive_hands,
                node.prepared_by_foot,
                node.last_limb,
            )
            current_cost = (
                node.waste_count,
                node.hand_cycles,
                steps,
                round(node.penalty, 5),
                round(node.fatigue, 5),
            )
            if best_cost.get(cost_key, current_cost) < current_cost:
                continue
            best_cost[cost_key] = current_cost
            expanded += 1

            frontier_nodes.append(node)
            frontier_nodes.sort(
                key=lambda item: (
                    self._frontier_value(item.state),
                    -len(item.actions),
                    -item.penalty,
                ),
                reverse=True,
            )
            del frontier_nodes[20:]

            if self._is_goal(node.state):
                path = self.replay(node.start_state, node.actions)
                if path and path.signature not in signatures:
                    signatures.add(path.signature)
                    solutions.append(path)
                    first_goal_hand_cycles = (
                        first_goal_hand_cycles
                        if first_goal_hand_cycles is not None
                        else node.hand_cycles
                    )
                    if len(solutions) >= max_solutions:
                        break
                elif path is None:
                    rejection_counts["full_replay_invalid"] += 1
                continue

            for limb in LIMB_KEYS:
                for target_id in self._targets_for_limb(limb, node.state):
                    current_evaluation = node.evaluations[-1]
                    transition = self._transition(
                        node.state,
                        limb,
                        target_id,
                        current_evaluation,
                        node.prepared_by_foot,
                        node.consecutive_hands,
                        False,
                    )
                    if transition is None:
                        transition_key = (
                            node.state,
                            current_evaluation.pose.pose_id,
                            limb,
                            target_id,
                            node.prepared_by_foot,
                            node.consecutive_hands,
                            False,
                        )
                        rejection_counts[
                            self._transition_rejections.get(transition_key, "transition_invalid")
                        ] += 1
                        continue
                    next_state = transition.next_state
                    landing = transition.landing
                    next_fatigue = node.fatigue + transition.fatigue_increment
                    if next_fatigue > 1.18:
                        rejection_counts["fatigue"] += 1
                        continue
                    action_type = (
                        "match"
                        if (
                            (limb in HAND_KEYS and next_state[0] == next_state[1])
                            or (limb in FOOT_KEYS and next_state[2] == next_state[3])
                        )
                        else "static_move"
                    )
                    action = MotionAction(
                        limb=limb,
                        target_id=target_id,
                        action_type=action_type,
                        purpose=transition.purpose,
                        moving_limbs=(limb,),
                        technique=transition.technique,
                        support_limbs=transition.support_limbs,
                        drive_limbs=transition.drive_limbs,
                        preparation_required=transition.preparation_required,
                        duration_seconds=transition.duration_seconds,
                        to_state=next_state,
                        support_evaluation=transition.support,
                        preparation_pose=(
                            self._crouch_pose(node.state, current_evaluation)
                            if transition.preparation_required
                            else None
                        ),
                    )
                    next_actions = [*node.actions, action]
                    next_penalty = node.penalty + transition.adjustment_penalty
                    next_peak = max(node.peak_stress, landing.stress)
                    limb_index = LIMB_KEYS.index(limb)
                    prior_targets = {
                        prior_state[limb_index]
                        for prior_state in node.states
                        if prior_state[limb_index]
                    }
                    waste_increment = int(target_id in prior_targets)
                    next_waste = node.waste_count + waste_increment
                    next_hand_cycles = node.hand_cycles + int(
                        limb in HAND_KEYS and action_type != "match"
                    )
                    if limb in FOOT_KEYS:
                        next_consecutive_hands = 0
                        next_prepared = True
                    elif action_type == "match":
                        next_consecutive_hands = node.consecutive_hands
                        next_prepared = node.prepared_by_foot
                    else:
                        next_consecutive_hands = node.consecutive_hands + 1
                        next_prepared = False
                    next_cost = (
                        next_waste,
                        next_hand_cycles,
                        len(next_actions),
                        round(next_penalty, 5),
                        round(next_fatigue, 5),
                    )
                    next_key = (
                        next_state,
                        landing.pose.pose_id,
                        node.dynamic_action_count,
                        next_consecutive_hands,
                        next_prepared,
                        limb,
                    )
                    if next_key in best_cost and best_cost[next_key] <= next_cost:
                        continue
                    best_cost[next_key] = next_cost
                    heapq.heappush(
                        open_list,
                        _QueueNode(
                            priority=(
                                next_waste,
                                next_hand_cycles,
                                len(next_actions),
                                next_penalty,
                                next_fatigue,
                                next(counter),
                            ),
                            state=next_state,
                            start_state=node.start_state,
                            actions=next_actions,
                            states=[*node.states, next_state],
                            evaluations=[*node.evaluations, landing],
                            penalty=next_penalty,
                            fatigue=next_fatigue,
                            peak_stress=next_peak,
                            dynamic_action_count=node.dynamic_action_count,
                            waste_count=next_waste,
                            hand_cycles=next_hand_cycles,
                            consecutive_hands=next_consecutive_hands,
                            prepared_by_foot=next_prepared,
                            last_limb=limb,
                        ),
                    )

        search_complete = not open_list or expanded < effective_budget
        if not search_complete:
            rejection_counts["search_budget"] += 1
        return SearchOutcome(
            paths=sorted(solutions, key=self._path_order_key),
            search_complete=search_complete,
            expanded_states=expanded,
            rejection_counts=rejection_counts,
            frontier_paths=[self._node_path(node) for node in frontier_nodes],
        )

    def _crouch_pose(
        self,
        state: State,
        current: StateEvaluation,
    ) -> PoseEvaluation:
        candidates = self.evaluate_candidates(state)
        lower = [
            evaluation.pose
            for evaluation in candidates
            if evaluation.pose.hip[1] <= current.pose.hip[1] - 0.025
            and evaluation.pose.hip_wall_distance <= current.pose.hip_wall_distance + 0.06
        ]
        if not lower:
            return current.pose
        return min(
            lower,
            key=lambda pose: (
                pose.hip[1],
                abs(pose.shoulder_wall_distance - 0.10),
                pose.posture_cost,
            ),
        )

    def replay(
        self,
        start_state: State,
        actions: Sequence[MotionAction],
    ) -> Optional[BetaPath]:
        if self._state_contact_rules(start_state) is not None:
            return None
        start_candidates = self.evaluate_candidates(start_state)
        if not start_candidates:
            return None
        if actions and actions[0].support_evaluation:
            reference_pose = actions[0].support_evaluation.pose
            start_evaluation = min(
                start_candidates,
                key=lambda evaluation: float(
                    np.linalg.norm(evaluation.pose.hip - reference_pose.hip)
                ),
            )
        else:
            start_evaluation = start_candidates[0]
        states = [start_state]
        evaluations = [start_evaluation]
        fatigue = 0.0
        peak_stress = start_evaluation.stress
        current = start_state
        rebuilt: List[MotionAction] = []
        dynamic_count = 0
        consecutive_hands = 0
        prepared_by_foot = True

        for action in actions:
            if action.dynamic:
                current_evaluation = evaluations[-1]
                current_state = current
                if action.to_state is None:
                    return None
                moving_set = set(action.moving_limbs or (action.limb,))
                if any(
                    action.to_state[index] != current_state[index]
                    for index, limb_key in enumerate(LIMB_KEYS)
                    if limb_key not in moving_set
                ):
                    return None
                landing_candidates = self.evaluate_candidates(action.to_state)
                if not landing_candidates:
                    return None
                landing = min(
                    landing_candidates,
                    key=lambda evaluation: float(
                        np.linalg.norm(
                            np.array(
                                [
                                    evaluation.pose.center_of_mass.x
                                    - current_evaluation.pose.center_of_mass.x,
                                    evaluation.pose.center_of_mass.y
                                    - current_evaluation.pose.center_of_mass.y,
                                ],
                                dtype=float,
                            )
                        )
                    ),
                )
                target_hold = self.setup.get(action.target_id)
                if not target_hold:
                    return None
                dynamic = action.dynamic_evaluation or solve_dynamic_trajectory(
                    current_evaluation.pose.center_of_mass,
                    landing.pose.center_of_mass,
                    self.profile,
                    target_hold,
                    self._physics_for(target_hold),
                )
                if not dynamic.feasible:
                    return None
                current = action.to_state
                rebuilt.append(
                    MotionAction(
                        **{
                            **action.__dict__,
                            "dynamic_evaluation": dynamic,
                            "preparation_pose": self._crouch_pose(current_state, current_evaluation),
                        }
                    )
                )
                fatigue += 0.06 + dynamic.catch_load_ratio * 0.045
                dynamic_count += 1
                states.append(current)
                evaluations.append(landing)
                peak_stress = max(peak_stress, landing.stress, dynamic.catch_load_ratio)
                consecutive_hands = min(2, consecutive_hands + 1)
                prepared_by_foot = False
                continue

            transition = self._transition(
                current,
                action.limb,
                action.target_id,
                evaluations[-1],
                prepared_by_foot,
                consecutive_hands,
                True,
            )
            if transition is None:
                return None
            next_state = transition.next_state
            landing = transition.landing
            action_type = (
                "match"
                if (
                    (action.limb in HAND_KEYS and next_state[0] == next_state[1])
                    or (action.limb in FOOT_KEYS and next_state[2] == next_state[3])
                )
                else action.action_type
            )
            rebuilt.append(
                MotionAction(
                    limb=action.limb,
                    target_id=action.target_id,
                    action_type=action_type,
                    purpose=transition.purpose,
                    moving_limbs=action.moving_limbs or (action.limb,),
                    technique=transition.technique,
                    support_limbs=transition.support_limbs,
                    drive_limbs=transition.drive_limbs,
                    preparation_required=transition.preparation_required,
                    duration_seconds=transition.duration_seconds,
                    to_state=next_state,
                    support_evaluation=transition.support,
                    preparation_pose=(
                        self._crouch_pose(current, evaluations[-1])
                        if transition.preparation_required
                        else None
                    ),
                )
            )
            current = next_state
            fatigue += transition.fatigue_increment
            states.append(current)
            evaluations.append(landing)
            peak_stress = max(peak_stress, landing.stress)
            if action.limb in FOOT_KEYS:
                consecutive_hands = 0
                prepared_by_foot = True
            elif action_type == "match":
                pass
            else:
                consecutive_hands += 1
                prepared_by_foot = False
        if not self._is_goal(current):
            return None
        return BetaPath(
            start_state=start_state,
            actions=rebuilt,
            states=states,
            evaluations=evaluations,
            fatigue=fatigue,
            peak_stress=peak_stress,
            dynamic_action_count=dynamic_count,
        )

    def replay_guided_robustness(self, reference_path: BetaPath) -> bool:
        """Replay a fixed Beta near its nominal poses without reopening A*."""
        if any(action.dynamic for action in reference_path.actions):
            return self.replay(
                reference_path.start_state,
                reference_path.actions,
            ) is not None

        def guided_candidates(
            state: State,
            reference_pose: PoseEvaluation,
        ) -> List[StateEvaluation]:
            candidates = evaluate_state_candidates(
                state_dict(state),
                self.profile,
                self.setup,
                self.hold_profiles,
                previous_pose=reference_pose,
                limit=4,
            )
            candidates.sort(
                key=lambda evaluation: (
                    float(np.linalg.norm(evaluation.pose.hip - reference_pose.hip)),
                    abs(
                        evaluation.pose.torso_angle_degrees
                        - reference_pose.torso_angle_degrees
                    ),
                    evaluation.pose.posture_cost,
                )
            )
            return candidates

        start_candidates = guided_candidates(
            reference_path.start_state,
            reference_path.evaluations[0].pose,
        )
        if not start_candidates:
            return False
        current = start_candidates[0]
        for index, action in enumerate(reference_path.actions):
            from_contacts = state_dict(reference_path.states[index])
            to_state = reference_path.states[index + 1]
            to_contacts = state_dict(to_state)
            if self._state_contact_rules(to_state) is not None:
                return False
            support_contacts = dict(from_contacts)
            support_contacts[action.limb] = None
            support = evaluate_pose_contacts(
                support_contacts,
                current.pose,
                self.profile,
                self.setup,
                self.hold_profiles,
            )
            reference_support = (
                action.support_evaluation.pose
                if action.support_evaluation
                else reference_path.evaluations[index].pose
            )
            support_state = state_tuple(support_contacts)
            support_candidates = (
                [support] if support.valid else []
            ) + guided_candidates(
                support_state,
                reference_support,
            )
            if not support_candidates:
                return False
            landing_candidates = guided_candidates(
                to_state,
                reference_path.evaluations[index + 1].pose,
            )
            if not landing_candidates:
                return False
            selected_landing: Optional[StateEvaluation] = None
            for support_candidate in support_candidates:
                for landing_candidate in landing_candidates:
                    valid, _ = validate_static_pose_transition(
                        current,
                        support_candidate,
                        landing_candidate,
                        from_contacts,
                        to_contacts,
                        action.limb,
                        self.profile,
                        self.setup,
                        self.hold_profiles,
                        max(0.9, action.duration_seconds),
                        sample_hz=30.0,
                    )
                    if valid:
                        selected_landing = landing_candidate
                        break
                if selected_landing is not None:
                    break
            if selected_landing is None:
                return False
            current = selected_landing
        return self._is_goal(reference_path.states[-1])

    def simplify(self, path: BetaPath) -> Optional[BetaPath]:
        validated = self.replay(path.start_state, path.actions)
        if not validated:
            return None
        actions = list(validated.actions)
        changed = True
        while changed:
            changed = False
            for index in range(len(actions)):
                candidate = [*actions[:index], *actions[index + 1 :]]
                replayed = self.replay(path.start_state, candidate)
                if replayed:
                    actions = replayed.actions
                    changed = True
                    break
        return self.replay(path.start_state, actions)

    def _dynamic_candidates(self, static_outcome: SearchOutcome) -> List[BetaPath]:
        candidates: List[Tuple[float, BetaPath]] = []
        seen: set[Tuple[State, str, str]] = set()
        for frontier in static_outcome.frontier_paths[:12]:
            current_state = frontier.states[-1]
            current_contacts = state_dict(current_state)
            current_evaluation = frontier.evaluations[-1]
            for limb in HAND_KEYS:
                for target_id in self.hand_targets:
                    key = (current_state, limb, target_id)
                    if key in seen or current_contacts.get(limb) == target_id:
                        continue
                    seen.add(key)
                    landing_contacts = dict(current_contacts)
                    landing_contacts[limb] = target_id
                    landing_state = state_tuple(landing_contacts)
                    if self._state_contact_rules(landing_state) is not None:
                        continue
                    static_transition = self._transition(
                        current_state,
                        limb,
                        target_id,
                        current_evaluation,
                        True,
                        0,
                    )
                    if static_transition is not None:
                        continue
                    target_hold = self.setup[target_id]
                    landing_candidates = self._continuous_candidates(
                        landing_state,
                        current_evaluation.pose,
                    )
                    if landing_candidates:
                        landing = landing_candidates[0]
                        dynamic = solve_dynamic_trajectory(
                            current_evaluation.pose.center_of_mass,
                            landing.pose.center_of_mass,
                            self.profile,
                            target_hold,
                            self._physics_for(target_hold),
                        )
                        if dynamic.feasible:
                            vertical_rows = int(target_id[1:]) - int((current_contacts.get(limb) or target_id)[1:])
                            action_type = "dyno" if vertical_rows >= 4 or dynamic.launch_velocity >= 2.2 else "deadpoint"
                            dynamic_action = MotionAction(
                                limb=limb,
                                target_id=target_id,
                                action_type=action_type,
                                purpose="以单次动态动作跨过静态触达卡点",
                                dynamic=True,
                                moving_limbs=(limb, "lf", "rf") if action_type == "dyno" else (limb,),
                                technique="dynamic_leg_drive",
                                support_limbs=tuple(
                                    key
                                    for key in LIMB_KEYS
                                    if key not in ((limb, "lf", "rf") if action_type == "dyno" else (limb,))
                                    and current_contacts.get(key)
                                ),
                                drive_limbs=tuple(
                                    key for key in FOOT_KEYS if current_contacts.get(key)
                                ),
                                preparation_required=True,
                                duration_seconds=dynamic.duration_seconds + 1.2,
                                to_state=landing_state,
                                dynamic_evaluation=dynamic,
                                preparation_pose=self._crouch_pose(
                                    current_state,
                                    current_evaluation,
                                ),
                            )
                            dynamic_path = BetaPath(
                                start_state=frontier.start_state,
                                actions=[*frontier.actions, dynamic_action],
                                states=[*frontier.states, landing_state],
                                evaluations=[*frontier.evaluations, landing],
                                fatigue=frontier.fatigue + 0.06 + dynamic.catch_load_ratio * 0.045,
                                peak_stress=max(frontier.peak_stress, landing.stress, dynamic.catch_load_ratio),
                                dynamic_action_count=1,
                            )
                            candidates.append((dynamic.score, dynamic_path))

                    for foot_limb in FOOT_KEYS:
                        other_foot = "rf" if foot_limb == "lf" else "lf"
                        for foot_target in self.foot_targets:
                            recovery_contacts = dict(landing_contacts)
                            recovery_contacts[foot_limb] = foot_target
                            recovery_contacts[other_foot] = None
                            recovery_state = state_tuple(recovery_contacts)
                            if self._state_contact_rules(recovery_state) is not None:
                                continue
                            recovery = self.evaluate(recovery_state)
                            if not recovery.valid:
                                continue
                            current_hand_id = current_contacts.get(limb)
                            current_hand_point = (
                                contact_point(
                                    current_hand_id,
                                    limb,
                                    self.setup,
                                    self.hold_profiles,
                                )
                                if current_hand_id
                                else np.array(
                                    [
                                        current_evaluation.pose.center_of_mass.x,
                                        current_evaluation.pose.center_of_mass.y,
                                    ],
                                    dtype=float,
                                )
                            )
                            target_point = contact_point(
                                target_id,
                                limb,
                                self.setup,
                                self.hold_profiles,
                            )
                            hand_delta = target_point - current_hand_point
                            catch_center = current_evaluation.pose.center_of_mass.model_copy(
                                update={
                                    "x": current_evaluation.pose.center_of_mass.x
                                    + float(hand_delta[0]) * 0.28,
                                    "y": current_evaluation.pose.center_of_mass.y
                                    + min(0.44, max(-0.12, float(hand_delta[1]) * 0.38)),
                                }
                            )
                            cut_loose_dynamic = solve_dynamic_trajectory(
                                current_evaluation.pose.center_of_mass,
                                catch_center,
                                self.profile,
                                target_hold,
                                self._physics_for(target_hold),
                            )
                            if not cut_loose_dynamic.feasible:
                                continue
                            cut_loose = MotionAction(
                                limb=limb,
                                target_id=target_id,
                                action_type="cut_loose",
                                purpose="释放双脚摆荡后在合法线路点恢复脚撑",
                                dynamic=True,
                                moving_limbs=(limb, "lf", "rf"),
                                technique="cut_loose_recovery",
                                support_limbs=tuple(
                                    key
                                    for key in HAND_KEYS
                                    if key != limb and current_contacts.get(key)
                                ),
                                drive_limbs=tuple(
                                    key for key in FOOT_KEYS if current_contacts.get(key)
                                ),
                                preparation_required=True,
                                duration_seconds=cut_loose_dynamic.duration_seconds + 1.5,
                                to_state=recovery_state,
                                dynamic_evaluation=cut_loose_dynamic,
                                preparation_pose=self._crouch_pose(
                                    current_state,
                                    current_evaluation,
                                ),
                            )
                            path = BetaPath(
                                start_state=frontier.start_state,
                                actions=[*frontier.actions, cut_loose],
                                states=[*frontier.states, recovery_state],
                                evaluations=[*frontier.evaluations, recovery],
                                fatigue=frontier.fatigue + 0.08 + cut_loose_dynamic.catch_load_ratio * 0.05,
                                peak_stress=max(frontier.peak_stress, recovery.stress, cut_loose_dynamic.catch_load_ratio),
                                dynamic_action_count=1,
                            )
                            candidates.append((cut_loose_dynamic.score - 5.0, path))
                            break
                        if candidates and candidates[-1][1].actions[-1].action_type == "cut_loose":
                            break
        candidates.sort(
            key=lambda item: (
                not self._is_goal(item[1].states[-1]),
                -self._frontier_value(item[1].states[-1])[0],
                len(item[1].actions),
                -item[0],
                item[1].peak_stress,
            )
        )
        unique: List[BetaPath] = []
        seen_landings: set[Tuple[State, str, str]] = set()
        for _, path in candidates:
            last_action = path.actions[-1]
            landing_key = (path.states[-1], last_action.action_type, last_action.target_id)
            if landing_key in seen_landings:
                continue
            seen_landings.add(landing_key)
            unique.append(path)
            if len(unique) >= 12:
                break
        return unique

    def solve(self, motion_mode: str) -> SolveOutcome:
        static = self.search_static()
        if static.paths:
            simplified = [
                simplified_path
                for path in static.paths
                if (simplified_path := self.simplify(path)) is not None
            ]
            deduplicated: Dict[Tuple[Tuple[str, str, str], ...], BetaPath] = {}
            for path in simplified:
                deduplicated.setdefault(path.signature, path)
            if deduplicated:
                paths = sorted(
                    deduplicated.values(),
                    key=self._path_order_key,
                )[:3]
                return SolveOutcome(
                    solution_mode="static",
                    paths=paths,
                    search_complete=static.search_complete,
                    expanded_states=static.expanded_states,
                    rejection_counts=static.rejection_counts,
                )
            static.rejection_counts["full_rate_replay_failed"] += 1
        if motion_mode == "static" or not static.search_complete:
            return SolveOutcome(
                solution_mode="none",
                paths=[],
                search_complete=static.search_complete,
                expanded_states=static.expanded_states,
                rejection_counts=static.rejection_counts,
            )

        dynamic_candidates = self._dynamic_candidates(static)
        total_expanded = static.expanded_states
        rejection_counts = Counter(static.rejection_counts)
        dynamic_solutions: List[BetaPath] = []
        dynamic_scores: List[float] = []
        for candidate in dynamic_candidates:
            continuation = self.search_static(
                initial_paths=[candidate],
                max_solutions=1,
                budget=max(2_000, self.search_budget // 3),
            )
            total_expanded += continuation.expanded_states
            rejection_counts.update(continuation.rejection_counts)
            if continuation.paths:
                path = self.simplify(continuation.paths[0])
                if path is None:
                    rejection_counts["full_rate_replay_failed"] += 1
                    continue
                dynamic_solutions.append(path)
                dynamic_scores.extend(
                    action.dynamic_evaluation.score
                    for action in path.actions
                    if action.dynamic and action.dynamic_evaluation
                )
                if len(dynamic_solutions) >= 3:
                    break
        if dynamic_solutions:
            dynamic_solutions.sort(key=self._path_order_key)
            return SolveOutcome(
                solution_mode="single_dynamic",
                paths=dynamic_solutions[:3],
                search_complete=True,
                expanded_states=total_expanded,
                rejection_counts=rejection_counts,
                dynamic_feasibility_score=max(dynamic_scores, default=0.0),
            )
        rejection_counts["dynamic_no_solution"] += 1
        return SolveOutcome(
            solution_mode="none",
            paths=[],
            search_complete=True,
            expanded_states=total_expanded,
            rejection_counts=rejection_counts,
        )
