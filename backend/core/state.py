from typing import Any, Dict

# {task_id: {"status": "pending|running|completed|failed|cancelled", "result": Any, "error": str | None}}
active_tasks: Dict[str, Dict[str, Any]] = {}
