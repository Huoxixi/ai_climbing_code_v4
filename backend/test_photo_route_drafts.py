import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from core.photo_route_drafts import (DraftUpdate, PhotoBoardSpec, PhotoRouteDraft, PhotoRouteStore,
                                     atomic_json, create_photo_route_router)
from scripts.import_photo_route_evidence import register_evidence


class PhotoRouteDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PhotoRouteStore(Path(self.tmp.name))
        self.store.assets.mkdir()
        def asset(size, mode='RGBA'):
            path = Path(self.tmp.name) / 'image.png'
            Image.new(mode, size, 'white').save(path)
            data = path.read_bytes(); sha = hashlib.sha256(data).hexdigest()
            name = sha + '.png'; (self.store.assets / name).write_bytes(data)
            return dict(filename=name, sha256=sha, width=size[0], height=size[1])
        source = asset((1000, 1000))
        objects = [{"id": f"object-{i:02d}", "source_bbox_px": box, "cutout": asset(tuple(box[2:])),
                    "mask": source, "z_index": i} for i, box in enumerate(([100, 100, 100, 200], [600, 700, 200, 100]), 1)]
        atomic_json(self.store.catalog / 'sample.json', {"name": "样例", "color": "黄色", "source": {"original": source,
                    "working_dimensions": [1000, 1000], "algorithm": "fixture", "result_sha256": 'a'*64}, "objects": objects})
        app = FastAPI()
        @app.middleware('http')
        async def owner(request, call_next):
            request.state.pilot_user = SimpleNamespace(username=request.headers.get('x-test-owner', 'owner'))
            return await call_next(request)
        app.include_router(create_photo_route_router(self.store))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def create(self):
        response = self.client.post('/api/photo-routes/drafts/import', json={'extraction_id': 'sample'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def payload(self, draft):
        return {**{k: draft[k] for k in ('name', 'color', 'notes', 'original_grade', 'objects')}, 'expected_version': draft['version']}

    def test_spec_and_isotropic_y_inversion(self):
        spec = PhotoBoardSpec()
        self.assertEqual((spec.board_width_mm, spec.board_height_mm), (6200, 4100))
        self.assertEqual(spec.columns * spec.rows, 600)
        a, b = self.create()['objects']
        self.assertGreater(a['center_y_mm'], b['center_y_mm'])
        self.assertEqual(a['scale_mm_per_px'], b['scale_mm_per_px'])
        self.assertAlmostEqual(a['scale_mm_per_px'], 3800/700)
        self.assertAlmostEqual(a['center_y_mm'] + 100*a['scale_mm_per_px'], 3900)
        self.assertAlmostEqual(b['center_y_mm'] - 50*b['scale_mm_per_px'], 100)

    def test_import_is_idempotent_and_restart_preserves_edits(self):
        draft = self.create(); payload = self.payload(draft); payload['name'] = '新名称'
        saved = self.client.put(f"/api/photo-routes/drafts/{draft['id']}", json=payload).json()
        self.assertEqual(saved['version'], 2)
        self.assertEqual(self.create(), saved)
        self.assertEqual(PhotoRouteStore(self.store.root).get(draft['id'], 'owner'), saved)
        self.assertEqual(len(self.client.get('/api/photo-routes/drafts').json()), 1)

    def test_stale_write_does_not_overwrite(self):
        draft = self.create(); payload = self.payload(draft)
        url = f"/api/photo-routes/drafts/{draft['id']}"
        self.assertEqual(self.client.put(url, json=payload).status_code, 200)
        payload['name'] = 'stale'
        self.assertEqual(self.client.put(url, json=payload).status_code, 409)
        self.assertEqual(self.client.get(url).json()['name'], '样例')

    def test_parallel_writers_only_one_version_wins(self):
        draft = self.create(); outcomes = []
        def write():
            try: outcomes.append(self.store.update(draft['id'], 'owner', DraftUpdate(**self.payload(draft)))['version'])
            except HTTPException as exc: outcomes.append(exc.status_code)
        threads = [threading.Thread(target=write) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(outcomes), [2, 409])

    def test_assets_owner_isolation_and_hash_tampering(self):
        draft = self.create(); ref = draft['objects'][0]['cutout']; url = '/photo-route-assets/' + ref['filename']
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url, headers={'x-test-owner': 'other'}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/photo-routes/drafts/{draft['id']}", headers={'x-test-owner': 'other'}).status_code, 404)
        (self.store.assets / ref['filename']).write_bytes(b'tampered')
        self.assertEqual(self.client.get(url).status_code, 422)
        self.assertEqual(self.client.put(f"/api/photo-routes/drafts/{draft['id']}", json=self.payload(draft)).status_code, 422)

    def test_reject_paths_immutable_assets_and_outside_wall(self):
        self.assertEqual(self.client.post('/api/photo-routes/drafts/import', json={'extraction_id': '../sample'}).status_code, 422)
        draft = self.create(); url = f"/api/photo-routes/drafts/{draft['id']}"
        payload = self.payload(copy.deepcopy(draft)); payload['objects'][0]['cutout']['filename'] = '../../secret.png'
        self.assertEqual(self.client.put(url, json=payload).status_code, 422)
        payload = self.payload(copy.deepcopy(draft)); payload['objects'][0]['center_x_mm'] = -20
        self.assertEqual(self.client.put(url, json=payload).status_code, 422)
        payload = self.payload(copy.deepcopy(draft)); payload['objects'][0]['contour_status'] = 'needs_correction'
        self.assertEqual(self.client.put(url, json=payload).status_code, 422)
        payload = self.payload(copy.deepcopy(draft)); payload['objects'].append(payload['objects'][0])
        self.assertEqual(self.client.put(url, json=payload).status_code, 422)

    def test_roles_rotation_scale_and_layer_roundtrip(self):
        draft = self.create(); payload = self.payload(draft)
        obj = payload['objects'][0]; obj.update(center_x_mm=3000, center_y_mm=2000, rotation_deg=35, scale_mm_per_px=1.2, roles=['start','end'], z_index=9, kind='volume')
        saved = self.client.put(f"/api/photo-routes/drafts/{draft['id']}", json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['objects'][0], obj)

    def test_real_evidence_count_boundaries_and_fingerprints(self):
        evidence = Path(__file__).resolve().parents[1] / 'docs/photo-route-evidence'
        source_dir = Path(__file__).resolve().parents[3]
        if not (source_dir / '抱石路线1.jpg').exists():
            self.skipTest('local source photos are not part of the repository')
        for color, count in [('yellow', 12), ('blue', 10)]:
            extraction = register_evidence(self.store, evidence, source_dir, color)
            draft = self.store.import_draft(extraction, 'owner')
            self.assertEqual(len(draft['objects']), count)
            self.assertEqual(register_evidence(self.store, evidence, source_dir, color), extraction)
            if color == 'yellow': self.assertNotIn('object-09', [o['id'] for o in draft['objects']])
            else:
                self.assertIn('object-06', [o['id'] for o in draft['objects']])
                self.assertEqual([o['id'] for o in draft['objects'] if o['contour_status'] == 'needs_correction'], ['object-03','object-07'])

    def test_existing_auth_and_edit_lease_protect_new_endpoints(self):
        import main
        from core.pilot_access import EditLeaseError
        access = Mock()
        access.session_user.return_value = None
        with patch.object(main, 'PILOT_AUTH_ENABLED', True), patch.object(main, 'pilot_access', access):
            with TestClient(main.app) as client:
                self.assertEqual(client.get('/api/photo-routes/drafts').status_code, 401)
                self.assertEqual(client.get('/photo-route-assets/' + 'a'*64 + '.png').status_code, 401)
                access.session_user.return_value = SimpleNamespace(username='owner')
                access.require_lease.side_effect = EditLeaseError('编辑权失效')
                self.assertEqual(client.post('/api/photo-routes/drafts/import', json={'extraction_id':'sample'}).status_code, 423)


if __name__ == '__main__':
    unittest.main()
