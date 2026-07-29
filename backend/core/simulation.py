"""Deterministic 2.5D climbing simulation for the fixed standard board."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from core.models import (
    BetaStep,
    ClimberCapabilities,
    ClimberProfile,
    ClimberRun,
    Hold,
    HoldPhysicsProfile,
    HoldType,
    Limb,
    SimulationAction,
    SimulationBatchRequest,
    SimulationBatchResult,
    SimulationFeedback,
    SimulationFeedbackRecord,
    SimulationFrame,
    SimulationJointPoint,
    SimulationRepairCandidate,
    SimulationReport,
    SimulationRequest,
    StandardBoardRouteDetail,
)
from core.moonboard_grading import DEFAULT_FONT_GRADE, FONT_GRADES, grade_from_number, grade_number
from core.simulation_solver import BetaPath, RouteSimulationSolver, SolveOutcome, state_dict
from core.simulation_physics import body_dimensions_valid, contact_point
from core.standard_board import detail_for, find_standard_route, query_standard_routes, validate_standard_roles


ENGINE_VERSION = "coordinated-2.5d-font-transfer-v1"
SOLVER_RULES_VERSION = "fixed-anthropometry-v1.4-natural-bends"
ACTION_LIBRARY_VERSION = "coordinated-primitives-v1.2"
POSE_CONFIG_VERSION = "fixed-proportions-four-pose-v1.4"
ANCHOR_MODEL_VERSION = "hold-center-only-v1.3"
DEPTH_MODEL_VERSION = "wall-depth-ranges-v1.2"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULTS_PATH = DATA_DIR / "simulation_defaults.json"
LOCAL_DIR = DATA_DIR / "local_simulation"
REPORTS_DIR = LOCAL_DIR / "reports"
LATEST_INDEX_PATH = LOCAL_DIR / "latest_reports.json"
HOLD_OVERRIDES_PATH = LOCAL_DIR / "hold_profiles.json"
FEEDBACK_PATH = LOCAL_DIR / "feedback.json"
MODIFICATION_LOG_PATH = DATA_DIR / "modification_log.json"

GRADE_ORDER = list(FONT_GRADES)
HOLD_DEMAND = {
    HoldType.JUG: 24.0,
    HoldType.CRIMP: 58.0,
    HoldType.SLOPER: 64.0,
    HoldType.PINCH: 52.0,
    HoldType.POCKET: 72.0,
    HoldType.FOOT: 34.0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _grade_number(value: Optional[str]) -> int:
    return grade_number(value or DEFAULT_FONT_GRADE)


def _capabilities_for_grade(grade: str) -> ClimberCapabilities:
    number = _grade_number(grade)
    # The calibrated product range begins at an already experienced climber,
    # so 6B must not be treated as a zero-strength capability profile.
    scaled_number = 3.0 + number * 7.0 / max(1, len(FONT_GRADES) - 1)
    base = min(92.0, 38.0 + scaled_number * 5.2)
    return ClimberCapabilities(
        ability_grade=FONT_GRADES[number],
        finger_strength=min(96.0, base + scaled_number * 0.8),
        pull_power=min(95.0, base + 3.0),
        core_tension=min(95.0, base + scaled_number * 0.5),
        hip_mobility=min(90.0, base + 2.0),
        shoulder_mobility=min(92.0, base + 4.0),
        endurance=min(96.0, base + scaled_number * 0.6),
        technique=min(96.0, base + 5.0),
    )


def get_climber_profiles(ability_grade: str = DEFAULT_FONT_GRADE) -> List[ClimberProfile]:
    defaults = _load_json(DEFAULTS_PATH, {})
    capabilities = _capabilities_for_grade(ability_grade)
    return [ClimberProfile(**item, capabilities=capabilities) for item in defaults.get("profiles", [])]


def get_hold_profiles() -> List[HoldPhysicsProfile]:
    overrides = _load_json(HOLD_OVERRIDES_PATH, None)
    source = overrides if isinstance(overrides, list) else _load_json(DEFAULTS_PATH, {}).get("hold_profiles", [])
    return [HoldPhysicsProfile(**item) for item in source]


def update_hold_profile(variant_id: str, profile: HoldPhysicsProfile) -> HoldPhysicsProfile:
    if profile.variant_id != variant_id:
        profile = profile.model_copy(update={"variant_id": variant_id})
    profiles = {item.variant_id: item for item in get_hold_profiles()}
    profiles[variant_id] = profile
    _write_json(HOLD_OVERRIDES_PATH, [item.model_dump(mode="json") for item in profiles.values()])
    return profile


def _route_holds(detail: StandardBoardRouteDetail) -> Dict[str, Hold]:
    return {hold.id: hold for hold in detail.board_setup}


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _hold_profile_for(hold: Hold, profiles: Dict[str, HoldPhysicsProfile]) -> Optional[HoldPhysicsProfile]:
    if hold.variant in profiles:
        return profiles[hold.variant]
    candidates = [item for item in profiles.values() if item.hold_type == hold.hold_type]
    return candidates[0] if candidates else None


def _perturbed_profile(profile: ClimberProfile, offset: float) -> ClimberProfile:
    scale = 1.0 + offset
    capability_updates = {
        key: max(0.0, min(100.0, value * scale))
        for key, value in profile.capabilities.model_dump().items()
        if key != "ability_grade"
    }
    capabilities = profile.capabilities.model_copy(update=capability_updates)
    body_fields = (
        "height_cm",
        "arm_span_cm",
        "weight_kg",
        "shoulder_width_cm",
        "hip_width_cm",
        "torso_length_cm",
        "upper_arm_cm",
        "forearm_cm",
        "hand_reach_cm",
        "thigh_cm",
        "shin_cm",
    )
    updates = {key: getattr(profile, key) * scale for key in body_fields}
    updates["capabilities"] = capabilities
    return profile.model_copy(update=updates)


def _path_robustness(
    detail: StandardBoardRouteDetail,
    profile: ClimberProfile,
    hold_profiles: Dict[str, HoldPhysicsProfile],
    path: BetaPath,
) -> float:
    rng = np.random.default_rng(20260717)
    offsets = rng.uniform(-0.05, 0.05, 20)
    successes = 0
    for offset in offsets:
        perturbed = _perturbed_profile(profile, float(offset))
        solver = RouteSimulationSolver(detail, perturbed, hold_profiles, search_budget=1)
        if solver.replay_guided_robustness(path):
            successes += 1
    return successes / len(offsets)


def _public_action(
    step: int,
    action,
    from_contacts: Dict[str, Optional[str]],
    to_contacts: Dict[str, Optional[str]],
) -> SimulationAction:
    changed_targets = _ordered_unique(
        target
        for key, target in to_contacts.items()
        if target and target != from_contacts.get(key)
    )
    dynamic = action.dynamic_evaluation
    return SimulationAction(
        step=step,
        action_type=action.action_type,
        moving_limbs=[Limb(key.upper()) for key in (action.moving_limbs or (action.limb,))],
        target_hold_ids=changed_targets or [action.target_id],
        from_contacts=from_contacts,
        to_contacts=to_contacts,
        purpose=action.purpose,
        technique=action.technique,
        support_limbs=[Limb(key.upper()) for key in action.support_limbs],
        drive_limbs=[Limb(key.upper()) for key in action.drive_limbs],
        preparation_required=action.preparation_required,
        dynamic=action.dynamic,
        duration_seconds=action.duration_seconds or (dynamic.duration_seconds if dynamic else 0.0),
        peak_velocity=dynamic.launch_velocity if dynamic else 0.0,
        catch_load_ratio=dynamic.catch_load_ratio if dynamic else 0.0,
    )


def _contact_anchor_map(
    contacts: Dict[str, Optional[str]],
    setup: Dict[str, Hold],
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> Dict[str, SimulationJointPoint]:
    anchors: Dict[str, SimulationJointPoint] = {}
    for limb, hold_id in contacts.items():
        if not hold_id:
            continue
        anchor = contact_point(
            hold_id,
            limb,
            setup,
            hold_profiles,
        )
        anchors[limb] = SimulationJointPoint(
            x=round(float(anchor[0]), 4),
            y=round(float(anchor[1]), 4),
            z=0.0,
        )
    return anchors


def _frames_and_actions(
    path: BetaPath,
    detail: StandardBoardRouteDetail,
    profile: ClimberProfile,
    hold_profiles: Dict[str, HoldPhysicsProfile],
) -> tuple[List[SimulationFrame], List[SimulationAction], List[BetaStep], Optional[int]]:
    """Build one visible stable pose per completed action.

    Continuous 30/60 Hz transition validation remains inside the solver and
    physics modules. Reports intentionally expose only the start pose and the
    stable landing pose after each action.
    """

    setup = _route_holds(detail)
    timestamp = 0.0
    frames: List[SimulationFrame] = []
    public_actions: List[SimulationAction] = []
    beta: List[BetaStep] = []
    crux_step: Optional[int] = None
    crux_stress = -1.0
    total_actions = max(1, len(path.actions))

    def append_frame(
        *,
        step: int,
        phase: str,
        contacts: Dict[str, Optional[str]],
        joints: Dict[str, SimulationJointPoint],
        center_of_mass: SimulationJointPoint,
        wall_pose,
        moving_limb: Optional[str] = None,
        hold_id: Optional[str] = None,
        technique: str = "",
        support_limbs: Iterable[str] = (),
        contact_loads: Optional[Dict[str, float]] = None,
        load_ratio: float = 0.0,
        fatigue: float = 0.0,
        stable: bool = True,
        dynamic: bool = False,
        note: str = "",
    ) -> None:
        anchors = _contact_anchor_map(contacts, setup, hold_profiles)
        frame_joints = dict(joints)
        endpoint_names = {
            "lh": "left_hand",
            "rh": "right_hand",
            "lf": "left_foot",
            "rf": "right_foot",
        }
        for limb, anchor in anchors.items():
            frame_joints[endpoint_names[limb]] = anchor
        if not body_dimensions_valid(frame_joints, profile):
            raise ValueError("body_proportion_invalid")
        frames.append(
            SimulationFrame(
                step=step,
                moving_limb=Limb(moving_limb.upper()) if moving_limb else None,
                hold_id=hold_id,
                contacts=dict(contacts),
                joints=frame_joints,
                center_of_mass=center_of_mass,
                phase=phase,
                timestamp_seconds=round(timestamp, 4),
                contact_anchors=anchors,
                support_limbs=[Limb(key.upper()) for key in support_limbs],
                shoulder_wall_distance=round(wall_pose.shoulder_wall_distance, 4),
                hip_wall_distance=round(wall_pose.hip_wall_distance, 4),
                technique=technique,
                contact_loads=contact_loads or {},
                dynamic=dynamic,
                load_ratio=round(load_ratio, 4),
                fatigue=round(fatigue, 3),
                stable=stable,
                note=note,
            )
        )

    start_contacts = state_dict(path.start_state)
    start_evaluation = path.evaluations[0]
    append_frame(
        step=0,
        phase="rest",
        contacts=start_contacts,
        joints=start_evaluation.pose.joints,
        center_of_mass=start_evaluation.pose.center_of_mass,
        wall_pose=start_evaluation.pose,
        support_limbs=(key for key, value in start_contacts.items() if value),
        contact_loads=start_evaluation.load.contact_loads,
        load_ratio=start_evaluation.load.peak_ratio,
        note="起步稳定姿态",
    )
    beta.extend(
        BetaStep(
            step=0,
            limb=Limb(key.upper()),
            hold_id=hold_id,
            intent="Start",
            **start_contacts,
        )
        for key, hold_id in start_contacts.items()
        if hold_id
    )

    for index, action in enumerate(path.actions):
        step = index + 1
        from_contacts = state_dict(path.states[index])
        to_contacts = state_dict(path.states[index + 1])
        landing = path.evaluations[index + 1]
        fatigue = path.fatigue * step / total_actions
        duration = max(0.8, action.duration_seconds)
        public_actions.append(_public_action(step, action, from_contacts, to_contacts))
        beta.append(
            BetaStep(
                step=step,
                limb=Limb(action.limb.upper()),
                hold_id=action.target_id,
                intent=action.purpose,
                is_top=(
                    action.target_id == to_contacts.get("lh") == to_contacts.get("rh")
                ),
                **to_contacts,
            )
        )

        timestamp += duration
        append_frame(
            step=step,
            phase="recovery" if action.dynamic and action.action_type == "cut_loose" else "settle",
            contacts=to_contacts,
            joints=landing.pose.joints,
            center_of_mass=landing.pose.center_of_mass,
            wall_pose=landing.pose,
            moving_limb=action.limb,
            hold_id=action.target_id,
            technique=action.technique,
            support_limbs=(key for key, value in to_contacts.items() if value),
            contact_loads=landing.load.contact_loads,
            load_ratio=landing.load.peak_ratio,
            fatigue=fatigue,
            stable=True,
            dynamic=action.dynamic,
            note=action.purpose,
        )
        action_stress = landing.stress
        if action.dynamic and action.dynamic_evaluation:
            action_stress = max(action_stress, action.dynamic_evaluation.catch_load_ratio)

        if action_stress > crux_stress:
            crux_stress = action_stress
            crux_step = step
    return frames, public_actions, beta, crux_step


def _simulate_profile(
    detail: StandardBoardRouteDetail,
    profile: ClimberProfile,
    hold_profiles: Dict[str, HoldPhysicsProfile],
    motion_mode: str,
    seed_paths: Optional[List[BetaPath]] = None,
) -> tuple[ClimberRun, List[BetaPath]]:
    solver = RouteSimulationSolver(detail, profile, hold_profiles)
    replayed_paths = []
    for seed in seed_paths or []:
        replayed = solver.replay(seed.start_state, seed.actions)
        if replayed:
            replayed_paths.append(replayed)
    if replayed_paths:
        replayed_paths.sort(key=lambda path: (len(path.actions), path.peak_stress, path.fatigue))
        outcome = SolveOutcome(
            solution_mode="static",
            paths=replayed_paths[:3],
            search_complete=True,
            expanded_states=0,
            rejection_counts=Counter(),
        )
    else:
        outcome = solver.solve(motion_mode)

    if not outcome.paths:
        start_states = solver._start_states()
        frames: List[SimulationFrame] = []
        if start_states:
            start = start_states[0]
            evaluation = solver.evaluate(start)
            frames.append(
                SimulationFrame(
                    step=0,
                    contacts=state_dict(start),
                    joints=evaluation.pose.joints,
                    center_of_mass=evaluation.pose.center_of_mass,
                    contact_loads=evaluation.load.contact_loads,
                    load_ratio=evaluation.load.peak_ratio,
                    note="搜索从该合法起攀姿态开始",
                )
            )
        dominant = outcome.rejection_counts.most_common(1)
        rejection = dominant[0][0] if dominant else "no_path"
        if not outcome.search_complete:
            failure_code = "search_incomplete"
            failure_reason = "搜索预算已用尽，当前不能据此判定线路不可攀"
            status = "review"
        elif rejection == "invalid_start":
            failure_code = "invalid_start"
            failure_reason = "起点无法形成符合人体关节和受力约束的姿态"
            status = "failed"
        else:
            failure_code = "no_valid_beta"
            failure_reason = f"完整搜索未找到合法 Beta，主要被拒绝约束：{rejection}"
            status = "failed"
        confidence = 0.72 if status == "failed" else 0.58
        return (
            ClimberRun(
                profile_id=profile.id,
                profile_label=profile.label,
                status=status,
                solution_mode="none",
                search_complete=outcome.search_complete,
                expanded_states=outcome.expanded_states,
                confidence=confidence,
                failure_step=1,
                failure_hold_id=detail.roles.get("end", [None])[0],
                failure_code=failure_code,
                failure_reason=failure_reason,
                dynamic_suspected=False,
                frames=frames,
            ),
            [],
        )

    path = outcome.paths[0]
    robustness = _path_robustness(detail, profile, hold_profiles, path)
    frames, public_actions, beta, crux_step = _frames_and_actions(
        path,
        detail,
        profile,
        hold_profiles,
    )
    used_hold_ids = {
        hold_id
        for state in path.states
        for hold_id in state
        if hold_id
    }
    setup = _route_holds(detail)
    hold_confidences = []
    for hold_id in used_hold_ids:
        hold = setup.get(hold_id)
        physics = _hold_profile_for(hold, hold_profiles) if hold else None
        hold_confidences.append(physics.confidence if physics else 0.35)
    hold_confidence = sum(hold_confidences) / max(1, len(hold_confidences))
    demand = {
        key: max((evaluation.demand.get(key, 0.0) for evaluation in path.evaluations), default=0.0)
        for key in ("reach", "finger_strength", "core_tension", "mobility")
    }
    demand["endurance"] = min(150.0, path.fatigue * 100.0)
    if outcome.solution_mode == "single_dynamic":
        demand["explosiveness"] = max(
            (
                action.dynamic_evaluation.launch_velocity / 3.0 * 100.0
                for action in path.actions
                if action.dynamic_evaluation
            ),
            default=0.0,
        )
        status = "review"
        confidence = min(
            0.74,
            robustness * 0.42
            + hold_confidence * 0.2
            + outcome.dynamic_feasibility_score / 100.0 * 0.22
            + 0.1,
        )
        failure_code = "dynamic_required"
        failure_reason = "静态搜索无解，找到单次动态可行 Beta，仍需真人复核"
        dynamic_suspected = True
    elif robustness >= 0.75:
        status = "passed"
        confidence = min(0.98, robustness * 0.58 + hold_confidence * 0.25 + 0.17)
        failure_code = None
        failure_reason = None
        dynamic_suspected = False
    else:
        status = "review"
        confidence = min(0.74, robustness * 0.55 + hold_confidence * 0.25 + 0.14)
        failure_code = "low_robustness"
        failure_reason = "找到静态 Beta，但身体与能力扰动重放的稳定性不足"
        dynamic_suspected = False
    return (
        ClimberRun(
            profile_id=profile.id,
            profile_label=profile.label,
            status=status,
            solution_mode=outcome.solution_mode,
            search_complete=outcome.search_complete,
            expanded_states=outcome.expanded_states,
            alternatives_found=len(outcome.paths),
            movement_count=len(path.actions),
            dynamic_action_count=path.dynamic_action_count,
            dynamic_feasibility_score=outcome.dynamic_feasibility_score,
            robustness=round(robustness, 2),
            confidence=round(confidence, 2),
            fatigue=round(path.fatigue, 3),
            crux_step=crux_step,
            failure_step=crux_step if failure_reason else None,
            failure_hold_id=public_actions[crux_step - 1].target_hold_ids[0] if failure_reason and crux_step else None,
            failure_code=failure_code,
            failure_reason=failure_reason,
            dynamic_suspected=dynamic_suspected,
            demand={key: round(min(150.0, value), 1) for key, value in demand.items()},
            actions=public_actions,
            beta_sequence=beta,
            frames=frames,
        ),
        outcome.paths,
    )


def _input_hash(
    detail: StandardBoardRouteDetail,
    profiles: List[ClimberProfile],
    hold_profiles: List[HoldPhysicsProfile],
    request: SimulationRequest,
) -> str:
    payload = {
        "engine": ENGINE_VERSION,
        "rules": SOLVER_RULES_VERSION,
        "action_library": ACTION_LIBRARY_VERSION,
        "pose_config": POSE_CONFIG_VERSION,
        "anchor_model": ANCHOR_MODEL_VERSION,
        "depth_model": DEPTH_MODEL_VERSION,
        "motion_mode": request.motion_mode,
        "source": detail.source_id,
        "roles": detail.roles,
        "profiles": [profile.model_dump(mode="json") for profile in profiles],
        "holds": [
            {
                key: value
                for key, value in profile.model_dump(mode="json").items()
                if key not in {
                    "hand_contact_anchor",
                    "foot_contact_anchor",
                    "recovery_contact_anchor",
                }
            }
            for profile in hold_profiles
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _grade_from_runs(detail: StandardBoardRouteDetail, runs: List[ClimberRun]) -> tuple[str, int]:
    source_grade = detail.predicted_grade or detail.grade
    source_number = _grade_number(source_grade)
    peak_demand = max((max(run.demand.values(), default=0.0) for run in runs), default=50.0)
    adjustment = 1 if peak_demand >= 112 else (-1 if peak_demand < 72 else 0)
    predicted = grade_from_number(source_number + adjustment)
    return predicted, _grade_number(predicted) - _grade_number(detail.grade)


def _report_for_detail(detail: StandardBoardRouteDetail, request: SimulationRequest, report_id: Optional[str] = None) -> SimulationReport:
    ability_grade = request.ability_grade or detail.grade
    all_profiles = get_climber_profiles(ability_grade)
    selected = set(request.profile_ids)
    profiles = [profile for profile in all_profiles if not selected or profile.id in selected]
    hold_profiles = get_hold_profiles()
    physics_by_id = {profile.variant_id: profile for profile in hold_profiles}
    input_hash = _input_hash(detail, profiles, hold_profiles, request)
    hard_failures = list(detail.validation.get("failures", []))
    runs_by_id: Dict[str, ClimberRun] = {}
    reference_paths: List[BetaPath] = []
    ordered_profiles = sorted(profiles, key=lambda profile: profile.id != "reference")
    for profile in ordered_profiles:
        run, paths = _simulate_profile(
            detail,
            profile,
            physics_by_id,
            request.motion_mode or "static_then_single_dynamic",
            seed_paths=reference_paths if profile.id != "reference" else None,
        )
        runs_by_id[profile.id] = run
        if profile.id == "reference" and run.solution_mode == "static":
            reference_paths = paths
    runs = [runs_by_id[profile.id] for profile in profiles]
    if hard_failures:
        for run in runs:
            run.status = "failed"
            run.solution_mode = "none"
            run.confidence = 1.0
            run.failure_code = hard_failures[0]
            run.failure_reason = detail.review_reasons[0] if detail.review_reasons else hard_failures[0]
    pass_count = sum(run.status == "passed" for run in runs)
    dynamic_suspected = any(run.solution_mode == "single_dynamic" for run in runs)
    confidence = round(sum(run.confidence for run in runs) / max(1, len(runs)), 2)
    calibration_complete = all(profile.confidence >= 0.8 and "待人工" not in profile.notes for profile in hold_profiles)
    all_search_complete = all(run.search_complete for run in runs)
    if hard_failures or (
        pass_count == 0
        and not dynamic_suspected
        and all_search_complete
        and calibration_complete
        and confidence >= 0.75
    ):
        verdict = "fail"
        label = "不通过"
    elif dynamic_suspected or not all_search_complete or pass_count <= 1 or confidence < 0.75:
        verdict = "review"
        label = "转真人复核"
    elif pass_count == len(runs):
        verdict = "pass"
        label = "通过"
    else:
        verdict = "pass_body_bias"
        label = "通过但存在体型偏置"

    predicted_grade, grade_delta = _grade_from_runs(detail, runs)
    failed_labels = [run.profile_label for run in runs if run.status != "passed"]
    reasons = list(dict.fromkeys([run.failure_reason for run in runs if run.failure_reason]))
    tags = list(detail.tags)
    tags.append({"pass": "simulation:static-pass", "pass_body_bias": "simulation:body-bias", "review": "simulation:needs-review", "fail": "simulation:failed"}[verdict])
    if dynamic_suspected:
        tags.append("demand:single-dynamic")
    if any(run.profile_id == "compact" and run.status != "passed" for run in runs):
        tags.append("fit:short-reach-sensitive")
    if any(run.profile_id == "tall-reach" and run.failure_code == "static_balance" for run in runs):
        tags.append("fit:tall-compression")
    max_demands = {key: max((run.demand.get(key, 0.0) for run in runs), default=0.0) for key in ("reach", "finger_strength", "core_tension", "mobility", "endurance", "explosiveness")}
    for key, tag in {"reach": "demand:reach", "finger_strength": "demand:finger-strength", "core_tension": "demand:core", "mobility": "demand:mobility", "endurance": "demand:endurance", "explosiveness": "demand:explosiveness"}.items():
        if max_demands[key] >= 90:
            tags.append(tag)
    if verdict == "pass":
        summary = "三个审计体型均找到经过扰动重放的稳定静态 Beta。"
    elif verdict == "pass_body_bias":
        summary = f"多数体型可静态完成，但 {', '.join(failed_labels)} 需要额外复核。"
    elif dynamic_suspected:
        summary = "至少一个体型需要单次动态动作，系统已给出可行证据并转真人复核。"
    elif not all_search_complete:
        summary = "至少一个体型的搜索预算已用尽，当前结果不能用于判定不可攀。"
    elif verdict == "review":
        summary = "当前证据不足以自动放行，请结合失败动作和人体画像进行真人复核。"
    else:
        summary = "所有审计体型均未找到满足接触、人体工学和受力约束的 Beta。"
    feasibility = round(sum(run.robustness for run in runs) / max(1, len(runs)) * 100.0, 1)
    return SimulationReport(
        report_id=report_id or str(uuid.uuid4()),
        source_id=detail.source_id,
        created_at=_now(),
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        verdict=verdict,
        verdict_label=label,
        summary=summary,
        ability_grade=ability_grade,
        motion_mode=request.motion_mode or "static_then_single_dynamic",
        pass_count=pass_count,
        profile_count=len(runs),
        feasibility_score=feasibility,
        confidence=confidence,
        predicted_grade=predicted_grade,
        grade_delta=grade_delta,
        tags=list(dict.fromkeys(tags)),
        reasons=reasons,
        dynamic_suspected=dynamic_suspected,
        calibration_complete=calibration_complete,
        shadow_mode=True,
        route=detail,
        runs=runs,
    )


def _report_path(report_id: str) -> Path:
    return REPORTS_DIR / f"{report_id}.json"


def save_report(report: SimulationReport) -> None:
    _write_json(_report_path(report.report_id), report.model_dump(mode="json"))
    index = _load_json(LATEST_INDEX_PATH, {})
    index[report.source_id] = report.report_id
    _write_json(LATEST_INDEX_PATH, index)


def get_report(report_id: str) -> Optional[SimulationReport]:
    raw = _load_json(_report_path(report_id), None)
    return SimulationReport(**raw) if isinstance(raw, dict) else None


def get_latest_report(source_id: str) -> Optional[SimulationReport]:
    report_id = _load_json(LATEST_INDEX_PATH, {}).get(source_id)
    report = get_report(report_id) if report_id else None
    if report and report.engine_version == ENGINE_VERSION:
        return report
    return None


def simulate_route(source_id: str, request: SimulationRequest) -> SimulationReport:
    route = find_standard_route(source_id)
    if not route:
        raise ValueError("未找到该标准板线路")
    detail = detail_for(route)
    ability_grade = request.ability_grade or detail.grade
    selected = set(request.profile_ids)
    profiles = [
        profile
        for profile in get_climber_profiles(ability_grade)
        if not selected or profile.id in selected
    ]
    input_hash = _input_hash(detail, profiles, get_hold_profiles(), request)
    cached = get_latest_report(source_id)
    if cached and not request.force_refresh and cached.input_hash == input_hash:
        return cached
    preview = _report_for_detail(detail, request)
    save_report(preview)
    if request.generate_repairs and preview.verdict in {"review", "fail", "pass_body_bias"}:
        preview.repair_candidates = generate_repair_candidates(preview.report_id)
        save_report(preview)
    return preview


def simulate_batch(request: SimulationBatchRequest) -> SimulationBatchResult:
    source_ids = list(request.source_ids)
    if not source_ids:
        response = query_standard_routes(difficulty=request.difficulty, limit=request.limit, valid_only=False)
        source_ids = [route.source_id for route in response.routes]
    reports = []
    single = SimulationRequest(
        ability_grade=request.ability_grade,
        profile_ids=request.profile_ids,
        motion_mode=request.motion_mode,
        generate_repairs=False,
        force_refresh=request.force_refresh,
    )
    for source_id in source_ids[: request.limit]:
        try:
            reports.append(simulate_route(source_id, single))
        except ValueError:
            continue
    counts = Counter(report.verdict for report in reports)
    return SimulationBatchResult(total=len(source_ids[: request.limit]), completed=len(reports), reports=reports, counts=dict(counts))


def _neighbor_coords(coord_id: str, strategy: str) -> List[str]:
    x = ord(coord_id[0].upper()) - ord("A")
    y = int(coord_id[1:])
    offsets = [(0, -1), (-1, 0), (1, 0)] if strategy == "reach" else [(-1 if x > 5 else 1, 0), (0, -1), (0, 1)]
    return [f"{chr(ord('A') + nx)}{ny}" for dx, dy in offsets if 0 <= (nx := x + dx) < 11 and 1 <= (ny := y + dy) <= 18]


def _reuse_quality(rate: float) -> str:
    if rate >= 0.7:
        return "optimal"
    if rate >= 0.4:
        return "pass"
    return "below_pass"


def _append_modification_log(report: SimulationReport, candidate: SimulationRepairCandidate) -> None:
    log = _load_json(MODIFICATION_LOG_PATH, [])
    log.append(
        {
            "timestamp": _now(),
            "module": "backend/core/simulation.py",
            "report_id": report.report_id,
            "source_id": report.source_id,
            "changes": [f"{item['from']} -> {item['to']}" for item in candidate.changed_holds],
            "reason": [candidate.reason],
            "reuse_rate": candidate.reuse_rate,
            "reuse_quality": candidate.reuse_quality,
        }
    )
    _write_json(MODIFICATION_LOG_PATH, log)


def generate_repair_candidates(report_id: str) -> List[SimulationRepairCandidate]:
    report = get_report(report_id)
    if not report:
        raise ValueError("未找到仿真报告")
    route = find_standard_route(report.source_id)
    if not route:
        raise ValueError("未找到来源线路")
    failure_hold = next((run.failure_hold_id for run in report.runs if run.failure_hold_id in report.route.roles.get("mid", [])), None)
    mids = list(report.route.roles.get("mid", []))
    target = failure_hold or (mids[len(mids) // 2] if mids else None)
    if not target:
        return []
    occupied = set(report.route.roles.get("start", []) + mids + report.route.roles.get("end", []))
    candidates: List[SimulationRepairCandidate] = []
    for strategy, label, reason in (
        ("reach", "触达友好候选", "将卡点向前一动作靠近，降低静态触达压力"),
        ("balance", "平衡友好候选", "将卡点向身体中线靠近，降低横向扭转和抓点负荷"),
        ("grade", "难度对齐候选", "用最小坐标变化降低 crux 峰值，保持目标等级附近"),
    ):
        replacements = [coord for coord in _neighbor_coords(target, "reach" if strategy == "reach" else "balance") if coord not in occupied]
        for replacement in replacements:
            roles = {key: list(value) for key, value in report.route.roles.items()}
            roles["mid"] = [replacement if coord == target else coord for coord in roles["mid"]]
            validation = validate_standard_roles(roles)
            if not validation.get("valid_for_climb"):
                continue
            detail = detail_for(route, roles)
            candidate_report = _report_for_detail(detail, SimulationRequest(ability_grade=report.ability_grade))
            original_count = len(occupied)
            reuse_rate = round((original_count - 1) / max(1, original_count), 3)
            if reuse_rate < 0.4 or candidate_report.pass_count < 2 or abs(candidate_report.grade_delta or 0) > 1:
                continue
            board_asset = detail.board_asset.model_copy(
                update={
                    "saved_id": None,
                    "source_type": "ai-generated",
                    "route_name": f"{detail.display_name} · {label}",
                    "setter_commentary": reason,
                    "tags": list(dict.fromkeys([*detail.board_asset.tags, "simulation-repair", f"simulation:{strategy}"])),
                }
            )
            candidate = SimulationRepairCandidate(
                id=f"{report.report_id}-{strategy}",
                label=label,
                strategy=strategy,
                reason=reason,
                changed_holds=[{"from": target, "to": replacement}],
                reuse_rate=reuse_rate,
                reuse_quality=_reuse_quality(reuse_rate),
                predicted_grade=candidate_report.predicted_grade,
                majority_passed=True,
                board_asset=board_asset,
            )
            candidates.append(candidate)
            _append_modification_log(report, candidate)
            break
    report.repair_candidates = candidates
    save_report(report)
    return candidates


def record_feedback(report_id: str, feedback: SimulationFeedback) -> SimulationFeedbackRecord:
    report = get_report(report_id)
    if not report:
        raise ValueError("未找到仿真报告")
    record = SimulationFeedbackRecord(
        **feedback.model_dump(),
        id=str(uuid.uuid4()),
        report_id=report_id,
        source_id=report.source_id,
        created_at=_now(),
    )
    records = _load_json(FEEDBACK_PATH, [])
    records.append(record.model_dump(mode="json"))
    _write_json(FEEDBACK_PATH, records)
    return record
