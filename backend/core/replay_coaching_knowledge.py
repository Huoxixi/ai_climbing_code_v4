"""Fail-closed claim permissions sourced exclusively from the local registry.

Unit review flags, a model's review identifiers, and retrieval scores confer no
permission. This module checks provenance structure; only human source review
and independent authorized video evaluation can establish semantic suitability.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from core.replay_coaching_evaluation import CATEGORIES, evaluate_attempts, pilot_gate


COMMON_CONDITIONS = frozenset({"camera_fixed", "slow_continuous", "limbs_and_next_target_visible",
                               "single_wall_clear_perspective", "existing_plan_unchanged"})
CATEGORY_CONDITIONS = {
    "existing_foot_sequence": {"foot_sequence_visible", "adjustment_confirmed"},
    "same_foothold_preparation": {"shoe_contact_process_visible", "contact_identity_reliable", "following_action_visible"},
    "existing_transition_preparation": {"before_pause_after_visible", "next_target_confirmed"},
}
SCOPE = {"population": "adults", "activity": "indoor_bouldering", "camera": "fixed", "movement": "slow_continuous"}
SELF_REPORT_FIELDS = frozenset({"goal", "fatigue", "discomfort", "movement_limitations", "activity", "adult_confirmed"})
VERSION_FIELDS = ("model", "prompt", "sampling", "knowledge", "ranking", "media_compression")
RUNTIME_VERSIONS = {"model": "qwen3-vl-plus", "prompt": "claim-review-2026-09-27",
                    "sampling": "local-sequence-v1", "ranking": "claim-goal-v1",
                    "media_compression": "jpeg-768-v1"}
APPROVED_SNAPSHOT_MODELS = frozenset({"qwen3-vl-plus-2025-09-23", "qwen3-vl-plus-2025-12-19"})


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def claim_digest(claim: dict) -> str:
    """Record IDs are excluded so review records need not hash themselves."""
    return _digest({key: value for key, value in claim.items() if key not in {"professional_review_id", "validation_record_id"}})


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


class ClaimRegistry:
    def __init__(self, root: Path, *, runtime_versions: dict | None = None):
        self.root = Path(root).resolve()
        self.claims = self._load("claims", "id")
        self.reviews = self._load("reviews", "id", kind="professional_review")
        self.validations = self._load("validations", "id", kind="video_validation")
        self.units = self._load("units", "id")
        self.evidence = {}
        duplicates = set()
        sources = _json(self.root / "sources.json").get("sources", [])
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            for evidence in source.get("evidence", []) if isinstance(source.get("evidence"), list) else []:
                if not isinstance(evidence, dict) or not _text(evidence.get("id")):
                    continue
                key = evidence["id"]
                if key in self.evidence:
                    duplicates.add(key)
                self.evidence[key] = {"source": source, "evidence": evidence}
        for key in duplicates:
            self.evidence.pop(key, None)
        self.content_fingerprint = _digest({"sources": sources, "units": self.units, "claims": self.claims})
        self.runtime_versions = {**RUNTIME_VERSIONS, **(runtime_versions or {}), "knowledge": self.content_fingerprint}
        hasher = hashlib.sha256()
        paths = [self.root / "sources.json"]
        for folder in ("claims", "reviews", "validations", "units"):
            paths.extend(sorted((self.root / folder).glob("**/*.json")))
        for path in paths:
            try:
                hasher.update(str(path.relative_to(self.root)).replace("\\", "/").encode("utf-8"))
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(b"unreadable")
        hasher.update(_digest(self.runtime_versions).encode("ascii"))
        self.fingerprint = hasher.hexdigest()

    def _load(self, directory, field, *, kind=None):
        result, duplicates = {}, set()
        for path in sorted((self.root / directory).glob("*.json")):
            item = _json(path)
            key = item.get(field)
            if not _text(key) or (kind and item.get("kind") != kind):
                continue
            if key in result:
                duplicates.add(key)
            result[key] = item
        for key in duplicates:
            result.pop(key, None)
        return result

    def _artifact(self, relative):
        if not _text(relative):
            return {}
        try:
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root / "validations") or path.suffix != ".json":
                return {}
            return _json(path)
        except (OSError, ValueError):
            return {}

    def evidence_digest(self, claim):
        return _digest([self.evidence.get(link.get("evidence_id")) for link in claim.get("evidence_links", []) if isinstance(link, dict)])

    def _record_matches(self, record, claim):
        return (bool(record) and record.get("claim_id") == claim["id"]
                and type(record.get("claim_version")) is int and record["claim_version"] == claim["version"]
                and record.get("claim_sha256") == claim_digest(claim)
                and record.get("revoked") is False and record.get("revoked_at") in (None, "")
                and record.get("scope") == claim.get("scope"))

    def eligibility(self, claim_or_id, *, risk=False):
        try:
            return self._eligibility(claim_or_id, risk=risk)
        except (TypeError, ValueError, KeyError, AttributeError):
            return {"allowed": False, "reason_codes": ["claim_contract_invalid"]}

    def _eligibility(self, claim_or_id, *, risk=False):
        claim_id = claim_or_id if isinstance(claim_or_id, str) else claim_or_id.get("id") if isinstance(claim_or_id, dict) else None
        claim = self.claims.get(claim_id)
        reasons = []
        if self.runtime_versions.get("model") not in APPROVED_SNAPSHOT_MODELS:
            reasons.append("model_snapshot_required")
        if risk:
            reasons.append("personalized_risk_disabled")
        if not claim or (isinstance(claim_or_id, dict) and claim_or_id != claim):
            return {"allowed": False, "reason_codes": reasons + ["claim_not_in_registry"]}
        if (claim.get("schema_version") != 1 or type(claim.get("version")) is not int or claim["version"] < 1
                or claim.get("kind") != "technical_adjustment" or claim.get("category") not in CATEGORIES
                or claim.get("scope") != SCOPE):
            reasons.append("claim_out_of_scope")
        if claim.get("status") != "active" or claim.get("automatic_use") is not True:
            reasons.append("claim_not_approved")
        for field in ("statement", "adjustment_template", "verification_template"):
            if not _text(claim.get(field)):
                reasons.append("claim_template_missing")
        conditions = claim.get("required_conditions")
        if not isinstance(conditions, list):
            conditions = []
        ids = [item.get("id") for item in conditions if isinstance(item, dict)]
        expected = COMMON_CONDITIONS | CATEGORY_CONDITIONS.get(claim.get("category"), set())
        if (not expected.issubset(set(ids)) or len(ids) != len(conditions) or len(set(ids)) != len(ids)
                or any(not _text(item.get("statement")) or item.get("source") not in {"visual_fact", "current_self_report"} for item in conditions)):
            reasons.append("required_conditions_invalid")
        if any(item.get("id") in expected and item.get("source") != "visual_fact" for item in conditions if isinstance(item, dict)):
            reasons.append("visual_condition_requires_visual_fact")
        exclusions = claim.get("exclusions")
        if (not isinstance(exclusions, list) or not exclusions or any(not isinstance(item, dict) or not _text(item.get("id")) or not _text(item.get("statement")) for item in exclusions)
                or not isinstance(claim.get("cannot_infer"), list) or not claim["cannot_infer"]):
            reasons.append("claim_boundaries_missing")
        unit = self.units.get(claim.get("unit_id"), {})
        source_claim = next((item for item in unit.get("claims", []) if isinstance(item, dict) and item.get("id") == claim.get("source_claim_id")), {})
        links = claim.get("evidence_links")
        if not source_claim or source_claim.get("basis") not in {"source_summary", "conditional_transfer"} or not isinstance(links, list) or not links:
            reasons.append("claim_source_missing")
            links = []
        for link in links:
            entry = self.evidence.get(link.get("evidence_id")) if isinstance(link, dict) else None
            if (not entry or entry["source"].get("id") != link.get("source_id")
                    or entry["source"].get("access_status") not in {"section_read", "full_text_read"}
                    or urlparse(str(entry["source"].get("url", ""))).scheme != "https"
                    or not _text(entry["evidence"].get("supports")) or not _text(entry["evidence"].get("limits"))
                    or not _text(link.get("locator")) or entry["evidence"].get("locator") != link["locator"]
                    or link["evidence_id"] not in source_claim.get("evidence_ids", [])):
                reasons.append("source_evidence_mismatch")
        review = self.reviews.get(claim.get("professional_review_id"), {})
        reviewers = review.get("reviewers") or []
        if (not self._record_matches(review, claim) or review.get("status") != "approved"
                or review.get("evidence_sha256") != self.evidence_digest(claim)
                or review.get("evidence_links") != links or review.get("evidence_matches_claim") is not True
                or review.get("adult_transfer_reviewed") is not True or not _text(review.get("reviewed_at"))
                or not any(isinstance(item, dict) and _text(item.get("reviewer_id")) and item.get("adult_bouldering_experience") is True for item in reviewers)):
            reasons.append("professional_review_missing_or_invalid")
        validation = self.validations.get(claim.get("validation_record_id"), {})
        if (not self._record_matches(validation, claim) or validation.get("status") != "passed"
                or validation.get("independent") is not True or not _text(validation.get("completed_at"))):
            reasons.append("independent_validation_missing_or_invalid")
        else:
            reasons.extend(self._validation_reasons(validation, claim))
        return {"allowed": not reasons, "reason_codes": list(dict.fromkeys(reasons))}

    def _validation_reasons(self, record, claim):
        protocol = self._artifact(record.get("protocol_file"))
        data = self._artifact(record.get("evaluation_file"))
        if (not protocol or not data or record.get("protocol_sha256") != _digest(protocol)
                or record.get("evaluation_sha256") != _digest(data)):
            return ["validation_artifact_missing_or_changed"]
        reviewers = data.get("reviewer_ids", [])
        versions = protocol.get("generation_versions", {})
        if (protocol.get("status") != "frozen" or not _text(protocol.get("frozen_at"))
                or protocol.get("dataset_id") != data.get("dataset_id")
                or protocol.get("claim_id") != claim["id"] or protocol.get("claim_version") != claim["version"]
                or protocol.get("category") != claim["category"]
                or not all(_text(versions.get(field)) for field in VERSION_FIELDS)
                or data.get("generation_versions") != versions
                or versions != self.runtime_versions
                or not isinstance(reviewers, list) or len(set(reviewers)) < 2 or not all(_text(item) for item in reviewers)
                or data.get("independent_blind_review") is not True or data.get("disagreements_resolved") is not True):
            return ["validation_protocol_invalid"]
        rows = data.get("attempts")
        if not isinstance(rows, list) or not rows:
            return ["validation_sample_missing"]
        development = protocol.get("development_groups")
        if not isinstance(development, dict) or any(not isinstance(development.get(key), list) for key in ("attempt_ids", "participant_groups", "route_groups")):
            return ["development_split_unrecorded"]
        for row in rows:
            if not isinstance(row, dict):
                return ["validation_sample_invalid"]
            if any(row.get(field) in development[key] for field, key in (("attempt_id", "attempt_ids"), ("participant_group", "participant_groups"), ("route_group", "route_groups"))):
                return ["development_holdout_leakage"]
        try:
            gate = pilot_gate(evaluate_attempts(rows), claim["category"])
        except (ValueError, TypeError, KeyError):
            return ["validation_sample_invalid"]
        return [] if gate["passed"] else ["validation_threshold_not_met", *gate["reason_codes"]]

    def approved_claims(self):
        return [copy.deepcopy(claim) for claim in self.claims.values() if self.eligibility(claim)["allowed"]]

    eligible_claims = approved_claims

    @staticmethod
    def _valid_fact(fact):
        if not isinstance(fact, dict) or not _text(fact.get("id")):
            return False
        review = fact.get("independent_review") or {}
        evidence = fact.get("evidence")
        if (not isinstance(review, dict) or review.get("status") != "verified" or review.get("visible") is not True
                or review.get("temporal_coverage") is not True or review.get("record_conflict") is not False
                or review.get("label_dependent") is not False or not isinstance(evidence, list) or not evidence):
            return False
        for item in evidence:
            value = item.get("time_seconds") if isinstance(item, dict) else None
            if (not isinstance(item, dict) or not _text(item.get("frame_id")) or isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                return False
        return True

    def validate_conditions(self, claim_or_id, condition_checks, facts, context):
        try:
            return self._validate_conditions(claim_or_id, condition_checks, facts, context)
        except (TypeError, ValueError, KeyError, AttributeError):
            return {"allowed": False, "reason_codes": ["condition_contract_invalid"], "conditions": []}

    def _validate_conditions(self, claim_or_id, condition_checks, facts, context):
        eligibility = self.eligibility(claim_or_id)
        if not eligibility["allowed"]:
            return {**eligibility, "conditions": []}
        claim = self.claims[claim_or_id if isinstance(claim_or_id, str) else claim_or_id["id"]]
        facts = list(facts.values()) if isinstance(facts, dict) else facts
        valid_facts, duplicate_facts = {}, set()
        for fact in facts if isinstance(facts, list) else []:
            if self._valid_fact(fact):
                if fact["id"] in valid_facts:
                    duplicate_facts.add(fact["id"])
                valid_facts[fact["id"]] = fact
        for key in duplicate_facts:
            valid_facts.pop(key, None)
        checks, duplicate_checks = {}, set()
        for check in condition_checks if isinstance(condition_checks, list) else []:
            if isinstance(check, dict) and _text(check.get("condition_id")):
                if check["condition_id"] in checks:
                    duplicate_checks.add(check["condition_id"])
                checks[check["condition_id"]] = check
        reasons, results = [], []
        requirements = [(item, "satisfied") for item in claim["required_conditions"]] + [(item, "not_satisfied") for item in claim["exclusions"]]
        for condition, desired in requirements:
            key = condition["id"]
            check = checks.get(key, {})
            state = check.get("state")
            verified = state == desired and key not in duplicate_checks
            cited = check.get("evidence") or []
            supported = False
            for reference in cited if isinstance(cited, list) else []:
                if not isinstance(reference, dict):
                    continue
                if reference.get("kind") == "visual_fact" and condition.get("source", "visual_fact") == "visual_fact":
                    fact = valid_facts.get(reference.get("fact_id"))
                    if fact:
                        reviewed = fact["independent_review"].get("condition_checks") or []
                        matches = [item for item in reviewed if isinstance(item, dict) and item.get("condition_id") == key]
                        frame_ids = reference.get("frame_ids")
                        available = {item["frame_id"] for item in fact["evidence"]}
                        if (not isinstance(frame_ids, list) or not frame_ids or not all(_text(item) for item in frame_ids)
                                or len(set(frame_ids)) != len(frame_ids) or not set(frame_ids).issubset(available)):
                            continue
                        reviewer_refs = matches[0].get("evidence", []) if len(matches) == 1 else []
                        anchored = any(isinstance(item, dict) and item.get("kind") == "visual_fact"
                            and item.get("fact_id") == fact["id"] and isinstance(item.get("frame_ids"), list)
                            and all(_text(frame) for frame in item["frame_ids"])
                            and set(frame_ids).issubset(set(item["frame_ids"]))
                            and set(item["frame_ids"]).issubset(available) for item in reviewer_refs)
                        supported = supported or (len(matches) == 1 and matches[0].get("state") == desired and anchored)
                elif reference.get("kind") == "current_self_report" and condition.get("source") == "current_self_report":
                    field = condition.get("self_report_field")
                    # A statement is only evidence of its own reported value.
                    # It cannot establish a visible contact or physical ability.
                    supported = supported or (field in SELF_REPORT_FIELDS and field == reference.get("field")
                        and isinstance(context, dict) and field in context and "expected_value" in condition
                        and context[field] == condition["expected_value"] and context[field] not in (None, ""))
            verified = verified and supported
            if not verified:
                reasons.append("condition_unknown" if state in (None, "unknown") else "condition_not_met" if state != desired else "condition_evidence_invalid")
            results.append({"condition_id": key, "state": state if state in {"satisfied", "not_satisfied", "unknown"} else "unknown", "verified": verified})
        return {"allowed": not reasons, "reason_codes": list(dict.fromkeys(reasons)), "conditions": results}


# Descriptive alias used by policy/status callers.
KnowledgeClaims = ClaimRegistry
