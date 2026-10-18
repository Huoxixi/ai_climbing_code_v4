"""Desktop lifecycle, independent port, health gate, and current-user singleton."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.request

from desktop.paths import resolve_paths, isolated_environment


def message(text):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, text, "攀岩桌面版", 0x10)
    else:
        print(text, file=sys.stderr)


class SingleInstance:
    def __init__(self, paths):
        self.paths = paths
        self.stream = None

    def acquire(self):
        import msvcrt
        self.stream = (self.paths.user / "runtime.lock").open("a+b")
        self.stream.seek(0)
        if (self.paths.user / "runtime.lock").stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            self.stream.close()
            self.stream = None
            return False

    def release(self):
        if self.stream:
            import msvcrt
            (self.paths.user / "instance.json").unlink(missing_ok=True)
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None


def activate_existing(paths):
    for _ in range(30):
        try:
            item = json.loads((paths.user / "instance.json").read_text(encoding="utf-8"))
            port = int(item["port"])
            if not 1024 <= port <= 65535:
                return False
            request = urllib.request.Request(f"http://127.0.0.1:{port}/desktop/activate", data=b"",
                                             headers={"X-Desktop-Token": item["token"]}, method="POST")
            with urllib.request.urlopen(request, timeout=1) as response:
                return response.status == 200
        except Exception:
            time.sleep(.5)
    return False


def attach_process_job():
    """Kernel cleans only this launcher's descendants after abnormal exit."""
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [("per_process", ctypes.c_longlong), ("per_job", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ro", "wo", "oo", "rb", "wb", "ob")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise RuntimeError("无法建立桌面进程保护，请重试。")
    # Keep handle open for the process lifetime (closing it kills the whole job).
    return handle


def verify_resources(paths):
    manifest_path = paths.install / "resources.json"
    if not manifest_path.is_file():
        raise RuntimeError("程序资源清单缺失，请重新解压完整程序包。")
    import hashlib
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["critical"]:
        path = (paths.install / item["path"]).resolve()
        if paths.install not in path.parents or not path.is_file():
            raise RuntimeError("程序资源缺失，请重新解压完整程序包。")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError("程序资源校验失败，请重新解压完整程序包。")


def require_webview2():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as key:
            if winreg.QueryValueEx(key, "Release")[0] < 394802:
                raise RuntimeError("Windows 用户环境缺少 .NET Framework 4.6.2 或更新版本，请按使用说明安装。")
    except OSError:
        raise RuntimeError("Windows 用户环境缺少 .NET Framework 4.6.2 或更新版本，请按使用说明安装。") from None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for prefix in (r"SOFTWARE\Microsoft", r"SOFTWARE\WOW6432Node\Microsoft"):
            try:
                with winreg.OpenKey(hive, prefix + r"\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}") as key:
                    value = winreg.QueryValueEx(key, "pv")[0]
                    if value and value != "0.0.0.0":
                        return
            except OSError:
                pass
    raise RuntimeError("Windows 用户环境缺少 Microsoft WebView2 Runtime。请按使用说明安装微软官方 Evergreen Standalone Installer x64 后重试。")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, help="Isolated verification directory only")
    parser.add_argument("--headless", action="store_true", help="Isolated build verification only")
    parser.add_argument("--ready-file", type=Path, help="Launcher-only startup progress signal")
    parser.add_argument("--window-check", type=Path, help="Constructed media window verification report")
    args = parser.parse_args(argv)
    try:
        paths = resolve_paths(user=args.data_root)
        paths.prepare()
    except Exception as exc:
        message(str(exc) if isinstance(exc, RuntimeError) else '存储目录不可用，请检查存储设备和访问权限后重试。')
        return 1
    if args.ready_file and args.ready_file.resolve().parent != (paths.user / 'tmp').resolve():
        raise RuntimeError("启动进度路径必须位于桌面临时目录。")
    lock = SingleInstance(paths)
    if not lock.acquire():
        if not activate_existing(paths):
            message("桌面程序正在启动或退出，请稍后再试。")
        return 0
    server = None
    window = None
    service_thread = None
    log = None
    try:
        verify_resources(paths)
        from desktop.storage import apply_pending_change
        try:
            paths = apply_pending_change(paths)
        except Exception:
            message('存储位置未切换，原资料保持完整。请在设置中重新选择可用的空文件夹。')
        if not args.headless:
            require_webview2()
        job_handle = attach_process_job()
        env = isolated_environment(paths)
        from desktop.credentials import load
        env.update(load(paths.config))
        os.environ.clear()
        os.environ.update(env)
        os.chdir(paths.user)
        for entry in (paths.install, paths.install / "backend"):
            sys.path.insert(0, str(entry))
        # Never persist raw exceptions, HTTP access, tokens, credentials or media.
        log = (paths.logs / "startup.log").open("a", encoding="utf-8")
        log.write("Starting isolated desktop runtime\n")
        log.flush()
        sys.stdout = sys.stderr = log
        import logging
        logging.disable(logging.CRITICAL)
        import uvicorn
        from desktop.server import create_app
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        token = secrets.token_urlsafe(32)
        def activate():
            if window:
                window.restore()
                window.show()
        probe_media = None
        if args.window_check:
            import subprocess
            from imageio_ffmpeg import get_ffmpeg_exe
            probe_media = paths.user / 'tmp' / ('constructed-' + secrets.token_hex(8) + '.mp4')
            subprocess.run([get_ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=8:duration=1', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', str(probe_media)], check=True, capture_output=True, timeout=30)
        def choose_storage():
            if not window:
                return None
            import webview
            selected = window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(paths.data.parent))
            return selected[0] if selected else None
        app = create_app(paths, token, origin, activate=activate, probe_media=probe_media,
                         choose_storage=choose_storage)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_config=None, access_log=False))
        service_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        service_thread.start()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if not service_thread.is_alive():
                raise RuntimeError("本机服务未能启动，请重新解压完整程序包。")
            try:
                request = urllib.request.Request(origin + "/api/health", headers={"X-Desktop-Token": token})
                with urllib.request.urlopen(request, timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError("启动等待超时，请检查可用内存后重试。")
        (paths.user / "instance.json").write_text(json.dumps({"pid": os.getpid(), "port": port, "token": token}), encoding="utf-8")
        log.write("Service ready\n")
        log.flush()
        if args.headless:
            while service_thread.is_alive():
                time.sleep(.2)
        else:
            import webview
            webview.settings["ALLOW_DOWNLOADS"] = True
            window = webview.create_window("攀岩桌面版", origin + "/desktop/bootstrap/" + token,
                                           width=1280, height=850, min_size=(960, 680),
                                           confirm_close=not bool(args.window_check), background_color="#fbfaf7")
            if args.ready_file:
                def signal_ready():
                    with args.ready_file.open('x', encoding='utf-8') as stream:
                        stream.write('ready')
                window.events.loaded += signal_ready
            if args.window_check:
                def verify_window():
                    from desktop.window_check import run
                    run(window, args.window_check)
                window.events.loaded += verify_window
            webview.start(gui="edgechromium", private_mode=False,
                          storage_path=str(paths.user / "cache/webview2"), debug=False)
        return 0
    except Exception as exc:
        if log:
            log.write("Startup failed: " + type(exc).__name__ + "\n")
            log.flush()
        known = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith(("程序资源", "用户数据", "当前 Windows", "云配置", "Windows 用户", "桌面实例", "本机服务", "无法建立", "启动等待")) else "启动失败。请确认已安装 Microsoft WebView2 Runtime，并重新解压完整程序包。详情见使用说明。"
        if not (args.headless or args.window_check):
            message(known)
        return 1
    finally:
        if server:
            server.should_exit = True
        if service_thread:
            service_thread.join(timeout=12)
        lock.release()
        if log:
            log.write("Desktop closed\n")
            log.flush()
        # Running native inference must not retain an invisible orphan process.
        if service_thread and service_thread.is_alive():
            os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
