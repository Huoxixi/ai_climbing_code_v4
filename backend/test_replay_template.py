"""Template task HTTP/lifecycle tests with synthetic evidence and no cloud calls."""
import copy
import json
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import create_climb_replay_router, ReplaySegmentReview
from core.replay_template import TemplateVideoManager, TEMPLATE_VERSION
from test_replay_coaching_lifecycle import ReplayCoachingLifecycleTests


class FakeRenderer:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False
        self.ignore_cancel = False

    def __call__(self, source, plan, output, *, cancelled, progress):
        self.calls.append({"source": source, "plan": copy.deepcopy(plan), "output": output})
        self.started.set()
        deadline = time.monotonic() + 5
        while not self.release.wait(.01):
            if cancelled() and not self.ignore_cancel:
                raise InterruptedError()
            if time.monotonic() > deadline:
                raise RuntimeError("fake renderer deadline")
        if not self.ignore_cancel:
            progress("Rendering private local movie", 60)
        if self.fail:
            raise RuntimeError("PRIVATE_ERROR_MUST_NOT_LEAK")
        output.write_bytes(b"synthetic-mp4-0123456789")
        return {"frame_count": 24, "duration_seconds": 6, "new_model_calls": 0}


class TemplateVideoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReplayCoachingLifecycleTests()
        self.fixture.setUp()
        self.store, self.coaching = self.fixture.store, self.fixture.manager
        self.job_id = self.fixture.job_id
        self.renderer = FakeRenderer()
        self.plans = []

        def planner(job, report):
            self.plans.append({"job": copy.deepcopy(job), "report": copy.deepcopy(report)})
            return {"version": TEMPLATE_VERSION, "duration_seconds": 6,
                    "source_duration_seconds": 6, "width": 96, "height": 64, "fps": 4,
                    "shots": [{"kind": "action", "caption": "观察这段动作", "duration_seconds": 6}],
                    "omitted_metrics": [{"metric": "climb_duration", "reason": "起止未确认"}],
                    "internal_test_path": "PRIVATE_PATH_MUST_NOT_LEAK"}

        self.manager = TemplateVideoManager(self.store, self.coaching, planner=planner, renderer=self.renderer)
        self.fixture.client.close()
        app = FastAPI()

        @app.middleware("http")
        async def identify(request: Request, call_next):
            name = request.headers.get("x-user", "alice")
            if name != "anonymous":
                request.state.pilot_user = SimpleNamespace(username=name)
            return await call_next(request)

        app.include_router(create_climb_replay_router(self.store, self.fixture.upstream,
                                                     coaching_manager=self.coaching, template_manager=self.manager))
        self.client = self.fixture.client = TestClient(app)
        self.url = f"/api/climb-replay/jobs/{self.job_id}/template-video"
        self.source, _ = self.store.media_file(self.job_id, "alice", "source_video")
        self.baseline, _ = self.store.media_file(self.job_id, "alice", "overlay_video")
        self.source_bytes, self.baseline_bytes = self.source.read_bytes(), self.baseline.read_bytes()

    def tearDown(self):
        self.renderer.release.set()
        self.fixture.engine.release.set()
        self.manager.close()
        self.fixture.tearDown()

    def create(self, **changes):
        response = self.client.post(self.url, json=self.fixture.payload(**changes))
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def wait(self, status="succeeded"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.manager.get(self.job_id, "alice")
            if state["status"] not in {"queued", "waiting_report", "running"}:
                self.assertEqual(state["status"], status, state)
                return state
            time.sleep(.01)
        self.fail("Template worker did not finish")

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.manager._queue.unfinished_tasks == 0:
                return
            time.sleep(.01)
        self.fail("Template worker did not become idle")

    def test_create_reuses_report_and_preserves_source_baseline_and_private_state(self):
        self.fixture.create()
        self.fixture.wait_report()
        first = self.create()
        state = self.wait()
        self.assertTrue(state["media_ready"])
        self.assertFalse(state["stale"])
        self.assertEqual(state["plan"]["chapter_count"], 1)
        self.assertEqual(state["plan"]["omitted_metrics"][0]["metric"], "climb_duration")
        self.assertEqual(len(self.fixture.engine.calls), 1)
        self.assertEqual(len(self.renderer.calls), 1)
        self.assertEqual(self.renderer.calls[0]["source"], self.source)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual(self.baseline.read_bytes(), self.baseline_bytes)
        self.assertEqual(self.create()["id"], first["id"])
        self.assertEqual(len(self.fixture.engine.calls), 1)
        self.assertEqual(len(self.renderer.calls), 1)
        self.assertNotIn("coaching", self.plans[0]["job"])
        self.assertNotIn("input_path", self.plans[0]["job"])
        public = self.client.get(f"/api/climb-replay/jobs/{self.job_id}").json()
        self.assertNotIn("template_video", public)
        serialized = json.dumps(state)
        for hidden in ("PRIVATE_PATH_MUST_NOT_LEAK", "storage_name", "evidence_fingerprint"):
            self.assertNotIn(hidden, serialized)

    def test_owner_isolation_and_real_range_response(self):
        self.create()
        self.wait()
        response = self.client.get(self.url + "/media", headers={"Range": "bytes=4-9"})
        self.assertEqual(response.status_code, 206, response.text)
        self.assertEqual(response.content, b"synthetic-mp4-0123456789"[4:10])
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        for method, suffix, body in (("GET", "", None), ("POST", "", self.fixture.payload()),
                                     ("POST", "/cancel", None), ("GET", "/media", None)):
            with self.subTest(method=method, suffix=suffix):
                response = self.client.request(method, self.url + suffix, json=body, headers={"x-user": "bob"})
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(self.url, headers={"x-user": "anonymous"}).status_code, 401)

    def test_template_observation_accepts_unspecified_age_without_fabricating_adult_consent(self):
        payload = self.fixture.payload()
        payload.pop("adult_confirmed")
        response = self.client.post(self.url, json=payload)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(self.wait()["media_ready"])
        private = self.store.get(self.job_id, "alice", private=True)
        self.assertIsNone(private["coaching"]["consent"]["adult_confirmed"])
        self.assertEqual(len(self.fixture.engine.calls), 1)

    def test_waits_for_identical_current_report_without_another_cloud_request(self):
        self.fixture.engine.release.clear()
        self.fixture.create()
        self.assertTrue(self.fixture.engine.started.wait(2))
        first = self.create()
        second = self.create()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.fixture.engine.calls), 1)
        self.assertEqual(len(self.renderer.calls), 0)
        self.fixture.engine.release.set()
        self.wait()
        self.assertEqual(len(self.fixture.engine.calls), 1)

    def test_source_is_required_and_invalid_consent_cannot_start_analysis(self):
        response = self.client.post(self.url, json=self.fixture.payload(budget_accepted=False))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.fixture.engine.calls, [])
        self.store.delete_media(self.job_id, "alice", "source_video")
        response = self.client.post(self.url, json=self.fixture.payload())
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.baseline.exists())
        self.assertEqual(self.fixture.engine.calls, [])
        self.assertEqual(self.renderer.calls, [])

    def test_cancel_does_not_cancel_a_shared_report_or_commit_late_movie(self):
        self.fixture.engine.release.clear()
        self.fixture.create()
        self.create()
        self.assertTrue(self.fixture.engine.started.wait(2))
        self.assertEqual(self.client.post(self.url + "/cancel").json()["status"], "cancelled")
        self.fixture.engine.release.set()
        self.fixture.wait_report()
        self.wait_idle()
        self.assertEqual(self.renderer.calls, [])
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])

    def test_cancel_stops_analysis_created_by_this_template(self):
        self.fixture.engine.release.clear()
        self.create()
        self.assertTrue(self.fixture.engine.started.wait(2))
        self.assertEqual(self.client.post(self.url + "/cancel").json()["status"], "cancelled")
        self.assertEqual(self.coaching.get(self.job_id, "alice")["status"], "cancelled")
        self.fixture.engine.release.set()
        self.fixture.wait_worker_idle()
        self.wait_idle()
        self.assertTrue(self.fixture.engine.saw_cancellation)
        self.assertEqual(self.renderer.calls, [])

    def test_changed_context_while_rendering_rejected_before_new_cloud_call(self):
        self.renderer.release.clear()
        self.create()
        self.assertTrue(self.renderer.started.wait(2))
        response = self.client.post(self.url, json=self.fixture.payload(context={"goal": "different"}))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.fixture.engine.calls), 1)
        self.renderer.release.set()
        self.wait()

    def test_failed_new_render_keeps_previous_success_playable_and_error_private(self):
        self.create()
        self.wait()
        old_path = self.manager.media_file(self.job_id, "alice")
        old_version = self.manager.get(self.job_id, "alice")["media_version"]
        old_bytes = old_path.read_bytes()
        self.renderer.fail = True
        previous_planner = self.manager.planner
        self.manager.planner = lambda job, report: dict(previous_planner(job, report), duration_seconds=12)
        self.create(context={"goal": "另一个观察重点"})
        state = self.wait("failed")
        self.assertTrue(state["media_ready"])
        self.assertEqual(state["media_version"], old_version)
        self.assertNotEqual(state["id"], old_version)
        self.assertEqual(state["plan"]["duration_seconds"], 12)
        self.assertEqual(state["media_plan"]["duration_seconds"], 6)
        self.assertEqual(self.manager.media_file(self.job_id, "alice"), old_path)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertNotIn("PRIVATE_ERROR_MUST_NOT_LEAK", json.dumps(state))
        self.assertNotIn("PRIVATE_ERROR_MUST_NOT_LEAK", self.store._path(self.job_id).read_text(encoding="utf-8"))

    def test_review_mutation_cancels_and_invalidates_late_render(self):
        self.renderer.release.clear()
        self.renderer.ignore_cancel = True
        self.create()
        self.assertTrue(self.renderer.started.wait(2))
        self.store.review_segment(self.job_id, "alice", "right_hand:1:2",
                                  ReplaySegmentReview(limb="right_hand", source_route_hold_id="H01",
                                                      target_route_hold_id="H02", start_time_seconds=.5,
                                                      end_time_seconds=2))
        state = self.manager.get(self.job_id, "alice")
        self.assertEqual(state["status"], "cancelled")
        self.assertTrue(state["stale"])
        self.renderer.release.set()
        self.wait_idle()
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
        self.assertFalse(list(self.store._path(self.job_id).parent.glob("template-*.mp4")))

    def test_source_deletion_and_consent_withdrawal_invalidate_successful_media(self):
        self.create()
        self.wait()
        self.coaching.cancel(self.job_id, "alice", revoke=True)
        self.assertTrue(self.manager.get(self.job_id, "alice")["stale"])
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
        self.assertEqual(self.client.get(self.url + "/media").status_code, 409)

    def test_source_deletion_does_not_allow_overlay_to_replace_it(self):
        self.create()
        self.wait()
        self.store.delete_media(self.job_id, "alice", "source_video")
        self.assertTrue(self.manager.get(self.job_id, "alice")["stale"])
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
        self.assertEqual(self.client.get(self.url + "/media").status_code, 409)

    def test_source_deletion_waits_for_active_renderer_to_release_reader(self):
        self.renderer.release.clear()
        self.create()
        self.assertTrue(self.renderer.started.wait(2))
        self.store.delete_media(self.job_id, "alice", "source_video")
        self.wait_idle()
        self.assertFalse(self.source.exists())
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
        self.assertEqual(self.baseline.read_bytes(), self.baseline_bytes)

    def test_scheduled_source_expiry_invalidates_movie_and_preserves_baseline(self):
        self.create()
        self.wait()
        job = self.store.get(self.job_id, "alice", private=True)
        job["media"]["source_video"]["delete_at"] = "2001-01-01T00:00:00+00:00"
        self.store.update(self.job_id, media=job["media"])
        self.assertIn(self.job_id, self.store.cleanup_due_media())
        self.assertFalse(self.source.exists())
        self.assertEqual(self.baseline.read_bytes(), self.baseline_bytes)
        self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
        self.assertEqual(self.client.get(self.url + "/media").status_code, 409)

    def test_knowledge_withdrawal_blocks_successful_movie_without_cloud_calls(self):
        self.create()
        self.wait()
        with patch.object(self.coaching, "_knowledge_version", return_value="withdrawn-claim-set"):
            state = self.manager.get(self.job_id, "alice")
            self.assertTrue(state["stale"])
            self.assertFalse(state["media_ready"])
            self.assertIn("知识", state["stale_reason"])
            self.assertEqual(self.client.get(self.url + "/media").status_code, 409)
        self.assertEqual(len(self.fixture.engine.calls), 1)

    def test_engine_analysis_version_change_invalidates_report_and_movie_cache(self):
        first = self.create()
        self.wait()
        with patch("core.replay_coaching_engine.ANALYSIS_VERSION", "changed-actions-analysis"):
            self.assertTrue(self.coaching.get(self.job_id, "alice")["stale"])
            self.assertFalse(self.manager.get(self.job_id, "alice")["media_ready"])
            second = self.create()
            self.assertNotEqual(first["id"], second["id"])
            self.wait()
            self.assertEqual(len(self.fixture.engine.calls), 2)

    def test_legacy_generation_report_is_not_reused_even_with_current_input_digest(self):
        self.fixture.create()
        self.fixture.wait_report()
        job = self.store.get(self.job_id, "alice", private=True)
        previous_id = job["coaching"]["id"]
        job["coaching"]["generation_version"] = "retired-generation"
        self.store.update(self.job_id, coaching=job["coaching"])
        self.assertTrue(self.coaching.get(self.job_id, "alice")["stale"])
        self.create()
        self.wait()
        self.assertNotEqual(self.coaching.get(self.job_id, "alice")["id"], previous_id)
        self.assertEqual(len(self.fixture.engine.calls), 2)

    def test_report_failure_does_not_start_renderer_or_remove_previous_movie(self):
        self.create()
        self.wait()
        previous_path = self.manager.media_file(self.job_id, "alice")
        self.fixture.engine.failures_remaining = 1
        self.create(context={"goal": "新分析重点"})
        state = self.wait("failed")
        self.assertTrue(state["media_ready"])
        self.assertEqual(len(self.renderer.calls), 1)
        self.assertEqual(self.manager.media_file(self.job_id, "alice"), previous_path)

    def test_stopping_shared_report_cancels_pending_template_only(self):
        self.fixture.engine.release.clear()
        self.fixture.create()
        self.create()
        self.assertTrue(self.fixture.engine.started.wait(2))
        self.coaching.cancel(self.job_id, "alice")
        self.assertEqual(self.wait("cancelled")["status"], "cancelled")
        self.fixture.engine.release.set()
        self.fixture.wait_worker_idle()
        self.wait_idle()
        self.assertEqual(self.renderer.calls, [])

    def test_whole_job_delete_cancels_worker_before_removing_directory(self):
        self.renderer.release.clear()
        self.create()
        self.assertTrue(self.renderer.started.wait(2))
        self.store.request_delete(self.job_id, "alice")
        receipt = self.store.process_delete(self.job_id)
        self.assertEqual(receipt["state"], "completed")
        self.wait_idle()
        self.assertFalse(self.store._path(self.job_id).parent.exists())
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_restart_marks_interrupted_task_failed_without_starting_cloud_or_renderer(self):
        self.store.update(self.job_id, template_video={"id": "interrupted", "status": "running",
                                                      "template_version": TEMPLATE_VERSION})
        other = TemplateVideoManager(self.store, self.coaching, planner=self.manager.planner, renderer=self.renderer)
        try:
            self.assertEqual(other.get(self.job_id, "alice")["status"], "failed")
            self.assertIsNone(other._thread)
            self.assertEqual(self.fixture.engine.calls, [])
            self.assertEqual(self.renderer.calls, [])
        finally:
            other.close()
            self.store.template_manager = self.manager


if __name__ == "__main__":
    unittest.main()
