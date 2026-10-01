"""Build a private 15-second in-place video treatment, with no model calls.

This sample is deliberately separate from the full replay and from earlier
rejected samples. It reads existing evidence and never rewrites its inputs.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
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

from core import replay_resources as resources
from scripts.build_replay_focus_sample import (AssemblyBudget, probe_video, read_json,
                                                sha256, validate_video, write_json)


PREVIEW_MEDIA = {"width": 720, "height": 880, "fps": 30,
                 "frame_count": 450, "duration_seconds": 15}


def validate_preview_manifest(manifest: dict) -> None:
    for field, expected in PREVIEW_MEDIA.items():
        value = manifest.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Preview {field} is required")
        if not math.isfinite(value) or value != expected:
            raise ValueError("This approved preview must be 15 seconds, 450 frames, 720 x 880 at 30 fps")


def local_h264_encoder() -> Path | None:
    """Find already installed FFmpeg; never download or install a binary."""
    candidates = []
    system = shutil.which("ffmpeg")
    if system:
        candidates.append(Path(system))
    spec = importlib.util.find_spec("imageio_ffmpeg")
    if spec and spec.origin:
        candidates.extend(sorted((Path(spec.origin).parent / "binaries").glob("ffmpeg*")))
    for candidate in candidates:
        if not candidate.is_file() or ".local" in [p.lower() for p in candidate.resolve().parts]:
            continue
        try:
            result = subprocess.run([str(candidate), "-hide_banner", "-encoders"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and b"libx264 " in result.stdout:
            return candidate.resolve()
    return None


def transcode_mp4(source: Path, output: Path, encoder: Path, *, cancelled=lambda: False,
                  progress=None, timeout_seconds=120) -> dict:
    if output.exists():
        raise ValueError("Transcoding requires a new private output path")
    process = None
    started = time.monotonic()
    try:
        with resources.high_resource_slot(cancelled=cancelled, progress=progress):
            budget = AssemblyBudget(cancelled, timeout_seconds)
            budget.check()
            if budget.metrics["system_min_available_mib"] < 1024:
                raise resources.VisualRenderFailure("memory_admission", "可用内存不足，保留已生成的 WebM 样片")
            if progress:
                progress("正在制作兼容手机播放的 MP4", 0)
            command = [str(encoder), "-nostdin", "-hide_banner", "-loglevel", "error",
                       "-i", str(source), "-map", "0:v:0", "-an", "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                       "-threads", "1", "-movflags", "+faststart", str(output)]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while process.poll() is None:
                budget.check()
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0 or not output.is_file():
                raise RuntimeError("H.264 compatibility output could not be generated")
            media = validate_video(output, **{k: PREVIEW_MEDIA[k] for k in
                                             ("width", "height", "fps", "frame_count")},
                                   check=budget.check)
            return {**media, "codec": "H.264", "pixel_format": "yuv420p", "faststart": True,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "resources": budget.metrics, "real_phone_verified": False}
    except BaseException:
        if process is not None:
            resources._stop_process_tree(process, {})
        output.unlink(missing_ok=True)
        raise
    finally:
        if process is not None:
            resources._stop_process_tree(process, {})


def build_sample(evidence: Path, review_dir: Path, output: Path, manifest_path: Path, *,
                 cancelled=lambda: False, progress=None, timeout_seconds=120) -> dict:
    import cv2
    cv2.setNumThreads(1)
    evidence, review_dir, output, manifest_path = (p.resolve() for p in (evidence, review_dir, output, manifest_path))
    if any(".local" in [part.lower() for part in p.parts] for p in (evidence, review_dir, output, manifest_path)):
        raise ValueError("This isolated sample must not access .local")
    if (not output.is_relative_to(PROJECT / ".tmp") or output in {evidence, review_dir}
            or any(directory.is_relative_to(output) for directory in (evidence, review_dir))):
        raise ValueError("Output must be a separate private project .tmp subdirectory")
    if manifest_path == output / "manifest.json":
        raise ValueError("Keep the authored input manifest separate from the generated manifest.json")
    source, result_path = evidence / "input.mp4", evidence / "result.json"
    for required in (source, result_path, review_dir / "summary.json", review_dir / "review.json", manifest_path):
        if not required.is_file():
            raise ValueError(f"Missing local input: {required.name}")
    protected = [evidence / name for name in ("input.mp4", "result.json", "baseline.webm", "enhanced.webm",
                                             "summary.json", "analysis-evidence.json", "reviewed-evidence.json")
                 if (evidence / name).is_file()]
    protected.extend([review_dir / "summary.json", review_dir / "review.json", manifest_path])
    before = {str(path): sha256(path) for path in protected}
    started = time.monotonic()
    try:
        if cancelled():
            raise InterruptedError("任务已取消")
        manifest = copy.deepcopy(read_json(manifest_path))
        validate_preview_manifest(manifest)
        summary, review = read_json(review_dir / "summary.json"), read_json(review_dir / "review.json")
        manifest.update(result_path=str(result_path), source=str(source), summary=summary,
                        review=review, review_path=str(review_dir / "review.json"))
        source_info = probe_video(source)
        if any(source_info[key] != PREVIEW_MEDIA[key] for key in ("width", "height", "fps")):
            raise ValueError("The reviewed source geometry or frame rate has changed")
        encoder = local_h264_encoder()
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".inplace-build-", dir=output) as temporary:
            stage = Path(temporary)
            write_json(stage / "manifest.json", manifest)
            render_metrics = resources.run_visual_worker(source, stage / "manifest.json", stage / "preview.webm",
                                                        stage / "render-metrics.json", cancelled=cancelled,
                                                        progress=progress, timeout_seconds=timeout_seconds,
                                                        worker_module="core.replay_inplace_renderer")
            with resources.high_resource_slot(cancelled=cancelled, progress=progress):
                budget = AssemblyBudget(cancelled, timeout_seconds)
                webm_info = validate_video(stage / "preview.webm", **{k: PREVIEW_MEDIA[k] for k in
                                                                     ("width", "height", "fps", "frame_count")},
                                           check=budget.check)
            compatibility = {"status": "unavailable", "reason": "No installed libx264 encoder found"}
            if encoder:
                try:
                    compatibility = {"status": "ready", **transcode_mp4(stage / "preview.webm", stage / "preview.mp4", encoder,
                                                                          cancelled=cancelled, progress=progress,
                                                                          timeout_seconds=timeout_seconds)}
                except InterruptedError:
                    raise
                except Exception as exc:
                    compatibility = {"status": "failed", "error_type": type(exc).__name__,
                                     "reason": "WebM remains the verified sample; MP4 conversion did not complete"}
            after = {str(path): sha256(path) for path in protected}
            if before != after:
                raise RuntimeError("Original local evidence changed during sample generation")
            if cancelled():
                raise InterruptedError("任务已取消")
            report = {"status": "ready_for_visual_review", "scope": "15_second_dynamic_preview_only",
                      "new_model_calls": 0, "full_replay_assembled": False,
                      "source_video": source_info, "preview_video": webm_info,
                      "render": render_metrics, "mp4": compatibility,
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "original_hashes_before": before, "original_hashes_after": after,
                      "originals_unchanged": True, "user_visual_accepted": False,
                      "real_phone_verified": False, "four_gib_server_verified": False}
            write_json(stage / "build-report.json", report)
            names = ["manifest.json", "render-metrics.json", "build-report.json", "preview.webm"]
            if compatibility["status"] == "ready":
                names.append("preview.mp4")
            elif (output / "preview.mp4").exists():
                # A previous MP4 must not be mistaken for this new WebM revision.
                # Preserve it under a distinct name rather than delete a sample.
                previous = output / f"preview-previous-{time.time_ns()}.mp4"
                os.replace(output / "preview.mp4", previous)
            for name in names:
                os.replace(stage / name, output / name)
        if progress:
            progress("15 秒动态试看已生成，等待视觉评审", 100)
        return report
    finally:
        if {str(path): sha256(path) for path in protected} != before:
            raise RuntimeError("Original evidence was modified; do not accept this build")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("evidence", "review-dir", "output", "manifest"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    if args.cancel_file and ".local" in [part.lower() for part in args.cancel_file.resolve().parts]:
        parser.error("The cancellation marker must not be in .local")
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("The timeout must be a positive finite duration")
    interrupted = False

    def cancel_signal(*_):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, cancel_signal)
    signal.signal(signal.SIGTERM, cancel_signal)
    cancelled = lambda: interrupted or bool(args.cancel_file and args.cancel_file.exists())

    def progress(label, value):
        print(json.dumps({"stage": label, "progress": value}, ensure_ascii=False), flush=True)

    try:
        report = build_sample(args.evidence, args.review_dir, args.output, args.manifest,
                              cancelled=cancelled, progress=progress, timeout_seconds=args.timeout_seconds)
        print(json.dumps({"status": report["status"], "elapsed_seconds": report["elapsed_seconds"],
                          "mp4_status": report["mp4"]["status"], "originals_unchanged": True}, ensure_ascii=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "cancelled" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                          "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
