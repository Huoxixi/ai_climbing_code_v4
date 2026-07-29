import unittest
import json

from core.standard_board import (
    REVIEW_QUEUE_PATH,
    _coord_to_label,
    detail_for,
    find_standard_route,
    generate_standard_route,
    load_board_setup,
    load_standard_routes,
    query_standard_board_repairs,
    query_standard_routes,
    validate_standard_roles,
)


class StandardBoardDataTest(unittest.TestCase):
    def test_coord_conversion_uses_zero_based_x_and_one_based_y(self):
        self.assertEqual(_coord_to_label([0, 1]), "A1")
        self.assertEqual(_coord_to_label([10, 18]), "K18")
        self.assertIsNone(_coord_to_label([11, 1]))
        self.assertIsNone(_coord_to_label([0, 0]))

    def test_query_filters_by_difficulty_and_benchmark(self):
        response = query_standard_routes(difficulty="7A", benchmark_only=True, limit=10)
        self.assertGreater(response.total, 0)
        self.assertLessEqual(len(response.routes), 10)
        self.assertTrue(all(route.grade == "7A" for route in response.routes))
        self.assertTrue(all(route.is_benchmark for route in response.routes))
        self.assertTrue(all(route.valid_for_climb for route in response.routes))

    def test_board_setup_loads_full_11_by_18_hold_grid(self):
        setup = load_board_setup()
        coord_ids = {hold.id for hold in setup}
        variants = {(hold.hold_type.value, hold.variant) for hold in setup}
        self.assertEqual(len(setup), 198)
        self.assertEqual(len(coord_ids), 198)
        self.assertIn("A1", coord_ids)
        self.assertIn("K18", coord_ids)
        self.assertEqual(len(variants), 8)
        self.assertTrue(all(hold.imageUrl for hold in setup))
        self.assertTrue(all(hold.imageUrl.startswith("/images/processed/") for hold in setup))
        self.assertTrue(all(hold.scale == 0.78 for hold in setup))
        self.assertTrue(all(0 <= hold.rotation < 360 for hold in setup))
        self.assertTrue(any(hold.rotation % 90 != 0 for hold in setup))
        self.assertGreater(len({hold.rotation for hold in setup}), 24)

    def test_default_query_only_returns_climbable_routes(self):
        response = query_standard_routes(limit=50)
        self.assertGreater(response.total, 0)
        for route in response.routes:
            self.assertTrue(route.valid_for_climb)
            self.assertIsNotNone(route.quality_score)
            self.assertGreaterEqual(route.quality_score, 0)
            self.assertIn(route.quality_tier, {"excellent", "good", "climbable", "review"})
            self.assertGreaterEqual(route.marker_summary["counts"]["start_hands"], 2)
            self.assertGreaterEqual(route.marker_summary["counts"]["start_markers"], 3)
            self.assertGreaterEqual(route.features.end_count, 1)
            self.assertGreaterEqual(route.features.hold_count, 6)
            self.assertLessEqual(route.features.hold_count, 12)

    def test_route_detail_builds_board_asset_and_virtual_leds(self):
        response = query_standard_routes(difficulty="7A", limit=1)
        route = find_standard_route(response.routes[0].source_id)
        detail = detail_for(route)
        self.assertEqual(len(detail.board_setup), 198)
        self.assertEqual(len(detail.virtual_led), detail.features.hold_count)
        self.assertEqual(len(detail.route_overlay), detail.features.hold_count)
        self.assertEqual(len(detail.board_asset.placed_holds), detail.features.hold_count)
        self.assertEqual(detail.board_asset.board_spec.preset_id, "classic-11x18")
        self.assertTrue(all(point.led_index > 0 for point in detail.virtual_led))
        roles = {point.role for point in detail.route_overlay}
        self.assertIn("start_hand", roles)
        self.assertIn("start_foot", roles)
        self.assertIn("end", roles)

    def test_score_is_stable_for_same_route(self):
        response = query_standard_routes(difficulty="6B+", limit=1)
        route = find_standard_route(response.routes[0].source_id)
        self.assertEqual(detail_for(route).score, detail_for(route).score)

    def test_generation_passes_validation_and_reuse_threshold(self):
        generated = generate_standard_route(target_difficulty="7A", variation=True)
        self.assertTrue(generated["validation"]["valid_for_climb"])
        self.assertGreaterEqual(generated["reuse_rate"], 0.7)
        self.assertEqual(generated["reuse_quality"], "optimal")
        self.assertGreaterEqual(len(generated["route"].route_roles["start"]), 2)
        self.assertGreaterEqual(len(generated["route"].route_roles["end"]), 1)
        self.assertIsNotNone(generated["route"].quality_score)

    def test_y5_start_is_allowed_when_role_is_explicit(self):
        validation = validate_standard_roles(
            {
                "start": ["E5", "J1"],
                "mid": ["H7", "F10", "E13", "A14"],
                "end": ["D17"],
            }
        )
        self.assertTrue(validation["valid_for_climb"], validation)
        self.assertEqual(validation["checks"]["start_hand_count"], 2)
        self.assertGreaterEqual(validation["checks"]["start_foot_count"], 1)

    def test_start_foot_does_not_replace_two_hand_starts(self):
        validation = validate_standard_roles(
            {
                "start": ["E5", "C2"],
                "mid": ["H7", "F10", "E13", "A14"],
                "end": ["D17"],
            }
        )
        self.assertFalse(validation["valid_for_climb"])
        self.assertIn("start_hand_count_lt_2", validation["failures"])

    def test_missing_explicit_start_is_rejected(self):
        validation = validate_standard_roles(
            {
                "start": [],
                "mid": ["J1", "H7", "F10", "E13", "A14"],
                "end": ["D17"],
            }
        )
        self.assertFalse(validation["valid_for_climb"])
        self.assertIn("start_hand_count_lt_2", validation["failures"])

    def test_rejected_routes_have_no_quality_score_and_are_queued(self):
        routes = load_standard_routes()
        rejected = next(route for route in routes if not route.valid_for_climb)
        self.assertIsNone(rejected.quality_score)
        self.assertEqual(rejected.quality_tier, "rejected")
        self.assertTrue(REVIEW_QUEUE_PATH.exists())
        with REVIEW_QUEUE_PATH.open("r", encoding="utf-8") as file:
            queue = json.load(file)
        self.assertGreater(queue["total_rejected"], 0)
        self.assertTrue(queue["routes"][0]["review_reasons"])

    def test_start_marker_repair_candidates_are_revalidated(self):
        response = query_standard_board_repairs(status="repaired", limit=5)
        self.assertGreater(response.total, 0)
        candidate = response.routes[0]
        self.assertEqual(candidate.repair_status, "repaired")
        self.assertTrue(candidate.added_start_hands)
        self.assertTrue(candidate.derived_start_feet)
        self.assertTrue(candidate.validation["valid_for_climb"])
        self.assertIsNotNone(candidate.quality_score)

    def test_structural_failures_are_not_repaired_as_good_routes(self):
        response = query_standard_board_repairs(status="unrepairable", limit=20)
        self.assertGreater(response.total, 0)
        self.assertTrue(all(candidate.repair_status == "unrepairable" for candidate in response.routes))


if __name__ == "__main__":
    unittest.main()
