"""Owner-scoped, configurable vision API. No legacy-provider fallback."""
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .photo_route_settings import SecretRoute


class VisionSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    base_url: str = Field(default='', max_length=512)
    model: str = Field(default='', max_length=128)
    api_mode: Literal['auto', 'chat_completions', 'responses'] = 'auto'
    api_key: str | None = Field(default=None, max_length=512, repr=False)
    cost_control_enabled: bool = False
    input_cny_per_million: float | None = Field(default=None, ge=0, le=100000)
    output_cny_per_million: float | None = Field(default=None, ge=0, le=100000)
    image_input_token_reserve: int = Field(default=4096, ge=256, le=1000000)
    image_cny_each: float = Field(default=0, ge=0, le=1000)
    budget_cny: float = Field(default=1, gt=0, le=100)

    @model_validator(mode='before')
    @classmethod
    def infer_explicit_endpoint(cls, value):
        if isinstance(value, dict) and value.get('api_mode', 'auto') == 'auto':
            address = str(value.get('base_url') or '').strip().rstrip('/')
            for suffix, mode in (('/responses', 'responses'), ('/chat/completions', 'chat_completions')):
                if address.endswith(suffix):
                    return {**value, 'api_mode': mode}
        return value

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        if not value:
            return value
        for suffix in ('/chat/completions', '/responses'):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
                break
        url = urlsplit(value)
        local = url.hostname in {'localhost', '127.0.0.1', '::1'}
        if (url.scheme != 'https' and not (local and url.scheme == 'http')) or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('请填写不含凭据的 HTTPS 服务地址')
        return value

    @field_validator('model', 'api_key')
    @classmethod
    def clean_text(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError('Invalid setting')
        return value.strip() if value is not None else None


def settings_path(root, owner):
    return Path(root) / 'private-settings' / ('replay-' + hashlib.sha256(owner.encode()).hexdigest() + '.json')


def load_settings(root, owner):
    path = settings_path(root, owner)
    if not path.is_file():
        return VisionSettings().model_dump()
    data = json.loads(path.read_text('utf-8'))
    if 'key_dpapi' in data:
        import base64
        from .replay_secret import crypt
        data['api_key'] = crypt(base64.b64decode(data.pop('key_dpapi')), decrypt=True).decode()
    return VisionSettings(**data).model_dump()


def save_settings(root, owner, payload):
    current = load_settings(root, owner)
    data = payload.model_dump()
    if payload.api_key is None:
        data['api_key'] = current.get('api_key')
    if os.name == 'nt' and data.get('api_key'):
        import base64
        from .replay_secret import crypt
        data['key_dpapi'] = base64.b64encode(crypt(data.pop('api_key').encode())).decode()
    path = settings_path(root, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def public_settings(data):
    output = {key: value for key, value in data.items() if key != 'api_key'}
    output['configured'] = bool(data.get('base_url') and data.get('model') and data.get('api_key'))
    output['pricing_configured'] = all(data.get(k) is not None for k in ('input_cny_per_million', 'output_cny_per_million'))
    output['ready'] = output['configured'] and (not data.get('cost_control_enabled', False) or output['pricing_configured'])
    return output


def configuration_fingerprint(data):
    # Include a digest of the secret, never the secret itself or in a public response.
    safe = public_settings(data)
    safe['credential_digest'] = hashlib.sha256((data.get('api_key') or '').encode()).hexdigest()
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()


def settings_router(root):
    router = APIRouter(prefix='/api/settings/replay-vision', route_class=SecretRoute)
    def owner(request):
        user = getattr(request.state, 'pilot_user', None)
        if user is None:
            raise HTTPException(401, '请先登录')
        return user.username

    @router.get('')
    def status(request: Request):
        return public_settings(load_settings(root, owner(request)))

    @router.put('')
    def save(payload: VisionSettings, request: Request):
        username = owner(request)
        save_settings(root, username, payload)
        return public_settings(load_settings(root, username))

    return router
