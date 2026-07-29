import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class ReleaseHardeningTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_production_environment_disables_debug_docs(self):
        self.assertIsNone(main.docs_url_for_environment("production", "/docs"))
        self.assertEqual(main.docs_url_for_environment("development", "/docs"), "/docs")

    def test_health_reports_release_and_local_runtime_state_without_paths(self):
        with (
            patch("main.RELEASE_SHA", "abc123"),
            patch.dict(os.environ, {"LOCAL_ONLY": "true"}),
        ):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["release_sha"], "abc123")
        self.assertTrue(payload["local_only"])
        self.assertIn("data_readable", payload)
        self.assertNotIn("data_path", payload)

    def test_simulation_endpoints_are_closed_when_feature_is_disabled(self):
        with patch("main.SIMULATION_ENABLED", False):
            response = self.client.get("/api/simulation/climber-profiles")

        self.assertEqual(response.status_code, 404)
        self.assertIn("未在本次试运行中开放", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
