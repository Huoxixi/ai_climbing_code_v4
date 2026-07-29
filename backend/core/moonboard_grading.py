"""MoonBoard Font-grade contract and deterministic transfer inference.

The source dataset remains authoritative for real MoonBoard routes.  The
transfer model estimates an equivalent Font grade for the custom 11x18, 40°
board and never rewrites a source route's original grade.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


FONT_GRADES = (
    "6B",
    "6B+",
    "6C",
    "6C+",
    "7A",
    "7A+",
    "7B",
    "7B+",
    "7C",
    "7C+",
    "8A",
    "8A+",
    "8B",
    "8B+",
)
DEFAULT_FONT_GRADE = "6B+"
UNGRADED = "未定级"
BELOW_RANGE = "低于 6B"
ABOVE_RANGE = "高于 8B+"
BOUNDARY_LABELS = {BELOW_RANGE, ABOVE_RANGE}
GRADE_SYSTEM = "font"
MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "moonboard_grade_model.json"
SPARSE_GRADES = {"6B", "8A+", "8B", "8B+"}
SUPPORTED_COLUMNS = 11
SUPPORTED_ROWS = 18
SUPPORTED_ANGLE = 40


def normalize_font_grade(value: Any, *, allow_ungraded: bool = False) -> Optional[str]:
    normalized = str(value or "").strip().upper()
    if normalized in FONT_GRADES:
        return normalized
    if allow_ungraded and normalized in {"", UNGRADED}:
        return UNGRADED
    return None


def require_font_grade(value: Any) -> str:
    grade = normalize_font_grade(value)
    if not grade:
        raise ValueError(f"难度必须是 {FONT_GRADES[0]}–{FONT_GRADES[-1]} 的 Font 等级")
    return grade


def grade_number(value: Any, *, default: str = DEFAULT_FONT_GRADE) -> int:
    grade = normalize_font_grade(value) or default
    return FONT_GRADES.index(grade)


def grade_delta(predicted: Any, target: Any) -> int:
    return grade_number(predicted) - grade_number(target)


def grade_from_number(value: float) -> str:
    index = max(0, min(len(FONT_GRADES) - 1, int(round(value))))
    return FONT_GRADES[index]


def grade_boundary_label(value: float) -> str:
    if value < 0:
        return BELOW_RANGE
    if value > len(FONT_GRADES) - 1:
        return ABOVE_RANGE
    return grade_from_number(value)


def font_grade_tag(value: Any) -> str:
    grade = normalize_font_grade(value)
    if not grade:
        return "difficulty:ungraded"
    return f"difficulty:{grade.lower().replace('+', '-plus')}"


def hold_transfer_demand(hold_type: Any, rotation: Any, profile: Any = None) -> float:
    """Combine hold type, quality, capacity, and direction into one demand."""

    base_by_type = {
        "Jug": 18.0,
        "Pinch": 52.0,
        "Sloper": 62.0,
        "Crimp": 72.0,
        "Pocket": 82.0,
        "Foot": 50.0,
    }
    normalized_type = getattr(hold_type, "value", hold_type)
    demand = base_by_type.get(str(normalized_type), 55.0)
    if profile is None:
        return demand

    getter = profile.get if isinstance(profile, Mapping) else lambda key, default=None: getattr(profile, key, default)
    quality = float(getter("quality", 3) or 3)
    capacity = float(getter("capacity", 0.7) or 0.7)
    preferred = float(getter("preferred_direction_degrees", 180) or 180)
    tolerance = float(getter("direction_tolerance_degrees", 90) or 90)
    actual = float(rotation or 0) % 360
    direction_gap = abs((actual - preferred + 180) % 360 - 180)

    demand += (3.0 - quality) * 6.0
    demand += (0.8 - capacity) * 15.0
    if direction_gap > tolerance:
        demand += min(10.0, (direction_gap - tolerance) / max(1.0, 180.0 - tolerance) * 10.0)
    return round(max(0.0, min(100.0, demand)), 2)


def board_is_calibrated(spec: Any) -> bool:
    if spec is None:
        return False
    getter = spec.get if isinstance(spec, Mapping) else lambda key, default=None: getattr(spec, key, default)
    columns = int(getter("columns", getter("cols", 0)) or 0)
    rows = int(getter("rows", 0) or 0)
    angle = int(round(float(getter("angle_degrees", 0) or 0)))
    return columns == SUPPORTED_COLUMNS and rows == SUPPORTED_ROWS and angle == SUPPORTED_ANGLE


def _coord_parts(coord_id: str) -> tuple[int, int]:
    return ord(coord_id[0].upper()) - ord("A"), int(coord_id[1:])


def route_feature_vector(roles: Mapping[str, Sequence[str]]) -> list[float]:
    """Return the fixed 612-value feature vector used by the model artifact."""

    vector = [0.0] * (198 * 3 + 18)
    normalized_roles: dict[str, list[tuple[int, int]]] = {}
    for role_index, role in enumerate(("start", "mid", "end")):
        coords: list[tuple[int, int]] = []
        for raw_coord in roles.get(role, []):
            try:
                x_index, y_index = _coord_parts(str(raw_coord))
            except (IndexError, TypeError, ValueError):
                continue
            if not 0 <= x_index < 11 or not 1 <= y_index <= 18:
                continue
            coords.append((x_index, y_index))
            vector[role_index * 198 + (y_index - 1) * 11 + x_index] = 1.0
        normalized_roles[role] = list(dict.fromkeys(coords))

    points = sorted(
        set(normalized_roles["start"] + normalized_roles["mid"] + normalized_roles["end"]),
        key=lambda item: (item[1], item[0]),
    )
    sequence: list[tuple[int, int]] = []
    for role in ("start", "mid", "end"):
        sequence.extend(sorted(normalized_roles[role], key=lambda item: (item[1], item[0])))
    sequence = list(dict.fromkeys(sequence))

    x_values = [point[0] for point in points] or [0]
    y_values = [point[1] for point in points] or [0]
    moves = [
        (current[0] - previous[0], current[1] - previous[1])
        for previous, current in zip(sequence, sequence[1:])
    ]
    dx_values = [move[0] for move in moves] or [0]
    dy_values = [move[1] for move in moves] or [0]
    distances = [math.hypot(dx, dy) for dx, dy in moves] or [0.0]

    def mean(values: Sequence[float]) -> float:
        return sum(values) / max(1, len(values))

    def std(values: Sequence[float]) -> float:
        average = mean(values)
        return math.sqrt(mean([(value - average) ** 2 for value in values]))

    compact = [
        float(len(points)),
        float(len(normalized_roles["start"])),
        float(len(normalized_roles["mid"])),
        float(len(normalized_roles["end"])),
        float(max(x_values) - min(x_values)),
        float(max(y_values) - min(y_values)),
        mean(x_values),
        mean(y_values),
        std(x_values),
        std(y_values),
        mean([abs(value) for value in dx_values]),
        mean([abs(value) for value in dy_values]),
        mean(distances),
        max(distances),
        mean([1.0 if abs(value) > 3 else 0.0 for value in dx_values]),
        mean([1.0 if value > 4 else 0.0 for value in dy_values]),
        float(sum(1 for previous, current in zip(dx_values, dx_values[1:]) if previous * current < 0)),
        float(min(y_values)),
    ]
    vector[-18:] = compact
    return vector


@lru_cache(maxsize=1)
def load_grade_model() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        return {
            "version": "missing",
            "coefficients": [],
            "feature_mean": [0.0] * 18,
            "feature_std": [1.0] * 18,
            "metrics": {},
            "sample_counts": {},
            "calibration_ready": False,
        }
    try:
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "version": "invalid",
            "coefficients": [],
            "feature_mean": [0.0] * 18,
            "feature_std": [1.0] * 18,
            "metrics": {},
            "sample_counts": {},
            "calibration_ready": False,
        }
    return model


def _model_score(roles: Mapping[str, Sequence[str]]) -> Optional[float]:
    model = load_grade_model()
    coefficients = model.get("coefficients") or []
    if len(coefficients) != 613:
        return None
    features = route_feature_vector(roles)
    means = model.get("feature_mean") or [0.0] * 18
    stds = model.get("feature_std") or [1.0] * 18
    for index in range(18):
        std = float(stds[index] or 1.0)
        features[-18 + index] = (features[-18 + index] - float(means[index])) / std
    return sum(float(value) * float(weight) for value, weight in zip(features, coefficients[:-1])) + float(coefficients[-1])


def assess_source_route(
    roles: Mapping[str, Sequence[str]],
    source_grade: str,
    *,
    beta_complete: bool = False,
) -> dict[str, Any]:
    """Assess model agreement without replacing an authoritative source grade."""

    grade = require_font_grade(source_grade)
    model = load_grade_model()
    raw_score = _model_score(roles)
    if raw_score is None:
        return {
            "predicted_grade": None,
            "grade_delta": None,
            "difficulty_confidence": 0.0,
            "confidence_tier": "low",
            "calibration_status": "calibrating",
        }
    predicted = grade_boundary_label(raw_score)
    delta = int(round(raw_score)) - grade_number(grade)
    count = int((model.get("sample_counts") or {}).get(grade, 0))
    confidence = 0.82 if model.get("calibration_ready") else 0.42
    if beta_complete:
        confidence += 0.04
    if abs(delta) >= 3:
        confidence = min(confidence, 0.64)
    if predicted in BOUNDARY_LABELS:
        confidence = min(confidence, 0.35)
    if grade in SPARSE_GRADES or count < 100:
        confidence = min(confidence, 0.44)
    confidence = round(min(0.9, confidence), 2)
    tier = "high" if confidence >= 0.75 and model.get("calibration_ready") else ("medium" if confidence >= 0.5 else "low")
    return {
        "predicted_grade": predicted,
        "grade_delta": delta,
        "difficulty_confidence": confidence,
        "confidence_tier": tier,
        "calibration_status": "ready" if model.get("calibration_ready") else "calibrating",
    }


def _hold_adjustment(hold_demands: Iterable[float]) -> int:
    values = [float(value) for value in hold_demands]
    if not values:
        return 0
    average = sum(values) / len(values)
    if average >= 70.0:
        return 1
    if average <= 35.0:
        return -1
    return 0


def assess_equivalent_grade(
    roles: Mapping[str, Sequence[str]],
    *,
    board_spec: Any,
    hold_demands: Iterable[float] = (),
    hold_confidences: Iterable[float] = (),
    beta_complete: bool = False,
) -> dict[str, Any]:
    if not board_is_calibrated(board_spec):
        return {
            "predicted_grade": None,
            "grade_system": GRADE_SYSTEM,
            "grade_origin": "ungraded",
            "difficulty_confidence": 0.0,
            "confidence_tier": "low",
            "calibration_status": "uncalibrated",
            "difficulty_reasons": ["仅 11×18、40° 岩板支持 MoonBoard 等效难度"],
        }

    model = load_grade_model()
    raw_score = _model_score(roles)
    if raw_score is None:
        return {
            "predicted_grade": None,
            "grade_system": GRADE_SYSTEM,
            "grade_origin": "transferred",
            "difficulty_confidence": 0.0,
            "confidence_tier": "low",
            "calibration_status": "calibrating",
            "difficulty_reasons": ["难度校准文件缺失或无效"],
        }

    adjusted_score = raw_score + _hold_adjustment(hold_demands)
    grade = grade_boundary_label(adjusted_score)
    sample_count = int((model.get("sample_counts") or {}).get(grade, 0))
    calibration_ready = bool(model.get("calibration_ready"))
    confidence = 0.78 if calibration_ready else 0.42
    reasons = ["按真实 MoonBoard 线路的坐标与动作结构校准"]

    if beta_complete:
        confidence += 0.06
    else:
        confidence -= 0.12
        reasons.append("Beta 不完整，动作顺序可信度降低")

    hold_confidence_values = [float(value) for value in hold_confidences]
    if hold_confidence_values and min(hold_confidence_values) < 0.8:
        confidence = min(confidence, 0.64)
        reasons.append("线路使用了尚未完成人工复核的自有岩点")

    if grade in SPARSE_GRADES or sample_count < 100:
        confidence = min(confidence, 0.44)
        reasons.append(f"{grade} 参考样本较少")

    if grade in BOUNDARY_LABELS:
        confidence = min(confidence, 0.35)
        reasons.append("线路超出当前训练等级范围，不强行归入边界等级")

    confidence = round(max(0.0, min(0.92, confidence)), 2)
    if confidence >= 0.75 and calibration_ready:
        tier = "high"
    elif confidence >= 0.5:
        tier = "medium"
    else:
        tier = "low"
    status = "ready" if calibration_ready else "calibrating"
    if not calibration_ready:
        reasons.append("当前结果为试算，离线验证尚未达到正式发布门槛")

    return {
        "predicted_grade": grade,
        "grade_score": round(adjusted_score, 3),
        "grade_system": GRADE_SYSTEM,
        "grade_origin": "transferred",
        "difficulty_confidence": confidence,
        "confidence_tier": tier,
        "calibration_status": status,
        "difficulty_reasons": reasons,
    }


def feedback_band_is_eligible(
    records: Iterable[Mapping[str, Any]],
    target_grade: str,
    *,
    minimum_records: int = 10,
    minimum_profiles: int = 3,
) -> bool:
    """Return whether reviewed feedback can enter the next versioned rebuild.

    Pending/rejected feedback never affects runtime inference.  A grade band is
    eligible only after enough approved records cover at least three distinct
    body profiles.  This helper does not update model parameters by itself.
    """

    target = require_font_grade(target_grade)
    accepted: list[Mapping[str, Any]] = []
    profile_keys: set[str] = set()
    for record in records:
        if str(record.get("review_status") or "") != "approved":
            continue
        perceived = normalize_font_grade(record.get("perceived_grade"))
        if not perceived or abs(grade_delta(perceived, target)) > 1:
            continue
        accepted.append(record)
        profile_key = str(record.get("profile_id") or "").strip()
        if not profile_key:
            height = record.get("height_cm")
            arm_span = record.get("arm_span_cm")
            if height is not None or arm_span is not None:
                profile_key = f"body:{height or 'unknown'}:{arm_span or 'unknown'}"
        if profile_key:
            profile_keys.add(profile_key)
    return len(accepted) >= minimum_records and len(profile_keys) >= minimum_profiles
