import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from dotenv import load_dotenv

# 加载环境变量 (.env)
load_dotenv()

from models import Hold, RouteRequest, RouteResponse
from agent import generate_route_with_reflection

app = FastAPI(
    title="Climbing AI Core Engine", 
    version="4.0"
)

# 🗡️ 斩杀跨域限制的护盾 (配置完美)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_mock_db() -> List[Hold]:
    try:
        with open("mock_holds.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return [Hold(**item) for item in data]
    except Exception as e:
        print(f"数据库加载失败: {e}")
        return []

holds_db = load_mock_db()

@app.get("/api/health")
async def health_check():
    return {"status": "success", "message": "API is running. Database loaded."}

@app.get("/api/holds", response_model=List[Hold])
async def get_holds():
    return holds_db

# 🚨 注意这里的路径是 /api/generate
@app.post("/api/generate", response_model=RouteResponse)
async def generate_route(request: RouteRequest):
    """
    核心定线端点：已全面接入 Agentic Workflow (大模型反思架构)
    """
    try:
        # 召唤混合智能体引擎
        response = await generate_route_with_reflection(
            climber=request.climber,
            holds=holds_db,
            target_difficulty=request.target_difficulty, # 🌟 核心修改：将前端传来的难度丢给 Agent
            max_retries=8
        )
        return response
    except Exception as e:
        # 兜底的全局异常捕捉
        raise HTTPException(status_code=500, detail=f"核心引擎崩溃: {str(e)}")