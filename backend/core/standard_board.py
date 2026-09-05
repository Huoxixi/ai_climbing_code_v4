"""Standard route library data services.

The module models a generic 11x18 fixed-hold training board. Route data is an
overlay that highlights a subset of the fixed setup; it is not hardware control.
"""

from __future__ import annotations

import json
import math
import pickle
import random
import os
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

from core.hold_image_processing import resolve_local_hold_image_url
from core.moonboard_grading import (
    DEFAULT_FONT_GRADE,
    FONT_GRADES,
    assess_source_route,
    font_grade_tag,
    grade_from_number,
    grade_number,
    load_grade_model,
    normalize_font_grade,
)
from core.models import (
    BetaStep,
    BoardAsset,
    BoardSpec,
    Hold,
    HoldType,
    Limb,
    RouteOverlayPoint,
    StandardBoardRepairCandidate,
    StandardBoardRepairComparison,
    StandardBoardRepairPublishResponse,
    StandardBoardRepairPublishSkipped,
    StandardBoardRepairQueryResponse,
    StandardBoardRouteDetail,
    StandardBoardRouteFeatures,
    StandardBoardRouteQueryResponse,
    StandardBoardRouteSummary,
    VirtualLedPoint,
)


BOARD_COLUMNS = 11
BOARD_ROWS = 18
X_LABELS = [chr(ord("A") + index) for index in range(BOARD_COLUMNS)]
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATASET_PATH = DATA_DIR / "raw_datasets" / "moonGen_scrape_2016_final"
HOLDS_MAPPING_PATH = DATA_DIR / "holds_mapping.json"
HOLDS_VECTORS_PATH = DATA_DIR / "holds_vectors.json"
HOLDS_IMAGES_PATH = DATA_DIR / "holds_images"
PROCESSED_HOLDS_IMAGES_PATH = DATA_DIR / "holds_images_processed"
REVIEW_QUEUE_PATH = DATA_DIR / "standard_board_review_queue.json"
ACCEPTED_REPAIRS_PATH = DATA_DIR / "standard_board_accepted_repairs.json"
SETUP_SCALE = 0.78
STANDARD_BOARD_VARIANT_KEYS = frozenset(
    {
        ("Jug", "Jug classic 1"),
        ("Jug", "Jug classic 2"),
        ("Jug", "Jug classic 3"),
        ("Crimp", "Crimp classic1"),
        ("Crimp", "Crimp classic2"),
        ("Crimp", "Crimp classic3"),
        ("Foot", "Foot classic 1"),
        ("Foot", "Foot classic 2"),
    }
)

FONT_GRADE_ORDER = list(FONT_GRADES)
HOLD_DIFFICULTY = {
    HoldType.JUG: 18.0,
    HoldType.PINCH: 52.0,
    HoldType.SLOPER: 62.0,
    HoldType.CRIMP: 72.0,
    HoldType.POCKET: 82.0,
    HoldType.FOOT: 50.0,
}

ROLE_COLORS = {
    "start": "#22c55e",
    "start_hand": "#22c55e",
    "start_foot": "#3b82f6",
    "mid": "#f59e0b",
    "end": "#ef4444",
}

TAG_COMPONENT_MAXIMA = {
    "move_distance": 20.0,
    "hold_demand": 20.0,
    "foot_demand": 15.0,
    "sequence_complexity": 10.0,
    "start_finish_pressure": 15.0,
}
TAG_COMPONENT_IDS = {
    "move_distance": "style:big-span",
    "hold_demand": "style:small-hold-strength",
    "foot_demand": "style:technical-footwork",
    "sequence_complexity": "style:sustained",
    "start_finish_pressure": "style:crux-start-finish",
}
TAG_THRESHOLD = 0.65


def _repaired_source_id(source_id: str) -> str:
    return f"repaired-{source_id}"


def _original_source_id(source_id: str) -> str:
    return str(source_id).removeprefix("repaired-")


def _is_repaired_source_id(source_id: str) -> bool:
    return str(source_id).startswith("repaired-")


def _display_name(source_id: str, source_name: str = "") -> str:
    if _is_repaired_source_id(source_id):
        return f"{source_name or f'标准线路 {_original_source_id(source_id)}'}（修复版）"
    return source_name or f"标准线路 {source_id}"

FAILURE_MESSAGES = {
    "invalid_coords": "存在无效坐标",
    "start_hand_count_lt_2": "明确手起点少于 2 个",
    "start_marker_count_lt_3": "起攀标记少于 3 个",
    "end_count_lt_1": "终点少于 1 个",
    "end_below_y16": "终点低于 Y16",
    "hold_count_out_of_range": "岩点总数不在 6-12 个范围内",
    "start_above_y5": "起攀点高于 Y5",
    "ladder_x_span_too_narrow": "横向跨度过窄，接近梯子线",
    "vertical_gap_gt_5": "纵向相邻层级断档超过 5 格",
    "end_on_foot_hold": "终点不能是脚点",
    "no_start_foothold": "没有可用的起攀脚点",
}


@dataclass(frozen=True)
class NormalizedStandardRoute:
    source_id: str
    source_url: Optional[str]
    source_name: str
    setter_name: str
    grade: str
    is_benchmark: bool
    repeats: int
    roles: Dict[Literal["start", "mid", "end"], List[str]]
    score: float
    quality_score: Optional[float]
    quality_tier: str
    score_breakdown: Dict[str, float]
    marker_summary: Dict[str, Any]
    review_reasons: List[str]
    difficulty_score: Optional[float]
    predicted_grade: Optional[str]
    grade_delta: Optional[int]
    difficulty_confidence: Optional[float]
    difficulty_breakdown: Dict[str, float]
    difficulty_reasons: List[str]
    grade_warning: str
    confidence_tier: str
    calibration_status: str
    features: StandardBoardRouteFeatures
    valid_for_climb: bool
    validation: Dict[str, Any]


def route_tags(route: NormalizedStandardRoute) -> List[str]:
    """Create stable route tags from the route's existing scoring evidence."""
    tags = [font_grade_tag(route.grade), f"quality:{route.quality_tier}"]
    for component, maximum in TAG_COMPONENT_MAXIMA.items():
        if route.difficulty_breakdown.get(component, 0.0) >= maximum * TAG_THRESHOLD:
            tags.append(TAG_COMPONENT_IDS[component])
    if route.is_benchmark:
        tags.append("trust:benchmark")
    if route.grade_warning != "none":
        tags.append("trust:needs-review")
    return tags


def _coord_to_label(coord: Iterable[Any]) -> Optional[str]:
    values = list(coord)
    if len(values) < 2:
        return None
    try:
        x_index = int(values[0])
        y_index = int(values[1])
    except (TypeError, ValueError):
        return None
    if not 0 <= x_index < BOARD_COLUMNS or not 1 <= y_index <= BOARD_ROWS:
        return None
    return f"{X_LABELS[x_index]}{y_index}"


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _parse_coords(raw_route: Dict[str, Any], role: Literal["start", "mid", "end"]) -> List[str]:
    labels = []
    for coord in raw_route.get(role) or []:
        label = _coord_to_label(coord)
        if label:
            labels.append(label)
    return _dedupe_preserve_order(labels)


def _coord_parts(coord_id: str) -> tuple[str, int]:
    return coord_id[0], int(coord_id[1:])


def _coord_exists(coord_id: str) -> bool:
    try:
        x_label, y_index = _coord_parts(coord_id)
    except (IndexError, ValueError):
        return False
    return x_label in X_LABELS and 1 <= y_index <= BOARD_ROWS


