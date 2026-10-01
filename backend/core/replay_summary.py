"""Source-time replay metrics, with an explicit, reversible review overlay.

This module uses saved evidence only.  A sampled contact is not proof of lift-off,
completion, or thought.  ``None`` means reviewed non-contact; ``"unknown"`` means
insufficient evidence.  Export slow motion and interpolated poses are never input.
"""
from __future__ import annotations

from copy import deepcopy
import math
from statistics import median


LIMBS = {"left_hand": ("左手", 9), "right_hand": ("右手", 10),
         "left_foot": ("左脚", 15), "right_foot": ("右脚", 16)}
UNKNOWN = "unknown"
EPSILON = 1e-7


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _rounded(value):
    return round(value, 6)


def _video(result):
    video = deepcopy(result.get("video") or {})
    duration = _number(video.get("duration_seconds"))
    if duration is None:
        fps, frames = _number(video.get("fps")), _number(video.get("frame_count"))
        duration = frames / fps if fps and fps > 0 and frames is not None else None
    if duration is None or duration < 0:
        raise ValueError("video.duration_seconds must be finite and nonnegative")
    video["duration_seconds"] = _rounded(duration)
    return video


def _timing(video, review):
    duration = video["duration_seconds"]
    timing = {"start_seconds": None, "end_seconds": None, "elapsed_seconds": None,
              "observed_start_seconds": 0.0, "observed_end_seconds": duration,
              "observed_duration_seconds": duration, "outcome": "unconfirmed",
              "status": "unconfirmed", "source": "source_video"}
    override = review.get("timing") if review else None
    if override is not None:
        start, end = _number(override.get("start_seconds")), _number(override.get("end_seconds"))
        if (start is None) != (end is None):
            raise ValueError("review timing requires both start_seconds and end_seconds")
        if start is not None:
            if not 0 <= start < end <= duration + EPSILON:
                raise ValueError("review timing must lie inside source video")
            end = min(end, duration)
            timing.update(start_seconds=_rounded(start), end_seconds=_rounded(end),
                          elapsed_seconds=_rounded(end - start))
        timing.update(outcome=str(override.get("outcome") or "unconfirmed"),
                      status=str(override.get("status") or "reviewed"),
                      source=str(override.get("source") or "reviewed"))
        if override.get("note"):
            timing["note"] = str(override["note"])
        # A reviewed observation window can be shorter than the full recording.
        for name in ("observed_start_seconds", "observed_end_seconds"):
            if name in override:
                value = _number(override[name])
                if value is None:
                    raise ValueError("observed timing must be finite")
                timing[name] = _rounded(value)
        observed_start, observed_end = timing["observed_start_seconds"], timing["observed_end_seconds"]
        if not 0 <= observed_start <= observed_end <= duration + EPSILON:
            raise ValueError("observed timing must lie inside source video")
        timing["observed_duration_seconds"] = _rounded(observed_end - observed_start)
    return timing


def _window(timing):
    if timing["start_seconds"] is not None:
        return timing["start_seconds"], timing["end_seconds"]
    return timing["observed_start_seconds"], timing["observed_end_seconds"]


def _contacts(result, review, start, end):
    reviewed = review is not None and "contacts" in review
    rows = review["contacts"] if reviewed else (result.get("attempt") or {}).get("contacts") or []
    contacts, excluded = [], 0
    for index, row in enumerate(rows):
        left = _number(row.get("start_seconds" if reviewed else "start_time_seconds"))
        right = _number(row.get("end_seconds" if reviewed else "end_time_seconds"))
        hold = row.get("hold_id", UNKNOWN)
        valid_hold = hold is None or isinstance(hold, (str, int)) and not isinstance(hold, bool)
        if row.get("limb") not in LIMBS or left is None or right is None or right <= left or not valid_hold:
            if reviewed:
                raise ValueError("invalid reviewed contact interval")
            excluded += 1
            continue
        left, right = max(start, left), min(end, right)
        if right <= left + EPSILON:
            continue
        contacts.append({"limb": row["limb"], "hold_id": hold,
                         "start_seconds": left, "end_seconds": right,
                         "status": "reviewed" if reviewed else "automatic",
                         "note": str(row.get("note") or ""), "evidence_index": index})
    return sorted(contacts, key=lambda row: (row["start_seconds"], row["end_seconds"])), reviewed, excluded


