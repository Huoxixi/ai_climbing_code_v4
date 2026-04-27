from typing import Dict, Any

# active_tasks 用于跟踪所有任务的状态、结果或错误
# 格式: {task_id: {"status": "RUNNING" | "SUCCESS" | "ERROR", "result": RouteResponse | None, "error": str | None}}
active_tasks: Dict[str, Dict[str, Any]] = {}
