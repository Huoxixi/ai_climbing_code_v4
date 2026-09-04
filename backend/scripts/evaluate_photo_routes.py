"""Score an explicit review without inferring ground truth from detections."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def result_fingerprint(report: dict) -> str:
    """Bind a review to actual output masks, not reusable candidate numbers."""
    fields = ("source_sha256", "algorithm", "model_sha256", "working_dimensions",
              "seed", "hue_tolerance", "objects")
    payload = {key: report.get(key) for key in fields}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def evaluate(report: dict, review: dict) -> dict:
    if report["source_sha256"] != review["source_sha256"] or report["algorithm"] != review["algorithm"]:
        raise ValueError("Review does not match the source image and algorithm version")
    fingerprint = result_fingerprint(report)
    if review.get("result_sha256") and review["result_sha256"] != fingerprint:
        raise ValueError("Review belongs to different extraction masks; review the new result")
    evidence_bound = (review.get("result_sha256") == fingerprint
                      and all(item.get("mask_sha256") for item in report["objects"]))
    objects = [item["id"] for item in report["objects"]]
    judgments = review["judgments"]
    reviewed = [item["candidate_id"] for item in judgments]
    if len(set(objects)) != len(objects) or len(set(reviewed)) != len(reviewed) or set(objects) != set(reviewed):
        raise ValueError("Every candidate must be reviewed exactly once")
    targets = review["target_ids"]
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("Target inventory must be nonempty and unique")
    for item in judgments:
        if not set(item["target_ids"]).issubset(targets):
            raise ValueError("Review names an unknown target")
    # A merged candidate cannot count as several separately editable objects.
    single_matches = [item["target_ids"][0] for item in judgments if len(item["target_ids"]) == 1]
    counts = Counter(single_matches)
    correct = len(counts)
    recall = correct / len(targets)
    precision = correct / len(objects) if objects else 0
    contour_errors = [item["candidate_id"] for item in judgments if item.get("major_contour_error")]
    unreviewed_contours = [item["candidate_id"] for item in judgments
                          if item["target_ids"] and not isinstance(item.get("major_contour_error"), bool)]
    unresolved = review.get("unresolved_inventory", [])
    performance = review.get("production_measurement", {})
    measured_seconds = performance.get("wall_seconds")
    measured_seconds_valid = (isinstance(measured_seconds, (int, float))
                              and not isinstance(measured_seconds, bool)
                              and 0 < measured_seconds <= 120)
    production_verified = (review.get("production_timing_verified") is True
                           and performance.get("result_sha256") == fingerprint
                           and bool(performance.get("evidence_path"))
                           and bool(performance.get("hardware"))
                           and performance.get("status") == "completed"
                           and measured_seconds_valid)
    return {
        "reviewer": review["reviewer"], "human_confirmed": review["human_confirmed"],
        "reference_target_count": len(targets), "candidate_count": len(objects),
        "one_to_one_matches": correct,
        "recall": round(recall, 4), "precision": round(precision, 4),
        "unmatched_target_ids": sorted(set(targets) - counts.keys()),
        "false_positive_candidate_ids": [item["candidate_id"] for item in judgments if not item["target_ids"]],
        "merged_candidate_ids": [item["candidate_id"] for item in judgments if len(item["target_ids"]) > 1],
        "duplicate_target_ids": sorted(target for target, count in counts.items() if count > 1),
        "major_contour_error_ids": contour_errors,
        "unreviewed_contour_ids": unreviewed_contours,
        "review_bound_to_result": bool(evidence_bound),
        "production_timing_verified": bool(production_verified),
        "unresolved_inventory": unresolved,
        "count_threshold_met": recall >= .9 and precision >= .9,
        "gate_passed": (review["human_confirmed"] and not unresolved and recall >= .9
                        and precision >= .9 and not contour_errors and not unreviewed_contours
                        and evidence_bound and production_verified),
        "correction_workflow_verified": review.get("correction_workflow_verified", False),
        "note": "Counts do not certify contours, correction time or production performance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.report.read_text("utf-8")), json.loads(args.review.read_text("utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
