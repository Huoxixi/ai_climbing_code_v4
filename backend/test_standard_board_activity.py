import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main
from core.standard_board import query_standard_routes


class StandardBoardActivityApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_activity_file = main.STANDARD_BOARD_ACTIVITY_FILE
        main.STANDARD_BOARD_ACTIVITY_FILE = str(Path(self.temp_dir.name) / "standard_board_activity.json")
        self.client = TestClient(main.app)
        self.headers = {"Authorization": "Bearer mock-token-local-demo"}
        self.source_id = query_standard_routes(limit=1).routes[0].source_id

    def tearDown(self):
        main.STANDARD_BOARD_ACTIVITY_FILE = self.original_activity_file
        self.temp_dir.cleanup()

    def test_local_activity_favorite_rating_and_ascent_log(self):
        favorite = self.client.post(f"/api/standard-board/routes/{self.source_id}/favorite", headers=self.headers)
        self.assertEqual(favorite.status_code, 200)
        self.assertTrue(favorite.json()["favorite"])

        first_rating = self.client.post(f"/api/standard-board/routes/{self.source_id}/rating", headers=self.headers, json={"rating": 3})
        self.assertEqual(first_rating.status_code, 200)
        self.assertEqual(first_rating.json()["rating"], 3)

        updated_rating = self.client.post(f"/api/standard-board/routes/{self.source_id}/rating", headers=self.headers, json={"rating": 5})
        self.assertEqual(updated_rating.status_code, 200)
        self.assertEqual(updated_rating.json()["rating"], 5)

        log = self.client.post(
            f"/api/standard-board/routes/{self.source_id}/ascent-log",
            headers=self.headers,
            json={"result": "send", "attempts": 4, "perceived_grade": "6B+", "notes": "稳定完成"},
        )
        self.assertEqual(log.status_code, 200)
        body = log.json()
        self.assertEqual(body["stats"]["attempts_total"], 4)
        self.assertEqual(body["stats"]["sends_total"], 1)
        self.assertEqual(body["stats"]["last_result"], "send")
        self.assertEqual(body["logs"][0]["notes"], "稳定完成")

        activity = self.client.get(f"/api/standard-board/routes/{self.source_id}/activity", headers=self.headers)
        self.assertEqual(activity.status_code, 200)
        self.assertTrue(activity.json()["favorite"])
        self.assertEqual(activity.json()["rating"], 5)

        unfavorite = self.client.delete(f"/api/standard-board/routes/{self.source_id}/favorite", headers=self.headers)
        self.assertEqual(unfavorite.status_code, 200)
        self.assertFalse(unfavorite.json()["favorite"])


if __name__ == "__main__":
    unittest.main()
