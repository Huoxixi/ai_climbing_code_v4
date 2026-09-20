"""Compare six input-size/candidate-cap settings on one development manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.photo_route_evaluation import evaluate_objects, summarize
from core.photo_route_processing import decode_photo
from scripts.run_photo_route_benchmark import run_process


SIZES = (1200, 1024, 960)
CAPS = (300, 200)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(manifest_path: Path, config: Path, checkpoint: Path, output: Path,
            timeout_seconds: float = 180) -> dict:
    for path in (manifest_path, config, checkpoint):
        if not path.is_file():
            raise ValueError(f"missing input: {path}")
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    eligible = [sample for sample in manifest["samples"]
                if sample.get("annotations_available", True)
                and not sample.get("evaluation_exclusion")]
    if not eligible or not all(sample.get("objects") for sample in eligible):
        raise ValueError("development comparison requires non-empty reviewed annotations")

    runner = Path(__file__).with_name("run_climbing_instance_model.py")
    rows = []
    for size in SIZES:
        for cap in CAPS:
            name = f"min{size}-cap{cap}"
            run_dir = output / name
            worker_root = Path(tempfile.mkdtemp(prefix=f"grid-{size}-{cap}-"))
            prediction_root = worker_root / "predictions"
            try:
                worker_manifest = worker_root / "manifest.json"
                worker_manifest.write_text(json.dumps(
                    {**manifest, "samples": eligible}, ensure_ascii=False
                ), encoding="utf-8")
                command = [
                    sys.executable, str(runner),
                    "--manifest", str(worker_manifest),
                    "--config", str(config.resolve()),
                    "--checkpoint", str(checkpoint.resolve()),
                    "--output", str(prediction_root),
                    "--threads", "2",
                    "--threshold", "0.4",
                    "--color-version", "interior-v4",
                    "--min-size", str(size),
                    "--max-detections", str(cap),
                ]
                process = run_process(command, run_dir, timeout_seconds)
                if process["status"] != "completed":
                    rows.append({"name": name, "min_size": size, "candidate_cap": cap,
                                 "status": process["status"], "process": process})
                    continue
                evaluation_rows = []
                for index, sample in enumerate(eligible, 1):
                    image_path = Path(sample["image"])
                    prediction_path = prediction_root / f"sample-{index}" / "result.json"
                    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
                    if digest(image_path) != prediction["input_fingerprint"]:
                        raise ValueError("prediction/image fingerprint mismatch")
                    shape = decode_photo(image_path.read_bytes()).shape[:2]
                    evaluation_rows.append(evaluate_objects(
                        sample["objects"], prediction["objects"], shape
                    ))
                metrics = summarize(evaluation_rows)
                run_report = json.loads((prediction_root / "run-report.json").read_text(encoding="utf-8"))
                rows.append({
                    "name": name,
                    "min_size": size,
                    "max_size": run_report["recipe"]["max_size_test"],
                    "candidate_cap": cap,
                    "score_threshold": 0.4,
                    "status": "completed",
                    "peak_resident_mib": process["peak_resident_mib"],
                    "wall_seconds": process["wall_seconds"],
                    "truth": metrics["counts"]["truth"],
                    "predictions": metrics["counts"]["predictions"],
                    "matched": metrics["counts"]["matched"],
                    "precision": metrics["object_precision"],
                    "recall": metrics["object_recall"],
                    "f1": (2 * metrics["object_precision"] * metrics["object_recall"] /
                           (metrics["object_precision"] + metrics["object_recall"])),
                    "boundary_f1": metrics["boundary_f1"],
                    "severe_contour_failures": metrics["severe_contour_failures"],
                    "effective_config_sha256": run_report["recipe"]["config_sha256"],
                })
                shutil.rmtree(run_dir, ignore_errors=True)
            finally:
                shutil.rmtree(worker_root, ignore_errors=True)
            (output / "report.json").write_text(json.dumps({
                "schema_version": 1,
                "model": "current climbing Mask R-CNN candidate",
                "checkpoint_sha256": digest(checkpoint),
                "base_config_sha256": digest(config),
                "manifest_sha256": digest(manifest_path),
                "comparison_constants": {
                    "score_threshold": 0.4,
                    "color_version": "interior-v4",
                    "threads": 2,
                    "matching": "maximum-cardinality IoU >= 0.5",
                },
                "rows": rows,
                "formal_acceptance": False,
                "limitations": [
                    "Two public development images and 179 objects; not an independent holdout.",
                    "Memory is a cold process-tree peak on the local Windows CPU environment.",
                    "Target-server services, upload transfer, swap, and human review are excluded.",
                ],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args()
    result = compare(args.manifest, args.config, args.checkpoint, args.output,
                     timeout_seconds=args.timeout_seconds)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if all(row["status"] == "completed" for row in result["rows"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