def _feature_snapshot(roles: Dict[Literal["start", "mid", "end"], List[str]]) -> StandardBoardRouteFeatures:
    coords = _dedupe_preserve_order(roles["start"] + roles["mid"] + roles["end"])
    x_values = [ord(coord[0]) - ord("A") for coord in coords]
    y_values = [int(coord[1:]) for coord in coords]
    return StandardBoardRouteFeatures(
        hold_count=len(coords),
        x_span=(max(x_values) - min(x_values) + 1) if x_values else 0,
        y_span=(max(y_values) - min(y_values) + 1) if y_values else 0,
        min_y=min(y_values) if y_values else 0,
        max_y=max(y_values) if y_values else 0,
        start_count=len(roles["start"]),
        mid_count=len(roles["mid"]),
        end_count=len(roles["end"]),
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _source_name(source_id: str, source_url: Optional[str]) -> str:
    slug = str(source_url or "").rstrip("/").rsplit("/", 1)[-1]
    if not slug or slug == str(source_id):
        return f"标准线路 {source_id}"
    return " ".join(word.capitalize() for word in slug.replace("_", "-").split("-") if word)


def _setter_name(raw_route: Dict[str, Any]) -> str:
    setter = raw_route.get("setter")
    if isinstance(setter, dict):
        return str(setter.get("Nickname") or f"{setter.get('Firstname', '')} {setter.get('Lastname', '')}").strip() or "未知定线者"
    return str(setter or raw_route.get("setter_name") or "未知定线者")


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _normalize_hold_type(value: Any) -> HoldType:
    normalized = str(value or "Jug").strip().capitalize()
    for hold_type in HoldType:
        if hold_type.value == normalized:
            return hold_type
    return HoldType.JUG


@lru_cache(maxsize=1)
def _recorded_hold_variants() -> List[Dict[str, Any]]:
    if not HOLDS_MAPPING_PATH.exists():
        return []
    with HOLDS_MAPPING_PATH.open("r", encoding="utf-8") as file:
        image_map = json.load(file)

    vector_map: Dict[str, Dict[str, str]] = {}
    if HOLDS_VECTORS_PATH.exists():
        with HOLDS_VECTORS_PATH.open("r", encoding="utf-8") as file:
            vector_map = json.load(file)

    variants: List[Dict[str, Any]] = []
    for hold_type, typed_variants in image_map.items():
        normalized_type = _normalize_hold_type(hold_type)
        for variant, image_url in typed_variants.items():
            if variant == "default":
                continue
            if (hold_type, variant) not in STANDARD_BOARD_VARIANT_KEYS:
                continue
            variants.append(
                {
                    "index": len(variants),
                    "hold_type": normalized_type,
                    "variant": variant,
                    "imageUrl": resolve_local_hold_image_url(
                        str(image_url),
                        HOLDS_IMAGES_PATH,
                        PROCESSED_HOLDS_IMAGES_PATH,
                    ),
                    "svgPath": vector_map.get(hold_type, {}).get(variant),
                }
            )
    return variants


def _variant_for_coord(x_index: int, y_index: int, hand_variants: List[Dict[str, Any]], foot_variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    use_low_foot = y_index <= 3 and (x_index + y_index) % 4 == 0
    if use_low_foot and foot_variants:
        return foot_variants[(x_index // 4 + y_index) % len(foot_variants)]
    return hand_variants[(x_index * 5 + y_index * 3) % len(hand_variants)]


def _rotation_for_coord(x_index: int, y_index: int, variant_index: int) -> int:
    return (x_index * 137 + y_index * 53 + variant_index * 29 + 17) % 360


@lru_cache(maxsize=1)
def load_board_setup() -> List[Hold]:
    variants = _recorded_hold_variants()
    hand_variants = [variant for variant in variants if variant["hold_type"] != HoldType.FOOT]
    foot_variants = [variant for variant in variants if variant["hold_type"] == HoldType.FOOT]
    if not hand_variants:
        return []

    setup: List[Hold] = []
    for y_index in range(1, BOARD_ROWS + 1):
        for x_index, x_label in enumerate(X_LABELS):
            coord_id = f"{x_label}{y_index}"
            variant = _variant_for_coord(x_index, y_index, hand_variants, foot_variants)
            hold_type = variant["hold_type"]
            setup.append(
                Hold(
                    id=coord_id,
                    x=x_label,
                    y=y_index,
                    hold_type=hold_type,
                    type=hold_type.value,
                    rotation=_rotation_for_coord(x_index, y_index, int(variant["index"])),
                    scale=SETUP_SCALE,
                    is_start=False,
                    variant=str(variant["variant"]),
                    imageUrl=variant.get("imageUrl"),
                    svgPath=variant.get("svgPath"),
                )
            )
    setup.sort(key=lambda hold: (hold.y, hold.x))
    return setup


@lru_cache(maxsize=1)
def _setup_map() -> Dict[str, Hold]:
    return {hold.id: hold for hold in load_board_setup()}


def _is_foot_hold(coord_id: str) -> bool:
    setup_hold = _setup_map().get(coord_id)
    return bool(setup_hold and setup_hold.hold_type == HoldType.FOOT)


def _coord_x_index(coord_id: str) -> int:
    return ord(coord_id[0]) - ord("A")


def _derive_start_feet(start_hands: List[str], existing_feet: List[str], occupied: set[str]) -> List[str]:
    if len(start_hands) < 2:
        return []

    max_needed = max(0, min(2 - len(existing_feet), 4 - len(start_hands) - len(existing_feet)))
    if max_needed <= 0:
        return []

    hand_center = sum(_coord_x_index(coord_id) for coord_id in start_hands) / len(start_hands)
    lowest_hand_y = min(int(coord_id[1:]) for coord_id in start_hands)
    candidates = []
    for coord_id, hold in _setup_map().items():
        if coord_id in occupied or hold.hold_type != HoldType.FOOT or hold.y > 5:
            continue
        x_distance = abs(_coord_x_index(coord_id) - hand_center)
        y_distance = abs(hold.y - max(1, lowest_hand_y - 2))
        candidates.append((x_distance * 2 + y_distance, hold.y, x_distance, coord_id))

    candidates.sort()
    return [coord_id for *_rest, coord_id in candidates[:max_needed]]


def _marker_snapshot(roles: Dict[Literal["start", "mid", "end"], List[str]]) -> Dict[str, Any]:
    start_coords = _dedupe_preserve_order(roles["start"])
    start_hands = [coord_id for coord_id in start_coords if _coord_exists(coord_id) and not _is_foot_hold(coord_id)]
    explicit_start_feet = [coord_id for coord_id in start_coords if _coord_exists(coord_id) and _is_foot_hold(coord_id)]
    occupied = set(roles["start"] + roles["mid"] + roles["end"])
    derived_start_feet = _derive_start_feet(start_hands, explicit_start_feet, occupied)
    start_feet = _dedupe_preserve_order(explicit_start_feet + derived_start_feet)
    start_markers = _dedupe_preserve_order(start_hands + start_feet)
    effective_roles = {
        "start": start_markers,
        "mid": list(roles["mid"]),
        "end": list(roles["end"]),
    }
    return {
        "start_hands": start_hands,
        "start_feets": start_feet,
        "start_feet": start_feet,
        "explicit_start_feet": explicit_start_feet,
        "derived_start_feet": derived_start_feet,
        "start_markers": start_markers,
        "end_holds": list(roles["end"]),
        "effective_roles": effective_roles,
        "counts": {
            "start_hands": len(start_hands),
            "start_feet": len(start_feet),
            "start_markers": len(start_markers),
            "derived_start_feet": len(derived_start_feet),
        },
    }


def _failure_message(code: str) -> str:
    base_code = code.split(":", 1)[0]
    return FAILURE_MESSAGES.get(base_code, code)


def _quality_tier(quality_score: Optional[float], valid_for_climb: bool) -> str:
    if not valid_for_climb or quality_score is None:
        return "rejected"
    if quality_score >= 85:
        return "excellent"
    if quality_score >= 70:
        return "good"
    if quality_score >= 55:
        return "climbable"
    return "review"


def _difficulty_number(font_grade: str) -> int:
    return grade_number(font_grade)


def _clamp_score(value: float, maximum: float) -> float:
    return round(max(0.0, min(maximum, value)), 2)


def _score_route_quality(
    font_grade: str,
    repeats: int,
    is_benchmark: bool,
    features: StandardBoardRouteFeatures,
    validation: Dict[str, Any],
) -> Dict[str, float]:
    checks = validation.get("checks", {})
    max_gap = float(checks.get("max_vertical_gap", 0))
    hold_count = features.hold_count
    grade_index = _difficulty_number(font_grade)

    rhythm = 12.0 * max(0.0, 1.0 - abs(hold_count - 8) / 5.0)
    vertical_flow = 10.0 * max(0.0, 1.0 - max(0.0, max_gap - 3.0) / 3.0)
    lateral_motion = 7.0 * min(1.0, features.x_span / 6.0)
    upward_coverage = 6.0 * min(1.0, features.y_span / 16.0)
    movement_quality = _clamp_score(rhythm + vertical_flow + lateral_motion + upward_coverage, 35.0)

    hold_comfort = 9.0 * max(0.0, 1.0 - abs(hold_count - 8) / 4.0)
    width_structure = 8.0 * min(1.0, max(0, features.x_span - 2) / 5.0)
    height_structure = 5.0 * min(1.0, features.y_span / 16.0)
    path_structure = 3.0 if features.mid_count >= 3 else 1.5
    climbable_structure = _clamp_score(hold_comfort + width_structure + height_structure + path_structure, 25.0)

    expected_holds = max(6.0, 10.0 - min(grade_index, 10) * 0.35)
    hold_match = 9.0 * max(0.0, 1.0 - abs(hold_count - expected_holds) / 5.0)
    expected_span = min(8.0, 3.0 + grade_index * 0.45)
    span_match = 6.0 * max(0.0, 1.0 - abs(features.x_span - expected_span) / 6.0)
    grade_shape = 5.0 * min(1.0, (features.y_span + features.x_span) / (15.0 + grade_index * 0.4))
    grade_confidence = _clamp_score(hold_match + span_match + grade_shape, 20.0)

    x_variety = 6.0 * min(1.0, features.x_span / 7.0)
    density = hold_count / max(1, features.y_span)
    density_score = 4.0 * max(0.0, 1.0 - abs(density - 0.55) / 0.45)
    mid_route_shape = 5.0 if features.mid_count >= 4 and features.x_span >= 4 else 2.5
    aesthetics = _clamp_score(x_variety + density_score + mid_route_shape, 15.0)

    data_bonus = 0.0
    if is_benchmark:
        data_bonus += 2.5
    data_bonus += min(2.5, repeats / 40.0)
    data_support = _clamp_score(data_bonus, 5.0)

    return {
        "movement_quality": movement_quality,
        "climbable_structure": climbable_structure,
        "grade_confidence": grade_confidence,
        "aesthetics": aesthetics,
        "data_support": data_support,
    }


def _coord_distance(a: str, b: str) -> float:
    ax = _coord_x_index(a)
    ay = int(a[1:])
    bx = _coord_x_index(b)
    by = int(b[1:])
    return math.hypot(ax - bx, (ay - by) * 1.15)


def _hold_difficulty(coord_id: str) -> tuple[float, bool]:
    setup_hold = _setup_map().get(coord_id)
    if not setup_hold:
        return 55.0, True
    return HOLD_DIFFICULTY.get(setup_hold.hold_type, 55.0), False


def _difficulty_hand_sequence(roles: Dict[Literal["start", "mid", "end"], List[str]], marker_summary: Dict[str, Any]) -> List[str]:
    start_hands = [coord_id for coord_id in marker_summary.get("start_hands", []) if _coord_exists(coord_id)]
    hand_mids = [coord_id for coord_id in roles["mid"] if _coord_exists(coord_id) and not _is_foot_hold(coord_id)]
    hand_ends = [coord_id for coord_id in roles["end"] if _coord_exists(coord_id) and not _is_foot_hold(coord_id)]
    hand_mids.sort(key=lambda coord_id: (int(coord_id[1:]), _coord_x_index(coord_id)))
    hand_ends.sort(key=lambda coord_id: (int(coord_id[1:]), _coord_x_index(coord_id)))
    return _dedupe_preserve_order(start_hands + hand_mids + hand_ends)


def _available_foot_holds(roles: Dict[Literal["start", "mid", "end"], List[str]], marker_summary: Dict[str, Any]) -> List[str]:
    explicit_feet = [coord_id for coord_id in marker_summary.get("start_feet", []) if _coord_exists(coord_id)]
    route_feet = [
        coord_id
        for coord_id in _dedupe_preserve_order(roles["start"] + roles["mid"] + roles["end"])
        if _coord_exists(coord_id) and _is_foot_hold(coord_id)
    ]
    return _dedupe_preserve_order(explicit_feet + route_feet)


def _foot_support_score(target: str, foot_holds: List[str]) -> float:
    if not foot_holds:
        return 78.0
    target_x = _coord_x_index(target)
    target_y = int(target[1:])
    usable = []
    for foot_id in foot_holds:
        foot_y = int(foot_id[1:])
        if foot_y > target_y + 1:
            continue
        x_gap = abs(_coord_x_index(foot_id) - target_x)
        y_gap = max(0, target_y - foot_y)
        usable.append((x_gap * 2.1 + y_gap * 0.8, x_gap, y_gap))
    if not usable:
        return 72.0
    support_cost, x_gap, y_gap = min(usable)
    return _clamp_score(18.0 + support_cost * 8.0 + max(0, x_gap - 3) * 6.0 + max(0, y_gap - 6) * 4.0, 100.0)


def _difficulty_grade_from_score(score: float) -> str:
    return grade_from_number(float(score) / 100.0 * (len(FONT_GRADES) - 1))


def _relabel_difficulty_with_grade(difficulty: Dict[str, Any], font_grade: str, predicted_grade: Optional[str]) -> Dict[str, Any]:
    next_difficulty = dict(difficulty)
    if not predicted_grade:
        next_difficulty.update({"predicted_grade": None, "grade_delta": None, "grade_warning": "uncertain"})
        return next_difficulty

    grade_delta = _difficulty_number(predicted_grade) - _difficulty_number(font_grade)
    confidence = float(next_difficulty.get("difficulty_confidence") or 0.5)

    next_difficulty.update(
        {
            "predicted_grade": predicted_grade,
            "grade_delta": grade_delta,
            "difficulty_confidence": confidence,
            "grade_warning": _difficulty_warning(grade_delta, confidence),
        }
    )
    return next_difficulty


def _build_difficulty_calibration(routes: List["NormalizedStandardRoute"]) -> None:
    # Kept as a compatibility hook.  The versioned offline artifact owns
    # calibration; loading routes must never retrain or mutate it.
    return None


def _apply_difficulty_calibration(routes: List["NormalizedStandardRoute"]) -> List["NormalizedStandardRoute"]:
    return routes


def _difficulty_warning(delta: int | None, confidence: float) -> str:
    if confidence < 0.45:
        return "uncertain"
    if delta is None:
        return "uncertain"
    distance = abs(delta)
    if distance >= 3:
        return "hard"
    if distance >= 2:
        return "soft"
    return "none"


def evaluate_route_difficulty(
    font_grade: str,
    repeats: int,
    is_benchmark: bool,
    roles: Dict[Literal["start", "mid", "end"], List[str]],
    marker_summary: Dict[str, Any],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    if not validation.get("valid_for_climb"):
        return {
            "difficulty_score": None,
            "predicted_grade": None,
            "grade_delta": None,
            "difficulty_confidence": None,
            "difficulty_breakdown": {},
            "difficulty_reasons": [],
            "grade_warning": "uncertain",
            "confidence_tier": "low",
            "calibration_status": "uncalibrated",
        }

    hand_sequence = _difficulty_hand_sequence(roles, marker_summary)
    foot_holds = _available_foot_holds(roles, marker_summary)
    unknown_holds = 0
    move_scores: List[float] = []
    distance_scores: List[float] = []
    hold_scores: List[float] = []
    foot_scores: List[float] = []
    body_scores: List[float] = []
    complexity_scores: List[float] = []
    direction_changes = 0
    previous_dx = 0

    for previous, current in zip(hand_sequence, hand_sequence[1:]):
        dx = _coord_x_index(current) - _coord_x_index(previous)
        dy = int(current[1:]) - int(previous[1:])
        distance = _coord_distance(previous, current)
        distance_score = _clamp_score(distance * 11.5 + max(0, abs(dx) - 4) * 5.0 + max(0, dy - 4) * 5.0, 100.0)
        hold_score, is_unknown = _hold_difficulty(current)
        unknown_holds += 1 if is_unknown else 0
        foot_score = _foot_support_score(current, foot_holds)
        body_score = _clamp_score(abs(dx) * 7.0 + max(0, dy - 3) * 7.0 + max(0, distance - 5.5) * 9.0 + foot_score * 0.22, 100.0)
        if previous_dx and dx and (previous_dx > 0) != (dx > 0):
            direction_changes += 1
        previous_dx = dx if dx else previous_dx
        complexity_score = _clamp_score(18.0 + direction_changes * 8.0 + max(0, abs(dx) - 3) * 4.0 + max(0, abs(dy) - 3) * 3.0, 100.0)
        move_score = distance_score * 0.32 + hold_score * 0.24 + foot_score * 0.18 + body_score * 0.18 + complexity_score * 0.08
        distance_scores.append(distance_score)
        hold_scores.append(hold_score)
        foot_scores.append(foot_score)
        body_scores.append(body_score)
        complexity_scores.append(complexity_score)
        move_scores.append(move_score)

    if not move_scores:
        return {
            "difficulty_score": 0.0,
            "predicted_grade": None,
            "grade_delta": None,
            "difficulty_confidence": 0.25,
            "difficulty_breakdown": {},
            "difficulty_reasons": ["可推断动作过少，难度可信度较低"],
            "grade_warning": "uncertain",
            "confidence_tier": "low",
            "calibration_status": "calibrating",
        }

    sorted_moves = sorted(move_scores, reverse=True)
    crux = sum(sorted_moves[:2]) / min(2, len(sorted_moves))
    hard_moves = [score for score in move_scores if score >= 55.0]
    sustained = (sum(sorted_moves[: max(1, math.ceil(len(sorted_moves) * 0.5))]) / max(1, math.ceil(len(sorted_moves) * 0.5)))
    average = sum(move_scores) / len(move_scores)
    start_pressure = move_scores[0]
    finish_pressure = move_scores[-1]
    pressure = max(start_pressure, finish_pressure)
    data_adjustment = min(5.0, (1.5 if is_benchmark else 0.0) + min(2.0, repeats / 80.0) + min(1.5, _difficulty_number(font_grade) * 0.15))
    difficulty_score = _clamp_score(crux * 0.45 + sustained * 0.25 + average * 0.15 + pressure * 0.10 + data_adjustment, 100.0)
    model_assessment = assess_source_route(roles, font_grade, beta_complete=len(move_scores) >= 4)
    predicted_grade = model_assessment["predicted_grade"]
    grade_delta = model_assessment["grade_delta"]

    unknown_ratio = unknown_holds / max(1, len(hand_sequence))
    confidence = float(model_assessment["difficulty_confidence"])
    if unknown_ratio > 0:
        confidence = round(max(0.2, confidence - unknown_ratio * 0.2), 2)

    reasons: List[str] = []
    if crux >= 72:
        reasons.append("存在明显 crux 动作")
    if max(distance_scores) >= 72:
        reasons.append("最大动作跨度偏大")
    if sum(1 for score in hold_scores if score >= 70) >= 2:
        reasons.append("连续小点或指力型岩点占比高")
    if max(foot_scores) >= 70:
        reasons.append("关键动作脚点支持弱")
    if max(body_scores) >= 70:
        reasons.append("横移或张力要求较高")
    if start_pressure >= 68:
        reasons.append("起步压力较高")
    if finish_pressure >= 68:
        reasons.append("终点前动作压力较高")
    if len(hard_moves) >= 3:
        reasons.append("难动作连续性较强")
    if not reasons:
        reasons.append("动作强度与结构分布较均衡")
    if unknown_ratio > 0:
        reasons.append("部分岩点类型缺失，难度可信度降低")

    return {
        "difficulty_score": difficulty_score,
        "predicted_grade": predicted_grade,
        "grade_delta": grade_delta,
        "difficulty_confidence": confidence,
        "difficulty_breakdown": {
            "move_distance": _clamp_score(sum(distance_scores) / len(distance_scores) * 0.20, 20.0),
            "hold_demand": _clamp_score(sum(hold_scores) / len(hold_scores) * 0.20, 20.0),
            "foot_demand": _clamp_score(sum(foot_scores) / len(foot_scores) * 0.15, 15.0),
            "body_tension": _clamp_score(sum(body_scores) / len(body_scores) * 0.15, 15.0),
            "sequence_complexity": _clamp_score(sum(complexity_scores) / len(complexity_scores) * 0.10, 10.0),
            "start_finish_pressure": _clamp_score(pressure * 0.15, 15.0),
            "data_adjustment": round(data_adjustment, 2),
        },
        "difficulty_reasons": reasons[:6],
        "grade_warning": _difficulty_warning(grade_delta, confidence),
        "confidence_tier": model_assessment["confidence_tier"],
        "calibration_status": model_assessment["calibration_status"],
    }


def validate_standard_roles(roles: Dict[Literal["start", "mid", "end"], List[str]]) -> Dict[str, Any]:
    marker_summary = _marker_snapshot(roles)
    effective_roles = marker_summary["effective_roles"]
    features = _feature_snapshot(effective_roles)
    coords = _dedupe_preserve_order(effective_roles["start"] + effective_roles["mid"] + effective_roles["end"])
    setup = _setup_map()
    failures: List[str] = []

    invalid_coords = [coord_id for coord_id in coords if coord_id not in setup]
    if invalid_coords:
        failures.append(f"invalid_coords:{','.join(invalid_coords[:5])}")

    if len(marker_summary["start_hands"]) < 2:
        failures.append("start_hand_count_lt_2")
    if len(marker_summary["start_markers"]) < 3:
        failures.append("start_marker_count_lt_3")
    if features.end_count < 1:
        failures.append("end_count_lt_1")
    if not 6 <= features.hold_count <= 12:
        failures.append("hold_count_out_of_range")

    start_y = [int(coord_id[1:]) for coord_id in effective_roles["start"] if _coord_exists(coord_id)]
    if any(y_index > 5 for y_index in start_y):
        failures.append("start_above_y5")

    end_y = [int(coord_id[1:]) for coord_id in effective_roles["end"] if _coord_exists(coord_id)]
    if not end_y or any(y_index < 16 for y_index in end_y):
        failures.append("end_below_y16")

    if features.x_span <= 2:
        failures.append("ladder_x_span_too_narrow")

    sorted_y = sorted({int(coord_id[1:]) for coord_id in coords if _coord_exists(coord_id)})
    max_gap = max((upper - lower for lower, upper in zip(sorted_y, sorted_y[1:])), default=0)
    if max_gap > 5:
        failures.append("vertical_gap_gt_5")

    if not marker_summary["start_feet"]:
        failures.append("no_start_foothold")

    end_foot_holds = [coord_id for coord_id in effective_roles["end"] if setup.get(coord_id, Hold(id=coord_id, x="A", y=1, hold_type=HoldType.FOOT)).hold_type == HoldType.FOOT]
    if end_foot_holds:
        failures.append("end_on_foot_hold")

    passed = not failures
    return {
        "passed": passed,
        "valid_for_climb": passed,
        "message": "standard-board validation passed" if passed else "standard-board validation failed",
        "failures": failures,
        "review_reasons": [_failure_message(code) for code in failures],
        "marker_summary": marker_summary,
        "effective_roles": effective_roles,
        "checks": {
            "start_count": features.start_count,
            "start_hand_count": len(marker_summary["start_hands"]),
            "start_foot_count": len(marker_summary["start_feet"]),
            "end_count": features.end_count,
            "hold_count": features.hold_count,
            "x_span": features.x_span,
            "max_vertical_gap": max_gap,
            "start_y_max": max(start_y) if start_y else 0,
            "end_y_min": min(end_y) if end_y else 0,
        },
    }


def _review_queue_entry(route: NormalizedStandardRoute) -> Dict[str, Any]:
    markers = route.marker_summary
    return {
        "source_id": route.source_id,
        "source_url": route.source_url,
        "grade": route.grade,
        "roles": route.roles,
        "marker_summary": {
            "start_hands": markers.get("start_hands", []),
            "start_feet": markers.get("start_feet", []),
            "derived_start_feet": markers.get("derived_start_feet", []),
            "counts": markers.get("counts", {}),
        },
        "failures": route.validation.get("failures", []),
        "review_reasons": route.review_reasons,
    }


def _write_review_queue(routes: List[NormalizedStandardRoute]) -> None:
    rejected = [route for route in routes if not route.valid_for_climb]
    payload = {
        "version": "1.0",
        "description": "Routes rejected by standard-board hard filters. They are held for later start-marker repair and manual review.",
        "total_rejected": len(rejected),
        "routes": [_review_queue_entry(route) for route in rejected],
    }
    try:
        if REVIEW_QUEUE_PATH.exists():
            with REVIEW_QUEUE_PATH.open("r", encoding="utf-8") as file:
                if json.load(file) == payload:
                    return
        _write_json_atomic(REVIEW_QUEUE_PATH, payload)
    except (OSError, json.JSONDecodeError):
        _write_json_atomic(REVIEW_QUEUE_PATH, payload)


def _normalize_route(source_id: str, raw_route: Dict[str, Any]) -> Optional[NormalizedStandardRoute]:
    grade = str(raw_route.get("grade") or raw_route.get("Grade") or "").upper()
    font_grade = normalize_font_grade(grade)
    if not font_grade:
        return None

    roles = {
        "start": _parse_coords(raw_route, "start"),
        "mid": _parse_coords(raw_route, "mid"),
        "end": _parse_coords(raw_route, "end"),
    }
    if _feature_snapshot(roles).hold_count <= 0:
        return None

    validation = validate_standard_roles(roles)
    effective_roles = validation["effective_roles"]
    features = _feature_snapshot(effective_roles)
    valid_for_climb = bool(validation.get("valid_for_climb"))
    repeats = _safe_int(raw_route.get("repeats"))
    is_benchmark = bool(raw_route.get("is_benchmark"))
    score_breakdown = _score_route_quality(font_grade, repeats, is_benchmark, features, validation) if valid_for_climb else {}
    quality_score = round(sum(score_breakdown.values()), 2) if valid_for_climb else None
    quality_tier = _quality_tier(quality_score, valid_for_climb)
    difficulty = evaluate_route_difficulty(font_grade, repeats, is_benchmark, effective_roles, validation["marker_summary"], validation)
    return NormalizedStandardRoute(
        source_id=str(source_id),
        source_url=raw_route.get("url"),
        source_name=_source_name(str(source_id), raw_route.get("url")),
        setter_name=_setter_name(raw_route),
        grade=grade,
        is_benchmark=is_benchmark,
        repeats=repeats,
        roles=effective_roles,
        score=quality_score or 0.0,
        quality_score=quality_score,
        quality_tier=quality_tier,
        score_breakdown=score_breakdown,
        marker_summary=validation["marker_summary"],
        review_reasons=validation.get("review_reasons", []),
        difficulty_score=difficulty["difficulty_score"],
        predicted_grade=difficulty["predicted_grade"],
        grade_delta=difficulty["grade_delta"],
        difficulty_confidence=difficulty["difficulty_confidence"],
        difficulty_breakdown=difficulty["difficulty_breakdown"],
        difficulty_reasons=difficulty["difficulty_reasons"],
        grade_warning=difficulty["grade_warning"],
        confidence_tier=difficulty["confidence_tier"],
        calibration_status=difficulty["calibration_status"],
        features=features,
        valid_for_climb=valid_for_climb,
        validation=validation,
    )


@lru_cache(maxsize=2)
def _load_standard_routes_cached(dataset_mtime_ns: int) -> List[NormalizedStandardRoute]:
    if not DATASET_PATH.exists():
        return []
    with DATASET_PATH.open("rb") as file:
        raw_data = pickle.load(file)
    if not isinstance(raw_data, dict):
        return []

    routes = [
        route
        for source_id, raw_route in raw_data.items()
        if isinstance(raw_route, dict)
        for route in [_normalize_route(str(source_id), raw_route)]
        if route is not None
    ]
    routes = _apply_difficulty_calibration(routes)
    _write_review_queue(routes)
    routes.sort(key=lambda route: route.score, reverse=True)
    return routes


def load_standard_routes() -> List[NormalizedStandardRoute]:
    if not DATASET_PATH.exists():
        return []
    return _load_standard_routes_cached(DATASET_PATH.stat().st_mtime_ns)


def _route_with_roles(
    route: NormalizedStandardRoute,
    roles: Dict[Literal["start", "mid", "end"], List[str]],
    source_id: Optional[str] = None,
    repeats: Optional[int] = None,
    is_benchmark: Optional[bool] = None,
) -> NormalizedStandardRoute:
    validation = validate_standard_roles(roles)
    resolved_roles = validation["effective_roles"]
    marker_summary = validation["marker_summary"]
    features = _feature_snapshot(resolved_roles)
    valid_for_climb = bool(validation.get("valid_for_climb"))
    route_repeats = route.repeats if repeats is None else repeats
    route_is_benchmark = route.is_benchmark if is_benchmark is None else is_benchmark
    score_breakdown = _score_route_quality(route.grade, route_repeats, route_is_benchmark, features, validation) if valid_for_climb else {}
    quality_score = round(sum(score_breakdown.values()), 2) if valid_for_climb else None
    difficulty = evaluate_route_difficulty(route.grade, route_repeats, route_is_benchmark, resolved_roles, marker_summary, validation)
    return NormalizedStandardRoute(
        source_id=source_id or route.source_id,
        source_url=route.source_url,
        source_name=route.source_name,
        setter_name=route.setter_name,
        grade=route.grade,
        is_benchmark=route_is_benchmark,
        repeats=route_repeats,
        roles=resolved_roles,
        score=quality_score or 0.0,
        quality_score=quality_score,
        quality_tier=_quality_tier(quality_score, valid_for_climb),
        score_breakdown=score_breakdown,
        marker_summary=marker_summary,
        review_reasons=validation.get("review_reasons", []),
        difficulty_score=difficulty["difficulty_score"],
        predicted_grade=difficulty["predicted_grade"],
        grade_delta=difficulty["grade_delta"],
        difficulty_confidence=difficulty["difficulty_confidence"],
        difficulty_breakdown=difficulty["difficulty_breakdown"],
        difficulty_reasons=difficulty["difficulty_reasons"],
        grade_warning=difficulty["grade_warning"],
        confidence_tier=difficulty["confidence_tier"],
        calibration_status=difficulty["calibration_status"],
        features=features,
        valid_for_climb=valid_for_climb,
        validation=validation,
    )


def _load_accepted_repair_records() -> List[Dict[str, Any]]:
    if not ACCEPTED_REPAIRS_PATH.exists():
        return []
    try:
        with ACCEPTED_REPAIRS_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        records = payload.get("routes", [])
    else:
        records = payload
    return records if isinstance(records, list) else []


def _write_accepted_repair_records(records: List[Dict[str, Any]]) -> None:
    _write_json_atomic(ACCEPTED_REPAIRS_PATH, {"routes": records})


def _accepted_repair_routes(base_routes: Optional[List[NormalizedStandardRoute]] = None) -> List[NormalizedStandardRoute]:
    routes = base_routes or list(load_standard_routes())
    base_by_id = {route.source_id: route for route in routes}
    accepted: List[NormalizedStandardRoute] = []
    for record in _load_accepted_repair_records():
        source_id = str(record.get("source_id") or "")
        base_route = base_by_id.get(source_id)
        repaired_roles = record.get("repaired_roles")
        if not source_id or not base_route or not isinstance(repaired_roles, dict):
            continue
        accepted_route = _route_with_roles(
            base_route,
            repaired_roles,
            source_id=_repaired_source_id(source_id),
            repeats=0,
            is_benchmark=False,
        )
        if accepted_route.valid_for_climb:
            accepted.append(accepted_route)
    return accepted


def summary_for(route: NormalizedStandardRoute) -> StandardBoardRouteSummary:
    return StandardBoardRouteSummary(
        source_id=route.source_id,
        display_name=_display_name(route.source_id, route.source_name),
        source_name=route.source_name,
        setter_name=route.setter_name,
        source_url=route.source_url,
        grade=route.grade,
        is_benchmark=route.is_benchmark,
        repeats=route.repeats,
        score=round(route.score, 2),
        quality_score=round(route.quality_score, 2) if route.quality_score is not None else None,
        quality_tier=route.quality_tier,
        score_breakdown=route.score_breakdown,
        marker_summary=route.marker_summary,
        review_reasons=route.review_reasons,
        difficulty_score=round(route.difficulty_score, 2) if route.difficulty_score is not None else None,
        predicted_grade=route.predicted_grade,
        grade_delta=route.grade_delta,
        difficulty_confidence=route.difficulty_confidence,
        difficulty_breakdown=route.difficulty_breakdown,
        difficulty_reasons=route.difficulty_reasons,
        grade_warning=route.grade_warning,
        confidence_tier=route.confidence_tier,
        calibration_status=route.calibration_status,
        tags=route_tags(route),
        features=route.features,
        valid_for_climb=route.valid_for_climb,
    )


def query_standard_routes(
    q: Optional[str] = None,
    difficulty: Optional[str] = None,
    predicted_grade: Optional[str] = None,
    grade_warning: Optional[str] = None,
    benchmark_only: bool = False,
    min_holds: Optional[int] = None,
    max_holds: Optional[int] = None,
    tag_ids: Optional[str] = None,
    tag_match: Literal["all", "any"] = "all",
    sort: str = "score_desc",
    limit: int = 24,
    offset: int = 0,
    valid_only: bool = True,
) -> StandardBoardRouteQueryResponse:
    routes = list(load_standard_routes())
    routes.extend(_accepted_repair_routes(routes))
    if valid_only:
        routes = [route for route in routes if route.valid_for_climb]
    if q and q.strip():
        needle = q.strip().casefold()
        routes = [
            route
            for route in routes
            if needle in route.source_id.casefold()
            or needle in route.source_name.casefold()
            or needle in route.setter_name.casefold()
        ]
    if difficulty:
        routes = [route for route in routes if route.grade == difficulty]
    if predicted_grade:
        routes = [route for route in routes if route.predicted_grade == predicted_grade]
    if grade_warning:
        routes = [route for route in routes if route.grade_warning == grade_warning]
    if benchmark_only:
        routes = [route for route in routes if route.is_benchmark]
    if min_holds is not None:
        routes = [route for route in routes if route.features.hold_count >= min_holds]
    if max_holds is not None:
        routes = [route for route in routes if route.features.hold_count <= max_holds]
    requested_tags = {tag.strip() for tag in (tag_ids or "").split(",") if tag.strip()}
    if requested_tags:
        if tag_match == "any":
            routes = [route for route in routes if requested_tags.intersection(route_tags(route))]
        else:
            routes = [route for route in routes if requested_tags.issubset(route_tags(route))]

    if sort == "repeats_desc":
        routes.sort(key=lambda route: (route.repeats, route.score), reverse=True)
    elif sort == "span_desc":
        routes.sort(key=lambda route: (route.features.x_span, route.features.y_span, route.score), reverse=True)
    elif sort == "holds_asc":
        routes.sort(key=lambda route: (route.features.hold_count, -route.score))
    elif sort == "difficulty_score_desc":
        routes.sort(key=lambda route: (route.difficulty_score or 0.0, route.score), reverse=True)
    elif sort == "difficulty_score_asc":
        routes.sort(key=lambda route: (route.difficulty_score or 0.0, -route.score))
    elif sort == "grade_mismatch_desc":
        routes.sort(key=lambda route: (abs(route.grade_delta or 0), route.difficulty_score or 0.0, route.score), reverse=True)
    else:
        routes.sort(key=lambda route: route.score, reverse=True)

    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    page = routes[bounded_offset : bounded_offset + bounded_limit]
    return StandardBoardRouteQueryResponse(
        total=len(routes),
        limit=bounded_limit,
        offset=bounded_offset,
        routes=[summary_for(route) for route in page],
    )


def find_standard_route(source_id: str) -> Optional[NormalizedStandardRoute]:
    routes = list(load_standard_routes())
    found = next((route for route in routes if route.source_id == source_id), None)
    if found:
        return found
    if _is_repaired_source_id(source_id):
        return next((route for route in _accepted_repair_routes(routes) if route.source_id == source_id), None)
    return None


def _board_spec() -> BoardSpec:
    return BoardSpec(
        preset_id="classic-11x18",
        template_key="spray-small",
        label="11×18 标准训练板",
        name="11×18 标准训练板",
        columns=BOARD_COLUMNS,
        cols=BOARD_COLUMNS,
        rows=BOARD_ROWS,
        hole_spacing_x_mm=200,
        hole_spacing_y_mm=200,
        board_width_mm=2440,
        board_height_mm=3660,
        grid_width_mm=2000,
        grid_height_mm=3400,
        margin_left_mm=220,
        margin_right_mm=220,
        margin_bottom_mm=130,
        margin_top_mm=130,
        angle_degrees=40,
        total_holes=BOARD_COLUMNS * BOARD_ROWS,
        unit="mm",
        reference_system="standard-board-derived",
        cellLabel="11 x 18",
        physicalLabel="2440 x 3660 mm",
        spacingLabel="200 x 200 mm",
        angleLabel="40°",
        material=None,
        skinClass=None,
        description="支持手工定线、完整性检查、AI 组合与审核。",
        width=2440,
        height=3660,
        xLabels=X_LABELS,
        yLabels=list(range(1, BOARD_ROWS + 1)),
    )


def _hold_for(coord_id: str, role: Literal["start", "mid", "end"]) -> Hold:
    setup_hold = _setup_map().get(coord_id)
    if setup_hold:
        return setup_hold.model_copy(update={"is_start": role == "start"})

    x_label, y_index = _coord_parts(coord_id)
    hold_type = HoldType.JUG if role in {"start", "end"} else HoldType.CRIMP
    return Hold(
        id=coord_id,
        x=x_label,
        y=y_index,
        hold_type=hold_type,
        type=hold_type.value,
        is_start=role == "start",
        variant=f"standard-{role}",
        rotation=0,
        scale=1.0,
    )


def _holds_for(roles: Dict[Literal["start", "mid", "end"], List[str]]) -> List[Hold]:
    holds: List[Hold] = []
    used: set[str] = set()
    for role in ("start", "mid", "end"):
        for coord_id in roles[role]:
            if coord_id in used:
                continue
            used.add(coord_id)
            holds.append(_hold_for(coord_id, role))
    return holds


def _beta_for(roles: Dict[Literal["start", "mid", "end"], List[str]], marker_summary: Dict[str, Any]) -> List[BetaStep]:
    steps: List[BetaStep] = []
    hand_cycle = [Limb.LH, Limb.RH]
    foot_cycle = [Limb.LF, Limb.RF]
    for index, coord_id in enumerate(marker_summary.get("start_hands", [])):
        steps.append(BetaStep(step=0, limb=hand_cycle[index % 2], hold_id=coord_id, intent="Start"))
    for index, coord_id in enumerate(marker_summary.get("start_feet", [])):
        steps.append(BetaStep(step=0, limb=foot_cycle[index % 2], hold_id=coord_id, intent="Start foot"))
    move_index = 1
    for coord_id in roles["mid"]:
        steps.append(BetaStep(step=move_index, limb=hand_cycle[move_index % 2], hold_id=coord_id, intent="Move"))
        move_index += 1
    for coord_id in roles["end"]:
        steps.append(BetaStep(step=move_index, limb=hand_cycle[move_index % 2], hold_id=coord_id, intent="Top", is_top=True))
        move_index += 1
    return steps


def _virtual_led_for(roles: Dict[Literal["start", "mid", "end"], List[str]], marker_summary: Dict[str, Any]) -> List[VirtualLedPoint]:
    points: List[VirtualLedPoint] = []
    used: set[str] = set()
    role_groups = [
        ("start_hand", marker_summary.get("start_hands", [])),
        ("start_foot", marker_summary.get("start_feet", [])),
        ("mid", roles["mid"]),
        ("end", roles["end"]),
    ]
    for role, coords in role_groups:
        for coord_id in coords:
            if coord_id in used:
                continue
            used.add(coord_id)
            x_label, y_index = _coord_parts(coord_id)
            col = ord(x_label) - ord("A") + 1
            led_index = (y_index - 1) * BOARD_COLUMNS + col
            points.append(
                VirtualLedPoint(
                    coord_id=coord_id,
                    led_index=led_index,
                    row=y_index,
                    col=col,
                    role=role,
                    color=ROLE_COLORS[role],
                )
            )
    return points


def _route_overlay_for(roles: Dict[Literal["start", "mid", "end"], List[str]], marker_summary: Dict[str, Any]) -> List[RouteOverlayPoint]:
    return [RouteOverlayPoint(**point.model_dump()) for point in _virtual_led_for(roles, marker_summary)]


def detail_for(route: NormalizedStandardRoute, roles: Optional[Dict[Literal["start", "mid", "end"], List[str]]] = None) -> StandardBoardRouteDetail:
    raw_roles = roles or route.roles
    validation = validate_standard_roles(raw_roles)
    resolved_roles = validation["effective_roles"]
    marker_summary = validation["marker_summary"]
    features = _feature_snapshot(resolved_roles)
    valid_for_climb = bool(validation.get("valid_for_climb"))
    score_breakdown = _score_route_quality(route.grade, route.repeats, route.is_benchmark, features, validation) if valid_for_climb else {}
    quality_score = round(sum(score_breakdown.values()), 2) if valid_for_climb else None
    quality_tier = _quality_tier(quality_score, valid_for_climb)
    difficulty = evaluate_route_difficulty(route.grade, route.repeats, route.is_benchmark, resolved_roles, marker_summary, validation)
    holds = _holds_for(resolved_roles)
    board_asset = BoardAsset(
        route_name=_display_name(route.source_id, route.source_name),
        setter_commentary=f"来源：MoonBoard 衍生数据；定线者：{route.setter_name}；原始难度：{route.grade}。",
        source_type="imported",
        visibility="private",
        tags=["standard-board", "virtual-led"],
        difficulty=route.grade,
        predicted_grade=route.predicted_grade,
        grade_origin="moonboard_source",
        difficulty_confidence=route.difficulty_confidence,
        confidence_tier=route.confidence_tier,
        calibration_status=route.calibration_status,
        board_spec=_board_spec(),
        placed_holds=holds,
        beta_sequence=_beta_for(resolved_roles, marker_summary),
    )
    summary = summary_for(
        NormalizedStandardRoute(
            source_id=route.source_id,
            source_url=route.source_url,
            source_name=route.source_name,
            setter_name=route.setter_name,
            grade=route.grade,
            is_benchmark=route.is_benchmark,
            repeats=route.repeats,
            roles=resolved_roles,
            score=quality_score or 0.0,
            quality_score=quality_score,
            quality_tier=quality_tier,
            score_breakdown=score_breakdown,
            marker_summary=marker_summary,
            review_reasons=validation.get("review_reasons", []),
            difficulty_score=difficulty["difficulty_score"],
            predicted_grade=difficulty["predicted_grade"],
            grade_delta=difficulty["grade_delta"],
            difficulty_confidence=difficulty["difficulty_confidence"],
            difficulty_breakdown=difficulty["difficulty_breakdown"],
            difficulty_reasons=difficulty["difficulty_reasons"],
            grade_warning=difficulty["grade_warning"],
            confidence_tier=difficulty["confidence_tier"],
            calibration_status=difficulty["calibration_status"],
            features=features,
            valid_for_climb=valid_for_climb,
            validation=validation,
        )
    )
    return StandardBoardRouteDetail(
        **summary.model_dump(),
        roles=resolved_roles,
        route_roles=resolved_roles,
        board_setup=load_board_setup(),
        route_overlay=_route_overlay_for(resolved_roles, marker_summary),
        virtual_led=_virtual_led_for(resolved_roles, marker_summary),
        board_asset=board_asset,
        validation=validation,
    )


def _candidate_mid_coords(original: str, occupied: set[str]) -> List[str]:
    x_label, y_index = _coord_parts(original)
    x_index = ord(x_label) - ord("A")
    candidates: List[str] = []
    setup = _setup_map()
    for dy in (0, 1, -1, 2, -2, 3, -3):
        for dx in (1, -1, 0, 2, -2, 3, -3):
            next_x = x_index + dx
            next_y = y_index + dy
            if not 0 <= next_x < BOARD_COLUMNS or not 1 <= next_y <= BOARD_ROWS:
                continue
            coord_id = f"{X_LABELS[next_x]}{next_y}"
            setup_hold = setup.get(coord_id)
            if not setup_hold or coord_id in occupied or setup_hold.hold_type == HoldType.FOOT:
                continue
            candidates.append(coord_id)
    return candidates


def _mutated_roles(route: NormalizedStandardRoute) -> Dict[Literal["start", "mid", "end"], List[str]]:
    roles = {role: list(coords) for role, coords in route.roles.items()}
    if not roles["mid"]:
        return roles

    target_index = len(roles["mid"]) // 2
    original = roles["mid"][target_index]
    occupied = set(roles["start"] + roles["mid"] + roles["end"])
    occupied.discard(original)

    for candidate in _candidate_mid_coords(original, occupied):
        next_roles = {role: list(coords) for role, coords in roles.items()}
        next_roles["mid"][target_index] = candidate
        if validate_standard_roles(next_roles).get("valid_for_climb"):
            return next_roles
    return roles


def _reuse_quality(reuse_rate: float) -> Literal["below_pass", "pass", "optimal"]:
    if reuse_rate >= 0.7:
        return "optimal"
    if reuse_rate >= 0.4:
        return "pass"
    return "below_pass"


def generate_standard_route(target_difficulty: str = DEFAULT_FONT_GRADE, benchmark_only: bool = False, variation: bool = True) -> Dict[str, Any]:
    candidates = [
        route
        for route in load_standard_routes()
        if route.valid_for_climb and route.grade == target_difficulty and (route.is_benchmark or not benchmark_only)
    ]
    if not candidates:
        candidates = [route for route in load_standard_routes() if route.valid_for_climb and route.grade == target_difficulty]
    if not candidates:
        raise ValueError(f"No valid standard-board routes found for difficulty {target_difficulty}")

    random.shuffle(candidates)
    for route in sorted(candidates[:500], key=lambda item: item.score, reverse=True):
        source_coords = set(route.roles["start"] + route.roles["mid"] + route.roles["end"])
        generated_roles = _mutated_roles(route) if variation else route.roles
        detail = detail_for(route, generated_roles)
        if not detail.validation.get("valid_for_climb"):
            detail = detail_for(route, route.roles)
        if detail.validation.get("valid_for_climb"):
            generated_coords = set(detail.route_roles["start"] + detail.route_roles["mid"] + detail.route_roles["end"])
            reuse_rate = len(source_coords & generated_coords) / len(source_coords) if source_coords else 0.0
            return {
                "route": detail,
                "source_route_id": route.source_id,
                "reuse_rate": round(reuse_rate, 3),
                "reuse_quality": _reuse_quality(reuse_rate),
                "validation": detail.validation,
            }

    raise ValueError(f"No valid standard-board routes passed validation for difficulty {target_difficulty}")


REPAIRABLE_FAILURES = {"start_hand_count_lt_2", "start_marker_count_lt_3", "no_start_foothold"}


def _load_review_queue() -> List[Dict[str, Any]]:
    if not REVIEW_QUEUE_PATH.exists():
        load_standard_routes()
    try:
        with REVIEW_QUEUE_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []
    routes = payload.get("routes", [])
    return routes if isinstance(routes, list) else []


def _route_from_queue_entry(entry: Dict[str, Any]) -> Dict[Literal["start", "mid", "end"], List[str]]:
    roles = entry.get("roles") or {}
    return {
        "start": _dedupe_preserve_order(str(coord_id) for coord_id in roles.get("start", [])),
        "mid": _dedupe_preserve_order(str(coord_id) for coord_id in roles.get("mid", [])),
        "end": _dedupe_preserve_order(str(coord_id) for coord_id in roles.get("end", [])),
    }


def _repairable_failure_set(entry: Dict[str, Any]) -> set[str]:
    failures = set()
    for code in entry.get("failures", []):
        failures.add(str(code).split(":", 1)[0])
    return failures


def _candidate_start_hands_for_repair(roles: Dict[Literal["start", "mid", "end"], List[str]], needed: int) -> List[str]:
    marker_summary = _marker_snapshot(roles)
    existing_hands = marker_summary.get("start_hands", [])
    reference_coords = existing_hands or roles["start"] or roles["mid"] or roles["end"]
    reference_x = (
        sum(_coord_x_index(coord_id) for coord_id in reference_coords if _coord_exists(coord_id)) / len(reference_coords)
        if reference_coords
        else (BOARD_COLUMNS - 1) / 2
    )
    candidates = []
    occupied = set(roles["start"] + roles["end"])
    for coord_id in roles["mid"]:
        if coord_id in occupied or not _coord_exists(coord_id) or _is_foot_hold(coord_id):
            continue
        _, y_index = _coord_parts(coord_id)
        if y_index > 5:
            continue
        x_distance = abs(_coord_x_index(coord_id) - reference_x)
        candidates.append((y_index, x_distance, coord_id))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [coord_id for *_rest, coord_id in candidates[:needed]]


def _repair_queue_entry(entry: Dict[str, Any], route: Optional[NormalizedStandardRoute] = None) -> StandardBoardRepairCandidate:
    source_id = str(entry.get("source_id") or "")
    source_metadata = {
        "source_name": route.source_name if route else _source_name(source_id, entry.get("source_url")),
        "setter_name": route.setter_name if route else "未知定线者",
        "original_grade": route.grade if route else str(entry.get("grade") or ""),
    }
    original_roles = _route_from_queue_entry(entry)
    failures = _repairable_failure_set(entry)
    if not failures or not failures.issubset(REPAIRABLE_FAILURES):
        return StandardBoardRepairCandidate(
            source_id=source_id,
            **source_metadata,
            repair_status="unrepairable",
            original_roles=original_roles,
            validation={"failures": list(failures)},
            review_reasons=entry.get("review_reasons", []),
        )

    marker_summary = _marker_snapshot(original_roles)
    needed_hands = max(0, 2 - len(marker_summary.get("start_hands", [])))
    added_hands = _candidate_start_hands_for_repair(original_roles, needed_hands)
    if len(added_hands) < needed_hands:
        return StandardBoardRepairCandidate(
            source_id=source_id,
            **source_metadata,
            repair_status="unrepairable",
            original_roles=original_roles,
            validation={"failures": ["no_low_hand_candidate"]},
            review_reasons=["原路线没有足够低位非脚点可补为手起点"],
        )

    repaired_roles = {
        "start": _dedupe_preserve_order(original_roles["start"] + added_hands),
        "mid": [coord_id for coord_id in original_roles["mid"] if coord_id not in set(added_hands)],
        "end": list(original_roles["end"]),
    }
    validation = validate_standard_roles(repaired_roles)
    if not validation.get("valid_for_climb"):
        return StandardBoardRepairCandidate(
            source_id=source_id,
            **source_metadata,
            repair_status="repairable",
            original_roles=original_roles,
            repaired_roles=validation.get("effective_roles", repaired_roles),
            added_start_hands=added_hands,
            derived_start_feet=validation.get("marker_summary", {}).get("derived_start_feet", []),
            validation=validation,
            review_reasons=validation.get("review_reasons", []),
        )

    features = _feature_snapshot(validation["effective_roles"])
    font_grade = normalize_font_grade(entry.get("grade") or entry.get("font_grade")) or DEFAULT_FONT_GRADE
    score_breakdown = _score_route_quality(font_grade, 0, False, features, validation)
    quality_score = round(sum(score_breakdown.values()), 2)
    difficulty = evaluate_route_difficulty(font_grade, 0, False, validation["effective_roles"], validation["marker_summary"], validation)
    return StandardBoardRepairCandidate(
        source_id=source_id,
        **source_metadata,
        repair_status="repaired",
        original_roles=original_roles,
        repaired_roles=validation["effective_roles"],
        added_start_hands=added_hands,
        derived_start_feet=validation.get("marker_summary", {}).get("derived_start_feet", []),
        validation=validation,
        quality_score=quality_score,
        difficulty_score=difficulty["difficulty_score"],
        predicted_grade=difficulty["predicted_grade"],
        grade_delta=difficulty["grade_delta"],
        difficulty_confidence=difficulty["difficulty_confidence"],
        difficulty_breakdown=difficulty["difficulty_breakdown"],
        difficulty_reasons=difficulty["difficulty_reasons"],
        grade_warning=difficulty["grade_warning"],
        confidence_tier=difficulty["confidence_tier"],
        calibration_status=difficulty["calibration_status"],
        review_reasons=[],
    )


def query_standard_board_repairs(q: Optional[str] = None, limit: int = 24, offset: int = 0, status: Optional[str] = None) -> StandardBoardRepairQueryResponse:
    accepted_ids = {str(record.get("source_id")) for record in _load_accepted_repair_records() if record.get("source_id")}
    route_by_id = {route.source_id: route for route in load_standard_routes()}
    candidates = [_repair_queue_entry(entry, route_by_id.get(str(entry.get("source_id") or ""))) for entry in _load_review_queue()]
    candidates = [candidate for candidate in candidates if candidate.source_id not in accepted_ids]
    if q and q.strip():
        needle = q.strip().casefold()
        candidates = [
            candidate
            for candidate in candidates
            if needle in candidate.source_id.casefold()
            or needle in candidate.source_name.casefold()
            or needle in candidate.setter_name.casefold()
        ]
    if status:
        candidates = [candidate for candidate in candidates if candidate.repair_status == status]
    else:
        candidates = [candidate for candidate in candidates if candidate.repair_status != "unrepairable"]
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    page = candidates[bounded_offset : bounded_offset + bounded_limit]
    return StandardBoardRepairQueryResponse(
        total=len(candidates),
        limit=bounded_limit,
        offset=bounded_offset,
        routes=page,
    )


def find_standard_board_repair(source_id: str) -> Optional[StandardBoardRepairCandidate]:
    source_id = _original_source_id(source_id)
    route = next((item for item in load_standard_routes() if item.source_id == source_id), None)
    for entry in _load_review_queue():
        if str(entry.get("source_id")) == str(source_id):
            return _repair_queue_entry(entry, route)
    return None


def repair_comparison(source_id: str) -> Optional[StandardBoardRepairComparison]:
    original_source_id = _original_source_id(source_id)
    candidate = find_standard_board_repair(original_source_id)
    route = next((item for item in load_standard_routes() if item.source_id == original_source_id), None)
    if not candidate or not route:
        return None
    repaired = None
    if candidate.repair_status == "repaired" and candidate.repaired_roles:
        repaired = detail_for(route, candidate.repaired_roles)
    return StandardBoardRepairComparison(
        candidate=candidate,
        original=detail_for(route, candidate.original_roles),
        repaired=repaired,
    )


def publish_standard_board_repairs(source_ids: List[str]) -> StandardBoardRepairPublishResponse:
    records = _load_accepted_repair_records()
    records_by_id = {str(record.get("source_id")): record for record in records if record.get("source_id")}
    published: List[StandardBoardRouteSummary] = []
    skipped: List[StandardBoardRepairPublishSkipped] = []
    base_routes = list(load_standard_routes())
    base_by_id = {route.source_id: route for route in base_routes}

    for raw_source_id in _dedupe_preserve_order(_original_source_id(source_id) for source_id in source_ids):
        source_id = str(raw_source_id)
        candidate = find_standard_board_repair(source_id)
        base_route = base_by_id.get(source_id)
        if not candidate or not base_route:
            skipped.append(StandardBoardRepairPublishSkipped(source_id=source_id, reason="未找到该待修复线路"))
            continue
        if candidate.repair_status != "repaired" or not candidate.repaired_roles:
            skipped.append(StandardBoardRepairPublishSkipped(source_id=source_id, reason="只有已修复候选可以放入线路库"))
            continue

        accepted_route = _route_with_roles(
            base_route,
            candidate.repaired_roles,
            source_id=_repaired_source_id(source_id),
            repeats=0,
            is_benchmark=False,
        )
        if not accepted_route.valid_for_climb:
            skipped.append(StandardBoardRepairPublishSkipped(source_id=source_id, reason="修复结果未通过线路库校验"))
            continue

        records_by_id[source_id] = {
            "source_id": source_id,
            "repaired_source_id": _repaired_source_id(source_id),
            "repaired_roles": candidate.repaired_roles,
            "added_start_hands": candidate.added_start_hands,
            "derived_start_feet": candidate.derived_start_feet,
        }
        published.append(summary_for(accepted_route))

    if published:
        _write_accepted_repair_records(list(records_by_id.values()))
    return StandardBoardRepairPublishResponse(published=published, skipped=skipped)
