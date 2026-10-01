"""Guarantees for unchanged baseline frames and isolated full-tail publishing."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import replay_resources as resources
from scripts import build_replay_inplace_full as pipeline


def manifest(duration=26):
    return {"visual_version": pipeline.VERSION, "width": 720, "height": 880,
            "fps": 30, "duration_seconds": duration, "frame_count": round(duration * 30),
            "last_source_seconds": 427 / 30}


class ManifestTests(unittest.TestCase):
    def test_full_tail_accepts_approved_durations_and_rejects_inconsistent_frames(self):
        for version in pipeline.WORKER_MODULES:
            for duration in (10, 10 + 1 / 30, 24, 26, 30, 60):
                pipeline.validate_manifest({**manifest(duration), "visual_version": version})
        for changes in ({"duration_seconds": 9}, {"duration_seconds": 61},
                        {"duration_seconds": 26.001}, {"frame_count": 779},
                        {"duration_seconds": float("nan")}, {"width": 1280},
                        {"visual_version": "replay-inplace-v1"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                pipeline.validate_manifest({**manifest(), **changes})

    def test_new_worker_is_allowlisted_and_inference_module_is_not(self):
        self.assertIn("core.replay_inplace_full_renderer", resources.VISUAL_WORKER_MODULES)
        self.assertIn("core.replay_inplace_rhythm_renderer", resources.VISUAL_WORKER_MODULES)
        self.assertEqual(pipeline.WORKER_MODULES[pipeline.VERSION], "core.replay_inplace_full_renderer")
        self.assertEqual(pipeline.WORKER_MODULES["replay-inplace-rhythm-v1"], "core.replay_inplace_rhythm_renderer")
        self.assertNotIn("core.climb_replay", resources.VISUAL_WORKER_MODULES)

    def test_source_endpoint_is_the_actual_last_frame_not_clip_duration(self):
        actual = {"frame_count": 428, "fps": 30}
        self.assertEqual(pipeline.validate_source_endpoint(manifest(), actual), 427 / 30)
        # A decimal JSON timestamp rounded to six places remains valid.
        pipeline.validate_source_endpoint({**manifest(), "last_source_seconds": 14.233333}, actual)
        for invalid in (428 / 30, 14, float("nan"), True, None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "actual source"):
                pipeline.validate_source_endpoint({**manifest(), "last_source_seconds": invalid}, actual)


class PublishingTests(unittest.TestCase):
    def test_render_failure_preserves_frozen_inputs_and_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            evidence, reviewed, output = (project / ".tmp" / name for name in ("evidence", "reviewed", "full"))
            for directory in (evidence, reviewed, output):
                directory.mkdir(parents=True)
            for name in ("input.mp4", "baseline.webm"):
                (evidence / name).write_bytes(name.encode())
            (evidence / "result.json").write_text("{}")
            for name in ("summary.json", "review.json"):
                (reviewed / name).write_text("{}")
            authored = output / "manifest-input.json"
            authored.write_text(json.dumps(manifest()))
            (output / "enhanced.webm").write_bytes(b"preserved earlier file")
            before = {str(p): pipeline.sha256(p) for folder in (evidence, reviewed, output) for p in folder.iterdir()}
            info = {"width": 720, "height": 880, "fps": 30, "frame_count": 428,
                    "duration_seconds": 428 / 30}
            with patch.object(pipeline, "PROJECT", project), \
                 patch.object(pipeline, "probe_video", return_value=info), \
                 patch.object(pipeline, "local_h264_encoder", return_value=Path("encoder")), \
                 patch.object(resources, "run_visual_worker", side_effect=RuntimeError("fixture failure")):
                with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                    pipeline.build_sample(evidence, reviewed, output, authored)
            self.assertEqual(before, {str(p): pipeline.sha256(p) for folder in (evidence, reviewed, output) for p in folder.iterdir()})


@unittest.skipIf(resources.psutil is None, "Resource monitoring unavailable")
class StreamCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = pipeline.local_h264_encoder()

    def setUp(self):
        if self.encoder is None:
            self.skipTest("No installed FFmpeg encoder")
        import cv2
        import numpy as np
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.baseline, self.tail = self.directory / "baseline.webm", self.directory / "tail.webm"
        for path, count, offset in ((self.baseline, 6, 20), (self.tail, 9, 170)):
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), 30, (64, 80))
            if not writer.isOpened():
                self.skipTest("VP8 unavailable")
            for i in range(count):
                frame = np.full((80, 64, 3), offset + i, dtype=np.uint8)
                frame[10:25, i:i+12] = 230
                writer.write(frame)
            writer.release()
        self.base_info, self.tail_info = pipeline.probe_video(self.baseline), pipeline.probe_video(self.tail)
        self.original = {p.name: pipeline.sha256(p) for p in (self.baseline, self.tail)}

    def tearDown(self):
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_stream_copy_preserves_every_body_pixel_and_h264_preserves_frame_count(self):
        output, mp4 = self.directory / "full.webm", self.directory / "full.mp4"
        report = pipeline.assemble_webm(self.baseline, self.tail, output, self.encoder,
                                        self.base_info, self.tail_info)
        self.assertEqual(report["frame_count"], 15)
        self.assertEqual(report["body_frames_checked"], 6)
        self.assertTrue(report["body_frames_identical"])
        self.assertFalse(report["body_reencoded"])
        self.assertEqual(report["baseline_decoded_sha256"], report["output_body_decoded_sha256"])
        converted = pipeline.transcode_full_mp4(output, mp4, self.encoder, report)
        self.assertEqual(converted["frame_count"], 15)
        self.assertTrue(converted["fully_decoded"])
        self.assertTrue(converted["body_reencoded"])
        self.assertEqual(self.original, {p.name: pipeline.sha256(p) for p in (self.baseline, self.tail)})
        content = mp4.read_bytes()
        self.assertLess(content.index(b"moov"), content.index(b"mdat"))

    def test_changed_body_frame_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Baseline content changed at frame 0"):
            pipeline.validate_full_video(self.tail, self.baseline, self.base_info, self.tail_info)

    def test_cancel_leaves_no_output_or_concat_list_and_releases_slot(self):
        output = self.directory / "full.webm"
        with self.assertRaises(InterruptedError):
            pipeline.assemble_webm(self.baseline, self.tail, output, self.encoder,
                                   self.base_info, self.tail_info, cancelled=lambda: True)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix(".concat.txt").exists())
        with resources.high_resource_slot():
            pass


if __name__ == "__main__":
    unittest.main()
