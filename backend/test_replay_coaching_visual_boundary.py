"""Synthetic extended media proves both coaching passes exclude the animation."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from core.replay_coaching import CoachingManager
from core.replay_coaching_engine import (
    CoachingEngine, CoachingEngineError, _local_frames, _sample_frames,
    analysis_frame_count,
)
from test_replay_coaching_engine import write_video


class ReplayCoachingVisualBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coaching-visual-boundary-")
        self.path = Path(self.temp.name) / "synthetic-extended.avi"
        write_video(self.path, count=130)
        self.job = {"video": {"duration_seconds": 5, "fps": 10}, "result": {"visual_replay": {
            "status": "ready", "analysis_frame_count": 50, "analysis_duration_seconds": 5,
            "tail_start_seconds": 5, "tail_duration_seconds": 8, "total_duration_seconds": 13,
        }}}

    def tearDown(self):
        self.temp.cleanup()

    def test_overview_and_focus_never_read_compressed_visual_time(self):
        self.job["reviewed_segments"] = [{"start_time_seconds": 4, "end_time_seconds": 12}]
        frames, duration, _ = _sample_frames(self.path, self.job,
            {"focus_start_seconds": 9, "focus_end_seconds": 12}, lambda: False)
        self.assertAlmostEqual(duration, 4.9)
        self.assertEqual(frames[-1]["frame_id"], "frame-49")
        self.assertTrue(all(frame["time_seconds"] < 5 for frame in frames))

    def test_independent_review_padding_stops_before_first_animation_frame(self):
        frames, windows = _local_frames(self.path, [
            {"id": "last-action", "start_seconds": 4.7, "end_seconds": 4.9},
            {"id": "invalid-tail", "start_seconds": 5, "end_seconds": 6},
        ], lambda: False, self.job)
        self.assertEqual(frames[-1]["frame_index"], 49)
        self.assertNotIn("invalid-tail", windows)
        self.assertTrue(windows["last-action"]["complete_event"])

    def test_readable_extended_media_preflight_returns_original_duration(self):
        manager = object.__new__(CoachingManager)
        manager.engine = CoachingEngine(provider=object())
        self.assertEqual(manager._validate_media(self.job, self.path, "overlay_video"), 5)
        with self.assertRaises(HTTPException):
            manager._validate_media(self.job, self.path, "source_video")

    def test_corrupt_missing_or_wrong_media_boundary_is_rejected(self):
        for changes in ({"analysis_frame_count": 131}, {"analysis_frame_count": 50.5},
                        {"analysis_duration_seconds": 13}, {"tail_start_seconds": 6},
                        {"total_duration_seconds": 12}, {"tail_duration_seconds": 9}):
            job = copy.deepcopy(self.job)
            job["result"]["visual_replay"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(CoachingEngineError):
                analysis_frame_count(job, 10, 130)
        with self.assertRaises(CoachingEngineError):
            analysis_frame_count({"video": {"duration_seconds": 5}}, 10, 130)

    def test_retry_stale_and_base_fallback_keep_the_same_real_boundary(self):
        for status in ("ready", "running", "failed", "stale", "cancelled"):
            self.job["result"]["visual_replay"]["status"] = status
            self.assertEqual(analysis_frame_count(self.job, 10, 130), 50)
            self.assertEqual(analysis_frame_count(self.job, 10, 50), 50)
        self.assertEqual(analysis_frame_count(self.job, 10, 50, "source_video"), 50)

    def test_visual_progress_does_not_invalidate_unchanged_analysis_evidence(self):
        manager = object.__new__(CoachingManager)
        manager.store = SimpleNamespace(_public=lambda job: job)
        manager.engine = SimpleNamespace(model="fixture")
        manager._knowledge_version = lambda: "fixture-knowledge"
        media = {"kind": "source_video", "checksum_sha256": "unchanged"}
        before = manager._evidence(self.job, media)
        self.job["result"]["visual_replay"].update(status="running", progress=55)
        self.job["result"]["visual_reference"] = {"visual_version": "next-render"}
        self.assertEqual(manager._evidence(self.job, media), before)
        self.assertNotEqual(manager._evidence(self.job, {**media, "checksum_sha256": "new"}), before)
        self.job["result"]["holds"] = [{"id": 3}]
        self.assertNotEqual(manager._evidence(self.job, media), before)

    def test_selected_old_overlay_uses_its_own_boundary_snapshot(self):
        old_visual = copy.deepcopy(self.job["result"]["visual_replay"])
        self.job["result"]["visual_replay"].update(tail_duration_seconds=10, total_duration_seconds=15)
        self.job["media"] = {"overlay_video": {"visual_replay": old_visual}}
        self.assertEqual(analysis_frame_count(self.job, 10, 130, "overlay_video"), 50)
        with self.assertRaises(CoachingEngineError):
            analysis_frame_count(self.job, 10, 130, "reviewed_overlay_video")
        self.job.pop("media")
        self.job["media_manifest"] = {"kind": "overlay_video", "visual_replay": old_visual}
        frames, duration, _ = _sample_frames(self.path, self.job, {}, lambda: False)
        self.assertEqual(frames[-1]["frame_id"], "frame-49")
        self.assertAlmostEqual(duration, 4.9)


if __name__ == "__main__":
    unittest.main()
