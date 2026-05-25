import json

import requests


url = "http://127.0.0.1:8000/api/generate"

payload = {
    "mode": "review_route",
    "user_requirements": "检查当前路线是否存在明显动作风险，不要修改原路线。",
    "board": {
        "route_name": "Local smoke test board",
        "setter_commentary": "",
        "difficulty": "V3",
        "source_type": "manual",
        "visibility": "private",
        "tags": [],
        "board_spec": {
            "preset_id": "classic-11x18",
            "template_key": "spray-small",
            "label": "Classic 11x18",
            "columns": 11,
            "rows": 18,
        },
        "placed_holds": [
            {"id": "D2", "x": "D", "y": 2, "hold_type": "Foot", "is_start": True},
            {"id": "F5", "x": "F", "y": 5, "hold_type": "Jug", "is_start": True},
            {"id": "H2", "x": "H", "y": 2, "hold_type": "Foot", "is_start": True},
            {"id": "F18", "x": "F", "y": 18, "hold_type": "Jug"},
        ],
        "beta_sequence": [],
    },
}

response = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
print(response.status_code)
print(response.json())
