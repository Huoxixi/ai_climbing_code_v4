import asyncio
import unittest
from unittest.mock import patch

from agent.experiments import compose_route_from_board, review_board_route
from core.models import AIExperimentRequest, BoardAsset, BetaStep, Hold, HoldType, Limb


def sample_board(route_name="AI Lab test board"):
    return BoardAsset(
        route_name=route_name,
        difficulty="V3",
        placed_holds=[
            Hold(id="E3", x="E", y=3, hold_type=HoldType.JUG, is_start=True),
            Hold(id="G3", x="G", y=3, hold_type=HoldType.CRIMP, is_start=True),
            Hold(id="F2", x="F", y=2, hold_type=HoldType.FOOT, is_start=True),
            Hold(id="D6", x="D", y=6, hold_type=HoldType.CRIMP),
            Hold(id="H7", x="H", y=7, hold_type=HoldType.PINCH),
            Hold(id="E10", x="E", y=10, hold_type=HoldType.JUG),
            Hold(id="G12", x="G", y=12, hold_type=HoldType.SLOPER),
            Hold(id="D14", x="D", y=14, hold_type=HoldType.CRIMP),
            Hold(id="F17", x="F", y=17, hold_type=HoldType.JUG),
            Hold(id="H16", x="H", y=16, hold_type=HoldType.CRIMP),
        ],
        beta_sequence=[
            BetaStep(step=0, limb=Limb.LH, hold_id="E3", intent="Start"),
            BetaStep(step=0, limb=Limb.RH, hold_id="G3", intent="Start"),
            BetaStep(step=1, limb=Limb.LH, hold_id="D6", intent="Move"),
            BetaStep(step=2, limb=Limb.RH, hold_id="H7", intent="Move"),
            BetaStep(step=3, limb=Limb.LH, hold_id="E10", intent="Move"),
            BetaStep(step=4, limb=Limb.RH, hold_id="F17", intent="Top", is_top=True),
        ],
    )


class AILabExperimentsTest(unittest.TestCase):
    def test_compose_returns_local_candidates_without_llm(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="V3")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(compose_route_from_board(request))

        self.assertEqual(response.mode, "compose_route")
        self.assertFalse(response.llm_enriched)
        self.assertGreaterEqual(len(response.selected_routes), 1)
        self.assertEqual(len(response.selected_routes), len(response.candidate_routes))
        signatures = {"|".join(sorted(hold.id for hold in route.placed_holds)) for route in response.selected_routes}
        self.assertEqual(len(signatures), len(response.selected_routes))
        self.assertTrue(all(candidate["valid_for_climb"] for candidate in response.candidate_routes))
        self.assertIn("standard_reference", response.metrics)

    def test_target_grade_candidate_is_close_to_requested_grade(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="V3")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(compose_route_from_board(request))

        target_candidates = [candidate for candidate in response.candidate_routes if candidate["label"] == "target_grade"]
        self.assertTrue(target_candidates)
        self.assertLessEqual(abs(target_candidates[0]["grade_delta"]), 4)

    def test_review_groups_hard_failures_as_must_fix(self):
        bad_board = BoardAsset(
            route_name="Bad review board",
            difficulty="V3",
            placed_holds=[
                Hold(id="E3", x="E", y=3, hold_type=HoldType.JUG, is_start=True),
                Hold(id="E10", x="E", y=10, hold_type=HoldType.CRIMP),
                Hold(id="E17", x="E", y=17, hold_type=HoldType.JUG),
            ],
        )
        request = AIExperimentRequest(mode="review_route", board=bad_board, target_difficulty="V3")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        self.assertEqual(response.risk_level, "high")
        self.assertTrue(any(suggestion.group == "must_fix" for suggestion in response.suggestions))
        self.assertTrue(any(violation.code in {"start_hand_count_lt_2", "vertical_gap_gt_5"} for violation in response.violations))

    def test_review_reports_missing_beta_hold_ids(self):
        board = sample_board()
        board.beta_sequence.append(BetaStep(step=99, limb=Limb.LH, hold_id="Z99", intent="Invalid"))
        request = AIExperimentRequest(mode="review_route", board=board, target_difficulty="V3")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        missing = [violation for violation in response.violations if violation.code == "missing_beta_hold"]
        self.assertTrue(missing)
        self.assertEqual(missing[0].hold_ids, ["Z99"])


if __name__ == "__main__":
    unittest.main()
