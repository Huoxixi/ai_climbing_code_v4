"""Offline action evaluation. Constructed cases never grant video approval."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from .replay_action_naming import finite, hold_key, NAMING_VERSION


def wilson(success, total):
    if not total:
        return None
    z = 1.959964
    p = success / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0., center-half), min(1., center+half)]


def matches(prediction, reference):
    if any(prediction.get(k) != reference.get(k) for k in ("code", "limb")):
        return False
    if any(hold_key(prediction.get(k)) != hold_key(reference.get(k)) for k in ("source_hold_id", "target_hold_id")):
        return False
    pstart, pend = prediction.get("start_seconds"), prediction.get("end_seconds")
    rstart, rend = reference.get("start_seconds"), reference.get("end_seconds")
    if not all(finite(t) for t in (pstart, pend, rstart, rend)) or not pstart < pend or not rstart < rend:
        return False
    intersection = max(0., min(pend, rend)-max(pstart, rstart))
    union = max(pend, rend)-min(pstart, rstart)
    return intersection/union >= .5 and max(abs(pstart-rstart), abs(pend-rend)) <= .5


def evaluate(dataset):
    rows = dataset.get("attempts", [])
    if not isinstance(rows, list):
        raise ValueError("attempts must be a list")
    reviewers = dataset.get("reviewers", [])
    protocol_ok = (dataset.get("naming_version") == NAMING_VERSION and dataset.get("protocol_frozen") is True
                   and dataset.get("independent_blind_review") is True and dataset.get("disagreements_resolved") is True
                   and isinstance(reviewers, list) and len(reviewers) == 2 and all(isinstance(r, str) and r for r in reviewers) and len(set(reviewers)) == 2)
    # Connected user/route groups, not neighbouring frames, are the units.
    parent = {}
    def root(node):
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = root(parent[node])
        return parent[node]
    for row in rows:
        if not isinstance(row, dict) or not row.get("participant_group") or not row.get("route_group") or row.get("split") not in {"development", "holdout"}:
            raise ValueError("Every attempt needs participant/route groups and a split")
        left, right = "p:"+str(row["participant_group"]), "r:"+str(row["route_group"])
        parent[root(left)] = root(right)
    splits = defaultdict(set)
    for row in rows:
        splits[root("p:"+str(row["participant_group"]))].add(row["split"])
    leakage = any(len(s) > 1 for s in splits.values())
    counts = defaultdict(lambda: {"correct": 0, "predictions": 0, "positives": 0, "negatives": 0,
                                  "eligible": 0, "all_references": 0, "groups": set(), "group_predictions": defaultdict(list),
                                  "unsupported": 0, "timing_errors": [], "candidate_predictions": 0, "candidate_correct": 0})
    seen = set()
    holdout = [row for row in rows if row["split"] == "holdout"]
    authentic = bool(holdout)
    for row in holdout:
        if not isinstance(row.get("attempt_id"), str) or row["attempt_id"] in seen:
            raise ValueError("Attempt IDs must be unique")
        seen.add(row["attempt_id"])
        authentic &= row.get("real_video") is True and row.get("authorized") is True
        references, predictions = row.get("references", []), row.get("predictions", [])
        if not isinstance(references, list) or not isinstance(predictions, list):
            raise ValueError("References and predictions must be lists")
        used, candidate_used = set(), set()
        group = root("p:"+str(row["participant_group"]))
        classes = set()
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError("Reference must be an object")
            code = reference.get("code")
            if not isinstance(code, str) or not code:
                raise ValueError("Reference code is required")
            stat = counts[code]; classes.add(code)
            stat["all_references"] += 1
            if reference.get("eligible") is True:
                stat["eligible"] += 1
                stat["positives"] += 1
        for code in row.get("negative_codes", []):
            if not isinstance(code, str):
                raise ValueError("Negative code must be a string")
            counts[code]["negatives"] += 1
            classes.add(code)
        for prediction in predictions:
            if not isinstance(prediction, dict) or prediction.get("status") not in {"locally_verified", "candidate", "human_confirmed"}:
                raise ValueError("Prediction must declare a supported review status")
            if prediction.get("status") == "human_confirmed":
                continue  # personal corrections are not algorithm results
            code = prediction.get("code")
            if not isinstance(code, str) or not code:
                raise ValueError("Prediction code is required")
            stat = counts[code]; classes.add(code)
            if prediction.get("status") == "candidate":
                stat["candidate_predictions"] += 1
                match = next((i for i, r in enumerate(references) if i not in candidate_used and r.get("eligible") is True and matches(prediction, r)), None)
                if match is not None:
                    candidate_used.add(match)
                    stat["candidate_correct"] += 1
                continue
            stat["predictions"] += 1
            supported = prediction.get("conditions_met") is True
            stat["unsupported"] += not supported
            eligible = [i for i, reference in enumerate(references) if i not in used and reference.get("eligible") is True and matches(prediction, reference)]
            correct = bool(eligible) and supported
            stat["correct"] += correct
            stat["group_predictions"][group].append(correct)
            same_identity = [r for r in references if all(prediction.get(k) == r.get(k) for k in ("code", "limb"))
                             and all(hold_key(prediction.get(k)) == hold_key(r.get(k)) for k in ("source_hold_id", "target_hold_id"))
                             and all(finite(r.get(k)) and finite(prediction.get(k)) for k in ("start_seconds", "end_seconds"))]
            if same_identity:
                stat["timing_errors"].append(min(max(abs(prediction['start_seconds']-r['start_seconds']), abs(prediction['end_seconds']-r['end_seconds'])) for r in same_identity))
            if correct:
                i = eligible[0]; used.add(i)
        for code in classes:
            counts[code]["groups"].add(group)
    results = {}
    for code, stat in counts.items():
        precision = stat["correct"]/stat["predictions"] if stat["predictions"] else None
        recall = stat["correct"]/stat["eligible"] if stat["eligible"] else None
        group_rows = list(stat["group_predictions"].values())
        # Conservative all-correct per-group interval alongside event precision.
        interval = wilson(sum(all(r) for r in group_rows), len(group_rows)) if len(group_rows) >= 20 else None
        errors = sorted(stat["timing_errors"])
        enough = stat["positives"] >= 60 and stat["negatives"] >= 60 and len(stat["groups"]) >= 20
        passed = bool(protocol_ok and authentic and not leakage and enough and precision is not None and precision >= .95
                      and recall is not None and recall >= .85 and interval and interval[0] >= .90 and not stat["unsupported"])
        results[code] = {k: v for k, v in stat.items() if k not in {"groups", "group_predictions", "timing_errors"}}
        results[code].update(precision=precision, recall=recall, coverage=stat['correct']/stat['all_references'] if stat['all_references'] else None,
                             eligible_opportunity_rate=stat['eligible']/stat['all_references'] if stat['all_references'] else None,
                             missed_eligible=stat['eligible']-stat['correct'],
                             candidate_precision=stat['candidate_correct']/stat['candidate_predictions'] if stat['candidate_predictions'] else None,
                             candidate_false_positives=stat['candidate_predictions']-stat['candidate_correct'],
                             independent_groups=len(stat["groups"]), conservative_group_interval95=interval,
                             timing_error_median=(errors[(len(errors)-1)//2]+errors[len(errors)//2])/2 if errors else None,
                             timing_error_p95=errors[min(len(errors)-1, math.ceil(len(errors)*.95)-1)] if errors else None,
                             meets_proposed_gate=passed)
    return {"naming_version": NAMING_VERSION, "real_holdout_available": authentic, "protocol_valid": protocol_ok,
            "development_holdout_leakage": leakage, "attempt_count": len(holdout), "classes": results,
            "automatic_confirmation_granted": False, "effect_improvement_established": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evaluated {report['attempt_count']} attempts; automatic confirmation not granted")


if __name__ == '__main__':
    main()
