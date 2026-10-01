"""Constructed contracts only; no professional approval or real video evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.replay_coaching_knowledge import (
    CATEGORY_CONDITIONS, COMMON_CONDITIONS, SCOPE, VERSION_FIELDS,
    ClaimRegistry, RUNTIME_VERSIONS, _digest, claim_digest,
)
from core.replay_coaching_evaluation import ADVICE_CHECKS, evaluate_attempts, pilot_gate, wilson_interval


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def attempt(index, *, advice=True):
    # These booleans exercise the gate; the fixture is never production evidence.
    return {"attempt_id": f"attempt-{index}", "participant_group": f"participant-{index}",
            "route_group": f"route-{index}", "category": "existing_foot_sequence",
            "in_scope": True, "authorized": True, "real_video": True,
            "normal_action": not advice, "should_refuse": not advice,
            "has_supported_opportunity": advice, "technical_problem_asserted": advice,
            "advice": [{name: True for name in ADVICE_CHECKS}] if advice else [],
            "critical_observations": [True], "primary_focus_acceptable": True,
            "user_understands": True, "prohibited_content_count": 0,
            "cost_cny": .10, "latency_seconds": 15, "strata": ["clear" if advice else "occluded"]}


def write_approved_fixture(root, *, extra_conditions=None):
    source = {"id": "SRC-TEST", "url": "https://example.test/source", "access_status": "section_read",
              "evidence": [{"id": "E-TEST", "locator": "Fixture paragraph 1", "supports": "Fixture statement", "limits": "Not actual evidence"}]}
    unit = {"id": "KB-TEST", "version": 1, "claims": [{"id": "C1", "basis": "conditional_transfer", "evidence_ids": ["E-TEST"]}],
            "review": {"automatic_use": True, "professional": "approved", "video_validation": "passed"}}
    write_json(root / "sources.json", {"sources": [source]})
    write_json(root / "units" / "KB-TEST.json", unit)
    required = COMMON_CONDITIONS | CATEGORY_CONDITIONS["existing_foot_sequence"]
    claim = {"schema_version": 1, "id": "CLAIM-TEST", "version": 1, "unit_id": "KB-TEST", "source_claim_id": "C1",
             "kind": "technical_adjustment", "category": "existing_foot_sequence", "status": "active", "automatic_use": True,
             "scope": SCOPE, "statement": "Constructed claim", "evidence_links": [{"source_id": "SRC-TEST", "evidence_id": "E-TEST", "locator": "Fixture paragraph 1"}],
             "required_conditions": [{"id": name, "statement": name, "source": "visual_fact"} for name in sorted(required)] + (extra_conditions or []),
             "exclusions": [{"id": "key_occlusion", "statement": "关键部位被遮挡"}],
             "adjustment_template": "保留已有方案，先确认下一步脚序。", "verification_template": "核对下次是否仍有相同调整。",
             "cannot_infer": ["Not a diagnosis"], "professional_review_id": "REVIEW-TEST", "validation_record_id": "VALIDATION-TEST"}
    write_json(root / "claims" / "CLAIM-TEST.json", claim)
    versions = ClaimRegistry(root, runtime_versions={"model": "qwen3-vl-plus-2025-12-19"}).runtime_versions
    protocol = {"status": "frozen", "frozen_at": "2026-01-01", "dataset_id": "fixture-only",
                "claim_id": claim["id"], "claim_version": 1, "category": claim["category"], "generation_versions": versions,
                "development_groups": {"attempt_ids": [], "participant_groups": [], "route_groups": []}}
    data = {"dataset_id": "fixture-only", "generation_versions": versions, "reviewer_ids": ["synthetic-a", "synthetic-b"],
            "independent_blind_review": True, "disagreements_resolved": True,
            "attempts": [attempt(i, advice=i < 60) for i in range(80)]}
    write_json(root / "validations" / "artifacts" / "protocol.json", protocol)
    write_json(root / "validations" / "artifacts" / "evaluation.json", data)
    match = {"claim_id": claim["id"], "claim_version": 1, "claim_sha256": claim_digest(claim), "scope": SCOPE, "revoked": False}
    review = {**match, "id": "REVIEW-TEST", "kind": "professional_review", "status": "approved", "reviewed_at": "2026-01-02",
              "evidence_links": claim["evidence_links"], "evidence_sha256": ClaimRegistry(root).evidence_digest(claim),
              "evidence_matches_claim": True, "adult_transfer_reviewed": True,
              "reviewers": [{"reviewer_id": "synthetic-reviewer", "adult_bouldering_experience": True}]}
    validation = {**match, "id": "VALIDATION-TEST", "kind": "video_validation", "status": "passed", "completed_at": "2026-01-03", "independent": True,
                  "protocol_file": "validations/artifacts/protocol.json", "evaluation_file": "validations/artifacts/evaluation.json",
                  "protocol_sha256": _digest(protocol), "evaluation_sha256": _digest(data)}
    write_json(root / "reviews" / "REVIEW-TEST.json", review)
    write_json(root / "validations" / "VALIDATION-TEST.json", validation)
    return claim, review, validation, protocol, data


def facts_and_checks(claim):
    checks = [{"condition_id": item["id"], "state": "satisfied", "evidence": [{"kind": "visual_fact", "fact_id": "observation-1", "frame_ids": ["frame-1", "frame-2"]}]} for item in claim["required_conditions"]]
    checks += [{"condition_id": item["id"], "state": "not_satisfied", "evidence": [{"kind": "visual_fact", "fact_id": "observation-1", "frame_ids": ["frame-1", "frame-2"]}]} for item in claim["exclusions"]]
    fact = {"id": "observation-1", "evidence": [{"frame_id": "frame-1", "time_seconds": 1.0}, {"frame_id": "frame-2", "time_seconds": 2.0}],
            "independent_review": {"status": "verified", "visible": True, "temporal_coverage": True,
                                   "record_conflict": False, "label_dependent": False, "condition_checks": copy.deepcopy(checks)}}
    return [fact], checks


class ClaimRegistryTests(unittest.TestCase):
    def setUp(self):
        self.runtime_patch = patch.dict(RUNTIME_VERSIONS, model="qwen3-vl-plus-2025-12-19")
        self.runtime_patch.start()
        self.temp = tempfile.TemporaryDirectory(prefix="coaching-claim-contract-")
        self.root = Path(self.temp.name)
        self.claim, self.review, self.validation, self.protocol, self.data = write_approved_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()
        self.runtime_patch.stop()

    def test_constructed_complete_contract_is_eligible_and_conditions_still_required(self):
        library = ClaimRegistry(self.root)
        self.assertEqual(len(library.approved_claims()), 1)
        self.assertFalse(library.validate_conditions(self.claim, [], [], {})["allowed"])
        facts, checks = facts_and_checks(self.claim)
        self.assertTrue(library.validate_conditions(self.claim, checks, facts, {})["allowed"])

    def test_live_library_is_entirely_closed(self):
        registry = ClaimRegistry(Path(__file__).resolve().parents[1] / "docs" / "bouldering-knowledge")
        self.assertEqual(registry.approved_claims(), [])

    def test_review_flags_on_unit_never_authorize_missing_claim(self):
        self.assertFalse(ClaimRegistry(self.root).eligibility("KB-TEST")["allowed"])

    def test_missing_retracted_wrong_version_and_changed_claim_review_rejected(self):
        for field, value in (("claim_id", "OTHER"), ("claim_version", 2), ("revoked", True), ("revoked_at", "2026-01-04"),
                             ("claim_sha256", "wrong"), ("reviewers", []), ("evidence_sha256", "wrong")):
            with self.subTest(field=field):
                review = {**self.review, field: value}
                write_json(self.root / "reviews" / "REVIEW-TEST.json", review)
                self.assertFalse(ClaimRegistry(self.root).eligibility(self.claim)["allowed"])
        (self.root / "reviews" / "REVIEW-TEST.json").unlink()
        self.assertFalse(ClaimRegistry(self.root).eligibility(self.claim)["allowed"])

    def test_model_cannot_replace_registered_claim_or_review_reference(self):
        forged = {**self.claim, "professional_review_id": "invented", "adjustment_template": "invented"}
        self.assertFalse(ClaimRegistry(self.root).eligibility(forged)["allowed"])

    def test_risk_never_authorized_even_with_complete_record(self):
        self.assertFalse(ClaimRegistry(self.root).eligibility(self.claim, risk=True)["allowed"])

    def test_wrong_source_changed_locator_and_product_rule_rejected(self):
        for change in ({"source_id": "WRONG"}, {"evidence_id": "OTHER"}, {"locator": "Different section"}):
            claim = copy.deepcopy(self.claim)
            claim["evidence_links"][0].update(change)
            write_json(self.root / "claims" / "CLAIM-TEST.json", claim)
            self.assertIn("source_evidence_mismatch", ClaimRegistry(self.root).eligibility(claim)["reason_codes"])

    def test_duplicate_claim_and_review_identifiers_fail_closed(self):
        write_json(self.root / "reviews" / "copy.json", self.review)
        self.assertFalse(ClaimRegistry(self.root).eligibility(self.claim)["allowed"])
        write_json(self.root / "claims" / "copy.json", self.claim)
        self.assertEqual(ClaimRegistry(self.root).claims, {})

    def test_unknown_nonempty_and_self_report_do_not_establish_visual_condition(self):
        registry = ClaimRegistry(self.root)
        for change in ({"state": "unknown"}, {"state": "not_satisfied"}, {"evidence": []},
                       {"evidence": [{"kind": "visual_fact", "fact_id": "invented"}]},
                       {"evidence": [{"kind": "current_self_report", "field": "goal"}]}):
            facts, checks = facts_and_checks(self.claim)
            checks[0].update(change)
            self.assertFalse(registry.validate_conditions(self.claim, checks, facts, {"goal": "脚序"})["allowed"])

    def test_reviewer_must_independently_check_the_same_condition(self):
        facts, checks = facts_and_checks(self.claim)
        facts[0]["independent_review"]["condition_checks"] = []
        self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks, facts, {})["allowed"])

    def test_current_self_report_is_limited_to_exact_declared_field_value(self):
        claim, *_ = write_approved_fixture(self.root, extra_conditions=[{
            "id": "reported_goal", "statement": "本次本人选择核对脚序", "source": "current_self_report",
            "self_report_field": "goal", "expected_value": "核对脚序"}])
        facts, checks = facts_and_checks(claim)
        report_check = next(item for item in checks if item["condition_id"] == "reported_goal")
        report_check["evidence"] = [{"kind": "current_self_report", "field": "goal"}]
        registry = ClaimRegistry(self.root)
        self.assertTrue(registry.validate_conditions(claim, checks, facts, {"goal": "核对脚序"})["allowed"])
        for context in ({}, {"goal": "核对出手"}):
            self.assertFalse(registry.validate_conditions(claim, checks, facts, context)["allowed"])
        report_check["evidence"][0]["field"] = "height_cm"
        self.assertFalse(registry.validate_conditions(claim, checks, facts, {"goal": "核对脚序", "height_cm": 180})["allowed"])

    def test_condition_evidence_requires_matching_actual_reviewed_frame_anchors(self):
        for frame_ids in ([], ["nonexistent"], ["frame-1", "frame-1"]):
            facts, checks = facts_and_checks(self.claim)
            checks[0]["evidence"][0]["frame_ids"] = frame_ids
            self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks, facts, {})["allowed"])
        facts, checks = facts_and_checks(self.claim)
        facts[0]["independent_review"]["condition_checks"][0]["evidence"][0]["frame_ids"] = ["frame-2"]
        self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks, facts, {})["allowed"])

    def test_unverified_occluded_conflicting_and_label_dependent_fact_rejected(self):
        for field, value in (("status", "pending"), ("visible", False), ("temporal_coverage", False),
                             ("record_conflict", True), ("label_dependent", True)):
            facts, checks = facts_and_checks(self.claim)
            facts[0]["independent_review"][field] = value
            self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks, facts, {})["allowed"])

    def test_missing_or_unknown_exclusion_is_rejected(self):
        facts, checks = facts_and_checks(self.claim)
        self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks[:-1], facts, {})["allowed"])

    def test_invalid_fact_evidence_and_duplicate_checks_rejected(self):
        facts, checks = facts_and_checks(self.claim)
        facts[0]["evidence"][0]["time_seconds"] = float("nan")
        self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks, facts, {})["allowed"])
        facts, checks = facts_and_checks(self.claim)
        self.assertFalse(ClaimRegistry(self.root).validate_conditions(self.claim, checks + [checks[0]], facts, {})["allowed"])

    def test_holdout_files_cannot_be_missing_changed_or_escape_directory(self):
        for value in ("../outside.json", "validations/missing.json", "sources.json"):
            write_json(self.root / "validations" / "VALIDATION-TEST.json", {**self.validation, "evaluation_file": value})
            self.assertFalse(ClaimRegistry(self.root).eligibility(self.claim)["allowed"])

    def test_development_user_and_route_leakage_rejected(self):
        for key, value in (("attempt_ids", "attempt-0"), ("participant_groups", "participant-0"), ("route_groups", "route-0")):
            protocol = copy.deepcopy(self.protocol)
            protocol["development_groups"][key].append(value)
            write_json(self.root / "validations" / "artifacts" / "protocol.json", protocol)
            write_json(self.root / "validations" / "VALIDATION-TEST.json", {**self.validation, "protocol_sha256": _digest(protocol)})
            self.assertIn("development_holdout_leakage", ClaimRegistry(self.root).eligibility(self.claim)["reason_codes"])

    def test_validation_metadata_never_substitutes_for_zero_advice_denominator(self):
        data = {**self.data, "attempts": [attempt(i, advice=False) for i in range(80)]}
        write_json(self.root / "validations" / "artifacts" / "evaluation.json", data)
        write_json(self.root / "validations" / "VALIDATION-TEST.json", {**self.validation, "evaluation_sha256": _digest(data)})
        self.assertIn("validation_threshold_not_met", ClaimRegistry(self.root).eligibility(self.claim)["reason_codes"])

    def test_malformed_claim_fails_closed_without_crashing(self):
        claim = {**self.claim, "category": []}
        write_json(self.root / "claims" / "CLAIM-TEST.json", claim)
        self.assertFalse(ClaimRegistry(self.root).eligibility(claim)["allowed"])

    def test_fingerprint_changes_with_revocation_or_evidence(self):
        before = ClaimRegistry(self.root).fingerprint
        write_json(self.root / "reviews" / "REVIEW-TEST.json", {**self.review, "revoked": True})
        self.assertNotEqual(before, ClaimRegistry(self.root).fingerprint)

    def test_changed_runtime_model_prompt_sampling_and_ranking_invalidate_old_evaluation(self):
        for field in ("model", "prompt", "sampling", "ranking", "media_compression"):
            registry = ClaimRegistry(self.root, runtime_versions={field: "changed-v2"})
            self.assertIn("validation_protocol_invalid", registry.eligibility(self.claim)["reason_codes"])

    def test_alias_model_never_uses_snapshot_validation(self):
        self.assertIn("model_snapshot_required", ClaimRegistry(self.root, runtime_versions={"model": "qwen3-vl-plus"}).eligibility(self.claim)["reason_codes"])


class EvaluationTests(unittest.TestCase):
    def test_zero_advice_is_not_correct_and_denominators_are_explicit(self):
        summary = evaluate_attempts([attempt(i, advice=False) for i in range(80)])
        metric = summary["overall"]["metrics"]["advice_correct_and_applicable"]
        self.assertEqual(metric["denominator"], 0)
        self.assertIsNone(metric["estimate"])
        self.assertIsNone(metric["interval_95"])
        self.assertFalse(pilot_gate(summary, "existing_foot_sequence")["passed"])

    def test_all_five_advice_reviews_must_pass(self):
        rows = [attempt(0), attempt(1, advice=False)]
        rows[0]["advice"][0]["conditions_met"] = False
        summary = evaluate_attempts(rows)
        self.assertEqual(summary["overall"]["metrics"]["advice_correct_and_applicable"]["estimate"], 0)
        self.assertEqual(summary["overall"]["metrics"]["advice_coverage"]["estimate"], .5)
        self.assertEqual(summary["overall"]["metrics"]["opportunity_coverage"]["estimate"], 0)

    def test_duplicate_attempts_and_partial_reviews_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate_attempt"):
            evaluate_attempts([attempt(0), attempt(0)])
        row = attempt(0)
        row["advice"][0].pop("conditions_met")
        with self.assertRaisesRegex(ValueError, "incomplete_advice_review"):
            evaluate_attempts([row])

    def test_same_route_does_not_create_independent_attempt_uncertainty(self):
        rows = [attempt(i) for i in range(60)]
        for row in rows:
            row["route_group"] = "same-route"
        summary = evaluate_attempts(rows)
        metric = summary["overall"]["metrics"]["advice_correct_and_applicable"]
        self.assertEqual(metric["independent_groups"], 1)
        self.assertIsNone(metric["interval_95"])
        self.assertFalse(pilot_gate(summary, "existing_foot_sequence")["passed"])

    def test_wilson_all_correct_still_has_uncertainty(self):
        self.assertLess(wilson_interval(60, 60)[0], 1)
        self.assertGreater(wilson_interval(60, 60)[0], .90)
        self.assertIsNone(wilson_interval(0, 0))

    def test_fact_accuracy_is_distinct_from_stricter_attempt_accuracy(self):
        row = attempt(0)
        row["critical_observations"] = [True, False]
        metrics = evaluate_attempts([row])["overall"]["metrics"]
        self.assertEqual(metrics["critical_observation_accuracy"]["estimate"], .5)
        self.assertEqual(metrics["critical_observation_accuracy"]["denominator"], 2)
        self.assertEqual(metrics["critical_observation_attempt_accuracy"]["estimate"], 0)
        self.assertEqual(metrics["critical_observation_attempt_accuracy"]["denominator"], 1)

    def test_synthetic_and_unconsented_material_cannot_pass_real_effect_gate(self):
        for field in ("real_video", "authorized"):
            rows = [attempt(i, advice=i < 60) for i in range(80)]
            rows[0][field] = False
            summary = evaluate_attempts(rows)
            self.assertFalse(pilot_gate(summary, "existing_foot_sequence")["passed"])
            self.assertFalse(summary["effect_improvement_established"])

    def test_refusal_errors_and_out_of_scope_advice_remain_visible(self):
        rows = [attempt(i, advice=i < 60) for i in range(80)]
        rows[0]["should_refuse"] = True
        self.assertIn("refusal_violation", pilot_gate(evaluate_attempts(rows), "existing_foot_sequence")["reason_codes"])
        rows[0]["in_scope"] = False
        self.assertEqual(evaluate_attempts(rows)["out_of_scope_advice_count"], 1)

    def test_missing_cost_is_unknown_and_failed_attempts_are_counted(self):
        rows = [attempt(0), attempt(1, advice=False)]
        rows[1]["cost_cny"] = None
        rows[1]["latency_seconds"] = 25
        summary = evaluate_attempts(rows)
        self.assertEqual(summary["total_attempts"], 2)
        self.assertEqual(summary["overall"]["cost_cny"]["unknown_attempts"], 1)
        self.assertEqual(summary["overall"]["cost_cny"]["total"], .1)
        self.assertEqual(summary["overall"]["latency_seconds"]["median"], 20)


if __name__ == "__main__":
    unittest.main()
