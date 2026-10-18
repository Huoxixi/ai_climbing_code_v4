"""Conservative, camera-registered 2D pose observations on the source clock.

This is an independent evidence channel, not a contact detector or a local-image
verification. No interpolation, anatomical relabelling, force or grip inference
is performed. Every detail has to survive confidence and continuity checks.
"""
from copy import deepcopy
import math
import numpy as np
from .replay_observation_validity import registration_reason, joint_mask

VERSION = "registered-torso-chain-observations-v2"
LIMBS = {"left_hand": (5, 7, 9), "right_hand": (6, 8, 10),
         "left_foot": (11, 13, 15), "right_foot": (12, 14, 16)}
LIMB_NAMES = {"left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚"}
REASONS = {"wall_registration": "墙面配准缺失或不稳定", "occluded_chain": "肩肘腕或髋膝踝有低置信／遮挡点",
           "body_scale": "躯干尺度证据不足", "sampling_gap": "原片姿态采样有间隔，不能补画轨迹",
           "chain_length_change": "肢体链长度突变", "trajectory_jump": "轨迹突跳，不能当作真实动作",
           "side_identity_conflict": "左右整条肢体链疑似交换", "short_observation": "连续有效姿态不足三帧",
           "boundary_missing": "动作前后证据未覆盖", "short_noise": "位移短暂或接近姿态抖动幅度",
           "torso_transform": "躯干共同旋转／尺度变化无法可靠分离"}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def registered_points(sample, video):
    """Keep the source model's joint identities; homography only changes frame."""
    if not sample.get("observed") or sample.get("wall_alignment") not in {"aligned", "reference"}:
        return None
    diagnostics = sample.get("wall_alignment_diagnostics") or sample.get("motion_registration") or {}
    if registration_reason(sample.get('wall_reference_transform'), diagnostics):
        return None
    try:
        w, h = float(video["width"]), float(video["height"])
        xy, score = np.asarray(sample["kpts_xy"], float), np.asarray(sample["kpts_score"], float)
        matrix = np.asarray(sample["wall_reference_transform"], float)
        if w <= 0 or h <= 0 or xy.shape != (17, 2) or score.shape != (17,):
            return None
        homogeneous = np.c_[xy * [w, h], np.ones(17)] @ matrix.T
        if not np.isfinite(homogeneous).all() or np.any(abs(homogeneous[:, 2]) < 1e-6):
            return None
        points = homogeneous[:, :2] / homogeneous[:, 2:] / [w, h]
        valid = joint_mask(xy, points, score, sample.get('joint_eligibility'))
        return points, valid
    except (KeyError, ValueError, TypeError, OverflowError, np.linalg.LinAlgError):
        return None


def _angle(points, chain):
    a, b, c = points[list(chain)]
    u, v = a - b, c - b
    lengths = np.linalg.norm(u) * np.linalg.norm(v)
    return float(np.degrees(np.arccos(np.clip(np.dot(u, v) / lengths, -1., 1.)))) if lengths > 1e-8 else None


def prepare_tracks(result):
    """Reuse this immutable cache for all events; distances use isotropic pixels."""
    video = result.get("video") or {}
    aspect = np.asarray([video.get("width", 1), video.get("height", 1)], float)
    aspect /= max(1., float(min(aspect)))
    rows = []
    for index, sample in enumerate(sorted((s for s in result.get("pose_samples", []) if isinstance(s, dict) and finite(s.get("time_seconds"))), key=lambda s: s["time_seconds"])):
        mapped = registered_points(sample, video)
        row = {"time": float(sample["time_seconds"]), "frame_id": f"frame-{sample.get('source_frame_id', sample.get('sample_index', index))}",
               "points": None, "valid": np.zeros(17, bool), "scale": None, "body": None, "reasons": []}
        if mapped is None:
            row["reasons"] = ["wall_registration"]
        else:
            row["points"], row["valid"] = mapped[0] * aspect, mapped[1]
            valid, points = row["valid"], row["points"]
            torso_lengths = [float(np.linalg.norm(points[a] - points[b])) for a, b in ((5, 11), (6, 12)) if valid[a] and valid[b]]
            if torso_lengths and .02 <= np.median(torso_lengths) <= 1.2:
                row["scale"] = float(np.median(torso_lengths))
            else:
                row["reasons"].append("body_scale")
            body = [i for i in (5, 6, 11, 12) if valid[i]]
            if len(body) >= 3:
                row["body"] = np.mean(points[body], axis=0)
        rows.append(row)
    return rows


