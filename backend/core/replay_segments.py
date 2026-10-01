"""Conservative, local action segments and same-route comparisons.

Only confirmed saved-route hold identities may cross a video boundary. The
sampled timeline is evidence, so intervals below describe sampling resolution,
not a calibrated confidence interval.
"""
from __future__ import annotations

import math
from collections import defaultdict


LIMBS = {"left_hand", "right_hand", "left_foot", "right_foot"}
JOINTS = {"left_elbow": (5, 7, 9), "right_elbow": (6, 8, 10),
          "left_hip": (5, 11, 13), "right_hip": (6, 12, 14),
          "left_knee": (11, 13, 15), "right_knee": (12, 14, 16)}


def measured_joint_angles(points: list, scores: list, width: int, height: int) -> dict[str, float]:
    """Return visible 2D image-plane angles; never infer force or depth."""
    result = {}
    for name, (a, b, c) in JOINTS.items():
        if max(a, b, c) >= len(points) or max(a, b, c) >= len(scores):
            continue
        if min(float(scores[index] or 0) for index in (a, b, c)) < .15:
            continue
        first = ((float(points[a][0]) - float(points[b][0])) * width,
                 (float(points[a][1]) - float(points[b][1])) * height)
        second = ((float(points[c][0]) - float(points[b][0])) * width,
                  (float(points[c][1]) - float(points[b][1])) * height)
        norm = math.hypot(*first) * math.hypot(*second)
        if norm < 1e-9:
            continue
        cosine = max(-1.0, min(1.0, (first[0] * second[0] + first[1] * second[1]) / norm))
        result[name] = round(math.degrees(math.acos(cosine)), 2)
    return result


def build_segments(result: dict) -> list[dict]:
    attempt = result.get("attempt") or {}
    holds = {hold.get("id"): hold for hold in result.get("holds") or []}
    samples = sorted(result.get("pose_samples") or [], key=lambda item: item.get("time_seconds", 0))
    def boundary_gap(frame: int | None) -> float:
        for index, sample in enumerate(samples):
            if sample.get("source_frame_id") == frame:
                gaps = []
                if index:
                    gaps.append(float(sample["time_seconds"]) - float(samples[index - 1]["time_seconds"]))
                if index + 1 < len(samples):
                    gaps.append(float(samples[index + 1]["time_seconds"]) - float(sample["time_seconds"]))
                return max(gaps, default=0.0)
        return 0.0
    by_limb: dict[str, list[dict]] = defaultdict(list)
    segments = []
    for action in attempt.get("action_steps") or []:
        limb = action.get("limb")
        if limb not in LIMBS:
            continue
        previous = by_limb[limb][-1] if by_limb[limb] else None
        by_limb[limb].append(action)
        if previous is None or previous.get("hold_id") == action.get("hold_id"):
            continue
        start = previous.get("stable_time_seconds")
        end = action.get("stable_time_seconds")
        if start is None or end is None or float(end) <= float(start):
            continue
        source = holds.get(previous.get("hold_id")) or {}
        target = holds.get(action.get("hold_id")) or {}
        source_id = str(source["saved_object_id"]) if source.get("identity_source") == "confirmed_saved_route" and source.get("saved_object_id") is not None else None
        target_id = str(target["saved_object_id"]) if target.get("identity_source") == "confirmed_saved_route" and target.get("saved_object_id") is not None else None
        # Action source frames remain the authoritative evidence pointer.
        boundary_samples = [sample for sample in samples if sample.get("source_frame_id") in
                            {previous.get("stable_source_frame"), action.get("stable_source_frame")}]
        aligned = len(boundary_samples) == 2 and all(sample.get("wall_alignment") == "aligned" for sample in boundary_samples)
        reason = None
        if not source_id or not target_id:
            reason = "unconfirmed_hold_identity"
        elif not aligned:
            reason = "wall_alignment_insufficient"
        elif min(float(source.get("saved_route_iou") or 0), float(target.get("saved_route_iou") or 0)) < .35:
            reason = "hold_match_weak"
        elif boundary_gap(previous.get("stable_source_frame")) <= 0 or boundary_gap(action.get("stable_source_frame")) <= 0:
            reason = "timestamps_unavailable"
        uncertainty = boundary_gap(previous.get("stable_source_frame")) + boundary_gap(action.get("stable_source_frame"))
        first_target_contact = action.get("start_time_seconds")
        stabilization = (round(float(end) - float(first_target_contact), 6)
                         if first_target_contact is not None and float(end) >= float(first_target_contact) else None)
        segments.append({
            "id": f"{limb}:{previous['step']}:{action['step']}",
            "limb": limb, "source_hold_id": previous["hold_id"],
            "target_hold_id": action["hold_id"],
            "source_route_hold_id": source_id, "target_route_hold_id": target_id,
            "start_time_seconds": round(float(start), 6),
            "end_time_seconds": round(float(end), 6),
            "duration_seconds": round(float(end) - float(start), 6),
            "boundary_uncertainty_seconds": round(uncertainty, 6),
            "start_source_frame": previous.get("stable_source_frame"),
            "end_source_frame": action.get("stable_source_frame"),
            "first_target_contact_time_seconds": first_target_contact,
            "landing_stabilization_seconds": stabilization,
            "adjustment_count": None,
            "comparable": reason is None, "reason": reason,
            "timing_basis": "normalized_video_sample_timestamps",
            "phase_detail": "not_observed_at_current_sample_rate",
            "technique_labels": [],
            "source": "automatic_contact_relation",
        })
    return segments


