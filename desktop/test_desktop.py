import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import FileResponse

from desktop.paths import resolve_paths, isolated_environment
from desktop.server import create_app
from desktop.launcher import SingleInstance, verify_resources


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = resolve_paths(install=root / "程序 空格", user=root / "独立 用户")
        self.paths.prepare()
        ui = self.paths.install / "frontend/dist"
        ui.mkdir(parents=True)
        (ui / "index.html").write_text("desktop index", encoding="utf-8")
        self.asset = self.paths.data / "video.mp4"
        self.asset.write_bytes(b"0123456789" * 10)
        backend = FastAPI()
        @backend.get('/api/health')
        def health():
            return {'ok': True}
        @backend.get('/api/video')
        def video():
            return FileResponse(self.asset, media_type="video/mp4")
        self.client = TestClient(create_app(self.paths, "test-instance", "http://127.0.0.1:51234", backend=backend), base_url="http://127.0.0.1:51234")

    def tearDown(self):
        self.temp.cleanup()

    def bootstrap(self):
        self.assertEqual(self.client.get('/desktop/bootstrap/test-instance').status_code, 200)

    def test_all_resources_require_instance(self):
        for url in ('/', '/api/health', '/api/video', '/desktop/status', '/images/a.png'):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_bootstrap_and_media_range(self):
        self.bootstrap()
        self.assertTrue(self.client.get('/api/health').json()['ok'])
        response = self.client.get('/api/video', headers={'Range': 'bytes=10-19'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'0123456789')
        self.assertEqual(response.headers['content-range'], 'bytes 10-19/100')

    def test_csrf_and_dns_rebinding_blocked(self):
        self.bootstrap()
        for headers in ({'Origin': 'https://outside.example'}, {'Host': 'attacker.example'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}):
            self.assertEqual(self.client.get('/api/health', headers=headers).status_code, 403)
            self.assertEqual(self.client.put('/desktop/cloud', headers=headers, json={}).status_code, 403)

    def test_same_origin_allowed(self):
        self.bootstrap()
        self.assertEqual(self.client.get('/api/health', headers={'Origin': 'http://127.0.0.1:51234', 'Sec-Fetch-Site': 'same-origin'}).status_code, 200)

    def test_lifespan_enters_and_exits(self):
        with self.client:
            self.bootstrap()
            self.assertEqual(self.client.get('/api/health').status_code, 200)

    def test_no_unknown_api_spa_fallback(self):
        self.bootstrap()
        self.assertEqual(self.client.get('/api/missing').status_code, 404)

    def test_bootstrap_cookie_is_private_and_session_scoped(self):
        response = self.client.get('/desktop/bootstrap/test-instance', follow_redirects=False)
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertNotIn('Max-Age', cookie)
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')

    def test_environment_does_not_inherit_development_secrets(self):
        inherited = {"ALIBABA_CLOUD_ACCESS_KEY_ID": "fake-development", "SUPABASE_URL": "fake",
                     "PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT": "outside", "CLIMB_REPLAY_TEST_VIDEOS": "fake",
                     "PYTHONPATH": "outside", "LOCALAPPDATA": str(self.paths.user)}
        env = isolated_environment(self.paths, inherited)
        for key in ("ALIBABA_CLOUD_ACCESS_KEY_ID", "SUPABASE_URL", "CLIMB_REPLAY_TEST_VIDEOS"):
            self.assertNotIn(key, env)
        self.assertNotIn("outside", env['PYTHONPATH'])
        self.assertEqual(env['PYTHON_DOTENV_DISABLED'], '1')
        self.assertEqual(env['LOCAL_ONLY'], 'true')
        self.assertNotIn('.local', env['PHOTO_ROUTE_DATA_DIR'])

    def test_private_and_install_data_rejected(self):
        for target in (self.paths.install, self.paths.install / 'data', self.paths.user / '.local/data'):
            with self.assertRaises(RuntimeError):
                resolve_paths(install=self.paths.install, user=target)

    def test_single_instance_unlock_after_close(self):
        first, second = SingleInstance(self.paths), SingleInstance(self.paths)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_resource_corruption_rejected(self):
        resource = self.paths.install / 'frontend/dist/index.html'
        import hashlib
        record = {'path': 'frontend/dist/index.html', 'sha256': hashlib.sha256(resource.read_bytes()).hexdigest()}
        (self.paths.install / 'resources.json').write_text(json.dumps({'critical': [record]}))
        verify_resources(self.paths)
        resource.write_text('corrupt')
        with self.assertRaises(RuntimeError):
            verify_resources(self.paths)

    def test_cloud_keys_not_returned_or_logged(self):
        self.bootstrap()
        with patch('desktop.credentials.save') as save:
            response = self.client.put('/desktop/cloud', json={'DASHSCOPE_API_KEY': 'fake-key'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('fake-key', response.text)
            save.assert_called_once()
        with patch('desktop.credentials.load', return_value={'DASHSCOPE_API_KEY': 'fake-key'}):
            response = self.client.get('/desktop/status')
            self.assertTrue(response.json()['action_configured'])
            self.assertNotIn('fake-key', response.text)

    def test_settings_error_does_not_echo_payload(self):
        self.bootstrap()
        with patch('desktop.credentials.save', side_effect=ValueError('fake-key')):
            response = self.client.put('/desktop/cloud', json={'DASHSCOPE_API_KEY': 'fake-key'})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('fake-key', response.text)


if __name__ == '__main__':
    unittest.main()
