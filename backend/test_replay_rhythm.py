import copy
import unittest

from core.replay_rhythm import rhythm_data


def summary():
    return {"timing": {"start_seconds": .5, "end_seconds": 14, "elapsed_seconds": 13.5},
            "phases": [
                {"start_seconds": .5, "end_seconds": 7.166667, "kind": "hold"},
                {"start_seconds": 7.166667, "end_seconds": 11.133334, "kind": "transition"},
                {"start_seconds": 11.133334, "end_seconds": 14, "kind": "unknown"}],
            "coverage": {"start_seconds": .5, "end_seconds": 14, "duration_seconds": 13.5,
                         "hold_seconds": 6.666667, "transition_seconds": 3.966667,
                         "unknown_seconds": 2.866666, "known_fraction": .787654}}


class ReplayRhythmTests(unittest.TestCase):
    def test_local_sample_totals_allocate_one_hundred_percent_with_deterministic_tie(self):
        result = rhythm_data(summary())
        self.assertEqual(result["totals"], {"hold": 6.666667, "transition": 3.966667, "unknown": 2.866666})
        self.assertEqual(result["percentages"], {"hold": 50, "transition": 29, "unknown": 21})
        self.assertEqual(result["display_percentages"], {"hold": 49.4, "transition": 29.4, "unknown": 21.2})
        self.assertEqual(sum(result["percentages"].values()), 100)
        self.assertAlmostEqual(sum(result["display_percentages"].values()), 100)
        self.assertAlmostEqual(sum(result["totals"].values()), result["elapsed_seconds"])

    def test_clips_outside_window_and_sorts_by_source_time_without_swallowing_unknown(self):
        data = {"timing": {"start_seconds": 0, "end_seconds": 4}, "phases": [
            {"start_seconds": 3, "end_seconds": 5, "kind": "unknown", "duration_seconds": 2},
            {"start_seconds": -1, "end_seconds": 2, "kind": "hold", "duration_seconds": 3},
            {"start_seconds": 2, "end_seconds": 3, "kind": "transition"},
            {"start_seconds": 6, "end_seconds": 8, "kind": "hold"}]}
        result = rhythm_data(data)
        self.assertEqual(result["totals"], {"hold": 2, "transition": 1, "unknown": 1})
        self.assertEqual([part["kind"] for part in result["segments"]], ["hold", "transition", "unknown"])
        self.assertEqual(result["segments"][0]["start_seconds"], 0)
        self.assertEqual(result["segments"][-1]["end_seconds"], 4)

    def test_gaps_overlaps_and_missing_ends_are_rejected(self):
        for change, message in ((.1, "gap"), (-.1, "overlap")):
            data = summary()
            data["phases"][1]["start_seconds"] += change
            with self.assertRaisesRegex(ValueError, message):
                rhythm_data(data)
        for index in (0, -1):
            data = summary()
            data["phases"].pop(index)
            with self.assertRaises(ValueError):
                rhythm_data(data)

    def test_stale_coverage_metrics_are_rejected_individually(self):
        for field in ("hold_seconds", "transition_seconds", "unknown_seconds", "known_fraction",
                      "duration_seconds", "start_seconds", "end_seconds"):
            data = summary()
            data["coverage"][field] += .01
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"coverage.{field}"):
                rhythm_data(data)

    def test_elapsed_and_phase_duration_claims_must_match_timestamps(self):
        data = summary()
        data["timing"]["elapsed_seconds"] = 99
        with self.assertRaisesRegex(ValueError, "timing.elapsed_seconds"):
            rhythm_data(data)
        data = summary()
        data["phases"][0]["duration_seconds"] = 7
        with self.assertRaisesRegex(ValueError, "duration_seconds"):
            rhythm_data(data)

    def test_observation_only_empty_or_nonfinite_timing_does_not_invent_climb_boundaries(self):
        for changes in ({"start_seconds": None}, {"end_seconds": None}, {"end_seconds": .5},
                        {"start_seconds": float("nan")}, {"end_seconds": float("inf")},
                        {"start_seconds": True}):
            data = summary()
            data["timing"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rhythm_data(data)

    def test_unknown_can_occupy_the_entire_interval_and_zero_categories_stay_zero(self):
        data = {"timing": {"start_seconds": 2, "end_seconds": 5}, "phases": [
            {"start_seconds": 2, "end_seconds": 5, "kind": "unknown"}]}
        result = rhythm_data(data)
        self.assertEqual(result["totals"], {"hold": 0, "transition": 0, "unknown": 3})
        self.assertEqual(result["percentages"], {"hold": 0, "transition": 0, "unknown": 100})

    def test_equal_thirds_use_fixed_tie_order_and_binary_float_noise_is_ignored(self):
        data = {"timing": {"start_seconds": 0, "end_seconds": .9}, "phases": [
            {"start_seconds": 0, "end_seconds": .1 + .2, "kind": "hold"},
            {"start_seconds": .3, "end_seconds": .6, "kind": "transition"},
            {"start_seconds": .6, "end_seconds": .9, "kind": "unknown"}]}
        self.assertEqual(rhythm_data(data)["percentages"], {"hold": 34, "transition": 33, "unknown": 33})
        self.assertEqual(rhythm_data(data)["display_percentages"], {"hold": 33.4, "transition": 33.3, "unknown": 33.3})

    def test_invalid_kind_or_nonpositive_phase_cannot_disappear_into_totals(self):
        for patch in ({"kind": "thinking"}, {"end_seconds": .5}, {"start_seconds": "not-a-number"}):
            data = summary()
            data["phases"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                rhythm_data(data)

    def test_does_not_mutate_source_summary(self):
        data = summary()
        before = copy.deepcopy(data)
        rhythm_data(data)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
