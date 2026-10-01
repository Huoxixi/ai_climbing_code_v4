"""Pure source-time mapping for piecewise slow motion and one optional freeze.

Presentation time never becomes evidence time. Source sections are contiguous,
and rates up to 1 preserve source frames when source and output share a frame
rate. The module does not read media or modify the supplied shot.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


_EPSILON = 1e-7


def _finite(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


@dataclass(frozen=True)
class _Section:
    source_start: float
    source_end: float
    rate: float
    clock_start: float
    clock_end: float


@dataclass(frozen=True)
class _Playback:
    source_start: float
    source_end: float
    sections: tuple[_Section, ...]
    moving_duration: float
    freeze_source: float | None
    freeze_start: float
    freeze_duration: float


def _read(shot: dict) -> _Playback:
    start = _finite(shot.get("source_start_seconds"), "source_start_seconds")
    end = _finite(shot.get("source_end_seconds"), "source_end_seconds")
    if not 0 <= start <= end:
        raise ValueError("Source interval must be nonnegative and ordered")

    if "playback_sections" in shot:
        rows = shot["playback_sections"]
        if not isinstance(rows, list):
            raise ValueError("playback_sections must be a list")
        if not rows and start != end:
            raise ValueError("Playback sections must cover the complete source interval")
    else:
        rate = _finite(shot.get("playback_rate", 1), "playback_rate")
        if not 0 < rate <= 1:
            raise ValueError("Playback rate must be greater than zero and at most one")
        rows = [] if start == end else [{"source_start_seconds": start,
                                        "source_end_seconds": end, "playback_rate": rate}]
    if start == end and rows:
        raise ValueError("Static source intervals do not need moving sections")

    source_cursor, clock_cursor = start, 0.
    sections = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Each playback section must be an object")
        left = _finite(row.get("source_start_seconds"), "section source_start_seconds")
        right = _finite(row.get("source_end_seconds"), "section source_end_seconds")
        rate = _finite(row.get("playback_rate"), "section playback_rate")
        if not 0 < rate <= 1:
            raise ValueError("Playback rate must be greater than zero and at most one")
        if (abs(left - source_cursor) > _EPSILON or right <= left
                or right > end + _EPSILON):
            raise ValueError("Playback sections must be ordered, contiguous and inside the source interval")
        # Remove only floating-point roundoff, never a source gap or overlap.
        left = source_cursor
        if index == len(rows) - 1 and abs(right - end) <= _EPSILON:
            right = end
        if right <= left:
            raise ValueError("Playback sections must have positive source duration")
        finish = clock_cursor + (right - left) / rate
        if not math.isfinite(finish):
            raise ValueError("Playback duration must remain finite")
        sections.append(_Section(left, right, rate, clock_cursor, finish))
        source_cursor, clock_cursor = right, finish
    if abs(source_cursor - end) > _EPSILON:
        raise ValueError("Playback sections must cover the complete source interval")

    freeze_source, freeze_start, freeze_duration = None, 0., 0.
    if "freeze_at" in shot or "freeze_duration" in shot:
        if "freeze_at" not in shot or "freeze_duration" not in shot:
            raise ValueError("freeze_at and freeze_duration must be supplied together")
        freeze_source = _finite(shot["freeze_at"], "freeze_at")
        freeze_duration = _finite(shot["freeze_duration"], "freeze_duration")
        if not start < freeze_source < end or freeze_duration <= 0:
            raise ValueError("A positive freeze must be strictly inside the source interval")
        section = next(part for part in sections if part.source_start <= freeze_source <= part.source_end)
        freeze_start = section.clock_start + (freeze_source - section.source_start) / section.rate
    if not math.isfinite(clock_cursor + freeze_duration):
        raise ValueError("Playback duration must remain finite")
    return _Playback(start, end, tuple(sections), clock_cursor,
                     freeze_source, freeze_start, freeze_duration)


def validate_playback(shot: dict) -> None:
    """Reject gaps, overlaps, invalid rates and out-of-range freezes."""
    _read(shot)


def playback_duration(shot: dict) -> float:
    """Minimum time to show all source motion and its explicit freeze.

    A static source interval returns zero; its presentation dwell remains the
    caller's ``duration_seconds``. Additional end-frame dwell is not motion time.
    """
    playback = _read(shot)
    return playback.moving_duration + playback.freeze_duration


def playback_state(shot: dict, local: float) -> tuple[float, bool, float]:
    """Return source seconds, frozen state and effective playback rate.

    Rate is zero while explicitly frozen, after reaching the source end, and
    for a static shot. Negative local time clamps to the source start. Section
    boundaries use the following section's rate without skipping source time.
    """
    playback = _read(shot)
    clock = max(0., _finite(local, "local presentation time"))
    if playback.source_start == playback.source_end:
        return playback.source_end, True, 0.
    if playback.freeze_source is not None:
        stop = playback.freeze_start + playback.freeze_duration
        if playback.freeze_start <= clock < stop:
            return playback.freeze_source, True, 0.
        if clock >= stop:
            # Anchor resume to the exact motion clock of the freeze. Subtracting
            # duration directly can round just below a section boundary and
            # incorrectly report the previous section's rate on the resume frame.
            clock = playback.freeze_start + (clock - stop)
    if clock >= playback.moving_duration:
        return playback.source_end, True, 0.
    for section in playback.sections:
        if clock < section.clock_end:
            source = section.source_start + (clock - section.clock_start) * section.rate
            return min(section.source_end, max(section.source_start, source)), False, section.rate
    return playback.source_end, True, 0.
