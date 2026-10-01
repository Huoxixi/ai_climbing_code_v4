"""Private coaching lifecycle checks using synthetic media and a fake provider."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import (
    ClimbReplayManager, ClimbReplayStore, REPLAY_CONSENT_VERSION,
    REPLAY_OVERLAY_FILENAME, REPLAY_OVERLAY_MEDIA_KIND, REPLAY_RETENTION_KEEP,
    VideoInfo, create_climb_replay_router,
)
from core.replay_coaching import CONSENT_VERSION, CoachingManager


SECRET_SENTINEL = "test-secret-must-never-persist-847521"  # gitleaks:allow -- fake leak-detection sentinel


class SyntheticCoachingEngine:
    configured = True
    model = "fake-vision-model"
    provider = "fake-private-provider"

    def __init__(self, knowledge_root):
        self.knowledge_root = knowledge_root
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.calls = []
        self.failures_remaining = 0
        self.saw_cancellation = False

    def generate(self, job, media_path, media_kind, personal, context, cancelled, usage_callback=None):
        self.calls.append({"job": copy.deepcopy(job), "media_kind": media_kind,
                           "personal": copy.deepcopy(personal), "context": copy.deepcopy(context)})
        call_number = len(self.calls)
        if usage_callback:
            usage_callback({"request_id": f"request-{call_number}", "stage": "observe", "model": "qwen3-vl-plus", "status": "started"})
        self.started.set()
        if not self.release.wait(8):
            raise RuntimeError("synthetic provider timed out")
        self.saw_cancellation = cancelled()
        if usage_callback:
            usage_callback({"request_id": f"request-{call_number}", "stage": "observe", "model": "qwen3-vl-plus", "status": "responded",
                            "usage_complete": True, "usage": {"prompt_tokens": 1000, "completion_tokens": 100}, "raw": SECRET_SENTINEL})
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError(SECRET_SENTINEL)
        # Intentionally return even after cancellation to test the commit barrier.
        return {"observations": [{"id": "obs-1", "text": "synthetic observation"}],
                "improvements": [], "risk_reminders": [], "summary": f"synthetic report {call_number}"}


class UnusedReplayAnalyzer:
    def analysis_contract(self, _):
        raise AssertionError("Coaching must not rerun the upstream replay analyzer")


class ReplayCoachingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="replay-coaching-test-")
        self.root = Path(self.temp.name)
        knowledge = self.root / "knowledge"
        knowledge.mkdir()
        (knowledge / "sources.json").write_text("[]", encoding="utf-8")
        self.store = ClimbReplayStore(self.root / "store")
        self.upstream = ClimbReplayManager(self.store, UnusedReplayAnalyzer())
        self.engine = SyntheticCoachingEngine(knowledge)
        self.manager = CoachingManager(self.store, self.engine, enabled=True)
        self.job_id = self.make_job()
        app = FastAPI()

        @app.middleware("http")
        async def identify(request: Request, call_next):
            username = request.headers.get("x-user", "alice")
            if username != "anonymous":
                request.state.pilot_user = SimpleNamespace(username=username)
            return await call_next(request)

        app.include_router(create_climb_replay_router(
            self.store, self.upstream, coaching_manager=self.manager,
        ))
        self.client = TestClient(app)
        self.url = f"/api/climb-replay/jobs/{self.job_id}/coaching"

    def tearDown(self):
        self.engine.release.set()
        self.manager.close()
        self.upstream.close()
        self.client.close()
        self.temp.cleanup()

    def make_job(self):
        source = self.root / "synthetic.mp4"
        source.write_bytes(b"synthetic-local-video")
        job = self.store.create(
            owner="alice", route_id="route-1", route_color="blue", source=source,
            original_name="private-original-name.mp4",
            info=VideoInfo(width=96, height=64, fps=4, frame_count=24,
                           duration_seconds=6, size_bytes=21),
            consent={"event": "granted", "attempt": 1, "version": REPLAY_CONSENT_VERSION},
            retention_mode=REPLAY_RETENTION_KEEP,
        )
        job_id = job["id"]
        self.store.update(job_id, status="succeeded", route_version_id="route-version-1",
                          route_hold_ids=["H01", "H02"], result={
            "schema_version": 2, "video": job["video"],
            "analysis": {"sampling": {"effective_fps": 4}},
            "pose_samples": [{"time_seconds": .5, "source_frame_id": 2}],
            "attempt": {"segments": [{"id": "right_hand:1:2", "limb": "right_hand",
                                       "start_time_seconds": .5, "end_time_seconds": 2,
                                       "duration_seconds": 1.5, "comparable": False,
                                       "reason": "unconfirmed_hold_identity"}]},
        })
        (self.store._path(job_id).parent / REPLAY_OVERLAY_FILENAME).write_bytes(b"synthetic-overlay")
        self.store.register_overlay(job_id)
        return job_id

    def payload(self, **changes):
        return {"consent_version": CONSENT_VERSION, "consent_granted": True,
                "indoor_bouldering_confirmed": True, "budget_accepted": True, "observation_only_accepted": True,
                "adult_confirmed": True, **changes}

    def create(self, **changes):
        response = self.client.post(self.url, json=self.payload(**changes))
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def wait_report(self, expected="succeeded"):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = self.manager.get(self.job_id, "alice")
            if result["status"] not in {"queued", "running"}:
                self.assertEqual(result["status"], expected, result)
                return result
            time.sleep(.01)
        self.fail("Synthetic coaching report did not finish")

    def wait_worker_idle(self):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.manager._queue.unfinished_tasks == 0:
                return
            time.sleep(.01)
        self.fail("Coaching worker did not finish its synthetic request")

    def block_provider(self):
        self.engine.release.clear()
        self.create()
        self.assertTrue(self.engine.started.wait(3), "Fake provider did not start")

    def test_policy_auth_and_every_report_operation_is_owner_scoped(self):
        policy = self.client.get("/api/climb-replay/coaching-policy")
        self.assertEqual(policy.status_code, 200)
        self.assertFalse(policy.json()["full_video_sent"])
        self.assertEqual(policy.headers["cache-control"], "private, no-store")
        self.assertEqual(self.client.get("/api/climb-replay/coaching-policy",
                                        headers={"x-user": "anonymous"}).status_code, 401)
        self.create()
        report = self.wait_report()
        operations = [("get", self.url, None), ("post", self.url, self.payload()),
                      ("post", self.url + "/cancel", None),
                      ("post", self.url + "/consent/withdraw", None),
                      ("post", self.url + "/feedback", {"report_id": report["id"],
                                                         "item_id": "obs-1", "kind": "helpful"})]
        for method, url, body in operations:
            with self.subTest(operation=url):
                response = self.client.request(method, url, json=body, headers={"x-user": "bob"})
                self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.manager.get(self.job_id, "alice")["status"], "succeeded")

    def test_identical_running_and_completed_requests_do_not_repeat_provider_call(self):
        self.block_provider()
        first = self.manager.get(self.job_id, "alice")
        second = self.create()
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.engine.calls), 1)
        self.engine.release.set()
        self.wait_report()
        third = self.create()
        self.assertEqual(third["id"], first["id"])
        self.assertEqual(len(self.engine.calls), 1)

    def test_personal_fields_optional_and_never_carried_to_next_report_implicitly(self):
        self.create(personal={"height_cm": 171, "usual_grade": " V3 "},
                    context={"goal": " foot placement "})
        self.wait_report()
        self.assertEqual(self.engine.calls[0]["personal"], {"height_cm": 171, "usual_grade": "V3"})
        self.create()
        self.wait_report()
        self.assertEqual(self.engine.calls[1]["personal"], {})
        for call in self.engine.calls:
            self.assertEqual(call["media_kind"], "source_video")
            self.assertNotIn("owner", call["job"])
            self.assertNotIn("original_name", call["job"])
            self.assertNotIn("input_path", call["job"])
            self.assertNotIn("coaching_history", call["job"])
        public = self.client.get(f"/api/climb-replay/jobs/{self.job_id}").json()
        self.assertNotIn("coaching", public)
        self.assertNotIn("coaching_history", public)
        self.assertNotIn("coaching", self.store.list("alice")[0])
        report = self.client.get(self.url)
        self.assertEqual(report.json().get("personal", {}), {})
        self.assertNotIn("coaching_history", report.json())
        self.assertEqual(report.headers["cache-control"], "private, no-store")

    def test_changed_context_cannot_start_second_report_while_first_runs(self):
        self.block_provider()
        response = self.client.post(self.url, json=self.payload(context={"goal": "another goal"}))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(self.engine.calls), 1)
        self.engine.release.set()
        self.wait_report()

    def test_reviewed_overlay_is_preferred_when_available(self):
        self.store.delete_media(self.job_id, "alice", "source_video")
        job = self.store.get(self.job_id, "alice", private=True)
        name = "overlay-review-1.webm"
        (self.store._path(self.job_id).parent / name).write_bytes(b"synthetic-reviewed-overlay")
        media = copy.deepcopy(job["media"])
        media["reviewed_overlay_video"] = {"status": "available", "storage_name": name,
                                           "checksum_sha256": "synthetic-review-checksum"}
        self.store.update(self.job_id, media=media)
        self.create()
        self.wait_report()
        self.assertEqual(self.engine.calls[0]["media_kind"], "reviewed_overlay_video")

    def test_consent_scope_and_interval_validation_precede_provider_calls(self):
        cases = [({"consent_granted": False}, 409), ({"consent_version": "old-version"}, 409),
                 ({"indoor_bouldering_confirmed": False}, 422),
                 ({"budget_accepted": False}, 409), ({"observation_only_accepted": False}, 409),
                 ({"context": {"focus_start_seconds": 1}}, 422),
                 ({"context": {"focus_start_seconds": 1, "focus_end_seconds": 7}}, 422),
                 ({"personal": {"height_cm": -1}}, 422)]
        for changes, status in cases:
            with self.subTest(changes=changes):
                response = self.client.post(self.url, json=self.payload(**changes))
                self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.manager.get(self.job_id, "alice")["status"], "none")

    def test_age_is_optional_for_observation_and_consent_preserves_supplied_value(self):
        for age_value in (None, False, True):
            with self.subTest(age_value=age_value):
                job_id = self.make_job()
                payload = self.payload()
                if age_value is None:
                    payload.pop("adult_confirmed")
                else:
                    payload["adult_confirmed"] = age_value
                response = self.client.post(f"/api/climb-replay/jobs/{job_id}/coaching", json=payload)
                self.assertEqual(response.status_code, 202, response.text)
                self.wait_worker_idle()
                private = self.store.get(job_id, "alice", private=True)
                self.assertEqual(private["coaching"]["status"], "succeeded")
                self.assertIs(private["coaching"]["consent"]["adult_confirmed"], age_value)

    def test_upstream_completion_and_existing_media_are_required(self):
        self.store.update(self.job_id, status="running")
        response = self.client.post(self.url, json=self.payload())
        self.assertEqual(response.status_code, 409)
        self.store.update(self.job_id, status="succeeded")
        self.store.delete_media(self.job_id, "alice", REPLAY_OVERLAY_MEDIA_KIND)
        self.store.delete_media(self.job_id, "alice", "source_video")
        response = self.client.post(self.url, json=self.payload())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.engine.calls, [])

    def test_unconfigured_or_disabled_provider_does_not_queue_report(self):
        self.engine.configured = False
        self.assertEqual(self.client.post(self.url, json=self.payload()).status_code, 503)
        self.engine.configured = True
        self.manager.enabled = False
        self.assertEqual(self.client.post(self.url, json=self.payload()).status_code, 503)
        self.assertEqual(self.engine.calls, [])

    def test_failed_provider_error_is_sanitized_and_explicit_retry_succeeds(self):
        self.engine.failures_remaining = 1
        first = self.create()
        failed = self.wait_report("failed")
        self.assertNotIn(SECRET_SENTINEL, json.dumps(failed))
        self.assertNotIn(SECRET_SENTINEL, self.store._path(self.job_id).read_text(encoding="utf-8"))
        second = self.create()
        self.assertNotEqual(first["id"], second["id"])
        self.wait_report()
        self.assertEqual(len(self.engine.calls), 2)
        self.assertNotIn(SECRET_SENTINEL, self.store._path(self.job_id).read_text(encoding="utf-8"))

    def test_feedback_requires_current_report_and_known_item_and_deduplicates(self):
        self.create()
        report = self.wait_report()
        valid = {"report_id": report["id"], "item_id": "obs-1", "kind": "helpful"}
        for changed in ({"report_id": "another-report"}, {"item_id": "absent-item"}):
            response = self.client.post(self.url + "/feedback", json={**valid, **changed})
            self.assertEqual(response.status_code, 409)
        for _ in range(2):
            response = self.client.post(self.url + "/feedback", json=valid)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["feedback"]), 1)

    def test_review_change_marks_completed_report_stale_and_rejects_feedback(self):
        self.create()
        report = self.wait_report()
        response = self.client.put(
            f"/api/climb-replay/jobs/{self.job_id}/segments/right_hand:1:2/review",
            json={"limb": "right_hand", "source_route_hold_id": "H01", "target_route_hold_id": "H02",
                  "start_time_seconds": .6, "end_time_seconds": 2.2, "technique_label": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.manager.get(self.job_id, "alice")["stale"])
        response = self.client.post(self.url + "/feedback", json={
            "report_id": report["id"], "item_id": "obs-1", "kind": "helpful"})
        self.assertEqual(response.status_code, 409)

    def test_evidence_snapshot_survives_edits_and_regeneration_without_public_exposure(self):
        self.create()
        first = self.wait_report()
        original = self.store.get(self.job_id, "alice", private=True)
        snapshot = copy.deepcopy(original["coaching"]["evidence_snapshot"])
        self.assertEqual(snapshot["result"], original["result"])
        self.assertEqual(snapshot["reviewed_segments"], self.store._public(original)["reviewed_segments"])

        result = copy.deepcopy(original["result"])
        result["hold_review_version"] = 2
        self.store.update(self.job_id, result=result)
        response = self.client.put(
            f"/api/climb-replay/jobs/{self.job_id}/segments/right_hand:1:2/review",
            json={"limb": "right_hand", "source_route_hold_id": "H01", "target_route_hold_id": "H02",
                  "start_time_seconds": .7, "end_time_seconds": 2.3, "technique_label": None})
        self.assertEqual(response.status_code, 200, response.text)
        changed = self.store.get(self.job_id, "alice", private=True)
        self.assertEqual(changed["coaching"]["evidence_snapshot"], snapshot)
        self.assertTrue(self.manager.get(self.job_id, "alice")["stale"])

        self.create()
        second = self.wait_report()
        self.assertNotEqual(first["id"], second["id"])
        regenerated = self.store.get(self.job_id, "alice", private=True)
        self.assertEqual(regenerated["coaching_history"][-1]["id"], first["id"])
        self.assertEqual(regenerated["coaching_history"][-1]["evidence_snapshot"], snapshot)
        new_snapshot = regenerated["coaching"]["evidence_snapshot"]
        self.assertEqual(new_snapshot["result"]["hold_review_version"], 2)
        self.assertEqual(new_snapshot["reviewed_segments"][0]["start_time_seconds"], .7)
        self.assertEqual(new_snapshot["segment_review_history"][-1]["operation"], "set")
        self.assertFalse(second["stale"])
        for public in (self.client.get(f"/api/climb-replay/jobs/{self.job_id}").json(),
                       self.store.list("alice"), self.client.get(self.url).json()):
            self.assertNotIn("evidence_snapshot", json.dumps(public))
            self.assertNotIn("coaching_history", json.dumps(public))

    def test_input_change_during_provider_request_cannot_commit_old_report(self):
        self.block_provider()
        job = self.store.get(self.job_id, "alice", private=True)
        result = copy.deepcopy(job["result"])
        result["hold_review_version"] = 2
        self.store.update(self.job_id, result=result)
        self.engine.release.set()
        self.wait_worker_idle()
        report = self.wait_report("cancelled")
        self.assertIsNone(report["report"])
        self.assertTrue(self.engine.saw_cancellation)

    def test_whole_job_delete_during_provider_request_never_recreates_directory(self):
        self.block_provider()
        directory = self.store._path(self.job_id).parent
        response = self.client.delete(f"/api/climb-replay/jobs/{self.job_id}")
        self.assertEqual(response.status_code, 202, response.text)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if self.store.get_deletion(self.job_id, "alice")["state"] == "completed":
                break
            time.sleep(.01)
        self.assertEqual(self.store.get_deletion(self.job_id, "alice")["state"], "completed")
        self.assertFalse(directory.exists())
        self.engine.release.set()
        self.wait_worker_idle()
        self.assertFalse(directory.exists())
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_overlay_delete_during_provider_request_discards_late_response(self):
        self.store.delete_media(self.job_id, "alice", "source_video")
        self.block_provider()
        response = self.client.delete(f"/api/climb-replay/jobs/{self.job_id}/media/overlay-video")
        self.assertEqual(response.status_code, 200, response.text)
        self.engine.release.set()
        self.wait_worker_idle()
        report = self.wait_report("cancelled")
        self.assertIsNone(report["report"])
        self.assertTrue(report["stale"])
        self.assertFalse((self.store._path(self.job_id).parent / REPLAY_OVERLAY_FILENAME).exists())

    def test_coaching_consent_withdrawal_during_request_discards_late_response(self):
        self.block_provider()
        response = self.client.post(self.url + "/consent/withdraw")
        self.assertEqual(response.status_code, 200, response.text)
        self.engine.release.set()
        self.wait_worker_idle()
        report = self.wait_report("cancelled")
        self.assertIsNone(report["report"])
        private = self.store.get(self.job_id, "alice", private=True)
        self.assertEqual(private["coaching"]["consent"]["event"], "withdrawn")
        self.assertEqual(private["status"], "succeeded")
        self.assertTrue(self.engine.saw_cancellation)

    def test_cancel_then_new_request_cannot_be_overwritten_by_first_response(self):
        self.block_provider()
        first = self.manager.get(self.job_id, "alice")
        self.assertEqual(self.client.post(self.url + "/cancel").status_code, 200)
        second = self.create(personal={"height_cm": 177})
        self.assertNotEqual(first["id"], second["id"])
        self.engine.release.set()
        self.wait_worker_idle()
        completed = self.wait_report()
        self.assertEqual(completed["id"], second["id"])
        self.assertEqual(completed["report"]["summary"], "synthetic report 2")
        self.assertEqual(len(self.engine.calls), 2)
        self.assertEqual(self.engine.calls[-1]["personal"], {"height_cm": 177})

    def test_service_close_cancels_late_result_and_rejects_new_requests(self):
        self.block_provider()
        self.manager.close()
        self.engine.release.set()
        self.wait_worker_idle()
        self.assertIsNone(self.wait_report("cancelled")["report"])
        self.assertEqual(self.client.post(self.url, json=self.payload()).status_code, 503)

    def test_upstream_consent_withdrawal_after_replay_completion_stops_coaching(self):
        self.block_provider()
        response = self.client.post(f"/api/climb-replay/jobs/{self.job_id}/consent/withdraw")
        self.assertEqual(response.status_code, 200, response.text)
        self.engine.release.set()
        self.wait_worker_idle()
        report = self.wait_report("cancelled")
        self.assertIsNone(report["report"])
        self.assertEqual(self.client.post(self.url, json=self.payload()).status_code, 409)

    def test_service_restart_marks_interrupted_reports_failed_without_cloud_retry(self):
        for state in ("queued", "running"):
            with self.subTest(state=state):
                self.store.update(self.job_id, coaching={"id": "interrupted-run", "status": state,
                                                        "report": None, "error": None})
                recovered = CoachingManager(self.store, self.engine, enabled=True)
                try:
                    private = self.store.get(self.job_id, "alice", private=True)
                    self.assertEqual(private["coaching"]["status"], "failed")
                    self.assertIsNone(recovered._thread)
                    self.assertTrue(recovered._queue.empty())
                    self.assertEqual(self.engine.calls, [])
                finally:
                    recovered.close()
        self.store.coaching_manager = self.manager

    def test_policy_and_preflight_explain_observation_mode_without_calling_provider(self):
        response = self.client.get(self.url + "/preflight")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["advice_available"])
        self.assertTrue(body["ready"])
        self.assertEqual(body["media"]["kind"], "source_video")
        self.assertFalse(body["media"]["has_overlay"])
        self.assertEqual(body["budget"]["amount"], .20)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.client.get(self.url + "/preflight", headers={"x-user": "bob"}).status_code, 404)

    def test_known_usage_is_saved_when_generation_fails(self):
        self.engine.failures_remaining = 1
        self.create()
        result = self.wait_report("failed")
        self.assertEqual(result["cost"]["status"], "estimated")
        self.assertEqual(result["cost"]["amount_min"], .002)
        self.assertNotIn(SECRET_SENTINEL, json.dumps(result))

    def test_pending_call_cost_is_unknown_until_cancelled_response_returns(self):
        self.block_provider()
        pending = self.manager.get(self.job_id, "alice")
        self.assertEqual(pending["cost"]["status"], "unavailable")
        self.assertFalse(pending["cost"]["usage_complete"])
        self.client.post(self.url + "/cancel")
        self.engine.release.set()
        self.wait_worker_idle()
        result = self.wait_report("cancelled")
        self.assertEqual(result["cost"]["amount_min"], .002)
        self.assertIsNone(result["report"])

    def test_cancelled_response_usage_goes_to_original_history(self):
        self.block_provider()
        first = self.manager.get(self.job_id, "alice")
        self.client.post(self.url + "/cancel")
        second = self.create(context={"goal": "核对另一个片段"})
        self.engine.release.set()
        self.wait_worker_idle()
        result = self.wait_report()
        self.assertEqual(result["id"], second["id"])
        stored = self.store.get(self.job_id, "alice", private=True)
        old = next(row for row in stored["coaching_history"] if row["id"] == first["id"])
        self.assertTrue(old["usage_ledger"][0]["usage_complete"])
        self.assertEqual(len(result["usage_ledger"]), 1)

    def test_reason_feedback_is_a_review_queue_not_an_automatic_correction(self):
        self.create()
        result = self.wait_report()
        response = self.client.post(self.url + "/feedback", json={"report_id": result["id"],
            "item_id": "obs-1", "kind": "inaccurate", "reason": "body_part"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["feedback"][0]["review_status"], "pending_review")
        self.assertEqual(response.json()["report"], result["report"])

    def test_knowledge_record_revocation_marks_report_stale(self):
        self.create()
        self.wait_report()
        records = self.engine.knowledge_root / "reviews"
        records.mkdir()
        (records / "review.json").write_text('{"status":"revoked"}', encoding="utf-8")
        self.assertTrue(self.manager.get(self.job_id, "alice")["stale"])


if __name__ == "__main__":
    unittest.main()
