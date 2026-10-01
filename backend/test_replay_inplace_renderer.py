"""Cheap timing, evidence and occlusion guarantees for the local style sample.

Fixtures are synthetic. No original media, model, font or video encoder is used.
"""
import copy
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image

from core import replay_inplace_renderer as renderer


def manifest():
    return {
        "visual_version": renderer.VERSION,
        "width": 720, "height": 880, "fps": 30,
        "frame_count": 450, "duration_seconds": 15,
        "motion": {"source_start": 9.7, "source_end": 12.3, "rate": .5,
                   "freeze_at": 10.7, "freeze_duration": 1.8},
        "summary": {"limbs": {"left_hand": {"hold_ids": [3, 5, 6, 7, 9]},
                              "right_hand": {"hold_ids": [3, 6, 7, 9]}}},
        "counts": {
            "limb": "left_hand",
            "late_frame": {"source_at": 14.2, "visible_holds": [3, 5, 6]},
            "early_frame": {"source_at": 0, "visible_holds": [5, 6, 7, 9]},
            "switch_at": 10.75, "crossfade_seconds": .35,
            "events": [{"hold_id": hold, "display_at": at} for hold, at in
                       [(3, 7.45), (5, 8.6), (6, 9.75), (7, 11.15), (9, 12.35)]],
        },
    }


class InPlaceManifestTests(unittest.TestCase):
    def test_exact_fifteen_second_450_frame_contract(self):
        renderer.validate_manifest(manifest())
        for key, value in (("duration_seconds", 14.9), ("duration_seconds", 15.1),
                           ("frame_count", 449), ("frame_count", 451),
                           ("fps", 24), ("width", 718), ("height", 878)):
            with self.subTest(key=key, value=value):
                data = manifest()
                data[key] = value
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(data)

    def test_count_events_match_left_hand_once_per_distinct_hold(self):
        data = manifest()
        data["counts"]["events"] = [event for event in data["counts"]["events"]
                                    if event["hold_id"] != 5]
        with self.assertRaisesRegex(ValueError, "left-hand"):
            renderer.validate_manifest(data)
        data = manifest()
        data["summary"]["limbs"]["left_hand"]["hold_ids"].append(9)
        data["counts"]["events"].append({"hold_id": 9, "display_at": 13.8})
        with self.assertRaisesRegex(ValueError, "deduplicated"):
            renderer.validate_manifest(data)

    def test_count_chapter_cannot_be_relabelled_as_another_limb(self):
        data = manifest()
        data["counts"]["limb"] = "right_hand"
        with self.assertRaises(ValueError):
            renderer.validate_manifest(data)

    def test_occluded_hold_is_rejected_in_each_selected_real_frame(self):
        for frame_key, hold_id in (("late_frame", 3), ("early_frame", 7)):
            with self.subTest(frame=frame_key):
                data = manifest()
                data["counts"][frame_key]["visible_holds"].remove(hold_id)
                with self.assertRaisesRegex(ValueError, "visible"):
                    renderer.validate_manifest(data)

    def test_event_cannot_increment_during_a_hidden_crossfade(self):
        data = manifest()
        data["counts"]["events"][3]["display_at"] = 10.9
        with self.assertRaises(ValueError):
            renderer.validate_manifest(data)


