"""Run offline extraction in a disposable process with a real deadline.

Run from backend; dependencies/model must already be installed. This script
does not install software, connect to a server, or touch application data.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time


def windows_process_tree(root_pid: int) -> list[int]:
    """Include the real interpreter behind a Windows virtualenv launcher."""
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return [root_pid]
    parents = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    family = {root_pid}
    while True:
        children = {pid for pid, parent in parents.items() if parent in family}
        if children <= family:
            return list(family)
        family |= children


def peak_resident_bytes(pid: int) -> int | None:
    """Read process peak resident memory, not system memory or swap usage."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform.startswith("linux"):
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return None


def run_process(command: list[str], output: Path, timeout_seconds: float,
                cancelled=lambda: False) -> dict:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Timeout must be finite and positive")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    peak = None
    status = None
    # Files avoid a full stderr pipe deadlocking inference; input cannot prompt.
    with (output / "stdout.log").open("wb") as stdout, (output / "stderr.log").open("wb") as stderr:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                 start_new_session=os.name != "nt",
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            while child.poll() is None:
                family = windows_process_tree(child.pid) if os.name == "nt" else [child.pid]
                samples = [peak_resident_bytes(pid) for pid in family]
                if any(sample is not None for sample in samples):
                    peak = max(peak or 0, sum(sample or 0 for sample in samples))
                if cancelled():
                    status = "cancelled"
                    break
                if time.monotonic() - started >= timeout_seconds:
                    status = "timed_out"
                    break
                time.sleep(.1)
        except KeyboardInterrupt:
            status = "cancelled"
        finally:
            if child.poll() is None:
                if os.name == "nt":
                    # Killing only the virtualenv launcher leaves inference alive.
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # The entire group already exited at the deadline.
                if child.poll() is None:
                    child.kill()
            child.wait()
    elapsed = time.monotonic() - started
    # Even a process observed just after the deadline must not claim success.
    status = status or ("timed_out" if elapsed >= timeout_seconds else
                        "completed" if child.returncode == 0 else "failed")
    result = {
        "status": status, "returncode": child.returncode,
        "wall_seconds": round(elapsed, 3), "timeout_seconds": timeout_seconds,
        "peak_resident_mib": round(peak / 1024**2, 1) if peak is not None else None,
        "memory_scope": "sampled sum of inference process-tree peak RSS/working sets; excludes supervisor, other services and swap",
    }
    (output / "process.json").write_text(json.dumps(result, indent=2), "utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--seed", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mobile-sam-repo", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--prune-inspection", action="store_true")
    parser.add_argument("--batch-size", type=int, choices=[1, 2, 4, 8], default=8)
    args = parser.parse_args()
    if (not 1 <= args.repeat <= 10 or not 1 <= args.threads <= 16
            or not 0 < args.timeout_seconds <= 180):
        parser.error("Use 1–10 runs, 1–16 threads and a deadline of at most 180 seconds")
    if bool(args.mobile_sam_repo) != bool(args.checkpoint):
        parser.error("Provide both local model repository and checkpoint")
    args.output.mkdir(parents=True, exist_ok=False)
    runs = []
    benchmark = Path(__file__).with_name("benchmark_photo_routes.py")
    for index in range(1, args.repeat + 1):
        folder = args.output / f"run-{index:02d}"
        command = [sys.executable, str(benchmark), "--image", str(args.image.resolve()),
                   "--seed", *map(str, args.seed), "--output", str(folder.resolve() / "evidence"),
                   "--threads", str(args.threads), "--timeout-seconds", str(args.timeout_seconds)]
        command += ["--batch-size", str(args.batch_size)]
        if args.mobile_sam_repo:
            command += ["--mobile-sam-repo", str(args.mobile_sam_repo.resolve()),
                        "--checkpoint", str(args.checkpoint.resolve())]
        if args.prune_inspection:
            command.append("--prune-inspection")
        run = run_process(command, folder, args.timeout_seconds)
        report_path = folder / "evidence/report.json"
        if run["status"] == "completed":
            if not report_path.is_file():
                run["status"] = "failed"
                run["error"] = "Child finished without extraction evidence"
            else:
                run["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
                extraction = json.loads(report_path.read_text("utf-8"))
                run["candidate_count"] = extraction["candidate_count"]
                run["result_sha256"] = extraction.get("result_sha256")
        runs.append(run)
        summary = {
            "source_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
            "environment": {"platform": platform.platform(), "processor": platform.processor(),
                            "logical_cpus": os.cpu_count(), "python": platform.python_version()},
            "torch_threads": args.threads, "batch_size": args.batch_size, "runs": runs,
            "timing_scope": "cold child startup + imports + decode + model + extraction + evidence encoding; excludes upload",
            "deployment_hardware_verified": False,
            "acceptance": "Diagnostic only; this machine is not automatically the deployment hardware",
        }
        (args.output / "performance.json").write_text(json.dumps(summary, indent=2), "utf-8")
        print(json.dumps(run), flush=True)
        if run["status"] != "completed":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
