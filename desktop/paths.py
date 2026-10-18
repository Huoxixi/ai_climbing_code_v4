from dataclasses import dataclass
import os
from pathlib import Path
import uuid


@dataclass(frozen=True)
class DesktopPaths:
    install: Path
    user: Path
    storage: Path | None = None

    @property
    def data(self):
        return self.storage or self.user / "data"

    @property
    def config(self):
        return self.user / "config"

    @property
    def logs(self):
        return self.user / "logs"

    def prepare(self):
        for path in (self.data, self.config, self.logs, self.user / "tmp",
                     self.user / "cache", self.data / "holds_images",
                     self.data / "holds_images_processed"):
            path.mkdir(parents=True, exist_ok=True)
        probe = self.user / "tmp" / ("write-check-" + uuid.uuid4().hex)
        with probe.open("xb") as stream:
            stream.write(b"ok")
        probe.unlink()


def resolve_paths(install=None, user=None):
    install = Path(install or Path(__file__).resolve().parents[1]).resolve()
    if user is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise RuntimeError("Windows 用户应用数据目录不可用。")
        user = Path(local) / "AiClimbing"
    user = Path(user).resolve()
    # An explicit test override must never redirect the desktop into private data.
    if any(part.lower() in {".local", ".private"} for part in user.parts):
        raise RuntimeError("桌面实例不能使用开发私密目录。")
    if user == install or install in user.parents:
        raise RuntimeError("用户数据必须独立于程序安装目录。")
    settings = user / 'config' / 'storage.json'
    storage = None
    if settings.is_file():
        import json
        saved = json.loads(settings.read_text('utf-8'))
        if saved.get('directory'):
            storage = Path(saved['directory']).resolve()
            if not storage.is_dir():
                raise RuntimeError('用户数据目录不可用，请连接存储设备后重试。')
    return DesktopPaths(install, user, storage)


def isolated_environment(paths, inherited=None):
    inherited = os.environ if inherited is None else inherited
    # No inherited API credentials, proxy, PYTHONPATH, test videos or model paths.
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "LOCALAPPDATA", "APPDATA",
               "USERPROFILE", "USERNAME", "SYSTEMDRIVE", "PROGRAMFILES",
               "PROGRAMFILES(X86)", "PROGRAMDATA", "NUMBER_OF_PROCESSORS"}
    env = {key: value for key, value in inherited.items() if key.upper() in allowed}
    env.update({
        "PATH": str(paths.install / "runtime") + os.pathsep + str(Path(env.get("SYSTEMROOT", "C:/Windows")) / "System32"),
        "PYTHONPATH": os.pathsep.join((str(paths.install), str(paths.install / "backend"))),
        "PYTHONNOUSERSITE": "1", "PYTHON_DOTENV_DISABLED": "1",
        "LOCAL_ONLY": "true", "DISABLE_SUPABASE": "true", "APP_ENV": "desktop",
        "PILOT_AUTH_ENABLED": "false", "PILOT_QUICK_LOGIN_ENABLED": "false",
        "MEMBER_ACCOUNTS_ENABLED": "false", "ENABLE_SIMULATION": "false",
        "CLIMB_REPLAY_VISUAL_ENABLED": "1", "HF_HUB_OFFLINE": "1",
        "CLIMB_REPLAY_KEEP_HIGH_RESOLUTION": "1",
        "CLIMB_REPLAY_RTMW_MODEL_DIR": str(paths.install / "backend/model_assets/rtmw-l-384x288"),
        "CLIMB_REPLAY_RTMW_DEVICE": "auto",
        "PHOTO_ROUTE_DATA_DIR": str(paths.data / "photo_routes"),
        "PILOT_USERS_FILE": str(paths.data / "pilot_users.json"),
        "PILOT_AUDIT_FILE": str(paths.logs / "pilot_audit.jsonl"),
        "PHOTO_ROUTE_CLIMBING_MODEL_CONFIG": str(paths.install / "backend/model_assets/climbing-mask-rcnn-r50-fpn-1200.yaml"),
        "PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT": str(paths.install / "models/verified-model_final.pth"),
        "TEMP": str(paths.user / "tmp"), "TMP": str(paths.user / "tmp"),
        "TORCH_HOME": str(paths.user / "cache/torch"),
        "HF_HOME": str(paths.user / "cache/huggingface"),
        "MPLCONFIGDIR": str(paths.user / "cache/matplotlib"),
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env