def _uncertainties(review, start, end):
    result = []
    for row in (review or {}).get("uncertainties") or []:
        left, right = _number(row.get("start_seconds")), _number(row.get("end_seconds"))
        limbs = row.get("limbs", list(LIMBS))
        if (left is None or right is None or right <= left or not isinstance(limbs, list)
                or not limbs or any(limb not in LIMBS for limb in limbs)):
            raise ValueError("invalid reviewed uncertainty interval")
        left, right = max(left, start), min(right, end)
        if right > left + EPSILON:
            result.append({"start_seconds": left, "end_seconds": right,
                           "limbs": limbs, "reason": str(row.get("reason") or "reviewed_uncertainty")})
    return result


def _sample_cells(result, start, end):
    samples = sorted((sample for sample in result.get("pose_samples") or []
                      if _number(sample.get("time_seconds")) is not None),
                     key=lambda sample: float(sample["time_seconds"]))
    gaps = [float(b["time_seconds"]) - float(a["time_seconds"])
            for a, b in zip(samples, samples[1:]) if float(b["time_seconds"]) > float(a["time_seconds"])]
    fps = _number((result.get("analysis") or {}).get("sampling", {}).get("effective_fps"))
    typical_gap = 1 / fps if fps and fps > 0 else median(gaps) if gaps else 0.0

    def visible(sample, limb):
        index = LIMBS[limb][1]
        points, scores = sample.get("kpts_xy") or [], sample.get("kpts_score") or []
        return (sample.get("observed", True) is not False and sample.get("wall_alignment") != "failed"
                and index < len(points) and index < len(scores) and len(points[index]) >= 2
                and any(_number(value) not in (None, 0) for value in points[index][:2])
                and (_number(scores[index]) or 0) >= .15)

    cells = []
    for index, sample in enumerate(samples):
        left = float(sample["time_seconds"])
        next_sample = samples[index + 1] if index + 1 < len(samples) else None
        right = float(next_sample["time_seconds"]) if next_sample else end
        # Requiring both bounding observations avoids filling missing evidence.
        close = typical_gap > 0 and right - left <= typical_gap * 1.75 + EPSILON
        valid = {limb: bool(close and visible(sample, limb) and
                            (next_sample is None or visible(next_sample, limb))) for limb in LIMBS}
        left, right = max(left, start), min(right, end)
        if right > left + EPSILON:
            cells.append({"start_seconds": left, "end_seconds": right, "valid": valid})
    return cells, typical_gap


def _inside(row, time):
    return row["start_seconds"] <= time < row["end_seconds"]


def _limb_state(rows, time, limb, cells, reviewed, uncertainties):
    doubt = next((row for row in uncertainties if limb in row["limbs"] and _inside(row, time)), None)
    if doubt:
        return UNKNOWN, "unknown", doubt["reason"]
    if not reviewed and not any(_inside(cell, time) and cell["valid"][limb] for cell in cells):
        return UNKNOWN, "unknown", "missing_measured_limb_evidence"
    active = [row for row in rows if _inside(row, time)]
    if active:
        holds = {row["hold_id"] for row in active}
        if len(holds) != 1 or UNKNOWN in holds:
            return UNKNOWN, "unknown", "conflicting_or_unknown_contact"
        if holds == {None}:
            # Explicit reviewed release may be part of a move between two holds.
            # A limb kept free, or a same-hold release/regrip, is not a new move.
            before = [row for row in rows if row["end_seconds"] <= time and row["hold_id"] is not None]
            after = [row for row in rows if row["start_seconds"] > time and row["hold_id"] is not None]
            previous = max(before, key=lambda row: row["end_seconds"]) if before else None
            following = min(after, key=lambda row: row["start_seconds"]) if after else None
            if previous and following:
                if UNKNOWN in (previous["hold_id"], following["hold_id"]):
                    return UNKNOWN, "unknown", "contact_state_unobserved"
                if previous["hold_id"] != following["hold_id"]:
                    return None, "transition", "change_to_different_hold"
                return previous["hold_id"], "hold", "same_hold_regrip_merged"
        return active[0]["hold_id"], "hold", ""
    before = [row for row in rows if row["end_seconds"] <= time]
    after = [row for row in rows if row["start_seconds"] > time]
    previous = max(before, key=lambda row: row["end_seconds"]) if before else None
    following = min(after, key=lambda row: row["start_seconds"]) if after else None
    if previous is None or following is None or UNKNOWN in (previous["hold_id"], following["hold_id"]):
        return UNKNOWN, "unknown", "contact_state_unobserved"
    if previous["hold_id"] == following["hold_id"]:
        return previous["hold_id"], "hold", "same_hold_regrip_merged"
    return None, "transition", "change_to_different_hold"


