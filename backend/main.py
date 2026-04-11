
"""
backend/main.py
"""

import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from dotenv import load_dotenv

# 加载环境变量 (.env)
load_dotenv()

from core.models import RouteRequest, RouteResponse
from agent.controller import generate_route_with_reflection

app = FastAPI(
    title="智行通途 (ZXT) - AI 攀岩定线引擎", 
    version="6.0" 
)

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

@app.post("/api/generate", response_model=RouteResponse)
async def generate_route(request: RouteRequest):
    """
    核心定线端点：已全面接入 PCG 漏斗架构
    1. Generator (批量撒点)
    2. Validator (物理初筛)
    3. A* Solver (寻路评分)
    4. LLM Curator (艺术决选)
    """
    try:
        response = await generate_route_with_reflection(request)
        return response
    except ValueError as ve:
        # 处理业务逻辑错误 (如无法生成符合要求的路线)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        # 处理服务器内部错误
        print(f"造物主引擎崩溃: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
