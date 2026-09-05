"""User-scoped server-side vision credentials. Never return stored secrets."""
import base64
import hashlib
import json
import os
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator

MODEL = 'deepseek-v4-flash-vision-exp'


class SecretRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse({'detail': '请输入有效的 API 密钥。'}, status_code=422)
            response.headers['Cache-Control'] = 'no-store'
            return response
        return safe_handler


class VisionKey(BaseModel):
    api_key: str = Field(default='', max_length=512, repr=False)

    @field_validator('api_key')
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if value and (len(value) < 8 or any(ord(c) < 33 or ord(c) > 126 for c in value)):
            raise ValueError('请输入有效的 API 密钥')
        return value


def key_path(root, owner):
    return Path(root) / 'private-settings' / (hashlib.sha256(owner.encode()).hexdigest() + '.json')


def get_visual_key(root, owner):
    path = key_path(root, owner)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))['api_key']
    return os.getenv('PHOTO_ROUTE_VISION_KEY') or os.getenv('DEEPSEEK_API_KEY') or ''


def save_visual_key(root, owner, key):
    path = key_path(root, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temporary, 'x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump({'api_key': key}, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def test_connection(key, *, client=None):
    if not key:
        return {'connected': False, 'message': '请先输入或保存 API 密钥。'}
    # A generated image tests the exact vision model, without sending user photos.
    picture = np.full((64, 64, 3), 255, np.uint8)
    cv2.circle(picture, (32, 32), 18, (0, 180, 255), -1)
    encoded = base64.b64encode(cv2.imencode('.png', picture)[1].tobytes()).decode()
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10))
    try:
        response = client.post('https://api.deepseek.com/chat/completions',
            headers={'Authorization': 'Bearer ' + key}, json={
                'model': MODEL, 'max_tokens': 64,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Briefly name the shape visible in this image.'},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + encoded}},
                ]}],
            })
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('empty response')
        return {'connected': True, 'message': '连接成功，视觉模型已响应图片请求。'}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        message = '密钥无效或无权访问视觉模型。' if code in {401, 403} else '账户余额不足，请检查 DeepSeek 账户。' if code == 402 else '请求过于频繁，请稍后重试。' if code == 429 else '视觉服务暂不可用，请稍后重试。'
        return {'connected': False, 'message': message}
    except httpx.TimeoutException:
        return {'connected': False, 'message': '连接超时，请稍后重试。'}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return {'connected': False, 'message': '连接未成功，请检查网络或稍后重试。'}
    finally:
        if owned: client.close()


def settings_router(root):
    router = APIRouter(prefix='/api/settings/vision', route_class=SecretRoute)

    @router.get('')
    def status(request: Request):
        return {'configured': bool(get_visual_key(root, request.state.pilot_user.username)), 'model': MODEL}

    @router.put('')
    def save(payload: VisionKey, request: Request):
        if not payload.api_key:
            return {'configured': bool(get_visual_key(root, request.state.pilot_user.username))}
        save_visual_key(root, request.state.pilot_user.username, payload.api_key)
        return {'configured': True}

    @router.post('/test')
    def test(payload: VisionKey, request: Request):
        return test_connection(payload.api_key or get_visual_key(root, request.state.pilot_user.username))

    return router
