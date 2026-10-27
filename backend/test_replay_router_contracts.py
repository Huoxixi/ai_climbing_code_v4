"""Frozen HTTP and registration contracts; opaque fixture files are never analyzed."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core import climb_replay as replay


SNAPSHOT = Path(__file__).parent / 'tests/fixtures/replay-router-contracts.json'
AUTH = {'x-contract-owner': 'alice'}
SOURCE_BYTES = b'opaque constructed source file; not real video'
COMPARISON_BYTES = b'opaque constructed comparison file; not real video'


def make_contract_app(root):
    store = replay.ClimbReplayStore(root / 'store')
    manager, coaching, template, actions = (Mock() for _ in range(4))
    store.coaching_manager, store.template_manager, store.action_manager = coaching, template, actions
    source, comparison = root / 'catalog.mp4', root / 'catalog-comparison.webm'
    source.write_bytes(SOURCE_BYTES)
    comparison.write_bytes(COMPARISON_BYTES)
    app = FastAPI(title='Replay router contracts', version='fixture')

    @app.middleware('http')
    async def identify(request: Request, call_next):
        if username := request.headers.get('x-contract-owner'):
            request.state.pilot_user = SimpleNamespace(username=username)
        return await call_next(request)

    router = replay.create_climb_replay_router(
        store, manager, coaching_manager=coaching, template_manager=template,
        test_video_cases=[{'id': 'catalog-case', 'path': source, 'comparison_path': comparison,
                           'label': '构造素材', 'description': '仅验证HTTP，不验证识别',
                           'comparison_route_color': '黄色', 'comparison_action_count': 7}],
    )
    app.include_router(router)
    return app, store, manager


def route_contract(app):
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif expand := getattr(route, 'effective_route_contexts', None):
            # Current FastAPI keeps included routers lazy; effective contexts
            # contain their actual prefixed paths, tags and generated IDs.
            routes.extend(context for context in expand() if isinstance(context.original_route, APIRoute))
    return [{
        'path': route.path, 'methods': sorted(route.methods), 'name': route.name,
        'tags': route.tags, 'status_code': route.status_code,
        'operation_id': route.operation_id, 'unique_id': route.unique_id,
        'include_in_schema': route.include_in_schema,
    } for route in routes]


class ReplayRouterContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Captured explicitly from the unchanged factory before the catalog move.
        # The test never rewrites its expected contract to accept a new schema.
        cls.expected = json.loads(SNAPSHOT.read_text(encoding='utf-8'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app, self.store, self.manager = make_contract_app(Path(self.temp.name))
        self.addCleanup(self.store.prepared_previews.close)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_registered_route_order_names_methods_tags_and_ids_are_frozen(self):
        routes = route_contract(self.app)
        self.assertGreater(len(routes), 0)
        registered = {(route['path'], tuple(route['methods'])) for route in routes}
        for path, method in (('/api/climb-replay/jobs', 'POST'),
                             ('/api/climb-replay/consent-policy', 'GET'),
                             ('/api/climb-replay/test-videos', 'GET'),
                             ('/api/climb-replay/test-videos/{case_id}/comparison', 'GET')):
            self.assertIn((path, (method,)), registered)
        self.assertEqual(routes, self.expected['routes'])

    def test_openapi_paths_operations_parameters_and_schemas_are_frozen(self):
        schema = self.app.openapi()
        self.assertIn('/api/climb-replay/jobs', schema['paths'])
        self.assertIn('/api/climb-replay/prepared-videos/{key}/start', schema['paths'])
        operations = [operation for path in schema['paths'].values()
                      for method, operation in path.items()
                      if method in {'get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace'}]
        self.assertGreater(len(operations), 0)
        self.assertTrue(all(operation.get('operationId') and operation.get('tags') for operation in operations))
        self.assertTrue(any(operation.get('parameters') for operation in operations))
        self.assertIn('ReplayUploadCreate', schema['components']['schemas'])
        self.assertEqual(schema, self.expected['openapi'])

    def test_authenticated_boundaries_preserve_unauthenticated_401(self):
        for path in ('consent-policy', 'test-video-info', 'test-videos', 'test-videos/catalog-case',
                     'test-videos/catalog-case/comparison', 'jobs'):
            with self.subTest(path=path):
                response = self.client.get('/api/climb-replay/' + path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {'detail': '请先登录'})
        response = self.client.post('/api/climb-replay/jobs',
            data={'route_color': '黄色'}, files={'video': ('fixture.mp4', SOURCE_BYTES, 'video/mp4')})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'detail': '请先登录'})
        self.manager.enqueue.assert_not_called()

    def test_current_consent_policy_wire_shape_is_frozen(self):
        response = self.client.get('/api/climb-replay/consent-policy', headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.expected['consent_policy'])

    def test_upload_consent_and_retention_errors_keep_status_and_text(self):
        for version, granted, expected_status, message in (
            (replay.REPLAY_CONSENT_VERSION, False, 422, '请先明确同意本次本地视频分析'),
            ('outdated-contract', True, 409, '数据处理告知已更新，请阅读最新说明并重新同意'),
        ):
            with self.subTest(version=version, granted=granted):
                response = self.client.post('/api/climb-replay/jobs', headers=AUTH,
                    data={'route_color': '黄色', 'consent_version': version, 'consent_granted': str(granted).lower()},
                    files={'video': ('fixture.mp4', SOURCE_BYTES, 'video/mp4')})
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json(), {'detail': message})
                response = self.client.post('/api/climb-replay/uploads', headers=AUTH, json={
                    'filename': 'fixture.mp4', 'content_type': 'video/mp4', 'size_bytes': len(SOURCE_BYTES),
                    'route_color': '黄色', 'consent_version': version, 'consent_granted': granted,
                })
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json(), {'detail': message})
        response = self.client.post('/api/climb-replay/jobs', headers=AUTH,
            data={'route_color': '黄色', 'consent_version': replay.REPLAY_CONSENT_VERSION,
                  'consent_granted': 'true', 'retention_mode': 'invalid-mode'},
            files={'video': ('fixture.mp4', SOURCE_BYTES, 'video/mp4')})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'detail': '请选择有效的视频保留方式'})
        self.manager.enqueue.assert_not_called()

    def test_multipart_legacy_delete_mode_still_keeps_the_original(self):
        response = self.client.post('/api/climb-replay/jobs', headers=AUTH,
            data={'route_color': '黄色', 'consent_version': replay.REPLAY_CONSENT_VERSION,
                  'consent_granted': 'true', 'retention_mode': 'delete_after_processing'},
            files={'video': ('fixture.mp4', SOURCE_BYTES, 'video/mp4')})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job['owner'], 'alice')
        self.assertEqual(job['media']['source_video']['retention_mode'], 'keep_private_original')
        self.assertEqual(job['consent_history'][-1]['event'], 'local_processing_granted')
        self.assertNotIn('source_path', job)
        self.manager.enqueue.assert_called_once_with(job['id'])

    def test_chunked_legacy_delete_mode_still_keeps_the_original(self):
        response = self.client.post('/api/climb-replay/uploads', headers=AUTH, json={
            'filename': 'fixture.mp4', 'content_type': 'video/mp4', 'size_bytes': len(SOURCE_BYTES),
            'route_color': '黄色', 'consent_version': replay.REPLAY_CONSENT_VERSION,
            'consent_granted': True, 'retention_mode': 'delete_after_processing',
        })
        self.assertEqual(response.status_code, 200, response.text)
        upload = '/api/climb-replay/uploads/' + response.json()['id']
        response = self.client.put(upload, headers={**AUTH, 'x-upload-offset': '0'}, content=SOURCE_BYTES)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(upload + '/complete', headers=AUTH)
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job['media']['source_video']['retention_mode'], 'keep_private_original')
        self.manager.enqueue.assert_called_once_with(job['id'])

    def test_catalog_metadata_wire_shape_and_no_private_paths(self):
        response = self.client.get('/api/climb-replay/test-videos', headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'items': [{
            'id': 'catalog-case', 'label': '构造素材', 'description': '仅验证HTTP，不验证识别',
            'filename': 'catalog.mp4', 'size_bytes': len(SOURCE_BYTES),
            'comparison_available': True, 'comparison_route_color': '黄色',
            'comparison_action_count': 7, 'source_url': None, 'usage': 'local_acceptance_only',
        }]})
        response = self.client.get('/api/climb-replay/test-video-info', headers=AUTH)
        self.assertEqual(response.json(), {
            'available': True, 'filename': 'catalog.mp4', 'size_bytes': len(SOURCE_BYTES),
            'source_url': None, 'usage': 'local_acceptance_only',
        })

    def test_catalog_media_preserves_bytes_headers_download_and_range(self):
        source = '/api/climb-replay/test-videos/catalog-case'
        for path, content, media_type, disposition in (
            (source, SOURCE_BYTES, 'video/mp4', 'attachment; filename="catalog.mp4"'),
            ('/api/climb-replay/test-video', SOURCE_BYTES, 'video/mp4', 'attachment; filename="catalog.mp4"'),
            (source + '/comparison', COMPARISON_BYTES, 'video/webm', None),
            (source + '/comparison?download=true', COMPARISON_BYTES, 'video/webm',
             'attachment; filename="catalog-comparison.webm"'),
        ):
            with self.subTest(path=path):
                response = self.client.get(path, headers=AUTH)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, content)
                self.assertEqual(response.headers['content-type'], media_type)
                self.assertEqual(response.headers['cache-control'], 'private, no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertEqual(response.headers.get('content-disposition'), disposition)
        response = self.client.get(source, headers={**AUTH, 'Range': 'bytes=0-3'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, SOURCE_BYTES[:4])
        self.assertEqual(response.headers['content-range'], f'bytes 0-3/{len(SOURCE_BYTES)}')

    def test_unknown_catalog_ids_remain_authenticated_not_found(self):
        for suffix in ('absent', 'absent/comparison'):
            response = self.client.get('/api/climb-replay/test-videos/' + suffix, headers=AUTH)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {'detail': '本机测试视频不存在'})


if __name__ == '__main__':
    unittest.main()
