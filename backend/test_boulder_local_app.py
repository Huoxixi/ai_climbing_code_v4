"""Isolated local application contract; never uses a real profile or model API."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient


class BoulderLocalTests(unittest.TestCase):
    def test_retained_workflows_removed_setter_routes_and_preserved_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'photos'
            asset = root / 'assets/original.jpg'
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b'constructed private photo')
            with patch.dict(os.environ, {'LOCAL_ONLY':'true','PHOTO_ROUTE_DATA_DIR':str(root),'CLIMB_REPLAY_TEST_VIDEOS':'[]'}):
                spec = importlib.util.spec_from_file_location('isolated_boulder_app', Path(__file__).with_name('boulder_local_app.py'))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                with TestClient(module.app) as client:
                    for path in ('/api/health','/api/auth/session','/api/photo-routes/workflow/current','/api/photo-routes/v2/routes','/api/climb-replay/jobs'):
                        self.assertEqual(client.get(path).status_code,200,path)
                    for path in ('/api/my-boards','/api/holds/mapping','/api/standard-board/routes','/api/generate','/api/simulation/profiles','/api/ai/experiments','/api/settings/replay-vision','/api/settings/vision'):
                        self.assertEqual(client.get(path).status_code,404,path)
                    self.assertEqual(client.get('/api/auth/session').json()['username'],'owner')
                    self.assertEqual(client.post('/api/auth/logout').status_code,200)
                    self.assertEqual(client.post('/api/auth/logout',headers={'Origin':'http://foreign.invalid'}).status_code,403)
                    self.assertEqual(asset.read_bytes(),b'constructed private photo')
                    self.assertEqual(client.post('/api/climb-replay/jobs/nonexistent/actions',json={'cloud_consent':True}).status_code,410)
                    self.assertFalse(any('/coaching' in path for path in module.app.openapi()['paths']))
                    self.assertTrue(any('/holds/editor' in path for path in module.app.openapi()['paths']))


if __name__ == '__main__':
    unittest.main()
