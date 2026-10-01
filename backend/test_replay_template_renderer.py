"""Behavioral checks for real-footage template timing and protected output."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from core.replay_template_renderer import (TemplateComposition, output_size,
    render_template_video, source_state, validate_plan, rhythm_percentages)


def plan():
    return {"version": "replay-template-v1", "width": 160, "height": 200,
            "fps": 30, "source_duration_seconds": 1., "shots": [
        {"kind": "action", "source_start_seconds": 0., "source_end_seconds": .5,
         "playback_rate": .5, "duration_seconds": 1., "caption": "先看脚步", "detail": ""},
        {"kind": "action", "source_start_seconds": .5, "source_end_seconds": 1.,
         "playback_rate": .5, "duration_seconds": 1., "caption": "再看手脚衔接", "detail": ""},
        {"kind": "data", "source_start_seconds": 29 / 30, "source_end_seconds": 29 / 30,
         "playback_rate": 1., "duration_seconds": 1., "transition_seconds": .3,
         "caption": "已观察约 1 秒", "detail": "未确认完攀"}]}


def source(path):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 200))
    if not writer.isOpened():
        raise unittest.SkipTest("No source fixture encoder")
    for frame in range(30):
        writer.write(np.full((200, 160, 3), 10 + frame * 6, dtype=np.uint8))
    writer.release()


class TemplateRenderTests(unittest.TestCase):
    def test_dissolve_is_additional_and_first_pass_complete(self):
        self.assertEqual(validate_plan(plan()), 99)
        modified = plan()
        modified["shots"][1]["source_start_seconds"] = .6
        with self.assertRaisesRegex(ValueError, "every source"):
            validate_plan(modified)
        modified = plan()
        modified["shots"][1]["source_end_seconds"] = .9
        with self.assertRaisesRegex(ValueError, "completion"):
            validate_plan(modified)

    def test_shortened_shot_and_nonfinite_timing_rejected(self):
        modified = plan()
        modified["shots"][0]["duration_seconds"] = .3
        with self.assertRaisesRegex(ValueError, "truncate"):
            validate_plan(modified)
        modified = plan()
        modified["shots"][0]["playback_rate"] = float("nan")
        with self.assertRaises(ValueError):
            validate_plan(modified)

    def test_source_time_stops_when_extra_reading_time_begins(self):
        shot = plan()["shots"][0]
        self.assertEqual(source_state(shot, .6), (.3, False))
        self.assertEqual(source_state(shot, 1.2), (.5, True))
        self.assertEqual(source_state(plan()["shots"][-1], .6), (29 / 30, True))

    def test_preserves_portrait_and_landscape_framing(self):
        self.assertEqual(output_size(720, 880), (720, 880))
        self.assertEqual(output_size(1080, 1920), (720, 1280))
        self.assertEqual(output_size(1920, 1080), (1280, 720))

    def test_rhythm_keeps_unknown_and_display_percentages_sum_to_100(self):
        percentages = rhythm_percentages({"hold_seconds": 6.666667,
                                         "transition_seconds": 3.966667, "unknown_seconds": 2.866666})
        self.assertEqual(sum(percentages.values()), 100)
        self.assertGreater(percentages["unknown"], 0)
        self.assertEqual(rhythm_percentages({"unknown_seconds": 5}),
                         {"hold": 0, "transition": 0, "unknown": 100})

    def test_stream_includes_last_movement_before_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.mp4"
            source(path)
            composition = TemplateComposition(plan(), path)
            try:
                frames = composition.frames()
                first, last = next(frames), None
                for index in range(1, 60):
                    last = next(frames)
                # Unobscured corner proves completion came from the last source frame.
                self.assertGreater(np.asarray(last)[80, 150, :3].mean(),
                                   np.asarray(first)[80, 150, :3].mean() + 130)
                self.assertEqual(len(list(frames)), 39)
            finally:
                composition.video.close()

    def test_protected_real_encode_and_cancel_leave_source_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, output = root / "source.mp4", root / "template.mp4"
            source(path)
            original = path.read_bytes()
            result = render_template_video(path, plan(), output)
            self.assertEqual(result["frame_count"], 99)
            self.assertTrue(result["fully_decoded"])
            self.assertEqual(path.read_bytes(), original)
            cancelled = root / "cancelled.mp4"
            with self.assertRaises(InterruptedError):
                render_template_video(path, plan(), cancelled, cancelled=lambda: True)
            self.assertFalse(cancelled.exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["source.mp4", "template.mp4"])


if __name__ == "__main__":
    unittest.main()
