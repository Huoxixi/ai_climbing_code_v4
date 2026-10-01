"""Synthetic media and mocked cloud responses; these test gates, not coaching accuracy."""
import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import httpx
import numpy as np

from core.replay_coaching_engine import (
    CoachingCancelled, CoachingEngine, CoachingEngineError, DashScopeProvider,
    KnowledgeLibrary, MAX_EDGE, MAX_FRAMES, MAX_OUTPUT_TOKENS, _base_url, _sample_frames,
)


def write_video(path: Path, *, count=50, width=160, height=120):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Synthetic fixture codec unavailable")
    try:
        for index in range(count):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            cv2.circle(frame, (10 + index % (width - 20), height // 2), 6, (0, 255, 0), -1)
            writer.write(frame)
    finally:
        writer.release()


def write_library(root: Path, *, approved=False, medical=False):
    (root / "units").mkdir(parents=True)
    (root / "sources.json").write_text(json.dumps({"sources": [{
        "id": "SRC-TEST", "title": "Fixture", "url": "https://example.test/coaching",
        "evidence": [{"id": "E-TEST"}],
    }]}), encoding="utf-8")
    review = {"automatic_use": approved, "professional": "approved" if approved else "pending",
              "video_validation": "passed" if approved else "not_started"}
    if approved:
        review.update(professional_record="fixture-coach-review", video_validation_record="fixture-holdout-review")
    if medical:
        review.update(medical="approved", medical_record="fixture-medical-review")
    unit = {"id": "KB-FOOT-TEST", "title": "脚点调整", "version": 3,
            "aliases": ["脚点", "落脚"], "context": {"applies_if": ["脚部接触可見"]},
            "claims": [{"id": "C1", "basis": "source_summary", "statement": "教学资料将脚点位置与下一步联系起来。",
                        "evidence_ids": ["E-TEST"]}], "review": review,
            "next_step": {"kind": "review_only", "text": "核对脚点和下一步"}}
    (root / "units" / "KB-FOOT-TEST.json").write_text(json.dumps(unit, ensure_ascii=False), encoding="utf-8")
    return unit


class FakeProvider:
    """New stages deliberately require a second image-bearing request."""
    def __init__(self, *, mutate_observe=None, mutate_verify=None, mutate_compose=None,
                 usage=None, response_model="qwen3-vl-plus-2025-12-19"):
        self.calls = []
        self.mutate_observe, self.mutate_verify, self.mutate_compose = mutate_observe, mutate_verify, mutate_compose
        self.usage = usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
        self.response_model = response_model

    def __call__(self, *, stage, messages, model, cancelled):
        self.calls.append({"stage": stage, "messages": messages, "model": model})
        payload = json.loads(messages[1]["content"][0]["text"])
        anchors = [json.loads(item["text"]) for item in messages[1]["content"][1:] if item["type"] == "text"]
        if stage == "observe":
            first, last = anchors[0], anchors[2]
            result = {"observations": [{"title": "左脚位置变化", "observation": "前后画面中左脚的位置不同。",
                       "fact_kind": "position_change", "limb": "left_foot", "visible": True,
                       "start_seconds": first["time_seconds"], "end_seconds": last["time_seconds"],
                       "evidence": [first, last], "retrieval_terms": ["脚点", "落脚"]}]}
            if self.mutate_observe:
                self.mutate_observe(result)
        elif stage == "verify":
            reviews = []
            for candidate in payload["candidates"]:
                allowed = payload["sampling"][candidate["id"]]["frame_ids"]
                evidence = [anchor for anchor in anchors if anchor["frame_id"] in allowed]
                checks = [{"condition_id": "feet_visible", "state": "satisfied",
                           "evidence": [{"kind": "visual_fact", "fact_id": candidate["id"],
                                         "frame_ids": [item["frame_id"] for item in evidence]}]}]
                reviews.append({"observation_id": candidate["id"], "factual_support": "supported",
                                "visible": True, "temporal_coverage": True, "event_fully_visible": True,
                                "normal_explanation": "ruled_out", "record_conflict": False,
                                "label_dependent": False, "evidence": evidence, "condition_checks": checks,
                                "review_worthy": True, "review_reason": "前后位置不同，落点关系值得核对。",
                                "review_question": "左脚位置变化前后的落点是否相同？"})
            result = {"reviews": reviews}
            if self.mutate_verify:
                self.mutate_verify(result)
        else:
            result = {"selected": {"candidate_id": "0", "goal_related": True, "priority_distinguishable": True,
                                   "reason": "这个变化与本次核对脚部衔接的目标对应。"},
                      # Unrequested fluent prescriptions must never escape.
                      "improvements": [{"adjustment": "改成勾脚并加快跳跃。"}],
                      "risk_reminders": [{"precaution": "模型伪造的个人风险判断"}]}
            if self.mutate_compose:
                self.mutate_compose(result)
        return {"content": result, "model": self.response_model, "usage": dict(self.usage)}


class FixtureRegistry:
    """Isolate engine gates; real review/approval records have separate tests."""
    template = {"id": "CLAIM-TEST-1", "version": 1, "unit_id": "KB-FOOT-TEST",
                "category": "existing_foot_sequence", "statement": "已有脚序的预先确认",
                "required_conditions": [{"id": "feet_visible", "source": "visual_fact", "statement": "脚部可见"}],
                "exclusions": [], "adjustment_template": "保留原动作方案，先确认下一步已有脚序。",
                "verification_template": "核对同一片段中是否仍出现相同调整。"}
    def __init__(self, root, **kwargs):
        self.claim = copy.deepcopy(self.template)
    def approved_claims(self):
        return [self.claim]
    def validate_conditions(self, claim, checks, facts, context):
        allowed = bool(checks) and checks[0].get("state") == "satisfied"
        return {"allowed": allowed, "conditions": [{"condition_id": "feet_visible", "state": "satisfied", "verified": True}]
                if allowed else [], "reason_codes": [] if allowed else ["condition_unknown"]}


class CoachingEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="replay-coaching-test-")
        self.root = Path(self.temp.name)
        self.media = self.root / "synthetic.avi"
        write_video(self.media)
        self.knowledge = self.root / "knowledge"
        write_library(self.knowledge)
        self.job = {"owner": "private-owner", "original_name": "private-name.mp4", "input_path": "private-local-path",
                    "reviewed_segments": [{"id": "foot-1", "start_time_seconds": .8, "end_time_seconds": 1.6,
                                           "source": "human_review", "private_metadata": "must-not-upload"}],
                    "result": {"attempt": {"action_steps": [{"step": 1, "limb": "left_foot", "stable_time_seconds": 1.0}]},
                               "pose_samples": [{"joint_angles": {"knee": 99}}]}}
    def tearDown(self):
        self.temp.cleanup()
    def generate(self, provider=None, **kwargs):
        engine = CoachingEngine(provider=provider or FakeProvider(), knowledge_root=self.knowledge)
        return engine.generate(self.job, self.media, kwargs.get("media_kind", "overlay_video"),
                               kwargs.get("personal", {}), kwargs.get("context", {}),
                               kwargs.get("cancelled", lambda: False), kwargs.get("usage_callback"))
    def approved(self, provider=None, **kwargs):
        with patch("core.replay_coaching_knowledge.ClaimRegistry", FixtureRegistry), patch.dict(
                "os.environ", {"REPLAY_COACHING_MODEL": "qwen3-vl-plus-2025-12-19"}):
            return self.generate(provider, context=kwargs.pop("context", {"goal": "核对脚部衔接"}), **kwargs)

    def test_pending_library_stops_after_independent_review_without_compose(self):
        provider = FakeProvider()
        report = self.generate(provider, personal={"height_cm": 169})
        self.assertEqual(len(report["observations"]), 1)
        self.assertEqual(report["improvements"], [])
        self.assertEqual(report["risk_reminders"], [])
        self.assertEqual(report["result_status"], "review")
        self.assertEqual(report["next_attempt"]["kind"], "review")
        self.assertEqual(report["knowledge_status"]["eligible_advice_claims"], 0)
        observation = report["observations"][0]
        self.assertEqual(observation["personal_factors"], [])
        self.assertNotIn("教学资料", observation["possible_explanation"])
        self.assertEqual(observation["knowledge_refs"], [])
        self.assertEqual(report["provenance"]["usage"]["total_tokens"], 24)
        self.assertEqual([call["stage"] for call in provider.calls], ["observe", "verify"])
        self.assertIn("no_approved_knowledge", report["reason_codes"])
        self.assertTrue(any("插值" in text for text in report["limitations"]))

    def test_personal_background_goals_and_causes_do_not_reach_visual_stages(self):
        provider = FakeProvider()
        report = self.generate(provider, personal={"height_cm": 168, "weight_kg": 50, "secret": "private-personal"},
            context={"goal": "GOAL_SECRET", "fatigue": "FATIGUE_SECRET", "discomfort": "DISCOMFORT_SECRET",
                     "movement_limitations": "LIMIT_SECRET", "private": "private-context"})
        prompt = json.dumps(provider.calls, ensure_ascii=False)
        for forbidden in ("private-owner", "private-name", "private-local-path", "must-not-upload", "joint_angles",
                          "private-personal", "private-context", "GOAL_SECRET", "FATIGUE_SECRET",
                          "DISCOMFORT_SECRET", "LIMIT_SECRET", "weight_kg", "height_cm"):
            self.assertNotIn(forbidden, prompt)
        first = json.loads(provider.calls[0]["messages"][1]["content"][0]["text"])
        self.assertNotIn("existing_evidence", first)
        self.assertNotIn("personal", first)
        self.assertNotIn("context", first)
        self.assertTrue(all(any(item["type"] == "image_url" for item in call["messages"][1]["content"])
                            for call in provider.calls))
        self.assertEqual({item["field"] for item in report["personal_information_used"]},
                         {"discomfort", "movement_limitations"})

    def test_goal_cannot_induce_a_different_observation(self):
        first = self.generate(context={"goal": "脚法一定差"})
        second = self.generate(context={"goal": "力量一定不足"})
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(first["personal_information_used"], [])

    def test_anchors_and_decodable_ordered_images_are_actual(self):
        frames, duration, _ = _sample_frames(self.media, self.job, {}, lambda: False)
        times = [frame["time_seconds"] for frame in frames]
        self.assertEqual(times, sorted(set(times)))
        self.assertEqual(times[0], 0)
        self.assertAlmostEqual(times[-1], duration)
        self.assertLessEqual(len(frames), MAX_FRAMES)
        self.assertIn(.8, times)
        self.assertIn(1.6, times)
        for frame in frames:
            data = base64.b64decode(frame["data_url"].split(",", 1)[1])
            decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertIsNotNone(decoded)
            self.assertLessEqual(max(decoded.shape[:2]), MAX_EDGE)
            self.assertEqual(frame["frame_id"], f'frame-{round(frame["time_seconds"] * 10)}')
        self.assertEqual(list(self.root.glob("*.jpg")), [])

    def test_frame_budget_preserves_focus_and_complete_span(self):
        long_media = self.root / "long.avi"
        write_video(long_media, count=150, width=800, height=24)
        frames, duration, _ = _sample_frames(long_media, {}, {"focus_start_seconds": 13, "focus_end_seconds": 14},
                                             lambda: False, max_frames=24)
        self.assertLessEqual(len(frames), 24)
        self.assertAlmostEqual(frames[-1]["time_seconds"], duration)
        self.assertIn(13, [frame["time_seconds"] for frame in frames])
        self.assertIn(14, [frame["time_seconds"] for frame in frames])
        report = self.generate()
        self.assertLessEqual(report["coverage"]["frames_reviewed"], MAX_FRAMES)

    def test_bad_structured_facts_and_illegal_anchors_stop_without_second_call(self):
        mutations = [
            lambda row: row["evidence"][0].update(frame_id="invented"),
            lambda row: row["evidence"][0].update(time_seconds=1.111),
            lambda row: row.update(start_seconds=.111), lambda row: row.update(end_seconds=10000),
            lambda row: row.update(evidence=row["evidence"][:1]), lambda row: row.pop("fact_kind"),
            lambda row: row.update(fact_kind={"bad": True}), lambda row: row.update(limb=None),
            lambda row: row.update(visible="true"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                provider = FakeProvider(mutate_observe=lambda result: mutation(result["observations"][0]))
                report = self.generate(provider)
                self.assertEqual(report["observations"], [])
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(report["result_status"], "insufficient")
                self.assertIsNone(report["next_attempt"])

    def test_safe_legal_timestamps_do_not_make_a_nonexistent_fact_true(self):
        provider = FakeProvider(mutate_verify=lambda result: result["reviews"][0].update(factual_support="contradicted"))
        report = self.generate(provider)
        self.assertEqual(report["observations"], [])
        self.assertIn("independent_review_failed", report["reason_codes"])
        self.assertEqual(len(provider.calls), 2)

    def test_fluent_summary_without_evidence_returns_insufficient_without_repair_call(self):
        def summary(result):
            result.clear()
            result["summary"] = "整段动作很流畅，继续练习即可。"
        provider = FakeProvider(mutate_observe=summary)
        report = self.generate(provider)
        self.assertEqual(report["result_status"], "insufficient")
        self.assertEqual(report["observations"], [])
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("invalid_fact_structure", report["reason_codes"])

    def test_unknown_or_missing_review_flags_fail_closed(self):
        for field in ("visible", "temporal_coverage", "record_conflict", "label_dependent", "factual_support"):
            with self.subTest(field=field):
                provider = FakeProvider(mutate_verify=lambda result: result["reviews"][0].pop(field))
                report = self.generate(provider)
                self.assertEqual(report["observations"], [])
                self.assertTrue(report["no_advice_reasons"])

    def test_conflict_occlusion_and_label_dependence_reject_synonym_candidate(self):
        cases = [("record_conflict", True, "record_conflict"), ("visible", False, "visibility_unknown"),
                 ("label_dependent", True, "label_dependent")]
        for field, value, reason in cases:
            provider = FakeProvider(mutate_observe=lambda result: result["observations"][0].update(
                observation="左脚的鞋底从下方位置来到上方位置。"),
                mutate_verify=lambda result: result["reviews"][0].update({field: value}))
            report = self.approved(provider)
            self.assertEqual(report["improvements"], [])
            self.assertEqual(report["observations"], [])
            self.assertIn(reason, report["reason_codes"])

    def test_two_frames_cannot_establish_repetition_or_contact_process(self):
        for kind in ("position_change", "repetition", "sequence", "contact_process"):
            provider = FakeProvider(mutate_observe=lambda result: result["observations"][0].update(fact_kind=kind),
                mutate_verify=lambda result: result["reviews"][0].update(
                    evidence=[result["reviews"][0]["evidence"][0], result["reviews"][0]["evidence"][-1]]))
            report = self.approved(provider)
            self.assertEqual(report["observations"], [])
            self.assertIn("event_sampling_insufficient", report["reason_codes"])

    def test_sparse_long_event_stays_unconfirmed_even_when_verifier_agrees(self):
        def long_event(result):
            row = result["observations"][0]
            row.update(fact_kind="repetition", end_seconds=4.9)
            row["evidence"][-1] = {"frame_id": "frame-49", "time_seconds": 4.9}
        report = self.approved(FakeProvider(mutate_observe=long_event))
        self.assertEqual(report["observations"], [])
        self.assertIn("event_sampling_insufficient", report["reason_codes"])

    def test_normal_explanation_is_a_review_not_a_technical_problem(self):
        for normal in ("plausible", "unknown", None):
            report = self.approved(FakeProvider(mutate_verify=lambda result: result["reviews"][0].update(normal_explanation=normal)))
            self.assertEqual(len(report["observations"]), 1)
            self.assertEqual(report["improvements"], [])
            self.assertEqual(report["result_status"], "review")
            self.assertIn("normal_explanation", report["reason_codes"])

    def test_review_focus_requires_explicit_worth_and_specific_reason(self):
        for mutation in (lambda row: row.update(review_worthy=False),
                         lambda row: row.pop("review_worthy"),
                         lambda row: row.update(review_reason=""),
                         lambda row: row.update(review_question="建议把脚换一个位置。")):
            report = self.generate(FakeProvider(mutate_verify=lambda result: mutation(result["reviews"][0])))
            self.assertEqual(len(report["observations"]), 1)
            self.assertIsNone(report["next_attempt"])

    def test_static_start_is_never_promoted_as_review_focus(self):
        def static(result):
            row = result["observations"][0]
            row.update(title="左脚可见位置", observation="左脚位于画面下方。", fact_kind="static_position",
                       end_seconds=row["start_seconds"], evidence=row["evidence"][:1])
        report = self.generate(FakeProvider(mutate_observe=static))
        self.assertEqual(len(report["observations"]), 1)
        self.assertIsNone(report["next_attempt"])

    def test_unsampled_candidates_are_disclosed_without_unique_priority(self):
        def many(result):
            result["observations"] = [copy.deepcopy(result["observations"][0]) for _ in range(3)]
        report = self.generate(FakeProvider(mutate_observe=many))
        self.assertEqual(len(report["observations"]), 2)
        self.assertIsNone(report["next_attempt"])
        self.assertIn("candidate_budget_limit", report["reason_codes"])

    def test_condition_text_needs_actual_condition_specific_frame_references(self):
        for frame_ids in (None, [], ["invented"], ["frame-49"], [{"bad": True}]):
            def bad(result):
                reference = result["reviews"][0]["condition_checks"][0]["evidence"][0]
                reference["frame_ids"] = frame_ids
            report = self.approved(FakeProvider(mutate_verify=bad))
            self.assertEqual(report["improvements"], [])
            self.assertIn("conditions_unknown", report["reason_codes"])

    def test_nonempty_unknown_conditions_never_grant_advice(self):
        report = self.approved(FakeProvider(mutate_verify=lambda result: result["reviews"][0].update(
            condition_checks=[{"condition_id": "feet_visible", "state": "unknown", "explanation": "大概适用"}])))
        self.assertEqual(report["improvements"], [])
        self.assertIn("conditions_unknown", report["reason_codes"])

    def test_unit_review_flags_and_medical_flags_cannot_grant_permissions(self):
        path = self.knowledge / "units" / "KB-FOOT-TEST.json"
        unit = json.loads(path.read_text(encoding="utf-8"))
        unit["review"] = {"automatic_use": True, "professional": "approved", "video_validation": "passed",
                          "professional_record": "nonexistent", "video_validation_record": "nonexistent",
                          "medical": "approved", "medical_record": "nonexistent"}
        path.write_text(json.dumps(unit), encoding="utf-8")
        report = self.generate()
        self.assertEqual(report["improvements"], [])
        self.assertEqual(report["risk_reminders"], [])
        self.assertFalse(KnowledgeLibrary.eligible(unit))

    def test_advice_is_one_approved_template_after_all_gates_and_goal_ranking(self):
        provider = FakeProvider()
        report = self.approved(provider, personal={"height_cm": 180, "weight_kg": 70})
        self.assertEqual([call["stage"] for call in provider.calls], ["observe", "verify", "compose"])
        self.assertEqual(len(report["improvements"]), 1)
        self.assertEqual(report["improvements"][0]["adjustment"], FixtureRegistry.template["adjustment_template"])
        self.assertEqual(report["improvements"][0]["claim_id"], "CLAIM-TEST-1")
        self.assertEqual(report["result_status"], "try")
        self.assertEqual(report["risk_reminders"], [])
        self.assertNotIn("weight_kg", json.dumps(provider.calls))
        self.assertEqual(report["personal_information_used"], [{
            "field": "goal", "purpose": "仅为已通过事实及条件检查的候选排序", "source": "current_self_report"}])

    def test_alias_or_model_drift_cannot_reuse_frozen_advice_validation(self):
        with patch("core.replay_coaching_knowledge.ClaimRegistry", FixtureRegistry):
            report = self.generate(context={"goal": "核对脚部"})
        self.assertEqual(report["improvements"], [])
        self.assertIn("model_version_unvalidated", report["reason_codes"])
        for drift_stage in ("observe", "verify", "compose"):
            fake = FakeProvider()
            class Drift:
                def __call__(self, **kwargs):
                    response = fake(**kwargs)
                    if kwargs["stage"] == drift_stage:
                        response["model"] = "qwen3-vl-plus-2025-09-23"
                    return response
            report = self.approved(Drift())
            self.assertEqual(report["improvements"], [])
            self.assertIn("model_version_unvalidated", report["reason_codes"])

    def test_real_registry_contract_integrates_with_local_review_and_fixed_template(self):
        from test_replay_coaching_knowledge import write_approved_fixture
        claim, *_ = write_approved_fixture(self.knowledge)
        def checked(result):
            row = result["reviews"][0]
            evidence = [{"kind": "visual_fact", "fact_id": row["observation_id"],
                         "frame_ids": [item["frame_id"] for item in row["evidence"]]}]
            row["condition_checks"] = [
                {"condition_id": item["id"], "state": "satisfied", "evidence": evidence}
                for item in claim["required_conditions"]]
            row["condition_checks"] += [
                {"condition_id": item["id"], "state": "not_satisfied", "evidence": evidence}
                for item in claim["exclusions"]]
        with patch.dict("os.environ", {"REPLAY_COACHING_MODEL": "qwen3-vl-plus-2025-12-19"}):
            report = self.generate(FakeProvider(mutate_verify=checked), context={"goal": "核对脚部衔接"})
            self.assertEqual(report["result_status"], "try")
            self.assertEqual(report["improvements"][0]["adjustment"], claim["adjustment_template"])
            self.assertEqual(report["improvements"][0]["claim_id"], claim["id"])
            def missing(result):
                checked(result)
                result["reviews"][0]["condition_checks"][0]["evidence"] = []
            refused = self.generate(FakeProvider(mutate_verify=missing), context={"goal": "核对脚部衔接"})
            self.assertEqual(refused["improvements"], [])
            self.assertIn("conditions_unknown", refused["reason_codes"])

    def test_unrelated_goal_or_tied_priority_and_no_goal_do_not_force_advice(self):
        for mutation in (lambda result: result.update(selected=None),
                         lambda result: result["selected"].update(goal_related=False),
                         lambda result: result["selected"].update(priority_distinguishable=False),
                         lambda result: result["selected"].update(candidate_id="invented")):
            self.assertEqual(self.approved(FakeProvider(mutate_compose=mutation))["improvements"], [])
        report = self.approved(context={})
        self.assertEqual(report["improvements"], [])
        self.assertIn("goal_relation_unknown", report["reason_codes"])

    def test_discomfort_or_restriction_stops_all_advice_without_diagnosis(self):
        for field in ("discomfort", "movement_limitations"):
            provider = FakeProvider()
            report = self.approved(provider, context={"goal": "核对脚部", field: "用户自述不舒服"})
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(report["improvements"], [])
            self.assertEqual(report["risk_reminders"], [])
            self.assertIn("self_report_restriction", report["reason_codes"])
            self.assertNotIn("用户自述不舒服", json.dumps(provider.calls, ensure_ascii=False))

    def test_complex_and_force_templates_are_rejected_even_if_registry_returns_them(self):
        for text in ("尝试勾脚。", "关节负荷降低 20%。", "建议进行康复训练。"):
            with patch.dict(FixtureRegistry.template, {"adjustment_template": text}):
                report = self.approved()
                self.assertEqual(report["improvements"], [])
                self.assertIn("boundary_rejected", report["reason_codes"])

    def test_unsafe_observation_is_not_a_report(self):
        for text in ("你应该伸直手臂。", "你明显疲劳。", "左臂承担大部分重量。",
                     "你的膝盖有扭伤风险。", "you should rotate your knee"):
            report = self.generate(FakeProvider(mutate_observe=lambda result: result["observations"][0].update(observation=text)))
            self.assertEqual(report["observations"], [])

    def test_missing_media_and_initial_cancel_do_not_call_cloud(self):
        provider = FakeProvider()
        with self.assertRaises(CoachingCancelled):
            self.generate(provider, cancelled=lambda: True)
        self.assertEqual(provider.calls, [])
        self.media.unlink()
        with self.assertRaisesRegex(CoachingEngineError, "media_missing"):
            self.generate(provider)
        self.assertEqual(provider.calls, [])

    def test_late_cancel_keeps_received_usage_and_stops_following_call(self):
        provider, events = FakeProvider(), []
        with self.assertRaises(CoachingCancelled):
            self.generate(provider, cancelled=lambda: bool(provider.calls), usage_callback=events.append)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(events[0]["status"], "started")
        self.assertTrue(events[-1]["usage_complete"])
        self.assertEqual(events[-1]["usage"]["total_tokens"], 12)

    def test_invalid_content_keeps_known_usage_before_parse_failure(self):
        provider, events = FakeProvider(), []
        class Invalid:
            def __call__(self, **kwargs):
                response = provider(**kwargs)
                response["content"] = "not-an-object"
                return response
        with self.assertRaisesRegex(CoachingEngineError, "provider_invalid_response"):
            self.generate(Invalid(), usage_callback=events.append)
        self.assertEqual([row["status"] for row in events], ["started", "responded", "failed"])
        self.assertTrue(events[-1]["usage_complete"])

    def test_timeout_records_unknown_fee_and_no_implicit_retry(self):
        events, calls = [], []
        class Timeout:
            def __call__(self, **kwargs):
                calls.append(kwargs)
                raise CoachingEngineError("provider_timeout")
        with self.assertRaisesRegex(CoachingEngineError, "provider_timeout"):
            self.generate(Timeout(), usage_callback=events.append)
        self.assertEqual(len(calls), 1)
        self.assertFalse(events[-1]["usage_complete"])
        self.assertEqual(events[-1]["status"], "failed")

    def test_unknown_usage_or_model_prevents_next_paid_call(self):
        for provider in (FakeProvider(usage={"total_tokens": 12}), FakeProvider(response_model="unknown")):
            report = self.generate(provider)
            self.assertEqual(len(provider.calls), 1)
            self.assertIn("usage_unknown", report["reason_codes"])
            self.assertEqual(report["result_status"], "insufficient")

    def test_spent_budget_prevents_next_call(self):
        provider = FakeProvider(usage={"prompt_tokens": 200000, "completion_tokens": 2000, "total_tokens": 202000})
        report = self.generate(provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("budget_limit", report["reason_codes"])

    def test_request_count_is_enforced_independently_of_money(self):
        provider = FakeProvider()
        engine = CoachingEngine(provider=provider, knowledge_root=self.knowledge)
        ledger = [{"model": "qwen3-vl-plus", "usage_complete": True,
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1}}] * 3
        with self.assertRaisesRegex(CoachingEngineError, "budget_limit"):
            engine._call("compose", "{}", [], lambda: False, ledger, None, lambda: None)
        self.assertEqual(provider.calls, [])

    def test_decode_gap_prevents_claiming_complete_event(self):
        original = cv2.VideoCapture
        class PartialCapture:
            def __init__(self, path):
                self.capture = original(path)
                self.index = 0
            def isOpened(self): return self.capture.isOpened()
            def get(self, prop): return self.capture.get(prop)
            def set(self, prop, value):
                self.index = int(value)
                return self.capture.set(prop, value)
            def read(self):
                return (False, None) if self.index == 2 else self.capture.read()
            def release(self): self.capture.release()
        with patch("core.replay_coaching_engine.cv2.VideoCapture", PartialCapture):
            report = self.generate(FakeProvider(mutate_observe=lambda result: result["observations"][0].update(fact_kind="repetition")))
        self.assertEqual(report["observations"], [])
        self.assertIn("event_sampling_insufficient", report["reason_codes"])

    def test_unknown_initial_model_is_rejected_before_paid_request(self):
        provider = FakeProvider()
        with patch.dict("os.environ", {"REPLAY_COACHING_MODEL": "unpriced-model"}):
            with self.assertRaisesRegex(CoachingEngineError, "budget_limit"):
                self.generate(provider)
        self.assertEqual(provider.calls, [])

    def test_media_and_knowledge_mutation_stop_after_metering_response(self):
        for mutate, error in ((lambda: self.media.touch(), "media_changed"),
                              (lambda: (self.knowledge / "withdrawals.json").write_text("[]"), "knowledge_changed")):
            provider = FakeProvider()
            events = []
            class Mutating:
                def __call__(self, **kwargs):
                    response = provider(**kwargs)
                    mutate()
                    return response
            with self.assertRaisesRegex(CoachingEngineError, error):
                self.generate(Mutating(), usage_callback=events.append)
            self.assertEqual(len(provider.calls), 1)
            self.assertTrue(events[-1]["usage_complete"])

    def test_knowledge_fingerprint_includes_reviews_and_withdrawals(self):
        engine = CoachingEngine(provider=FakeProvider(), knowledge_root=self.knowledge)
        before = engine.knowledge_fingerprint()
        (self.knowledge / "withdrawals.json").write_text("[]", encoding="utf-8")
        self.assertNotEqual(before, engine.knowledge_fingerprint())

    def test_source_media_is_recorded_without_claiming_overlay_was_removed(self):
        report = self.generate(media_kind="source_video")
        self.assertFalse(report["provenance"]["media"]["overlay_present"])
        self.assertEqual(report["provenance"]["media"]["kind"], "source_video")
        self.assertFalse(any("插值" in note for note in report["limitations"]))


class ProviderTests(unittest.TestCase):
    def test_only_https_beijing_endpoints_can_receive_frames(self):
        for endpoint in ("https://dashscope.aliyuncs.com/compatible-mode/v1",
                         "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"):
            self.assertEqual(_base_url(endpoint), endpoint)
        for endpoint in ("http://dashscope.aliyuncs.com/compatible-mode/v1",
                         "https://dashscope.aliyuncs.com.evil.invalid/compatible-mode/v1",
                         "https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1",
                         "https://ws.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
                         "https://dashscope.aliyuncs.com/compatible-mode/v1?token=secret"):
            with self.assertRaises(CoachingEngineError):
                _base_url(endpoint)

    def test_timeouts_and_provider_errors_are_sanitized(self):
        provider = DashScopeProvider("test-key-never-real", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        for exception, code in ((httpx.ReadTimeout("secret internal request"), "provider_timeout"),
                                (httpx.ConnectError("secret response"), "provider_invalid_response")):
            with patch("core.replay_coaching_engine.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.side_effect = exception
                with self.assertRaises(CoachingEngineError) as captured:
                    provider(stage="observe", messages=[], model="qwen3-vl-plus", cancelled=lambda: False)
                self.assertEqual(str(captured.exception), code)
                self.assertNotIn("secret", str(captured.exception))

    def test_real_adapter_is_bounded_and_meters_before_generated_json_parse(self):
        with patch("core.replay_coaching_engine.httpx.Client") as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.return_value = {"choices": [{"message": {"content": "invalid"}}],
                "model": "qwen3-vl-plus", "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}
            events = []
            with self.assertRaisesRegex(CoachingEngineError, "provider_invalid_response"):
                DashScopeProvider("fake", "https://dashscope.aliyuncs.com/compatible-mode/v1")(
                    stage="observe", messages=[], model="qwen3-vl-plus", cancelled=lambda: False,
                    response_callback=events.append)
            self.assertEqual(events[0]["usage"]["total_tokens"], 6)
            self.assertFalse(client.call_args.kwargs["follow_redirects"])
            payload = client.return_value.__enter__.return_value.post.call_args.kwargs["json"]
            self.assertEqual(payload["max_tokens"], MAX_OUTPUT_TOKENS)
            self.assertFalse(payload["enable_thinking"])


if __name__ == "__main__":
    unittest.main()
