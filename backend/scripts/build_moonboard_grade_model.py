"""Build the deterministic MoonBoard Font-grade transfer artifact."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from core.moonboard_grading import FONT_GRADES, MODEL_PATH, route_feature_vector  # noqa: E402


DATASET_PATH = BACKEND_DIR / "data" / "raw_datasets" / "moonGen_scrape_2016_final"
BENCHMARK_WEIGHT = 4.0
CLASS_BALANCE_POWER = 0.4
RIDGE_LAMBDA = 50.0
OVERALL_GATE = 0.68
BENCHMARK_GATE = 0.75
BIAS_GATE = 0.5


def _coord_label(coord: Any) -> str | None:
    try:
        x_index, y_index = int(coord[0]), int(coord[1])
    except (IndexError, TypeError, ValueError):
        return None
    if not 0 <= x_index < 11 or not 1 <= y_index <= 18:
        return None
    return f"{chr(ord('A') + x_index)}{y_index}"


def _roles(raw_route: dict[str, Any]) -> dict[str, list[str]]:
    return {
        role: [
            label
            for coord in raw_route.get(role) or []
            for label in [_coord_label(coord)]
            if label
        ]
        for role in ("start", "mid", "end")
    }


def _repeat_weight(repeats: int) -> float:
    return 1.0 + min(math.log1p(max(0, repeats)) / math.log(101), 1.5)


def build_model() -> dict[str, Any]:
    dataset_bytes = DATASET_PATH.read_bytes()
    raw_data = pickle.loads(dataset_bytes)
    grade_index = {grade: index for index, grade in enumerate(FONT_GRADES)}
    rows = []
    for source_id, raw_route in raw_data.items():
        grade = str(raw_route.get("grade") or raw_route.get("Grade") or "").upper()
        if grade not in grade_index:
            continue
        features = route_feature_vector(_roles(raw_route))
        benchmark = bool(raw_route.get("is_benchmark"))
        weight = (BENCHMARK_WEIGHT if benchmark else 1.0) * _repeat_weight(int(raw_route.get("repeats") or 0))
        split = int(hashlib.sha1(str(source_id).encode("utf-8")).hexdigest()[:8], 16) % 5
        rows.append((features, grade_index[grade], weight, split, benchmark, grade))

    x_values = np.asarray([row[0] for row in rows], dtype=np.float64)
    labels = np.asarray([row[1] for row in rows], dtype=np.int64)
    base_weights = np.asarray([row[2] for row in rows], dtype=np.float64)
    splits = np.asarray([row[3] for row in rows], dtype=np.int64)
    benchmarks = np.asarray([row[4] for row in rows], dtype=np.bool_)
    train_mask = splits != 0
    test_mask = ~train_mask

    means = x_values[train_mask, -18:].mean(axis=0)
    stds = x_values[train_mask, -18:].std(axis=0)
    stds[stds < 1e-6] = 1.0
    x_values[:, -18:] = (x_values[:, -18:] - means) / stds

    counts = np.bincount(labels[train_mask], minlength=len(FONT_GRADES))
    class_weights = (counts.max() / np.maximum(counts, 1)) ** CLASS_BALANCE_POWER
    weights = base_weights * class_weights[labels]
    design = np.column_stack((x_values, np.ones(len(x_values), dtype=np.float64)))
    weighted_design = design[train_mask] * np.sqrt(weights[train_mask, None])
    weighted_labels = labels[train_mask] * np.sqrt(weights[train_mask])
    matrix = weighted_design.T @ weighted_design
    matrix.flat[:: matrix.shape[0] + 1] += RIDGE_LAMBDA
    matrix[-1, -1] -= RIDGE_LAMBDA
    coefficients = np.linalg.solve(matrix, weighted_design.T @ weighted_labels)

    raw_predictions = design[test_mask] @ coefficients
    predictions = np.clip(np.rint(raw_predictions), 0, len(FONT_GRADES) - 1).astype(np.int64)
    expected = labels[test_mask]
    differences = predictions - expected
    absolute_differences = np.abs(differences)
    benchmark_differences = absolute_differences[benchmarks[test_mask]]
    metrics = {
        "holdout_count": int(test_mask.sum()),
        "benchmark_holdout_count": int(benchmarks[test_mask].sum()),
        "exact_accuracy": round(float(np.mean(absolute_differences == 0)), 4),
        "within_one_accuracy": round(float(np.mean(absolute_differences <= 1)), 4),
        "benchmark_within_one_accuracy": round(float(np.mean(benchmark_differences <= 1)), 4),
        "mean_absolute_error": round(float(np.mean(absolute_differences)), 4),
        "mean_bias": round(float(np.mean(differences)), 4),
    }
    calibration_ready = (
        metrics["within_one_accuracy"] >= OVERALL_GATE
        and metrics["benchmark_within_one_accuracy"] >= BENCHMARK_GATE
        and abs(metrics["mean_bias"]) < BIAS_GATE
    )
    return {
        "version": "font-transfer-v1",
        "grade_system": "font",
        "grade_order": list(FONT_GRADES),
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "sample_count": len(rows),
        "sample_counts": dict(Counter(row[5] for row in rows)),
        "benchmark_count": int(sum(row[4] for row in rows)),
        "split": "sha1(source_id) modulo 5; zero is holdout",
        "parameters": {
            "benchmark_weight": BENCHMARK_WEIGHT,
            "class_balance_power": CLASS_BALANCE_POWER,
            "ridge_lambda": RIDGE_LAMBDA,
            "overall_within_one_gate": OVERALL_GATE,
            "benchmark_within_one_gate": BENCHMARK_GATE,
            "absolute_bias_gate": BIAS_GATE,
        },
        "metrics": metrics,
        "calibration_ready": calibration_ready,
        "feature_mean": [round(float(value), 8) for value in means],
        "feature_std": [round(float(value), 8) for value in stds],
        "coefficients": [round(float(value), 10) for value in coefficients],
    }


if __name__ == "__main__":
    model = build_model()
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(MODEL_PATH), "metrics": model["metrics"], "calibration_ready": model["calibration_ready"]}, ensure_ascii=False))
