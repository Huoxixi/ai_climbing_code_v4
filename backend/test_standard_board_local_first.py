import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main


class StandardBoardLocalFirstTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_standard_board_routes_do_not_require_supabase_auth(self):
        with patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))):
            response = self.client.get("/api/standard-board/routes", params={"limit": 1})

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["routes"]), 0)

    def test_standard_board_detail_does_not_require_supabase_auth(self):
        route_response = self.client.get("/api/standard-board/routes", params={"limit": 1})
        source_id = route_response.json()["routes"][0]["source_id"]

        with patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))):
            response = self.client.get(f"/api/standard-board/routes/{source_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_id"], source_id)

    def test_standard_board_activity_uses_local_store(self):
        route_response = self.client.get("/api/standard-board/routes", params={"limit": 1})
        source_id = route_response.json()["routes"][0]["source_id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            activity_path = str(Path(tmpdir) / "standard_board_activity.json")
            with (
                patch("main.STANDARD_BOARD_ACTIVITY_FILE", activity_path),
                patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))),
            ):
                read_response = self.client.get(f"/api/standard-board/routes/{source_id}/activity")
                rate_response = self.client.post(f"/api/standard-board/routes/{source_id}/rating", json={"rating": 4})
                reread_response = self.client.get(f"/api/standard-board/routes/{source_id}/activity")

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(rate_response.status_code, 200)
        self.assertEqual(reread_response.status_code, 200)
        self.assertEqual(reread_response.json()["rating"], 4)

    def test_resource_endpoints_return_local_data_without_supabase_auth(self):
        with patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))):
            mapping_response = self.client.get("/api/holds/mapping")
            vectors_response = self.client.get("/api/holds/vectors")
            boards_response = self.client.get("/api/my-boards")

        self.assertEqual(mapping_response.status_code, 200)
        self.assertEqual(vectors_response.status_code, 200)
        self.assertEqual(boards_response.status_code, 200)
        self.assertGreater(len(mapping_response.json()), 0)
        self.assertGreater(len(vectors_response.json()), 0)
        self.assertGreater(len(boards_response.json()), 0)

    def test_repair_comparison_returns_original_for_repairable_route(self):
        repairable_response = self.client.get("/api/standard-board/repairs", params={"status": "repairable", "limit": 1})
        self.assertEqual(repairable_response.status_code, 200)
        self.assertGreater(len(repairable_response.json()["routes"]), 0)
        source_id = repairable_response.json()["routes"][0]["source_id"]

        comparison_response = self.client.get(f"/api/standard-board/repairs/{source_id}/comparison")

        self.assertEqual(comparison_response.status_code, 200)
        payload = comparison_response.json()
        self.assertEqual(payload["candidate"]["source_id"], source_id)
        self.assertIsNotNone(payload["original"])
        self.assertIsNone(payload["repaired"])

    def test_publish_repaired_route_adds_repaired_library_entry(self):
        repaired_response = self.client.get("/api/standard-board/repairs", params={"status": "repaired", "limit": 1})
        self.assertEqual(repaired_response.status_code, 200)
        self.assertGreater(len(repaired_response.json()["routes"]), 0)
        source_id = repaired_response.json()["routes"][0]["source_id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            accepted_path = Path(tmpdir) / "standard_board_accepted_repairs.json"
            with patch("core.standard_board.ACCEPTED_REPAIRS_PATH", accepted_path):
                publish_response = self.client.post("/api/standard-board/repairs/publish", json={"source_ids": [source_id]})
                library_response = self.client.get(f"/api/standard-board/routes/repaired-{source_id}")

        self.assertEqual(publish_response.status_code, 200)
        self.assertEqual(publish_response.json()["published"][0]["source_id"], f"repaired-{source_id}")
        self.assertEqual(library_response.status_code, 200)
        self.assertEqual(library_response.json()["source_id"], f"repaired-{source_id}")


if __name__ == "__main__":
    unittest.main()
