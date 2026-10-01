"""Safety and compatibility checks for the isolated 15-second preview."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import replay_resources as resources
from scripts import build_replay_inplace_sample as pipeline


class ManifestTests(unittest.TestCase):
    def test_only_the_approved_preview_geometry_and_duration_are_accepted(self):
        pipeline.validate_preview_manifest(dict(pipeline.PREVIEW_MEDIA))
        for field, value in (("duration_seconds", 35), ("frame_count", 1050),
                             ("fps", float("nan")), ("height", 1280), ("width", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                pipeline.validate_preview_manifest({**pipeline.PREVIEW_MEDIA, field: value})

    def test_inplace_renderer_is_explicitly_allowed_without_allowing_arbitrary_modules(self):
        self.assertIn("core.replay_inplace_renderer", resources.VISUAL_WORKER_MODULES)
        self.assertNotIn("core.climb_replay", resources.VISUAL_WORKER_MODULES)


class PublishingTests(unittest.TestCase):
    def test_failed_render_preserves_prior_sample_and_both_evidence_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            evidence, reviewed, output = (project / ".tmp" / name for name in ("evidence", "reviewed", "inplace"))
            for directory in (evidence, reviewed, output):
                directory.mkdir(parents=True)
            (evidence / "input.mp4").write_bytes(b"unchanged original")
            (evidence / "result.json").write_text("{}")
            for name in ("summary.json", "review.json"):
                (reviewed / name).write_text("{}")
            authored = output / "manifest-input.json"
            authored.write_text(json.dumps(pipeline.PREVIEW_MEDIA))
            (output / "preview.webm").write_bytes(b"existing sample")
            (output / "preview.mp4").write_bytes(b"existing compatible sample")
            before = {str(p): pipeline.sha256(p) for directory in (evidence, reviewed, output)
                      for p in directory.iterdir()}
            with patch.object(pipeline, "PROJECT", project), \
                 patch.object(pipeline, "probe_video", return_value=dict(pipeline.PREVIEW_MEDIA)), \
                 patch.object(pipeline, "local_h264_encoder", return_value=None), \
                 patch.object(resources, "run_visual_worker", side_effect=RuntimeError("fixture render failure")):
                with self.assertRaisesRegex(RuntimeError, "fixture render failure"):
                    pipeline.build_sample(evidence, reviewed, output, authored)
            self.assertEqual(before, {str(p): pipeline.sha256(p) for directory in (evidence, reviewed, output)
                                      for p in directory.iterdir()})


@unittest.skipIf(resources.psutil is None, "resource monitoring unavailable")
class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = pipeline.local_h264_encoder()

    def test_installed_encoder_makes_fully_decodable_h264_with_faststart(self):
        if self.encoder is None:
            self.skipTest("No installed libx264 encoder")
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "source.webm", directory / "output.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"VP80"), 30, (64, 80))
            if not writer.isOpened():
                self.skipTest("VP8 unavailable")
            for i in range(6):
                writer.write(np.full((80, 64, 3), 40 + i * 15, dtype=np.uint8))
            writer.release()
            original_hash = pipeline.sha256(source)
            tiny_media = {"width": 64, "height": 80, "fps": 30, "frame_count": 6,
                          "duration_seconds": .2}
            with patch.object(pipeline, "PREVIEW_MEDIA", tiny_media):
                report = pipeline.transcode_mp4(source, output, self.encoder)
            self.assertTrue(report["fully_decoded"])
            self.assertEqual(report["frame_count"], 6)
            self.assertEqual(pipeline.sha256(source), original_hash)
            data = output.read_bytes()
            self.assertLess(data.index(b"moov"), data.index(b"mdat"))
            self.assertIn(b"avc1", data)

    def test_cancellation_does_not_publish_partial_mp4_or_hold_resource_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output.mp4"
            with self.assertRaises(InterruptedError):
                pipeline.transcode_mp4(Path(temporary) / "source.webm", output, Path("unused"),
                                       cancelled=lambda: True)
            self.assertFalse(output.exists())
            with resources.high_resource_slot():
                pass


if __name__ == "__main__":
    unittest.main()
