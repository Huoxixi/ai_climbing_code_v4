"""Local media integration tests; no model, user media, network, or credentials."""
import copy
import json
import os
import tempfile
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from core.climb_replay import (
    ClimbReplayManager, ClimbReplayStore, ReplayCancelled, ReplaySegmentReview,
    REPLAY_REFERENCE_FILENAME, REPLAY_REFERENCE_MEDIA_KIND, REPLAY_OVERLAY_MEDIA_KIND,
    REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, probe_video, render_replay_overlay_video,
    visual_input_version,
)
from core.replay_resources import VisualRenderFailure
from core.replay_visual_renderer import render_visual_tail


def local_worker(reference, manifest, output, metrics, **kwargs):
    return render_visual_tail(reference, json.loads(manifest.read_text(encoding="utf-8")), output,
                              cancelled=kwargs.get("cancelled"))


def sample_video(path, *, fps=24, size=(160, 96)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not writer.isOpened():
        raise unittest.SkipTest("MP4 encoder unavailable")
    frame = np.full((size[1], size[0], 3), (80, 95, 108), np.uint8)
    cv2.rectangle(frame, (size[0] // 4, size[1] // 2),
                  (size[0] // 4 + 15, size[1] // 2 + 10), (150, 170, 60), -1)
    for index in range(6):
        writer.write(frame)
    writer.release()


def evidence(path):
    return {"video": asdict(probe_video(path)), "hold_evidence": {"reference_frame": 0},
            "holds": [{"id": 1, "saved_object_id": "h1", "bbox": [.25, .5, .1, .1],
                       "polygon": [[.25, .5], [.35, .5], [.35, .6], [.25, .6]]},
                      {"id": 2, "saved_object_id": "h2", "bbox": [.6, .2, .1, .1],
                       "polygon": [[.6, .2], [.7, .2], [.7, .3], [.6, .3]]}],
            "pose_samples": [], "attempt": {"contacts": [
                {"hold_id": 1, "limb": "left_hand", "start_source_frame": 0,
                 "end_source_frame": 2, "start_time_seconds": 0},
                {"hold_id": 2, "limb": "left_hand", "start_source_frame": 3,
                 "end_source_frame": 5, "start_time_seconds": 3 / probe_video(path).fps}],
                "segments": [{"id": "left_hand:1:2", "limb": "left_hand",
                              "start_time_seconds": 0, "end_time_seconds": .2}]}}


class VisualReplayIntegrationTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, {"CLIMB_REPLAY_VISUAL_ENABLED": "1"})
        settings.start()
        self.addCleanup(settings.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def create_succeeded(self):
        source = self.root / "source.mp4"
        sample_video(source)
        store = ClimbReplayStore(self.root / "store")
        job = store.create(owner="alice", route_id="route", route_color="蓝色", source=source,
                           original_name="sample.mp4", info=probe_video(source), consent={},
                           retention_mode="keep_private_original")
        stored = store.get(job["id"], private=True)
        source = Path(stored["input_path"])
        result = evidence(source)
        with patch("core.climb_replay.run_visual_worker", side_effect=local_worker):
            result["overlay"] = render_replay_overlay_video(source, source.with_name("overlay.webm"), result)
        store.register_overlay(job["id"], result)
        store.update(job["id"], status="succeeded", result=result, route_hold_ids=["h1", "h2"])
        manager = ClimbReplayManager.__new__(ClimbReplayManager)
        manager.store, manager._stop = store, threading.Event()
        manager.analyzer = object()  # Any inference access fails the local retry test.
        return store, manager, job["id"]

    def test_tail_and_body_have_one_frame_rate_and_correct_boundaries(self):
        for fps, size in ((24, (160, 96)), (30, (96, 160))):
            with self.subTest(fps=fps):
                source, target = self.root / f"input-{fps}.mp4", self.root / f"out-{fps}.webm"
                sample_video(source, fps=fps, size=size)
                result = evidence(source)
                with patch("core.climb_replay.run_visual_worker", side_effect=local_worker):
                    overlay = render_replay_overlay_video(source, target, result)
                actual = probe_video(target)
                self.assertEqual(actual.frame_count, 6 + fps * 8)
                self.assertEqual(actual.fps, fps)
                self.assertEqual((actual.width, actual.height), size)
                self.assertEqual(overlay["analysis_frame_count"], 6)
                self.assertEqual(result["visual_replay"]["tail_start_seconds"], 6 / fps)
                self.assertAlmostEqual(result["visual_replay"]["total_duration_seconds"], actual.frame_count / fps)
                self.assertEqual(result["video"]["frame_count"], 6)
                self.assertEqual(result["visual_reference"]["coordinate_version"], "normalized_reference_v1")
                self.assertFalse(list(self.root.glob(".visual-*")))

    def test_tail_timeout_returns_valid_basic_replay(self):
        source, target = self.root / "input.mp4", self.root / "out.webm"
        sample_video(source)
        result = evidence(source)
        with patch("core.climb_replay.run_visual_worker", side_effect=VisualRenderFailure("timeout", "timeout")):
            render_replay_overlay_video(source, target, result)
        self.assertEqual(probe_video(target).frame_count, 6)
        self.assertEqual(result["visual_replay"]["status"], "failed")
        self.assertEqual(result["visual_replay"]["failure_reason"], "timeout")

    def test_cancel_does_not_replace_existing_media_or_leave_temporary_tail(self):
        source, target = self.root / "input.mp4", self.root / "out.webm"
        sample_video(source)
        target.write_bytes(b"previous-playable-version")
        with patch("core.climb_replay.run_visual_worker", side_effect=InterruptedError("cancelled")):
            with self.assertRaises(ReplayCancelled):
                render_replay_overlay_video(source, target, evidence(source))
        self.assertEqual(target.read_bytes(), b"previous-playable-version")
        self.assertFalse(list(self.root.glob(".visual-*")))

    def test_failed_retry_preserves_previous_media_and_analysis(self):
        store, manager, job_id = self.create_succeeded()
        before = store.get(job_id, private=True)
        original = Path(before["input_path"]).with_name("overlay.webm").read_bytes()
        store.request_visual_retry(job_id, "alice")
        with patch("core.climb_replay.run_visual_worker", side_effect=VisualRenderFailure("timeout", "timeout")):
            manager._execute_visual(job_id)
        after = store.get(job_id, private=True)
        self.assertEqual(after["status"], "succeeded")
        self.assertEqual(after["media"], before["media"])
        self.assertEqual(after["result"]["attempt"], before["result"]["attempt"])
        self.assertEqual(after["result"]["visual_replay"]["tail_frame_count"], 192)
        self.assertEqual(Path(before["input_path"]).with_name("overlay.webm").read_bytes(), original)
        self.assertFalse(list(store._path(job_id).parent.glob("overlay-visual-*")))

    def test_historical_retry_uses_analysis_body_without_reappending_old_tail(self):
        store, manager, job_id = self.create_succeeded()
        before = store.get(job_id, private=True)
        media = copy.deepcopy(before["media"])
        media["source_video"]["status"] = "deleted"
        store.update(job_id, media=media)  # Simulate independently retained valid derivative.
        Path(before["input_path"]).unlink()
        store.request_visual_retry(job_id, "alice")
        with patch("core.climb_replay.run_visual_worker", side_effect=local_worker):
            manager._execute_visual(job_id)
        after = store.get(job_id, private=True)
        path, _ = store.media_file(job_id, "alice", REPLAY_REVIEWED_OVERLAY_MEDIA_KIND)
        self.assertEqual(probe_video(path).frame_count, 6 + 192)
        self.assertEqual(after["result"]["visual_replay"]["status"], "ready")
        self.assertEqual(after["analysis_runs"], before["analysis_runs"])
        with self.assertRaises(HTTPException):
            store.media_file(job_id, "bob", REPLAY_REFERENCE_MEDIA_KIND)

    def test_input_change_during_render_prevents_late_commit(self):
        store, manager, job_id = self.create_succeeded()
        store.request_visual_retry(job_id, "alice")

        def change_input(*args, **kwargs):
            current = store.get(job_id, private=True)
            changed = copy.deepcopy(current["result"])
            changed["holds"][0]["bbox"][0] = .28
            changed["visual_replay"].update(status="stale", stale=True)
            store.update(job_id, result=changed)
            raise InterruptedError("input changed")

        with patch("core.climb_replay.run_visual_worker", side_effect=change_input):
            manager._execute_visual(job_id)
        after = store.get(job_id, private=True)
        self.assertEqual(after["result"]["visual_replay"]["status"], "stale")
        self.assertEqual(after["result"]["holds"][0]["bbox"][0], .28)
        self.assertNotIn(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, after["media"])
        self.assertFalse(list(store._path(job_id).parent.glob("overlay-visual-*")))

    def test_review_invalidates_tail_and_preserves_stale_flag_across_failure(self):
        store, manager, job_id = self.create_succeeded()
        before = store.get(job_id, private=True)
        review = ReplaySegmentReview(limb="left_hand", source_route_hold_id="h1", target_route_hold_id="h2",
                                     start_time_seconds=.01, end_time_seconds=.16)
        changed = store.review_segment(job_id, "alice", "left_hand:1:2", review)
        self.assertTrue(changed["result"]["visual_replay"]["stale"])
        self.assertNotEqual(visual_input_version(changed["result"]), visual_input_version(before["result"]))
        store.request_visual_retry(job_id, "alice")
        with patch("core.climb_replay.run_visual_worker", side_effect=InterruptedError("cancelled")):
            manager._execute_visual(job_id)
        self.assertTrue(store.get(job_id)["result"]["visual_replay"]["stale"])

    def test_source_expiry_cleans_reference_and_disables_retry(self):
        store, _, job_id = self.create_succeeded()
        path = store._path(job_id).parent / REPLAY_REFERENCE_FILENAME
        self.assertTrue(path.is_file())
        store.delete_media(job_id, "alice", "source_video")
        self.assertFalse(path.exists())
        unavailable = store.request_visual_retry(job_id, "alice")
        self.assertEqual(unavailable["result"]["visual_replay"]["status"], "unavailable")
        self.assertFalse(unavailable["result"]["visual_replay"]["can_retry"])

    def test_disabled_visual_keeps_existing_resolution_and_does_not_freeze_reference(self):
        source, target = self.root / "wide.mp4", self.root / "wide.webm"
        sample_video(source, size=(1344, 800))
        result = evidence(source)
        with patch.dict(os.environ, {"CLIMB_REPLAY_VISUAL_ENABLED": "0"}), \
                patch("core.climb_replay.run_visual_worker") as worker:
            render_replay_overlay_video(source, target, result)
        self.assertEqual(probe_video(target).width, 1344)
        self.assertEqual(probe_video(target).frame_count, 6)
        worker.assert_not_called()
        self.assertFalse((self.root / REPLAY_REFERENCE_FILENAME).exists())
        self.assertEqual(result["visual_replay"]["status"], "disabled")

    def test_recovery_queue_is_bounded_and_duplicate_enqueues_are_atomic(self):
        import queue
        manager = ClimbReplayManager.__new__(ClimbReplayManager)
        manager._queue, manager._queued, manager._queue_lock = queue.Queue(maxsize=8), set(), threading.Lock()
        threads = [threading.Thread(target=manager.enqueue, args=("samejob",)) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
        self.assertEqual(manager._queue.qsize(), 1)
        for index in range(30):
            manager.enqueue(str(index))
        self.assertEqual(manager._queue.qsize(), 8)
        self.assertEqual(len(manager._queued), 8)

    def test_visual_version_change_stays_stale_if_regeneration_fails(self):
        store, manager, job_id = self.create_succeeded()
        job = store.get(job_id, private=True)
        job["result"]["visual_replay"]["visual_version"] = "previous-visual-version"
        store.update(job_id, result=job["result"])
        self.assertEqual(store.get(job_id)["result"]["visual_replay"]["status"], "stale")
        queued = store.request_visual_retry(job_id, "alice")
        self.assertTrue(queued["result"]["visual_replay"]["stale"])
        with patch("core.climb_replay.run_visual_worker", side_effect=VisualRenderFailure("timeout", "timeout")):
            manager._execute_visual(job_id)
        self.assertTrue(store.get(job_id)["result"]["visual_replay"]["stale"])


if __name__ == "__main__":
    unittest.main()
