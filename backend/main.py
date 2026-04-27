
"""
backend/main.py
"""

import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import uuid
import cv2
import numpy as np

# 加载环境变量 (.env)
load_dotenv()

from core.models import RouteRequest, RouteResponse, FinalRoute, GenerationInitiated
from agent.controller import generate_route_with_reflection

app = FastAPI(
    title="智行通途 (ZXT) - AI 攀岩定线引擎",
    version="6.0"
)

# --- App State ---
tasks: Dict[str, asyncio.Task] = {}
results: Dict[str, Any] = {}


# --- Background Task Runner ---
async def run_and_store_generation(task_id: str, request: RouteRequest):
    """后台运行生成任务并存储结果"""
    try:
        task = asyncio.create_task(generate_route_with_reflection(request))
        tasks[task_id] = task
        result = await task
        results[task_id] = result
    except asyncio.CancelledError:
        results[task_id] = RouteResponse(selected_routes=[], failure_suggestion="任务已被用户取消")
    except Exception as e:
        print(f"Task {task_id} failed: {e}")
        results[task_id] = RouteResponse(selected_routes=[], failure_suggestion=f"生成失败: {e}")
    finally:
        if task_id in tasks:
            del tasks[task_id]

# 静态文件目录
app.mount("/images", StaticFiles(directory="data/holds_images"), name="images")

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_empty_wall() -> List[Dict[str, Any]]:
    path = os.path.join("data", "empty_wall_grid.json")
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"空白墙加载失败: {e}")
        return []

empty_wall = load_empty_wall()

@app.get("/api/health")
async def health_check():
    return {"status": "success", "message": "ZXT Engine is running. Funnel architecture active."}

@app.get("/api/wall")
async def get_wall_grid():
    return empty_wall

HOLDS_MAPPING_FILE = "data/holds_mapping.json"
HOLDS_VECTORS_FILE = "data/holds_vectors.json"

# --- Helper Functions for Data Persistence ---
def get_json_data(file_path: str) -> Dict:
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json_data(file_path: str, data: Dict):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@app.get("/api/holds/mapping")
async def get_holds_mapping():
    return get_json_data(HOLDS_MAPPING_FILE)

@app.get("/api/holds/vectors")
async def get_holds_vectors():
    return get_json_data(HOLDS_VECTORS_FILE)

def extract_svg_path_from_image(image_bytes: bytes) -> str:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return ""

    largest_contour = max(contours, key=cv2.contourArea)
    arc_length = cv2.arcLength(largest_contour, True)
    epsilon = 0.0005 * arc_length
    approx_contour = cv2.approxPolyDP(largest_contour, epsilon, True)

    x, y, w, h = cv2.boundingRect(approx_contour)
    if w == 0 or h == 0: return ""
    
    points = approx_contour.reshape(-1, 2)
    scale = 100 / max(w, h)
    new_w, new_h = w * scale, h * scale
    offset_x = (100 - new_w) / 2
    offset_y = (100 - new_h) / 2

    normalized_points = [
        (((p[0] - x) * scale) + offset_x, ((p[1] - y) * scale) + offset_y)
        for p in points
    ]

    if not normalized_points:
        return ""
    
    return "M " + " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in normalized_points) + " Z"