def chain_pair_reasons(a, b, limb):
    chain = LIMBS[limb]
    if a["points"] is None or b["points"] is None:
        return ["wall_registration"]
    if not all(a["valid"][i] and b["valid"][i] for i in chain):
        return ["occluded_chain"]
    scale = np.median([s for s in (a["scale"], b["scale"]) if s is not None]) if a["scale"] or b["scale"] else None
    dt = b["time"] - a["time"]
    if dt <= 0 or dt > .6:
        return ["sampling_gap"]
    if scale is None:
        return ["body_scale"]
    reasons = []
    # A whole-chain identity exchange differs from a natural wrist crossing.
    opposite = LIMBS[("right_" if limb.startswith("left_") else "left_") + limb.split("_")[-1]]
    if all(a["valid"][i] and b["valid"][i] for i in opposite):
        same = np.linalg.norm(b["points"][list(chain)] - a["points"][list(chain)], axis=1)
        crossed = np.linalg.norm(b["points"][list(chain)] - a["points"][list(opposite)], axis=1)
        other_same = np.linalg.norm(b["points"][list(opposite)] - a["points"][list(opposite)], axis=1)
        other_crossed = np.linalg.norm(b["points"][list(opposite)] - a["points"][list(chain)], axis=1)
        if (np.median(same) > .25 * scale and np.all(crossed < same * .45)
                and np.all(other_crossed < other_same * .45)):
            reasons.append("side_identity_conflict")
    lengths_a = np.linalg.norm(np.diff(a["points"][list(chain)], axis=0), axis=1)
    lengths_b = np.linalg.norm(np.diff(b["points"][list(chain)], axis=0), axis=1)
    ratios = np.maximum(lengths_a, lengths_b) / np.maximum(1e-6, np.minimum(lengths_a, lengths_b))
    if np.any((ratios > 1.8) & (abs(lengths_a - lengths_b) > scale * .18)):
        reasons.append("chain_length_change")
    # Body translation is removed before testing the chain's active velocity.
    root_delta = b["points"][chain[0]] - a["points"][chain[0]]
    relative = b["points"][list(chain)] - a["points"][list(chain)] - root_delta
    if max(np.linalg.norm(relative, axis=1)) / dt / scale > 4.5:
        reasons.append("trajectory_jump")
    return reasons


def _direction(delta, scale):
    dx, dy = delta / scale
    if abs(dx) > max(.12, abs(dy) * 1.3):
        return "left" if dx < 0 else "right"
    if abs(dy) > max(.12, abs(dx) * 1.3):
        return "up" if dy < 0 else "down"
    if np.linalg.norm([dx, dy]) >= .18:
        return ("up_" if dy < 0 else "down_") + ("left" if dx < 0 else "right")
    return None


def _direction_word(direction):
    return {"up": "向上", "down": "向下", "left": "向左", "right": "向右", "up_left": "向左上方", "up_right": "向右上方", "down_left": "向左下方", "down_right": "向右下方"}.get(direction, "")


def _torso_similarity(reference, current):
    """Fit only confident matched shoulder/hip identities, never the moving limb.

    A common planar similarity is an explanation to remove, not evidence of an
    anatomical technique. Reflections, degenerate triangles and poor fits are
    unknown rather than silently treated as an identity transform.
    """
    ids = [i for i in (5, 6, 11, 12) if reference['valid'][i] and current['valid'][i]]
    if len(ids) < 3:
        return None
    x, y = reference['points'][ids], current['points'][ids]
    x, y = x - x.mean(axis=0), y - y.mean(axis=0)
    scatter = x.T @ x
    if np.linalg.eigvalsh(scatter)[0] < reference['scale'] ** 2 * .005:
        return None
    try:
        u, singular, vt = np.linalg.svd(x.T @ y)
        rotation = u @ vt
        if np.linalg.det(rotation) <= 0:
            return None
        scale = float(sum(singular) / max(1e-9, float(np.sum(x * x))))
        residual = float(np.sqrt(np.mean(np.sum((y - scale * x @ rotation) ** 2, axis=1))) / reference['scale'])
        if not .2 < scale < 3 or residual > .12:
            return None
        angle = float(np.degrees(np.arctan2(rotation[0, 1], rotation[0, 0])))
        return {'rotation': rotation, 'scale': scale, 'angle': angle, 'residual': residual}
    except np.linalg.LinAlgError:
        return None


