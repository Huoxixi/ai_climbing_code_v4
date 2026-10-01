"""Source-time and evidence safeguards without encoding a full replay."""
import copy
import unittest

import numpy as np

from core import replay_focus_renderer as renderer


def manifest():
    return {"schema_version": 1, "visual_version": renderer.VERSION,
            "width": 720, "height": 880, "fps": 30,
            "duration_seconds": 4, "frame_count": 120,
            "shots": [{"id": "slow-foot", "kind": "move", "start_seconds": 0,
                       "duration_seconds": 4, "source_start_seconds": 2,
                       "source_end_seconds": 3, "playback_rate": .5}]}


def pose(at, *, observed=True, score=.9, position=(.4, .6)):
    return {"time_seconds": at, "observed": observed,
            "kpts_score": [score] * 17, "kpts_xy": [list(position) for _ in range(17)],
            "wall_alignment": "aligned", "wall_reference_transform": np.eye(3).tolist()}


def composition(samples):
    # Only the geometry methods are needed: no fonts, files or video decoder.
    result = renderer.Composition.__new__(renderer.Composition)
    result.samples, result.sw, result.sh = samples, 720, 880
    result.holds = {"3": {"id": 3, "polygon": [[.2, .3], [.3, .3], [.3, .4]]}}
    return result


class SourceTimeTests(unittest.TestCase):
    def test_fall_uses_verified_boundary_duration_without_claiming_completion(self):
        self.assertEqual(renderer.timing_display({"outcome": "fallen", "elapsed_seconds": 3,
                         "observed_duration_seconds": 10}), (False, True, True, 3))

    def test_truncated_or_insufficient_timing_is_observed_duration_only(self):
        self.assertEqual(renderer.timing_display({"outcome": "truncated", "elapsed_seconds": 3,
                         "observed_duration_seconds": 10}), (False, False, False, 3))
        self.assertEqual(renderer.timing_display({"outcome": "unconfirmed", "elapsed_seconds": None,
                         "observed_duration_seconds": 10}), (False, False, False, 10))

    def test_slow_motion_advances_source_time_at_half_rate_and_freezes(self):
        shot = manifest()["shots"][0]
        values = [renderer.source_time(shot, value) for value in (-1, 0, 1, 2, 3, 4)]
        self.assertEqual(values, [2, 2, 2.5, 3, 3, 3])
        self.assertEqual(renderer.source_time(shot, 20), 3)

    def test_repeated_chapter_does_not_change_original_measurement(self):
        first = manifest()["shots"][0]
        repeated = {**first, "id": "repeat", "start_seconds": 30}
        self.assertEqual(renderer.source_time(first, 1), renderer.source_time(repeated, 1))
        self.assertEqual(first["source_end_seconds"] - first["source_start_seconds"], 1)


class EvidenceGeometryTests(unittest.TestCase):
    def test_marker_interpolates_only_between_close_observed_samples(self):
        viewer = composition([pose(1, position=(.2, .4)), pose(1.25, position=(.4, .6))])
        np.testing.assert_allclose(viewer.measured_point("left_foot", 1.125), [216, 440])

    def test_unknown_low_confidence_or_long_gap_never_creates_marker(self):
        cases = [([pose(1), pose(1.25, observed=False)], 1.125),
                 ([pose(1, observed=False), pose(1.25)], 1.125),
                 ([pose(1), pose(1.25, score=.2)], 1.125),
                 ([pose(1), pose(1.5)], 1.25),
                 ([pose(1), pose(1.25)], .9),
                 ([pose(1), pose(1.25)], 1.3)]
        for samples, at in cases:
            with self.subTest(at=at, samples=samples):
                self.assertIsNone(composition(samples).measured_point("right_hand", at))

    def test_hold_is_not_drawn_without_current_invertible_registration(self):
        for change, at in (({"wall_reference_transform": None}, 1),
                           ({"wall_reference_transform": [[0] * 3 for _ in range(3)]}, 1),
                           ({"wall_alignment": "unknown"}, 1),
                           ({}, 1.5)):
            with self.subTest(change=change, at=at):
                sample = {**pose(1), **change}
                self.assertIsNone(composition([sample]).polygon(3, at))
        self.assertIsNone(composition([pose(1)]).polygon(99, 1))

    def test_valid_hold_uses_inverse_wall_transform_in_source_pixels(self):
        sample = pose(1)
        sample["wall_reference_transform"] = [[1, 0, 20], [0, 1, -10], [0, 0, 1]]
        expected = np.array([[.2, .3], [.3, .3], [.3, .4]]) * [720, 880] + [-20, 10]
        np.testing.assert_allclose(composition([sample]).polygon(3, 1), expected, atol=1e-4)


class ManifestTests(unittest.TestCase):
    def test_valid_real_source_and_freeze_chapter_is_accepted(self):
        renderer.validate_manifest(manifest())

    def test_discontinuous_or_reversed_source_times_are_rejected(self):
        for key, value in (("start_seconds", .1), ("source_end_seconds", 1),
                           ("source_start_seconds", -1), ("playback_rate", 0)):
            with self.subTest(key=key):
                value_to_check = manifest()
                value_to_check["shots"][0][key] = value
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(value_to_check)

    def test_nonfinite_chapter_and_total_times_are_rejected(self):
        for location, key in (("shot", "start_seconds"), ("shot", "duration_seconds"),
                              ("shot", "source_start_seconds"), ("shot", "playback_rate"),
                              ("manifest", "duration_seconds")):
            with self.subTest(location=location, key=key):
                value_to_check = copy.deepcopy(manifest())
                target = value_to_check["shots"][0] if location == "shot" else value_to_check
                target[key] = float("nan")
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(value_to_check)


if __name__ == "__main__":
    unittest.main()
