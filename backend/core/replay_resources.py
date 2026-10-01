"""Shared admission and measured protection for inference, video and visuals."""
from __future__ import annotations

from contextlib import contextmanager
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

try:
    import psutil
except ImportError:  # Basic replay and photo inference can still run.
    psutil = None

_thread_lock = threading.Lock()
_local = threading.local()
# Retain the filename so older, in-flight photo workers participate too.
RESOURCE_LOCK_PATH = Path(tempfile.gettempdir()) / "ai-climbing-photo-inference.lock"
MIB = 1024 * 1024
VISUAL_WORKER_MODULES = frozenset({"core.replay_visual_renderer", "core.replay_focus_renderer",
                                   "core.replay_inplace_renderer", "core.replay_inplace_full_renderer",
                                   "core.replay_inplace_rhythm_renderer", "core.replay_template_renderer",
                                   "core.replay_action_renderer"})


class VisualRenderFailure(RuntimeError):
    def __init__(self, code, message, metrics=None):
        super().__init__(message)
        self.code = code
        self.metrics = metrics or {}


@contextmanager
def high_resource_slot(*, cancelled=None, progress=None):
    """Acquire a single stage; reject nested stages instead of deadlocking."""
    cancelled = cancelled or (lambda: False)
    if getattr(_local, "held", False):
        raise RuntimeError("High-resource stages must not acquire nested slots")
    if progress:
        progress("等待资源队列", 0)
    acquired = False
    try:
        while not acquired:
            if cancelled():
                raise InterruptedError("任务已取消")
            acquired = _thread_lock.acquire(timeout=.1)
        with RESOURCE_LOCK_PATH.open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            locked = False
            try:
                while not locked:
                    if cancelled():
                        raise InterruptedError("任务已取消")
                    handle.seek(0)
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except (BlockingIOError, OSError):
                        time.sleep(.1)
                if cancelled():
                    raise InterruptedError("任务已取消")
                _local.held = True
                yield
            finally:
                _local.held = False
                if locked:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        if acquired:
            _thread_lock.release()


def serialized_heavy_stage(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        remaining = (max(.1, kwargs["deadline"] - time.monotonic())
                     if kwargs.get("deadline") is not None else None)
        with high_resource_slot(cancelled=kwargs.get("cancelled"), progress=kwargs.get("progress")):
            if remaining is not None:
                kwargs["deadline"] = time.monotonic() + remaining
            return fn(*args, **kwargs)
    return run


def _process_tree(root):
    try:
        return [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []


def _stop_process_tree(process, known):
    """Terminate descendants as well as the renderer; reap the Popen child."""
    try:
        known.update({p.pid: p for p in _process_tree(psutil.Process(process.pid))})
    except psutil.NoSuchProcess:
        pass
    targets = list(reversed(list(known.values())))
    for child in targets:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(targets, timeout=1)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    psutil.wait_procs(alive, timeout=2)


def run_visual_worker(reference_path, manifest_path, output_path, metrics_path, *,
                      cancelled=None, progress=None, timeout_seconds=120,
                      max_tree_mib=768, min_start_available_mib=1024,
                      min_running_available_mib=768,
                      worker_module="core.replay_visual_renderer"):
    """Render into new private temporary paths under tree-wide protection."""
    if worker_module not in VISUAL_WORKER_MODULES:
        raise ValueError("Unsupported replay visual worker")
    cancelled = cancelled or (lambda: False)
    output_path, metrics_path = Path(output_path), Path(metrics_path)
    reference_path, manifest_path = Path(reference_path), Path(manifest_path)
    partial_path = output_path.with_name(f".{output_path.name}.partial.webm")
    paths = [p.resolve() for p in (reference_path, manifest_path, output_path, metrics_path)]
    if (len(set(paths)) != 4 or partial_path.resolve() in paths
            or output_path.exists() or metrics_path.exists() or partial_path.exists()):
        raise ValueError("渲染必须使用新的临时输出路径")
    if not reference_path.is_file() or not manifest_path.is_file():
        raise VisualRenderFailure("missing_assets", "线路回放素材已不可用")
    if psutil is None:
        raise VisualRenderFailure("resource_monitor_unavailable", "资源监测组件不可用，已保留基础复盘")
    metrics = {"tree_peak_rss_mib": 0.0, "system_min_available_mib": None,
               "elapsed_seconds": 0.0, "timeout_seconds": timeout_seconds,
               "rss_limit_mib": max_tree_mib, "status": "waiting"}
    process = None
    known = {}
    try:
        with high_resource_slot(cancelled=cancelled, progress=progress):
            available = psutil.virtual_memory().available / MIB
            metrics["system_min_available_mib"] = round(available, 2)
            if available < min_start_available_mib:
                raise VisualRenderFailure("memory_admission", "当前可用内存不足，已保留基础复盘", metrics)
            if progress:
                progress("正在制作线路回放", 0)
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                       NUMEXPR_NUM_THREADS="1")
            command = [sys.executable, "-m", worker_module,
                       "--reference", str(reference_path.resolve()),
                       "--manifest", str(manifest_path.resolve()),
                       "--output", str(output_path.resolve()),
                       "--metrics", str(metrics_path.resolve())]
            started = time.monotonic()
            process = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[1]),
                                       env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            root = psutil.Process(process.pid)
            metrics["status"] = "running"
            while True:
                tree = _process_tree(root)
                known.update({p.pid: p for p in tree})
                rss = 0
                for child in tree:
                    try:
                        rss += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                available = psutil.virtual_memory().available / MIB
                metrics["tree_peak_rss_mib"] = max(metrics["tree_peak_rss_mib"], round(rss / MIB, 2))
                metrics["system_min_available_mib"] = min(metrics["system_min_available_mib"], round(available, 2))
                metrics["elapsed_seconds"] = round(time.monotonic() - started, 3)
                if cancelled():
                    raise InterruptedError("任务已取消")
                if rss / MIB > max_tree_mib or available < min_running_available_mib:
                    raise VisualRenderFailure("memory_limit", "线路回放已因内存保护停止，基础复盘仍可使用", metrics)
                if metrics["elapsed_seconds"] > timeout_seconds:
                    raise VisualRenderFailure("timeout", "线路回放制作超时，基础复盘仍可使用", metrics)
                if process.poll() is not None:
                    break
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0 or not output_path.is_file() or not metrics_path.is_file():
                raise VisualRenderFailure("render_failed", "线路回放暂未生成，可重试", metrics)
            child_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["status"] = "succeeded"
            result = dict(child_metrics, resources=metrics)
            metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            if progress:
                progress("线路回放已生成", 100)
            return result
    except BaseException:
        if process is not None:
            _stop_process_tree(process, known)
        output_path.unlink(missing_ok=True)
        metrics_path.unlink(missing_ok=True)
        raise
    finally:
        if process is not None:
            _stop_process_tree(process, known)
            partial_path.unlink(missing_ok=True)
