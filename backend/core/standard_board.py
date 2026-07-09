"""Standard training board data services.

The module models a generic 11x18 fixed-hold training board. Route data is an
overlay that highlights a subset of the fixed setup; it is not hardware control.
"""

from __future__ import annotations

import json
import pickle
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

from core.models import (
    BetaStep,
    BoardAsset,
    BoardSpec,
    Hold,
    HoldType,
    Limb,
    RouteOverlayPoint,
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
REVIEW_QUEUE_PATH = DATA_DIR / "standard_board_review_queue.json"
SETUP_SCALE = 0.78

GRADE_TO_V = {
    "6A": "V0",
    "6A+": "V0",
    "6B": "V0",
    "6B+": "V1",
    "6C": "V2",
    "6C+": "V3",
    "7A": "V3",
    "7A+": "V4",
    "7B": "V5",
    "7B+": "V6",
    "7C": "V7",
    "7C+": "V8",
    "8A": "V9",
    "8A+": "V10",
}

ROLE_COLORS = {
    "start": "#22c55e",
    "start_hand": "#22c55e",
    "start_foot": "#3b82f6",
    "mid": "#f59e0b",
    "end": "#ef4444",
}

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
    grade: str
    v_grade: str
    is_benchmark: bool
    repeats: int
    roles: Dict[Literal["start", "mid", "end"], List[str]]
    score: float
    quality_score: Optional[float]
    quality_tier: str
    score_breakdown: Dict[str, float]
    marker_summary: Dict[str, Any]
    review_reasons: List[str]
    features: StandardBoardRouteFeatures
    valid_for_climb: bool
    validation: Dict[str, Any]


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
            variants.append(
                {
                    "index": len(variants),
                    "hold_type": normalized_type,
                    "variant": variant,
                    "imageUrl": str(image_url),
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


def _difficulty_number(v_grade: str) -> int:
    try:
        return int(v_grade.upper().replace("V", ""))
    except ValueError:
        return 3


def _clamp_score(value: float, maximum: float) -> float:
    return round(max(0.0, min(maximum, value)), 2)


def _score_route_quality(
    v_grade: str,
    repeats: int,
    is_benchmark: bool,
    features: StandardBoardRouteFeatures,
    validation: Dict[str, Any],
) -> Dict[str, float]:
    checks = validation.get("checks", {})
    max_gap = float(checks.get("max_vertical_gap", 0))
    hold_count = features.hold_count
    v_number = _difficulty_number(v_grade)

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

    expected_holds = max(6.0, 10.0 - min(v_number, 10) * 0.35)
    hold_match = 9.0 * max(0.0, 1.0 - abs(hold_count - expected_holds) / 5.0)
    expected_span = min(8.0, 3.0 + v_number * 0.45)
    span_match = 6.0 * max(0.0, 1.0 - abs(features.x_span - expected_span) / 6.0)
    grade_shape = 5.0 * min(1.0, (features.y_span + features.x_span) / (15.0 + v_number * 0.4))
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
        "v_grade": route.v_grade,
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
        with REVIEW_QUEUE_PATH.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _normalize_route(source_id: str, raw_route: Dict[str, Any]) -> Optional[NormalizedStandardRoute]:
    grade = str(raw_route.get("grade") or raw_route.get("Grade") or "").upper()
    v_grade = GRADE_TO_V.get(grade)
    if not v_grade:
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
    score_breakdown = _score_route_quality(v_grade, repeats, is_benchmark, features, validation) if valid_for_climb else {}
    quality_score = round(sum(score_breakdown.values()), 2) if valid_for_climb else None
    quality_tier = _quality_tier(quality_score, valid_for_climb)
    return NormalizedStandardRoute(
        source_id=str(source_id),
        source_url=raw_route.get("url"),
        grade=grade,
        v_grade=v_grade,
        is_benchmark=is_benchmark,
        repeats=repeats,
        roles=effective_roles,
        score=quality_score or 0.0,
        quality_score=quality_score,
        quality_tier=quality_tier,
        score_breakdown=score_breakdown,
        marker_summary=validation["marker_summary"],
        review_reasons=validation.get("review_reasons", []),
        features=features,
        valid_for_climb=valid_for_climb,
        validation=validation,
    )


@lru_cache(maxsize=1)
def load_standard_routes() -> List[NormalizedStandardRoute]:
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
    _write_review_queue(routes)
    routes.sort(key=lambda route: route.score, reverse=True)
    return routes


def summary_for(route: NormalizedStandardRoute) -> StandardBoardRouteSummary:
    return StandardBoardRouteSummary(
        source_id=route.source_id,
        display_name=f"Standard route {route.source_id}",
        grade=route.grade,
        v_grade=route.v_grade,
        is_benchmark=route.is_benchmark,
        repeats=route.repeats,
        score=round(route.score, 2),
        quality_score=round(route.quality_score, 2) if route.quality_score is not None else None,
        quality_tier=route.quality_tier,
        score_breakdown=route.score_breakdown,
        marker_summary=route.marker_summary,
        review_reasons=route.review_reasons,
        features=route.features,
        valid_for_climb=route.valid_for_climb,
    )


def query_standard_routes(
    difficulty: Optional[str] = None,
    benchmark_only: bool = False,
    min_holds: Optional[int] = None,
    max_holds: Optional[int] = None,
    sort: str = "score_desc",
    limit: int = 24,
    offset: int = 0,
    valid_only: bool = True,
) -> StandardBoardRouteQueryResponse:
    routes = list(load_standard_routes())
    if valid_only:
        routes = [route for route in routes if route.valid_for_climb]
    if difficulty:
        routes = [route for route in routes if route.v_grade == difficulty]
    if benchmark_only:
        routes = [route for route in routes if route.is_benchmark]
    if min_holds is not None:
        routes = [route for route in routes if route.features.hold_count >= min_holds]
    if max_holds is not None:
        routes = [route for route in routes if route.features.hold_count <= max_holds]

    if sort == "repeats_desc":
        routes.sort(key=lambda route: (route.repeats, route.score), reverse=True)
    elif sort == "span_desc":
        routes.sort(key=lambda route: (route.features.x_span, route.features.y_span, route.score), reverse=True)
    elif sort == "holds_asc":
        routes.sort(key=lambda route: (route.features.hold_count, -route.score))
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
    return next((route for route in load_standard_routes() if route.source_id == source_id), None)


def _board_spec() -> BoardSpec:
    return BoardSpec(
        preset_id="classic-11x18",
        template_key="spray-small",
        label="Standard training board 11x18",
        name="Standard training board 11x18",
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
        angleLabel="40 deg",
        material="wood composite",
        skinClass="skin-wood-classic",
        description="Generic standard training board for virtual lighting and algorithm validation.",
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
    score_breakdown = _score_route_quality(route.v_grade, route.repeats, route.is_benchmark, features, validation) if valid_for_climb else {}
    quality_score = round(sum(score_breakdown.values()), 2) if valid_for_climb else None
    quality_tier = _quality_tier(quality_score, valid_for_climb)
    holds = _holds_for(resolved_roles)
    board_asset = BoardAsset(
        route_name=f"Standard route {route.source_id}",
        setter_commentary="Standard-board dataset route. The fixed board setup is separate from this route overlay.",
        source_type="imported",
        visibility="private",
        tags=["standard-board", "virtual-led"],
        difficulty=route.v_grade,
        board_spec=_board_spec(),
        placed_holds=holds,
        beta_sequence=_beta_for(resolved_roles, marker_summary),
    )
    summary = summary_for(
        NormalizedStandardRoute(
            source_id=route.source_id,
            source_url=route.source_url,
            grade=route.grade,
            v_grade=route.v_grade,
            is_benchmark=route.is_benchmark,
            repeats=route.repeats,
            roles=resolved_roles,
            score=quality_score or 0.0,
            quality_score=quality_score,
            quality_tier=quality_tier,
            score_breakdown=score_breakdown,
            marker_summary=marker_summary,
            review_reasons=validation.get("review_reasons", []),
            features=features,
            valid_for_climb=valid_for_climb,
            validation=validation,
        )
    )
    return StandardBoardRouteDetail(
        **summary.model_dump(),
        source_url=route.source_url,
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


def generate_standard_route(target_difficulty: str = "V3", benchmark_only: bool = False, variation: bool = True) -> Dict[str, Any]:
    candidates = [
        route
        for route in load_standard_routes()
        if route.valid_for_climb and route.v_grade == target_difficulty and (route.is_benchmark or not benchmark_only)
    ]
    if not candidates:
        candidates = [route for route in load_standard_routes() if route.valid_for_climb and route.v_grade == target_difficulty]
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
