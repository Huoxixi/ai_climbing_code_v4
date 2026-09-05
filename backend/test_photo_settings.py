import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.photo_route_settings import get_visual_key, settings_router, test_connection, MODEL


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        app = FastAPI()
        @app.middleware('http')
        async def identity(request, call_next):
            request.state.pilot_user = SimpleNamespace(username=request.headers.get('x-test-owner','owner'))
            return await call_next(request)
        app.include_router(settings_router(self.root))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_save_persists_without_echo_and_is_scoped_to_owner(self):
        key = 'sk-test-only-not-real'
        result = self.client.put('/api/settings/vision', json={'api_key':key})
        self.assertEqual(result.status_code,200)
        self.assertNotIn(key,result.text)
        self.assertEqual(get_visual_key(self.root,'owner'),key)
        with patch.dict('os.environ',{'PHOTO_ROUTE_VISION_KEY':'','DEEPSEEK_API_KEY':''}):
            self.assertFalse(self.client.get('/api/settings/vision',headers={'x-test-owner':'other'}).json()['configured'])
        self.assertTrue(self.client.get('/api/settings/vision').json()['configured'])
        self.assertEqual(result.headers['cache-control'],'no-store')

    def test_invalid_input_is_never_echoed(self):
        secret = 'sk-secret-with invalid\ncharacters'
        result = self.client.put('/api/settings/vision',json={'api_key':secret})
        self.assertEqual(result.status_code,422)
        self.assertNotIn('sk-secret',result.text)

    def test_connection_really_requests_vision_and_does_not_save_input(self):
        seen=[]
        def remote(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'circle'}}]})
        with httpx.Client(transport=httpx.MockTransport(remote)) as client:
            result=test_connection('sk-test-only',client=client)
        self.assertTrue(result['connected'])
        self.assertEqual(seen[0]['model'],MODEL)
        self.assertEqual(seen[0]['messages'][0]['content'][1]['type'],'image_url')
        self.assertFalse(list(self.root.glob('**/*.json')))

    def test_upstream_failure_is_sanitized_and_timeout_is_distinct(self):
        for status in [401,402,403,429,500]:
            with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(status,json={'error':'secret upstream details'}))) as client:
                result=test_connection('sk-test-only',client=client)
            self.assertFalse(result['connected']);self.assertNotIn('secret',json.dumps(result))
        def timeout(request):raise httpx.ReadTimeout('secret')
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            self.assertIn('超时',test_connection('sk-test-only',client=client)['message'])


if __name__ == '__main__':unittest.main()
