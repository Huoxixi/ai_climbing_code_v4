"""Bounded local CPU-render acceptance; never a claim about production capacity."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.replay_resources import run_visual_worker, psutil
from core.replay_visual_renderer import build_visual_manifest


def prepare_cases(sample: Path, directory: Path):
    frozen = json.loads((sample / "frozen-input.json").read_text(encoding="utf-8"))
    original = json.loads((sample / "manifest.json").read_text(encoding="utf-8"))
    source = cv2.imdecode(np.fromfile(str(sample / "reference.jpg"), np.uint8), cv2.IMREAD_COLOR)
    cases = []
    for name, fps, landscape in (("portrait-24", 24, False), ("portrait-30", 30, False),
                                  ("landscape-24", 24, True), ("landscape-30", 30, True)):
        target = directory / name
        target.mkdir(parents=True, exist_ok=True)
        result = json.loads(json.dumps(frozen))
        metadata = dict(original["reference"])
        pixels = source
        if landscape:
            # A real crop, with coordinates recomputed and partially visible
            # holds omitted. No invented scene or generated wall extension.
            top, bottom = 620, 1076
            pixels = source[top:bottom]
            height, width = source.shape[:2]
            chosen = []
            for hold in result["holds"]:
                points = np.asarray(hold["polygon"]) * [width, height]
                if points[:, 1].min() >= top and points[:, 1].max() < bottom:
                    points[:, 1] -= top
                    hold["polygon"] = (points / [width, bottom - top]).tolist()
                    chosen.append(hold)
            result["holds"] = chosen
            ids = {item["id"] for item in chosen}
            result["attempt"]["contacts"] = [e for e in result["attempt"]["contacts"] if e["hold_id"] in ids]
            metadata.update(width=pixels.shape[1], height=pixels.shape[0], quality="limited",
                            source_crop_xyxy=[0, top, width, bottom])
        reference = target / "reference.jpg"
        cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 94])[1].tofile(str(reference))
        metadata["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
        manifest = build_visual_manifest(result, metadata, fps=fps,
                                          output_size=(1280, 720) if landscape else (720, 1280))
        manifest_path = target / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        cases.append((name, reference, manifest_path, target))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        raise ValueError("Use 1-10 bounded sequential runs")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = prepare_cases(args.sample, args.output)
    memory = psutil.virtual_memory()
    report = {"environment": {"os": platform.platform(), "logical_cpus": psutil.cpu_count(),
                              "system_total_mib": round(memory.total / 2**20, 2),
                              "python": platform.python_version(), "opencv": cv2.__version__,
                              "scope": "Local workstation, not a 4 GiB server test"},
              "runs": [], "acceptance": "Only rendering resources; real contacts and target-mobile acceptance pending"}
    initial = time.monotonic()
    for index in range(args.runs):
        name, reference, manifest, target = cases[index % len(cases)]
        output = target / f"run-{index + 1:02}.webm"
        metrics_path = target / f"run-{index + 1:02}.json"
        metrics = run_visual_worker(reference, manifest, output, metrics_path)
        report["runs"].append(dict(case=name, ordinal=index + 1, **metrics))
        print(json.dumps({"run": index + 1, "case": name, "resources": metrics["resources"]}), flush=True)
        # Keep one playable result per case, only discard repeat files created
        # by this exact benchmark invocation.
        if index >= len(cases):
            output.unlink()
        report["elapsed_seconds"] = round(time.monotonic() - initial, 3)
        (args.output / "resource-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["summary"] = {
        "runs_completed": len(report["runs"]),
        "max_tree_peak_rss_mib": max(r["resources"]["tree_peak_rss_mib"] for r in report["runs"]),
        "min_system_available_mib": min(r["resources"]["system_min_available_mib"] for r in report["runs"]),
        "max_elapsed_seconds": max(r["resources"]["elapsed_seconds"] for r in report["runs"]),
        "under_512_mib_target": all(r["resources"]["tree_peak_rss_mib"] <= 512 for r in report["runs"]),
        "under_30_seconds_target": all(r["resources"]["elapsed_seconds"] <= 30 for r in report["runs"]),
        "temporary_files_remaining": [str(p.relative_to(args.output)) for p in args.output.rglob("*.webm")
                                      if p.name.endswith((".tmp.webm", ".partial.webm"))],
    }
    (args.output / "resource-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    main()