def _torso_axis_angle(reference, current):
    """Fallback alarm only: an unreliable torso fit may not establish movement."""
    if not all(reference['valid'][i] and current['valid'][i] for i in (5, 6, 11, 12)):
        return None
    def axis(row):
        return np.mean(row['points'][[5, 6]], axis=0) - np.mean(row['points'][[11, 12]], axis=0)
    a, b = axis(reference), axis(current)
    if min(np.linalg.norm(a), np.linalg.norm(b)) < .02:
        return None
    return float(np.degrees(np.arctan2(a[0] * b[1] - a[1] * b[0], np.dot(a, b))))


def active_relative_delta(a, b, limb):
    """Pairwise candidate locator uses the same common-body compensation."""
    if limb not in LIMBS or a['points'] is None or b['points'] is None:
        return None
    root, _, tip = LIMBS[limb]
    before, after = a['points'][tip] - a['points'][root], b['points'][tip] - b['points'][root]
    fit = _torso_similarity(a, b) if a['scale'] and b['scale'] else None
    if fit is not None:
        return after @ fit['rotation'].T / fit['scale'] - before
    # Without a nondegenerate fit, even a small rotation plus scale change can
    # mimic a step. A locator may retain body motion, but not a limb assertion.
    return None


def analyze_event(result, limb, start, end, tracks=None):
    """Observe active limb motion relative to its shoulder/hip, with wall checks."""
    detail = {"version": VERSION, "basis": "registered_pose_trajectory", "status": "insufficient", "summary": "骨架轨迹证据不足",
              "coverage": 0., "evidence": [], "phases": [], "measurements": {}, "reasons": [],
              "limitations": ["只观察二维骨架；接触、抓握、踩实和受力不能由这些点确认"]}
    if limb not in LIMBS or not finite(start) or not finite(end) or end <= start:
        detail["reasons"] = ["short_observation"]
        return detail
    # The boundary tolerance never creates interpolated poses or moves the event.
    rows = [r for r in (tracks if tracks is not None else prepare_tracks(result)) if start - .12 <= r["time"] <= end + .12]
    chain = LIMBS[limb]
    valid = lambda r: r["points"] is not None and r["scale"] is not None and all(r["valid"][i] for i in chain)
    reasons = []
    for row in rows:
        reasons.extend(row["reasons"])
        if row["points"] is not None and not all(row["valid"][i] for i in chain):
            reasons.append("occluded_chain")
    runs, run, valid_seconds = [], [], 0.
    for i, row in enumerate(rows):
        if not valid(row):
            if run: runs.append(run)
            run = []
            continue
        if run:
            pair_reasons = chain_pair_reasons(run[-1], row, limb)
            if pair_reasons:
                reasons.extend(pair_reasons)
                runs.append(run); run = []
            else:
                valid_seconds += max(0., min(end, row["time"]) - max(start, run[-1]["time"]))
        run.append(row)
    if run: runs.append(run)
    detail["coverage"] = round(min(1., valid_seconds / (end - start)), 4)
    detail["reasons"] = sorted(set(reasons))
    detail["reason_labels"] = [REASONS[r] for r in detail["reasons"]]
    conflict = any(r in reasons for r in ("side_identity_conflict", "trajectory_jump", "chain_length_change"))
    if conflict:
        detail.update(status="conflict", summary="骨架轨迹有连续性冲突，动作细节待复核")
        return detail
    best = max(runs, key=lambda r: r[-1]["time"] - r[0]["time"], default=[])
    if len(best) < 3 or detail["coverage"] < .65:
        detail["reasons"] = sorted(set([*detail["reasons"], "short_observation"]))
        detail["reason_labels"] = [REASONS[r] for r in detail["reasons"]]
        return detail
    if best[0]["time"] > start + .3 or best[-1]["time"] < end - .3:
        detail["reasons"] = sorted(set([*detail["reasons"], "boundary_missing"]))
        detail["reason_labels"] = [REASONS[r] for r in detail["reasons"]]
        return detail
    scale = float(np.median([r["scale"] for r in best]))
    points = np.asarray([r["points"][chain[-1]] for r in best])
    roots = np.asarray([r["points"][chain[0]] for r in best])
    root_relative, times = points - roots, np.asarray([r["time"] for r in best])
    fits = [_torso_similarity(best[0], row) for row in best]
    fitted = sum(fit is not None for fit in fits)
    axis_angles = [_torso_axis_angle(best[0], row) for row in best]
    suspected_rotation = (max((abs(a) for a in axis_angles if a is not None), default=0.) > 8
                          or max((abs(fit['angle']) for fit in fits if fit is not None), default=0.) > 8)
    scale_change = max(abs(row['scale'] / best[0]['scale'] - 1) for row in best) > .12
    shape_change = False
    for row in best:
        common_scale = row['scale'] / best[0]['scale']
        changes = [abs(np.linalg.norm(row['points'][a] - row['points'][b]) / common_scale - np.linalg.norm(best[0]['points'][a] - best[0]['points'][b])) / best[0]['scale']
                   for a, b in ((5, 6), (11, 12), (5, 11), (6, 12), (5, 12), (6, 11)) if row['valid'][a] and row['valid'][b] and best[0]['valid'][a] and best[0]['valid'][b]]
        shape_change |= max(changes, default=0) > .12
    if fitted != len(best) and (suspected_rotation or scale_change or shape_change):
        detail.update(status='insufficient', summary='躯干旋转或尺度变化与肢体动作无法可靠分离')
        detail['reasons'] = sorted(set([*detail['reasons'], 'torso_transform']))
        detail['reason_labels'] = [REASONS[r] for r in detail['reasons']]
        return detail
    # A legacy translation-relative vector is retained only to identify a
    # stationary or jointly carried endpoint. It cannot authorize an active
    # observation when the torso fit is missing or degenerate.
    relative = np.asarray([vector @ fit['rotation'].T / fit['scale'] if fit is not None else vector
                           for vector, fit in zip(root_relative, fits)])
    torso_rotation = max((abs(fit['angle']) for fit in fits if fit is not None), default=0.)
    torso_scale_ratio = fits[-1]['scale'] if fits[-1] is not None else None
    wall_net, relative_net = points[-1] - points[0], relative[-1] - relative[0]
    wall_extent = max(np.linalg.norm(p - points[0]) for p in points) / scale
    relative_extent = max(np.linalg.norm(p - relative[0]) for p in relative) / scale
    speeds = np.linalg.norm(np.diff(relative, axis=0), axis=1) / np.diff(times) / scale
    wall_speeds = np.linalg.norm(np.diff(points, axis=0), axis=1) / np.diff(times) / scale
    angles = np.asarray([_angle(r["points"], chain) for r in best], float)
    angle_change = float(angles[-1] - angles[0])
    detail["evidence"] = [{"frame_id": r["frame_id"], "time_seconds": r["time"]} for r in best]
    detail["measurements"] = {"wall_displacement_body_units": round(float(np.linalg.norm(wall_net) / scale), 3),
                              "relative_displacement_body_units": round(float(np.linalg.norm(relative_net) / scale), 3),
                              "relative_extent_body_units": round(float(relative_extent), 3), "joint_angle_change_deg": round(angle_change, 1),
                              "relative_speed_p95_body_units_per_second": round(float(np.quantile(speeds, .95)), 3),
                              "root_relative_displacement_body_units": round(float(np.linalg.norm(root_relative[-1] - root_relative[0]) / scale), 3),
                              "torso_rotation_degrees": round(torso_rotation, 1), "torso_scale_ratio": round(torso_scale_ratio, 3) if torso_scale_ratio is not None else None,
                              "torso_transform_coverage": round(fitted / len(best), 4),
                              "body_scale_basis": "registered_shoulder_hip_length", "coordinate_basis": "wall_registered_initial_torso_frame"}
    detail["trace"] = [{"time_seconds": r["time"], "relative_x": round(float(p[0] / scale), 4), "relative_y": round(float(p[1] / scale), 4), "joint_angle_degrees": round(float(angle), 1)} for r, p, angle in zip(best, relative, angles)]
    anchor = "肩部" if limb.endswith("hand") else "髋部"
    if wall_extent < .10 and max(wall_speeds, default=0) < .20:
        detail.update(status="stationary", summary="肢体末端在墙面参考系中基本未移位；身体位置变化不能写作伸手或抬脚")
        return detail
    if relative_extent < .12:
        reason = '旋转／尺度变化' if torso_rotation > 8 or torso_scale_ratio is not None and abs(torso_scale_ratio - 1) > .12 else '位移'
        detail.update(status="body_carried", summary=f"肢体随躯干共同{reason}，相对躯干没有清楚的主动移位")
        return detail
    # Reject an out-and-back single-frame spike and small alternating jitter.
    active = np.flatnonzero(speeds > .10)
    if len(active) < 2 or np.linalg.norm(relative_net) / scale < .12 or (times[active[-1] + 1] - times[active[0]]) < .25:
        detail.update(status="insufficient", summary="短时位移接近姿态抖动，不能确定为独立动作")
        detail["reasons"] = sorted(set([*detail["reasons"], "short_noise"]))
        detail["reason_labels"] = [REASONS[r] for r in detail["reasons"]]
        return detail
    if fitted != len(best):
        detail.update(status='insufficient', summary='躯干参考不完整或退化，不能排除共同旋转／尺度变化造成的位移')
        detail['reasons'] = sorted(set([*detail['reasons'], 'torso_transform']))
        detail['reason_labels'] = [REASONS[r] for r in detail['reasons']]
        return detail
    detail["status"] = "observed"
    direction = _direction(relative_net, scale)
    detail["direction"] = direction
    detail["wall_direction"] = _direction(wall_net, scale)
    detail["body_direction"] = _direction(roots[-1] - roots[0], scale)
    motion = _direction_word(direction) + ("移手" if limb.endswith("hand") else "移脚")
    if direction and direction.startswith("up"):
        motion = _direction_word(direction) + ("抬手" if limb.endswith("hand") else "抬脚")
    if abs(angle_change) >= 18:
        joint = "手臂" if limb.endswith("hand") else "膝部"
        motion += "，" + ("手臂伸展" if limb.endswith("hand") and angle_change > 0 else "手臂屈曲" if limb.endswith("hand") else "膝部伸展" if angle_change > 0 else "屈膝")
    detail["summary"] = f"相对{anchor}{motion}（二维骨架观察）"
    if torso_rotation > 8:
        detail['limitations'].append('已扣除躯干共同二维旋转；相对方向以片段起始躯干方向为参照')
        detail['summary'] = f"扣除躯干共同旋转后，相对{anchor}{motion}（二维骨架观察）"
    if detail["wall_direction"] and detail["wall_direction"] != direction:
        detail["summary"] = f"墙面参考中{_direction_word(detail['wall_direction'])}移位；相对{anchor}{motion}（二维骨架观察）"
    begin, stop = int(active[0]), int(active[-1] + 1)
    # Explicit phases need their own measurements, rather than a canned script.
    phases = []
    if times[begin] - times[0] >= .25:
        phases.append({"start_seconds": max(start, float(times[0])), "end_seconds": float(times[begin]), "code": "preparation", "text": "末端位置暂未明显变化"})
    mid = (begin + stop) // 2
    first_direction = _direction(relative[mid] - relative[begin], scale)
    second_direction = _direction(relative[stop] - relative[mid], scale)
    second_angle = angles[stop] - angles[mid]
    if mid - begin >= 2 and stop - mid >= 2 and first_direction and (second_direction and first_direction != second_direction or second_angle >= 18):
        first = _direction_word(first_direction) + ("抬手" if limb.endswith("hand") and first_direction.startswith("up") else "抬脚" if first_direction.startswith("up") else "移手" if limb.endswith("hand") else "移脚")
        second = "伸展手臂" if limb.endswith("hand") and second_angle >= 18 else "伸展膝部" if second_angle >= 18 else _direction_word(second_direction) + ("移手" if limb.endswith("hand") else "移脚")
        phases.extend([{"start_seconds": max(start, float(times[begin])), "end_seconds": float(times[mid]), "code": "transport_first", "text": first},
                       {"start_seconds": float(times[mid]), "end_seconds": min(end, float(times[stop])), "code": "transport_second", "text": second}])
        detail["summary"] = f"先{first}，再{second}（相对{anchor}的二维骨架观察）"
        if detail["wall_direction"] and detail["wall_direction"] != direction:
            detail["summary"] = f"墙面参考中{_direction_word(detail['wall_direction'])}移位；" + detail["summary"]
    else:
        phases.append({"start_seconds": max(start, float(times[begin])), "end_seconds": min(end, float(times[stop])), "code": "transport", "text": motion})
    if times[-1] - times[stop] >= .35 and len(speeds[stop:]) >= 2 and max(speeds[stop:]) < .10:
        phases.append({"start_seconds": float(times[stop]), "end_seconds": min(end, float(times[-1])), "code": "settling", "text": "末端位置趋于稳定，接触仍未确认"})
    detail["phases"] = [p for p in phases if p["end_seconds"] > p["start_seconds"]]
    return detail