def compare_segments(first: dict, second: dict, *, same_climber_confirmed: bool) -> dict:
    if first.get("owner") != second.get("owner") or not first.get("owner"):
        raise ValueError("owner_mismatch")
    if not first.get("route_id") or first.get("route_id") != second.get("route_id"):
        raise ValueError("route_mismatch")
    if first.get("route_version_id") != second.get("route_version_id") or not first.get("route_version_id"):
        raise ValueError("route_version_mismatch")
    if not same_climber_confirmed:
        raise ValueError("same_climber_unconfirmed")
    left = effective_segments(first)
    right = effective_segments(second)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for segment in right:
        key = (segment.get("limb"), segment.get("source_route_hold_id"), segment.get("target_route_hold_id"))
        groups[key].append(segment)
    used: set[str] = set()
    rows = []
    for segment in left:
        key = (segment.get("limb"), segment.get("source_route_hold_id"), segment.get("target_route_hold_id"))
        candidates = [item for item in groups[key] if item.get("id") not in used]
        peer = candidates[0] if candidates else None
        if peer:
            used.add(peer["id"])
        reason = segment.get("reason") or (peer or {}).get("reason")
        if not peer:
            reason = reason or "matching_segment_missing"
        if peer and segment.get("comparable") and peer.get("comparable"):
            first_duration = float(segment["duration_seconds"])
            second_duration = float(peer["duration_seconds"])
            delta = round(second_duration - first_duration, 6)
            uncertainty = round(float(segment["boundary_uncertainty_seconds"]) +
                                float(peer["boundary_uncertainty_seconds"]), 6)
            status = "uncertain" if abs(delta) <= uncertainty else "shorter" if delta < 0 else "longer"
        else:
            delta = uncertainty = None
            status = "not_comparable"
        rows.append({"first": segment, "second": peer, "status": status,
                     "reason": reason, "delta_seconds": delta,
                     "combined_uncertainty_seconds": uncertainty})
    for segment in right:
        if segment.get("id") not in used:
            rows.append({"first": None, "second": segment, "status": "not_comparable",
                         "reason": segment.get("reason") or "matching_segment_missing",
                         "delta_seconds": None, "combined_uncertainty_seconds": None})
    return {"route_id": first["route_id"], "route_version_id": first["route_version_id"],
            "first_job_id": first["id"], "second_job_id": second["id"],
            "timing_basis": "normalized_video_sample_timestamps", "segments": rows}


def effective_segments(job: dict) -> list[dict]:
    """Apply a review overlay without changing automatic evidence."""
    reviews = job.get("segment_reviews") or {}
    fps = float((job.get("video") or {}).get("fps") or 0)
    result = []
    for original in (job.get("result") or {}).get("attempt", {}).get("segments") or []:
        segment = dict(original)
        review = reviews.get(segment["id"])
        if review:
            segment.update({
                "limb": review["limb"],
                "source_route_hold_id": review["source_route_hold_id"],
                "target_route_hold_id": review["target_route_hold_id"],
                "start_time_seconds": review["start_time_seconds"],
                "end_time_seconds": review["end_time_seconds"],
                "duration_seconds": round(review["end_time_seconds"] - review["start_time_seconds"], 6),
                "boundary_uncertainty_seconds": max(float(segment.get("boundary_uncertainty_seconds") or 0),
                                                    2 / fps if fps > 0 else 0),
                "comparable": True, "reason": None,
                "source": "user_confirmed", "review_version": review["version"],
                "technique_labels": ([{"name": review["technique_label"], "source": "user_confirmed"}]
                                     if review.get("technique_label") else []),
                "landing_stabilization_seconds": None,
                "adjustment_count": None,
            })
        result.append(segment)
    return result
