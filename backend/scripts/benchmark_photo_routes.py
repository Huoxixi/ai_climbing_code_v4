"""Generate local segmentation evidence, without touching application assets.

Example (from backend):
  python scripts/benchmark_photo_routes.py --image wall.jpg --seed .4 .3 --output /tmp/evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from core.photo_route_processing import cutout, decode_photo, extract_candidates
from scripts.evaluate_photo_routes import result_fingerprint


def save_image(path: Path, image: np.ndarray):
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise RuntimeError(f"Image encoding failed: {path.name}")
    path.write_bytes(encoded.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--seed", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-refine", action="store_true")
    parser.add_argument("--hue-tolerance", type=float, default=12)
    parser.add_argument("--mobile-sam-repo", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--prune-inspection", action="store_true", help="Experimental v6; contour validation still required")
    parser.add_argument("--batch-size", type=int, choices=[1, 2, 4, 8], default=8)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16 or not 0 < args.timeout_seconds <= 180:
        parser.error("Use 1–16 threads and a deadline of at most 180 seconds")
    if args.output.exists():
        parser.error("Output already exists; use a new directory to preserve previous evidence")
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    data = args.image.read_bytes()
    photo = decode_photo(data)
    model_sha = None
    if args.mobile_sam_repo:
        if not args.checkpoint:
            parser.error("--checkpoint is required with --mobile-sam-repo")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        sys.path.insert(0, str(args.mobile_sam_repo.resolve()))
        from core.photo_route_mobilesam import extract_with_mobilesam
        model_sha = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
        result = extract_with_mobilesam(photo, tuple(args.seed), checkpoint=args.checkpoint,
                                       threads=args.threads, timeout_seconds=args.timeout_seconds,
                                       prune_inspection=args.prune_inspection, batch_size=args.batch_size)
    else:
        result = extract_candidates(photo, tuple(args.seed), refine=not args.no_refine,
                                    hue_tolerance=args.hue_tolerance, timeout_seconds=args.timeout_seconds)
    args.output.mkdir(parents=True, exist_ok=False)
    image = result.image
    overlay = image.copy()
    replica = np.full_like(image, 242)
    objects = []
    for index, candidate in enumerate(result.candidates, 1):
        name = f"object-{index:02d}"
        save_image(args.output / f"{name}.png", cutout(image, candidate))
        save_image(args.output / f"{name}-mask.png", candidate.mask)
        selected = candidate.mask > 0
        replica[selected] = image[selected]
        contours, _ = cv2.findContours(candidate.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (40, 40, 240), 2)
        x, y, w, h = candidate.bounds
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (20, 210, 40), 1)
        cv2.rectangle(overlay, (x, y), (x + 35, y + 27), (255, 255, 255), -1)
        cv2.putText(overlay, str(index), (x + 3, y + 21), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 2)
        objects.append({"id": name, "bbox": candidate.bounds, "area": int(np.count_nonzero(selected)),
                        "touches_border": candidate.touches_border,
                        "mask_sha256": hashlib.sha256((args.output / f"{name}-mask.png").read_bytes()).hexdigest()})
    save_image(args.output / "overlay.jpg", overlay)
    save_image(args.output / "replica.jpg", replica)
    report = {
        "algorithm": ("mobilesam-color-v6" if args.prune_inspection else "mobilesam-color-v5") if args.mobile_sam_repo else "opencv-color-grabcut-v2", "refine": not args.no_refine,
        "model_sha256": model_sha, "torch_threads": args.threads if args.mobile_sam_repo else None,
        "batch_size": args.batch_size if args.mobile_sam_repo else None,
        "source_name": args.image.name, "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_dimensions": [photo.shape[1], photo.shape[0]],
        "working_dimensions": [image.shape[1], image.shape[0]], "seed": args.seed,
        "hue_tolerance": args.hue_tolerance, "seed_hue": result.seed_hue,
        "elapsed_seconds": round(result.duration_seconds, 3), "candidate_count": len(objects),
        "objects": objects, "warnings": result.warnings,
        "environment": {"platform": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count(), "opencv_threads": cv2.getNumThreads(), "opencv": cv2.__version__, "python": platform.python_version()},
        "acceptance": "UNASSESSED: candidates are not confirmed ground truth; server timing has not been measured",
    }
    report["result_sha256"] = result_fingerprint(report)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(objects), "elapsed_seconds": report["elapsed_seconds"], "output": str(args.output)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