def _phase(start, end, kind, contacts, status, notes, source):
    return {"start_seconds": _rounded(start), "end_seconds": _rounded(end),
            "duration_seconds": _rounded(end - start), "kind": kind,
            "contacts": contacts, "status": status, "notes": sorted(set(notes)), "source": source}


def _merge_phases(phases):
    merged = []
    for phase in phases:
        previous = merged[-1] if merged else None
        if (previous and abs(previous["end_seconds"] - phase["start_seconds"]) < EPSILON
                and all(previous[key] == phase[key] for key in ("kind", "contacts", "status", "source"))):
            previous["end_seconds"] = phase["end_seconds"]
            previous["duration_seconds"] = _rounded(previous["end_seconds"] - previous["start_seconds"])
            previous["notes"] = sorted(set(previous["notes"] + phase["notes"]))
        else:
            merged.append(deepcopy(phase))
    for index, phase in enumerate(merged, 1):
        phase["id"] = f"phase-{index:03d}"
    return merged


def _automatic_phases(contacts, cells, uncertainties, start, end, reviewed):
    boundaries = {start, end}
    for row in contacts + cells + uncertainties:
        boundaries.update((row["start_seconds"], row["end_seconds"]))
    boundaries = sorted(value for value in boundaries if start <= value <= end)
    by_limb = {limb: [row for row in contacts if row["limb"] == limb] for limb in LIMBS}
    phases = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left + EPSILON:
            continue
        states = {limb: _limb_state(by_limb[limb], (left + right) / 2, limb, cells, reviewed, uncertainties)
                  for limb in LIMBS}
        kinds = {state[1] for state in states.values()}
        kind = "unknown" if "unknown" in kinds else "transition" if "transition" in kinds else "hold"
        status = "unconfirmed" if kind == "unknown" else "reviewed" if reviewed else "automatic"
        phases.append(_phase(left, right, kind, {limb: state[0] for limb, state in states.items()}, status,
                             [f"{limb}:{state[2]}" for limb, state in states.items() if state[2]],
                             "reviewed_contacts" if reviewed else "measured_pose_and_contacts"))
    return _merge_phases(phases)


def _reviewed_phases(rows, uncertainties, start, end):
    normalized = []
    for row in rows:
        left, right = _number(row.get("start_seconds")), _number(row.get("end_seconds"))
        if left is None or right is None or right <= left or row.get("kind") not in ("hold", "transition", "unknown"):
            raise ValueError("invalid phase review")
        contacts = {limb: (row.get("contacts") or {}).get(limb, UNKNOWN) for limb in LIMBS}
        if any(value is not None and (not isinstance(value, (str, int)) or isinstance(value, bool))
               for value in contacts.values()):
            raise ValueError("invalid phase review contacts")
        kind = row["kind"]
        if UNKNOWN in contacts.values():
            kind = "unknown"
        notes = row.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        left, right = max(left, start), min(right, end)
        if right > left + EPSILON:
            normalized.append(_phase(left, right, kind, contacts,
                                     "unconfirmed" if kind == "unknown" else "reviewed",
                                     [str(note) for note in notes], "reviewed_phases"))
    normalized.sort(key=lambda row: row["start_seconds"])
    if any(b["start_seconds"] < a["end_seconds"] - EPSILON for a, b in zip(normalized, normalized[1:])):
        raise ValueError("phase reviews must not overlap")
    boundaries = sorted({start, end, *(value for row in normalized + uncertainties
                                      for value in (row["start_seconds"], row["end_seconds"]))})
    phases = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left + EPSILON:
            continue
        middle = (left + right) / 2
        row = next((row for row in normalized if _inside(row, middle)), None)
        contacts = deepcopy(row["contacts"]) if row else dict.fromkeys(LIMBS, UNKNOWN)
        notes = list(row["notes"]) if row else ["unreviewed_phase_gap"]
        kind = row["kind"] if row else "unknown"
        for uncertainty in uncertainties:
            if _inside(uncertainty, middle):
                contacts.update({limb: UNKNOWN for limb in uncertainty["limbs"]})
                notes.append(uncertainty["reason"])
                kind = "unknown"
        phases.append(_phase(left, right, kind, contacts, "unconfirmed" if kind == "unknown" else "reviewed",
                             notes, "reviewed_phases"))
    return _merge_phases(phases)