class InPlaceTimingTests(unittest.TestCase):
    def test_frame_iterator_emits_450_frames_and_closes_its_source(self):
        composition = object.__new__(renderer.InPlaceComposition)
        motion_times, count_times, closed = [], [], []
        pixel = Image.new("RGBA", (1, 1), (12, 24, 36, 255))
        composition.motion_image = lambda time: (motion_times.append(time), pixel)[1]
        composition.counts_image = lambda time: (count_times.append(time), pixel)[1]
        composition.video = SimpleNamespace(close=lambda: closed.append(True))
        self.assertEqual(sum(1 for _ in composition.frames()), 450)
        self.assertEqual(len(motion_times), 210)
        self.assertEqual(len(count_times), 240)
        self.assertEqual(motion_times[0], 0)
        self.assertEqual(count_times[0], 7)
        self.assertAlmostEqual(count_times[-1], 15 - 1 / 30)
        self.assertEqual(closed, [True])

    def test_slow_freeze_resume_preserve_original_source_seconds(self):
        data = manifest()
        before = copy.deepcopy(data)
        cases = [(0, 9.7, False), (1, 10.2, False), (2, 10.7, True),
                 (3, 10.7, True), (3.8, 10.7, False), (4.8, 11.2, False),
                 (6.9, 12.25, False), (7, 12.3, False)]
        for display, expected_source, expected_freeze in cases:
            with self.subTest(display=display):
                source, frozen = renderer.source_state(data, display)
                self.assertAlmostEqual(source, expected_source, places=8)
                self.assertEqual(frozen, expected_freeze)
        for boundary in (2., 3.8):
            with self.subTest(boundary=boundary):
                left = renderer.source_state(data, boundary - 1e-6)[0]
                right = renderer.source_state(data, boundary + 1e-6)[0]
                self.assertLess(abs(right - left), 1e-6)
        self.assertEqual(data, before, "Presentation timing must not rewrite source evidence")

    def test_counter_changes_on_event_boundary_and_matches_first_visible_frame(self):
        data = manifest()
        # Bypass video decoding and fonts; observe only the semantic drawing calls.
        composition = object.__new__(renderer.InPlaceComposition)
        composition.manifest = data
        composition.source_image = lambda *_args, **_kwargs: Image.new("RGBA", (64, 64), (18, 24, 28, 255))
        highlighted, painted_counts = [], []

        def highlight(image, hold_id, _source_at, strength=1., *, previous=False, **_kwargs):
            if strength > 0 and not previous:
                highlighted.append(hold_id)
            return image

        def words(image, entries, *_args, **_kwargs):
            if entries and entries[0][1] == "左手":
                painted_counts.append(int(entries[1][1]))
            return image

        composition.highlight, composition.words = highlight, words
        for index, event in enumerate(data["counts"]["events"], start=1):
            with self.subTest(hold=event["hold_id"]):
                boundary = event["display_at"]
                count, _ = renderer.count_state(data, boundary - 1 / 30)
                self.assertEqual(count, index - 1)
                count, active = renderer.count_state(data, boundary)
                self.assertEqual(count, index)
                self.assertIs(active, event)
                # Non-grid event times must advance both effects on the same frame.
                first_frame = np.ceil(boundary * 30) / 30
                highlighted.clear()
                painted_counts.clear()
                composition.counts_image(float(first_frame))
                self.assertEqual(highlighted, [event["hold_id"]])
                self.assertEqual(painted_counts, [index])


class InPlaceOcclusionTests(unittest.TestCase):
    def test_exclusion_erases_fill_and_stroke_without_drawing_rectangle_edges(self):
        composition = object.__new__(renderer.InPlaceComposition)
        composition.polygon = lambda *_args: np.array([[8., 8.], [55., 8.], [55., 55.], [8., 55.]])
        base = Image.new("RGBA", (64, 64), (22, 37, 44, 255))
        original = np.asarray(base)
        # Cross both the real upper contour and its interior; the crop's lower
        # and side edges are not real rock boundaries and must not gain a stroke.
        exclusion = (25, 0, 40, 36)
        inside = np.zeros((64, 64), dtype=bool)
        inside[0:37, 25:41] = True
        for previous in (False, True):
            with self.subTest(previous=previous):
                full = np.asarray(composition.highlight(base, 3, 0, previous=previous))
                clipped = np.asarray(composition.highlight(base, 3, 0, previous=previous,
                                                            exclusion=exclusion))
                self.assertFalse(np.array_equal(full[8, 30], original[8, 30]), "Fixture must intersect stroke")
                self.assertFalse(np.array_equal(full[25, 30], original[25, 30]), "Fixture must intersect fill")
                np.testing.assert_array_equal(clipped[inside], original[inside])
                np.testing.assert_array_equal(clipped[~inside], full[~inside])
                np.testing.assert_array_equal(np.asarray(base), original)


if __name__ == "__main__":
    unittest.main()
