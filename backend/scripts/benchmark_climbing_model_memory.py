"""Benchmark the production climbing-mask chain without requiring annotations.

Each run uses a fresh child process so the reported peak includes imports, model
loading, inference, color classification, and generation of review assets. The
supervisor samples the complete process tree; application data is never used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_photo_route_benchmark import run_process


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker(image: Path, output: Path) -> int:
    from core.photo_route_analysis import analyze_board_photo
    from core.photo_route_colors import CANDIDATE_COLOR_VERSION

    started = time.monotonic()
    result = analyze_board_photo(
        image,
        output,
        require_climbing_model=True,
        color_version=CANDIDATE_COLOR_VERSION,
        boundary_refinement=False,
    )
    summary = {
        "status": "completed",
        "seconds": round(time.monotonic() - started, 3),
        "candidate_count": len(result["objects"]),
        "model_version": result["model_version"],
        "processing_config": result["processing_config"],
        "input_sha256": digest(image),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=True), flush=True)
    return 0


def benchmark(args: argparse.Namespace) -> int:
    for label, path in (("config", args.config), ("checkpoint", args.checkpoint)):
        if not path.is_file():
            raise ValueError(f"{label} does not exist: {path}")
    if not 1 <= args.repeat <= 10:
        raise ValueError("repeat must be between 1 and 10")
    if args.max_peak_memory_mb is not None and args.max_peak_memory_mb <= 0:
        raise ValueError("max peak memory must be positive")
    images = [path.resolve() for path in args.images]
    if not images or any(not path.is_file() for path in images):
        raise ValueError("all benchmark images must exist")
    args.output.mkdir(parents=True, exist_ok=False)

    environment = os.environ.copy()
    environment["PHOTO_ROUTE_CLIMBING_MODEL_CONFIG"] = str(args.config.resolve())
    environment["PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT"] = str(args.checkpoint.resolve())
    runs = []
    script = Path(__file__).resolve()
    for image_index, image in enumerate(images, 1):
        for repeat_index in range(1, args.repeat + 1):
            run_dir = args.output / f"image-{image_index:02d}-run-{repeat_index:02d}"
            worker_output = Path(tempfile.mkdtemp(prefix="climb-memory-"))
            try:
                command = [sys.executable, str(script), "--worker-image", str(image),
                           "--worker-output", str(worker_output)]
                previous = os.environ.copy()
                os.environ.update(environment)
                try:
                    measurement = run_process(command, run_dir, args.timeout_seconds)
                finally:
                    os.environ.clear()
                    os.environ.update(previous)
                result_path = worker_output / "result.json"
                if measurement["status"] == "completed" and result_path.is_file():
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    measurement.update({
                        "image": str(image),
                        "image_sha256": result["input_sha256"],
                        "algorithm_seconds": result["seconds"],
                        "candidate_count": result["candidate_count"],
                        "model_version": result["model_version"],
                        "processing_config": result["processing_config"],
                    })
                else:
                    measurement.update({"image": str(image), "status": "failed"})
                runs.append(measurement)
                if measurement["status"] == "completed":
                    shutil.rmtree(run_dir, ignore_errors=True)
            finally:
                shutil.rmtree(worker_output, ignore_errors=True)

    peaks = [run["peak_resident_mib"] for run in runs
             if run["status"] == "completed" and run["peak_resident_mib"] is not None]
    budget = args.max_peak_memory_mb
    report = {
        "schema_version": 1,
        "scope": "cold process-tree imports, model load, inference, interior-v4 color classification, and review-asset generation",
        "excludes": ["upload transfer", "other server services", "swap", "human review"],
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "config_sha256": digest(args.config),
        "checkpoint_sha256": digest(args.checkpoint),
        "runs": runs,
        "peak_resident_mib": max(peaks) if peaks else None,
        "memory_limit_mib": budget,
        "measurement_complete": len(peaks) == len(runs),
        "memory_gate_passed": bool(peaks and len(peaks) == len(runs)
                                   and budget is not None and max(peaks) <= budget),
        "target_hardware_verified": False,
    }
    (args.output / "memory-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if all(run["status"] == "completed" for run in runs) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, nargs="+")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--max-peak-memory-mb", type=int)
    parser.add_argument("--worker-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_image or args.worker_output:
        if not args.worker_image or not args.worker_output:
            parser.error("worker image and output must be provided together")
        return worker(args.worker_image.resolve(), args.worker_output.resolve())
    if not all((args.images, args.config, args.checkpoint, args.output)):
        parser.error("images, config, checkpoint, and output are required")
    return benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
