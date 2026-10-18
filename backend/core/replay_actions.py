"""Source-time action organization, independent of coaching and knowledge approval.

Automatic tracks remain immutable. Local visual decisions are stored alongside
them and only structured, twice-checked events can supply anatomical side names.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import numpy as np
from .replay_action_naming import ACTIONS, checked_details, enrich_names
from .replay_action_trajectory import registered_points, prepare_tracks, chain_pair_reasons, active_relative_delta
from .replay_action_segmentation import displacement_bouts

VERSION = "replay-actions-v1"
ALGORITHM_VERSION = "observed-motion-settled-event-timeline-v11"
LIMBS = {"left_hand": ("左手", (5, 7, 9)), "right_hand": ("右手", (6, 8, 10)),
         "left_foot": ("左脚", (11, 13, 15)), "right_foot": ("右脚", (12, 14, 16))}
EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12),
         (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def aligned(sample, video):
    """Return anatomical joint indices in the wall frame, never x-sorted sides."""
    return registered_points(sample, video)


def motion_intervals(result):
    video = result["video"]
    samples = sorted((p for p in result.get("pose_samples", []) if number(p.get("time_seconds"))),
                     key=lambda p: p["time_seconds"])
    tracks = prepare_tracks(result)
    intervals = []
    for index, (a, b) in enumerate(zip(samples, samples[1:])):
        start, end = a["time_seconds"], b["time_seconds"]
        dt = end - start
        pa, pb = aligned(a, video), aligned(b, video)
        kind, moving, flags = "unknown", [], []
        if 0 < dt <= .6 and pa is not None and pb is not None:
            valid = pa[1] & pb[1]
            velocity = np.linalg.norm(pb[0] - pa[0], axis=1) / dt
            body = [i for i in (5, 6, 11, 12) if valid[i]]
            chains = []
            for limb, (_, chain) in LIMBS.items():
                if all(valid[i] for i in chain):
                    # A discontinuity is a reason to inspect; never flip labels by x.
                    conflicts = chain_pair_reasons(tracks[index], tracks[index + 1], limb)
                    if max(velocity[list(chain)]) > 1.2 or any(reason in conflicts for reason in ("side_identity_conflict", "chain_length_change", "trajectory_jump")):
                        flags.append(limb)
                        continue
                    chains.append(limb)
                    # Active movement is relative to the anatomical shoulder or
                    # hip; a translated body cannot make every limb reach.
                    relative_delta = active_relative_delta(tracks[index], tracks[index + 1], limb)
                    relative_velocity = np.linalg.norm(relative_delta) / dt if relative_delta is not None else None
                    if velocity[chain[-1]] > .025 and relative_velocity is not None and relative_velocity > .04:
                        moving.append(limb)
            body_moving = len(body) >= 2 and np.median(velocity[body]) > .035
            # One obscured contact cannot turn visible body motion into unknown.
            if moving or body_moving:
                kind = "moving"
            elif len(body) >= 3 and len(chains) >= 3 and not flags:
                kind = "relative_still"
        intervals.append({"start_seconds": start, "end_seconds": end, "kind": kind,
                          "candidate_limbs": moving, "continuity_conflicts": flags})
    return intervals


def locate_groups(result):
    """Locate significant axis displacement, retaining preparation and settling."""
    duration = result["video"]["duration_seconds"]
    intervals = motion_intervals(result)
    bouts = displacement_bouts(result)
    from .replay_torso_trajectory import climbing_window
    window = climbing_window(result)
    if window['start_seconds'] is not None and window['end_seconds'] is not None:
        bouts = [{**b, 'start':max(b['start'],window['start_seconds'])}
                 for b in bouts if b['start'] <= window['end_seconds']]
        bouts = [b for b in bouts if b['end']-b['start'] >= .25]
    groups = []
    for i, bout in enumerate(bouts):
        start = max(window['start_seconds'] or 0., bout["start"] - .3)
        end = min(duration, bout["end"])
        if i:
            start = max(start, (bout['start'] + bouts[i-1]['end']) / 2)
        if i + 1 < len(bouts):
            end = min(end, (bout['end'] + bouts[i+1]['start']) / 2)
        groups.append({"id": f"action-{i + 1:03d}", "start_seconds": start, "end_seconds": end,
                       "motion_start_seconds": bout["start"], "motion_end_seconds": bout["end"],
                       "candidate_limbs": sorted(bout["limbs"]), "body_moving": bout.get('body', False),
                       "ending_stable": bout.get('settled', False),
                       "settle_confirmation_seconds": .8 if bout.get('settled') else None,
                       "events": [], "description": "动作片段",
                       "evidence_status": "needs_local_review", "evidence": []})
    return groups, intervals


def basic_metrics(result, intervals, review=None):
    from .replay_summary import build_replay_summary
    summary = build_replay_summary(result, review)
    timing = summary["timing"]
    reliable = timing.get("status") in {"reviewed", "confirmed", "user_confirmed"} and timing.get("elapsed_seconds") is not None
    metrics = [{"key": "duration", "label": "攀爬用时" if reliable else "视频记录时长",
                "value": timing["elapsed_seconds"] if reliable else result["video"]["duration_seconds"],
                "unit": "秒", "approximate": True, "basis": "reviewed_boundary" if reliable else "source_duration"}]
    for limb, row in summary["limbs"].items():
        if row["contact_count"]:
            metrics.append({"key": limb, "label": LIMBS[limb][0] + "不同岩点", "value": row["count"],
                            "unit": "个", "basis": summary["provenance"]["contact_source"]})
    known = [row for row in intervals if row["kind"] != "unknown"]
    duration = result["video"]["duration_seconds"]
    coverage = sum(r["end_seconds"] - r["start_seconds"] for r in known)
    if coverage >= duration * .8:
        for kind, label in (("moving", "可见移动"), ("relative_still", "相对停留")):
            seconds = sum(r["end_seconds"] - r["start_seconds"] for r in known if r["kind"] == kind)
            metrics.append({"key": kind, "label": label, "value": round(seconds, 1), "unit": "秒",
                            "approximate": True, "basis": "registered_body_and_limbs"})
    # Longest stop requires continuous body/limb evidence; unrelated contact gaps
    # do not invalidate it, and missing pose intervals may not be bridged.
    runs = []
    for row in intervals:
        if row["kind"] == "relative_still":
            if runs and abs(runs[-1][1] - row["start_seconds"]) < 1e-6:
                runs[-1][1] = row["end_seconds"]
            else:
                runs.append([row["start_seconds"], row["end_seconds"]])
    longest = max(runs, key=lambda r: r[1] - r[0], default=None)
    if longest and longest[1] - longest[0] >= 1 and coverage >= duration * .95:
        metrics.append({"key": "longest_still", "label": "最长相对停留", "value": round(longest[1] - longest[0], 1),
                        "unit": "秒", "approximate": True, "start_seconds": longest[0], "end_seconds": longest[1],
                        "basis": "continuous_registered_motion"})
    return metrics


def apply_local_review(group, proposed, checked, frames, holds=()):
    """Every displayed side/event needs a local chain check and temporal anchors.

    Free model prose is never displayed. Missing/conflicting events retain the
    playable window; candidate side identities are not promoted to facts.
    """
    output = deepcopy(group)
    by_id = {f["frame_id"]: f for f in frames}
    events = proposed.get("events", []) if isinstance(proposed, dict) else []
    verifications = checked.get("events", []) if isinstance(checked, dict) else []
    if not isinstance(verifications, list):
        verifications = []
    accepted = []
    for i, event in enumerate(events if isinstance(events, list) else []):
        if not isinstance(event, dict) or i >= len(verifications):
            continue
        check = verifications[i]
        ids = event.get("frame_ids", [])
        limb, action = event.get("limb"), event.get("action")
        if (not isinstance(check, dict) or not isinstance(limb, str) or not isinstance(action, str) or limb not in LIMBS or action not in ACTIONS
                or check.get("verified") is not True or check.get("chain_continuous") is not True
                or check.get("conflict") is not False or check.get("limb") != limb
                or check.get("action") != action or check.get("occluded") is not False
                or not isinstance(ids, list) or len(ids) < 3
                or any(not isinstance(key, str) or key not in by_id for key in ids)
                or len(set(ids)) != len(ids)):
            continue
        times = [by_id[key]["time_seconds"] for key in ids]
        if times != sorted(times) or times[0] >= times[-1] or not group["start_seconds"] - .04 <= times[0] < times[-1] <= group["end_seconds"] + .04:
            continue
        if accepted and times[0] < accepted[-1]["start_seconds"]:
            continue
        accepted.append({"limb": limb, "action": action, "start_seconds": times[0], "end_seconds": times[-1],
                         "evidence": [{"frame_id": key, "time_seconds": by_id[key]["time_seconds"]} for key in ids],
                         "evidence_status": "locally_verified"})
        details = checked_details({**event, "start_seconds": times[0], "end_seconds": times[-1]}, check, by_id, holds)
        accepted[-1].update(details)
        required = {"contact": "target_contact", "release": "release", "readjust": "readjust", "attempt": "attempt", "wall_contact": "wall_contact"}.get(action)
        if required and not any(f["kind"] == required for f in details["facts"]):
            accepted[-1]["action"] = "adjust" if action == "readjust" else "move"
    # Only independently checked events supply words. Other candidates remain
    # in the audit record; one unresolved event must not hide a clearly seen foot.
    if accepted:
        output.update(events=accepted, evidence_status="locally_verified",
                      coverage_status="complete" if len(accepted) == len(events) else "partial",
                      evidence=[e for event in accepted for e in event["evidence"]])
        output = enrich_names({"groups": [output]})["groups"][0]
    return output


def organize(job, reviews=None):
    result = deepcopy(job["result"])
    result["video"] = {**job.get("video", {}), **result.get("video", {})}
    duration = result["video"].get("duration_seconds")
    if not number(duration) or not 0 < duration <= 1800:
        raise ValueError("Original source timeline required")
    groups, intervals = locate_groups(result)
    automatic = deepcopy(groups)
    for index, group in enumerate(groups):
        review = (reviews or {}).get(group["id"])
        if review:
            groups[index] = apply_local_review(group, review["proposed"], review["checked"], review["frames"], result.get("holds", []))
    organized = enrich_names({"schema_version": VERSION, "algorithm_version": ALGORITHM_VERSION, "source_duration_seconds": duration, "time_basis": "source_video",
            "groups": groups, "automatic_groups": automatic, "local_reviews": deepcopy(reviews or {}),
            "segmentation_basis": "significant_axis_displacement", "motion_intervals": intervals, "metrics": basic_metrics(result, intervals),
            "video": result["video"], "pose_samples": result.get("pose_samples", []), "holds": result.get("holds", []),
            "attempt": deepcopy(result.get("attempt") or {})})
    if result.get('skeleton_only') or job.get('skeleton_only'):
        from .replay_skeleton_mode import without_hold_data
        organized = without_hold_data(organized)
    return organized
