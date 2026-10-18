"""Serve the built UI behind an outer instance guard (including media/Range)."""
import hmac
import json
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.requests import Request as StarletteRequest

from desktop import VERSION
from desktop import credentials

COOKIE = "ai_climbing_desktop"


class InstanceGuard:
    def __init__(self, app, token, origin):
        self.app, self.token, self.origin = app, token, origin
        self.host = origin.removeprefix("http://")

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        client = scope.get("client")
        valid_host = headers.get("host") == self.host and client and client[0] in {"127.0.0.1", "::1", "testclient"}
        valid_origin = headers.get("origin") in {None, self.origin}
        site = headers.get("sec-fetch-site")
        valid_site = site not in {"cross-site", "same-site"}
        bootstrap = scope["path"] == "/desktop/bootstrap/" + self.token
        request = StarletteRequest(scope)
        supplied = headers.get("x-desktop-token") or request.cookies.get(COOKIE, "")
        authorized = bootstrap or hmac.compare_digest(supplied.encode("utf-8"), self.token.encode("utf-8"))
        if not (valid_host and valid_origin and valid_site and authorized):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "请从攀岩桌面程序访问。"}, status_code=403)(scope, receive, send)
        async def protected_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"frame-ancestors 'none'; object-src 'none'; base-uri 'self'"),
                ])
            await send(message)
        return await self.app(scope, receive, protected_send)


def create_app(paths, token, origin, *, backend=None, activate=None, probe_media=None, choose_storage=None):
    if backend is None:
        from boulder_local_app import app as backend
    @asynccontextmanager
    async def lifespan(app):
        async with backend.router.lifespan_context(backend):
            yield
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/desktop/bootstrap/{provided}")
    def bootstrap(provided):
        response = RedirectResponse("/#/photo-routes", status_code=303)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/desktop/status")
    def status():
        from core.replay_pose_rtmw import model_status
        configured = credentials.load(paths.config)
        from desktop.storage import read_settings
        update_label = None
        try:
            update_label = json.loads((paths.install / 'local-update.json').read_text('utf-8')).get('update_label')
        except (OSError, ValueError):
            pass
        return {"desktop": True, "version": VERSION, "data_directory": str(paths.data),
                "update_label": update_label,
                "pending_data_directory": read_settings(paths).get('pending_directory'),
                "pose_configured": model_status(paths.install / "backend/model_assets/rtmw-l-384x288")["available"],
                "pose_provider": "local-rtmw", "pose_requires_credentials": False,
                "action_configured": bool(configured.get("DASHSCOPE_API_KEY")),
                "local_model_available": (paths.install / "models/verified-model_final.pth").is_file()}

    @app.post('/desktop/storage/choose')
    def select_storage():
        from desktop.storage import schedule_change
        try:
            selected = choose_storage() if choose_storage else None
            if not selected:
                return {'cancelled': True}
            return schedule_change(paths, selected)
        except ValueError as exc:
            return JSONResponse({'detail': str(exc)}, status_code=422)
        except Exception:
            return JSONResponse({'detail': '无法使用这个文件夹，请检查访问权限后重试。'}, status_code=422)

    @app.put("/desktop/cloud")
    async def cloud(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError()
            credentials.save(paths.config, payload)
        except Exception:
            return JSONResponse({"detail": "配置未保存，请检查输入和当前 Windows 用户权限。"}, status_code=422)
        return {"saved": True, "restart_required": True}

    @app.post("/desktop/activate")
    def show():
        if activate:
            activate()
        return {"active": True}

    if probe_media is not None:
        @app.get("/desktop/probe-video")
        def probe_video(download: bool = False):
            return FileResponse(probe_media, media_type="video/mp4",
                                filename="构造桌面导出.mp4" if download else None)

    # Mount the backend first for every existing API/media prefix; unknown API
    # paths stay 404 instead of being mistaken for the Vue index.
    for prefix in ("/api", "/images", "/photo-route-assets"):
        app.mount(prefix, PrefixApp(backend, prefix))
    app.mount("/", StaticFiles(directory=paths.install / "frontend/dist", html=True))
    return InstanceGuard(app, token, origin)


class PrefixApp:
    """Restore root_path for legacy routes already containing their prefix."""
    def __init__(self, app, prefix):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["root_path"] = scope.get("root_path", "").removesuffix(self.prefix)
        await self.app(scope, receive, send)
