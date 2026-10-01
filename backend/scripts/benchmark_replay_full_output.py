"""Compare base and enhanced export, including the tail's second encode.

The fixed 2-second source and contacts are clearly labelled demonstration data.
The parent measures the whole export process tree, including its visual worker.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def render_case(directory: Path, enhanced: bool):
    import cv2
    from core.climb_replay import render_replay_overlay_video
    cv2.setNumThreads(1)
    os.environ["CLIMB_REPLAY_VISUAL_ENABLED"] = "1" if enhanced else "0"
    result = json.loads((directory / "input.json").read_text(encoding="utf-8"))
    start = time.monotonic()
    output = directory / ("enhanced-full.webm" if enhanced else "base-full.webm")
    overlay = render_replay_overlay_video(directory / "source.mp4", output, result)
    metrics = {"elapsed_seconds": round(time.monotonic() - start, 3), "overlay": overlay,
               "visual_replay": result.get("visual_replay"), "size_bytes": output.stat().st_size}
    (directory / ("enhanced-render.json" if enhanced else "base-render.json")).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(sample: Path, directory: Path):
    import cv2
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    result = json.loads((sample / "frozen-input.json").read_text(encoding="utf-8"))
    image = cv2.imdecode(np.fromfile(str(sample / "reference.jpg"), np.uint8), cv2.IMREAD_COLOR)
    image = cv2.resize(image, (720, 1280), interpolation=cv2.INTER_AREA)
    fps, frames = 24, 48
    source = directory / "source.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), fps, (720, 1280))
    if not writer.isOpened():
        raise RuntimeError("MP4 fixture writer unavailable")
    try:
        for _ in range(frames):
            writer.write(image)
    finally:
        writer.release()
    contacts = result["attempt"]["contacts"]
    maximum = max(e["start_time_seconds"] for e in contacts)
    for contact in contacts:
        second = round(contact["start_time_seconds"] / maximum * 1.6, 3)
        contact.update(start_time_seconds=second, end_time_seconds=second + .2,
                       start_source_frame=round(second * fps), end_source_frame=min(frames - 1, round((second + .2) * fps)))
    for hold in result["holds"]:
        points = np.asarray(hold["polygon"])
        low, high = points.min(axis=0), points.max(axis=0)
        hold["bbox"] = [*low.tolist(), *(high - low).tolist()]
    result.update(video={"width": 720, "height": 1280, "fps": fps, "frame_count": frames,
                         "duration_seconds": frames / fps}, hold_evidence={"reference_frame": 0}, pose_samples=[])
    (directory / "input.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def measured_case(directory: Path, enhanced: bool):
    import psutil
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    name = "enhanced" if enhanced else "base"
    log_path = directory / f"{name}-process.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--output", str(directory.resolve()),
                                    "--case", name], stdout=log, stderr=log, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        root = psutil.Process(process.pid)
        peak, available, start = 0., float("inf"), time.monotonic()
        while process.poll() is None:
            try:
                tree = [root, *root.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in tree if p.is_running()) / 2**20
                peak = max(peak, rss)
                available = min(available, psutil.virtual_memory().available / 2**20)
            except psutil.NoSuchProcess:
                pass
            if time.monotonic() - start > 120:
                for child in root.children(recursive=True):
                    child.kill()
                process.kill()
                process.wait()
                raise RuntimeError("Full-output acceptance exceeded 120 seconds")
            try:
                process.wait(timeout=.05)
            except subprocess.TimeoutExpired:
                pass
    if process.returncode:
        raise RuntimeError(f"{name} export failed; see {log_path}")
    metrics = json.loads((directory / f"{name}-render.json").read_text(encoding="utf-8"))
    metrics["process_tree"] = {"peak_rss_mib": round(peak, 2), "system_min_available_mib": round(available, 2),
                               "wall_with_import_seconds": round(time.monotonic() - start, 3)}
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("base", "enhanced"))
    args = parser.parse_args()
    if args.case:
        render_case(args.output, args.case == "enhanced")
        return
    prepare(args.sample, args.output)
    base = measured_case(args.output, False)
    print(json.dumps({"case": "base", "elapsed_seconds": base["elapsed_seconds"], "resources": base["process_tree"]}), flush=True)
    enhanced = measured_case(args.output, True)
    report = {"scope": "Local workstation; same 2-second 720x1280/24fps real-wall still source and illustrative contacts; not a long-video or 4 GiB server result",
              "base": base, "enhanced": enhanced,
              "incremental_elapsed_seconds": round(enhanced["elapsed_seconds"] - base["elapsed_seconds"], 3),
              "includes_temporary_tail_encoding_and_final_append_encoding": True,
              "incremental_under_30_seconds_target": enhanced["elapsed_seconds"] - base["elapsed_seconds"] <= 30,
              "temporary_files_remaining": [str(p.relative_to(args.output)) for p in args.output.rglob("*")
                                            if p.name.endswith((".tmp.webm", ".partial.webm"))]}
    if (enhanced.get("visual_replay") or {}).get("status") != "ready":
        raise RuntimeError("Enhanced case fell back; cannot claim full-output acceptance")
    (args.output / "full-output-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"incremental_elapsed_seconds": report["incremental_elapsed_seconds"],
                      "enhanced_resources": enhanced["process_tree"]}), flush=True)


if __name__ == "__main__":
    main()
