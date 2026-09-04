import unittest
from unittest.mock import patch

from core.moonboard_grading import (
    FONT_GRADES,
    assess_equivalent_grade,
    board_is_calibrated,
    feedback_band_is_eligible,
    grade_boundary_label,
    grade_delta,
    hold_transfer_demand,
    load_grade_model,
    normalize_font_grade,
)
from core.standard_board import query_standard_routes
from scripts.build_moonboard_grade_model import build_model
from scripts.migrate_font_grades import migrate_board


ROLES = {
    "start": ["E3", "G3"],
    "mid": ["D7", "H10", "E13"],
    "end": ["F17"],
}
BOARD_SPEC = {"columns": 11, "rows": 18, "angle_degrees": 40}


class MoonBoardGradeContractTest(unittest.TestCase):
    def test_all_font_grades_parse_sort_and_compute_adjacent_delta(self):
        self.assertEqual(len(FONT_GRADES), 14)
        for index, grade in enumerate(FONT_GRADES):
            self.assertEqual(normalize_font_grade(grade.lower()), grade)
            if index:
                self.assertEqual(grade_delta(grade, FONT_GRADES[index - 1]), 1)
        self.assertEqual(grade_boundary_label(-0.1), "低于 6B")
        self.assertEqual(grade_boundary_label(14), "高于 8B+")

    def test_dataset_and_model_keep_8b_and_8b_plus(self):
        model = load_grade_model()
        self.assertGreater(model["sample_counts"]["8B"], 0)
        self.assertGreater(model["sample_counts"]["8B+"], 0)
        self.assertEqual(model["grade_order"], list(FONT_GRADES))

    def test_fixed_split_rebuild_is_reproducible_and_meets_release_gate(self):
        first = build_model()
        second = build_model()
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["metrics"]["within_one_accuracy"], 0.68)
        self.assertGreaterEqual(first["metrics"]["benchmark_within_one_accuracy"], 0.75)
        self.assertLess(abs(first["metrics"]["mean_bias"]), 0.5)
        self.assertTrue(first["calibration_ready"])

    def test_only_11_by_18_at_40_degrees_is_calibrated(self):
        self.assertTrue(board_is_calibrated(BOARD_SPEC))
        self.assertFalse(board_is_calibrated({**BOARD_SPEC, "angle_degrees": 25}))
        self.assertFalse(board_is_calibrated({**BOARD_SPEC, "columns": 14}))
        assessment = assess_equivalent_grade(
            ROLES,
            board_spec={**BOARD_SPEC, "angle_degrees": 25},
        )
        self.assertEqual(assessment["calibration_status"], "uncalibrated")
        self.assertIsNone(assessment["predicted_grade"])

    def test_unreviewed_holds_cannot_produce_high_confidence(self):
        assessment = assess_equivalent_grade(
            ROLES,
            board_spec=BOARD_SPEC,
            hold_demands=[55] * 6,
            hold_confidences=[0.65] * 6,
            beta_complete=True,
        )
        self.assertLessEqual(assessment["difficulty_confidence"], 0.64)
        self.assertNotEqual(assessment["confidence_tier"], "high")

    def test_custom_hold_correction_uses_profile_and_stays_within_one_grade(self):
        easy_profile = {
            "quality": 5,
            "capacity": 1.4,
            "preferred_direction_degrees": 0,
            "direction_tolerance_degrees": 90,
        }
        hard_profile = {
            "quality": 1,
            "capacity": 0.3,
            "preferred_direction_degrees": 180,
            "direction_tolerance_degrees": 30,
        }
        easy_demand = hold_transfer_demand("Crimp", 0, easy_profile)
        hard_demand = hold_transfer_demand("Crimp", 0, hard_profile)
        self.assertLess(easy_demand, hard_demand)

        with patch("core.moonboard_grading._model_score", return_value=6.0):
            easy = assess_equivalent_grade(
                ROLES, board_spec=BOARD_SPEC, hold_demands=[easy_demand] * 6, beta_complete=True
            )
            hard = assess_equivalent_grade(
                ROLES, board_spec=BOARD_SPEC, hold_demands=[hard_demand] * 6, beta_complete=True
            )
        self.assertLessEqual(abs(grade_delta(easy["predicted_grade"], "7B")), 1)
        self.assertLessEqual(abs(grade_delta(hard["predicted_grade"], "7B")), 1)

    def test_out_of_range_predictions_are_labeled_without_clamping(self):
        with patch("core.moonboard_grading._model_score", return_value=-0.25):
            below = assess_equivalent_grade(ROLES, board_spec=BOARD_SPEC, beta_complete=True)
        with patch("core.moonboard_grading._model_score", return_value=13.25):
            above = assess_equivalent_grade(ROLES, board_spec=BOARD_SPEC, beta_complete=True)
        self.assertEqual(below["predicted_grade"], "低于 6B")
        self.assertEqual(above["predicted_grade"], "高于 8B+")
        self.assertEqual(below["confidence_tier"], "low")
        self.assertEqual(above["confidence_tier"], "low")

    def test_standard_route_keeps_original_grade_and_exposes_no_v_fields(self):
        route = query_standard_routes(difficulty="8B+", limit=1).routes[0]
        payload = route.model_dump(mode="json")
        self.assertEqual(payload["grade"], "8B+")
        self.assertEqual(payload["grade_origin"], "moonboard_source")
        self.assertFalse(any("v_grade" in key for key in payload))

    def test_feedback_requires_approved_count_and_three_profiles(self):
        records = [
            {
                "review_status": "approved",
                "perceived_grade": "7A",
                "profile_id": f"profile-{index % 3}",
            }
            for index in range(10)
        ]
        self.assertTrue(feedback_band_is_eligible(records, "7A"))
        pending = [{**record, "review_status": "pending"} for record in records]
        self.assertFalse(feedback_band_is_eligible(pending, "7A"))
        two_profiles = [{**record, "profile_id": f"profile-{index % 2}"} for index, record in enumerate(records)]
        self.assertFalse(feedback_band_is_eligible(two_profiles, "7A"))

    def test_active_history_migration_is_idempotent_and_archives_are_deferred(self):
        archived = {"saved_id": "archived", "difficulty": "V4", "archived_at": "2026-01-01"}
        self.assertEqual(migrate_board(archived), archived)
        active = {
            "saved_id": "active",
            "source_type": "manual",
            "difficulty": "V4",
            "board_spec": BOARD_SPEC,
            "placed_holds": [
                {"id": "E3", "x": "E", "y": 3, "hold_type": "Jug", "is_start": True},
                {"id": "G3", "x": "G", "y": 3, "hold_type": "Crimp", "is_start": True},
                {"id": "F2", "x": "F", "y": 2, "hold_type": "Foot", "is_start": True},
                {"id": "D7", "x": "D", "y": 7, "hold_type": "Crimp"},
                {"id": "H10", "x": "H", "y": 10, "hold_type": "Pinch"},
                {"id": "F17", "x": "F", "y": 17, "hold_type": "Jug"},
            ],
            "beta_sequence": [
                {"step": 0, "limb": "LH", "hold_id": "E3", "intent": "Start"},
                {"step": 1, "limb": "RH", "hold_id": "G3", "intent": "Start"},
                {"step": 2, "limb": "LF", "hold_id": "F2", "intent": "Start foot"},
                {"step": 3, "limb": "LH", "hold_id": "D7", "intent": "Move"},
                {"step": 4, "limb": "RH", "hold_id": "H10", "intent": "Move"},
                {"step": 5, "limb": "LH", "hold_id": "F17", "intent": "Top", "is_top": True},
            ],
        }
        first = migrate_board(active)
        second = migrate_board(first)
        self.assertEqual(first, second)
        self.assertEqual(first["legacy_difficulty"], "V4")
        self.assertIn(first["difficulty"], FONT_GRADES)


if __name__ == "__main__":
    unittest.main()
