import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from core.board_readiness import apply_board_readiness
from core.models import BoardAsset, BetaStep, BoardSpec, Hold, HoldType, Limb
from core.moonboard_grading import FONT_GRADES
from core.standard_board import query_standard_routes
from core.validator import PhysicsValidator


def complete_board(columns=11, rows=18, difficulty="6B+"):
    top_y = rows - 1
    return BoardAsset(
        route_name="客户演示线路",
        difficulty=difficulty,
        board_spec=BoardSpec(columns=columns, rows=rows),
        placed_holds=[
            Hold(id="E3", x="E", y=3, hold_type=HoldType.JUG, is_start=True),
            Hold(id="G3", x="G", y=3, hold_type=HoldType.CRIMP, is_start=True),
            Hold(id="F2", x="F", y=2, hold_type=HoldType.FOOT, is_start=True),
            Hold(id="D7", x="D", y=7, hold_type=HoldType.CRIMP),
            Hold(id="H11", x="H", y=11, hold_type=HoldType.PINCH),
            Hold(id=f"F{top_y}", x="F", y=top_y, hold_type=HoldType.JUG),
        ],
        beta_sequence=[
            BetaStep(step=0, limb=Limb.LH, hold_id="E3", intent="Start"),
            BetaStep(step=1, limb=Limb.RH, hold_id="G3", intent="Start"),
            BetaStep(step=2, limb=Limb.LF, hold_id="F2", intent="Start foot"),
            BetaStep(step=3, limb=Limb.LH, hold_id="D7", intent="Move"),
            BetaStep(step=4, limb=Limb.RH, hold_id="H11", intent="Move"),
            BetaStep(step=5, limb=Limb.LH, hold_id=f"F{top_y}", intent="Top", is_top=True),
        ],
    )


class ReleaseReadinessTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_readiness_and_ai_eligibility_are_derived(self):
        ready = apply_board_readiness(complete_board())
        self.assertEqual(ready.workflow_status, "ready_for_review")
        self.assertTrue(ready.ai_eligible)
        manual_only = apply_board_readiness(complete_board(columns=14, rows=20))
        self.assertEqual(manual_only.workflow_status, "ready_for_review")
        self.assertFalse(manual_only.ai_eligible)

    def test_incomplete_route_is_saved_as_draft(self):
        board = complete_board()
        board.beta_sequence = []
        draft = apply_board_readiness(board)
        self.assertEqual(draft.workflow_status, "draft")
        self.assertFalse(draft.ai_eligible)
        self.assertTrue(any("Beta" in issue for issue in draft.readiness_issues))

    def test_hold_suitability_does_not_depend_on_grade(self):
        board = complete_board(difficulty="6B")
        board.placed_holds[-1].hold_type = HoldType.CRIMP
        assessed = apply_board_readiness(board)
        self.assertEqual(assessed.workflow_status, "ready_for_review")

    def test_beta_balance_reconstructs_contacts_from_sequential_steps(self):
        board = complete_board()
        ok, message = PhysicsValidator().validate_beta_balance(board.beta_sequence, board.placed_holds)
        self.assertTrue(ok, message)
        self.assertIn("重建", message)

    def test_font_grade_contract_and_metadata_search(self):
        self.assertEqual(FONT_GRADES[0], "6B")
        self.assertEqual(FONT_GRADES[-1], "8B+")
        self.assertEqual(len(FONT_GRADES), 14)
        result = query_standard_routes(q="Jonty", limit=10)
        self.assertGreater(result.total, 0)
        self.assertTrue(all("jonty" in route.setter_name.casefold() for route in result.routes))
        self.assertTrue(all(route.source_name and route.source_url for route in result.routes))

    def test_board_archive_and_restore_are_recoverable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "boards.json")
            with patch("main.SAVED_BOARDS_FILE", path):
                created = self.client.post("/api/save-board", json=complete_board().model_dump(mode="json")).json()
                saved_id = created["saved_id"]
                self.assertEqual(self.client.delete(f"/api/my-boards/{saved_id}").status_code, 200)
                self.assertEqual(self.client.get("/api/my-boards").json(), [])
                archived = self.client.get("/api/my-boards", params={"include_archived": True}).json()
                self.assertEqual(archived[0]["saved_id"], saved_id)
                self.assertIsNotNone(archived[0]["archived_at"])
                self.assertEqual(self.client.post(f"/api/my-boards/{saved_id}/restore").status_code, 200)
                self.assertEqual(len(self.client.get("/api/my-boards").json()), 1)


if __name__ == "__main__":
    unittest.main()
