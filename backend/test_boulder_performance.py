"""Constructed data only: cache isolation, upload availability and regressions."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from core.climb_replay import ClimbReplayStore, REPLAY_CONSENT_VERSION, create_climb_replay_router, _atomic_json
from core.photo_route_workflow import workflow_router


class ReplayCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ClimbReplayStore(Path(self.temp.name))
        self.job = {'id': 'sample', 'owner': 'owner', 'status': 'succeeded',
                    'created_at': '2026-10-09', 'progress': 100,
                    'input_path': 'private-path', 'result': {'pose_samples': [], 'attempt': {}}}
        _atomic_json(self.store._path('sample'), self.job)

    def test_repeated_get_and_list_avoid_read_and_projection(self):
        expected = self.store._public(self.job)
        with patch.object(self.store, '_read', wraps=self.store._read) as read:
            with patch.object(self.store, '_public', wraps=self.store._public) as public:
                self.assertEqual(self.store.get('sample', 'owner'), expected)
                self.assertEqual(self.store.get('sample', 'owner'), expected)
                self.assertEqual(self.store.list('owner'), [expected])
                self.assertEqual(read.call_count, 1)
                self.assertEqual(public.call_count, 1)

    def test_owner_and_return_value_isolation(self):
        value = self.store.get('sample', 'owner')
        value['result']['pose_samples'].append({'modified': True})
        self.assertEqual(self.store.get('sample', 'owner')['result']['pose_samples'], [])
        with self.assertRaises(HTTPException) as failure:
            self.store.get('sample', 'other')
        self.assertEqual(failure.exception.status_code, 404)
        self.assertEqual(self.store.list('other'), [])
        self.assertNotIn('input_path', self.store.get('sample', 'owner'))
        self.assertIn('input_path', self.store.get('sample', 'owner', private=True))

    def test_atomic_update_external_replace_and_delete_invalidate(self):
        self.store.get('sample', 'owner')
        self.store.update('sample', progress=50)
        self.assertEqual(self.store.get('sample', 'owner')['progress'], 50)
        replacement = {**self.job, 'owner': 'other', 'progress': 25}
        _atomic_json(self.store._path('sample'), replacement)
        self.assertEqual(self.store.get('sample', 'other')['progress'], 25)
        self.assertEqual(self.store.list('owner'), [])
        self.store._path('sample').unlink()
        self.assertEqual(self.store.list('other'), [])
        with self.assertRaises(HTTPException):
            self.store.get('sample', 'other')
        self.assertEqual(self.store._public_cache_bytes, 0)

    def test_entry_and_byte_limits(self):
        self.store._public_cache_entries = 2
        for index in range(5):
            ident = f'job{index}'
            _atomic_json(self.store._path(ident), {**self.job, 'id': ident})
            self.store.get(ident, 'owner')
        self.assertEqual(list(self.store._public_cache), ['job3', 'job4'])
        self.assertEqual(self.store._public_cache_bytes, sum(len(v[2]) for v in self.store._public_cache.values()))
        self.store._public_cache_limit = 1
        self.store.get('sample', 'owner')
        self.assertNotIn('sample', self.store._public_cache)


class UploadAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_responds_while_photo_processing_is_blocked(self):
        started, release = threading.Event(), threading.Event()
        def upload(*args):
            started.set()
            if not release.wait(3):
                raise RuntimeError('test processing timed out')
            return {'id': 'sample'}
        app = FastAPI()
        @app.middleware('http')
        async def owner(request: Request, call_next):
            request.state.pilot_user = SimpleNamespace(username='owner')
            return await call_next(request)
        @app.get('/api/health')
        async def health():
            return {'status': 'success'}
        app.include_router(workflow_router(SimpleNamespace(upload=upload)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            pending = asyncio.create_task(client.post('/api/photo-routes/workflow/upload',
                data={'request_id': 'sample'}, files={'photo': ('photo.jpg', b'constructed', 'image/jpeg')}))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                response = await asyncio.wait_for(client.get('/api/health'), timeout=1)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(pending.done())
            finally:
                release.set()
                response = await pending
            self.assertEqual(response.status_code, 200)


class ReplayUploadTests(unittest.TestCase):
    def test_multipart_and_chunked_upload_preserve_skeleton_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ClimbReplayStore(Path(directory))
            manager = SimpleNamespace(ensure_capacity=Mock(), enqueue=Mock())
            app = FastAPI()
            @app.middleware('http')
            async def owner(request: Request, call_next):
                request.state.pilot_user = SimpleNamespace(username='owner')
                return await call_next(request)
            app.include_router(create_climb_replay_router(store, manager))
            try:
                with TestClient(app) as client:
                    for skip in (False, True):
                        response = client.post('/api/climb-replay/jobs', data={
                            'route_color': '' if skip else '绿色', 'skip_holds': str(skip).lower(),
                            'consent_version': REPLAY_CONSENT_VERSION, 'consent_granted': 'true'},
                            files={'video': ('sample.mp4', b'constructed-video', 'video/mp4')})
                        self.assertEqual(response.status_code, 202, response.text)
                        job = store.get(response.json()['id'], 'owner', private=True)
                        self.assertEqual(job['consent_history'][-1]['skip_holds'], skip)
                    content = b'constructed-video'
                    response = client.post('/api/climb-replay/uploads', json={
                        'filename': 'sample.mp4', 'content_type': 'video/mp4', 'size_bytes': len(content),
                        'skip_holds': True, 'consent_version': REPLAY_CONSENT_VERSION, 'consent_granted': True})
                    self.assertEqual(response.status_code, 200, response.text)
                    uid = response.json()['id']
                    response = client.put(f'/api/climb-replay/uploads/{uid}', content=content, headers={'x-upload-offset': '0'})
                    self.assertEqual(response.status_code, 200, response.text)
                    response = client.post(f'/api/climb-replay/uploads/{uid}/complete')
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertTrue(store.get(response.json()['id'], 'owner', private=True)['consent_history'][-1]['skip_holds'])
                    self.assertEqual(manager.enqueue.call_count, 3)
            finally:
                for name in ('action_manager', 'template_manager', 'coaching_manager'):
                    getattr(store, name).close()


if __name__ == '__main__':
    unittest.main()
