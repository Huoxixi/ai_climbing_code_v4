import asyncio
import unittest
from unittest.mock import patch

from agent.experiments import _plain_chinese_text, compose_route_from_board, review_board_route
from core.models import AIExperimentRequest, BoardAsset, BetaStep, BoardSpec, Hold, HoldType, Limb


def sample_board(route_name="AI experiment test board"):
    return BoardAsset(
        route_name=route_name,
        difficulty="6B+",
        board_spec=BoardSpec(columns=11, rows=18, angle_degrees=40),
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
            BetaStep(step=0, limb=Limb.LF, hold_id="F2", intent="Start foot"),
            BetaStep(step=1, limb=Limb.LH, hold_id="D6", intent="Move"),
            BetaStep(step=2, limb=Limb.RH, hold_id="H7", intent="Move"),
            BetaStep(step=3, limb=Limb.LH, hold_id="E10", intent="Move"),
            BetaStep(step=4, limb=Limb.RH, hold_id="F17", intent="Top", is_top=True),
        ],
    )


class AILabExperimentsTest(unittest.TestCase):
    def test_customer_copy_accepts_chinese_and_rejects_english_answers(self):
        self.assertEqual(_plain_chinese_text("建议先补低位脚点，再移动右手到 A8。"), "建议先补低位脚点，再移动右手到 A8。")
        self.assertIsNone(_plain_chinese_text("This route is balanced and safe."))
        self.assertIsNone(_plain_chinese_text("This route 很稳定"))

    def test_compose_returns_local_candidates_without_llm(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(compose_route_from_board(request))

        self.assertEqual(response.mode, "compose_route")
        self.assertFalse(response.llm_enriched)
        self.assertGreaterEqual(len(response.selected_routes), 1)
        self.assertLessEqual(len(response.selected_routes), 2)
        self.assertEqual(len(response.selected_routes), len(response.candidate_routes))
        signatures = {"|".join(sorted(hold.id for hold in route.placed_holds)) for route in response.selected_routes}
        self.assertEqual(len(signatures), len(response.selected_routes))
        source_signature = "|".join(sorted(hold.id for hold in request.board.placed_holds))
        self.assertNotIn(source_signature, signatures)
        self.assertTrue(all(candidate["valid_for_climb"] for candidate in response.candidate_routes))
        self.assertIn("standard_reference", response.metrics)

    def test_compose_explanation_is_deterministic_and_accounts_for_scores(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            first = asyncio.run(compose_route_from_board(request))
            second = asyncio.run(compose_route_from_board(request))

        self.assertIsNotNone(first.explanation)
        self.assertEqual(first.explanation.input_fingerprint, second.explanation.input_fingerprint)
        self.assertAlmostEqual(
            sum(item.score for item in first.explanation.score_breakdown),
            first.candidate_routes[0]["quality_score"],
            places=2,
        )
        self.assertAlmostEqual(
            sum(float(item["points"]) for item in first.explanation.risk_breakdown),
            first.candidate_routes[0]["risk_score"],
            places=2,
        )
        self.assertTrue(any(item.status == "selected" for item in first.explanation.candidate_trace))
        self.assertTrue(all(item.reason_code and item.reason for item in first.explanation.candidate_trace))
        self.assertNotIn("优质标准线路结构参考", first.applied_constraints)
        self.assertIn("仅用于结果对照", first.explanation.reference_note)

    def test_compose_does_not_fabricate_a_second_candidate(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="6B+")
        single_layout = [hold for hold in sample_board().placed_holds if hold.id != "H16"]
        with (
            patch("agent.experiments.settings.api_key", ""),
            patch("agent.experiments.AStarSolver.solve", return_value=(None, {"reason": "测试只保留一个候选"})),
            patch("agent.experiments._compose_strategy_holds", return_value=single_layout),
        ):
            response = asyncio.run(compose_route_from_board(request))

        self.assertEqual(len(response.selected_routes), 1)
        self.assertEqual(len(response.selected_routes), len(response.candidate_routes))

    def test_compose_explains_fallback_and_marks_action_risk_unchecked(self):
        board = sample_board()
        changed_layout = [hold for hold in board.placed_holds if hold.id not in {"H16", "D14"}]

        def strategy_result(holds, target_grade, strategy):
            return changed_layout if strategy == "different_style" else holds

        request = AIExperimentRequest(
            mode="compose_route",
            board=board,
            target_difficulty="6B+",
            generation_goal="quality_first",
        )
        with (
            patch("agent.experiments.settings.api_key", ""),
            patch("agent.experiments.AStarSolver.solve", return_value=(None, {"reason": "没有找到动作候选"})),
            patch("agent.experiments._compose_strategy_holds", side_effect=strategy_result),
        ):
            response = asyncio.run(compose_route_from_board(request))

        candidate = response.candidate_routes[0]
        self.assertEqual(candidate["selection_mode"], "fallback")
        self.assertEqual(candidate["movement_validation_status"], "not_run")
        self.assertEqual(candidate["risk_scope"], "structure_only")
        self.assertEqual(candidate["risk_assessment_status"], "partial")
        self.assertIn("回退", candidate["why_selected"])
        self.assertIn("动作风险尚未评估", candidate["why_selected"])
        self.assertTrue(candidate["change_evidence"]["removed_hold_ids"])
        self.assertEqual(
            next(item for item in response.explanation.candidate_trace if item.status == "selected").reason_code,
            "selected_as_fallback",
        )

    def test_compose_rejects_english_llm_copy_and_keeps_chinese_fallback(self):
        request = AIExperimentRequest(
            mode="compose_route",
            board=sample_board(),
            target_difficulty="6B+",
            generation_goal="quality_first",
        )
        with patch(
            "agent.experiments._llm_json",
            return_value={
                "route_names": {
                    "best_quality": "The Balanced Route",
                    "target_grade": "Grade Match",
                    "different_style": "Dynamic Flow",
                },
                "summary": "This route is balanced and suitable for the target grade.",
            },
        ):
            response = asyncio.run(compose_route_from_board(request))

        self.assertFalse(response.llm_enriched)
        self.assertTrue(all("The " not in route.route_name for route in response.selected_routes))
        self.assertTrue(all("This route" not in route.setter_commentary for route in response.selected_routes))
        self.assertIn("生成目标：质量优先", response.applied_constraints)
        self.assertNotIn("生成目标：quality_first", response.applied_constraints)

    def test_review_rejects_english_llm_summary_and_localizes_focus(self):
        request = AIExperimentRequest(
            mode="review_route",
            board=sample_board(),
            target_difficulty="6B+",
            review_focus="beta_sequence",
        )
        with patch(
            "agent.experiments._llm_json",
            return_value={"review_summary": "The beta sequence is balanced and safe."},
        ):
            response = asyncio.run(review_board_route(request))

        self.assertFalse(response.llm_enriched)
        self.assertNotIn("The beta", response.review_summary or "")
        self.assertIn("审核重点：动作顺序检查", response.applied_constraints)
        self.assertNotIn("审核重点：beta_sequence", response.applied_constraints)

    def test_target_grade_candidate_is_close_to_requested_grade(self):
        request = AIExperimentRequest(mode="compose_route", board=sample_board(), target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(compose_route_from_board(request))

        target_candidates = [candidate for candidate in response.candidate_routes if candidate["label"] == "target_grade"]
        self.assertTrue(target_candidates)
        self.assertLessEqual(abs(target_candidates[0]["grade_delta"]), 4)

    def test_review_groups_hard_failures_as_must_fix(self):
        bad_board = BoardAsset(
            route_name="Bad review board",
            difficulty="6B+",
            placed_holds=[
                Hold(id="E3", x="E", y=3, hold_type=HoldType.JUG, is_start=True),
                Hold(id="E10", x="E", y=10, hold_type=HoldType.CRIMP),
                Hold(id="E17", x="E", y=17, hold_type=HoldType.JUG),
            ],
        )
        request = AIExperimentRequest(mode="review_route", board=bad_board, target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        self.assertEqual(response.risk_level, "high")
        self.assertTrue(any(suggestion.group == "must_fix" for suggestion in response.suggestions))
        self.assertTrue(any(violation.code in {"start_hand_count_lt_2", "vertical_gap_gt_5"} for violation in response.violations))

    def test_review_reports_missing_beta_hold_ids(self):
        board = sample_board()
        board.beta_sequence.append(BetaStep(step=99, limb=Limb.LH, hold_id="Z99", intent="Invalid"))
        request = AIExperimentRequest(mode="review_route", board=board, target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        missing = [violation for violation in response.violations if violation.code == "missing_beta_hold"]
        self.assertTrue(missing)
        self.assertEqual(missing[0].hold_ids, ["Z99"])
        checks = {item.id: item for item in response.explanation.checks}
        self.assertEqual(checks["beta_references"].status, "fail")
        self.assertEqual(checks["beta_balance"].status, "not_run")

    def test_review_without_beta_marks_action_checks_not_run(self):
        board = sample_board()
        board.beta_sequence = []
        request = AIExperimentRequest(mode="review_route", board=board, target_difficulty="6B+")
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        checks = {item.id: item for item in response.explanation.checks}
        self.assertEqual(checks["beta_references"].status, "not_run")
        self.assertEqual(checks["beta_balance"].status, "not_run")
        self.assertIn("Beta 缺失或引用不完整", " ".join(response.explanation.uncertainties))

    def test_review_focus_changes_executed_rules(self):
        with patch("agent.experiments.settings.api_key", ""):
            footholds = asyncio.run(
                review_board_route(
                    AIExperimentRequest(
                        mode="review_route",
                        board=sample_board(),
                        target_difficulty="6B+",
                        review_focus="footholds",
                    )
                )
            )
            difficulty = asyncio.run(
                review_board_route(
                    AIExperimentRequest(
                        mode="review_route",
                        board=sample_board(),
                        target_difficulty="6B+",
                        review_focus="difficulty",
                    )
                )
            )
            beta = asyncio.run(
                review_board_route(
                    AIExperimentRequest(
                        mode="review_route",
                        board=sample_board(),
                        target_difficulty="6B+",
                        review_focus="beta_sequence",
                    )
                )
            )

        foothold_checks = {item.id: item.status for item in footholds.explanation.checks}
        difficulty_checks = {item.id: item.status for item in difficulty.explanation.checks}
        beta_checks = {item.id: item.status for item in beta.explanation.checks}
        self.assertEqual(foothold_checks["difficulty_match"], "not_run")
        self.assertEqual(foothold_checks["hand_move_sequence"], "not_run")
        self.assertEqual(difficulty_checks["beta_balance"], "not_run")
        self.assertNotEqual(difficulty_checks["difficulty_match"], "not_run")
        self.assertNotEqual(beta_checks["hand_move_sequence"], "not_run")

    def test_review_suggestions_are_quantified_and_risk_matches_findings(self):
        request = AIExperimentRequest(
            mode="review_route",
            board=sample_board(),
            target_difficulty="6B+",
            review_focus="overall",
        )
        with patch("agent.experiments.settings.api_key", ""):
            response = asyncio.run(review_board_route(request))

        self.assertTrue(all(item.reason_code for item in response.suggestions))
        self.assertTrue(all(item.observed and item.threshold and item.expected_effect for item in response.suggestions))
        self.assertAlmostEqual(
            sum(float(item["points"]) for item in response.explanation.risk_breakdown),
            response.metrics["risk_score"],
            places=2,
        )
        if any(item.group == "should_fix" for item in response.suggestions):
            self.assertGreater(response.metrics["risk_score"], 0)
            self.assertEqual(response.risk_level, "medium")

    def test_review_rejects_uncalibrated_board_angle(self):
        board = sample_board()
        board.board_spec = BoardSpec(columns=11, rows=18, angle_degrees=25)
        request = AIExperimentRequest(mode="review_route", board=board, target_difficulty="6B+")

        with self.assertRaisesRegex(ValueError, "11×18、40°"):
            asyncio.run(review_board_route(request))


if __name__ == "__main__":
    unittest.main()