@app.post("/api/holds/upload")
async def upload_hold_image(
    hold_type: str = Form(...),
    variant: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        image_bytes = await file.read()
        
        # --- Image File Persistence ---
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        save_path = os.path.join("data", "holds_images", filename)
        with open(save_path, "wb") as buffer:
            buffer.write(image_bytes)

        # --- Image Path Mapping Persistence ---
        mapping = get_json_data(HOLDS_MAPPING_FILE)
        if hold_type not in mapping: mapping[hold_type] = {}
        mapping[hold_type][variant] = f"/images/{filename}"
        save_json_data(HOLDS_MAPPING_FILE, mapping)

        # --- Vector Path Persistence ---
        svg_path = extract_svg_path_from_image(image_bytes)
        vectors = get_json_data(HOLDS_VECTORS_FILE)
        if hold_type not in vectors: vectors[hold_type] = {}
        vectors[hold_type][variant] = svg_path
        save_json_data(HOLDS_VECTORS_FILE, vectors)

        return {"success": True, "image_path": mapping[hold_type][variant], "svg_path": svg_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片上传及矢量化处理失败: {e}")

@app.delete("/api/holds/{hold_type}/{variant}")
async def delete_hold(hold_type: str, variant: str):
    try:
        # --- Delete from Image Mapping ---
        mapping = get_json_data(HOLDS_MAPPING_FILE)
        image_path_to_delete = None
        if hold_type in mapping and variant in mapping[hold_type]:
            image_path_to_delete = mapping[hold_type].pop(variant)
            if not mapping[hold_type]: # Remove type if empty
                del mapping[hold_type]
            save_json_data(HOLDS_MAPPING_FILE, mapping)

        # --- Delete from Vector Mapping ---
        vectors = get_json_data(HOLDS_VECTORS_FILE)
        if hold_type in vectors and variant in vectors[hold_type]:
            vectors[hold_type].pop(variant)
            if not vectors[hold_type]:
                 del vectors[hold_type]
            save_json_data(HOLDS_VECTORS_FILE, vectors)

        # --- Delete Physical Image File ---
        if image_path_to_delete:
            physical_path = os.path.join("data", "holds_images", os.path.basename(image_path_to_delete))
            if os.path.exists(physical_path):
                os.remove(physical_path)
        
        return {"success": True, "message": f"岩点 '{hold_type} - {variant}' 已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除岩点失败: {e}")

# --- Board Persistence ---
SAVED_BOARDS_FILE = os.path.join("data", "saved_boards.json")

@app.post("/api/save-board")
async def save_board(route: FinalRoute):
    try:
        boards = []
        if os.path.exists(SAVED_BOARDS_FILE):
            with open(SAVED_BOARDS_FILE, "r", encoding="utf-8") as f:
                boards = json.load(f)
        
        board_data = route.dict()
        board_data["saved_id"] = str(uuid.uuid4())
        boards.append(board_data)

        with open(SAVED_BOARDS_FILE, "w", encoding="utf-8") as f:
            json.dump(boards, f, indent=2, ensure_ascii=False)
            
        return {"success": True, "message": "岩板已保存!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法保存岩板: {e}")

@app.get("/api/my-boards", response_model=List[FinalRoute])
async def get_my_boards():
    if not os.path.exists(SAVED_BOARDS_FILE):
        return []
    try:
        with open(SAVED_BOARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法加载已保存的岩板: {e}")

@app.post("/api/generate", response_model=GenerationInitiated, status_code=202)
async def generate_route(request: RouteRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    background_tasks.add_task(run_and_store_generation, task_id, request)
    return GenerationInitiated(task_id=task_id)

@app.get("/api/result/{task_id}")
async def get_generation_result(task_id: str):
    if task_id in results:
        result = results.pop(task_id)
        if isinstance(result, Exception):
             raise HTTPException(status_code=500, detail=str(result))
        return result
    elif task_id in tasks:
        return {"status": "RUNNING"}
    else:
        raise HTTPException(status_code=404, detail="任务未找到或已过期")

@app.post("/api/cancel/{task_id}")
async def cancel_generation_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="无法取消：未找到正在运行的任务")
    
    tasks[task_id].cancel()
    # 等待一小段时间以确保取消信号传播
    await asyncio.sleep(0.1)
    
    # 从 tasks 字典中移除任务，无论它是否成功取消
    if task_id in tasks:
        del tasks[task_id]
        
    # 在 results 中放置一个“已取消”的标记
    results[task_id] = RouteResponse(selected_routes=[], failure_suggestion="任务已被用户成功取消")

    return {"status": "CANCELLED", "message": "取消请求已发送"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, loop="auto", timeout_keep_alive=65)