def _build(result, review):
    video = _video(result)
    timing = _timing(video, review)
    start, end = _window(timing)
    contacts, reviewed, excluded = _contacts(result, review, start, end)
    uncertainties = _uncertainties(review, start, end)
    cells, sample_gap = _sample_cells(result, start, end)
    if review is not None and "phase_reviews" in review:
        phases = _reviewed_phases(review["phase_reviews"], uncertainties, start, end)
    else:
        phases = _automatic_phases(contacts, cells, uncertainties, start, end, reviewed)
    limbs = {}
    for limb, (label, _) in LIMBS.items():
        relevant = [row for row in contacts if row["limb"] == limb and row["hold_id"] not in (None, UNKNOWN)]
        ids = list(dict.fromkeys(row["hold_id"] for row in relevant))
        limbs[limb] = {"label": label, "hold_ids": ids, "count": len(ids), "contact_count": len(relevant)}
    holds = [phase for phase in phases if phase["kind"] == "hold" and phase["status"] != "unconfirmed"]
    longest = max(holds, key=lambda row: row["duration_seconds"], default=None)
    durations = {kind: _rounded(sum(row["duration_seconds"] for row in phases if row["kind"] == kind))
                 for kind in ("hold", "transition", "unknown")}
    length = end - start
    return {"schema_version": 1, "video": video, "timing": timing, "limbs": limbs,
            "phases": phases, "longest_hold": deepcopy(longest),
            "coverage": {"start_seconds": _rounded(start), "end_seconds": _rounded(end),
                         "duration_seconds": _rounded(length),
                         **{f"{kind}_seconds": value for kind, value in durations.items()},
                         "known_fraction": _rounded((length - durations["unknown"]) / length) if length else 0.0,
                         "sample_interval_seconds": _rounded(sample_gap) if sample_gap else None},
            "provenance": {"timing_basis": "source_video_timestamps",
                           "contact_source": "reviewed_contacts" if reviewed else "automatic_contacts",
                           "phase_source": "reviewed_phases" if review is not None and "phase_reviews" in review else
                                           "reviewed_contacts" if reviewed else "measured_pose_and_contacts",
                           "review_applied": review is not None,
                           "excluded_invalid_automatic_contacts": excluded,
                           "contact_count_definition": "intersecting_contact_intervals_before_same_hold_merge",
                           "hold_definition": "unchanged_four_limb_contact_group_including_same_hold_regrips",
                           "limitations": ["Automatic contacts and endpoints require visual review.",
                                           "Hold duration does not infer thinking or intent.",
                                           "Unknown intervals cannot contribute to longest hold."]}}


def build_replay_summary(result: dict, review: dict | None = None) -> dict:
    """Summarize evidence without mutation, model calls, or file access.

    Review keys are ``timing``, replacement ``contacts``, ``uncertainties``, and
    optional replacement ``phase_reviews``. Contacts use ``limb``, ``hold_id``,
    ``start_seconds``, ``end_seconds``. Phases use the same time keys plus ``kind``
    and a four-limb ``contacts`` map. Null contact means reviewed non-contact;
    ``"unknown"`` means insufficient evidence. Phase review gaps remain unknown.
    Counts always come from contacts, not phase splits. A reviewed result retains
    ``automatic_summary`` and the exact ``review`` in ``provenance`` for audit.
    """
    summary = _build(result, review)
    if review is not None:
        summary["automatic_summary"] = _build(result, None)
        summary["provenance"]["review"] = deepcopy(review)
    return summary
