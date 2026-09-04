"""Deterministic 2.5D body-pose, contact-load, and single-move dynamics.

This module is intentionally independent from the route-generation A* solver.
It validates a fixed set of route contacts and never invents board holds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from core.models import ClimberProfile, Hold, HoldPhysicsProfile, SimulationJointPoint


BOARD_ANGLE_DEGREES = 40.0
GRID_SPACING_METERS = 0.2
# The normalized capacities are coarse manual categories, not calibrated force
# sensors. Keep a small deterministic tolerance so a brief three-point support
# is not rejected by rounding at the category boundary.
STATIC_LOAD_LIMIT = 1.30
SHOULDER_WALL_RANGE = (0.06, 0.20)
HIP_WALL_RANGE = (0.08, 0.28)
SHOULDER_WALL_HARD_LIMIT = 0.30
HIP_WALL_HARD_LIMIT = 0.35
MAX_STATIC_COM_SPEED = 0.52
MAX_STATIC_JOINT_SPEED = 1.8
BODY_LENGTH_TOLERANCE = 0.001


@dataclass(frozen=True)
class BodyDimensions:
    torso: float
    head: float
    shoulder_width: float
    hip_width: float
    upper_arm: float
    forearm_hand: float
    thigh: float
    shin: float

    @classmethod
    def from_profile(cls, profile: ClimberProfile) -> "BodyDimensions":
        return cls(
            torso=profile.torso_length_cm / 100.0,
            head=profile.height_cm / 100.0 * 0.12,
            shoulder_width=profile.shoulder_width_cm / 100.0,
            hip_width=profile.hip_width_cm / 100.0,
            upper_arm=profile.upper_arm_cm / 100.0,
            forearm_hand=(profile.forearm_cm + profile.hand_reach_cm) / 100.0,
            thigh=profile.thigh_cm / 100.0,
            shin=profile.shin_cm / 100.0,
        )


def coord(coord_id: str) -> np.ndarray:
    return np.array(
        [
            (ord(coord_id[0].upper()) - ord("A")) * GRID_SPACING_METERS,
            (int(coord_id[1:]) - 1) * GRID_SPACING_METERS,
        ],
        dtype=float,
    )


def point(value: Iterable[float], z: float = 0.0) -> SimulationJointPoint:
    x, y = value
    return SimulationJointPoint(x=round(float(x), 4), y=round(float(y), 4), z=round(float(z), 4))


def _distance_between(
    joints: Dict[str, SimulationJointPoint],
    first: str,
    second: str,
) -> Optional[float]:
    if first not in joints or second not in joints:
        return None
    return float(np.linalg.norm(_point_array(joints[first]) - _point_array(joints[second])))


def body_dimension_errors(
    joints: Dict[str, SimulationJointPoint],
    profile: ClimberProfile,
) -> Dict[str, float]:
    dimensions = BodyDimensions.from_profile(profile)
    expected_segments = {
        "torso": ("pelvis", "shoulder_center", dimensions.torso),
        "head": ("shoulder_center", "head", dimensions.head),
        "shoulder_width": ("left_shoulder", "right_shoulder", dimensions.shoulder_width),
        "hip_width": ("left_hip", "right_hip", dimensions.hip_width),
        "left_upper_arm": ("left_shoulder", "left_elbow", dimensions.upper_arm),
        "left_forearm_hand": ("left_elbow", "left_hand", dimensions.forearm_hand),
        "right_upper_arm": ("right_shoulder", "right_elbow", dimensions.upper_arm),
        "right_forearm_hand": ("right_elbow", "right_hand", dimensions.forearm_hand),
        "left_thigh": ("left_hip", "left_knee", dimensions.thigh),
        "left_shin": ("left_knee", "left_foot", dimensions.shin),
        "right_thigh": ("right_hip", "right_knee", dimensions.thigh),
        "right_shin": ("right_knee", "right_foot", dimensions.shin),
    }
    errors: Dict[str, float] = {}
    for label, (first, second, expected) in expected_segments.items():
        actual = _distance_between(joints, first, second)
        errors[label] = float("inf") if actual is None else abs(actual - expected)
    return errors


def body_dimensions_valid(
    joints: Dict[str, SimulationJointPoint],
    profile: ClimberProfile,
    tolerance: float = BODY_LENGTH_TOLERANCE,
) -> bool:
    return all(error <= tolerance for error in body_dimension_errors(joints, profile).values())


def angular_distance(first: float, second: float) -> float:
    difference = abs((first - second) % 360.0)
    return min(difference, 360.0 - difference)


@dataclass
class PoseEvaluation:
    valid: bool
    reason: str = ""
    joints: Dict[str, SimulationJointPoint] = field(default_factory=dict)
    roots: Dict[str, np.ndarray] = field(default_factory=dict)
    center_of_mass: SimulationJointPoint = field(default_factory=lambda: SimulationJointPoint(x=0.0, y=0.0))
    extensions: Dict[str, float] = field(default_factory=dict)
    joint_angles: Dict[str, float] = field(default_factory=dict)
    posture_cost: float = 0.0
    torso_offset: float = 0.0
    pose_id: str = ""
    hip: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    shoulder: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    torso_angle_degrees: float = 0.0
    shoulder_wall_distance: float = 0.0
    hip_wall_distance: float = 0.0
    contact_points: Dict[str, np.ndarray] = field(default_factory=dict)
    bend_directions: Dict[str, str] = field(default_factory=dict)


@dataclass
class LoadEvaluation:
    stable: bool
    reason: str = ""
    contact_loads: Dict[str, float] = field(default_factory=dict)
    peak_ratio: float = 0.0
    residual: float = 0.0
    normal_ratio: float = 0.0


@dataclass
class StateEvaluation:
    valid: bool
    reason: str
    pose: PoseEvaluation
    load: LoadEvaluation
    stress: float = 0.0
    demand: Dict[str, float] = field(default_factory=dict)


@dataclass
class DynamicEvaluation:
    feasible: bool
    reason: str
    score: float = 0.0
    duration_seconds: float = 0.0
    launch_velocity: float = 0.0
    catch_velocity: float = 0.0
    catch_load_ratio: float = 0.0
    trajectory: List[Tuple[float, np.ndarray, np.ndarray]] = field(default_factory=list)


def _hold_profile_for(
    hold: Hold,
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> Optional[HoldPhysicsProfile]:
    if hold.variant in hold_profiles:
        return hold_profiles[hold.variant]
    return next((item for item in hold_profiles.values() if item.hold_type == hold.hold_type), None)


def contact_point(
    hold_id: str,
    limb: str,
    setup: Optional[Dict[str, Hold]] = None,
    hold_profiles: Optional[Dict[str, HoldPhysicsProfile]] = None,
    anchor_kind: Optional[str] = None,
) -> np.ndarray:
    """Return the fixed board-hole center for every supporting contact.

    The extra arguments remain in the public signature for compatibility with
    v1.2 callers and saved hold profiles. Contact-anchor offsets are no longer
    applied: a hand or foot recorded on a hold is always attached to the
    center of that hold image.
    """

    return coord(hold_id)


def _point_array(value: SimulationJointPoint) -> np.ndarray:
    return np.array([value.x, value.y], dtype=float)


def _orientation(first: np.ndarray, second: np.ndarray, third: np.ndarray) -> float:
    first_x = float(second[0] - first[0])
    first_y = float(second[1] - first[1])
    second_x = float(third[0] - first[0])
    second_y = float(third[1] - first[1])
    return first_x * second_y - first_y * second_x


def _segments_cross_strict(
    first_a: np.ndarray,
    first_b: np.ndarray,
    second_a: np.ndarray,
    second_b: np.ndarray,
) -> bool:
    for first in (first_a, first_b):
        for second in (second_a, second_b):
            delta_x = float(first[0] - second[0])
            delta_y = float(first[1] - second[1])
            if delta_x * delta_x + delta_y * delta_y <= 1e-12:
                return False
    return (
        _orientation(first_a, first_b, second_a) * _orientation(first_a, first_b, second_b) < -1e-8
        and _orientation(second_a, second_b, first_a) * _orientation(second_a, second_b, first_b) < -1e-8
    )


def pose_has_crossing(joints: Dict[str, SimulationJointPoint]) -> bool:
    limb_pairs = (
        (
            (("left_shoulder", "left_elbow"), ("left_elbow", "left_hand")),
            (("right_shoulder", "right_elbow"), ("right_elbow", "right_hand")),
        ),
        (
            (("left_hip", "left_knee"), ("left_knee", "left_foot")),
            (("right_hip", "right_knee"), ("right_knee", "right_foot")),
        ),
    )
    for left_segments, right_segments in limb_pairs:
        for left_start, left_end in left_segments:
            for right_start, right_end in right_segments:
                if not all(key in joints for key in (left_start, left_end, right_start, right_end)):
                    continue
                left_start_point = joints[left_start]
                left_end_point = joints[left_end]
                right_start_point = joints[right_start]
                right_end_point = joints[right_end]
                if _segments_cross_strict(
                    (left_start_point.x, left_start_point.y),
                    (left_end_point.x, left_end_point.y),
                    (right_start_point.x, right_start_point.y),
                    (right_end_point.x, right_end_point.y),
                ):
                    return True
    return False


def _two_link_joint(
    root: np.ndarray,
    target: np.ndarray,
    first: float,
    second: float,
    bend: float,
) -> Optional[Tuple[np.ndarray, float, float]]:
    delta = target - root
    distance = float(np.linalg.norm(delta))
    effective_first = first
    effective_second = second
    physical_minimum = abs(first - second)
    if distance < physical_minimum:
        deficit = physical_minimum - distance
        adjustment = deficit / 2.0 + 1e-7
        if adjustment > BODY_LENGTH_TOLERANCE:
            return None
        if first < second:
            effective_first += adjustment
            effective_second -= adjustment
        else:
            effective_first -= adjustment
            effective_second += adjustment
    minimum = abs(effective_first - effective_second)
    maximum = effective_first + effective_second - 0.001
    if distance < minimum or distance > maximum:
        return None
    direction = delta / max(distance, 1e-9)
    perpendicular = np.array([-direction[1], direction[0]], dtype=float) * bend
    along = (
        effective_first * effective_first
        - effective_second * effective_second
        + distance * distance
    ) / (2.0 * distance)
    height = math.sqrt(max(0.0, effective_first * effective_first - along * along))
    middle = root + direction * along + perpendicular * height
    cosine = max(
        -1.0,
        min(
            1.0,
            (
                effective_first * effective_first
                + effective_second * effective_second
                - distance * distance
            )
            / (2.0 * effective_first * effective_second),
        ),
    )
    joint_angle = math.degrees(math.acos(cosine))
    return middle, joint_angle, distance / (first + second)


def _bend_vertical_offset(
    root: np.ndarray,
    target: np.ndarray,
    middle: np.ndarray,
) -> float:
    direction = target - root
    squared_length = float(np.dot(direction, direction))
    if squared_length <= 1e-12:
        return 0.0
    projection = root + direction * (
        float(np.dot(middle - root, direction)) / squared_length
    )
    return float(middle[1] - projection[1])


def _bend_direction(
    root: np.ndarray,
    target: np.ndarray,
    middle: np.ndarray,
) -> str:
    offset = _bend_vertical_offset(root, target, middle)
    if offset < -1e-6:
        return "down"
    if offset > 1e-6:
        return "up"
    return "neutral"


def _bend_sign_from_joint(
    root: np.ndarray,
    target: np.ndarray,
    middle: np.ndarray,
) -> float:
    return 1.0 if _orientation(root, target, middle) >= 0.0 else -1.0


def _preferred_bend_sign(
    root: np.ndarray,
    target: np.ndarray,
    first: float,
    second: float,
    limb: str,
) -> Optional[float]:
    solutions = []
    for bend in (-1.0, 1.0):
        solution = _two_link_joint(root, target, first, second, bend)
        if solution:
            middle, _, _ = solution
            vertical_offset = _bend_vertical_offset(root, target, middle)
            side = -1.0 if limb in {"lh", "lf"} else 1.0
            outward_offset = float((middle[0] - root[0]) * side)
            if limb in {"lh", "rh"}:
                score = (vertical_offset, -outward_offset, bend)
            else:
                score = (-vertical_offset, -outward_offset, bend)
            solutions.append((score, bend))
    return min(solutions, default=(None, None), key=lambda item: item[0])[1]


def normal_bend_is_valid(pose: PoseEvaluation, limb: str) -> bool:
    expected = "down" if limb in {"lh", "rh"} else "up"
    return pose.bend_directions.get(limb) in {expected, "neutral"}


def _free_limb_points(
    root: np.ndarray,
    first: float,
    second: float,
    limb: str,
) -> Tuple[np.ndarray, np.ndarray]:
    side = -1.0 if limb in {"lh", "lf"} else 1.0
    if limb in {"lh", "rh"}:
        first_direction = np.array([side * 0.45, -0.89], dtype=float)
        second_direction = np.array([side * 0.05, -0.999], dtype=float)
    else:
        first_direction = np.array([side * 0.38, -0.925], dtype=float)
        second_direction = np.array([side * 0.05, -0.999], dtype=float)
    first_direction /= np.linalg.norm(first_direction)
    second_direction /= np.linalg.norm(second_direction)
    middle = root + first_direction * first
    end = middle + second_direction * second
    return middle, end


def _unique_values(values: Iterable[float], limit: int) -> List[float]:
    unique = sorted({round(float(value), 4) for value in values})
    if len(unique) <= limit:
        return unique
    indices = np.linspace(0, len(unique) - 1, limit).round().astype(int)
    return [unique[index] for index in indices]


def _candidate_body_positions(
    contact_points: Dict[str, np.ndarray],
    profile: ClimberProfile,
    previous_pose: Optional[PoseEvaluation] = None,
) -> Iterable[Tuple[np.ndarray, float, float, float]]:
    hand_points = [contact_points[key] for key in ("lh", "rh") if key in contact_points]
    foot_points = [contact_points[key] for key in ("lf", "rf") if key in contact_points]
    hand_center = np.mean(hand_points, axis=0) if hand_points else np.array([1.0, 1.8])
    foot_center = np.mean(foot_points, axis=0) if foot_points else hand_center - np.array([0.0, 0.7])
    arm_length = (
        profile.upper_arm_cm + profile.forearm_cm + profile.hand_reach_cm
    ) / 100.0
    leg_length = (profile.thigh_cm + profile.shin_cm) / 100.0
    torso_length = profile.torso_length_cm / 100.0

    blended_x = foot_center[0] * 0.58 + hand_center[0] * 0.42
    foot_based_y = foot_center[1] + leg_length * 0.56
    hand_based_y = hand_center[1] - torso_length - arm_length * 0.48
    blended_y = (foot_based_y + hand_based_y) / 2.0
    lean_limit = 18.0 + profile.capabilities.core_tension * 0.12
    if previous_pose:
        x_values = _unique_values(
            [
                previous_pose.hip[0] - 0.18,
                previous_pose.hip[0],
                previous_pose.hip[0] + 0.18,
            ],
            3,
        )
        y_values = _unique_values(
            [
                previous_pose.hip[1] - 0.18,
                previous_pose.hip[1],
                previous_pose.hip[1] + 0.18,
            ],
            3,
        )
        lean_values = _unique_values(
            [
                previous_pose.torso_angle_degrees,
                0.0,
                -lean_limit if previous_pose.torso_angle_degrees <= 0 else lean_limit,
            ],
            2,
        )
    else:
        x_values = _unique_values(
            [
                blended_x + offset
                for offset in (-0.36, -0.24, -0.12, 0.0, 0.12, 0.24, 0.36)
            ]
            + [foot_center[0], hand_center[0]],
            5,
        )
        y_values = _unique_values(
            [
                foot_based_y - 0.15,
                foot_based_y,
                foot_based_y + 0.15,
                hand_based_y - 0.12,
                hand_based_y,
                hand_based_y + 0.12,
                blended_y,
            ],
            5,
        )
        lean_values = (-lean_limit, 0.0, lean_limit)

    for x_value in x_values:
        for y_value in y_values:
            for lean_degrees in lean_values:
                lateral_offset = abs(float(hand_center[0] - x_value))
                crouch_depth = max(0.0, float(foot_center[1] + leg_length * 0.52 - y_value))
                shoulder_z = min(
                    SHOULDER_WALL_RANGE[1],
                    max(SHOULDER_WALL_RANGE[0], 0.085 + lateral_offset * 0.11 + abs(lean_degrees) * 0.0007),
                )
                hip_z = min(
                    HIP_WALL_RANGE[1],
                    max(HIP_WALL_RANGE[0], shoulder_z + 0.045 + crouch_depth * 0.08),
                )
                yield np.array([x_value, y_value], dtype=float), lean_degrees, shoulder_z, hip_z


def solve_pose_candidates(
    contacts: Dict[str, Optional[str]],
    profile: ClimberProfile,
    setup: Optional[Dict[str, Hold]] = None,
    hold_profiles: Optional[Dict[str, HoldPhysicsProfile]] = None,
    previous_pose: Optional[PoseEvaluation] = None,
    limit: int = 4,
) -> List[PoseEvaluation]:
    if not any(contacts.get(key) for key in ("lh", "rh")):
        return []
    if not any(contacts.get(key) for key in ("lf", "rf")):
        return []

    targets = {
        key: contact_point(hold_id, key, setup, hold_profiles)
        for key, hold_id in contacts.items()
        if hold_id
    }
    if (
        contacts.get("lh")
        and contacts.get("rh")
        and contacts["lh"] != contacts["rh"]
        and targets["lh"][0] > targets["rh"][0] + 1e-6
    ):
        return []
    if (
        contacts.get("lf")
        and contacts.get("rf")
        and contacts["lf"] != contacts["rf"]
        and targets["lf"][0] > targets["rf"][0] + 1e-6
    ):
        return []

    lengths = {
        "lh": (
            profile.upper_arm_cm / 100.0,
            (profile.forearm_cm + profile.hand_reach_cm) / 100.0,
        ),
        "rh": (
            profile.upper_arm_cm / 100.0,
            (profile.forearm_cm + profile.hand_reach_cm) / 100.0,
        ),
        "lf": (profile.thigh_cm / 100.0, profile.shin_cm / 100.0),
        "rf": (profile.thigh_cm / 100.0, profile.shin_cm / 100.0),
    }
    joint_names = {
        "lh": ("left_elbow", "left_hand"),
        "rh": ("right_elbow", "right_hand"),
        "lf": ("left_knee", "left_foot"),
        "rf": ("right_knee", "right_foot"),
    }
    torso_length = profile.torso_length_cm / 100.0
    shoulder_half = profile.shoulder_width_cm / 200.0
    hip_half = profile.hip_width_cm / 200.0
    candidates: List[PoseEvaluation] = []

    for position_index, (hip, lean_degrees, shoulder_z, hip_z) in enumerate(
        _candidate_body_positions(targets, profile, previous_pose)
    ):
        lean_radians = math.radians(lean_degrees)
        torso_axis = np.array([math.sin(lean_radians), math.cos(lean_radians)], dtype=float)
        width_axis = np.array([torso_axis[1], -torso_axis[0]], dtype=float)
        shoulder = hip + torso_axis * torso_length
        roots = {
            "lh": shoulder - width_axis * shoulder_half,
            "rh": shoulder + width_axis * shoulder_half,
            "lf": hip - width_axis * hip_half,
            "rf": hip + width_axis * hip_half,
        }
        normal_bends: Dict[str, float] = {}
        invalid_roots = False
        for key, target in targets.items():
            first, second = lengths[key]
            bend = _preferred_bend_sign(roots[key], target, first, second, key)
            if bend is None:
                invalid_roots = True
                break
            normal_bends[key] = bend
        if invalid_roots:
            continue
        bend_patterns = [dict(normal_bends)]
        for key in ("lf", "rf"):
            if key in normal_bends:
                alternate = dict(normal_bends)
                alternate[key] *= -1.0
                bend_patterns.append(alternate)

        for bend_index, bend_preferences in enumerate(bend_patterns):
            extensions: Dict[str, float] = {}
            joint_angles: Dict[str, float] = {}
            middle_points: Dict[str, np.ndarray] = {}
            end_points: Dict[str, np.ndarray] = {}
            bend_directions: Dict[str, str] = {}
            invalid = False
            extension_cost = 0.0

            for key, root in roots.items():
                hold_id = contacts.get(key)
                first, second = lengths[key]
                if not hold_id:
                    middle, end = _free_limb_points(root, first, second, key)
                    middle_points[key] = middle
                    end_points[key] = end
                    extensions[key] = 0.0
                    joint_angles[key] = 170.0
                    bend_directions[key] = (
                        "down" if key in {"lh", "rh"} else "up"
                    )
                    continue
                target = targets[key]
                solution = _two_link_joint(root, target, first, second, bend_preferences[key])
                if not solution:
                    invalid = True
                    break
                middle, joint_angle, extension = solution
                if key in {"lh", "rh"} and not 18.0 <= joint_angle <= 178.0:
                    invalid = True
                    break
                if key in {"lf", "rf"} and not 22.0 <= joint_angle <= 175.0:
                    invalid = True
                    break
                if key in {"lf", "rf"}:
                    maximum_high_step = 0.18 + profile.capabilities.hip_mobility / 210.0
                    if target[1] - hip[1] > maximum_high_step:
                        invalid = True
                        break
                middle_points[key] = middle
                end_points[key] = target
                extensions[key] = extension
                joint_angles[key] = joint_angle
                bend_directions[key] = _bend_direction(root, target, middle)
                extension_cost += max(0.0, extension - 0.72) ** 2 * 34.0
            if invalid:
                continue

            hand_points = [targets[key] for key in ("lh", "rh") if key in targets]
            foot_points = [targets[key] for key in ("lf", "rf") if key in targets]
            hand_center = np.mean(hand_points, axis=0)
            foot_center = np.mean(foot_points, axis=0)
            torso_offset = abs(float(hand_center[0] - foot_center[0]))
            wall_cost = abs(shoulder_z - 0.11) * 8.0 + abs(hip_z - 0.16) * 5.0
            posture_cost = extension_cost + abs(lean_degrees) * 0.09 + torso_offset * 5.5 + wall_cost
            posture_cost += sum(
                7.0
                for key in ("lf", "rf")
                if key in bend_preferences
                and bend_preferences[key] != normal_bends.get(key)
            )

            if contacts.get("lf") and contacts.get("rf") and contacts["lf"] != contacts["rf"]:
                foot_gap = abs(float(targets["lf"][1] - targets["rf"][1]))
                posture_cost += max(0.0, foot_gap - 0.4) * 12.0
            hand_foot_matches = sum(
                1
                for hand_key in ("lh", "rh")
                for foot_key in ("lf", "rf")
                if contacts.get(hand_key) and contacts.get(hand_key) == contacts.get(foot_key)
            )
            posture_cost += hand_foot_matches * 8.0
            if contacts.get("lf") and contacts.get("lf") == contacts.get("rf"):
                posture_cost += 18.0
            if len({value for value in contacts.values() if value}) <= 2:
                posture_cost += 16.0

            if previous_pose:
                pelvis_shift = float(np.linalg.norm(hip - previous_pose.hip))
                shoulder_shift = float(np.linalg.norm(shoulder - previous_pose.shoulder))
                depth_shift = abs(shoulder_z - previous_pose.shoulder_wall_distance) + abs(
                    hip_z - previous_pose.hip_wall_distance
                )
                if pelvis_shift > 0.58 or shoulder_shift > 0.58 or depth_shift > 0.32:
                    continue
                posture_cost += pelvis_shift * 9.0 + shoulder_shift * 7.0 + depth_shift * 5.0

            root_depth = {"lh": shoulder_z, "rh": shoulder_z, "lf": hip_z, "rf": hip_z}
            center_of_mass = hip * 0.58 + shoulder * 0.42
            center_z = hip_z * 0.58 + shoulder_z * 0.42
            joints: Dict[str, SimulationJointPoint] = {
                "pelvis": point(hip, hip_z),
                "shoulder_center": point(shoulder, shoulder_z),
                "head": point(
                    shoulder + torso_axis * (profile.height_cm / 100.0 * 0.12),
                    shoulder_z,
                ),
                "left_shoulder": point(roots["lh"], shoulder_z),
                "right_shoulder": point(roots["rh"], shoulder_z),
                "left_hip": point(roots["lf"], hip_z),
                "right_hip": point(roots["rf"], hip_z),
            }
            for key, (middle_name, end_name) in joint_names.items():
                middle_z = min(
                    0.30,
                    root_depth[key] * (0.58 if key in {"lh", "rh"} else 0.62)
                    + (0.025 if bend_preferences.get(key, -1.0) < 0 else 0.045),
                )
                joints[middle_name] = point(middle_points[key], middle_z)
                joints[end_name] = point(
                    end_points[key],
                    0.0 if contacts.get(key) else root_depth[key] * 0.4,
                )
            if pose_has_crossing(joints) or not body_dimensions_valid(joints, profile):
                continue

            pose_id = (
                f"{position_index}:{bend_index}:"
                f"{hip[0]:.3f}:{hip[1]:.3f}:{lean_degrees:.1f}:{shoulder_z:.3f}:{hip_z:.3f}"
            )
            candidates.append(
                PoseEvaluation(
                    valid=True,
                    joints=joints,
                    roots={key: value.copy() for key, value in roots.items()},
                    center_of_mass=point(center_of_mass, center_z),
                    extensions=extensions,
                    joint_angles=joint_angles,
                    posture_cost=round(posture_cost, 4),
                    torso_offset=round(torso_offset, 4),
                    pose_id=pose_id,
                    hip=hip.copy(),
                    shoulder=shoulder.copy(),
                    torso_angle_degrees=round(lean_degrees, 3),
                    shoulder_wall_distance=round(shoulder_z, 4),
                    hip_wall_distance=round(hip_z, 4),
                    contact_points={key: value.copy() for key, value in targets.items()},
                    bend_directions=bend_directions,
                )
            )
    candidates.sort(key=lambda item: (item.posture_cost, item.pose_id))
    selected: List[PoseEvaluation] = candidates[:1]
    remaining = candidates[1:]
    if selected:
        first_parts = selected[0].pose_id.split(":")
        alternate_index = next(
            (
                index
                for index, candidate in enumerate(remaining)
                if candidate.pose_id.split(":")[0] == first_parts[0]
                and candidate.pose_id.split(":")[1] != first_parts[1]
            ),
            None,
        )
        if alternate_index is not None and len(selected) < max(1, limit):
            selected.append(remaining.pop(alternate_index))
    while remaining and len(selected) < max(1, limit):
        candidate_index = max(
            range(len(remaining)),
            key=lambda index: (
                min(
                    float(np.linalg.norm(remaining[index].hip - existing.hip))
                    + abs(
                        remaining[index].torso_angle_degrees
                        - existing.torso_angle_degrees
                    )
                    * 0.004
                    for existing in selected
                )
                - remaining[index].posture_cost * 0.004,
                -remaining[index].posture_cost,
            ),
        )
        candidate = remaining.pop(candidate_index)
        selected.append(candidate)
    selected.sort(key=lambda item: (item.posture_cost, item.pose_id))
    return selected


def solve_pose(
    contacts: Dict[str, Optional[str]],
    profile: ClimberProfile,
    setup: Optional[Dict[str, Hold]] = None,
    hold_profiles: Optional[Dict[str, HoldPhysicsProfile]] = None,
    previous_pose: Optional[PoseEvaluation] = None,
) -> PoseEvaluation:
    candidates = solve_pose_candidates(
        contacts,
        profile,
        setup,
        hold_profiles,
        previous_pose=previous_pose,
        limit=1,
    )
    if candidates:
        return candidates[0]
    return PoseEvaluation(valid=False, reason="当前四肢接触没有符合关节范围且不交叉的人体姿态")


def _ability_scale(limb: str, profile: ClimberProfile) -> float:
    if limb in {"lh", "rh"}:
        ability = profile.capabilities.finger_strength * 0.65 + profile.capabilities.pull_power * 0.35
    else:
        ability = profile.capabilities.core_tension * 0.45 + profile.capabilities.technique * 0.55
    return 0.74 + ability / 210.0


def solve_contact_loads(
    contacts: Dict[str, Optional[str]],
    pose: PoseEvaluation,
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> LoadEvaluation:
    active: List[Tuple[str, str, np.ndarray, float]] = []
    capacity_by_hold: Dict[str, float] = {}
    for limb, hold_id in contacts.items():
        if not hold_id:
            continue
        hold = setup.get(hold_id)
        if not hold:
            return LoadEvaluation(stable=False, reason=f"接触点 {hold_id} 不存在于岩板")
        physics = _hold_profile_for(hold, hold_profiles)
        base_capacity = physics.capacity if physics else 0.58
        preferred = ((physics.preferred_direction_degrees if physics else 180) + hold.rotation) % 360
        tolerance = physics.direction_tolerance_degrees if physics else 75
        direction_error = angular_distance(preferred, 90.0)
        if direction_error <= tolerance:
            direction_fit = 1.0
        else:
            direction_fit = max(0.48, 1.0 - (direction_error - tolerance) / max(1.0, 180.0 - tolerance) * 0.52)
        capacity = base_capacity * _ability_scale(limb, profile) * (0.72 + direction_fit * 0.28)
        active.append(
            (
                limb,
                hold_id,
                contact_point(hold_id, limb, setup, hold_profiles),
                max(0.12, capacity),
            )
        )
        capacity_by_hold[hold_id] = max(capacity_by_hold.get(hold_id, 0.0), max(0.12, capacity))

    if len({hold_id for _, hold_id, _, _ in active}) < 2:
        return LoadEvaluation(stable=False, reason="静态支撑少于两个不同岩点", peak_ratio=2.0, residual=1.0)

    gravity_parallel = math.cos(math.radians(BOARD_ANGLE_DEGREES))
    matrix = np.array(
        [
            [1.0 for _ in active],
            [position[0] - pose.center_of_mass.x for _, _, position, _ in active],
        ],
        dtype=float,
    )
    target = np.array([gravity_parallel, 0.0], dtype=float)
    best: Optional[Tuple[float, float, np.ndarray]] = None

    force_candidates: List[np.ndarray] = []
    offsets = matrix[1]
    for index, offset in enumerate(offsets):
        if abs(float(offset)) <= 1e-8:
            forces = np.zeros(len(active), dtype=float)
            forces[index] = gravity_parallel
            force_candidates.append(forces)
    for first_index in range(len(active)):
        for second_index in range(first_index + 1, len(active)):
            first_offset = float(offsets[first_index])
            second_offset = float(offsets[second_index])
            denominator = second_offset - first_offset
            if abs(denominator) <= 1e-9:
                continue
            first_force = gravity_parallel * second_offset / denominator
            second_force = -gravity_parallel * first_offset / denominator
            if first_force < -1e-8 or second_force < -1e-8:
                continue
            forces = np.zeros(len(active), dtype=float)
            forces[first_index] = max(0.0, first_force)
            forces[second_index] = max(0.0, second_force)
            force_candidates.append(forces)
    if len(active) > 2:
        gram = matrix @ matrix.T
        determinant = float(np.linalg.det(gram))
        if abs(determinant) > 1e-10:
            distributed = matrix.T @ np.linalg.solve(gram, target)
            if np.all(distributed >= -1e-8):
                force_candidates.append(np.maximum(distributed, 0.0))

    for expanded in force_candidates:
        residual = float(np.linalg.norm(matrix @ expanded - target) / max(gravity_parallel, 1e-9))
        ratios = [expanded[index] / active[index][3] for index in range(len(active))]
        peak = max(ratios, default=2.0)
        score = peak + residual * 5.0
        if best is None or score < best[0]:
            best = (score, residual, expanded)

    if not best:
        return LoadEvaluation(stable=False, reason="接触点无法形成非负静力平衡", peak_ratio=2.0, residual=1.0)

    _, residual, forces = best
    contact_loads = {
        active[index][0]: round(float(forces[index] / active[index][3]), 4)
        for index in range(len(active))
    }
    hold_force_totals: Dict[str, float] = {}
    for index, (_, hold_id, _, _) in enumerate(active):
        hold_force_totals[hold_id] = hold_force_totals.get(hold_id, 0.0) + float(forces[index])
    group_ratios = [
        force / max(capacity_by_hold[hold_id] * (1.15 if sum(item[1] == hold_id for item in active) > 1 else 1.0), 0.1)
        for hold_id, force in hold_force_totals.items()
    ]
    hand_capacity = sum(
        capacity
        for limb, _, _, capacity in active
        if limb in {"lh", "rh"}
    )
    gravity_normal = math.sin(math.radians(BOARD_ANGLE_DEGREES))
    normal_ratio = gravity_normal / max(hand_capacity * 0.86 + profile.capabilities.core_tension / 500.0, 0.1)
    peak_ratio = max([*contact_loads.values(), *group_ratios, normal_ratio], default=2.0)
    residual_limit = 0.12 + profile.capabilities.core_tension / 500.0
    stable = residual <= residual_limit and peak_ratio <= STATIC_LOAD_LIMIT
    if residual > residual_limit:
        reason = "重心无法在现有接触间形成静力平衡"
    elif peak_ratio > STATIC_LOAD_LIMIT:
        reason = "岩点承载或墙外拉力超过当前画像能力"
    else:
        reason = ""
    return LoadEvaluation(
        stable=stable,
        reason=reason,
        contact_loads=contact_loads,
        peak_ratio=round(float(peak_ratio), 4),
        residual=round(residual, 4),
        normal_ratio=round(normal_ratio, 4),
    )


def evaluate_state(
    contacts: Dict[str, Optional[str]],
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
    previous_pose: Optional[PoseEvaluation] = None,
) -> StateEvaluation:
    candidates = evaluate_state_candidates(
        contacts,
        profile,
        setup,
        hold_profiles,
        previous_pose=previous_pose,
        limit=4,
    )
    if candidates:
        return candidates[0]
    pose = solve_pose(contacts, profile, setup, hold_profiles, previous_pose=previous_pose)
    reason = pose.reason or "当前接触没有可连续到达的稳定姿态"
    empty_load = LoadEvaluation(stable=False, reason=reason, peak_ratio=2.0, residual=1.0)
    return StateEvaluation(valid=False, reason=reason, pose=pose, load=empty_load, stress=2.0)


def _state_evaluation_from_pose(
    contacts: Dict[str, Optional[str]],
    pose: PoseEvaluation,
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> StateEvaluation:
    load = solve_contact_loads(contacts, pose, profile, setup, hold_profiles)
    extension_ratio = max(pose.extensions.values(), default=0.0)
    mobility_ratio = max(
        [
            extension_ratio,
            max(0.0, pose.torso_offset - 0.25) / max(0.18 + profile.capabilities.hip_mobility / 350.0, 0.1),
        ]
    )
    core_ratio = pose.torso_offset / max(0.34 + profile.capabilities.core_tension / 260.0, 0.2)
    stress = max(extension_ratio, mobility_ratio, core_ratio, load.peak_ratio, load.residual * 3.0)
    demand = {
        "reach": extension_ratio * 100.0,
        "finger_strength": load.peak_ratio * 100.0,
        "core_tension": core_ratio * 100.0,
        "mobility": mobility_ratio * 100.0,
    }
    return StateEvaluation(
        valid=load.stable,
        reason=load.reason,
        pose=pose,
        load=load,
        stress=round(stress, 4),
        demand=demand,
    )


def evaluate_pose_contacts(
    contacts: Dict[str, Optional[str]],
    pose: PoseEvaluation,
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> StateEvaluation:
    """Recheck a continuous pose after one contact is released."""
    return _state_evaluation_from_pose(
        contacts,
        pose,
        profile,
        setup,
        hold_profiles,
    )


def evaluate_state_candidates(
    contacts: Dict[str, Optional[str]],
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
    previous_pose: Optional[PoseEvaluation] = None,
    limit: int = 4,
) -> List[StateEvaluation]:
    pose_candidates = solve_pose_candidates(
        contacts,
        profile,
        setup,
        hold_profiles,
        previous_pose=previous_pose,
        # Load balance can reject the geometrically prettiest pose. Keep a
        # broader posture pool, then select the four stable, diverse poses.
        limit=max(limit * 2, 12),
    )
    evaluations = [
        _state_evaluation_from_pose(contacts, pose, profile, setup, hold_profiles)
        for pose in pose_candidates
    ]
    valid = [evaluation for evaluation in evaluations if evaluation.valid]
    valid.sort(
        key=lambda item: (
            item.pose.posture_cost,
            item.load.peak_ratio,
            item.pose.pose_id,
        )
    )
    selected: List[StateEvaluation] = valid[:1]
    remaining = valid[1:]
    if selected:
        first_parts = selected[0].pose.pose_id.split(":")
        alternate_index = next(
            (
                index
                for index, evaluation in enumerate(remaining)
                if evaluation.pose.pose_id.split(":")[0] == first_parts[0]
                and evaluation.pose.pose_id.split(":")[1] != first_parts[1]
            ),
            None,
        )
        if alternate_index is not None and len(selected) < max(1, limit):
            selected.append(remaining.pop(alternate_index))
    while remaining and len(selected) < max(1, limit):
        evaluation_index = max(
            range(len(remaining)),
            key=lambda index: (
                min(
                    float(
                        np.linalg.norm(
                            remaining[index].pose.hip - existing.pose.hip
                        )
                    )
                    + abs(
                        remaining[index].pose.torso_angle_degrees
                        - existing.pose.torso_angle_degrees
                    )
                    * 0.004
                    for existing in selected
                )
                - remaining[index].pose.posture_cost * 0.004,
                -remaining[index].pose.posture_cost,
            ),
        )
        evaluation = remaining.pop(evaluation_index)
        selected.append(evaluation)
    selected.sort(
        key=lambda item: (
            item.pose.posture_cost,
            item.load.peak_ratio,
            item.pose.pose_id,
        )
    )
    return selected


def _interpolate_pose(
    first: PoseEvaluation,
    second: PoseEvaluation,
    fraction: float,
    profile: ClimberProfile,
    moving_limb: Optional[str] = None,
) -> PoseEvaluation:
    dimensions = BodyDimensions.from_profile(profile)
    hip = first.hip + (second.hip - first.hip) * fraction
    hip_path = second.hip - first.hip
    hip_path_length = float(np.linalg.norm(hip_path))
    if hip_path_length > 1e-9:
        hip += (
            np.array([-hip_path[1], hip_path[0]], dtype=float)
            / hip_path_length
            * math.sin(math.pi * fraction)
            * 0.04
        )
    torso_angle = (
        first.torso_angle_degrees
        + (second.torso_angle_degrees - first.torso_angle_degrees) * fraction
    )
    lean_radians = math.radians(torso_angle)
    torso_axis = np.array(
        [math.sin(lean_radians), math.cos(lean_radians)],
        dtype=float,
    )
    width_axis = np.array([torso_axis[1], -torso_axis[0]], dtype=float)
    shoulder = hip + torso_axis * dimensions.torso
    shoulder_z = (
        first.shoulder_wall_distance
        + (second.shoulder_wall_distance - first.shoulder_wall_distance) * fraction
    )
    hip_z = (
        first.hip_wall_distance
        + (second.hip_wall_distance - first.hip_wall_distance) * fraction
    )
    roots = {
        "lh": shoulder - width_axis * (dimensions.shoulder_width / 2.0),
        "rh": shoulder + width_axis * (dimensions.shoulder_width / 2.0),
        "lf": hip - width_axis * (dimensions.hip_width / 2.0),
        "rf": hip + width_axis * (dimensions.hip_width / 2.0),
    }
    root_names = {
        "lh": "left_shoulder",
        "rh": "right_shoulder",
        "lf": "left_hip",
        "rf": "right_hip",
    }
    joint_names = {
        "lh": ("left_elbow", "left_hand"),
        "rh": ("right_elbow", "right_hand"),
        "lf": ("left_knee", "left_foot"),
        "rf": ("right_knee", "right_foot"),
    }
    lengths = {
        "lh": (dimensions.upper_arm, dimensions.forearm_hand),
        "rh": (dimensions.upper_arm, dimensions.forearm_hand),
        "lf": (dimensions.thigh, dimensions.shin),
        "rf": (dimensions.thigh, dimensions.shin),
    }
    joints: Dict[str, SimulationJointPoint] = {
        "pelvis": point(hip, hip_z),
        "shoulder_center": point(shoulder, shoulder_z),
        "head": point(shoulder + torso_axis * dimensions.head, shoulder_z),
        "left_shoulder": point(roots["lh"], shoulder_z),
        "right_shoulder": point(roots["rh"], shoulder_z),
        "left_hip": point(roots["lf"], hip_z),
        "right_hip": point(roots["rf"], hip_z),
    }
    extensions: Dict[str, float] = {}
    joint_angles: Dict[str, float] = {}
    bend_directions: Dict[str, str] = {}
    preferred_pose = first if fraction < 0.5 else second
    for limb, (middle_name, end_name) in joint_names.items():
        start_end = _point_array(first.joints[end_name])
        finish_end = _point_array(second.joints[end_name])
        if limb == moving_limb:
            start_root = _point_array(first.joints[root_names[limb]])
            finish_root = _point_array(second.joints[root_names[limb]])
            start_vector = start_end - start_root
            finish_vector = finish_end - finish_root
            start_angle = math.atan2(start_vector[1], start_vector[0])
            finish_angle = math.atan2(finish_vector[1], finish_vector[0])
            angle_delta = (finish_angle - start_angle + math.pi) % (
                math.pi * 2.0
            ) - math.pi
            radius = (
                float(np.linalg.norm(start_vector)) * (1.0 - fraction)
                + float(np.linalg.norm(finish_vector)) * fraction
            )
            angle = start_angle + angle_delta * fraction
            end = roots[limb] + np.array(
                [math.cos(angle), math.sin(angle)],
                dtype=float,
            ) * radius
        else:
            end = start_end + (finish_end - start_end) * fraction
        preferred_root = _point_array(preferred_pose.joints[root_names[limb]])
        preferred_end = _point_array(preferred_pose.joints[end_name])
        preferred_middle = _point_array(preferred_pose.joints[middle_name])
        bend = _bend_sign_from_joint(
            preferred_root,
            preferred_end,
            preferred_middle,
        )
        solution = _two_link_joint(
            roots[limb],
            end,
            lengths[limb][0],
            lengths[limb][1],
            bend,
        )
        if not solution:
            return PoseEvaluation(
                valid=False,
                reason=f"固定身体比例下，{limb} 中间姿态没有逆运动学解",
                hip=hip,
                shoulder=shoulder,
                torso_angle_degrees=torso_angle,
                shoulder_wall_distance=shoulder_z,
                hip_wall_distance=hip_z,
            )
        middle, joint_angle, extension = solution
        middle_z = (
            (first.joints[middle_name].z or 0.0)
            + ((second.joints[middle_name].z or 0.0) - (first.joints[middle_name].z or 0.0))
            * fraction
        )
        end_z = (
            (first.joints[end_name].z or 0.0)
            + ((second.joints[end_name].z or 0.0) - (first.joints[end_name].z or 0.0))
            * fraction
        )
        joints[middle_name] = point(middle, middle_z)
        joints[end_name] = point(end, end_z)
        extensions[limb] = extension
        joint_angles[limb] = joint_angle
        bend_directions[limb] = _bend_direction(roots[limb], end, middle)
    center_xy = hip * 0.58 + shoulder * 0.42
    center_z = hip_z * 0.58 + shoulder_z * 0.42
    valid = body_dimensions_valid(joints, profile)
    return PoseEvaluation(
        valid=valid,
        reason="" if valid else "中间姿态改变了固定身体比例",
        joints=joints,
        roots={key: value.copy() for key, value in roots.items()},
        center_of_mass=point(center_xy, center_z),
        extensions=extensions,
        joint_angles=joint_angles,
        posture_cost=(
            first.posture_cost
            + (second.posture_cost - first.posture_cost) * fraction
        ),
        torso_offset=(
            first.torso_offset
            + (second.torso_offset - first.torso_offset) * fraction
        ),
        pose_id=f"fixed-interpolation:{fraction:.4f}",
        hip=hip,
        shoulder=shoulder,
        torso_angle_degrees=torso_angle,
        shoulder_wall_distance=shoulder_z,
        hip_wall_distance=hip_z,
        bend_directions=bend_directions,
    )


def validate_static_pose_transition(
    start: StateEvaluation,
    support: StateEvaluation,
    landing: StateEvaluation,
    from_contacts: Dict[str, Optional[str]],
    to_contacts: Dict[str, Optional[str]],
    moving_limb: str,
    profile: ClimberProfile,
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
    duration_seconds: float,
    sample_hz: float = 30.0,
) -> Tuple[bool, str]:
    if not (start.valid and support.valid and landing.valid):
        return False, "动作关键姿态未通过静态受力校验"
    endpoint_names = {
        "lh": "left_hand",
        "rh": "right_hand",
        "lf": "left_foot",
        "rf": "right_foot",
    }
    support_contacts = dict(from_contacts)
    support_contacts[moving_limb] = None

    if sample_hz <= 0:
        key_poses = (start.pose, support.pose, landing.pose)
        if any(
            not body_dimensions_valid(pose.joints, profile)
            for pose in key_poses
        ):
            return False, "动作关键姿态改变了固定身体比例"
        if any(pose_has_crossing(pose.joints) for pose in key_poses):
            return False, "动作过渡中出现左右肢体穿插"
        if any(
            pose.shoulder_wall_distance > SHOULDER_WALL_HARD_LIMIT
            or pose.hip_wall_distance > HIP_WALL_HARD_LIMIT
            for pose in key_poses
        ):
            return False, "动作过渡中身体离墙过远"
        for first_pose, second_pose, phase_fraction in (
            (start.pose, support.pose, 0.42),
            (support.pose, landing.pose, 0.58),
        ):
            phase_duration = max(1e-6, duration_seconds * phase_fraction)
            com_distance = math.sqrt(
                (second_pose.center_of_mass.x - first_pose.center_of_mass.x) ** 2
                + (second_pose.center_of_mass.y - first_pose.center_of_mass.y) ** 2
                + (
                    (second_pose.center_of_mass.z or 0.0)
                    - (first_pose.center_of_mass.z or 0.0)
                )
                ** 2
            )
            if com_distance / phase_duration > MAX_STATIC_COM_SPEED + 1e-6:
                return False, "重心移动速度超过静态动作上限"
            for key, first_joint in first_pose.joints.items():
                second_joint = second_pose.joints.get(key)
                if not second_joint:
                    continue
                if key.endswith(("elbow", "knee")):
                    continue
                joint_distance = math.sqrt(
                    (second_joint.x - first_joint.x) ** 2
                    + (second_joint.y - first_joint.y) ** 2
                    + ((second_joint.z or 0.0) - (first_joint.z or 0.0)) ** 2
                )
                if joint_distance / phase_duration > MAX_STATIC_JOINT_SPEED + 1e-6:
                    return False, "关节移动速度超过静态动作上限"
        for pose, contacts in ((support.pose, support_contacts), (landing.pose, to_contacts)):
            for limb, hold_id in contacts.items():
                if not hold_id or limb == moving_limb:
                    continue
                endpoint = pose.joints.get(endpoint_names[limb])
                if not endpoint:
                    return False, "支撑肢体缺少末端关节"
                anchor = contact_point(hold_id, limb, setup, hold_profiles)
                delta_x = endpoint.x - float(anchor[0])
                delta_y = endpoint.y - float(anchor[1])
                if delta_x * delta_x + delta_y * delta_y > 0.0101**2:
                    return False, "支撑肢体在动作过程中滑离接触锚点"
        return True, ""

    frame_count = max(3, int(math.ceil(max(duration_seconds, 0.4) * sample_hz)))
    previous_pose = start.pose
    previous_time = 0.0

    for frame in range(1, frame_count + 1):
        fraction = frame / frame_count
        if fraction <= 0.42:
            local = fraction / 0.42
            pose = _interpolate_pose(
                start.pose,
                support.pose,
                local,
                profile,
                moving_limb,
            )
            contacts = from_contacts if fraction < 0.42 else support_contacts
        else:
            local = (fraction - 0.42) / 0.58
            pose = _interpolate_pose(
                support.pose,
                landing.pose,
                local,
                profile,
                moving_limb,
            )
            contacts = support_contacts if frame < frame_count else to_contacts
        if not pose.valid or not body_dimensions_valid(pose.joints, profile):
            return False, pose.reason or "动作中间姿态改变了固定身体比例"

        current_time = duration_seconds * fraction
        delta_time = max(1e-6, current_time - previous_time)
        com_speed = math.sqrt(
            (pose.center_of_mass.x - previous_pose.center_of_mass.x) ** 2
            + (pose.center_of_mass.y - previous_pose.center_of_mass.y) ** 2
            + ((pose.center_of_mass.z or 0.0) - (previous_pose.center_of_mass.z or 0.0)) ** 2
        ) / delta_time
        if com_speed > MAX_STATIC_COM_SPEED + 1e-6:
            return False, "重心移动速度超过静态动作上限"
        for key, current_joint in pose.joints.items():
            prior_joint = previous_pose.joints.get(key)
            if not prior_joint:
                continue
            if key.endswith(("elbow", "knee")):
                continue
            joint_speed = math.sqrt(
                (current_joint.x - prior_joint.x) ** 2
                + (current_joint.y - prior_joint.y) ** 2
                + ((current_joint.z or 0.0) - (prior_joint.z or 0.0)) ** 2
            ) / delta_time
            if joint_speed > MAX_STATIC_JOINT_SPEED + 1e-6:
                return False, "关节移动速度超过静态动作上限"
        if (
            pose.shoulder_wall_distance > SHOULDER_WALL_HARD_LIMIT
            or pose.hip_wall_distance > HIP_WALL_HARD_LIMIT
        ):
            return False, "动作过渡中身体离墙过远"

        for limb, hold_id in contacts.items():
            if not hold_id or limb == moving_limb:
                continue
            endpoint = pose.joints.get(endpoint_names[limb])
            if not endpoint:
                return False, "支撑肢体缺少末端关节"
            anchor = contact_point(hold_id, limb, setup, hold_profiles)
            if np.linalg.norm(_point_array(endpoint) - anchor) > 0.0101:
                return False, "支撑肢体在动作过程中滑离接触锚点"

        previous_pose = pose
        previous_time = current_time
    return True, ""


def reachable_from_root(
    root: np.ndarray,
    target_id: str,
    first_length: float,
    second_length: float,
    limb: str = "lh",
    setup: Optional[Dict[str, Hold]] = None,
    hold_profiles: Optional[Dict[str, HoldPhysicsProfile]] = None,
) -> Tuple[bool, float]:
    distance = float(np.linalg.norm(contact_point(target_id, limb, setup, hold_profiles) - root))
    minimum = max(
        0.0,
        abs(first_length - second_length) - BODY_LENGTH_TOLERANCE * 2.0,
    )
    maximum = first_length + second_length - 0.001
    return minimum <= distance <= maximum, distance / max(first_length + second_length, 0.001)


def solve_dynamic_trajectory(
    start_com: SimulationJointPoint,
    end_com: SimulationJointPoint,
    profile: ClimberProfile,
    target_hold: Hold,
    target_physics: Optional[HoldPhysicsProfile],
) -> DynamicEvaluation:
    start = np.array([start_com.x, start_com.y], dtype=float)
    end = np.array([end_com.x, end_com.y], dtype=float)
    gravity = math.cos(math.radians(BOARD_ANGLE_DEGREES)) * 9.81
    maximum_launch_speed = 1.15 + profile.capabilities.pull_power * 0.014 + profile.capabilities.technique * 0.004
    best: Optional[Tuple[float, float, np.ndarray, np.ndarray]] = None

    for frame in range(18, 73):
        duration = frame / 60.0
        velocity = np.array(
            [
                (end[0] - start[0]) / duration,
                (end[1] - start[1] + 0.5 * gravity * duration * duration) / duration,
            ],
            dtype=float,
        )
        launch_speed = float(np.linalg.norm(velocity))
        catch_velocity_vector = velocity + np.array([0.0, -gravity * duration], dtype=float)
        catch_speed = float(np.linalg.norm(catch_velocity_vector))
        score = launch_speed + catch_speed * 0.28
        if best is None or score < best[0]:
            best = (score, duration, velocity, catch_velocity_vector)

    if not best:
        return DynamicEvaluation(feasible=False, reason="无法建立动态轨迹")
    _, duration, velocity, catch_velocity_vector = best
    launch_speed = float(np.linalg.norm(velocity))
    catch_speed = float(np.linalg.norm(catch_velocity_vector))
    base_capacity = target_physics.capacity if target_physics else 0.58
    ability_scale = 0.72 + (profile.capabilities.finger_strength * 0.65 + profile.capabilities.pull_power * 0.35) / 210.0
    direction_error = angular_distance(
        ((target_physics.preferred_direction_degrees if target_physics else 180) + target_hold.rotation) % 360,
        90.0,
    )
    direction_fit = max(0.58, 1.0 - direction_error / 420.0)
    catch_capacity = base_capacity * ability_scale * direction_fit
    catch_force_bodyweights = 0.42 + catch_speed * catch_speed / (2.0 * 9.81 * 0.48)
    catch_load_ratio = catch_force_bodyweights / max(catch_capacity, 0.1)
    launch_ratio = launch_speed / max(maximum_launch_speed, 0.1)
    feasible = launch_ratio <= 1.05 and catch_load_ratio <= 1.35
    if launch_ratio > 1.05:
        reason = "所需起跳速度超过当前爆发力画像"
    elif catch_load_ratio > 1.35:
        reason = "动态抓取冲击超过目标岩点或指力承载"
    else:
        reason = ""
    margin = min(1.0 / max(launch_ratio, 0.01), 1.35 / max(catch_load_ratio, 0.01), 1.0)
    internal_trajectory: List[Tuple[float, np.ndarray, np.ndarray]] = []
    internal_frame_count = max(2, int(math.ceil(duration * 60.0)))
    for sample in range(internal_frame_count + 1):
        time_value = duration * sample / internal_frame_count
        position = start + velocity * time_value + np.array([0.0, -0.5 * gravity * time_value * time_value])
        current_velocity = velocity + np.array([0.0, -gravity * time_value])
        if not np.all(np.isfinite(position)) or not np.all(np.isfinite(current_velocity)):
            return DynamicEvaluation(feasible=False, reason="动态轨迹数值不稳定")
        internal_trajectory.append((time_value, position, current_velocity))
    key_indices = sorted(
        {
            0,
            internal_frame_count // 4,
            internal_frame_count // 2,
            internal_frame_count * 3 // 4,
            internal_frame_count,
        }
    )
    trajectory = [internal_trajectory[index] for index in key_indices]
    return DynamicEvaluation(
        feasible=feasible,
        reason=reason,
        score=round(margin * 100.0, 1),
        duration_seconds=round(duration, 4),
        launch_velocity=round(launch_speed, 4),
        catch_velocity=round(catch_speed, 4),
        catch_load_ratio=round(catch_load_ratio, 4),
        trajectory=trajectory,
    )
