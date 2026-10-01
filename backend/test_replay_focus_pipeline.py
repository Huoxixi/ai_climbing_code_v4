"""Focused guarantees for private replay assembly and worker selection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import replay_resources as resources
from scripts import build_replay_focus_sample as pipeline


def storyboard():
    return {"schema_version": 1, "visual_version": "replay-focus-v1",
            "width": 64, "height": 80, "fps": 30, "duration_seconds": 1,
            "frame_count": 30, "shots": [{"id": "focus", "kind": "move",
                "start_seconds": 0, "duration_seconds": 1,
                "source_start_seconds": 0, "source_end_seconds": .5, "playback_rate": .5}]}


class StoryboardTests(unittest.TestCase):
    def setUp(self):
        self.video = {"width": 64, "height": 80, "fps": 30, "frame_count": 60}

    def test_contiguous_freeze_and_data_shots_are_allowed(self):
        manifest = storyboard()
        manifest["shots"].append({"id": "summary", "kind": "summary", "start_seconds": 1,
                                   "duration_seconds": 2})
        manifest.update(duration_seconds=3, frame_count=90)
        self.assertIs(pipeline.validate_storyboard(manifest, self.video), manifest)

    def test_gaps_out_of_source_bounds_and_nonfinite_times_are_rejected(self):
        for key, value in (("start_seconds", .1), ("source_end_seconds", 2),
                           ("source_start_seconds", float("nan")), ("playback_rate", 0)):
            with self.subTest(key=key):
                manifest = storyboard()
                manifest["shots"][0][key] = value
                with self.assertRaises(ValueError):
                    pipeline.validate_storyboard(manifest, self.video)

    def test_final_frame_count_and_duplicate_ids_are_not_silently_fixed(self):
        manifest = storyboard()
        manifest["frame_count"] = 29
        with self.assertRaises(ValueError):
            pipeline.validate_storyboard(manifest, self.video)
        manifest = storyboard()
        duplicate = copy.deepcopy(manifest["shots"][0])
        duplicate["start_seconds"] = 1
        manifest["shots"].append(duplicate)
        manifest.update(duration_seconds=2, frame_count=60)
        with self.assertRaisesRegex(ValueError, "unique"):
            pipeline.validate_storyboard(manifest, self.video)


class WorkerModuleTests(unittest.TestCase):
    def test_only_two_explicit_lightweight_workers_are_allowed(self):
        with patch.object(resources.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                resources.run_visual_worker("missing", "missing", "missing", "missing",
                                            worker_module="core.climb_replay")
            popen.assert_not_called()

    @unittest.skipIf(resources.psutil is None, "resource monitoring dependency unavailable")
    def test_default_worker_is_unchanged_and_focus_worker_uses_same_flags(self):
        class LaunchObserved(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference, manifest = directory / "input.mp4", directory / "manifest.json"
            reference.write_bytes(b"fixture")
            manifest.write_text("{}")
            for module in (None, "core.replay_focus_renderer"):
                with self.subTest(module=module), patch.object(resources.subprocess, "Popen", side_effect=LaunchObserved) as popen:
                    options = {"worker_module": module} if module else {}
                    with self.assertRaises(LaunchObserved):
                        resources.run_visual_worker(reference, manifest, directory / "tail.webm",
                                                    directory / "metrics.json", min_start_available_mib=0, **options)
                    command = popen.call_args.args[0]
                    self.assertEqual(command[2], module or "core.replay_visual_renderer")
                    self.assertEqual(command[3::2], ["--reference", "--manifest", "--output", "--metrics"])


@unittest.skipIf(resources.psutil is None, "resource monitoring dependency unavailable")
class AssemblyTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.baseline, self.tail = self.directory / "baseline.webm", self.directory / "tail.webm"
        for path, shade in ((self.baseline, 40), (self.tail, 180)):
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), 30, (64, 80))
            if not writer.isOpened():
                self.skipTest("VP8 unavailable")
            for i in range(6):
                writer.write(np.full((80, 64, 3), shade + i, dtype=np.uint8))
            writer.release()
        self.before = {p.name: pipeline.sha256(p) for p in (self.baseline, self.tail)}
        self.manifest = {"width": 64, "height": 80, "fps": 30, "frame_count": 6}

    def tearDown(self):
        self.temporary.cleanup()

    def test_full_streamed_assembly_retains_order_count_and_originals(self):
        import cv2
        output = self.directory / "combined.webm"
        with patch.object(pipeline.shutil, "which", return_value=None):
            metrics = pipeline.concat_videos(self.baseline, self.tail, output,
                                            baseline_info=pipeline.probe_video(self.baseline), manifest=self.manifest)
        self.assertEqual(metrics["frame_count"], 12)
        self.assertTrue(metrics["fully_decoded"])
        cap = cv2.VideoCapture(str(output))
        levels = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            levels.append(float(frame.mean()))
        cap.release()
        self.assertTrue(max(levels[:6]) < 80 < min(levels[6:]))
        self.assertEqual(self.before, {p.name: pipeline.sha256(p) for p in (self.baseline, self.tail)})

    def test_mid_assembly_cancel_removes_partial_and_releases_slot(self):
        output = self.directory / "combined.webm"
        checks = [0]

        def cancelled():
            checks[0] += 1
            return checks[0] >= 7

        with patch.object(pipeline.shutil, "which", return_value=None):
            with self.assertRaises(InterruptedError):
                pipeline.concat_videos(self.baseline, self.tail, output,
                                       baseline_info=pipeline.probe_video(self.baseline),
                                       manifest=self.manifest, cancelled=cancelled)
        self.assertFalse(output.exists())
        self.assertEqual(self.before, {p.name: pipeline.sha256(p) for p in (self.baseline, self.tail)})
        with resources.high_resource_slot():
            pass


class PublishingTests(unittest.TestCase):
    def test_failed_worker_keeps_previous_sample_and_original_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            evidence, output = project / ".tmp" / "evidence", project / ".tmp" / "focus"
            evidence.mkdir(parents=True)
            output.mkdir(parents=True)
            for name in ("input.mp4", "baseline.webm", "enhanced.webm"):
                (evidence / name).write_bytes(name.encode())
            (evidence / "result.json").write_text("{}")
            (output / "enhanced.webm").write_bytes(b"prior playable sample")
            review, script = project / "review.json", project / "storyboard.json"
            review.write_text("{}")
            script.write_text(json.dumps(storyboard()))
            before = {p.name: pipeline.sha256(p) for p in evidence.iterdir()}
            info = {"width": 64, "height": 80, "fps": 30, "frame_count": 60, "duration_seconds": 2}
            with patch.object(pipeline, "PROJECT", project), \
                 patch.object(pipeline, "probe_video", return_value=info), \
                 patch("core.replay_summary.build_replay_summary", return_value={}), \
                 patch.object(pipeline, "run_visual_worker", side_effect=RuntimeError("fixture failure")):
                with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                    pipeline.build_sample(evidence, output, review, script)
            self.assertEqual((output / "enhanced.webm").read_bytes(), b"prior playable sample")
            self.assertEqual(before, {p.name: pipeline.sha256(p) for p in evidence.iterdir()})
            self.assertEqual([p.name for p in output.iterdir()], ["enhanced.webm"])


if __name__ == "__main__":
    unittest.main()
