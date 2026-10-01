"""Drawing and evidence contracts only; no user media, fonts, or video encoding."""
import copy
import unittest

import numpy as np
from PIL import Image

from core import replay_inplace_rhythm_renderer as renderer
from core.replay_rhythm import rhythm_data
from test_replay_inplace_full_renderer import manifest as legacy_manifest


def manifest():
    data = legacy_manifest()
    data["visual_version"] = renderer.VERSION
    phase = data["summary"]["longest_hold"]
    data["summary"]["phases"] = [
        {"start_seconds": .5, "end_seconds": phase["start_seconds"], "kind": "transition"},
        copy.deepcopy(phase),
        {"start_seconds": phase["end_seconds"], "end_seconds": 14., "kind": "unknown"}]
    return data


class RhythmShadingTests(unittest.TestCase):
    def test_right_shading_leaves_opposite_edge_unchanged_and_zero_alpha_changes_nothing(self):
        white = Image.new("RGBA", (120, 100), (255, 255, 255, 255))
        shaded = renderer.shade_side(white, "right", 25, 65, alpha=1, reach=70)
        np.testing.assert_array_equal(np.asarray(shaded)[:, 0], np.asarray(white)[:, 0])
        self.assertLess(shaded.getpixel((119, 40))[0], 255)
        np.testing.assert_array_equal(
            np.asarray(renderer.shade_side(white, "right", 25, 65, alpha=0, reach=70)),
            np.asarray(white))
        self.assertEqual(white.getpixel((119, 40)), (255, 255, 255, 255))

    def test_caption_shadow_and_text_share_entry_and_exit_alpha(self):
        composition = object.__new__(renderer.RhythmComposition)
        seen = []
        composition.words = lambda image, entries, alpha: (seen.append(alpha), image)[1]
        white = Image.new("RGBA", (120, 100), (255, 255, 255, 255))
        entries = [((70, 35), "synthetic caption", 12, 400)]
        for local, options, expected in ((0, {}, 0), (.09, {}, .5),
                                          (1.92, {"alpha": .6, "duration": 2}, .3),
                                          (2, {"duration": 2}, 0)):
            with self.subTest(local=local):
                actual = composition.caption(white, entries, local, side="right", reach=70, **options)
                self.assertAlmostEqual(seen[-1], expected)
                # Use the exact alpha sent to text: an otherwise harmless binary
                # rounding difference can change an 8-bit mask value by one.
                reference = renderer.shade_side(white, "right", 35, 47, seen[-1], reach=70)
                np.testing.assert_array_equal(np.asarray(actual), np.asarray(reference))
                np.testing.assert_array_equal(np.asarray(actual)[:, 0], np.asarray(white)[:, 0])

    def test_backdrop_does_not_globally_dim_motion_or_freeze(self):
        composition = object.__new__(renderer.RhythmComposition)
        pixels = np.arange(6 * 8 * 4, dtype=np.uint8).reshape(6, 8, 4)
        pixels[:, :, 3] = 255
        original = Image.fromarray(pixels, "RGBA")
        calls = []
        composition.source_image = lambda at, still: (calls.append((at, still)), original)[1]
        shot = {"source_start_seconds": 1, "source_end_seconds": 3,
                "playback_rate": .5, "freeze_at": 2, "freeze_duration": 1}
        for local, expected in ((1, (1.5, False)), (2.5, (2, True)), (6, (3, True))):
            image, at, frozen = composition.backdrop(shot, local)
            self.assertEqual((at, frozen), expected)
            self.assertEqual(calls[-1], expected)
            np.testing.assert_array_equal(np.asarray(image), pixels)


class RhythmBarTests(unittest.TestCase):
    def setUp(self):
        self.composition = object.__new__(renderer.RhythmComposition)
        self.composition.rhythm = rhythm_data({
            "timing": {"start_seconds": 10, "end_seconds": 30, "elapsed_seconds": 20},
            "phases": [{"start_seconds": 10, "end_seconds": 15, "kind": "hold"},
                       {"start_seconds": 15, "end_seconds": 25, "kind": "transition"},
                       {"start_seconds": 25, "end_seconds": 30, "kind": "unknown"}]})
        self.composition.caption = lambda image, *_args, **_kwargs: image
        self.composition.words = lambda image, *_args, **_kwargs: image
        self.white = Image.new("RGBA", (600, 800), (255, 255, 255, 255))

    def color(self, kind):
        return Image.alpha_composite(Image.new("RGBA", (1, 1), "white"),
                                     Image.new("RGBA", (1, 1), (*renderer.COLORS[kind], 230))).getpixel((0, 0))

    def test_bar_geometry_uses_source_duration_and_preserves_unknown_at_the_end(self):
        self.composition.manifest = {"duration_seconds": 80}
        first = self.composition.rhythm_view(self.white, 1)
        # The 510px bar starts at x=38: 25%, 50%, 25% follow source intervals.
        for x, kind in ((164, "hold"), (167, "transition"), (419, "transition"), (422, "unknown")):
            self.assertEqual(first.getpixel((x, 598)), self.color(kind))
        self.composition.manifest = {"duration_seconds": 200}
        later = self.composition.rhythm_view(self.white, 15)
        np.testing.assert_array_equal(np.asarray(first), np.asarray(later))

    def test_partial_reveal_stops_chronologically_without_reallocating_widths(self):
        image = self.composition.rhythm_view(self.white, .425)
        self.assertEqual(image.getpixel((100, 598)), self.color("hold"))
        self.assertEqual(image.getpixel((290, 598)), self.color("transition"))
        self.assertEqual(image.getpixel((300, 598)), (255, 255, 255, 255))
        self.assertEqual(image.getpixel((480, 598)), (255, 255, 255, 255))


class RhythmManifestTests(unittest.TestCase):
    def test_legacy_uniform_playback_adapts_without_mutating_evidence_or_dropping_checks(self):
        data = manifest()
        before = copy.deepcopy(data)
        renderer.validate_manifest(data)
        self.assertEqual(data, before)
        for change in ("count", "contact", "early_end", "phase_gap"):
            with self.subTest(change=change):
                invalid = manifest()
                if change == "count":
                    invalid["summary"]["limbs"]["left_foot"]["count"] = 99
                elif change == "contact":
                    invalid["summary"]["longest_hold"]["contacts"]["right_foot"] = "unknown"
                elif change == "early_end":
                    invalid["shots"][2]["source_end_seconds"] = 12.3
                else:
                    invalid["summary"]["phases"][2]["start_seconds"] += .1
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(invalid)

    def test_piecewise_tempo_keeps_completion_and_cannot_truncate_its_source_interval(self):
        data = manifest()
        move = data["shots"][2]
        move.pop("playback_rate")
        move["playback_sections"] = [
            {"source_start_seconds": 9.7, "source_end_seconds": 11.7, "playback_rate": .5},
            {"source_start_seconds": 11.7, "source_end_seconds": data["last_source_seconds"], "playback_rate": .75}]
        renderer.validate_manifest(data)
        move["duration_seconds"] = 2
        with self.assertRaisesRegex(ValueError, "truncate"):
            renderer.validate_manifest(data)

    def test_longest_hold_cannot_contradict_unknown_rhythm_evidence(self):
        data = manifest()
        data["summary"]["phases"] = [{"start_seconds": .5, "end_seconds": 14., "kind": "unknown"}]
        with self.assertRaises(ValueError):
            renderer.validate_manifest(data)


if __name__ == "__main__":
    unittest.main()
