"""
FastAPI entrypoint for the climbing board backend.
"""

import asyncio
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.controller import generate_route_with_reflection
from agent.experiments import run_ai_experiment
from core.board_readiness import apply_board_readiness
from core.photo_route_drafts import PhotoRouteStore, create_photo_route_router
from core.photo_route_v2 import PhotoRouteJobManager, PhotoRouteV2Store, create_photo_route_v2_router
from core.climb_replay import (AliyunReplayAnalyzer, ClimbReplayManager,
                               ClimbReplayStore, create_climb_replay_router)
from core.hold_image_processing import (
    PROCESSING_VERSION,
    SUPPORTED_IMAGE_SUFFIXES,
    HoldImageProcessingError,
    process_hold_image_bytes,
    processed_filename_for,
    resolve_local_holds_mapping,
    write_bytes_atomic,
)
from core.models import (
    AIExperimentRequest,
    BoardAsset,
    ClimberProfile,
    FinalRoute,
    GenerationInitiated,
    HoldPhysicsProfile,
    RouteRequest,
    RouteResponse,
    StandardBoardRepairCandidate,
    StandardBoardRepairComparison,
    StandardBoardRepairPublishRequest,
    StandardBoardRepairPublishResponse,
    StandardBoardRepairQueryResponse,
    StandardBoardGenerateRequest,
    StandardBoardGenerateResponse,
    StandardBoardRouteDetail,
    StandardBoardRouteQueryResponse,
    StandardRouteActivityLog,
    StandardRouteActivityResponse,
    StandardRouteActivityStats,
    StandardRouteAscentLogRequest,
    StandardRouteRatingRequest,
    SimulationBatchRequest,
    SimulationBatchResult,
    SimulationFeedback,
    SimulationFeedbackRecord,
    SimulationRepairCandidate,
    SimulationReport,
    SimulationRequest,
    TaskEnvelope,
)
from core.moonboard_grading import (
    DEFAULT_FONT_GRADE,
    UNGRADED,
    assess_equivalent_grade,
    hold_transfer_demand,
    normalize_font_grade,
)
from core.pilot_access import (
    EditLeaseError,
    InvalidCredentialsError,
    LoginBlockedError,
    PilotAccessError,
    PilotAccessManager,
    PilotUser,
)
from core.standard_board import (
    detail_for,
    find_standard_board_repair,
    find_standard_route,
    generate_standard_route,
    publish_standard_board_repairs,
    query_standard_board_repairs,
    query_standard_routes,
    repair_comparison,
)
from core.state import active_tasks
from core.simulation import (
    generate_repair_candidates,
    get_climber_profiles,
    get_hold_profiles,
    get_latest_report,
    record_feedback,
    simulate_batch,
    simulate_route,
    update_hold_profile,
)
from core.supabase_repo import (
    SupabaseRepository,
    SupabaseRepositoryError,
    extract_bearer_token,
    extract_user_id_from_auth_header,
    is_local_only_mode,
    is_supabase_configured,
)

load_dotenv()

TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
RELEASE_SHA = os.getenv("RELEASE_SHA", "development").strip() or "development"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_ENV_VALUES


SIMULATION_ENABLED = env_flag("ENABLE_SIMULATION", default=APP_ENV != "production")
CLIMB_REPLAY_ENABLED = env_flag("ENABLE_CLIMB_REPLAY", default=True)
CLIMB_REPLAY_TEST_VIDEO_PATH = (
    os.getenv("CLIMB_REPLAY_TEST_VIDEO_PATH", "").strip()
    if APP_ENV != "production" else ""
)
CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL = (
    os.getenv("CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL", "").strip()
    if APP_ENV != "production" else ""
)
try:
    CLIMB_REPLAY_TEST_VIDEOS = json.loads(
        os.getenv("CLIMB_REPLAY_TEST_VIDEOS", "[]")
        if APP_ENV != "production" else "[]"
    )
    if not isinstance(CLIMB_REPLAY_TEST_VIDEOS, list):
        CLIMB_REPLAY_TEST_VIDEOS = []
except (TypeError, ValueError):
    CLIMB_REPLAY_TEST_VIDEOS = []


def docs_url_for_environment(app_env: str, path: str) -> str | None:
    return None if app_env == "production" else path


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/result/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

