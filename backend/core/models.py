"""
Shared Pydantic contracts for the API, route generator, and frontend board studio.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class HoldType(str, Enum):
    JUG = "Jug"
    CRIMP = "Crimp"
    SLOPER = "Sloper"
    PINCH = "Pinch"
    POCKET = "Pocket"
    FOOT = "Foot"


class Limb(str, Enum):
    LH = "LH"
    RH = "RH"
    LF = "LF"
    RF = "RF"


class Hold(BaseModel):
    """Single hold placed on a board coordinate."""

    id: str = Field(..., description="Grid coordinate such as C5")
    x: str
    y: int
    hold_type: HoldType
    rotation: int = 0
    scale: float = 1.0
    is_start: bool = False
    variant: str = "default"
    type: Optional[str] = Field(None, description="Frontend compatibility alias")
    imageUrl: Optional[str] = Field(None, description="Frontend hold image URL")
    svgPath: Optional[str] = Field(None, description="Frontend hold vector path")


class BetaStep(BaseModel):
    """One movement in a route beta sequence."""

    step: int
    limb: Limb
    hold_id: str
    intent: str = "Move"
    is_top: bool = False
    lh: Optional[str] = None
    rh: Optional[str] = None
    lf: Optional[str] = None
    rf: Optional[str] = None


class RouteCandidate(BaseModel):
    placed_holds: List[Hold]
    beta_sequence: List[BetaStep] = Field(default_factory=list)
    total_cost: float = 0.0
    flow_score: float = 0.0
    crux_step: Optional[str] = None
    quota_violations: Dict[HoldType, int] = Field(default_factory=dict)


class BoardSpec(BaseModel):
    """Frontend board template snapshot. Extra UI labels are preserved."""

    model_config = ConfigDict(extra="allow")

    preset_id: Optional[str] = None
    template_key: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    columns: int = 11
    cols: Optional[int] = None
    rows: int = 18
    hole_spacing_x_mm: int = 200
    hole_spacing_y_mm: int = 200
    board_width_mm: Optional[int] = None
    board_height_mm: Optional[int] = None
    grid_width_mm: Optional[int] = None
    grid_height_mm: Optional[int] = None
    margin_left_mm: int = 220
    margin_right_mm: int = 220
    margin_bottom_mm: int = 130
    margin_top_mm: int = 130
    angle_degrees: int = 40
    total_holes: Optional[int] = None
    unit: str = "mm"
    reference_system: Optional[str] = None
    cellLabel: Optional[str] = None
    physicalLabel: Optional[str] = None
    spacingLabel: Optional[str] = None
    angleLabel: Optional[str] = None
    material: Optional[str] = None
    skinClass: Optional[str] = None
    description: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    xLabels: List[str] = Field(default_factory=list)
    yLabels: List[int] = Field(default_factory=list)


class RecipeItem(BaseModel):
    count: int
    variant: str


class HoldSpec(BaseModel):
    hold_type: HoldType
    variant: str = "default"
    rotation: int = 0
    scale: float = 1.0


class RouteRequest(BaseModel):
    climber_height_cm: int
    climber_span_cm: int
    target_difficulty: str
    special_requirements: str = ""
    recipe: Dict[HoldType, RecipeItem] = Field(default_factory=dict)
    hold_pool: List[HoldSpec] = Field(default_factory=list)


class FinalRoute(BaseModel):
    """A generated or saved route shown in the frontend."""

    saved_id: Optional[str] = None
    owner_id: Optional[str] = None
    source_type: str = "ai-generated"
    visibility: str = "private"
    tags: List[str] = Field(default_factory=list)
    difficulty: str = "V3"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    board_spec: Optional[BoardSpec] = None
    route_name: str
    setter_commentary: str = ""
    placed_holds: List[Hold]
    beta_sequence: List[BetaStep] = Field(default_factory=list)


class BoardAsset(FinalRoute):
    """Editable board asset persisted by the redesigned frontend."""

    source_type: str = "manual"


class RenameBoardRequest(BaseModel):
    route_name: str


class RouteResponse(BaseModel):
    selected_routes: List[FinalRoute]
    failure_suggestion: Optional[str] = None
    task_id: Optional[str] = None


class GenerationInitiated(BaseModel):
    task_id: str
    status: str = "pending"


class TaskEnvelope(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    result: Optional[Any] = None
    error: Optional[str] = None


class AIExperimentRequest(BaseModel):
    mode: Literal["compose_route", "review_route"] = "compose_route"
    board: BoardAsset
    user_requirements: str = ""
    target_difficulty: Optional[str] = None
    climber_height_cm: int = 175
    climber_span_cm: int = 175


class RouteReviewViolation(BaseModel):
    code: str
    message: str
    hold_ids: List[str] = Field(default_factory=list)


class RouteReviewSuggestion(BaseModel):
    title: str
    detail: str
    hold_ids: List[str] = Field(default_factory=list)
    group: Literal["must_fix", "should_fix", "optional"] = "optional"
    candidate_route: Optional[FinalRoute] = None


class AIExperimentResponse(BaseModel):
    mode: Literal["compose_route", "review_route"]
    selected_routes: List[FinalRoute] = Field(default_factory=list)
    review_summary: Optional[str] = None
    violations: List[RouteReviewViolation] = Field(default_factory=list)
    suggestions: List[RouteReviewSuggestion] = Field(default_factory=list)
    risk_level: Optional[Literal["low", "medium", "high"]] = None
    board: Optional[BoardAsset] = None
    failure_suggestion: Optional[str] = None
    analysis_summary: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    candidate_routes: List[Dict[str, Any]] = Field(default_factory=list)
    applied_constraints: List[str] = Field(default_factory=list)
    algorithm_notes: List[str] = Field(default_factory=list)
    llm_enriched: bool = False


class StandardBoardRouteFeatures(BaseModel):
    hold_count: int
    x_span: int
    y_span: int
    min_y: int
    max_y: int
    start_count: int
    mid_count: int
    end_count: int


class VirtualLedPoint(BaseModel):
    coord_id: str
    led_index: int
    row: int
    col: int
    role: Literal["start", "start_hand", "start_foot", "mid", "end"]
    color: str


class RouteOverlayPoint(VirtualLedPoint):
    pass


class StandardBoardRouteSummary(BaseModel):
    source_id: str
    display_name: str
    grade: str
    v_grade: str
    is_benchmark: bool = False
    repeats: int = 0
    score: float
    quality_score: Optional[float] = None
    quality_tier: Literal["excellent", "good", "climbable", "review", "rejected"] = "review"
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    marker_summary: Dict[str, Any] = Field(default_factory=dict)
    review_reasons: List[str] = Field(default_factory=list)
    difficulty_score: Optional[float] = None
    predicted_v_grade: Optional[str] = None
    grade_delta: Optional[int] = None
    difficulty_confidence: Optional[float] = None
    difficulty_breakdown: Dict[str, float] = Field(default_factory=dict)
    difficulty_reasons: List[str] = Field(default_factory=list)
    grade_warning: Literal["none", "soft", "hard", "uncertain"] = "none"
    features: StandardBoardRouteFeatures
    valid_for_climb: bool = True


class StandardBoardRouteDetail(StandardBoardRouteSummary):
    source_type: str = "standard-board-dataset"
    source_url: Optional[str] = None
    roles: Dict[Literal["start", "mid", "end"], List[str]]
    route_roles: Dict[Literal["start", "mid", "end"], List[str]]
    board_setup: List[Hold] = Field(default_factory=list)
    route_overlay: List[RouteOverlayPoint] = Field(default_factory=list)
    virtual_led: List[VirtualLedPoint]
    board_asset: BoardAsset
    validation: Dict[str, Any] = Field(default_factory=dict)


class StandardBoardRouteQueryResponse(BaseModel):
    total: int
    limit: int
    offset: int
    routes: List[StandardBoardRouteSummary]


class StandardBoardGenerateRequest(BaseModel):
    target_difficulty: str = "V3"
    benchmark_only: bool = False
    variation: bool = True


class StandardBoardGenerateResponse(BaseModel):
    route: StandardBoardRouteDetail
    source_route_id: str
    reuse_rate: float
    reuse_quality: Literal["below_pass", "pass", "optimal"]
    validation: Dict[str, Any]


class StandardRouteRatingRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class StandardRouteAscentLogRequest(BaseModel):
    result: Literal["flash", "send", "attempt", "fail"]
    attempts: int = Field(1, ge=1, le=999)
    perceived_grade: Optional[str] = None
    notes: str = ""


class StandardRouteActivityLog(BaseModel):
    id: str
    result: Literal["flash", "send", "attempt", "fail"]
    attempts: int
    perceived_grade: Optional[str] = None
    notes: str = ""
    created_at: str


class StandardRouteActivityStats(BaseModel):
    attempts_total: int = 0
    sends_total: int = 0
    flashes_total: int = 0
    last_result: Optional[str] = None


class StandardRouteActivityResponse(BaseModel):
    favorite: bool = False
    rating: Optional[int] = None
    logs: List[StandardRouteActivityLog] = Field(default_factory=list)
    stats: StandardRouteActivityStats = Field(default_factory=StandardRouteActivityStats)


class StandardBoardRepairCandidate(BaseModel):
    source_id: str
    repair_status: Literal["repairable", "repaired", "unrepairable"]
    original_roles: Dict[Literal["start", "mid", "end"], List[str]]
    repaired_roles: Optional[Dict[Literal["start", "mid", "end"], List[str]]] = None
    added_start_hands: List[str] = Field(default_factory=list)
    derived_start_feet: List[str] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    quality_score: Optional[float] = None
    difficulty_score: Optional[float] = None
    predicted_v_grade: Optional[str] = None
    grade_delta: Optional[int] = None
    difficulty_confidence: Optional[float] = None
    difficulty_breakdown: Dict[str, float] = Field(default_factory=dict)
    difficulty_reasons: List[str] = Field(default_factory=list)
    grade_warning: Literal["none", "soft", "hard", "uncertain"] = "none"
    review_reasons: List[str] = Field(default_factory=list)


class StandardBoardRepairQueryResponse(BaseModel):
    total: int
    limit: int
    offset: int
    routes: List[StandardBoardRepairCandidate]


class StandardBoardRepairComparison(BaseModel):
    candidate: StandardBoardRepairCandidate
    original: StandardBoardRouteDetail
    repaired: Optional[StandardBoardRouteDetail] = None


class StandardBoardRepairPublishRequest(BaseModel):
    source_ids: List[str] = Field(default_factory=list)


class StandardBoardRepairPublishSkipped(BaseModel):
    source_id: str
    reason: str


class StandardBoardRepairPublishResponse(BaseModel):
    published: List[StandardBoardRouteSummary] = Field(default_factory=list)
    skipped: List[StandardBoardRepairPublishSkipped] = Field(default_factory=list)
