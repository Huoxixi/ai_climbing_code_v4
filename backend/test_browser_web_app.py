import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from browser_web_app import create_app

ROOT=Path(__file__).resolve().parents[1]


class BrowserWebsiteTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.tmp/browser-static-tests'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.root=Path(self.temp.name)
        self.static=self.root/'static'
        self.static.mkdir()
        (self.static/'browser-replay.html').write_text('<html>local replay</html>')
        self.installer=self.root/'test-installer.exe'
        self.installer.write_bytes(b'MZ-test-only')
        self.client=TestClient(create_app(static_root=self.static,installer=self.installer))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_public_entry_does_not_require_cookies_or_accounts(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn('local replay',response.text)
        self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(self.client.get('/browser-replay.html').status_code,200)
        self.assertEqual(self.client.get('/api/browser/health').json(),{'status':'ok','compute':'browser-only','accounts':False,'media_uploads':False})
        with patch.dict(os.environ,{'APP_ENV':'production'}):
            with TestClient(create_app(static_root=self.static,installer=self.installer)) as production:
                self.assertEqual(production.get('/').status_code,200)
        self.assertEqual(list(self.root.rglob('*.sqlite3')),[])

    def test_account_and_media_apis_have_been_removed(self):
        for route in ['session','login','register','setup','logout','profile','password','admin/users','admin/invites','history']:
            for method in ['GET','POST','PATCH']:
                with self.subTest(route=route,method=method):
                    response=self.client.request(method,'/api/browser/'+route,json={})
                    self.assertEqual(response.status_code,404)
                    self.assertNotIn('set-cookie',response.headers)
        for path in ['/api/save-board','/api/photo-routes','/api/local-replay/upload','/api/member/login']:
            self.assertEqual(self.client.post(path,json={}).status_code,404)

    def test_release_health_and_html_cache_policy(self):
        with patch.dict(os.environ,{'RELEASE_SHA':'a'*40}):
            response=self.client.get('/api/health')
        self.assertEqual(response.json()['release_sha'],'a'*40)
        self.assertEqual(response.json()['compute'],'browser-only')
        self.assertEqual(response.json()['status'],'success')
        self.assertEqual(self.client.get('/').headers['cache-control'],'no-store')
        for path in ['/docs','/openapi.json','/redoc']:
            self.assertEqual(self.client.get(path).status_code,404)

    def test_desktop_download_supports_ranges_and_missing_file(self):
        response=self.client.get('/downloads/climbing-assistant-windows.exe',headers={'Range':'bytes=0-1'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(response.content,b'MZ')
        self.assertIn('attachment',response.headers['content-disposition'])
        with TestClient(create_app(installer=self.root/'missing.exe',static_root=self.static)) as missing:
            self.assertEqual(missing.get('/downloads/climbing-assistant-windows.exe').status_code,404)
