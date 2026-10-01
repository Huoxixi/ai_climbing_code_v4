"""Build a private real-video focus sample from frozen evidence, without inference.

Only derived files in a separate project .tmp directory are published. The
existing source, baseline, rejected edit and analysis evidence remain immutable.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "backend"))

from core.replay_resources import (MIB, VisualRenderFailure, high_resource_slot,
                                   psutil, run_visual_worker)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path.name}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value, name: str, *, positive=False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"Invalid {name}")
    return number


def validate_storyboard(manifest: dict, video: dict) -> dict:
    """Reject misleading timing before any worker or encoder is started."""
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("shots"), list):
        raise ValueError("Unsupported storyboard schema")
    fps = finite(manifest.get("fps"), "fps", positive=True)
    for key in ("width", "height"):
        if manifest.get(key) != video[key]:
            raise ValueError(f"Storyboard {key} must match the original video")
    if abs(fps - video["fps"]) > .01:
        raise ValueError("Storyboard fps must match the original video")
    cursor = 0.0
    last_source_time = (video["frame_count"] - 1) / video["fps"]
    seen = set()
    for shot in manifest["shots"]:
        if not isinstance(shot, dict) or not isinstance(shot.get("id"), str) or not shot["id"]:
            raise ValueError("Every shot needs a unique id")
        if shot["id"] in seen:
            raise ValueError("Shot ids must be unique")
        seen.add(shot["id"])
        if shot.get("kind") not in {"overview", "hold", "move", "counts", "summary"}:
            raise ValueError("Unsupported shot kind")
        start = finite(shot.get("start_seconds"), "shot start")
        duration = finite(shot.get("duration_seconds"), "shot duration", positive=True)
        if abs(start - cursor) > 1e-5:
            raise ValueError("Storyboard shots must be contiguous and ordered")
        if abs(duration * fps - round(duration * fps)) > 1e-4:
            raise ValueError("Shot duration must contain a whole number of frames")
        has_start, has_end = "source_start_seconds" in shot, "source_end_seconds" in shot
        if has_start != has_end or (not has_start and shot["kind"] not in {"counts", "summary"}):
            raise ValueError("A real-video shot needs both source boundaries")
        if has_start:
            source_start = finite(shot["source_start_seconds"], "source start")
            source_end = finite(shot["source_end_seconds"], "source end")
            if source_start > source_end or source_end > last_source_time + 1e-5:
                raise ValueError("Source boundaries exceed the recorded video")
            finite(shot.get("playback_rate", 1), "playback rate", positive=True)
        cursor += duration
    if not seen:
        raise ValueError("Storyboard needs at least one shot")
    duration = finite(manifest.get("duration_seconds"), "duration", positive=True)
    frames = manifest.get("frame_count")
    if (abs(duration - cursor) > 1e-5 or isinstance(frames, bool)
            or not isinstance(frames, int) or frames != round(duration * fps)):
        raise ValueError("Storyboard duration and frame count do not match the shots")
    return manifest


def probe_video(path: Path) -> dict:
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open {path.name}")
        info = {"width": round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(cap.get(cv2.CAP_PROP_FPS)),
                "frame_count": round(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "fourcc": round(cap.get(cv2.CAP_PROP_FOURCC))}
        if min(info[k] for k in ("width", "height", "fps", "frame_count")) <= 0:
            raise ValueError(f"Invalid video metadata in {path.name}")
        info["duration_seconds"] = info["frame_count"] / info["fps"]
        return info
    finally:
        cap.release()


class AssemblyBudget:
    """Bound assembly memory, time and cancellation, including child encoders."""
    def __init__(self, cancelled, timeout_seconds=120, max_tree_mib=768,
                 min_available_mib=768):
        if psutil is None:
            raise VisualRenderFailure("resource_monitor_unavailable", "资源监测组件不可用")
        self.cancelled, self.timeout = cancelled, timeout_seconds
        self.max_rss, self.min_available = max_tree_mib, min_available_mib
        self.started = time.monotonic()
        self.root = psutil.Process()
        self.metrics = {"tree_peak_rss_mib": 0.0, "system_min_available_mib": None}

    def check(self):
        if self.cancelled():
            raise InterruptedError("任务已取消")
        if time.monotonic() - self.started > self.timeout:
            raise VisualRenderFailure("timeout", "成片拼接超时，原复盘仍保留")
        rss = 0
        for process in [self.root, *self.root.children(recursive=True)]:
            try:
                rss += process.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        available = psutil.virtual_memory().available / MIB
        self.metrics["tree_peak_rss_mib"] = max(self.metrics["tree_peak_rss_mib"], round(rss / MIB, 2))
        previous = self.metrics["system_min_available_mib"]
        self.metrics["system_min_available_mib"] = round(min(available, previous if previous is not None else available), 2)
        if rss / MIB > self.max_rss or available < self.min_available:
            raise VisualRenderFailure("memory_limit", "成片拼接因内存保护停止，原复盘仍保留")


def validate_video(path: Path, *, width: int, height: int, fps: float,
                   frame_count: int, check=lambda: None) -> dict:
    """Decode the whole file; metadata alone cannot establish completeness."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    count = 0
    try:
        if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS) - fps) > .01:
            raise ValueError("Generated video cannot be decoded at the intended frame rate")
        while True:
            check()
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (height, width):
                raise ValueError("Generated video dimensions changed")
            count += 1
    finally:
        cap.release()
    if count != frame_count:
        raise ValueError(f"Incomplete video: decoded {count}, expected {frame_count}")
    return {"width": width, "height": height, "fps": fps, "frame_count": count,
            "duration_seconds": count / fps, "fully_decoded": True}


