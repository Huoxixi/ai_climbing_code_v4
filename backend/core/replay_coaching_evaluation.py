"""Offline, attempt-level evaluation. Synthetic checks are never effect evidence.

No media or personal information is read. Input identities must be opaque group
keys maintained by the evaluation owner, not names or account identifiers.
"""
from __future__ import annotations

import math
import random
from statistics import median


CATEGORIES = frozenset({"existing_foot_sequence", "same_foothold_preparation",
                        "existing_transition_preparation"})
ADVICE_CHECKS = ("facts_correct", "knowledge_supported", "conditions_met",
                 "adjustment_appropriate", "verification_appropriate")


def wilson_interval(successes: int, denominator: int) -> list[float] | None:
    if not denominator:
        return None
    z = 1.959963984540054
    p, z2 = successes / denominator, z * z
    center = (p + z2 / (2 * denominator)) / (1 + z2 / denominator)
    half = z * math.sqrt(p * (1 - p) / denominator + z2 / (4 * denominator ** 2)) / (1 + z2 / denominator)
    return [max(0.0, center - half), min(1.0, center + half)]


def _clusters(rows: list[dict]) -> list[list[int]]:
    """Connected user/route groups prevent repeated clips masquerading as N."""
    parents = list(range(len(rows)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    for index, row in enumerate(rows):
        for kind in ("participant_group", "route_group"):
            key = (kind, row[kind])
            if key in seen:
                parents[find(index)] = find(seen[key])
            else:
                seen[key] = index
    groups = {}
    for index in range(len(rows)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def _metric(rows, values, clusters):
    selected = [value for value in values if value is not None]
    successes, denominator = sum(selected), len(selected)
    interval = wilson_interval(successes, denominator)
    method = "wilson_95_independent_attempts"
    relevant = [[values[i] for i in group if values[i] is not None] for group in clusters]
    relevant = [group for group in relevant if group]
    if relevant and any(len(group) > 1 for group in relevant):
        method = "cluster_bootstrap_95_with_conservative_wilson_bound"
        # Few connected groups cannot establish a reliable uncertainty interval.
        if len(relevant) < 20:
            interval = None
            method = "insufficient_independent_groups"
        else:
            rng = random.Random(20260927)
            rates = []
            for _ in range(2000):
                sample = [rng.choice(relevant) for _ in relevant]
                rates.append(sum(sum(group) for group in sample) / sum(map(len, sample)))
            rates.sort()
            # Ordinary resampling gives [1, 1] when every answer is correct.
            # Preserve uncertainty using effective N = independent groups.
            group_rate = sum(selected) / denominator
            group_bound = wilson_interval(round(group_rate * len(relevant)), len(relevant))
            interval = [min(rates[49], group_bound[0]), max(rates[1949], group_bound[1])]
    return {"numerator": successes, "denominator": denominator,
            "estimate": successes / denominator if denominator else None,
            "interval_95": interval, "interval_method": method,
            "independent_groups": len(relevant)}


def _validate_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("attempts_must_be_list")
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_attempt")
        for name in ("attempt_id", "participant_group", "route_group"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError("missing_" + name)
        if row["attempt_id"] in ids:
            raise ValueError("duplicate_attempt")
        ids.add(row["attempt_id"])
        if not isinstance(row.get("strata", []), list) or any(not isinstance(value, str) for value in row.get("strata", [])):
            raise ValueError("invalid_strata")
        if row.get("category") not in CATEGORIES:
            raise ValueError("unsupported_category")
        for name in ("in_scope", "authorized", "real_video", "normal_action",
                     "should_refuse", "has_supported_opportunity", "technical_problem_asserted"):
            if not isinstance(row.get(name), bool):
                raise ValueError("invalid_" + name)
        if not isinstance(row.get("advice"), list) or len(row["advice"]) > 1:
            raise ValueError("zero_or_one_advice_required")
        for item in row["advice"]:
            if not isinstance(item, dict) or any(not isinstance(item.get(name), bool) for name in ADVICE_CHECKS):
                raise ValueError("incomplete_advice_review")
        observations = row.get("critical_observations")
        if not isinstance(observations, list) or any(not isinstance(value, bool) for value in observations):
            raise ValueError("invalid_observation_review")
        for name in ("primary_focus_acceptable", "user_understands"):
            if row.get(name) is not None and not isinstance(row.get(name), bool):
                raise ValueError("invalid_" + name)
        if not isinstance(row.get("prohibited_content_count"), int) or isinstance(row["prohibited_content_count"], bool) or row["prohibited_content_count"] < 0:
            raise ValueError("invalid_prohibited_count")
        for name in ("cost_cny", "latency_seconds"):
            value = row.get(name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0):
                raise ValueError("invalid_" + name)


def _summarize(rows):
    groups = _clusters(rows)
    has_advice = [bool(row["advice"]) for row in rows]
    correct = [all(row["advice"][0][name] for name in ADVICE_CHECKS) if row["advice"] else None for row in rows]
    values = {
        "advice_correct_and_applicable": correct,
        "advice_coverage": has_advice,
        "opportunity_coverage": [correct[i] is True if row["has_supported_opportunity"] else None for i, row in enumerate(rows)],
        "critical_observation_attempt_accuracy": [all(row["critical_observations"]) if row["critical_observations"] else None for row in rows],
        "primary_focus_acceptability": [row.get("primary_focus_acceptable") for row in rows],
        "normal_action_false_problem_rate": [row["technical_problem_asserted"] if row["normal_action"] else None for row in rows],
        "refusal_false_advice_rate": [has_advice[i] if row["should_refuse"] else None for i, row in enumerate(rows)],
        "user_understanding": [row.get("user_understands") for row in rows],
    }
    result = {"attempt_count": len(rows), "independent_groups": len(groups),
              "metrics": {key: _metric(rows, value, groups) for key, value in values.items()},
              "prohibited_content_count": sum(row["prohibited_content_count"] for row in rows)}
    # The report's fact-level numerator is separate from the stricter attempt
    # metric. Facts in the same attempt never become independent CI samples.
    fact_values, fact_groups = [], []
    for group in groups:
        indices = []
        for index in group:
            for value in rows[index]["critical_observations"]:
                indices.append(len(fact_values))
                fact_values.append(value)
        if indices:
            fact_groups.append(indices)
    result["metrics"]["critical_observation_accuracy"] = _metric([], fact_values, fact_groups)
    for field in ("cost_cny", "latency_seconds"):
        measured = sorted(row[field] for row in rows if row.get(field) is not None)
        result[field] = {"known_attempts": len(measured), "unknown_attempts": len(rows) - len(measured),
                         "total": sum(measured) if measured else None,
                         "median": median(measured) if measured else None,
                         "p95": measured[max(0, math.ceil(len(measured) * .95) - 1)] if measured else None}
    return result


def evaluate_attempts(rows: list[dict]) -> dict:
    """Every row is one complete attempt, including failure/no-advice/retries.

    Advice on excluded material remains visible as an out-of-scope violation.
    An empty advice list has no accuracy denominator, never a correct answer.
    """
    _validate_rows(rows)
    scoped = [row for row in rows if row["in_scope"]]
    categories = {category: _summarize([row for row in scoped if row["category"] == category]) for category in sorted(CATEGORIES)}
    strata = sorted({group for row in scoped for group in row.get("strata", []) if isinstance(group, str)})
    return {"schema_version": 1, "evidence_kind": "independent_real_video" if rows and all(row["real_video"] and row["authorized"] for row in rows) else "synthetic_or_unverified",
            "effect_improvement_established": False,
            "total_attempts": len(rows), "in_scope_attempts": len(scoped),
            "out_of_scope_advice_count": sum(bool(row["advice"]) for row in rows if not row["in_scope"]),
            "overall": _summarize(scoped), "categories": categories,
            "strata": {group: _summarize([row for row in scoped if group in row.get("strata", [])]) for group in strata}}


def pilot_gate(summary: dict, category: str) -> dict:
    """Proposed thresholds only; passing arithmetic does not approve a claim."""
    reasons = []
    if summary.get("evidence_kind") != "independent_real_video":
        reasons.append("real_authorized_evidence_missing")
    group = summary.get("categories", {}).get(category, {})
    if group.get("attempt_count", 0) < 60:
        reasons.append("fewer_than_60_attempts")
    metrics = group.get("metrics", {})
    for name, threshold in (("advice_correct_and_applicable", .95), ("critical_observation_accuracy", .95),
                            ("primary_focus_acceptability", .90), ("user_understanding", .90)):
        metric = metrics.get(name, {})
        if metric.get("estimate") is None or metric["estimate"] < threshold:
            reasons.append(name + "_not_met")
    interval = metrics.get("advice_correct_and_applicable", {}).get("interval_95")
    if interval is None or interval[0] < .90:
        reasons.append("advice_interval_lower_bound_not_met")
    for name in ("normal_action_false_problem_rate", "refusal_false_advice_rate"):
        if not metrics.get(name, {}).get("denominator"):
            reasons.append(name + "_not_sampled")
    if metrics.get("refusal_false_advice_rate", {}).get("numerator", 0):
        reasons.append("refusal_violation")
    if group.get("prohibited_content_count", 0) or summary.get("out_of_scope_advice_count", 0):
        reasons.append("prohibited_content")
    return {"passed": not reasons, "reason_codes": reasons}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Aggregate authorized, de-identified attempt reviews; never approve knowledge.")
    parser.add_argument("input", type=Path, help="JSON object with an attempts array")
    parser.add_argument("--output", type=Path, help="Optional local summary JSON path")
    arguments = parser.parse_args()
    try:
        document = json.loads(arguments.input.read_text(encoding="utf-8"))
        summary = evaluate_attempts(document.get("attempts"))
        output = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if arguments.output:
            arguments.output.write_text(output, encoding="utf-8")
        else:
            print(output)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, "Evaluation input or output is invalid; no approval was produced.\n")
