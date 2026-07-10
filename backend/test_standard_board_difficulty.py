import unittest
from collections import Counter
from unittest.mock import patch

from core import standard_board
from core.standard_board import (
    detail_for,
    evaluate_route_difficulty,
    find_standard_route,
    query_standard_routes,
    validate_standard_roles,
)


def difficulty_for(roles, v_grade="V3"):
    validation = validate_standard_roles(roles)
    assert validation["valid_for_climb"], validation
    return evaluate_route_difficulty(v_grade, 0, False, validation["effective_roles"], validation["marker_summary"], validation)


class StandardBoardDifficultyTest(unittest.TestCase):
    def test_difficulty_is_stable_and_does_not_change_quality_score(self):
        response = query_standard_routes(difficulty="V3", limit=1)
        route = find_standard_route(response.routes[0].source_id)
        first = detail_for(route)
        second = detail_for(route)

        self.assertEqual(first.difficulty_score, second.difficulty_score)
        self.assertEqual(first.predicted_v_grade, second.predicted_v_grade)
        self.assertEqual(first.quality_score, second.quality_score)
        self.assertEqual(first.quality_score, route.quality_score)

    def test_large_span_scores_harder_than_compact_route(self):
        compact = difficulty_for({"start": ["E3", "G3"], "mid": ["E7", "F10", "G13"], "end": ["F17"]})
        large_span = difficulty_for({"start": ["A1", "K1"], "mid": ["A7", "K10", "A13"], "end": ["K17"]})

        self.assertGreater(large_span["difficulty_score"], compact["difficulty_score"])
        self.assertGreater(large_span["difficulty_breakdown"]["move_distance"], compact["difficulty_breakdown"]["move_distance"])

    def test_crimp_sequence_scores_harder_than_jug_sequence(self):
        jug_line = difficulty_for({"start": ["A4", "E4"], "mid": ["B7", "C10", "D13"], "end": ["D17"]})
        crimp_line = difficulty_for({"start": ["B4", "C4"], "mid": ["A7", "B10", "C13"], "end": ["A17"]})

        self.assertGreater(crimp_line["difficulty_score"], jug_line["difficulty_score"])
        self.assertGreater(crimp_line["difficulty_breakdown"]["hold_demand"], jug_line["difficulty_breakdown"]["hold_demand"])

    def test_start_and_finish_pressure_raise_breakdown(self):
        base = difficulty_for({"start": ["E3", "G3"], "mid": ["F7", "F10", "F13"], "end": ["F17"]})
        hard_start = difficulty_for({"start": ["A1", "K1"], "mid": ["F7", "F10", "F13"], "end": ["F17"]})
        hard_finish = difficulty_for({"start": ["E3", "G3"], "mid": ["F7", "F10", "F13"], "end": ["K17"]})

        self.assertGreater(hard_start["difficulty_breakdown"]["start_finish_pressure"], base["difficulty_breakdown"]["start_finish_pressure"])
        self.assertGreater(hard_finish["difficulty_breakdown"]["start_finish_pressure"], base["difficulty_breakdown"]["start_finish_pressure"])

    def test_grade_mismatch_warning_for_undergraded_route(self):
        hard_v3 = difficulty_for({"start": ["A1", "K1"], "mid": ["A7", "K10", "A13"], "end": ["K17"]}, v_grade="V3")

        self.assertGreaterEqual(hard_v3["grade_delta"], 3)
        self.assertEqual(hard_v3["grade_warning"], "hard")
        self.assertEqual(hard_v3["predicted_v_grade"], "V9")

    def test_missing_hold_type_lowers_confidence_without_blocking_score(self):
        normal = difficulty_for({"start": ["E3", "G3"], "mid": ["F7", "F10", "F13"], "end": ["F17"]})
        original_hold_difficulty = standard_board._hold_difficulty

        def unknown_hold(coord_id):
            return (55.0, True) if coord_id == "F10" else original_hold_difficulty(coord_id)

        with patch("core.standard_board._hold_difficulty", side_effect=unknown_hold):
            with_missing_type = difficulty_for({"start": ["E3", "G3"], "mid": ["F7", "F10", "F13"], "end": ["F17"]})

        self.assertIsNotNone(with_missing_type["difficulty_score"])
        self.assertLess(with_missing_type["difficulty_confidence"], normal["difficulty_confidence"])

    def test_query_filters_and_sorts_by_difficulty_fields(self):
        filtered = query_standard_routes(predicted_v_grade="V5", limit=10)
        self.assertGreater(filtered.total, 0)
        self.assertTrue(all(route.predicted_v_grade == "V5" for route in filtered.routes))

        mismatches = query_standard_routes(grade_warning="hard", sort="grade_mismatch_desc", limit=10)
        self.assertGreater(mismatches.total, 0)
        deltas = [abs(route.grade_delta or 0) for route in mismatches.routes]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_calibrated_predictions_cover_high_grades(self):
        routes = query_standard_routes(valid_only=True, limit=100, sort="difficulty_score_desc").routes
        predicted = Counter(route.predicted_v_grade for route in routes)

        self.assertTrue(any(grade in predicted for grade in {"V5", "V6", "V7", "V8", "V9", "V10"}))
        self.assertGreater(max(int(route.predicted_v_grade[1:]) for route in routes if route.predicted_v_grade), 4)


if __name__ == "__main__":
    unittest.main()
