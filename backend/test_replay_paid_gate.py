"""Cost boundary regressions use constructed video and never cloud credentials."""
import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from core.climb_replay import (AliyunReplayAnalyzer, ReplayAnalyzerBase, ClimbReplayManager, ClimbReplayStore,
                               ReplayHoldPoint, REPLAY_CONSENT_VERSION, VideoInfo,
                               holds_revision)
from test_climb_replay import FakeAnalyzer, FailingAnalyzer


class PaidGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        source = root / "constructed.mp4"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (120, 100))
        if not writer.isOpened():
            self.skipTest("MP4 encoder unavailable")
        frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
        cv2.rectangle(frame, (42, 82), (59, 96), (170, 125, 20), -1)
        cv2.rectangle(frame, (16, 30), (32, 44), (170, 125, 20), -1)
        for _ in range(8):
            writer.write(frame)
        writer.release()
        self.info = VideoInfo(120, 100, 4, 8, 2, source.stat().st_size)
        self.store = ClimbReplayStore(root / "store")
        self.job = self.store.create(owner="alice", route_id=None, route_color="青色",
                                     source=source, original_name="constructed.mp4", info=self.info,
                                     consent={"event": "granted", "attempt": 1, "version": REPLAY_CONSENT_VERSION},
                                     retention_mode="keep_private_original")
        self.job_id = self.job["id"]
        self.source = self.store.jobs / self.job_id / "input.mp4"
        self.draft = {"holds": [{"id": 1, "bbox": [.13, .3, .14, .15]}],
                      "hold_evidence": {"reference_frame": 0}, "hold_candidates": [],
                      "models": {"holds": "constructed"}, "route": {"color": "青色"}}
        self.store.update(self.job_id, status="awaiting_hold_review", hold_draft=self.draft)
        self.point = ReplayHoldPoint(point_xy=[50 / 120, .9], time_seconds=0)
        self.consent = {"event": "granted", "version": REPLAY_CONSENT_VERSION}

    def tearDown(self):
        self.temp.cleanup()

    def confirm(self):
        revision = self.store.get(self.job_id)["holds_revision"]
        return self.store.confirm_all_holds(self.job_id, "alice", revision)

    def test_local_detection_never_initializes_sdk_and_accepts_empty_draft(self):
        analyzer = AliyunReplayAnalyzer(access_key_id="", access_key_secret="")
        with patch.object(analyzer, "_client", side_effect=AssertionError("no SDK before confirmation")), \
             patch.object(analyzer, "_request_pose", side_effect=AssertionError("no pose")), \
             patch.object(analyzer, "_video_holds", return_value=([], [], {"reference_frame": 0}, None, "local")):
            draft = analyzer.detect_holds(self.source, route_color="青色", video_info=self.info,
                                          progress=lambda *_: None, cancelled=lambda: False)
            self.assertEqual(draft["holds"], [])
            with self.assertRaises(RuntimeError):
                analyzer.analyze(self.source, route_color="青色", video_info=self.info,
                                 progress=lambda *_: None, cancelled=lambda: False, telemetry=lambda *_: None)

    def test_preview_local_add_and_undo_never_confirm_global_set_or_call_cloud(self):
        with patch.object(AliyunReplayAnalyzer, "_request_pose", side_effect=AssertionError("no cloud")), \
             patch.object(AliyunReplayAnalyzer, "analyze", side_effect=AssertionError("no full analysis")), \
             patch("core.climb_replay.render_replay_overlay_video", side_effect=AssertionError("no pre-pose rendering")):
            before = self.store.get(self.job_id)
            self.store.preview_hold_at_point(self.job_id, "alice", self.point)
            self.assertEqual(self.store.get(self.job_id), before)
            added = self.store.add_hold_at_point(self.job_id, "alice", self.point)
            self.assertEqual(len(added["hold_draft"]["holds"]), 2)
            self.assertIsNone(added["holds_confirmation"])
            with self.assertRaises(HTTPException):
                self.store.start_paid_analysis(self.job_id, "alice", self.consent)
            undone = self.store.undo_last_clicked_hold(self.job_id, "alice")
            self.assertEqual(len(undone["hold_draft"]["holds"]), 1)
            self.assertEqual(undone["analysis_runs"], [])

    def test_delete_invalidates_confirmation_and_stale_confirmation_is_rejected(self):
        confirmed = self.confirm()
        old_revision = confirmed["holds_revision"]
        deleted = self.store.remove_hold(self.job_id, "alice", 1)
        self.assertIsNone(deleted["holds_confirmation"])
        self.assertEqual(deleted["hold_draft"]["holds"], [])
        with self.assertRaises(HTTPException):
            self.store.start_paid_analysis(self.job_id, "alice", self.consent)
        with self.assertRaises(HTTPException):
            self.store.confirm_all_holds(self.job_id, "alice", old_revision)
        added = self.store.add_hold_at_point(self.job_id, "alice", self.point)
        with self.assertRaises(HTTPException) as stale:
            self.store.confirm_all_holds(self.job_id, "alice", old_revision)
        self.assertEqual(stale.exception.status_code, 409)
        self.assertNotEqual(added["holds_revision"], old_revision)

    def test_restart_waiting_for_review_never_runs_pose_analysis(self):
        restored = ClimbReplayStore(self.store.root)
        analyzer = FakeAnalyzer()
        with patch.object(analyzer, "analyze", side_effect=AssertionError("must wait for user")) as paid:
            manager = ClimbReplayManager(restored, analyzer)
            try:
                time.sleep(.1)
                paid.assert_not_called()
                self.assertEqual(restored.get(self.job_id)["status"], "awaiting_hold_review")
            finally:
                manager.close()

    def test_no_holds_after_deletion_cannot_be_reported_as_completion(self):
        records = [{"frame_id": 0, "kpts_xy": [[0, 0]] * 17, "kpts_score": [0] * 17}]
        attempt = AliyunReplayAnalyzer._contacts(records, [], 4)
        self.assertFalse(attempt["topped_out"])
        self.assertIsNone(attempt["completion_frame"])

    def test_worker_failure_preserves_safe_diagnostic_and_local_retry_recovers_draft(self):
        analyzer = FakeAnalyzer()
        manager = ClimbReplayManager(self.store, analyzer)
        try:
            with patch.object(manager, "_execute", side_effect=NameError("private provider details", name="missing_symbol")), \
                 patch("core.climb_replay.logging.getLogger") as logger:
                self.store.update(self.job_id, status="queued")
                manager.enqueue(self.job_id)
                deadline = time.monotonic() + 2
                while self.store.get(self.job_id)["status"] != "failed" and time.monotonic() < deadline:
                    time.sleep(.01)
                failed = self.store.get(self.job_id, private=True)
                self.assertEqual(failed["error_code"], "worker_failed")
                self.assertEqual(failed["worker_failure"]["exception_type"], "NameError")
                self.assertEqual(failed["worker_failure"]["identifier"], "missing_symbol")
                self.assertNotIn("private provider details", str(failed["worker_failure"]))
                self.assertNotIn("worker_failure", self.store.get(self.job_id))
                logger.return_value.error.assert_called_once()
            with patch.object(analyzer, "analyze", side_effect=AssertionError("no paid retry")) as paid, \
                 patch.object(analyzer, "detect_holds", side_effect=AssertionError("keep existing draft")) as detect:
                self.store.retry(self.job_id, "alice", {**self.consent, "attempt": 2})
                manager.enqueue(self.job_id)
                deadline = time.monotonic() + 2
                while self.store.get(self.job_id)["status"] != "awaiting_hold_review" and time.monotonic() < deadline:
                    time.sleep(.01)
                restored = self.store.get(self.job_id, private=True)
                self.assertEqual(restored["status"], "awaiting_hold_review")
                self.assertEqual(restored["hold_draft"], self.draft)
                self.assertIsNone(restored.get("worker_failure"))
                self.assertIsNone(restored["paid_analysis_request"])
                self.assertEqual(restored["analysis_runs"], [])
                paid.assert_not_called()
                detect.assert_not_called()
        finally:
            manager.close()

    def test_legacy_queued_grant_and_retry_cannot_bypass_paid_gate(self):
        self.store.update(self.job_id, status="queued", hold_draft=None)
        analyzer = FakeAnalyzer()
        with patch.object(analyzer, "analyze", side_effect=AssertionError("old grant is insufficient")) as paid:
            manager = ClimbReplayManager(self.store, analyzer)
            try:
                deadline = time.monotonic() + 2
                while self.store.get(self.job_id)["status"] != "awaiting_hold_review" and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(self.store.get(self.job_id)["status"], "awaiting_hold_review")
                self.confirm()
                self.store.update(self.job_id, status="failed")
                self.store.retry(self.job_id, "alice", {**self.consent, "attempt": 2})
                manager._execute(self.job_id)
                paid.assert_not_called()
                self.assertIsNone(self.store.get(self.job_id)["holds_confirmation"])
            finally:
                manager.close()

    def test_post_analysis_delete_reuses_pose_samples_and_paid_rerun_preserves_edits(self):
        result = copy.deepcopy(self.draft)
        result["pose_samples"] = [{"sample_index": i, "source_frame_id": i,
                                   "observed": True, "wall_alignment": "aligned",
                                   "kpts_xy": [[0, 0]] * 17, "kpts_score": [1] * 17,
                                   "time_seconds": i / 4} for i in range(4)]
        result["analysis"] = {"sampling": {"effective_fps": 4}}
        self.store.update(self.job_id, status="succeeded", result=result)

        def render(_, target, __):
            target.write_bytes(b"constructed-overlay")
            return {"rendered": True}

        with patch.object(AliyunReplayAnalyzer, "_request_pose", side_effect=AssertionError("no cloud")), \
             patch.object(AliyunReplayAnalyzer, "analyze", side_effect=AssertionError("no full analysis")), \
             patch("core.climb_replay.render_replay_overlay_video", side_effect=render) as rendering, \
             patch.object(ReplayAnalyzerBase, "_contacts", wraps=ReplayAnalyzerBase._contacts) as contacts:
            added = self.store.add_hold_at_point(self.job_id, "alice", self.point)
            deleted = self.store.remove_hold(self.job_id, "alice", 1)
            self.assertEqual(deleted["result"], result)
            self.assertEqual(len(deleted["hold_edit_draft"]["holds"]), 1)
            self.assertEqual(deleted["analysis_runs"], [])
            self.assertEqual(added["hold_edit_draft"]["hold_review_version"], 1)
            rendering.assert_not_called()
            contacts.assert_not_called()
            confirmed = self.confirm()
            self.assertEqual(rendering.call_count, 1)
            self.assertEqual(contacts.call_count, 1)
            self.assertIsNone(confirmed["hold_edit_draft"])
            self.assertEqual(confirmed["result"]["pose_samples"], result["pose_samples"])
            self.assertEqual(confirmed["result"]["holds"], deleted["hold_edit_draft"]["holds"])
            self.confirm()
            self.assertEqual(rendering.call_count, 1, "unchanged confirmed holds must not be analyzed twice")
            queued = self.store.start_paid_analysis(self.job_id, "alice", self.consent)
            self.assertEqual(queued["hold_draft"]["holds"], deleted["hold_edit_draft"]["holds"])
            self.assertEqual(queued["holds_confirmation"]["revision"], holds_revision(queued["hold_draft"]))
            with self.assertRaises(HTTPException):
                self.store.start_paid_analysis(self.job_id, "alice", self.consent)

    def run_paid_rerun(self, analyzer):
        original = copy.deepcopy(self.draft)
        self.store.update(self.job_id, status="succeeded", result=original)
        # Use the application's canonical filename rather than a test-only path.
        from core.climb_replay import REPLAY_OVERLAY_FILENAME
        base_overlay = self.source.with_name(REPLAY_OVERLAY_FILENAME)
        base_overlay.write_bytes(b"previous-complete-video")
        self.store.register_overlay(self.job_id, original)
        self.confirm()
        self.store.start_paid_analysis(self.job_id, "alice", self.consent)
        # A synchronous worker avoids any additional queued execution in this test.
        manager = ClimbReplayManager.__new__(ClimbReplayManager)
        manager.store, manager.analyzer, manager._stop = self.store, analyzer, threading.Event()
        manager._execute(self.job_id)
        self.assertEqual(base_overlay.read_bytes(), b"previous-complete-video")
        self.assertEqual(len(list(self.source.parent.glob("analysis-before-*.json"))), 1)
        return self.store.get(self.job_id), original

    def test_multiple_points_and_undo_survive_restart_and_analyze_only_after_global_confirmation(self):
        result = copy.deepcopy(self.draft)
        result["holds"] = []
        result["pose_samples"] = [{"sample_index": 0, "source_frame_id": 0,
                                   "observed": False, "time_seconds": 0}]
        self.store.update(self.job_id, status="succeeded", result=result)
        with patch.object(AliyunReplayAnalyzer, "_request_pose", side_effect=AssertionError("no cloud")), \
             patch.object(AliyunReplayAnalyzer, "analyze", side_effect=AssertionError("no paid analysis")), \
             patch.object(ReplayAnalyzerBase, "_contacts", wraps=ReplayAnalyzerBase._contacts) as contacts, \
             patch("core.climb_replay.render_replay_overlay_video", side_effect=AssertionError("no per-point render")) as rendered:
            first = self.store.add_hold_at_point(self.job_id, "alice", self.point)
            second = self.store.add_hold_at_point(self.job_id, "alice", ReplayHoldPoint(point_xy=[.2, .37], time_seconds=0))
            self.assertEqual(len(second["hold_edit_draft"]["holds"]), 2)
            undone = self.store.undo_clicked_hold(self.job_id, "alice", 1)
            self.assertEqual(len(undone["hold_edit_draft"]["holds"]), 1)
            self.assertEqual(undone["result"], result)
            rendered.assert_not_called()
            contacts.assert_not_called()
            self.store = ClimbReplayStore(self.store.root)
            restored = self.store.get(self.job_id)
            self.assertEqual(restored["hold_edit_draft"], undone["hold_edit_draft"])
            self.assertTrue(restored["holds_pending_local_analysis"])
            with self.assertRaises(HTTPException) as stale:
                self.store.confirm_all_holds(self.job_id, "alice", first["holds_revision"])
            self.assertEqual(stale.exception.status_code, 409)
            with self.assertRaises(HTTPException):
                self.store.start_paid_analysis(self.job_id, "alice", self.consent)
            with self.assertRaises(AssertionError):
                self.confirm()
            failed = self.store.get(self.job_id)
            self.assertEqual(failed["result"], result)
            self.assertEqual(failed["hold_edit_draft"], restored["hold_edit_draft"])
            self.assertIsNone(failed["holds_confirmation"])
            self.assertNotIn(self.job_id, self.store._active_hold_renders)

        def render(_, target, __):
            target.write_bytes(b"single-batch-overlay")
            return {"rendered": True}

        with patch("core.climb_replay.render_replay_overlay_video", side_effect=render) as rendered:
            confirmed = self.confirm()
            self.assertEqual(rendered.call_count, 1)
            self.assertFalse(confirmed["holds_pending_local_analysis"])
            self.assertEqual(confirmed["result"]["holds"], restored["hold_edit_draft"]["holds"])

    def test_full_paid_rerun_keeps_base_video_and_uses_new_output(self):
        job, _ = self.run_paid_rerun(FakeAnalyzer())
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["analysis_runs"][-1]["state"], "succeeded")
        self.assertEqual(job["media"]["overlay_video"]["status"], "available")
        new = job["media"]["reviewed_overlay_video"]
        self.assertEqual(new["status"], "available")
        self.assertTrue((self.source.parent / new["storage_name"]).is_file())

    def test_failed_paid_rerun_preserves_previous_analysis_and_playable_video(self):
        job, original = self.run_paid_rerun(FailingAnalyzer())
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"], original)
        self.assertEqual(job["analysis_runs"][-1]["state"], "failed")
        self.assertEqual(job["media"]["overlay_video"]["status"], "available")
        self.assertIn("保留原复盘", job["stage"])


if __name__ == "__main__":
    unittest.main()
