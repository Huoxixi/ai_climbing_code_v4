import json
import tempfile
import threading
import unittest
from pathlib import Path

import bcrypt
from fastapi.testclient import TestClient

import main
from core.pilot_access import PilotAccessManager


class PilotAccessApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        users_file = root / "users.json"
        users_file.write_text(
            json.dumps(
                {
                    "users": {
                        "ma-trial": {
                            "display_name": "马老师",
                            "active": True,
                            "password_hash": bcrypt.hashpw(
                                b"ma-password-very-long-2026",
                                bcrypt.gensalt(),
                            ).decode(),
                        },
                        "deng-trial": {
                            "display_name": "邓老师",
                            "active": True,
                            "password_hash": bcrypt.hashpw(
                                b"deng-password-very-long-2026",
                                bcrypt.gensalt(),
                            ).decode(),
                        },
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.previous_enabled = main.PILOT_AUTH_ENABLED
        self.previous_secure = main.PILOT_COOKIE_SECURE
        self.previous_quick_enabled = main.PILOT_QUICK_LOGIN_ENABLED
        self.previous_quick_remote = main.PILOT_QUICK_LOGIN_ALLOW_REMOTE
        self.previous_quick_username = main.PILOT_QUICK_LOGIN_USERNAME
        self.previous_quick_display_name = main.PILOT_QUICK_LOGIN_DISPLAY_NAME
        self.previous_access = main.pilot_access
        main.PILOT_AUTH_ENABLED = True
        main.PILOT_COOKIE_SECURE = True
        main.PILOT_QUICK_LOGIN_ENABLED = False
        main.PILOT_QUICK_LOGIN_ALLOW_REMOTE = False
        main.PILOT_QUICK_LOGIN_USERNAME = "ma-trial"
        main.PILOT_QUICK_LOGIN_DISPLAY_NAME = "马老师"
        main.pilot_access = PilotAccessManager(
            users_file=str(users_file),
            audit_file=str(root / "audit.jsonl"),
            lease_seconds=30,
        )
        self.client = TestClient(main.app, base_url="https://testserver")

    def tearDown(self):
        self.client.close()
        main.PILOT_AUTH_ENABLED = self.previous_enabled
        main.PILOT_COOKIE_SECURE = self.previous_secure
        main.PILOT_QUICK_LOGIN_ENABLED = self.previous_quick_enabled
        main.PILOT_QUICK_LOGIN_ALLOW_REMOTE = self.previous_quick_remote
        main.PILOT_QUICK_LOGIN_USERNAME = self.previous_quick_username
        main.PILOT_QUICK_LOGIN_DISPLAY_NAME = self.previous_quick_display_name
        main.pilot_access = self.previous_access
        self.temp_dir.cleanup()

    def login(self, client, username, password):
        return client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )

    def test_login_session_logout_and_protected_routes(self):
        self.assertEqual(self.client.get("/api/wall").status_code, 401)

        response = self.login(
            self.client,
            "ma-trial",
            "ma-password-very-long-2026",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)

        self.assertEqual(
            self.client.post("/api/cancel/not-running").status_code,
            423,
        )
        lease = self.client.post("/api/pilot/edit-lease/acquire")
        self.assertEqual(lease.status_code, 200)
        self.assertTrue(lease.json()["owned_by_me"])

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        session = self.client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertFalse(session.json()["authenticated"])

    def test_quick_login_uses_configured_default_account_without_password(self):
        main.PILOT_QUICK_LOGIN_ENABLED = True
        main.PILOT_QUICK_LOGIN_ALLOW_REMOTE = True

        session = self.client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertFalse(session.json()["authenticated"])
        self.assertTrue(session.json()["quick_login_enabled"])
        self.assertEqual(session.json()["default_username"], "ma-trial")
        self.assertEqual(session.json()["default_display_name"], "马老师")

        response = self.client.post("/api/auth/quick-login")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "ma-trial")
        self.assertEqual(response.json()["display_name"], "马老师")
        self.assertTrue(self.client.get("/api/auth/session").json()["authenticated"])

    def test_quick_login_is_hidden_when_disabled(self):
        session = self.client.get("/api/auth/session")
        self.assertFalse(session.json()["quick_login_enabled"])
        self.assertEqual(self.client.post("/api/auth/quick-login").status_code, 404)

    def test_quick_login_is_local_only_without_explicit_remote_opt_in(self):
        main.PILOT_QUICK_LOGIN_ENABLED = True
        session = self.client.get("/api/auth/session")
        self.assertFalse(session.json()["quick_login_enabled"])
        self.assertEqual(self.client.post("/api/auth/quick-login").status_code, 404)

    def test_only_one_user_can_hold_edit_lease(self):
        self.assertEqual(
            self.login(self.client, "ma-trial", "ma-password-very-long-2026").status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/pilot/edit-lease/acquire").status_code,
            200,
        )

        other = TestClient(main.app, base_url="https://testserver")
        try:
            self.assertEqual(
                self.login(other, "deng-trial", "deng-password-very-long-2026").status_code,
                200,
            )
            blocked = other.post("/api/pilot/edit-lease/acquire")
            self.assertEqual(blocked.status_code, 423)
            self.assertIn("马老师", blocked.json()["detail"])
        finally:
            other.close()

    def test_failed_login_is_rate_limited(self):
        for _ in range(5):
            response = self.login(self.client, "ma-trial", "wrong-password")
            self.assertEqual(response.status_code, 401)
        blocked = self.login(self.client, "ma-trial", "wrong-password")
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn("ma-trial", blocked.text)

    def test_concurrent_json_mutations_do_not_overwrite_each_other(self):
        target = Path(self.temp_dir.name) / "concurrent.json"
        target.write_text('{"values":[]}', encoding="utf-8")

        threads = [
            threading.Thread(
                target=main.mutate_json,
                args=(str(target), {"values": []}, lambda payload, value=value: payload["values"].append(value)),
            )
            for value in range(24)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(sorted(payload["values"]), list(range(24)))


if __name__ == "__main__":
    unittest.main()