def enrich_trajectories(organized):
    """Derived layer only. Repeated reads never append duplicate observations."""
    output = deepcopy(organized)
    tracks = prepare_tracks(output)
    duration = output.get("source_duration_seconds") or (output.get("video") or {}).get("duration_seconds")
    if not finite(duration) or duration <= 0:
        return output
    gaps = []
    cursor = 0.
    for a, b in zip(tracks, tracks[1:]):
        if a["time"] > cursor + .01:
            gaps.append({"start_seconds": cursor, "end_seconds": min(duration, a["time"]), "reason": "sampling_gap"})
        if a["points"] is None or b["points"] is None or a["body"] is None or b["body"] is None or not a["scale"] or not b["scale"] or b["time"] - a["time"] > .6:
            reason = "wall_registration" if a["points"] is None or b["points"] is None else "body_scale" if a["body"] is None or b["body"] is None or not a["scale"] or not b["scale"] else "sampling_gap"
            gaps.append({"start_seconds": a["time"], "end_seconds": min(duration, b["time"]), "reason": reason})
        cursor = b["time"]
    if cursor < duration:
        gaps.append({"start_seconds": cursor, "end_seconds": duration, "reason": "sampling_gap"})
    body_motion = []
    for a, b in zip(tracks, tracks[1:]):
        if a["body"] is not None and b["body"] is not None and a["scale"] and b["scale"] and 0 < b["time"] - a["time"] <= .6:
            speed = float(np.linalg.norm(b["body"] - a["body"]) / (b["time"] - a["time"]) / np.median([a["scale"], b["scale"]]))
            body_motion.append({"start_seconds": a["time"], "end_seconds": b["time"], "body_speed_units_per_second": round(speed, 3)})
    limb_summary = {limb: {"observed_events": 0, "insufficient_events": 0, "conflicting_events": 0, "body_carried_events": 0} for limb in LIMBS}
    for limb in LIMBS:
        seconds = sum(max(0., min(duration, b["time"]) - max(0., a["time"])) for a, b in zip(tracks, tracks[1:]) if not chain_pair_reasons(a, b, limb))
        limb_summary[limb].update(valid_trajectory_seconds=round(seconds, 3), coverage=round(min(1., seconds / duration), 4))
    for group in output.get("groups", []):
        # Only our previous derived events are regenerated; saved visual/human
        # decisions and the original source pose tracks stay untouched.
        group["events"] = [e for e in group.get("events", []) if e.get("motion_origin") != "pose_trajectory"]
        observations = []
        for limb in LIMBS:
            detail = analyze_event(output, limb, group["start_seconds"], group["end_seconds"], tracks)
            observations.append({"limb": limb, "limb_name": LIMB_NAMES[limb], **detail})
            key = {"observed": "observed_events", "conflict": "conflicting_events", "body_carried": "body_carried_events"}.get(detail["status"], "insufficient_events")
            limb_summary[limb][key] += 1
            if detail["status"] == "observed" and not any(e.get("limb") == limb for e in group["events"]):
                phases = [p for p in detail["phases"] if p["code"].startswith("transport")]
                if phases:
                    group["events"].append({"id": f"{group['id']}-trajectory-{limb}", "limb": limb, "action": "move", "start_seconds": phases[0]["start_seconds"],
                                            "end_seconds": phases[-1]["end_seconds"], "evidence_status": "trajectory_observed", "event_status": "trajectory_observed",
                                            "motion_origin": "pose_trajectory", "evidence": detail["evidence"], "facts": [], "technique_tags": [], "trajectory_details": detail})
        group["trajectory_observations"] = observations
        if group["events"] and all(e.get("motion_origin") == "pose_trajectory" for e in group["events"]):
            group["evidence_status"] = "trajectory_observed"
            group["coverage_status"] = "pose_observation_only"
        for event in group["events"]:
            if event.get("motion_origin") != "pose_trajectory":
                event["trajectory_details"] = analyze_event(output, event.get("limb"), event.get("start_seconds"), event.get("end_seconds"), tracks)
        group["events"].sort(key=lambda e: (e.get("start_seconds", 0), e.get("end_seconds", 0), e.get("limb", "")))
    output["motion_analysis"] = {"version": VERSION, "basis": "registered_pose_trajectory", "status": "observation_only", "time_basis": "source_video",
                                  "coverage_basis": "registered_torso_intervals",
                                  "coverage": round(max(0., 1 - sum(max(0., r["end_seconds"] - r["start_seconds"]) for r in gaps) / duration), 4),
                                  "gaps": gaps, "body_motion": body_motion, "limbs": limb_summary,
                                  "limitations": ["身体共同位移与主动肢体移位分别检查", "二维点不证明抓握、踩实、受力或专业技术", "真实识别准确率待独立视频验收"]}
    return output
