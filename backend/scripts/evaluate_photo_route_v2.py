"""Evaluate V2 object recall/precision and anchor accuracy on local annotations.

Manifest format is documented in docs/照片线路V2标注与验收.md. Images and
annotations never leave this computer.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from core.photo_route_analysis import analyze_board_photo


def mask_for(contour, shape):
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.asarray(contour, np.int32)], 1)
    return mask


def iou(first, second):
    overlap = np.count_nonzero((first > 0) & (second > 0))
    union = np.count_nonzero((first > 0) | (second > 0))
    return overlap / union if union else 0.0


def evaluate(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total_truth = total_predictions = matched = correct_anchors = anchor_total = severe = 0
    per_image = []
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        for sample in manifest["samples"]:
            image_path = (manifest_path.parent / sample["image"]).resolve()
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None: raise ValueError(f"无法读取标注图片：{sample['image']}")
            result = analyze_board_photo(image_path, output / image_path.stem)
            truth = sample["objects"]; predictions = result["objects"]
            truth_masks = [mask_for(item["contour"], image.shape[:2]) for item in truth]
            prediction_masks = [mask_for(item["contour"], image.shape[:2]) for item in predictions]
            candidates = sorted(((iou(tmask, pmask), ti, pi) for ti, tmask in enumerate(truth_masks)
                                 for pi, pmask in enumerate(prediction_masks)), reverse=True)
            used_truth, used_predictions, pairs = set(), set(), []
            for score, ti, pi in candidates:
                if score < .5 or ti in used_truth or pi in used_predictions: continue
                used_truth.add(ti); used_predictions.add(pi); pairs.append((score, ti, pi))
            image_severe = sum(score < .65 for score, _, _ in pairs)
            for _, ti, pi in pairs:
                expected = set(truth[ti].get("hole_ids", []))
                proposed = {item["hole_id"] for item in predictions[pi].get("anchors", [])}
                anchor_total += len(expected); correct_anchors += len(expected & proposed)
            total_truth += len(truth); total_predictions += len(predictions); matched += len(pairs); severe += image_severe
            per_image.append({"image": sample["image"], "holdout": bool(sample.get("holdout")),
                              "truth": len(truth), "predictions": len(predictions), "matched": len(pairs),
                              "severe_contour_failures": image_severe})
    recall = matched / total_truth if total_truth else 0
    precision = matched / total_predictions if total_predictions else 0
    anchor_accuracy = correct_anchors / anchor_total if anchor_total else 0
    return {"object_recall": recall, "object_precision": precision, "anchor_accuracy": anchor_accuracy,
            "severe_contour_failures": severe, "counts": {"truth": total_truth, "predictions": total_predictions,
            "matched": matched, "anchors": anchor_total}, "per_image": per_image,
            "passed": recall >= .9 and precision >= .9 and anchor_accuracy >= .95 and severe == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.manifest)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output: args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__": main()
