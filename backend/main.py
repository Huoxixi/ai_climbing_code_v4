"""
FastAPI entrypoint for the climbing board backend.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent.controller import generate_route_with_reflection
from agent.experiments import run_ai_experiment
from core.models import (
    AIExperimentRequest,
    BoardAsset,
    FinalRoute,
    GenerationInitiated,
    RouteRequest,
    RouteResponse,
    TaskEnvelope,
)
from core.state import active_tasks
from core.supabase_repo import (
    SupabaseRepository,
    SupabaseRepositoryError,
    extract_bearer_token,
    extract_user_id_from_auth_header,
    is_supabase_configured,
)

load_dotenv()


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/result/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

app = FastAPI(title="ZXT AI Climbing Route Engine", version="7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = "data"
HOLDS_IMAGES_DIR = os.path.join(DATA_DIR, "holds_images")
HOLDS_MAPPING_FILE = os.path.join(DATA_DIR, "holds_mapping.json")
HOLDS_VECTORS_FILE = os.path.join(DATA_DIR, "holds_vectors.json")
SAVED_BOARDS_FILE = os.path.join(DATA_DIR, "saved_boards.json")
EMPTY_WALL_FILE = os.path.join(DATA_DIR, "empty_wall_grid.json")

app.mount("/images", StaticFiles(directory=HOLDS_IMAGES_DIR), name="images")

tasks: Dict[str, asyncio.Task] = {}
supabase_repo = SupabaseRepository()


async def resolve_supabase_user(request: Request) -> dict | None:
    if not is_supabase_configured():
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
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        return default


def save_json(file_path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def task_envelope(task_id: str, status: str, result: Any = None, error: str | None = None) -> Dict[str, Any]:
    return {"task_id": task_id, "status": status, "result": result, "error": error}


def serialize_result(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


async def update_supabase_task(task_id: str, status: str, result: Any = None, error: str | None = None) -> None:
    if not is_supabase_configured():
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
            result = await run_ai_experiment(AIExperimentRequest(**payload))
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


def load_boards() -> List[Dict[str, Any]]:
    raw_boards = load_json(SAVED_BOARDS_FILE, [])
    if not isinstance(raw_boards, list):
        return []
    return raw_boards


def dump_board(board: BoardAsset) -> Dict[str, Any]:
    return board.model_dump(mode="json")


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
    data.setdefault("difficulty", "V3")
    data.setdefault("created_at", now)
    data["updated_at"] = data.get("updated_at") or now
    return BoardAsset(**data)


@app.get("/api/health")
async def health_check():
    return {"status": "success", "message": "ZXT Engine is running.", "version": app.version}


@app.get("/api/wall")
async def get_wall_grid():
    return load_json(EMPTY_WALL_FILE, [])


@app.get("/api/holds/mapping")
async def get_holds_mapping(request: Request):
    if is_supabase_configured():
        try:
            user = await resolve_supabase_user(request)
            return await supabase_repo.get_holds_mapping(user["id"] if user else None)
        except SupabaseRepositoryError as exc:
            print(f"Supabase holds mapping fallback: {exc}")
    return load_json(HOLDS_MAPPING_FILE, {})


@app.get("/api/holds/vectors")
async def get_holds_vectors(request: Request):
    if is_supabase_configured():
        try:
            user = await resolve_supabase_user(request)
            return await supabase_repo.get_holds_vectors(user["id"] if user else None)
        except SupabaseRepositoryError as exc:
            print(f"Supabase holds vectors fallback: {exc}")
    return load_json(HOLDS_VECTORS_FILE, {})


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
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传图片为空")

    try:
        ext = os.path.splitext(getattr(file, "filename", "") or "")[1] or ".png"
        filename = f"{uuid.uuid4()}{ext}"
        svg_path = extract_svg_path_from_image(image_bytes)
        if is_supabase_configured():
            try:
                content_type = getattr(file, "content_type", None) or "image/png"
                user = await resolve_supabase_user(request)
                if not user:
                    raise HTTPException(status_code=401, detail="Supabase login required")
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

        save_path = os.path.join(HOLDS_IMAGES_DIR, filename)
        os.makedirs(HOLDS_IMAGES_DIR, exist_ok=True)
        with open(save_path, "wb") as buffer:
            buffer.write(image_bytes)

        mapping = load_json(HOLDS_MAPPING_FILE, {})
        mapping.setdefault(hold_type, {})[variant] = f"/images/{filename}"
        save_json(HOLDS_MAPPING_FILE, mapping)

        vectors = load_json(HOLDS_VECTORS_FILE, {})
        vectors.setdefault(hold_type, {})[variant] = svg_path
        save_json(HOLDS_VECTORS_FILE, vectors)

        return {"success": True, "image_path": mapping[hold_type][variant], "svg_path": vectors[hold_type][variant]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"图片上传或向量化失败: {exc}") from exc


@app.delete("/api/holds/{hold_type}/{variant}")
async def delete_hold(hold_type: str, variant: str, request: Request):
    if is_supabase_configured():
        user = await resolve_supabase_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            archived = await supabase_repo.archive_hold_asset(hold_type, variant, user["id"])
            if not archived:
                raise HTTPException(status_code=404, detail="未找到该岩点")
            return {"success": True, "message": "岩点已归档"}
        except SupabaseRepositoryError as exc:
            print(f"Supabase hold archive fallback: {exc}")

    mapping = load_json(HOLDS_MAPPING_FILE, {})
    vectors = load_json(HOLDS_VECTORS_FILE, {})

    if hold_type in mapping and variant in mapping[hold_type]:
        mapping[hold_type].pop(variant)
        if not mapping[hold_type]:
            del mapping[hold_type]
        save_json(HOLDS_MAPPING_FILE, mapping)

    if hold_type in vectors and variant in vectors[hold_type]:
        vectors[hold_type].pop(variant)
        if not vectors[hold_type]:
            del vectors[hold_type]
        save_json(HOLDS_VECTORS_FILE, vectors)

    return {"success": True, "message": "岩点已删除"}


@app.post("/api/save-board")
async def save_board(payload: Dict[str, Any], request: Request):
    user = await resolve_supabase_user(request)
    owner_id = user["id"] if user else extract_user_id_from_auth_header(request.headers.get("authorization"))
    if is_supabase_configured():
        if not owner_id:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            normalized = normalize_board_payload(payload).model_dump(mode="json")
            saved = await supabase_repo.create_board(normalized, owner_id)
            return {"success": True, "message": "岩板已保存", **saved}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board create fallback: {exc}")

    boards = load_boards()
    board = normalize_board_payload(payload)
    board.saved_id = str(uuid.uuid4())
    boards.append(dump_board(board))
    save_json(SAVED_BOARDS_FILE, boards)
    return {"success": True, "message": "岩板已保存", **dump_board(board)}


@app.get("/api/my-boards", response_model=List[BoardAsset])
async def get_my_boards(request: Request):
    user = await resolve_supabase_user(request)
    owner_id = user["id"] if user else extract_user_id_from_auth_header(request.headers.get("authorization"))
    if is_supabase_configured():
        if not owner_id:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            return [normalize_board_payload(board).model_dump(mode="json") for board in await supabase_repo.list_boards(owner_id)]
        except SupabaseRepositoryError as exc:
            print(f"Supabase board list fallback: {exc}")
    return [normalize_board_payload(board).model_dump(mode="json") for board in load_boards()]


@app.put("/api/my-boards/{saved_id}")
async def update_saved_board(saved_id: str, payload: Dict[str, Any], request: Request):
    user = await resolve_supabase_user(request)
    owner_id = user["id"] if user else extract_user_id_from_auth_header(request.headers.get("authorization"))
    if is_supabase_configured():
        if not owner_id:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            if not str(payload.get("route_name", "")).strip():
                raise HTTPException(status_code=400, detail="岩板名称不能为空")
            saved = await supabase_repo.update_board(saved_id, payload, owner_id)
            return {"success": True, "message": "岩板已更新", **saved}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board update fallback: {exc}")

    boards = load_boards()
    target_index = next((index for index, board in enumerate(boards) if board.get("saved_id") == saved_id), None)
    if target_index is None:
        raise HTTPException(status_code=404, detail="未找到该岩板")

    existing = boards[target_index]
    merged = {**existing, **payload, "saved_id": saved_id}
    if not str(merged.get("route_name", "")).strip():
        raise HTTPException(status_code=400, detail="岩板名称不能为空")

    board = normalize_board_payload(merged, saved_id=saved_id)
    boards[target_index] = dump_board(board)
    save_json(SAVED_BOARDS_FILE, boards)
    return {"success": True, "message": "岩板已更新", **dump_board(board)}


@app.delete("/api/my-boards/{saved_id}")
async def delete_saved_board(saved_id: str, request: Request):
    if is_supabase_configured():
        user = await resolve_supabase_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            archived = await supabase_repo.archive_board(saved_id, user["id"])
            if not archived:
                raise HTTPException(status_code=404, detail="未找到该岩板")
            return {"success": True, "message": "岩板已归档"}
        except SupabaseRepositoryError as exc:
            print(f"Supabase board archive fallback: {exc}")

    boards = load_boards()
    filtered = [board for board in boards if board.get("saved_id") != saved_id]
    if len(filtered) == len(boards):
        raise HTTPException(status_code=404, detail="未找到该岩板")
    save_json(SAVED_BOARDS_FILE, filtered)
    return {"success": True, "message": "岩板已删除"}


@app.post("/api/generate", response_model=GenerationInitiated, status_code=202)
async def generate_route(payload: Dict[str, Any], background_tasks: BackgroundTasks, request: Request):
    task_id = str(uuid.uuid4())
    user = await resolve_supabase_user(request)
    owner_id = user["id"] if user else extract_user_id_from_auth_header(request.headers.get("authorization"))
    active_tasks[task_id] = task_envelope(task_id, "pending")
    if is_supabase_configured():
        if not owner_id:
            raise HTTPException(status_code=401, detail="Supabase login required")
        try:
            await supabase_repo.create_task(task_id, payload, owner_id)
        except SupabaseRepositoryError as exc:
            print(f"Supabase task create skipped: {exc}")
    background_tasks.add_task(run_and_store_generation, task_id, payload, owner_id)
    return GenerationInitiated(task_id=task_id, status="pending")


@app.get("/api/result/{task_id}", response_model=TaskEnvelope)
async def get_generation_result(task_id: str):
    task_info = active_tasks.get(task_id)
    if not task_info and is_supabase_configured():
        try:
            task_info = await supabase_repo.get_task(task_id)
        except SupabaseRepositoryError as exc:
            print(f"Supabase task result fallback: {exc}")
    if not task_info:
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

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, loop="auto", timeout_keep_alive=65)
