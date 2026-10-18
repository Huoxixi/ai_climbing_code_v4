"""Measured, wall-registered torso positions for the post-climb recap only."""
from copy import deepcopy
import math
import numpy as np

from .replay_action_trajectory import prepare_tracks

VERSION = "registered-torso-center-trajectory-v2"
MAX_GAP = .6
MAX_SPEED = 4.5  # Torso lengths / source second; reject discontinuities, not techniques.
WINDOW_BASIS = "two_distinct_lit_holds_to_two_hand_finish_overlap"


def climbing_window(result):
    """Use overlapping saved contact intervals, never pose proximity or video edges."""
    if result.get('skeleton_only'):
        from .replay_pose_start import pose_climbing_window
        return pose_climbing_window(result)
    video = result.get("video") or {}
    fps = video.get("fps") or 0
    duration = result.get("source_duration_seconds", video.get("duration_seconds", 0))
    holds = [h for h in result.get("holds", []) if h.get("route_candidate") is not False]
    ids = {str(h.get("id")) for h in holds if h.get("id") is not None}
    explicit = {str(h["id"]) for h in holds if h.get("is_finish") or h.get("role") in ("finish", "top")}
    boxes = [h for h in holds if isinstance(h.get("bbox"), (list, tuple)) and len(h["bbox"]) >= 4
             and all(isinstance(v, (int, float)) and math.isfinite(v) for v in h["bbox"][:4])]
    top = min(boxes, key=lambda h: h["bbox"][1] + h["bbox"][3] / 2, default=None)
    finish_ids = explicit or ({str(top["id"])} if top is not None else set())
    limbs = ("left_hand", "right_hand", "left_foot", "right_foot")
    contacts = {limb: [] for limb in limbs}
    for row in (result.get("attempt") or {}).get("contacts") or []:
        if row.get("limb") not in contacts or str(row.get("hold_id")) not in ids:
            continue
        start, end = row.get("start_time_seconds"), row.get("end_time_seconds")
        if start is None and fps > 0 and row.get("start_source_frame") is not None:
            start = row["start_source_frame"] / fps
        if end is None and fps > 0 and row.get("end_source_frame") is not None:
            end = row["end_source_frame"] / fps
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (start, end)) or not 0 <= start < end <= duration + .05:
            continue
        contacts[row["limb"]].append((start, min(end, duration), str(row["hold_id"])))
    starts = sorted({a for rows in contacts.values() for a, _, _ in rows})
    def lit_holds(t):
        # Match the player: the newest active contact wins for each limb.
        active = [max((row for row in contacts[limb] if row[0] <= t <= row[1]),
                      key=lambda row: row[0], default=None) for limb in limbs]
        return {row[2] for row in active if row is not None}

    start = next((t for t in starts if len(lit_holds(t)) >= 2), None)
    output = {"status": "start_unconfirmed", "start_seconds": start, "end_seconds": None,
              "finish_hold_ids": sorted(finish_ids), "finish_basis": "marked_finish" if explicit else "highest_route_hold_candidate",
              "basis": WINDOW_BASIS}
    if start is None:
        return output
    ends = [max(a, c) for a, b, hold in contacts["left_hand"] for c, d, other in contacts["right_hand"]
            if hold in finish_ids and other in finish_ids and max(a, c) >= start and max(a, c) < min(b, d)]
    if ends:
        output.update(status="finish_observed", end_seconds=min(ends))
    else:
        # A fall has no finish. Stop at the last on-route hand contact instead of
        # extending the trajectory through landing and walking away.
        end = max((b for limb in limbs[:2] for a, b, _ in contacts[limb] if b > start),
                  default=max((b for rows in contacts.values() for a, b, _ in rows if b > start), default=start))
        output.update(status="finish_unconfirmed", end_seconds=end)
    return output


