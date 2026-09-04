import os
import unittest
from pathlib import Path
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
        with (
            patch("main.SIMULATION_ENABLED", False),
            patch("main.PILOT_AUTH_ENABLED", True),
        ):
            response = self.client.get("/api/simulation/climber-profiles")

        self.assertEqual(response.status_code, 404)
        self.assertIn("未在本次试运行中开放", response.json()["detail"])

    def test_nginx_does_not_serve_frontend_for_debug_document_paths(self):
        nginx_config = (
            Path(__file__).resolve().parents[1]
            / "deploy"
            / "nginx"
            / "ai_climbing.conf"
        ).read_text(encoding="utf-8")

        for path in ("/docs", "/openapi.json", "/redoc"):
            self.assertGreaterEqual(
                nginx_config.count(f"location = {path} {{"),
                2,
                msg=f"{path} must be blocked in both local gateways",
            )


if __name__ == "__main__":
    unittest.main()