app = FastAPI(
    title="攀岩定线辅助系统本地服务",
    version="7.0",
    docs_url=docs_url_for_environment(APP_ENV, "/docs"),
    redoc_url=docs_url_for_environment(APP_ENV, "/redoc"),
    openapi_url=docs_url_for_environment(APP_ENV, "/openapi.json"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = "data"
PHOTO_ROUTE_DATA_ROOT = Path(os.getenv("PHOTO_ROUTE_DATA_DIR", str(Path(__file__).resolve().parent / "data/photo_routes")))
photo_route_store = PhotoRouteStore(PHOTO_ROUTE_DATA_ROOT)
app.include_router(create_photo_route_router(photo_route_store))
photo_route_v2_store = PhotoRouteV2Store(PHOTO_ROUTE_DATA_ROOT)
photo_route_jobs = PhotoRouteJobManager(photo_route_v2_store)
app.include_router(create_photo_route_v2_router(photo_route_v2_store, photo_route_jobs))
climb_replay_manager = None
if CLIMB_REPLAY_ENABLED:
    climb_replay_store = ClimbReplayStore(PHOTO_ROUTE_DATA_ROOT / "climb_replay")
    climb_replay_manager = ClimbReplayManager(climb_replay_store, AliyunReplayAnalyzer())
    app.include_router(create_climb_replay_router(
        climb_replay_store,
        climb_replay_manager,
        route_lookup=photo_route_v2_store.get_route,
        test_video_path=(Path(CLIMB_REPLAY_TEST_VIDEO_PATH)
                         if CLIMB_REPLAY_TEST_VIDEO_PATH else None),
        test_video_source_url=CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL or None,
        test_video_cases=CLIMB_REPLAY_TEST_VIDEOS,
    ))
from core.photo_route_workflow import PhotoWorkflow, workflow_router
photo_workflow = PhotoWorkflow(photo_route_v2_store)
app.include_router(workflow_router(photo_workflow))
from core.photo_route_settings import settings_router
app.include_router(settings_router(PHOTO_ROUTE_DATA_ROOT))
HOLDS_IMAGES_DIR = os.path.join(DATA_DIR, "holds_images")
PROCESSED_HOLDS_IMAGES_DIR = os.path.join(DATA_DIR, "holds_images_processed")
HOLDS_MAPPING_FILE = os.path.join(DATA_DIR, "holds_mapping.json")
HOLDS_VECTORS_FILE = os.path.join(DATA_DIR, "holds_vectors.json")
HOLDS_METADATA_FILE = os.path.join(DATA_DIR, "hold_assets_meta.json")
SAVED_BOARDS_FILE = os.path.join(DATA_DIR, "saved_boards.json")
EMPTY_WALL_FILE = os.path.join(DATA_DIR, "empty_wall_grid.json")
STANDARD_BOARD_ACTIVITY_FILE = os.path.join(DATA_DIR, "standard_board_activity.json")
PILOT_AUTH_ENABLED = env_flag("PILOT_AUTH_ENABLED", default=APP_ENV == "production")
PILOT_COOKIE_SECURE = env_flag("PILOT_COOKIE_SECURE", default=APP_ENV == "production")
PILOT_QUICK_LOGIN_ENABLED = env_flag(
    "PILOT_QUICK_LOGIN_ENABLED",
    default=APP_ENV == "development",
)
PILOT_QUICK_LOGIN_ALLOW_REMOTE = env_flag("PILOT_QUICK_LOGIN_ALLOW_REMOTE", default=False)
PILOT_QUICK_LOGIN_USERNAME = (
    os.getenv("PILOT_QUICK_LOGIN_USERNAME", "ma-trial").strip().lower() or "ma-trial"
)
PILOT_QUICK_LOGIN_DISPLAY_NAME = (
    os.getenv("PILOT_QUICK_LOGIN_DISPLAY_NAME", "马老师").strip() or "马老师"
)
PILOT_COOKIE_NAME = "ai_climbing_session"
PILOT_USERS_FILE = os.getenv("PILOT_USERS_FILE", os.path.join(DATA_DIR, "pilot_users.json"))
PILOT_AUDIT_FILE = os.getenv("PILOT_AUDIT_FILE", os.path.join(DATA_DIR, "pilot_audit.jsonl"))

os.makedirs(PROCESSED_HOLDS_IMAGES_DIR, exist_ok=True)
app.mount("/images/processed", StaticFiles(directory=PROCESSED_HOLDS_IMAGES_DIR), name="processed-images")
app.mount("/images", StaticFiles(directory=HOLDS_IMAGES_DIR), name="images")

tasks: Dict[str, asyncio.Task] = {}
supabase_repo = SupabaseRepository()
_json_locks: Dict[str, threading.RLock] = {}
_json_locks_guard = threading.Lock()
pilot_access = PilotAccessManager(
    users_file=PILOT_USERS_FILE,
    audit_file=PILOT_AUDIT_FILE,
)

from core.member_accounts import MemberAccounts
from core.member_storage import member, member_key, private_path, combine, difference

if env_flag('MEMBER_ACCOUNTS_ENABLED', default=APP_ENV == 'production'):
    pilot_access = MemberAccounts(database=os.path.join(DATA_DIR, 'accounts.sqlite3'),
                                  users_file=PILOT_USERS_FILE, audit_file=PILOT_AUDIT_FILE)
    PILOT_QUICK_LOGIN_ENABLED = False
task_owners = {}


def protect_public_hold(hold_type, variant):
    if member.get() and (variant in read_json(HOLDS_MAPPING_FILE, {}).get(hold_type, {})
                         or variant in read_json(HOLDS_VECTORS_FILE, {}).get(hold_type, {})):
        raise HTTPException(403, '公共岩点只能查看和引用。')


class PilotLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def request_client_ip(request: Request) -> str:
    return (
        request.headers.get("x-real-ip")
        or (request.client.host if request.client else "unknown")
    )


def quick_login_available(request: Request) -> bool:
    if not PILOT_QUICK_LOGIN_ENABLED:
        return False
    if PILOT_QUICK_LOGIN_ALLOW_REMOTE:
        return True
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    socket_host = request.client.host if request.client else "unknown"
    return request_client_ip(request) in loopback_hosts and socket_host in loopback_hosts


def quick_login_identity(request: Request) -> PilotUser | None:
    if not quick_login_available(request):
        return None
    try:
        return pilot_access.active_user(PILOT_QUICK_LOGIN_USERNAME)
    except PilotAccessError:
        if APP_ENV == "development":
            return PilotUser(PILOT_QUICK_LOGIN_USERNAME, PILOT_QUICK_LOGIN_DISPLAY_NAME)
        return None


def set_pilot_session_cookie(response: JSONResponse, token: str) -> None:
    response.set_cookie(
        PILOT_COOKIE_NAME,
        token,
        max_age=pilot_access.session_seconds,
        secure=PILOT_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
        path="/",
    )


def request_user(request: Request) -> PilotUser:
    user = getattr(request.state, "pilot_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def audit_request(request: Request, status: int, event: str | None = None) -> None:
    user = getattr(request.state, "pilot_user", None)
    pilot_access.audit(
        username=user.username if user else "anonymous",
        request_id=getattr(request.state, "request_id", "unknown"),
        method=request.method,
        path=request.url.path,
        status=status,
        event=event,
    )


@app.middleware("http")
async def pilot_access_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    path = request.url.path
    if path.startswith('/api/auth/') and request.method == 'POST':
        from urllib.parse import urlsplit
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse(status_code=403, content={'detail': '请从本站页面提交。'})
    simulation_path = (
        path.startswith("/api/simulation/")
        or path == "/api/standard-board/simulations/batch"
        or (
            path.startswith("/api/standard-board/routes/")
            and "/simulation" in path
        )
    )
    if not SIMULATION_ENABLED and simulation_path:
        return JSONResponse(
            status_code=404,
            content={"detail": "仿真审核未在本次试运行中开放。"},
            headers={"X-Request-ID": request.state.request_id},
        )
    if not PILOT_AUTH_ENABLED:
        request.state.pilot_user = PilotUser("owner", "负责人")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    public_paths = {
        "/api/health",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/quick-login",
        "/api/auth/logout",
        "/api/auth/session",
    }
    if request.method == "OPTIONS" or path in public_paths:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        return response

    token = request.cookies.get(PILOT_COOKIE_NAME)
    user = pilot_access.session_user(token)
    if not user:
        return JSONResponse(
            status_code=401,
            content={"detail": "登录已失效，请重新登录。"},
            headers={"X-Request-ID": request.state.request_id},
        )
    request.state.pilot_user = user

    if isinstance(pilot_access, MemberAccounts):
        member.set(user.username)
        parts = path.split('/')
        if path.startswith('/images/'):
            image_owner = next((p for p in parts if p.startswith('u-')), None)
            if image_owner and image_owner != member_key():
                return JSONResponse(status_code=404, content={'detail': '未找到图片。'})
        if path.startswith(('/api/result/', '/api/cancel/')) and task_owners.get(parts[-1]) != user.username:
            return JSONResponse(status_code=404, content={'detail': '未找到任务。'})
        if path == '/api/standard-board/repairs/publish' or path.startswith('/api/simulation/'):
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                return JSONResponse(status_code=403, content={'detail': '公共资源不允许修改。'})

    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    lease_path = path.startswith("/api/pilot/edit-lease")
    if is_write and path.startswith("/api/") and not lease_path and not path.startswith('/api/settings/vision') and not isinstance(pilot_access, MemberAccounts):
        try:
            pilot_access.require_lease(user.username)
        except EditLeaseError as exc:
            audit_request(request, 423, "write_blocked_without_edit_lease")
            return JSONResponse(
                status_code=423,
                content={"detail": str(exc)},
                headers={"X-Request-ID": request.state.request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    if isinstance(pilot_access, MemberAccounts):
        response.headers['Cache-Control'] = 'no-store'
    if is_write and not lease_path:
        audit_request(request, response.status_code)
    return response


def is_local_demo_request(request: Request) -> bool:
    token = extract_bearer_token(request.headers.get("authorization"))
    return bool(token and token.startswith("mock-token-local-demo"))


def should_use_supabase(request: Request | None = None) -> bool:
    if is_local_only_mode() or not is_supabase_configured():
        return False
    if request is not None and is_local_demo_request(request):
        return False
    return True


async def resolve_supabase_user(request: Request) -> dict | None:
    if not should_use_supabase(request):
        return None
    token = extract_bearer_token(request.headers.get("authorization"))
    if not token:
        return None
    try:
        user = await supabase_repo.get_auth_user(token)
        if user:
            await supabase_repo.ensure_profile(user)
        return user
    except SupabaseRepositoryError as exc:
        print(f"Supabase auth validation failed: {exc}")
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(file_path: str, default: Any) -> Any:
    scoped = private_path(file_path)
    if scoped != str(Path(file_path)):
        public = read_json(file_path, default)
        personal = read_json(scoped, default)
        return combine(file_path, public, personal)
    return read_json(file_path, default)


def read_json(file_path: str, default: Any) -> Any:
    if not os.path.exists(file_path):
        return default
    try:
        with json_file_lock(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
    except json.JSONDecodeError:
        return default


def save_json(file_path: str, data: Any) -> None:
    scoped = private_path(file_path)
    if scoped != str(Path(file_path)):
        public = read_json(file_path, [] if Path(file_path).name == 'saved_boards.json' else {})
        data = difference(file_path, public, data)
        file_path = scoped
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    temp_path = f"{file_path}.{uuid.uuid4().hex}.tmp"
    with json_file_lock(file_path):
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, file_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def json_file_lock(file_path: str) -> threading.RLock:
    normalized = os.path.abspath(file_path)
    with _json_locks_guard:
        return _json_locks.setdefault(normalized, threading.RLock())


def mutate_json(file_path: str, default: Any, mutator) -> Any:
    """Read, mutate and atomically replace one JSON file under the same lock."""
    with json_file_lock(file_path):
        data = load_json(file_path, default)
        result = mutator(data)
        save_json(file_path, data)
        return result


def task_envelope(task_id: str, status: str, result: Any = None, error: str | None = None) -> Dict[str, Any]:
    if member.get():
        task_owners.setdefault(task_id, member.get())
    return {"task_id": task_id, "status": status, "result": result, "error": error}


def serialize_result(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


async def update_supabase_task(task_id: str, status: str, result: Any = None, error: str | None = None) -> None:
    if not should_use_supabase():
        return
    try:
        await supabase_repo.update_task(task_id, status, result=result, error=error)
    except SupabaseRepositoryError as exc:
        print(f"Supabase task update skipped: {exc}")


async def run_and_store_generation(task_id: str, payload: Dict[str, Any], owner_id: str | None = None) -> None:
    active_tasks[task_id] = task_envelope(task_id, "running")
    await update_supabase_task(task_id, "running")
    current_task = asyncio.current_task()
    if current_task:
        tasks[task_id] = current_task
    try:
        if "mode" in payload or "board" in payload:
            experiment_request = AIExperimentRequest(**payload)
            # Route search and validation are CPU-heavy. Keep them off the API
            # event loop so the 202 response and result polling stay responsive.
            result = await asyncio.to_thread(lambda: asyncio.run(run_ai_experiment(experiment_request)))
        else:
            result = await generate_route_with_reflection(RouteRequest(**payload), task_id)
        serialized = serialize_result(result)
        active_tasks[task_id] = task_envelope(task_id, "completed", serialized)
        await update_supabase_task(task_id, "completed", result=serialized)
    except asyncio.CancelledError:
        active_tasks[task_id] = task_envelope(task_id, "cancelled", error="任务已被用户取消")
    except Exception as exc:
        import traceback

        print(f"Task {task_id} failed: {exc}\n{traceback.format_exc()}")
        active_tasks[task_id] = task_envelope(task_id, "failed", error=str(exc))
        await update_supabase_task(task_id, "failed", error=str(exc))
    finally:
        tasks.pop(task_id, None)


async def run_and_store_simulation(task_id: str, operation, *args) -> None:
    active_tasks[task_id] = task_envelope(task_id, "running")
    current_task = asyncio.current_task()
    if current_task:
        tasks[task_id] = current_task
    try:
        result = await asyncio.to_thread(operation, *args)
        active_tasks[task_id] = task_envelope(task_id, "completed", serialize_result(result))
    except asyncio.CancelledError:
        active_tasks[task_id] = task_envelope(task_id, "cancelled", error="仿真任务已取消")
    except Exception as exc:
        import traceback

        print(f"Simulation task {task_id} failed: {exc}\n{traceback.format_exc()}")
        active_tasks[task_id] = task_envelope(task_id, "failed", error=str(exc))
    finally:
        tasks.pop(task_id, None)


def load_boards() -> List[Dict[str, Any]]:
    raw_boards = load_json(SAVED_BOARDS_FILE, [])
    if not isinstance(raw_boards, list):
        return []
    return raw_boards


def dump_board(board: BoardAsset) -> Dict[str, Any]:
    data = board.model_dump(mode="json")
    if board.legacy_difficulty:
        data["legacy_difficulty"] = board.legacy_difficulty
    return data


def _grade_roles(data: Dict[str, Any]) -> Dict[str, List[str]]:
    holds = [item for item in data.get("placed_holds", []) if isinstance(item, dict) and item.get("id")]
    start = [str(item["id"]) for item in holds if item.get("is_start")]
    top_ids = [
        str(step.get("hold_id"))
        for step in data.get("beta_sequence", [])
        if isinstance(step, dict) and step.get("is_top") and step.get("hold_id")
    ]
    if not top_ids:
        hand_holds = [item for item in holds if str(item.get("hold_type") or item.get("type")) != "Foot"]
        if hand_holds:
            top_ids = [str(max(hand_holds, key=lambda item: int(item.get("y") or 0))["id"])]
    occupied = set(start) | set(top_ids)
    return {
        "start": start,
        "mid": [str(item["id"]) for item in holds if str(item["id"]) not in occupied],
        "end": list(dict.fromkeys(top_ids)),
    }


def _apply_font_grade(data: Dict[str, Any]) -> Dict[str, Any]:
    existing = str(data.get("difficulty") or "")
    legacy = existing if re.fullmatch(r"V(?:[0-9]|1[0-2])", existing.upper()) else data.get("legacy_difficulty")
    if legacy and not data.get("legacy_difficulty"):
        data["legacy_difficulty"] = legacy

    if data.get("archived_at"):
        data["difficulty"] = normalize_font_grade(existing) or UNGRADED
        data["grade_system"] = "font"
        data["grade_origin"] = "ungraded" if data["difficulty"] == UNGRADED else data.get("grade_origin", "transferred")
        return data

    source_grade_match = re.search(r"原始难度[：:]\s*(6B\+?|6C\+?|7A\+?|7B\+?|7C\+?|8A\+?|8B\+?)", str(data.get("setter_commentary") or ""), re.I)
    if data.get("source_type") == "imported" and source_grade_match:
        source_grade = source_grade_match.group(1).upper()
        data.update(
            {
                "difficulty": source_grade,
                "predicted_grade": data.get("predicted_grade"),
                "grade_system": "font",
                "grade_origin": "moonboard_source",
                "difficulty_confidence": data.get("difficulty_confidence", 1.0),
                "confidence_tier": data.get("confidence_tier", "high"),
                "calibration_status": "ready",
            }
        )
        return data

    if data.get("grade_origin") == "human_confirmed" and normalize_font_grade(existing):
        return data

    profiles = {profile.variant_id: profile for profile in get_hold_profiles()}
    holds = [item for item in data.get("placed_holds", []) if isinstance(item, dict)]
    assessment = assess_equivalent_grade(
        _grade_roles(data),
        board_spec=data.get("board_spec"),
        hold_demands=[
            hold_transfer_demand(
                item.get("hold_type") or item.get("type"),
                item.get("rotation"),
                profiles.get(str(item.get("variant") or "")),
            )
            for item in holds
        ],
        hold_confidences=[float(getattr(profiles.get(str(item.get("variant") or "")), "confidence", 0.65)) for item in holds],
        beta_complete=bool(data.get("beta_sequence")),
    )
    data.update(assessment)
    data["difficulty"] = normalize_font_grade(assessment.get("predicted_grade")) or UNGRADED
    return data


def normalize_board_payload(payload: Dict[str, Any], saved_id: str | None = None) -> BoardAsset:
    now = utc_now()
    data = dict(payload)
    if saved_id:
        data["saved_id"] = saved_id
    data.setdefault("route_name", "未命名岩板")
    data.setdefault("setter_commentary", "")
    data.setdefault("placed_holds", [])
    data.setdefault("beta_sequence", [])
    data.setdefault("source_type", "manual")
    data.setdefault("visibility", "private")
    data.setdefault("tags", [])
    data.setdefault("difficulty", UNGRADED)
    data.setdefault("created_at", now)
    data["updated_at"] = data.get("updated_at") or now
    data = _apply_font_grade(data)
    return apply_board_readiness(BoardAsset(**data))


def hold_asset_key(hold_type: str, variant: str) -> str:
    return f"{hold_type}:{variant}"


def load_hold_assets(include_archived: bool = False) -> List[Dict[str, Any]]:
    mapping = load_json(HOLDS_MAPPING_FILE, {})
    vectors = load_json(HOLDS_VECTORS_FILE, {})
    metadata = load_json(HOLDS_METADATA_FILE, {})
    assets: List[Dict[str, Any]] = []
    for hold_type in sorted(set(mapping) | set(vectors)):
        variants = sorted(set(mapping.get(hold_type, {})) | set(vectors.get(hold_type, {})))
        for variant in variants:
            if variant == "default":
                continue
            meta = metadata.get(hold_asset_key(hold_type, variant), {})
            archived_at = meta.get("archived_at")
            if archived_at and not include_archived:
                continue
            assets.append(
                {
                    "key": hold_asset_key(hold_type, variant),
                    "hold_type": hold_type,
                    "variant": variant,
                    "imageUrl": mapping.get(hold_type, {}).get(variant) or mapping.get(hold_type, {}).get("default"),
                    "svgPath": vectors.get(hold_type, {}).get(variant) or vectors.get(hold_type, {}).get("default"),
                    "archived_at": archived_at,
                    "visibility": 'public' if member.get() and variant in read_json(HOLDS_MAPPING_FILE, {}).get(hold_type, {}) else 'private',
                }
            )
    return assets


def local_activity_key(user_key: str, source_id: str) -> str:
    return f"{user_key}:{source_id}"


def load_standard_activity_store() -> Dict[str, Any]:
    store = load_json(STANDARD_BOARD_ACTIVITY_FILE, {})
    if not isinstance(store, dict):
        store = {}
    store.setdefault("favorites", {})
    store.setdefault("ratings", {})
    store.setdefault("logs", [])
    return store


def save_standard_activity_store(store: Dict[str, Any]) -> None:
    save_json(STANDARD_BOARD_ACTIVITY_FILE, store)


def local_activity_user_key(request: Request, owner_id: str | None = None) -> str:
    if owner_id:
        return owner_id
    pilot_user = getattr(request.state, "pilot_user", None)
    if pilot_user:
        return pilot_user.username
    token = extract_bearer_token(request.headers.get("authorization"))
    if token and token.startswith("mock-token-local-demo"):
        return "local-demo-user"
    return extract_user_id_from_auth_header(request.headers.get("authorization")) or "anonymous"


def activity_from_entries(favorite: bool, rating: int | None, logs: List[Dict[str, Any]]) -> StandardRouteActivityResponse:
    ordered_logs = sorted(logs, key=lambda item: item.get("created_at", ""), reverse=True)
    attempts_total = sum(int(item.get("attempts") or 0) for item in ordered_logs)
    sends_total = sum(1 for item in ordered_logs if item.get("result") in {"flash", "send"})
    flashes_total = sum(1 for item in ordered_logs if item.get("result") == "flash")
    parsed_logs = [
        StandardRouteActivityLog(
            id=str(item.get("id")),
            result=item.get("result"),
            attempts=int(item.get("attempts") or 1),
            perceived_grade=item.get("perceived_grade"),
            notes=str(item.get("notes") or ""),
            created_at=str(item.get("created_at") or ""),
            review_status=item.get("review_status") or "pending",
        )
        for item in ordered_logs[:20]
    ]
    return StandardRouteActivityResponse(
        favorite=favorite,
        rating=rating,
        logs=parsed_logs,
        stats=StandardRouteActivityStats(
            attempts_total=attempts_total,
            sends_total=sends_total,
            flashes_total=flashes_total,
            last_result=ordered_logs[0].get("result") if ordered_logs else None,
        ),
    )


def get_local_standard_activity(user_key: str, source_id: str) -> StandardRouteActivityResponse:
    store = load_standard_activity_store()
    key = local_activity_key(user_key, source_id)
    favorite = bool(store["favorites"].get(key, {}).get("active"))
    rating_entry = store["ratings"].get(key) or {}
    logs = [
        item
        for item in store["logs"]
        if item.get("user_key") == user_key and str(item.get("source_id")) == str(source_id)
    ]
    return activity_from_entries(favorite, rating_entry.get("rating"), logs)


async def get_standard_activity(request: Request, source_id: str) -> StandardRouteActivityResponse:
    return get_local_standard_activity(local_activity_user_key(request), source_id)


async def append_standard_activity_event(request: Request, source_id: str, activity_type: str, content: str, rating: int | None = None, metadata: Dict[str, Any] | None = None) -> StandardRouteActivityResponse:
    user_key = local_activity_user_key(request)
    key = local_activity_key(user_key, source_id)
    now = utc_now()
    metadata = metadata or {}

    def update(store: Dict[str, Any]) -> StandardRouteActivityResponse:
        if not isinstance(store, dict):
            raise HTTPException(status_code=500, detail="活动记录文件格式不正确。")
        store.setdefault("favorites", {})
        store.setdefault("ratings", {})
        store.setdefault("logs", [])
        if activity_type == "favorite":
            store["favorites"][key] = {"user_key": user_key, "source_id": source_id, "active": bool(metadata.get("active")), "updated_at": now}
        elif activity_type == "rating":
            store["ratings"][key] = {"user_key": user_key, "source_id": source_id, "rating": rating, "updated_at": now}
        elif activity_type == "ascent_log":
            store["logs"].append(
                {
                    "id": str(uuid.uuid4()),
                    "user_key": user_key,
                    "source_id": source_id,
                    "result": metadata.get("result"),
                    "attempts": metadata.get("attempts") or 1,
                    "perceived_grade": metadata.get("perceived_grade"),
                    "notes": metadata.get("notes") or "",
                    "created_at": now,
                    "review_status": "pending",
                }
            )
        favorite = bool(store["favorites"].get(key, {}).get("active"))
        rating_entry = store["ratings"].get(key) or {}
        logs = [
            item
            for item in store["logs"]
            if item.get("user_key") == user_key and str(item.get("source_id")) == str(source_id)
        ]
        return activity_from_entries(favorite, rating_entry.get("rating"), logs)

    return mutate_json(STANDARD_BOARD_ACTIVITY_FILE, {}, update)


@app.post('/api/auth/register')
async def register_member(request: Request):
    if not isinstance(pilot_access, MemberAccounts):
        raise HTTPException(404, '注册未开放。')
    if int(request.headers.get('content-length') or 0) > 4096:
        raise HTTPException(413, '注册信息过长。')
    try:
        data = await request.json()
        fields = ['username', 'display_name', 'password', 'invite_code']
        if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or len(data[k]) > 256 for k in fields):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, '请完整填写用户名、昵称、密码和邀请码。')
    try:
        token, user = await asyncio.to_thread(pilot_access.register, data['username'], data['display_name'],
                                              data['password'], data['invite_code'], request_client_ip(request))
    except LoginBlockedError as exc:
        raise HTTPException(429, str(exc)) from exc
    except PilotAccessError as exc:
        raise HTTPException(400, str(exc)) from exc
    request.state.pilot_user = user
    response = JSONResponse({'authenticated': True, 'auth_enabled': True, 'registration_enabled': True,
                             'username': user.username, 'display_name': user.display_name}, status_code=201)
    set_pilot_session_cookie(response, token)
    audit_request(request, 201, 'registration_succeeded')
    return response


@app.post("/api/auth/login")
async def pilot_login(payload: PilotLoginRequest, request: Request):
    try:
        token, user = pilot_access.authenticate(
            payload.username,
            payload.password,
            request_client_ip(request),
        )
    except LoginBlockedError as exc:
        pilot_access.audit(
            username=payload.username.strip().lower() or "anonymous",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status=429,
            event="login_blocked",
        )
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (InvalidCredentialsError, PilotAccessError) as exc:
        pilot_access.audit(
            username=payload.username.strip().lower() or "anonymous",
            request_id=request.state.request_id,
            method=request.method,
            path=request.url.path,
            status=401,
            event="login_failed",
        )
        raise HTTPException(status_code=401, detail="用户名或密码不正确。") from exc

    request.state.pilot_user = user
    response = JSONResponse(
        {
            "authenticated": True,
            "username": user.username,
            "display_name": user.display_name,
        }
    )
    set_pilot_session_cookie(response, token)
    audit_request(request, 200, "login_succeeded")
    return response


@app.post("/api/auth/quick-login")
async def pilot_quick_login(request: Request):
    identity = quick_login_identity(request)
    if not identity:
        raise HTTPException(status_code=404, detail="快速登录当前不可用。")
    token, user = pilot_access.create_session(identity)

    request.state.pilot_user = user
    response = JSONResponse(
        {
            "authenticated": True,
            "username": user.username,
            "display_name": user.display_name,
        }
    )
    set_pilot_session_cookie(response, token)
    audit_request(request, 200, "quick_login_succeeded")
    return response


@app.post("/api/auth/logout")
async def pilot_logout(request: Request):
    user = pilot_access.logout(request.cookies.get(PILOT_COOKIE_NAME))
    request.state.pilot_user = user
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        PILOT_COOKIE_NAME,
        secure=PILOT_COOKIE_SECURE,
        httponly=True,
        samesite="strict",
        path="/",
    )
    if user:
        audit_request(request, 200, "logout")
    return response


@app.get("/api/auth/session")
async def pilot_session(request: Request):
    if not PILOT_AUTH_ENABLED:
        return {
            "authenticated": True,
            "username": "owner",
            "display_name": "负责人",
            "auth_enabled": False,
        }
    user = pilot_access.session_user(request.cookies.get(PILOT_COOKIE_NAME))
    quick_identity = quick_login_identity(request)
    if not user:
        return {
            "authenticated": False,
            "auth_enabled": True,
            "registration_enabled": isinstance(pilot_access, MemberAccounts),
            "quick_login_enabled": quick_identity is not None,
            "default_username": quick_identity.username if quick_identity else "",
            "default_display_name": quick_identity.display_name if quick_identity else "",
        }
    return {
        "authenticated": True,
        "username": user.username,
        "display_name": user.display_name,
        "auth_enabled": True,
        "registration_enabled": isinstance(pilot_access, MemberAccounts),
        "quick_login_enabled": quick_identity is not None,
        "default_username": quick_identity.username if quick_identity else "",
        "default_display_name": quick_identity.display_name if quick_identity else "",
    }


@app.get("/api/pilot/edit-lease")
async def get_pilot_edit_lease(request: Request):
    user = request_user(request)
    return pilot_access.lease_status(user.username)


@app.post("/api/pilot/edit-lease/acquire")
async def acquire_pilot_edit_lease(request: Request):
    user = request_user(request)
    try:
        status = pilot_access.acquire_lease(user)
    except EditLeaseError as exc:
        audit_request(request, 423, "edit_lease_acquire_blocked")
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    audit_request(request, 200, "edit_lease_acquired")
    return status


@app.post("/api/pilot/edit-lease/heartbeat")
async def heartbeat_pilot_edit_lease(request: Request):
    user = request_user(request)
    try:
        return pilot_access.heartbeat_lease(user)
    except EditLeaseError as exc:
        audit_request(request, 423, "edit_lease_heartbeat_failed")
        raise HTTPException(status_code=423, detail=str(exc)) from exc


@app.delete("/api/pilot/edit-lease")
async def release_pilot_edit_lease(request: Request):
    user = request_user(request)
    status = pilot_access.release_lease(user)
    audit_request(request, 200, "edit_lease_released")
    return status


@app.get("/api/health")
async def health_check():
    data_readable = os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.R_OK)
    return {
        "status": "success" if data_readable else "degraded",
        "message": "本地服务运行正常。" if data_readable else "运行数据暂不可读取。",
        "version": app.version,
        "release_sha": RELEASE_SHA[:40],
        "local_only": is_local_only_mode(),
        "data_readable": data_readable,
        "simulation_enabled": SIMULATION_ENABLED,
    }


@app.get("/api/wall")
async def get_wall_grid():
    return load_json(EMPTY_WALL_FILE, [])


@app.get("/api/holds/mapping")
async def get_holds_mapping(request: Request):
    local_mapping = load_json(HOLDS_MAPPING_FILE, {})
    if local_mapping:
        return resolve_local_holds_mapping(
            local_mapping,
            Path(HOLDS_IMAGES_DIR),
            Path(PROCESSED_HOLDS_IMAGES_DIR),
        )

    if should_use_supabase(request):
        try:
            user = await resolve_supabase_user(request)
            if user:
                return await supabase_repo.get_holds_mapping(user["id"])
        except SupabaseRepositoryError as exc:
            print(f"Supabase holds mapping fallback: {exc}")
    return local_mapping


@app.get("/api/holds/vectors")
async def get_holds_vectors(request: Request):
    local_vectors = load_json(HOLDS_VECTORS_FILE, {})
    if local_vectors:
        return local_vectors

    if should_use_supabase(request):
        try:
            user = await resolve_supabase_user(request)
            if user:
                return await supabase_repo.get_holds_vectors(user["id"])
        except SupabaseRepositoryError as exc:
            print(f"Supabase holds vectors fallback: {exc}")
    return local_vectors


@app.get("/api/holds/assets")
async def get_hold_assets(include_archived: bool = False):
    return load_hold_assets(include_archived=include_archived)


def extract_svg_path_from_image(image_bytes: bytes) -> str:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析上传图片")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return ""

    largest_contour = max(contours, key=cv2.contourArea)
    epsilon = 0.0005 * cv2.arcLength(largest_contour, True)
    approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)
    x, y, w, h = cv2.boundingRect(approx_contour)
    if w == 0 or h == 0:
        return ""

    scale = 100 / max(w, h)
    new_w, new_h = w * scale, h * scale
    offset_x = (100 - new_w) / 2
    offset_y = (100 - new_h) / 2
    points = approx_contour.reshape(-1, 2)
    normalized_points = [
        (((point[0] - x) * scale) + offset_x, ((point[1] - y) * scale) + offset_y)
        for point in points
    ]
    return "M " + " ".join(f"{px:.2f},{py:.2f}" for px, py in normalized_points) + " Z"


@app.post("/api/holds/upload")
async def upload_hold_image(request: Request):
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="服务器缺少 python-multipart，无法解析图片上传表单。请安装 requirements.txt。",
        ) from exc

    hold_type = str(form.get("hold_type") or "").strip()
    variant = str(form.get("variant") or "").strip()
    file = form.get("file")
    if not hold_type or not variant or file is None or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="请提供 hold_type、variant 和图片文件")

    image_bytes = await file.read()
    close_file = getattr(file, "close", None)
    if close_file:
        await close_file()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传图片为空")

    try:
        ext = os.path.splitext(getattr(file, "filename", "") or "")[1].lower() or ".png"
        filename = f"{uuid.uuid4()}{ext}"
        if member.get():
            if variant in read_json(HOLDS_MAPPING_FILE, {}).get(hold_type, {}) or variant in read_json(HOLDS_VECTORS_FILE, {}).get(hold_type, {}):
                raise HTTPException(403, '公共岩点不能覆盖，请使用新的岩点名称。')
            filename = member_key() + '/' + filename
        svg_path = extract_svg_path_from_image(image_bytes)
        if should_use_supabase(request):
            try:
                content_type = getattr(file, "content_type", None) or "image/png"
                user = await resolve_supabase_user(request)
                if user:
                    storage_path = await supabase_repo.upload_hold_image(filename, image_bytes, content_type, user["id"])
                    saved = await supabase_repo.upsert_hold_asset(
                        hold_type,
                        variant,
                        storage_path,
                        svg_path,
                        user["id"],
                        is_system=False,
                    )
                    return {"success": True, "image_path": saved.get("public_image_url"), "svg_path": saved.get("svg_path")}
            except SupabaseRepositoryError as exc:
                print(f"Supabase hold upload fallback: {exc}")

        if ext not in SUPPORTED_IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持 PNG、JPEG 或 WebP 图片")
        try:
            processed_bytes = process_hold_image_bytes(image_bytes)
        except HoldImageProcessingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        save_path = Path(HOLDS_IMAGES_DIR) / filename
        processed_name = processed_filename_for(Path(filename).name)
        if member.get():
            processed_name = member_key() + '/' + processed_name
        processed_path = Path(PROCESSED_HOLDS_IMAGES_DIR) / processed_name
        write_bytes_atomic(save_path, image_bytes)
        try:
            write_bytes_atomic(processed_path, processed_bytes)
        except Exception:
            save_path.unlink(missing_ok=True)
            raise

        mapping = load_json(HOLDS_MAPPING_FILE, {})
        mapping.setdefault(hold_type, {})[variant] = f"/images/processed/{processed_name}"
        vectors = load_json(HOLDS_VECTORS_FILE, {})
        vectors.setdefault(hold_type, {})[variant] = svg_path
        try:
            save_json(HOLDS_MAPPING_FILE, mapping)
            save_json(HOLDS_VECTORS_FILE, vectors)
            metadata = load_json(HOLDS_METADATA_FILE, {})
            metadata[hold_asset_key(hold_type, variant)] = {
                **metadata.get(hold_asset_key(hold_type, variant), {}),
                "archived_at": None,
                "updated_at": utc_now(),
            }
            save_json(HOLDS_METADATA_FILE, metadata)
        except Exception:
            save_path.unlink(missing_ok=True)
            processed_path.unlink(missing_ok=True)
            raise

        return {
            "success": True,
            "image_path": f"/images/processed/{processed_name}",
            "svg_path": vectors[hold_type][variant],
            "background_removed": True,
            "processing_version": PROCESSING_VERSION,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图片上传或向量化失败: {exc}") from exc


@app.delete("/api/holds/{hold_type}/{variant}")
async def delete_hold(hold_type: str, variant: str, request: Request):
    protect_public_hold(hold_type, variant)
    user = await resolve_supabase_user(request) if should_use_supabase(request) else None
    if should_use_supabase(request) and user:
        try:
            archived = await supabase_repo.archive_hold_asset(hold_type, variant, user["id"])
            if not archived:
                raise HTTPException(status_code=404, detail="未找到该岩点")
            return {"success": True, "message": "岩点已归档"}
        except SupabaseRepositoryError as exc:
            print(f"Supabase hold archive fallback: {exc}")

    mapping = load_json(HOLDS_MAPPING_FILE, {})
    vectors = load_json(HOLDS_VECTORS_FILE, {})
    if variant not in mapping.get(hold_type, {}) and variant not in vectors.get(hold_type, {}):
        raise HTTPException(status_code=404, detail="未找到该岩点")
    key = hold_asset_key(hold_type, variant)
    mutate_json(
        HOLDS_METADATA_FILE,
        {},
        lambda metadata: metadata.__setitem__(
            key,
            {**metadata.get(key, {}), "archived_at": utc_now(), "updated_at": utc_now()},
        ),
    )
    return {"success": True, "message": "岩点已归档"}


@app.post("/api/holds/{hold_type}/{variant}/restore")
async def restore_hold(hold_type: str, variant: str):
    protect_public_hold(hold_type, variant)
    mapping = load_json(HOLDS_MAPPING_FILE, {})
    vectors = load_json(HOLDS_VECTORS_FILE, {})
    if variant not in mapping.get(hold_type, {}) and variant not in vectors.get(hold_type, {}):
        raise HTTPException(status_code=404, detail="未找到该岩点")
    key = hold_asset_key(hold_type, variant)
    mutate_json(
        HOLDS_METADATA_FILE,
        {},
        lambda metadata: metadata.__setitem__(
            key,
            {**metadata.get(key, {}), "archived_at": None, "updated_at": utc_now()},
        ),
    )
    return {"success": True, "message": "岩点已恢复"}


@app.post("/api/save-board")
async def save_board(payload: Dict[str, Any], request: Request):
    user = await resolve_supabase_user(request) if should_use_supabase(request) else None
    if should_use_supabase(request) and user:
        try:
            normalized = normalize_board_payload(payload).model_dump(mode="json")
            saved = await supabase_repo.create_board(normalized, user["id"])
            return {"success": True, "message": "岩板已保存", **saved}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board create fallback: {exc}")

    board = normalize_board_payload(payload)
    board.saved_id = str(uuid.uuid4())
    saved = dump_board(board)
    if member.get():
        saved['visibility'] = 'private'
    mutate_json(SAVED_BOARDS_FILE, [], lambda boards: boards.append(saved))
    return {"success": True, "message": "岩板已保存", **saved}


@app.get("/api/my-boards", response_model=List[BoardAsset])
async def get_my_boards(request: Request, include_archived: bool = False):
    local_boards = load_boards()
    if local_boards:
        normalized = [normalize_board_payload(board).model_dump(mode="json") for board in local_boards]
        return normalized if include_archived else [board for board in normalized if not board.get("archived_at")]

    user = await resolve_supabase_user(request) if should_use_supabase(request) else None
    if should_use_supabase(request) and user:
        try:
            normalized = [normalize_board_payload(board).model_dump(mode="json") for board in await supabase_repo.list_boards(user["id"])]
            return normalized if include_archived else [board for board in normalized if not board.get("archived_at")]
        except SupabaseRepositoryError as exc:
            print(f"Supabase board list fallback: {exc}")
    return [normalize_board_payload(board).model_dump(mode="json") for board in local_boards]


@app.put("/api/my-boards/{saved_id}")
async def update_saved_board(saved_id: str, payload: Dict[str, Any], request: Request):
    user = await resolve_supabase_user(request) if should_use_supabase(request) else None
    if should_use_supabase(request) and user:
        try:
            if not str(payload.get("route_name", "")).strip():
                raise HTTPException(status_code=400, detail="岩板名称不能为空")
            saved = await supabase_repo.update_board(saved_id, payload, user["id"])
            return {"success": True, "message": "岩板已更新", **saved}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board update fallback: {exc}")

    def update_board(boards: List[Dict[str, Any]]) -> Dict[str, Any]:
        target_index = next((index for index, board in enumerate(boards) if board.get("saved_id") == saved_id), None)
        if target_index is None:
            raise HTTPException(status_code=404, detail="未找到该岩板")
        merged = {**boards[target_index], **payload, "saved_id": saved_id}
        if not str(merged.get("route_name", "")).strip():
            raise HTTPException(status_code=400, detail="岩板名称不能为空")
        saved = dump_board(normalize_board_payload(merged, saved_id=saved_id))
        boards[target_index] = saved
        return saved

    saved = mutate_json(SAVED_BOARDS_FILE, [], update_board)
    return {"success": True, "message": "岩板已更新", **saved}


@app.delete("/api/my-boards/{saved_id}")
async def delete_saved_board(saved_id: str, request: Request):
    user = await resolve_supabase_user(request) if should_use_supabase(request) else None
    if should_use_supabase(request) and user:
        try:
            archived = await supabase_repo.archive_board(saved_id, user["id"])
            if not archived:
                raise HTTPException(status_code=404, detail="未找到该岩板")
            return {"success": True, "message": "岩板已归档"}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board archive fallback: {exc}")

    def archive_board(boards: List[Dict[str, Any]]) -> None:
        target_index = next((index for index, board in enumerate(boards) if board.get("saved_id") == saved_id), None)
        if target_index is None:
            raise HTTPException(status_code=404, detail="未找到该岩板")
        boards[target_index] = {**boards[target_index], "archived_at": utc_now(), "updated_at": utc_now()}

    mutate_json(SAVED_BOARDS_FILE, [], archive_board)
    return {"success": True, "message": "岩板已归档"}


@app.post("/api/my-boards/{saved_id}/restore")
async def restore_saved_board(saved_id: str):
    def restore_board(boards: List[Dict[str, Any]]) -> Dict[str, Any]:
        target_index = next((index for index, board in enumerate(boards) if board.get("saved_id") == saved_id), None)
        if target_index is None:
            raise HTTPException(status_code=404, detail="未找到该岩板")
        restored_payload = {**boards[target_index], "archived_at": None, "updated_at": utc_now()}
        saved = dump_board(normalize_board_payload(restored_payload, saved_id=saved_id))
        boards[target_index] = saved
        return saved

    restored = mutate_json(SAVED_BOARDS_FILE, [], restore_board)
    return {"success": True, "message": "岩板已恢复", **restored}


@app.get("/api/standard-board/routes", response_model=StandardBoardRouteQueryResponse)
async def list_standard_board_routes(
    q: str | None = None,
    difficulty: str | None = None,
    predicted_grade: str | None = None,
    grade_warning: str | None = None,
    benchmark_only: bool = False,
    min_holds: int | None = None,
    max_holds: int | None = None,
    tag_ids: str | None = None,
    tag_match: str = "all",
    sort: str = "score_desc",
    limit: int = 24,
    offset: int = 0,
    valid_only: bool = True,
):
    return query_standard_routes(
        q=q,
        difficulty=difficulty,
        predicted_grade=predicted_grade,
        grade_warning=grade_warning,
        benchmark_only=benchmark_only,
        min_holds=min_holds,
        max_holds=max_holds,
        tag_ids=tag_ids,
        tag_match=tag_match if tag_match in {"all", "any"} else "all",
        sort=sort,
        limit=limit,
        offset=offset,
        valid_only=valid_only,
    )


@app.get("/api/standard-board/routes/{source_id}", response_model=StandardBoardRouteDetail)
async def get_standard_board_route(source_id: str):
    route = find_standard_route(source_id)
    if not route:
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return detail_for(route)


@app.get("/api/standard-board/routes/{source_id}/activity", response_model=StandardRouteActivityResponse)
async def get_standard_board_route_activity(source_id: str, request: Request):
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return await get_standard_activity(request, source_id)


@app.post("/api/standard-board/routes/{source_id}/favorite", response_model=StandardRouteActivityResponse)
async def favorite_standard_board_route(source_id: str, request: Request):
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return await append_standard_activity_event(
        request,
        source_id,
        "favorite",
        "收藏标准板线路",
        metadata={"active": True},
    )


@app.delete("/api/standard-board/routes/{source_id}/favorite", response_model=StandardRouteActivityResponse)
async def unfavorite_standard_board_route(source_id: str, request: Request):
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return await append_standard_activity_event(
        request,
        source_id,
        "favorite",
        "取消收藏标准板线路",
        metadata={"active": False},
    )


@app.post("/api/standard-board/routes/{source_id}/rating", response_model=StandardRouteActivityResponse)
async def rate_standard_board_route(source_id: str, payload: StandardRouteRatingRequest, request: Request):
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return await append_standard_activity_event(
        request,
        source_id,
        "rating",
        f"评分 {payload.rating}",
        rating=payload.rating,
    )


@app.post("/api/standard-board/routes/{source_id}/ascent-log", response_model=StandardRouteActivityResponse)
async def log_standard_board_ascent(source_id: str, payload: StandardRouteAscentLogRequest, request: Request):
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    return await append_standard_activity_event(
        request,
        source_id,
        "ascent_log",
        payload.notes or payload.result,
        metadata=payload.model_dump(mode="json"),
    )


@app.get("/api/standard-board/repairs", response_model=StandardBoardRepairQueryResponse)
async def list_standard_board_repairs(q: str | None = None, limit: int = 24, offset: int = 0, status: str | None = None):
    return query_standard_board_repairs(q=q, limit=limit, offset=offset, status=status)


@app.get("/api/standard-board/repairs/{source_id}", response_model=StandardBoardRepairCandidate)
async def get_standard_board_repair(source_id: str):
    candidate = find_standard_board_repair(source_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="未找到该待修复线路")
    return candidate


@app.get("/api/standard-board/repairs/{source_id}/comparison", response_model=StandardBoardRepairComparison)
async def compare_standard_board_repair(source_id: str):
    comparison = repair_comparison(source_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="未找到该待修复线路")
    return comparison


@app.get("/api/standard-board/repairs/{source_id}/preview", response_model=StandardBoardRouteDetail)
async def preview_standard_board_repair(source_id: str):
    candidate = find_standard_board_repair(source_id)
    route = find_standard_route(source_id)
    if not candidate or not route:
        raise HTTPException(status_code=404, detail="未找到该待修复线路")
    if candidate.repair_status != "repaired" or not candidate.repaired_roles:
        raise HTTPException(status_code=400, detail="该线路暂无可预览的修复结果")
    return detail_for(route, candidate.repaired_roles)


@app.post("/api/standard-board/repairs/publish", response_model=StandardBoardRepairPublishResponse)
async def publish_standard_board_repair_routes(payload: StandardBoardRepairPublishRequest):
    return publish_standard_board_repairs(payload.source_ids)


@app.post("/api/standard-board/generate", response_model=StandardBoardGenerateResponse)
async def generate_standard_board_route(payload: StandardBoardGenerateRequest):
    try:
        return generate_standard_route(
            target_difficulty=payload.target_difficulty,
            benchmark_only=payload.benchmark_only,
            variation=payload.variation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def require_simulation_enabled() -> None:
    if not SIMULATION_ENABLED:
        raise HTTPException(status_code=404, detail="仿真审核未在本次试运行中开放")


@app.get("/api/simulation/climber-profiles", response_model=List[ClimberProfile])
async def list_simulation_climber_profiles(ability_grade: str = DEFAULT_FONT_GRADE):
    require_simulation_enabled()
    return get_climber_profiles(ability_grade)


@app.get("/api/simulation/hold-profiles", response_model=List[HoldPhysicsProfile])
async def list_simulation_hold_profiles():
    require_simulation_enabled()
    return get_hold_profiles()


@app.put("/api/simulation/hold-profiles/{variant_id}", response_model=HoldPhysicsProfile)
async def save_simulation_hold_profile(variant_id: str, payload: HoldPhysicsProfile):
    require_simulation_enabled()
    return update_hold_profile(variant_id, payload)


@app.post(
    "/api/standard-board/routes/{source_id}/simulation",
    response_model=GenerationInitiated,
    status_code=202,
)
async def start_standard_board_simulation(source_id: str, payload: SimulationRequest, background_tasks: BackgroundTasks):
    require_simulation_enabled()
    if not find_standard_route(source_id):
        raise HTTPException(status_code=404, detail="未找到该标准板线路")
    task_id = str(uuid.uuid4())
    active_tasks[task_id] = task_envelope(task_id, "pending")
    background_tasks.add_task(run_and_store_simulation, task_id, simulate_route, source_id, payload)
    return GenerationInitiated(task_id=task_id, status="pending")


@app.get(
    "/api/standard-board/routes/{source_id}/simulation/latest",
    response_model=SimulationReport,
)
async def latest_standard_board_simulation(source_id: str):
    require_simulation_enabled()
    report = get_latest_report(source_id)
    if not report:
        raise HTTPException(status_code=404, detail="该线路尚无仿真报告")
    return report


@app.post(
    "/api/standard-board/simulations/batch",
    response_model=GenerationInitiated,
    status_code=202,
)
async def start_standard_board_simulation_batch(payload: SimulationBatchRequest, background_tasks: BackgroundTasks):
    require_simulation_enabled()
    task_id = str(uuid.uuid4())
    active_tasks[task_id] = task_envelope(task_id, "pending")
    background_tasks.add_task(run_and_store_simulation, task_id, simulate_batch, payload)
    return GenerationInitiated(task_id=task_id, status="pending")


@app.post(
    "/api/simulation/reports/{report_id}/repair-candidates",
    response_model=List[SimulationRepairCandidate],
)
async def create_simulation_repair_candidates(report_id: str):
    require_simulation_enabled()
    try:
        return await asyncio.to_thread(generate_repair_candidates, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/api/simulation/reports/{report_id}/feedback",
    response_model=SimulationFeedbackRecord,
)
async def submit_simulation_feedback(report_id: str, payload: SimulationFeedback):
    require_simulation_enabled()
    try:
        return record_feedback(report_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/generate", response_model=GenerationInitiated, status_code=202)
async def generate_route(payload: Dict[str, Any], request: Request):
    task_id = str(uuid.uuid4())
    use_supabase = should_use_supabase(request)
    user = await resolve_supabase_user(request) if use_supabase else None
    owner_id = user["id"] if user else (extract_user_id_from_auth_header(request.headers.get("authorization")) if use_supabase else None)
    active_tasks[task_id] = task_envelope(task_id, "pending")
    if use_supabase:
        if not owner_id:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            await supabase_repo.create_task(task_id, payload, owner_id)
        except SupabaseRepositoryError as exc:
            print(f"Supabase task create skipped: {exc}")
    task = asyncio.create_task(run_and_store_generation(task_id, payload, owner_id))
    tasks[task_id] = task
    return GenerationInitiated(task_id=task_id, status="pending")


@app.get("/api/result/{task_id}", response_model=TaskEnvelope)
async def get_generation_result(task_id: str):
    task_info = active_tasks.get(task_id)
    if not task_info and should_use_supabase():
        try:
            task_info = await supabase_repo.get_task(task_id)
        except SupabaseRepositoryError as exc:
            print(f"Supabase task result fallback: {exc}")
    if not task_info:
        if is_local_only_mode():
            raise HTTPException(status_code=404, detail="本地任务不存在或服务已重启")
        raise HTTPException(status_code=404, detail="任务未找到或已过期")
    return task_info


@app.post("/api/cancel/{task_id}")
async def cancel_generation_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        if task_id in active_tasks and active_tasks[task_id]["status"] in {"completed", "failed", "cancelled"}:
            return {"status": active_tasks[task_id]["status"], "message": "任务已结束，无法取消"}
        raise HTTPException(status_code=404, detail="未找到正在运行的任务")

    task.cancel()
    await update_supabase_task(task_id, "cancelled", error="取消请求已发送")
    active_tasks[task_id] = task_envelope(task_id, "cancelled", error="取消请求已发送")
    return {"status": "cancelled", "message": "取消请求已发送"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("CLIMB_HOST", "127.0.0.1"),
        port=8000,
        reload=True,
        loop="auto",
        timeout_keep_alive=65,
    )
