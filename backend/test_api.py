
import requests
import json

url = "http://127.0.0.1:8008/api/generate"

payload = {
    "climber_height_cm": 175,
    "climber_span_cm": 175,
    "target_difficulty": "V3",
    "recipe": {
        "Jug": {"count": 4, "variant": "random"},
        "Crimp": {"count": 6, "variant": "random"},
        "Sloper": {"count": 4, "variant": "random"},
        "Pinch": {"count": 2, "variant": "random"},
        "Pocket": {"count": 2, "variant": "random"},
        "Foot": {"count": 6, "variant": "random"}
    }
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, data=json.dumps(payload))

print(response.status_code)
print(response.json())
