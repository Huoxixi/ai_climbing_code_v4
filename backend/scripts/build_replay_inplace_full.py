"""Build the full local replay: unchanged baseline frames plus a new real-video tail.

The WebM is assembled by stream copy, then optionally transcoded to H.264 for
playback compatibility. All source evidence remains read-only and local.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import json

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "backend"))

from core import replay_resources as resources
from scripts.build_replay_focus_sample import (AssemblyBudget, probe_video, read_json,
                                                sha256, validate_video, write_json)
from scripts.build_replay_inplace_sample import local_h264_encoder

VERSION = "replay-inplace-full-v1"
WORKER_MODULES = {VERSION: "core.replay_inplace_full_renderer",
                  "replay-inplace-rhythm-v1": "core.replay_inplace_rhythm_renderer"}


def validate_manifest(manifest):
    if manifest.get("visual_version") not in WORKER_MODULES:
        raise ValueError("Unsupported full-tail visual version")
    for field, expected in (("width", 720), ("height", 880), ("fps", 30)):
        value = manifest.get(field)
        if isinstance(value, bool) or value != expected:
            raise ValueError("Full replay must retain 720 x 880 at 30 fps")
    duration, frames = manifest.get("duration_seconds"), manifest.get("frame_count")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or not 10 <= duration <= 60
            or isinstance(frames, bool) or not isinstance(frames, int)
            or abs(frames - duration * 30) > 1e-6):
        raise ValueError("Full tail must be 10–60 seconds, aligned to whole frames with a matching frame count")


def validate_source_endpoint(manifest, source_info):
    """Use metadata read from the actual source, never a claimed final timestamp."""
    last = manifest.get("last_source_seconds")
    expected = (source_info["frame_count"] - 1) / source_info["fps"]
    if (isinstance(last, bool) or not isinstance(last, (int, float))
            or not math.isfinite(last) or abs(last - expected) > 1e-6):
        raise ValueError("last_source_seconds must match the actual source video's final frame")
    return expected


def validate_full_video(path, baseline, baseline_info, tail_info, *, check=lambda: None):
    """Decode the complete WebM and compare every body frame to the baseline."""
    import cv2
    import numpy as np
    expected = baseline_info["frame_count"] + tail_info["frame_count"]
    cap, original = cv2.VideoCapture(str(path)), cv2.VideoCapture(str(baseline))
    count = 0
    source_digest, output_digest = hashlib.sha256(), hashlib.sha256()
    try:
        for opened in (cap, original):
            if not opened.isOpened() or abs(opened.get(cv2.CAP_PROP_FPS) - baseline_info["fps"]) > .01:
                raise ValueError("Full replay or baseline could not be decoded at the expected frame rate")
        while True:
            check()
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (baseline_info["height"], baseline_info["width"]):
                raise ValueError("Full replay frame dimensions changed")
            if count < baseline_info["frame_count"]:
                original_ok, original_frame = original.read()
                if not original_ok or not np.array_equal(original_frame, frame):
                    raise ValueError(f"Baseline content changed at frame {count}")
                source_digest.update(original_frame)
                output_digest.update(frame)
            count += 1
        if count != expected or original.read()[0]:
            raise ValueError("Full replay or baseline frame count is incomplete")
    finally:
        cap.release()
        original.release()
    return {"width": baseline_info["width"], "height": baseline_info["height"],
            "fps": baseline_info["fps"], "frame_count": count,
            "duration_seconds": count / baseline_info["fps"], "fully_decoded": True,
            "body_frames_checked": baseline_info["frame_count"], "body_frames_identical": True,
            "baseline_decoded_sha256": source_digest.hexdigest(),
            "output_body_decoded_sha256": output_digest.hexdigest()}


def run_media_command(command, output, validator, *, cancelled=lambda: False,
                      progress=None, label="正在输出视频", timeout_seconds=120):
    """Share the same single heavy stage and measured protection as rendering."""
    output = Path(output)
    if output.exists():
        raise ValueError("Encoding requires a new private output path")
    process = None
    started = time.monotonic()
    try:
        with resources.high_resource_slot(cancelled=cancelled, progress=progress):
            budget = AssemblyBudget(cancelled, timeout_seconds)
            budget.check()
            if budget.metrics["system_min_available_mib"] < 1024:
                raise resources.VisualRenderFailure("memory_admission", "当前可用内存不足，原有复盘仍保留")
            if progress:
                progress(label, 0)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while process.poll() is None:
                budget.check()
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0 or not output.is_file():
                raise RuntimeError("Video encoder did not complete successfully")
            media = validator(budget.check)
            budget.check()
            if progress:
                progress(label, 100)
            return {**media, "resources": budget.metrics,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
    except BaseException:
        if process is not None:
            resources._stop_process_tree(process, {})
        output.unlink(missing_ok=True)
        raise
    finally:
        if process is not None:
            resources._stop_process_tree(process, {})


def assemble_webm(baseline, tail, output, encoder, baseline_info, tail_info, **kwargs):
    if any(baseline_info[key] != tail_info[key] for key in ("width", "height", "fps", "fourcc")):
        raise ValueError("Baseline and tail must use the same geometry, frame rate and codec for stream copy")
    listing = Path(output).with_suffix(".concat.txt")
    lines = ["file '" + str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''") + "'"
             for p in (baseline, tail)]
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        command = [str(encoder), "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "concat",
                   "-safe", "0", "-i", str(listing), "-map", "0:v:0", "-c:v", "copy", "-an", str(output)]
        media = run_media_command(command, output,
                                  lambda check: validate_full_video(output, baseline, baseline_info, tail_info, check=check),
                                  label="正在无损拼接正文并逐帧核验", **kwargs)
        return {**media, "assembly_method": "ffmpeg_video_stream_copy", "body_reencoded": False}
    finally:
        listing.unlink(missing_ok=True)


def transcode_full_mp4(source, output, encoder, media_info, **kwargs):
    command = [str(encoder), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-threads", "1", "-movflags", "+faststart", str(output)]
    media = run_media_command(command, output,
                              lambda check: validate_video(output, **{key: media_info[key] for key in
                                                                       ("width", "height", "fps", "frame_count")}, check=check),
                              label="正在制作完整 MP4 并核验播放", **kwargs)
    return {**media, "codec": "H.264", "pixel_format": "yuv420p", "faststart": True,
            "body_reencoded": True, "body_layout_and_speed_retained": True, "real_phone_verified": False}


def build_sample(evidence, review_dir, output, manifest_path, *, cancelled=lambda: False,
                 progress=None, timeout_seconds=120):
    import cv2
    cv2.setNumThreads(1)
    evidence, review_dir, output, manifest_path = (Path(p).resolve() for p in (evidence, review_dir, output, manifest_path))
    selected = (evidence, review_dir, output, manifest_path)
    if any(".local" in [part.lower() for part in path.parts] for path in selected):
        raise ValueError("This isolated build must not access .local")
    if (not output.is_relative_to(PROJECT / ".tmp") or output in {evidence, review_dir}
            or any(directory.is_relative_to(output) for directory in (evidence, review_dir))):
        raise ValueError("Use a new separate project .tmp directory")
    if manifest_path == output / "manifest.json":
        raise ValueError("Keep the authored manifest separate from the generated manifest.json")
    source, baseline, result_path = (evidence / name for name in ("input.mp4", "baseline.webm", "result.json"))
    required = (source, baseline, result_path, review_dir / "summary.json", review_dir / "review.json", manifest_path)
    if not all(path.is_file() for path in required):
        raise ValueError("A required frozen local input is missing")
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
        validate_manifest(manifest)
        manifest.update(result_path=str(result_path), source=str(source), baseline_path=str(baseline),
                        summary=read_json(review_dir / "summary.json"), review=read_json(review_dir / "review.json"),
                        review_path=str(review_dir / "review.json"))
        source_info, baseline_info = probe_video(source), probe_video(baseline)
        source_endpoint = validate_source_endpoint(manifest, source_info)
        if any(info[key] != manifest[key] for info in (source_info, baseline_info)
               for key in ("width", "height", "fps")):
            raise ValueError("Source or baseline geometry or frame rate does not match the reviewed tail")
        if baseline_info["frame_count"] != source_info["frame_count"]:
            raise ValueError("Baseline must contain the entire original analysis interval")
        encoder = local_h264_encoder()
        if encoder is None:
            raise RuntimeError("An installed FFmpeg with libx264 is required; no software was downloaded")
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".inplace-full-build-", dir=output) as temporary:
            stage = Path(temporary)
            write_json(stage / "manifest.json", manifest)
            render_metrics = resources.run_visual_worker(source, stage / "manifest.json", stage / "tail.webm",
                                                        stage / "render-metrics.json", cancelled=cancelled,
                                                        progress=progress, timeout_seconds=timeout_seconds,
                                                        worker_module=WORKER_MODULES[manifest["visual_version"]])
            tail_info = probe_video(stage / "tail.webm")
            if any(tail_info[key] != manifest[key] for key in ("width", "height", "fps", "frame_count")):
                raise ValueError("Tail video metadata does not match the approved manifest")
            webm = assemble_webm(baseline, stage / "tail.webm", stage / "enhanced.webm", encoder,
                                 baseline_info, tail_info, cancelled=cancelled, progress=progress,
                                 timeout_seconds=timeout_seconds)
            compatibility = {"status": "ready"}
            try:
                compatibility.update(transcode_full_mp4(stage / "enhanced.webm", stage / "enhanced.mp4", encoder,
                                                       webm, cancelled=cancelled, progress=progress,
                                                       timeout_seconds=timeout_seconds))
            except InterruptedError:
                raise
            except Exception as exc:
                compatibility = {"status": "failed", "error_type": type(exc).__name__,
                                 "reason": "Verified WebM retained; compatibility conversion did not complete"}
            after = {str(path): sha256(path) for path in protected}
            if before != after:
                raise RuntimeError("Original evidence changed during generation")
            if cancelled():
                raise InterruptedError("任务已取消")
            report = {"status": "ready_for_visual_review", "scope": "full_baseline_plus_inplace_tail",
                      "visual_version": manifest["visual_version"],
                      "source_endpoint_verified": True, "last_source_seconds": source_endpoint,
                      "new_model_calls": 0, "source_video": source_info, "baseline_video": baseline_info,
                      "tail_video": tail_info, "render": render_metrics, "full_video": webm, "mp4": compatibility,
                      "analysis_duration_seconds": baseline_info["duration_seconds"],
                      "tail_start_seconds": baseline_info["duration_seconds"],
                      "tail_duration_seconds": manifest["duration_seconds"],
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "original_hashes_before": before, "original_hashes_after": after,
                      "originals_unchanged": True, "user_visual_accepted": False,
                      "real_phone_verified": False, "four_gib_server_verified": False}
            write_json(stage / "build-report.json", report)
            names = ["manifest.json", "render-metrics.json", "build-report.json", "tail.webm", "enhanced.webm"]
            if compatibility["status"] == "ready":
                names.append("enhanced.mp4")
            elif (output / "enhanced.mp4").exists():
                os.replace(output / "enhanced.mp4", output / f"enhanced-previous-{time.time_ns()}.mp4")
            for name in names:
                os.replace(stage / name, output / name)
        if progress:
            progress("完整结尾复盘已生成，等待视觉评审", 100)
        return report
    finally:
        if {str(path): sha256(path) for path in protected} != before:
            raise RuntimeError("Original evidence was modified; do not accept this build")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("evidence", "review-dir", "output", "manifest"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    if args.cancel_file and ".local" in [p.lower() for p in args.cancel_file.resolve().parts]:
        parser.error("The cancellation marker must not be in .local")
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("Timeout must be positive and finite")
    interrupted = False

    def interrupt(*_):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    cancelled = lambda: interrupted or bool(args.cancel_file and args.cancel_file.exists())

    def progress(label, value):
        print(json.dumps({"stage": label, "progress": value}, ensure_ascii=False), flush=True)

    try:
        report = build_sample(args.evidence, args.review_dir, args.output, args.manifest,
                              cancelled=cancelled, progress=progress, timeout_seconds=args.timeout_seconds)
        print(json.dumps({"status": report["status"], "elapsed_seconds": report["elapsed_seconds"],
                          "body_frames_identical": report["full_video"]["body_frames_identical"],
                          "mp4_status": report["mp4"]["status"], "originals_unchanged": True}, ensure_ascii=False))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "cancelled" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                          "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
