"""
Shared Pydantic contracts for the API, route generator, and frontend board studio.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.moonboard_grading import BOUNDARY_LABELS, DEFAULT_FONT_GRADE, FONT_GRADES, UNGRADED, normalize_font_grade


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

    @field_validator("target_difficulty")
    @classmethod
    def validate_target_difficulty(cls, value: str) -> str:
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError(f"目标难度必须是 {FONT_GRADES[0]}–{FONT_GRADES[-1]} 的 Font 等级")
        return grade


class FinalRoute(BaseModel):
    """A generated or saved route shown in the frontend."""

    saved_id: Optional[str] = None
    owner_id: Optional[str] = None
    source_type: str = "ai-generated"
    visibility: str = "private"
    tags: List[str] = Field(default_factory=list)
    difficulty: str = DEFAULT_FONT_GRADE
    predicted_grade: Optional[str] = None
    grade_system: Literal["font"] = "font"
    grade_origin: Literal["moonboard_source", "transferred", "human_confirmed", "ungraded"] = "ungraded"
    difficulty_confidence: Optional[float] = Field(None, ge=0, le=1)
    confidence_tier: Literal["low", "medium", "high"] = "low"
    calibration_status: Literal["ready", "calibrating", "uncalibrated"] = "uncalibrated"
    legacy_difficulty: Optional[str] = Field(None, exclude=True)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    board_spec: Optional[BoardSpec] = None
    route_name: str
    setter_commentary: str = ""
    placed_holds: List[Hold]
    beta_sequence: List[BetaStep] = Field(default_factory=list)

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        grade = normalize_font_grade(value, allow_ungraded=True)
        if not grade:
            raise ValueError(f"难度必须是 {FONT_GRADES[0]}–{FONT_GRADES[-1]} 或“{UNGRADED}”")
        return grade

    @field_validator("predicted_grade")
    @classmethod
    def validate_predicted_grade(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        grade = normalize_font_grade(value)
        if not grade and value not in BOUNDARY_LABELS:
            raise ValueError("预测难度必须使用 Font 等级")
        return grade or value


class BoardAsset(FinalRoute):
    """Editable board asset persisted by the redesigned frontend."""

    source_type: str = "manual"
    workflow_status: Literal["draft", "ready_for_review"] = "draft"
    readiness_issues: List[str] = Field(default_factory=list)
    readiness_warnings: List[str] = Field(default_factory=list)
    ai_eligible: bool = False
    archived_at: Optional[str] = None


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
    generation_goal: Literal["quality_first", "grade_match", "style_variation"] = "quality_first"
    review_focus: Literal["overall", "footholds", "difficulty", "beta_sequence"] = "overall"
    user_requirements: str = ""
    target_difficulty: Optional[str] = None
    climber_height_cm: int = 175
    climber_span_cm: int = 175

    @field_validator("target_difficulty")
    @classmethod
    def validate_optional_target_difficulty(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError("AI 目标难度必须使用 Font 等级")
        return grade


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
    reason_code: str = ""
    observed: str = ""
    threshold: str = ""
    expected_effect: str = ""
    beta_steps: List[int] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence_status: Literal["measured", "estimated", "not_measured"] = "measured"


class AIExperimentScoreItem(BaseModel):
    id: str
    label: str
    score: float
    max_score: float
    observed: str
    threshold: str
    explanation: str
    related_hold_ids: List[str] = Field(default_factory=list)


class AIExperimentCheck(BaseModel):
    id: str
    label: str
    status: Literal["pass", "warning", "fail", "not_run"]
    observed: str
    threshold: str
    explanation: str
    related_hold_ids: List[str] = Field(default_factory=list)


class AIExperimentCandidateTrace(BaseModel):
    strategy: str
    strategy_label: str
    source: str
    status: Literal["selected", "rejected", "duplicate", "failed_validation"]
    reason_code: str
    reason: str
    signature: Optional[str] = None
    selected_rank: Optional[int] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class AIExperimentExplanation(BaseModel):
    schema_version: str = "ai-explanation-v1"
    decision_sources: List[Dict[str, str]] = Field(default_factory=list)
    input_summary: Dict[str, Any] = Field(default_factory=dict)
    input_fingerprint: str
    score_breakdown: List[AIExperimentScoreItem] = Field(default_factory=list)
    risk_breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    checks: List[AIExperimentCheck] = Field(default_factory=list)
    candidate_trace: List[AIExperimentCandidateTrace] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    versions: Dict[str, str] = Field(default_factory=dict)
    reference_note: Optional[str] = None


class AIExperimentRecommendation(BaseModel):
    status: Literal["optimized", "keep_original"]
    title: str
    summary: str


class AIExperimentResponse(BaseModel):
    mode: Literal["compose_route", "review_route"]
    recommendation: Optional[AIExperimentRecommendation] = None
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
    explanation: Optional[AIExperimentExplanation] = None


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
    source_name: str
    setter_name: str = "未知定线者"
    source_url: Optional[str] = None
    grade: str
    grade_system: Literal["font"] = "font"
    grade_origin: Literal["moonboard_source"] = "moonboard_source"
    is_benchmark: bool = False
    repeats: int = 0
    score: float
    quality_score: Optional[float] = None
    quality_tier: Literal["excellent", "good", "climbable", "review", "rejected"] = "review"
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    marker_summary: Dict[str, Any] = Field(default_factory=dict)
    review_reasons: List[str] = Field(default_factory=list)
    difficulty_score: Optional[float] = None
    predicted_grade: Optional[str] = None
    grade_delta: Optional[int] = None
    difficulty_confidence: Optional[float] = None
    difficulty_breakdown: Dict[str, float] = Field(default_factory=dict)
    difficulty_reasons: List[str] = Field(default_factory=list)
    grade_warning: Literal["none", "soft", "hard", "uncertain"] = "none"
    confidence_tier: Literal["low", "medium", "high"] = "low"
    calibration_status: Literal["ready", "calibrating", "uncalibrated"] = "ready"
    tags: List[str] = Field(default_factory=list)
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
    target_difficulty: str = DEFAULT_FONT_GRADE
    benchmark_only: bool = False
    variation: bool = True

    @field_validator("target_difficulty")
    @classmethod
    def validate_target_difficulty(cls, value: str) -> str:
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError("生成目标难度必须使用 Font 等级")
        return grade


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

    @field_validator("perceived_grade")
    @classmethod
    def validate_perceived_grade(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError("体感难度必须使用 Font 等级")
        return grade


class StandardRouteActivityLog(BaseModel):
    id: str
    result: Literal["flash", "send", "attempt", "fail"]
    attempts: int
    perceived_grade: Optional[str] = None
    notes: str = ""
    created_at: str
    review_status: Literal["pending", "approved", "rejected"] = "pending"


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
    source_name: str = ""
    setter_name: str = "未知定线者"
    original_grade: str = ""
    repair_status: Literal["repairable", "repaired", "unrepairable"]
    original_roles: Dict[Literal["start", "mid", "end"], List[str]]
    repaired_roles: Optional[Dict[Literal["start", "mid", "end"], List[str]]] = None
    added_start_hands: List[str] = Field(default_factory=list)
    derived_start_feet: List[str] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    quality_score: Optional[float] = None
    difficulty_score: Optional[float] = None
    predicted_grade: Optional[str] = None
    grade_delta: Optional[int] = None
    difficulty_confidence: Optional[float] = None
    difficulty_breakdown: Dict[str, float] = Field(default_factory=dict)
    difficulty_reasons: List[str] = Field(default_factory=list)
    grade_warning: Literal["none", "soft", "hard", "uncertain"] = "none"
    confidence_tier: Literal["low", "medium", "high"] = "low"
    calibration_status: Literal["ready", "calibrating", "uncalibrated"] = "ready"
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


class ClimberCapabilities(BaseModel):
    ability_grade: str = DEFAULT_FONT_GRADE
    finger_strength: float = Field(55.0, ge=0, le=100)
    pull_power: float = Field(55.0, ge=0, le=100)
    core_tension: float = Field(55.0, ge=0, le=100)
    hip_mobility: float = Field(55.0, ge=0, le=100)
    shoulder_mobility: float = Field(55.0, ge=0, le=100)
    endurance: float = Field(55.0, ge=0, le=100)
    technique: float = Field(55.0, ge=0, le=100)

    @field_validator("ability_grade")
    @classmethod
    def validate_ability_grade(cls, value: str) -> str:
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError("攀爬者能力必须使用 Font 等级")
        return grade


class ClimberProfile(BaseModel):
    id: str
    label: str
    description: str = ""
    height_cm: float = Field(..., gt=100, lt=230)
    arm_span_cm: float = Field(..., gt=100, lt=240)
    weight_kg: float = Field(..., gt=25, lt=180)
    shoulder_width_cm: float
    hip_width_cm: float
    torso_length_cm: float
    upper_arm_cm: float
    forearm_cm: float
    hand_reach_cm: float = Field(7.0, ge=4.0, le=12.0)
    thigh_cm: float
    shin_cm: float
    capabilities: ClimberCapabilities = Field(default_factory=ClimberCapabilities)
    version: str = "1.0"


class HoldContactAnchor(BaseModel):
    x: float = Field(0.0, ge=-1.0, le=1.0)
    y: float = Field(0.0, ge=-1.0, le=1.0)


class HoldPhysicsProfile(BaseModel):
    variant_id: str
    hold_type: HoldType
    grip_family: Literal["jug", "crimp", "sloper", "pinch", "pocket", "foot"]
    quality: int = Field(3, ge=1, le=5)
    usable_by: Literal["hand", "foot", "both"] = "hand"
    preferred_direction_degrees: int = Field(180, ge=0, le=359)
    direction_tolerance_degrees: int = Field(90, ge=10, le=180)
    capacity: float = Field(0.7, ge=0.1, le=2.0)
    confidence: float = Field(0.65, ge=0, le=1)
    hand_contact_anchor: HoldContactAnchor = Field(default_factory=HoldContactAnchor)
    foot_contact_anchor: HoldContactAnchor = Field(default_factory=HoldContactAnchor)
    recovery_contact_anchor: HoldContactAnchor = Field(default_factory=HoldContactAnchor)
    notes: str = ""
    version: str = "1.2"


class SimulationRequest(BaseModel):
    ability_grade: Optional[str] = None
    profile_ids: List[str] = Field(default_factory=list)
    motion_mode: Optional[Literal["static", "static_then_single_dynamic"]] = None
    static_only: Optional[bool] = None
    generate_repairs: bool = False
    force_refresh: bool = False

    @model_validator(mode="after")
    def resolve_motion_mode(self):
        legacy_mode = None
        if self.static_only is not None:
            legacy_mode = "static" if self.static_only else "static_then_single_dynamic"
        if self.motion_mode and legacy_mode and self.motion_mode != legacy_mode:
            raise ValueError("motion_mode 与 static_only 冲突")
        self.motion_mode = self.motion_mode or legacy_mode or "static_then_single_dynamic"
        self.static_only = self.motion_mode == "static"
        return self


class SimulationBatchRequest(SimulationRequest):
    source_ids: List[str] = Field(default_factory=list)
    difficulty: Optional[str] = None
    limit: int = Field(24, ge=1, le=200)


class SimulationJointPoint(BaseModel):
    x: float
    y: float
    z: Optional[float] = 0.0


class SimulationAction(BaseModel):
    step: int
    action_type: Literal["static_move", "match", "deadpoint", "dyno", "cut_loose", "recovery"]
    moving_limbs: List[Limb] = Field(default_factory=list)
    target_hold_ids: List[str] = Field(default_factory=list)
    from_contacts: Dict[str, Optional[str]] = Field(default_factory=dict)
    to_contacts: Dict[str, Optional[str]] = Field(default_factory=dict)
    purpose: str
    technique: str = "direct_reach"
    support_limbs: List[Limb] = Field(default_factory=list)
    drive_limbs: List[Limb] = Field(default_factory=list)
    preparation_required: bool = False
    dynamic: bool = False
    duration_seconds: float = 0.0
    peak_velocity: float = 0.0
    catch_load_ratio: float = 0.0


class SimulationFrame(BaseModel):
    step: int
    moving_limb: Optional[Limb] = None
    hold_id: Optional[str] = None
    contacts: Dict[str, Optional[str]] = Field(default_factory=dict)
    joints: Dict[str, SimulationJointPoint] = Field(default_factory=dict)
    center_of_mass: SimulationJointPoint
    phase: Literal[
        "rest",
        "weight_shift",
        "crouch",
        "release",
        "reach",
        "place",
        "push",
        "flight",
        "catch",
        "settle",
        "recovery",
    ] = "rest"
    timestamp_seconds: float = 0.0
    contact_anchors: Dict[str, SimulationJointPoint] = Field(default_factory=dict)
    support_limbs: List[Limb] = Field(default_factory=list)
    shoulder_wall_distance: float = 0.0
    hip_wall_distance: float = 0.0
    technique: str = ""
    contact_loads: Dict[str, float] = Field(default_factory=dict)
    velocity: Optional[SimulationJointPoint] = None
    dynamic: bool = False
    load_ratio: float = 0.0
    fatigue: float = 0.0
    stable: bool = True
    note: str = ""


class ClimberRun(BaseModel):
    profile_id: str
    profile_label: str
    status: Literal["passed", "failed", "review"]
    solution_mode: Literal["static", "single_dynamic", "none"] = "none"
    search_complete: bool = True
    expanded_states: int = 0
    alternatives_found: int = 0
    movement_count: int = 0
    dynamic_action_count: int = 0
    dynamic_feasibility_score: float = 0.0
    robustness: float = 0.0
    confidence: float = 0.0
    fatigue: float = 0.0
    crux_step: Optional[int] = None
    failure_step: Optional[int] = None
    failure_hold_id: Optional[str] = None
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
    dynamic_suspected: bool = False
    demand: Dict[str, float] = Field(default_factory=dict)
    actions: List[SimulationAction] = Field(default_factory=list)
    beta_sequence: List[BetaStep] = Field(default_factory=list)
    frames: List[SimulationFrame] = Field(default_factory=list)


class SimulationRepairCandidate(BaseModel):
    id: str
    label: str
    strategy: Literal["reach", "balance", "grade"]
    reason: str
    changed_holds: List[Dict[str, str]] = Field(default_factory=list)
    reuse_rate: float
    reuse_quality: Literal["below_pass", "pass", "optimal"]
    predicted_grade: Optional[str] = None
    majority_passed: bool = False
    board_asset: Optional[BoardAsset] = None


class SimulationReport(BaseModel):
    report_id: str
    source_id: str
    created_at: str
    engine_version: str
    input_hash: str
    verdict: Literal["pass", "pass_body_bias", "review", "fail"]
    verdict_label: str
    summary: str
    ability_grade: str
    motion_mode: Literal["static", "static_then_single_dynamic"] = "static_then_single_dynamic"
    pass_count: int
    profile_count: int
    feasibility_score: float
    confidence: float
    predicted_grade: Optional[str] = None
    grade_delta: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    dynamic_suspected: bool = False
    calibration_complete: bool = False
    shadow_mode: bool = True
    route: StandardBoardRouteDetail
    runs: List[ClimberRun] = Field(default_factory=list)
    repair_candidates: List[SimulationRepairCandidate] = Field(default_factory=list)


class SimulationBatchResult(BaseModel):
    total: int
    completed: int
    reports: List[SimulationReport] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)


class SimulationFeedback(BaseModel):
    outcome: Literal["flash", "send", "attempt", "fail"]
    profile_id: Optional[str] = None
    height_cm: Optional[float] = Field(None, gt=100, lt=230)
    arm_span_cm: Optional[float] = Field(None, gt=100, lt=240)
    ability_grade: Optional[str] = None
    perceived_grade: Optional[str] = None
    failure_step: Optional[int] = None
    failure_hold_id: Optional[str] = None
    system_correct: Optional[bool] = None
    notes: str = ""

    @field_validator("ability_grade", "perceived_grade")
    @classmethod
    def validate_optional_grade(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        grade = normalize_font_grade(value)
        if not grade:
            raise ValueError("能力与体感难度必须使用 Font 等级")
        return grade


class SimulationFeedbackRecord(SimulationFeedback):
    id: str
    report_id: str
    source_id: str
    created_at: str
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    calibration_eligible: bool = False
