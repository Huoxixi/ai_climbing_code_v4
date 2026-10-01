"""Source-time guarantees only: no rendering, media or numerical libraries."""
import copy
import math
import unittest

from core.replay_playback import playback_duration, playback_state, validate_playback


def piecewise():
    return {"source_start_seconds": 9.7, "source_end_seconds": 427 / 30,
            "playback_sections": [
                {"source_start_seconds": 9.7, "source_end_seconds": 10.3, "playback_rate": .75},
                {"source_start_seconds": 10.3, "source_end_seconds": 11.7, "playback_rate": .5},
                {"source_start_seconds": 11.7, "source_end_seconds": 13.35, "playback_rate": .75},
                {"source_start_seconds": 13.35, "source_end_seconds": 427 / 30, "playback_rate": .5}],
            "freeze_at": 10.7, "freeze_duration": .9}


class PlaybackValidationTests(unittest.TestCase):
    def test_rates_and_times_must_be_finite_and_cannot_accelerate_past_source_frames(self):
        for rate in (0, -1, 1.01, 1e-320, float("nan"), float("inf"), True):
            for sections in (False, True):
                with self.subTest(rate=rate, sections=sections):
                    shot = piecewise() if sections else {"source_start_seconds": 0,
                                                         "source_end_seconds": 1, "playback_rate": rate}
                    if sections:
                        shot["playback_sections"][0]["playback_rate"] = rate
                    with self.assertRaises(ValueError):
                        validate_playback(shot)
        for key, value in (("source_start_seconds", -1), ("source_start_seconds", float("nan")),
                           ("source_end_seconds", 9), ("source_end_seconds", float("inf"))):
            with self.subTest(key=key, value=value):
                shot = piecewise()
                shot[key] = value
                with self.assertRaises(ValueError):
                    validate_playback(shot)

    def test_sections_must_cover_the_entire_source_interval_without_overlap(self):
        for index, key, value in ((0, "source_start_seconds", 9.8),
                                  (1, "source_start_seconds", 10.4),
                                  (1, "source_start_seconds", 10.2),
                                  (3, "source_end_seconds", 14),
                                  (3, "source_end_seconds", 14.3)):
            with self.subTest(index=index, key=key, value=value):
                shot = piecewise()
                shot["playback_sections"][index][key] = value
                with self.assertRaises(ValueError):
                    validate_playback(shot)
        for rows in ([], None, {}, [None]):
            with self.subTest(rows=rows):
                shot = piecewise()
                shot["playback_sections"] = rows
                with self.assertRaises(ValueError):
                    validate_playback(shot)

    def test_freeze_is_a_paired_positive_interval_inside_the_source(self):
        for key, value in (("freeze_at", 9.7), ("freeze_at", 427 / 30),
                           ("freeze_at", float("nan")), ("freeze_duration", 0),
                           ("freeze_duration", -1), ("freeze_duration", float("inf"))):
            with self.subTest(key=key, value=value):
                shot = piecewise()
                shot[key] = value
                with self.assertRaises(ValueError):
                    validate_playback(shot)
        for missing in ("freeze_at", "freeze_duration"):
            with self.subTest(missing=missing):
                shot = piecewise()
                shot.pop(missing)
                with self.assertRaises(ValueError):
                    validate_playback(shot)


