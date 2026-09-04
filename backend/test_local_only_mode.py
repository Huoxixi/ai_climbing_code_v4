import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from core.supabase_repo import is_local_only_mode


AUTH_HEADERS = {"Authorization": "Bearer expired.jwt.token"}


def sample_board_payload(route_name: str = "Local only board"):
    return {
        "route_name": route_name,
        "difficulty": "6B+",
        "placed_holds": [
            {"id": "E3", "x": "E", "y": 3, "hold_type": "Jug", "is_start": True},
            {"id": "G3", "x": "G", "y": 3, "hold_type": "Crimp", "is_start": True},
            {"id": "F2", "x": "F", "y": 2, "hold_type": "Foot", "is_start": True},
            {"id": "E8", "x": "E", "y": 8, "hold_type": "Crimp"},
            {"id": "G12", "x": "G", "y": 12, "hold_type": "Pinch"},
            {"id": "F17", "x": "F", "y": 17, "hold_type": "Jug"},
        ],
        "beta_sequence": [],
    }


class LocalOnlyModeTest(unittest.TestCase):
    def setUp(self):
        main.active_tasks.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.active_tasks.clear()

    def test_local_only_is_the_default_without_an_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(is_local_only_mode())

    def test_generate_uses_memory_task_without_supabase_auth_or_task_create(self):
        payload = {
            "mode": "review_route",
            "board": sample_board_payload(),
            "target_difficulty": "6B+",
        }

        with (
            patch.dict(os.environ, {"LOCAL_ONLY": "true"}),
            patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))) as auth_mock,
            patch.object(main.supabase_repo, "create_task", AsyncMock(side_effect=AssertionError("Supabase task create should not run"))) as create_mock,
            patch.object(main.supabase_repo, "update_task", AsyncMock(side_effect=AssertionError("Supabase task update should not run"))) as update_mock,
            patch("main.run_ai_experiment", AsyncMock(return_value={"local": True})),
        ):
            response = self.client.post("/api/generate", json=payload, headers=AUTH_HEADERS)

        self.assertEqual(response.status_code, 202)
        self.assertIn(response.json()["task_id"], main.active_tasks)
        auth_mock.assert_not_called()
        create_mock.assert_not_called()
        update_mock.assert_not_called()

    def test_result_lookup_does_not_read_supabase_tasks(self):
        with (
            patch.dict(os.environ, {"LOCAL_ONLY": "true"}),
            patch.object(main.supabase_repo, "get_task", AsyncMock(side_effect=AssertionError("Supabase task lookup should not run"))) as get_mock,
        ):
            response = self.client.get("/api/result/missing-local-task")

        self.assertEqual(response.status_code, 404)
        self.assertIn("本地任务不存在", response.json()["detail"])
        get_mock.assert_not_called()

    def test_saved_board_crud_uses_local_json_with_expired_jwt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_boards_path = str(Path(tmpdir) / "saved_boards.json")
            with (
                patch.dict(os.environ, {"LOCAL_ONLY": "true"}),
                patch("main.SAVED_BOARDS_FILE", saved_boards_path),
                patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))) as auth_mock,
                patch.object(main.supabase_repo, "create_board", AsyncMock(side_effect=AssertionError("Supabase board create should not run"))) as create_mock,
                patch.object(main.supabase_repo, "list_boards", AsyncMock(side_effect=AssertionError("Supabase board list should not run"))) as list_mock,
                patch.object(main.supabase_repo, "update_board", AsyncMock(side_effect=AssertionError("Supabase board update should not run"))) as update_mock,
                patch.object(main.supabase_repo, "archive_board", AsyncMock(side_effect=AssertionError("Supabase board archive should not run"))) as archive_mock,
            ):
                create_response = self.client.post("/api/save-board", json=sample_board_payload(), headers=AUTH_HEADERS)
                saved_id = create_response.json()["saved_id"]
                list_response = self.client.get("/api/my-boards", headers=AUTH_HEADERS)
                update_response = self.client.put(
                    f"/api/my-boards/{saved_id}",
                    json={"route_name": "Renamed local board"},
                    headers=AUTH_HEADERS,
                )
                delete_response = self.client.delete(f"/api/my-boards/{saved_id}", headers=AUTH_HEADERS)

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(list_response.json()[0]["saved_id"], saved_id)
        self.assertEqual(update_response.json()["route_name"], "Renamed local board")
        auth_mock.assert_not_called()
        create_mock.assert_not_called()
        list_mock.assert_not_called()
        update_mock.assert_not_called()
        archive_mock.assert_not_called()

    def test_standard_board_activity_stays_local(self):
        route_response = self.client.get("/api/standard-board/routes", params={"limit": 1})
        source_id = route_response.json()["routes"][0]["source_id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            activity_path = str(Path(tmpdir) / "standard_board_activity.json")
            with (
                patch.dict(os.environ, {"LOCAL_ONLY": "true"}),
                patch("main.STANDARD_BOARD_ACTIVITY_FILE", activity_path),
                patch("main.resolve_supabase_user", AsyncMock(side_effect=AssertionError("Supabase auth should not run"))) as auth_mock,
            ):
                favorite_response = self.client.post(f"/api/standard-board/routes/{source_id}/favorite", headers=AUTH_HEADERS)
                rating_response = self.client.post(
                    f"/api/standard-board/routes/{source_id}/rating",
                    json={"rating": 5},
                    headers=AUTH_HEADERS,
                )
                activity_response = self.client.get(f"/api/standard-board/routes/{source_id}/activity", headers=AUTH_HEADERS)

        self.assertEqual(favorite_response.status_code, 200)
        self.assertEqual(rating_response.status_code, 200)
        self.assertEqual(activity_response.status_code, 200)
        self.assertTrue(activity_response.json()["favorite"])
        self.assertEqual(activity_response.json()["rating"], 5)
        auth_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
