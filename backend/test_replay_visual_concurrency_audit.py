"""Deterministic regression checks for visual/store lock ordering and cleanup."""
import copy
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.climb_replay import REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, probe_video
import test_replay_visual_integration as visual_fixture


class VisualReplayConcurrencyAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = visual_fixture.VisualReplayIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.manager, self.job_id = self.fixture.create_succeeded()

    def test_hold_video_render_keeps_other_job_reads_and_writes_responsive(self):
        store, job_id = self.store, self.job_id
        before = store.get(job_id, private=True)
        result = copy.deepcopy(before["result"])
        result["hold_candidates"] = [{"bbox": [.8, .7, .08, .08],
            "polygon": [[.8, .7], [.88, .7], [.88, .78], [.8, .78]],
            "contour_source": "climbing_model_native_mask", "appearances": 3}]
        result["pose_samples"] = [{"sample_index": index, "source_frame_id": index,
            "observed": False, "kpts_xy": [[0, 0]] * 17, "kpts_score": [0] * 17,
            "time_seconds": index / 24} for index in range(6)]
        store.update(job_id, result=result)
        source = self.fixture.root / "second.mp4"
        visual_fixture.sample_video(source)
        other = store.create(owner="bob", route_id=None, route_color="蓝色", source=source,
                             original_name="second.mp4", info=probe_video(source), consent={},
                             retention_mode="keep_private_original")
        entered, release, accessed = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def render(_source, target, _result, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test release timed out")
            target.write_bytes(b"synthetic-reviewed-media")
            return {"rendered": True}

        def review():
            try:
                store.promote_hold_candidate(job_id, "alice", 0)
            except Exception as exc:
                errors.append(exc)

        def access():
            try:
                store.get(other["id"], "bob")
                store.update(other["id"], stage="other job remains responsive")
                accessed.set()
            except Exception as exc:
                errors.append(exc)

        with patch("core.climb_replay.render_replay_overlay_video", side_effect=render):
            rendering = threading.Thread(target=review)
            rendering.start()
            self.assertTrue(entered.wait(5))
            accessor = threading.Thread(target=access)
            accessor.start()
            responsive_during_render = accessed.wait(.5)
            release.set()
            rendering.join(5)
            accessor.join(5)
        self.assertTrue(responsive_during_render, "hold render held the global store lock while waiting")
        self.assertEqual(errors, [])
        self.assertFalse(rendering.is_alive())
        self.assertFalse(accessor.is_alive())

    def test_cleanup_reloads_pointer_before_removing_obsolete_visual_video(self):
        store, job_id = self.store, self.job_id
        job = store.get(job_id, private=True)
        directory = store._path(job_id).parent
        old = directory / ("overlay-visual-" + "1" * 32 + ".webm")
        new = directory / ("overlay-visual-" + "2" * 32 + ".webm")
        old.write_bytes(b"old synthetic output")
        media = copy.deepcopy(job["media"])
        media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND] = {"status": "available", "storage_name": old.name}
        store.update(job_id, media=media)
        original = Path.read_text
        triggered = False
        committed = threading.Event()
        committers = []

        def read_then_commit(path, *args, **kwargs):
            nonlocal triggered
            text = original(path, *args, **kwargs)
            if path == store._path(job_id) and not triggered:
                triggered = True
                latest_media = copy.deepcopy(media)
                latest_media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND]["storage_name"] = new.name
                def commit():
                    with store._lock:
                        new.write_bytes(b"new synthetic output")
                        store.update(job_id, media=latest_media)
                        old.unlink(missing_ok=True)
                    committed.set()
                committer = threading.Thread(target=commit)
                committers.append(committer)
                committer.start()
                committed.wait(.2)
            return text

        with patch.object(Path, "read_text", read_then_commit):
            store.cleanup_due_media()
        for committer in committers:
            committer.join(3)
        self.assertTrue(committed.is_set())
        self.assertTrue(new.exists(), "cleanup removed the newly committed current media")
        self.assertFalse(old.exists())

    def test_progress_does_not_revive_render_after_input_review(self):
        store, manager, job_id = self.store, self.manager, self.job_id
        store.request_visual_retry(job_id, "alice")
        original_get = store.get
        reads = 0
        reviewed = threading.Event()
        reviewers = []

        def read_then_review(*args, **kwargs):
            nonlocal reads
            snapshot = original_get(*args, **kwargs)
            reads += 1
            if reads == 2:
                changed = copy.deepcopy(snapshot["result"])
                changed["holds"][0]["bbox"][0] += .01
                changed["visual_replay"].update(status="stale", stale=True)
                def review():
                    store.update(job_id, result=changed)
                    reviewed.set()
                reviewer = threading.Thread(target=review)
                reviewers.append(reviewer)
                reviewer.start()
                # If progress owns the lock, the review waits until its update
                # finishes. Otherwise this opens the actual former race window.
                reviewed.wait(.2)
            return snapshot

        def interrupted(*args, **kwargs):
            if not reviewed.wait(3):
                raise RuntimeError("test review timed out")
            raise InterruptedError("review changed")

        with patch.object(store, "get", side_effect=read_then_review), patch(
                "core.climb_replay.render_replay_overlay_video", side_effect=interrupted):
            manager._execute_visual(job_id)
        for reviewer in reviewers:
            reviewer.join(3)
        self.assertTrue(reviewed.is_set())
        self.assertEqual(original_get(job_id, private=True)["result"]["visual_replay"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
