"""Inspect saved replay analyses offline without models, keys or source mutation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.replay_action_naming import enrich_names


def inspect(path):
    original = json.loads(path.read_text(encoding="utf-8"))
    result = enrich_names(original)
    events = [{"group_id": g["id"], "event_id": e["id"], "limb": e["limb"],
               "start_seconds": e["start_seconds"], "end_seconds": e["end_seconds"],
               "evidence_status": e.get("evidence_status"), "name": e["display_name"],
               "trajectory_details": e.get("trajectory_details")} for g in result["groups"] for e in g["events"]]
    return {"sample": path.name, "status": "regression_observation_only", "independent_accuracy": "not_measured",
            "cloud_calls": 0, "source_pose_samples": len(result.get("pose_samples", [])),
            "event_status_counts": dict(Counter(e["trajectory_details"]["status"] for e in events)),
            "motion_analysis": result.get("motion_analysis"), "events": events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = {"validation": "existing_samples_are_regression_only", "samples": [inspect(p) for p in args.inputs]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("Use a new diagnostic output path; existing evidence is retained")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"samples": len(payload["samples"]), "output": str(args.output)}, ensure_ascii=False))
