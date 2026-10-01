"""Small source-time and evidence checks; no user media, fonts or encoding."""
import copy
from types import SimpleNamespace
import unittest

from PIL import Image

from core import replay_inplace_full_renderer as renderer


def manifest():
    last = 427 / 30

    def shot(kind, start, length, source_start, source_end, rate=1, **extra):
        return {"id": kind, "kind": kind, "start_seconds": start,
                "duration_seconds": length, "source_start_seconds": source_start,
                "source_end_seconds": source_end, "playback_rate": rate, **extra}

    return {
        "visual_version": renderer.VERSION, "width": 720, "height": 880, "fps": 30,
        "duration_seconds": 26, "frame_count": 780, "last_source_seconds": last,
        "shots": [shot("counts", 0, 3.5, last, last),
                  shot("hold", 3.5, 7.5, 1.8, 4.65, .5, freeze_at=3.733333, freeze_duration=1.8),
                  shot("move", 11, 12, 9.7, last, .5, freeze_at=10.7, freeze_duration=1.8),
                  shot("summary", 23, 3, last, last)],
        "summary": {
            "timing": {"start_seconds": .5, "end_seconds": 14., "elapsed_seconds": 13.5,
                       "outcome": "completed", "status": "reviewed"},
            "longest_hold": {"start_seconds": 2.233333, "end_seconds": 3.733333,
                             "duration_seconds": 1.5, "kind": "hold", "status": "reviewed",
                             "contacts": {"left_hand": 5, "right_hand": 6,
                                          "left_foot": 2, "right_foot": 1}},
            "limbs": {limb: {"hold_ids": ids, "count": len(ids)} for limb, ids in
                      [("left_hand", [3, 5, 6, 7, 9]), ("right_hand", [3, 6, 7, 9]),
                       ("left_foot", [2, 3, 6, 4]), ("right_foot", [1, 3, 4])]},
        },
    }


class FullManifestTests(unittest.TestCase):
    def test_valid_manifest_and_distinct_limb_counts(self):
        data = manifest()
        renderer.validate_manifest(data)
        data["summary"]["limbs"]["left_foot"]["count"] = 5
        with self.assertRaises(ValueError):
            renderer.validate_manifest(data)

    def test_unknown_or_contradictory_longest_hold_is_not_confirmed(self):
        for state in ("unknown", 999, "missing"):
            with self.subTest(state=state):
                data = manifest()
                contacts = data["summary"]["longest_hold"]["contacts"]
                if state == "missing":
                    contacts.pop("right_foot")
                else:
                    contacts["right_foot"] = state
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(data)
        for key, value in (("kind", "unknown"), ("status", "unconfirmed")):
            with self.subTest(key=key):
                data = manifest()
                data["summary"]["longest_hold"][key] = value
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(data)

    def test_displayed_durations_must_match_the_source_boundaries(self):
        for section, key in (("timing", "elapsed_seconds"), ("longest_hold", "duration_seconds")):
            with self.subTest(section=section):
                data = manifest()
                data["summary"][section][key] = 99
                with self.assertRaises(ValueError):
                    renderer.validate_manifest(data)

    def test_truncated_movement_early_summary_and_sequential_counts_are_rejected(self):
        cases = []
        data = manifest()
        data["shots"][2]["source_end_seconds"] = 12.3
        cases.append(("move stops before completion", data))
        data = manifest()
        data["shots"][2]["duration_seconds"] = 10
        data["shots"][3].update(start_seconds=21, duration_seconds=5)
        cases.append(("summary interrupts unfinished motion", data))
        data = manifest()
        data["shots"][3]["source_start_seconds"] = 14
        cases.append(("summary jumps away from final source frame", data))
        data = manifest()
        data["shots"][0]["events"] = [{"hold_id": 3, "display_at": 1}]
        cases.append(("old sequential count events", data))
        for name, data in cases:
            with self.subTest(case=name), self.assertRaises(ValueError):
                renderer.validate_manifest(data)