class PlaybackSourceTimeTests(unittest.TestCase):
    def test_uniform_fallback_preserves_the_previous_slow_freeze_resume_mapping(self):
        shot = {"source_start_seconds": 9.7, "source_end_seconds": 12.3, "playback_rate": .5,
                "freeze_at": 10.7, "freeze_duration": 1.8}
        self.assertAlmostEqual(playback_duration(shot), 7)
        for local, source, frozen, rate in ((0, 9.7, False, .5), (1, 10.2, False, .5),
                                            (2, 10.7, True, 0), (3.5, 10.7, True, 0),
                                            (3.8, 10.7, False, .5), (4.8, 11.2, False, .5),
                                            (7.1, 12.3, True, 0)):
            with self.subTest(local=local):
                actual, stopped, actual_rate = playback_state(shot, local)
                self.assertAlmostEqual(actual, source)
                self.assertEqual((stopped, actual_rate), (frozen, rate))

    def test_variable_rate_playback_reaches_every_source_frame_291_through_427(self):
        shot = piecewise()
        before = copy.deepcopy(shot)
        required = (10.3 - 9.7) / .75 + (11.7 - 10.3) / .5 + (13.35 - 11.7) / .75 + (427 / 30 - 13.35) / .5 + .9
        self.assertAlmostEqual(playback_duration(shot), required)
        states = [playback_state(shot, frame / 30) for frame in range(math.ceil(required * 30) + 2)]
        ids = [round(state[0] * 30) for state in states]
        self.assertEqual(set(ids), set(range(291, 428)))
        self.assertTrue(all(0 <= after - prior <= 1 for prior, after in zip(ids, ids[1:])))
        self.assertEqual(states[-1], (427 / 30, True, 0.))
        self.assertEqual({state[2] for state in states}, {0., .5, .75})
        self.assertEqual(shot, before)

    def test_freeze_at_rate_boundary_is_inserted_once_and_statistics_do_not_advance(self):
        shot = piecewise()
        shot["freeze_at"] = 10.3
        begins = (10.3 - 9.7) / .75
        finish = begins + .9
        for local in (begins, begins + .2, finish - .01):
            source, frozen, rate = playback_state(shot, local)
            self.assertEqual((source, frozen, rate), (10.3, True, 0.))
            self.assertAlmostEqual(source - .5, 9.8, msg="Climbing time must use source time")
        source, frozen, rate = playback_state(shot, finish)
        self.assertAlmostEqual(source, 10.3)
        self.assertEqual((frozen, rate), (False, .5))
        self.assertAlmostEqual(playback_state(shot, finish + .4)[0], 10.5)
        for boundary in (begins, finish, begins + .9 + (11.7 - 10.3) / .5):
            left, right = (playback_state(shot, boundary + delta)[0] for delta in (-1e-6, 1e-6))
            self.assertLessEqual(abs(right - left), 2e-6)

    def test_reviewed_hold_uses_one_second_freeze_but_remains_one_point_five_source_seconds(self):
        shot = {"source_start_seconds": 1.8, "source_end_seconds": 4.65,
                "playback_sections": [
                    {"source_start_seconds": 1.8, "source_end_seconds": 2.233333, "playback_rate": .75},
                    {"source_start_seconds": 2.233333, "source_end_seconds": 3.733333, "playback_rate": .5},
                    {"source_start_seconds": 3.733333, "source_end_seconds": 4.65, "playback_rate": .75}],
                "freeze_at": 3.733333, "freeze_duration": 1.0}
        self.assertAlmostEqual(playback_duration(shot), 5.8)
        begins = (2.233333 - 1.8) / .75 + 1.5 / .5
        for offset in (.1, .5, .9):
            source, frozen, rate = playback_state(shot, begins + offset)
            self.assertTrue(frozen)
            self.assertEqual(rate, 0)
            self.assertAlmostEqual(source - 2.233333, 1.5)
        source, frozen, rate = playback_state(shot, begins + 1)
        self.assertAlmostEqual(source, 3.733333)
        self.assertEqual((frozen, rate), (False, .75))

    def test_static_and_end_holds_have_zero_effective_rate(self):
        shot = {"source_start_seconds": 427 / 30, "source_end_seconds": 427 / 30,
                "duration_seconds": 3}
        self.assertEqual(playback_duration(shot), 0)
        for local in (-1, 0, 1, 20):
            self.assertEqual(playback_state(shot, local), (427 / 30, True, 0.))
        shot["playback_sections"] = []
        validate_playback(shot)
        with self.assertRaises(ValueError):
            playback_state(shot, float("nan"))


if __name__ == "__main__":
    unittest.main()
