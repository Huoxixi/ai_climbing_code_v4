"""Validate a source-time rhythm partition without changing its evidence.

Times have the replay summary's microsecond precision. No gap is filled and no
unknown phase is reclassified. Integer shares use largest remainders, with ties
resolved in the fixed order hold, transition, unknown.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP


KINDS = ("hold", "transition", "unknown")
PRECISION = Decimal("0.000001")


def _decimal(value, field):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def _time(value, field):
    try:
        return _decimal(value, field).quantize(PRECISION, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"{field} exceeds supported time precision") from None


def _check(existing, expected, field):
    if abs(_decimal(existing, field) - expected) > PRECISION:
        raise ValueError(f"{field} disagrees with source-time phases")


def _allocate(totals, elapsed, units):
    # Compare remainders without division, preserving exact ties even where the
    # corresponding decimal share repeats. A unit is 1% or 0.1% at the call site.
    numerators = {kind: totals[kind] * units for kind in KINDS}
    allocated = {kind: int((numerators[kind] / elapsed).to_integral_value(rounding=ROUND_FLOOR))
                 for kind in KINDS}
    ranked = sorted(KINDS, key=lambda kind: (-(numerators[kind] - allocated[kind] * elapsed),
                                            KINDS.index(kind)))
    for kind in ranked[:units - sum(allocated.values())]:
        allocated[kind] += 1
    return allocated


def rhythm_data(summary: dict) -> dict:
    """Return segments, totals, integer shares, and one-decimal display shares.

    Requires a finite, positive ``timing.start_seconds/end_seconds`` interval.
    Phases are sorted by original timestamps and clipped to that interval. Their
    intersection must cover it exactly, without gaps or overlaps. Any provided
    elapsed time, phase duration, or relevant coverage metric must agree within
    one microsecond (one millionth for the coverage fraction).

    The function raises ValueError on inconsistent input and never edits summary.
    It does not infer actual climb boundaries from observation-only timing.
    """
    timing = summary.get("timing") or {}
    start = _time(timing.get("start_seconds"), "timing.start_seconds")
    end = _time(timing.get("end_seconds"), "timing.end_seconds")
    if start < 0 or end <= start:
        raise ValueError("timing must be a positive source-time interval")
    elapsed = end - start
    if "elapsed_seconds" in timing:
        _check(timing["elapsed_seconds"], elapsed, "timing.elapsed_seconds")

    rows = []
    for index, phase in enumerate(summary.get("phases") or []):
        prefix = f"phases[{index}]"
        left = _time(phase.get("start_seconds"), f"{prefix}.start_seconds")
        right = _time(phase.get("end_seconds"), f"{prefix}.end_seconds")
        if right <= left:
            raise ValueError(f"{prefix} must have positive duration")
        kind = phase.get("kind")
        if kind not in KINDS:
            raise ValueError(f"{prefix}.kind must be hold, transition, or unknown")
        if "duration_seconds" in phase:
            _check(phase["duration_seconds"], right - left, f"{prefix}.duration_seconds")
        left, right = max(start, left), min(end, right)
        if right > left:
            rows.append((left, right, kind))
    rows.sort(key=lambda row: (row[0], row[1]))

    cursor = start
    totals = dict.fromkeys(KINDS, Decimal(0))
    segments = []
    for left, right, kind in rows:
        if left < cursor:
            raise ValueError("phases overlap inside timing interval")
        if left > cursor:
            raise ValueError("phases leave a gap inside timing interval")
        duration = right - left
        totals[kind] += duration
        segments.append({"start_seconds": float(left), "end_seconds": float(right),
                         "duration_seconds": float(duration), "kind": kind})
        cursor = right
    if cursor != end:
        raise ValueError("phases do not cover the complete timing interval")
    if sum(totals.values()) != elapsed:
        raise ValueError("phase totals do not equal elapsed time")

    coverage = summary.get("coverage") or {}
    expected_coverage = {"start_seconds": start, "end_seconds": end,
                         "duration_seconds": elapsed,
                         **{f"{kind}_seconds": totals[kind] for kind in KINDS},
                         "known_fraction": (totals["hold"] + totals["transition"]) / elapsed}
    for field, expected in expected_coverage.items():
        if field in coverage:
            _check(coverage[field], expected, f"coverage.{field}")

    percentages = _allocate(totals, elapsed, 100)
    display_units = _allocate(totals, elapsed, 1000)
    return {"segments": segments, "totals": {kind: float(totals[kind]) for kind in KINDS},
            "percentages": percentages,
            "display_percentages": {kind: display_units[kind] / 10 for kind in KINDS},
            "start_seconds": float(start),
            "end_seconds": float(end), "elapsed_seconds": float(elapsed)}
