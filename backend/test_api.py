import requests


URL = "http://127.0.0.1:8000/api/generate"
PAYLOAD = {
    "mode": "review_route",
    "review_focus": "overall",
    "board": {
        "route_name": "Local smoke test board",
        "setter_commentary": "",
        "difficulty": "6B+",
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


def run_manual_smoke_test() -> None:
    """Explicit local smoke test; importing this module never sends a request."""
    response = requests.post(URL, json=PAYLOAD, timeout=10)
    response.raise_for_status()
    print(response.status_code)
    print(response.json())


if __name__ == "__main__":
    run_manual_smoke_test()