def concat_videos(baseline: Path, tail: Path, output: Path, *, baseline_info: dict,
                  manifest: dict, cancelled=lambda: False, progress=None,
                  timeout_seconds=120) -> dict:
    """Publish only a fully decoded body + tail, using one frame at a time."""
    import cv2
    if output.exists():
        raise ValueError("Assembly requires a new private output path")
    expected = baseline_info["frame_count"] + manifest["frame_count"]
    width, height, fps = (manifest[k] for k in ("width", "height", "fps"))
    if any(baseline_info[key] != manifest[key] for key in ("width", "height", "fps")):
        raise ValueError("Baseline and tail must have identical geometry and frame rate")
    with high_resource_slot(cancelled=cancelled, progress=progress):
        budget = AssemblyBudget(cancelled, timeout_seconds)
        budget.check()
        if budget.metrics["system_min_available_mib"] < 1024:
            raise VisualRenderFailure("memory_admission", "当前可用内存不足，原复盘仍保留")
        writer = None
        process = None
        started = time.monotonic()
        method = "streamed_vp8_reencode"
        try:
            ffmpeg = shutil.which("ffmpeg")
            tail_info = probe_video(tail)
            if ffmpeg and baseline_info["fourcc"] == tail_info["fourcc"]:
                # Explicit paths in a private file; no shell or command interpolation.
                listing = output.with_suffix(".concat.txt")
                lines = ["file '" + str(p.resolve()).replace("\\", "/").replace("'", "'\\''") + "'"
                         for p in (baseline, tail)]
                listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
                try:
                    process = subprocess.Popen([ffmpeg, "-nostdin", "-v", "error", "-f", "concat",
                                                "-safe", "0", "-i", str(listing), "-map", "0:v:0",
                                                "-c", "copy", "-an", str(output)],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    while process.poll() is None:
                        budget.check()
                        try:
                            process.wait(timeout=.05)
                        except subprocess.TimeoutExpired:
                            pass
                    if process.returncode != 0:
                        raise RuntimeError("Available ffmpeg could not stream-copy this video pair")
                    method = "ffmpeg_video_stream_copy"
                finally:
                    listing.unlink(missing_ok=True)
            else:
                writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height))
                if not writer.isOpened():
                    raise RuntimeError("VP8 encoder is unavailable")
                total = 0
                for path, expected_source_frames in ((baseline, baseline_info["frame_count"]),
                                                     (tail, manifest["frame_count"])):
                    cap = cv2.VideoCapture(str(path))
                    count = 0
                    try:
                        if not cap.isOpened():
                            raise ValueError(f"Cannot decode {path.name}")
                        while True:
                            budget.check()
                            ok, frame = cap.read()
                            if not ok:
                                break
                            if frame.shape[:2] != (height, width):
                                raise ValueError("An input frame changed dimensions")
                            writer.write(frame)
                            count += 1
                            total += 1
                            if progress and total % max(1, round(fps)) == 0:
                                progress("正在保留正文并拼接新结尾", round(total / expected * 85))
                    finally:
                        cap.release()
                    if count != expected_source_frames:
                        raise ValueError(f"Incomplete assembly input: {path.name}")
                writer.release()
                writer = None
            if progress:
                progress("正在完整解码核验成片", 90)
            media = validate_video(output, width=width, height=height, fps=fps,
                                   frame_count=expected, check=budget.check)
            budget.check()
            return {**media, "assembly_method": method, "body_layout_and_speed_retained": True,
                    "baseline_file_modified": False, "resources": budget.metrics,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if writer is not None:
                writer.release()
                writer = None
            output.unlink(missing_ok=True)
            raise
        finally:
            if writer is not None:
                writer.release()


def build_sample(evidence: Path, output: Path, review_path: Path, storyboard_path: Path,
                 *, cancelled=lambda: False, progress=None, timeout_seconds=120) -> dict:
    from core.replay_summary import build_replay_summary
    import cv2
    cv2.setNumThreads(1)
    evidence, output, review_path, storyboard_path = (p.resolve() for p in (evidence, output, review_path, storyboard_path))
    if any(".local" in [part.lower() for part in p.parts] for p in (evidence, output, review_path, storyboard_path)):
        raise ValueError("This local sample must not access .local")
    if not output.is_relative_to(PROJECT / ".tmp") or output == evidence or evidence.is_relative_to(output):
        raise ValueError("Output must be a separate private project .tmp subdirectory")
    source, baseline, result_path = (evidence / name for name in ("input.mp4", "baseline.webm", "result.json"))
    protected = [evidence / name for name in ("input.mp4", "baseline.webm", "enhanced.webm", "result.json",
                                             "summary.json", "analysis-evidence.json", "reviewed-evidence.json")
                 if (evidence / name).is_file()]
    for required in (source, baseline, result_path, review_path, storyboard_path):
        if not required.is_file():
            raise ValueError(f"Required local input is missing: {required.name}")
    original_hashes = {p.name: sha256(p) for p in protected}
    started = time.monotonic()
    report = None
    try:
        source_info, baseline_info = probe_video(source), probe_video(baseline)
        if source_info["frame_count"] != baseline_info["frame_count"]:
            raise ValueError("Baseline must contain exactly the original analysis interval")
        result = read_json(result_path)
        result = result.get("result") if isinstance(result.get("result"), dict) else result
        review = read_json(review_path)
        manifest = copy.deepcopy(read_json(storyboard_path))
        validate_storyboard(manifest, source_info)
        summary = build_replay_summary(result, review)
        summary["media"] = {"analysis_duration_seconds": baseline_info["duration_seconds"],
                            "analysis_frame_count": baseline_info["frame_count"],
                            "tail_start_seconds": baseline_info["duration_seconds"],
                            "tail_duration_seconds": manifest["duration_seconds"],
                            "total_duration_seconds": baseline_info["duration_seconds"] + manifest["duration_seconds"],
                            "total_frame_count": baseline_info["frame_count"] + manifest["frame_count"],
                            **{key: manifest[key] for key in ("width", "height", "fps")}}
        summary["references"] = {"source": str(source), "baseline": str(baseline),
                                 "previous_enhanced": str(evidence / "enhanced.webm"), "result": str(result_path)}
        manifest.update(summary=summary, result_path=str(result_path), source=str(source))
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".focus-build-", dir=output) as temporary:
            stage = Path(temporary)
            write_json(stage / "summary.json", summary)
            write_json(stage / "review.json", review)
            write_json(stage / "storyboard.json", manifest)
            if cancelled():
                raise InterruptedError("任务已取消")
            render_metrics = run_visual_worker(source, stage / "storyboard.json", stage / "tail.webm",
                                               stage / "render-metrics.json", cancelled=cancelled,
                                               progress=progress, timeout_seconds=timeout_seconds,
                                               worker_module="core.replay_focus_renderer")
            assembled = concat_videos(baseline, stage / "tail.webm", stage / "enhanced.webm",
                                      baseline_info=baseline_info, manifest=manifest, cancelled=cancelled,
                                      progress=progress, timeout_seconds=timeout_seconds)
            final_hashes = {p.name: sha256(p) for p in protected}
            if final_hashes != original_hashes:
                raise RuntimeError("Original evidence changed during sample generation")
            if cancelled():
                raise InterruptedError("任务已取消")
            report = {"status": "ready_for_visual_review", "new_model_calls": 0,
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "source_video": source_info, "baseline_video": baseline_info,
                      "render": render_metrics, "assembly": assembled,
                      "original_hashes_before": original_hashes, "original_hashes_after": final_hashes,
                      "originals_unchanged": True, "real_phone_verified": False,
                      "four_gib_server_verified": False, "user_visual_accepted": False}
            write_json(stage / "build-report.json", report)
            # The playable movie is replaced last, only after full decoding and
            # the immutable-input audit. Rendering failures leave any prior movie.
            for name in ("summary.json", "review.json", "storyboard.json", "render-metrics.json",
                         "build-report.json", "tail.webm", "enhanced.webm"):
                os.replace(stage / name, output / name)
        if progress:
            progress("真实视频样片已生成，等待视觉评审", 100)
        return report
    finally:
        if {p.name: sha256(p) for p in protected} != original_hashes:
            raise RuntimeError("Original evidence was modified; do not accept this build")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    interrupted = False

    def cancel_signal(*_):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, cancel_signal)
    signal.signal(signal.SIGTERM, cancel_signal)
    cancelled = lambda: interrupted or bool(args.cancel_file and args.cancel_file.exists())
    last_progress = [None, -1]

    def progress(label, value):
        if label != last_progress[0] or value >= last_progress[1] + 5:
            print(json.dumps({"stage": label, "progress": value}, ensure_ascii=False), flush=True)
            last_progress[:] = [label, value]

    try:
        report = build_sample(args.evidence, args.output, args.review, args.storyboard,
                              cancelled=cancelled, progress=progress,
                              timeout_seconds=finite(args.timeout_seconds, "timeout", positive=True))
        print(json.dumps({"status": report["status"], "elapsed_seconds": report["elapsed_seconds"],
                          "output": str(args.output.resolve()), "originals_unchanged": True}, ensure_ascii=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "cancelled" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                          "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