class FullSourceTimeTests(unittest.TestCase):
    def test_motion_visits_every_source_frame_through_completion_without_a_jump(self):
        data = manifest()
        before = copy.deepcopy(data)
        move, ending = data["shots"][2:]
        frame_ids = [round(renderer.source_state(move, index / 30)[0] * 30)
                     for index in range(round(move["duration_seconds"] * 30))]
        self.assertEqual(frame_ids[0], 291)
        self.assertEqual(frame_ids[-1], 427)
        self.assertEqual(set(frame_ids), set(range(291, 428)))
        self.assertTrue(all(0 <= right - left <= 1 for left, right in zip(frame_ids, frame_ids[1:])))
        self.assertAlmostEqual(renderer.source_state(ending, 0)[0], frame_ids[-1] / 30)
        for shot in data["shots"][1:3]:
            start = (shot["freeze_at"] - shot["source_start_seconds"]) / shot["playback_rate"]
            finish = start + shot["freeze_duration"]
            for boundary in (start, finish):
                with self.subTest(shot=shot["kind"], boundary=boundary):
                    left = renderer.source_state(shot, boundary - 1e-6)[0]
                    right = renderer.source_state(shot, boundary + 1e-6)[0]
                    self.assertLess(abs(right - left), 1e-6)
        self.assertEqual(data, before)

    def test_statistics_stop_during_freeze_and_at_the_original_end(self):
        data = manifest()
        timing, phase = data["summary"]["timing"], data["summary"]["longest_hold"]
        for shot in data["shots"][1:3]:
            start = (shot["freeze_at"] - shot["source_start_seconds"]) / shot["playback_rate"]
            points = [renderer.source_state(shot, start + offset)[0] for offset in (.1, .8, 1.7)]
            self.assertEqual(len(set(points)), 1)
            self.assertEqual(len({renderer.elapsed_at(timing, at) for at in points}), 1)
            self.assertEqual(len({renderer.hold_elapsed(phase, at) for at in points}), 1)
            if shot["kind"] == "hold":
                self.assertAlmostEqual(renderer.hold_elapsed(phase, points[0]), 1.5)
        self.assertEqual(renderer.elapsed_at(timing, 0), 0)
        self.assertAlmostEqual(renderer.elapsed_at(timing, 10.7), 10.2)
        self.assertEqual(renderer.elapsed_at(timing, data["last_source_seconds"]), 13.5)
        self.assertEqual(renderer.hold_elapsed(phase, 1.8), 0)
        self.assertAlmostEqual(renderer.hold_elapsed(phase, 3.5), 1.266667)
        self.assertAlmostEqual(renderer.hold_elapsed(phase, 4.65), 1.5)


class FullDrawingContractTests(unittest.TestCase):
    def test_four_limb_values_share_one_reveal_without_point_events(self):
        data = manifest()
        composition = object.__new__(renderer.FullComposition)
        composition.manifest, composition.summary = data, data["summary"]
        composition.baseline_last = None
        pixel = Image.new("RGBA", (1, 1), (12, 24, 36, 255))
        composition.backdrop = lambda *_args: (pixel, data["last_source_seconds"], True)
        calls = []
        composition.words = lambda image, entries, alpha: (calls.append((entries, alpha)), image)[1]

        def unexpected_highlight(*_args, **_kwargs):
            self.fail("The simultaneous summary must not return to per-point highlighting")

        composition.highlight = unexpected_highlight
        composition.shot_image(data["shots"][0], .8)
        composition.shot_image(data["shots"][0], 2.4)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], calls[1][0])
        for entries, alpha in calls:
            self.assertGreater(alpha, 0)
            lines = [entry[1].replace(" ", "") for entry in entries]
            same_line = [line for line in lines if all(value in line for value in
                         ("左手5", "右手4", "左脚4", "右脚3"))]
            self.assertEqual(len(same_line), 1)

    def test_frame_iterator_emits_780_frames_and_closes_source(self):
        composition = object.__new__(renderer.FullComposition)
        composition.manifest = manifest()
        pixel = Image.new("RGBA", (1, 1), (12, 24, 36, 255))
        calls, closed = [], []
        composition.shot_image = lambda shot, local: (calls.append((shot["kind"], local)), pixel)[1]
        composition.video = SimpleNamespace(close=lambda: closed.append(True))
        self.assertEqual(sum(1 for _ in composition.frames()), 780)
        self.assertEqual(calls[0], ("counts", 0))
        self.assertEqual(calls[-1][0], "summary")
        self.assertAlmostEqual(calls[-1][1], 3 - 1 / 30)
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
