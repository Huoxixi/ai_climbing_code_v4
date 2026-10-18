import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from core.replay_pose_display import TORSO_CENTER_STYLE, torso_center


def pose(frame=0):
    sample = {"observed": True, "source_frame_id": frame,
              "time_seconds":frame/4,"wall_alignment":"reference",
              "wall_reference_transform":[[1,0,0],[0,1,0],[0,0,1]],
              "kpts_xy": [[0., 0.] for _ in range(17)], "kpts_score": [0.] * 17}
    for index, x, y in ((5, .3, .2), (6, .7, .2), (11, .3, .7), (12, .7, .7)):
        sample["kpts_xy"][index] = [x, y]
        sample["kpts_score"][index] = .9
    return sample


class TorsoCenterTests(unittest.TestCase):
    def test_reliability_and_invalid_samples(self):
        sample = pose()
        np.testing.assert_allclose(torso_center(sample), [.5, .45])
        sample["kpts_score"][5] = .49
        np.testing.assert_allclose(torso_center(sample), [1.7 / 3, 1.6 / 3])
        sample["kpts_xy"][6] = [float("nan"), .2]
        self.assertIsNone(torso_center(sample))
        self.assertIsNone(torso_center({**pose(), "observed": False}))
        for value in (None, {}, {"kpts_xy": [[0, 0]], "kpts_score": []}):
            self.assertIsNone(torso_center(value))
        for value in (0, 1, float("inf"), None, "0.3"):
            sample = pose()
            sample["kpts_xy"][5] = [value, .2]
            sample["kpts_score"][6] = .49
            self.assertIsNone(torso_center(sample))

    def test_encoded_video_has_center_dot_and_hides_it_when_unreliable(self):
        from core.climb_replay import _render_replay_overlay_video_body
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.mp4", Path(directory) / "overlay.webm"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4., (400, 300))
            self.assertTrue(writer.isOpened())
            for _ in range(4):
                writer.write(np.full((300, 400, 3), 20, np.uint8))
            writer.release()
            missing = pose(2)
            missing["kpts_score"][5] = missing["kpts_score"][6] = 0
            result = {"holds": [], "pose_samples": [pose(), missing], "attempt": {}}
            def registered(capture, *_):
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                return []
            with patch("core.climb_replay._registered_hold_polygons", side_effect=registered):
                contract = _render_replay_overlay_video_body(source, target, result)
            self.assertEqual(contract["torso_center"], TORSO_CENTER_STYLE)
            x, y, w, h = contract["route_map_rect"]
            cx, cy = round(x + .5 * w), round(y + .45 * h)
            capture = cv2.VideoCapture(str(target))
            try:
                for index in range(4):
                    ok, frame = capture.read()
                    self.assertTrue(ok)
                    if index == 0:
                        self.assertGreater(float(frame[cy, cx].mean()), 235)
                    if index >= 2:
                        self.assertLess(float(frame[cy, cx].mean()), 70)
            finally:
                capture.release()