def _trajectory(result, mass=False):
    video = result.get("video") or {}
    width, height = video.get("width", 0), video.get("height", 0)
    duration = result.get("source_duration_seconds", video.get("duration_seconds", 0))
    output = {"version": VERSION, "status": "insufficient", "coordinate_basis": "wall_reference_image",
              "time_basis": "source_video", "reference_size": [width, height],
              "duration_seconds": duration, "segments": [], "coverage": 0., "observed_seconds": 0.,
              "metrics": None, "breaks": {}, "max_gap_seconds": MAX_GAP,
              "basis": "shoulder_hip_mean_min3_score05", "interpolated": False}
    if mass:
        from .replay_center_of_mass import VERSION as MASS_VERSION
        output.update(version=MASS_VERSION, basis='segment_mass_weighted_2d_head_wrist_ankle_proxies',
                      label='估算重心', dimensionality='2d_projection')
    window = climbing_window(result)
    output["climbing_window"] = window
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
               for v in (width, height, duration)):
        return output
    if window["start_seconds"] is None or window["end_seconds"] is None or window["end_seconds"] <= window["start_seconds"]:
        return output
    start, end = window["start_seconds"], window["end_seconds"]
    aspect = np.array([width, height], float) / min(width, height)
    rows = prepare_tracks(result)
    candidates = []
    for row in rows:
        if not start <= row["time"] <= end:
            continue
        if row["body"] is None or row["scale"] is None:
            candidates.append(None)
            continue
        joints = tuple(i for i in (5, 6, 11, 12) if row["valid"][i])
        xy = row['body']
        if mass:
            from .replay_center_of_mass import estimate_center_of_mass
            estimate = estimate_center_of_mass({'observed':True, 'kpts_xy':(row['points']/aspect).tolist(),
                'kpts_score':row['valid'].astype(float).tolist()})
            if not estimate:
                candidates.append(None)
                continue
            xy = np.asarray(estimate['xy']) * aspect
            joints = tuple(estimate['joints'])
        candidates.append({"time": row["time"], "xy": xy, "scale": row["scale"],
                           "joints": joints, "frame_id": row["frame_id"]})

    def speed(a, b):
        dt = b["time"] - a["time"]
        return float(np.linalg.norm(b["xy"] - a["xy"])) / max(1e-9, dt * (a["scale"] + b["scale"]) / 2)

    # A lone spike followed by a return is never a legitimate excursion statistic.
    spikes = set()
    for index in range(1, len(candidates) - 1):
        a, b, c = candidates[index - 1:index + 2]
        if (all(point is not None for point in (a, b, c))
                and a["joints"] == b["joints"] == c["joints"]
                and 0 < b["time"] - a["time"] <= MAX_GAP
                and 0 < c["time"] - b["time"] <= MAX_GAP
                and speed(a, b) > MAX_SPEED and speed(b, c) > MAX_SPEED
                and speed(a, c) <= MAX_SPEED):
            spikes.add(index)

    runs, run, previous = [], [], None
    breaks, observed_seconds = {}, 0.
    for index, point in enumerate(candidates):
        reason = None
        if point is None or index in spikes:
            reason = "jump" if index in spikes else "missing_or_unregistered"
        elif previous is not None:
            dt = point["time"] - previous["time"]
            if not 0 < dt <= MAX_GAP:
                reason = "sampling_gap"
            elif point["joints"] != previous["joints"]:
                reason = "reference_joints_changed"
            elif speed(previous, point) > MAX_SPEED:
                reason = "jump"
            else:
                observed_seconds += dt
        if reason:
            breaks[reason] = breaks.get(reason, 0) + 1
            if run:
                runs.append(run)
            run, previous = [], None
        if point is not None and index not in spikes:
            xy = point["xy"] / aspect
            run.append({"time_seconds": round(point["time"], 6), "frame_id": point["frame_id"],
                        "xy": [round(float(v), 6) for v in xy], "joints": list(point["joints"])})
            previous = point
    if run:
        runs.append(run)
    # Singletons are not a route. Keeping them would turn isolated detections into extrema.
    runs = [run for run in runs if len(run) >= 2]
    points = [point for run in runs for point in run]
    output.update(segments=runs, breaks=breaks, observed_seconds=round(observed_seconds, 6),
                  coverage=round(min(1., observed_seconds / (end - start)), 4))
    if len(points) < 3:
        return output
    output["status"] = "observed" if output["coverage"] >= .8 and not breaks else "partial"
    first, last = points[0], points[-1]
    output.update(start_seconds=first["time_seconds"], end_seconds=last["time_seconds"])
    if not breaks.get("jump") and all(point["joints"] == first["joints"] for point in points):
        xs = [point["xy"][0] for point in points]
        output["metrics"] = {
            "net_horizontal_percent": round((last["xy"][0] - first["xy"][0]) * 100, 1),
            "left_extent_percent": round(max(0., first["xy"][0] - min(xs)) * 100, 1),
            "right_extent_percent": round(max(0., max(xs) - first["xy"][0]) * 100, 1),
            "horizontal_span_percent": round((max(xs) - min(xs)) * 100, 1),
            "basis": "first_reliable_center", "unit": "reference_image_width_percent"}
    return output


def torso_trajectory(result):
    return _trajectory(result)


def center_of_mass_trajectory(result):
    return _trajectory(result, mass=True)


def enrich_torso_trajectory(result):
    output = deepcopy(result)
    output["torso_trajectory"] = torso_trajectory(output)
    output['center_of_mass_trajectory'] = center_of_mass_trajectory(output)
    return output
