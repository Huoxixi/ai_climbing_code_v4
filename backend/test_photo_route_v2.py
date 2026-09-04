import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.photo_route_analysis import (assess_capture_quality, board_holes, compute_homography,
                                       map_point, nearest_hole)
from core.photo_route_v2 import (ColorRouteCreate, PhotoRouteV2Store, RouteMemberInput,
                                 RouteUpdate, create_photo_route_v2_router)


class FakeJobs:
    def __init__(self): self.enqueued = []; self.cancelled = []
    def enqueue(self, job_id): self.enqueued.append(job_id)
    def cancel(self, job_id): self.cancelled.append(job_id)


def photo_bytes(width=1200, height=800):
    rng = np.random.default_rng(7)
    image = np.full((height, width, 3), (175, 185, 195), np.uint8)
    noise = rng.integers(-24, 25, image.shape, dtype=np.int16)
    image = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    cv2.circle(image, (300, 300), 65, (0, 210, 245), -1)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    return encoded.tobytes()


class PhotoRouteV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PhotoRouteV2Store(Path(self.tmp.name))
        self.jobs = FakeJobs()
        app = FastAPI()
        @app.middleware('http')
        async def owner(request, call_next):
            request.state.pilot_user = SimpleNamespace(username=request.headers.get('x-test-owner', 'owner'))
            return await call_next(request)
        app.include_router(create_photo_route_v2_router(self.store, self.jobs))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def create_board(self):
        response = self.client.post('/api/photo-routes/v2/boards/upload',
                                    files={'photo': ('board.jpg', photo_bytes(), 'image/jpeg')})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed_analysis(self, board_id, color='黄色'):
        ref_data = photo_bytes(120, 80)
        ref = self.store.save_asset(ref_data, 'jpg', 120, 80)
        self.store.set_analysis_result(board_id, {
            'calibration': {'matrix': [[6.2,0,0],[0,-5.125,4100],[0,0,1]], 'status':'confirmed'},
            'model_version': 'test',
            'objects': [{
                'id':'object-001','kind':'hold','color_group':color,
                'contour':[[280,280],[320,280],[320,320],[280,320]],
                'source_bbox_px':[280,280,40,40],'cutout':ref,'mask':ref,
                'center_x_mm':1800,'center_y_mm':1600,'rotation_deg':0,'scale_mm_per_px':5,
                'confidence':.95,'review_status':'confirmed',
                'anchors':[{'hole_id':'I9','x_mm':1800,'y_mm':1700,'confidence':.99,'confirmed':True}],
            }],
        })
        return self.store.get_board(board_id, 'owner')

    def test_grid_and_homography_are_deterministic(self):
        holes = board_holes()
        self.assertEqual(len(holes), 600)
        self.assertEqual((holes[0]['id'], holes[-1]['id']), ('A1', 'AD20'))
        matrix = compute_homography([[0,0],[100,0],[100,100],[0,100]],
                                    [[0,4100],[6200,4100],[6200,0],[0,0]])
        self.assertAlmostEqual(map_point(matrix, 50, 50)[0], 3100, places=4)
        self.assertEqual(nearest_hole(205, 103)[0]['id'], 'A1')

    def test_capture_gate_rejects_blur_and_upload_queues_job(self):
        blur = np.full((800, 1200, 3), 170, np.uint8)
        self.assertFalse(assess_capture_quality(blur).accepted)
        rejected = self.client.post('/api/photo-routes/v2/boards/upload',
                                    files={'photo': ('blur.jpg', cv2.imencode('.jpg', blur)[1].tobytes(), 'image/jpeg')})
        self.assertEqual(rejected.status_code, 422)
        created = self.create_board()
        self.assertEqual(created['board']['status'], 'processing')
        self.assertEqual(self.jobs.enqueued, [created['job']['id']])

    def test_object_anchor_route_validation_versions_and_history(self):
        created = self.create_board(); board = self.seed_analysis(created['board']['id'])
        obj = board['objects'][0]
        route = self.store.create_route_from_color('owner', ColorRouteCreate(
            board_version_id=board['id'], color_group='黄色', name='测试黄线'))
        invalid = self.client.put(f"/api/photo-routes/v2/routes/{route['id']}", json={
            'expected_version':1,'name':'测试黄线','difficulty':'V2','setter':'', 'notes':'',
            'members':[{'object_id':obj['id'],'roles':['start'],'tags':['动态'],'note':'注意核心'}],
        })
        self.assertEqual(invalid.status_code, 200)
        route = invalid.json()
        self.assertEqual(self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/complete").status_code, 422)
        saved = self.client.put(f"/api/photo-routes/v2/routes/{route['id']}", json={
            'expected_version':route['version'],'name':'测试黄线','difficulty':'V2','setter':'定线员', 'notes':'',
            'members':[{'object_id':obj['id'],'roles':['start','end'],'tags':['动态'],'note':'注意核心'}],
        }).json()
        completed = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/complete")
        self.assertEqual(completed.status_code, 200, completed.text)
        revisions = self.client.get(f"/api/photo-routes/v2/routes/{route['id']}/revisions").json()
        self.assertEqual(len(revisions), 1)
        restored = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/revisions/{saved['version']}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['status'], 'draft')

    def test_same_color_rule_and_conflict_protection(self):
        created = self.create_board(); board = self.seed_analysis(created['board']['id'])
        route = self.store.create_route_from_color('owner', ColorRouteCreate(
            board_version_id=board['id'], color_group='黄色'))
        obj = board['objects'][0]
        payload = {'expected_version':1,'name':'黄线','difficulty':'','setter':'甲','notes':'',
                   'members':[{'object_id':obj['id'],'roles':['start','end'],'tags':[],'note':''}]}
        self.assertEqual(self.client.put(f"/api/photo-routes/v2/routes/{route['id']}", json=payload).status_code, 200)
        self.assertEqual(self.client.put(f"/api/photo-routes/v2/routes/{route['id']}", json=payload).status_code, 409)
        self.assertEqual(self.client.get('/api/photo-routes/v2/routes', params={'color':'黄色'}).status_code, 200)

    def test_manual_add_split_merge_and_archive(self):
        created = self.create_board(); board = self.seed_analysis(created['board']['id'])
        added = self.client.post(f"/api/photo-routes/v2/boards/{board['id']}/objects", json={
            'expected_version':board['version'], 'kind':'hold', 'color_group':'黄色',
            'contour':[[500,300],[560,300],[560,360],[500,360]],
        })
        self.assertEqual(added.status_code, 200, added.text); board = added.json()
        new_object = next(item for item in board['objects'] if item['id'] != board['objects'][0]['id'])
        split = self.client.post(f"/api/photo-routes/v2/boards/{board['id']}/objects/{new_object['id']}/split", json={
            'expected_version':new_object['object_version'],
            'contours':[[[500,300],[530,300],[530,360],[500,360]],[[530,300],[560,300],[560,360],[530,360]]],
        })
        self.assertEqual(split.status_code, 200, split.text); board = split.json()
        halves = [item for item in board['objects'] if item['review_status'] == 'needs_review' and item['source_bbox_px'][0] >= 500]
        merge = self.client.post(f"/api/photo-routes/v2/boards/{board['id']}/objects/merge", json={
            'expected_version':board['version'], 'object_ids':[item['id'] for item in halves],
        })
        self.assertEqual(merge.status_code, 200, merge.text)
        route = self.store.create_route_from_color('owner', ColorRouteCreate(board_version_id=board['id'], color_group='黄色'))
        self.assertEqual(self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/archive").status_code, 200)
        self.assertEqual(self.client.get('/api/photo-routes/v2/routes').json(), [])
        self.assertEqual(self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/restore").status_code, 200)

    def test_cancel_retry_and_restart_recovery(self):
        created = self.create_board(); job = created['job']
        cancelled = self.client.post(f"/api/photo-routes/v2/jobs/{job['id']}/cancel")
        self.assertEqual(cancelled.json()['status'], 'cancelled')
        retried = self.client.post(f"/api/photo-routes/v2/jobs/{job['id']}/retry")
        self.assertEqual(retried.json()['attempt'], 2)
        self.store.mark_job(job['id'], 'running', '识别中', 30)
        restarted = PhotoRouteV2Store(self.store.root)
        recovered = restarted.get_job(job['id'], 'owner')
        self.assertEqual(recovered['status'], 'failed')
        self.assertIn('重启', recovered['error'])

    def test_legacy_import_keeps_read_only_backup(self):
        self.client.close(); self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name); (root/'assets').mkdir()
        data = photo_bytes(120, 80); sha = hashlib.sha256(data).hexdigest(); name = sha+'.jpg'
        (root/'assets'/name).write_bytes(data)
        ref = {'filename':name,'sha256':sha,'width':120,'height':80}
        draft = {'id':'d1','owner':'owner','extraction_id':'sample','name':'旧线路','color':'蓝色',
                 'original_grade':'V1','notes':'','version':2,'created_at':'2026-01-01T00:00:00+00:00',
                 'updated_at':'2026-01-02T00:00:00+00:00','source':{'original':ref},
                 'objects':[{'id':'o1','kind':'hold','source_bbox_px':[10,10,20,20], 'cutout':ref,'mask':ref,
                             'center_x_mm':200,'center_y_mm':100,'rotation_deg':0,'scale_mm_per_px':1,
                             'contour_status':'provisional','roles':['start']} ]}
        (root/'drafts.json').write_text(json.dumps([draft], ensure_ascii=False), encoding='utf-8')
        store = PhotoRouteV2Store(root)
        self.assertEqual(len(store.list_boards('owner')), 1)
        self.assertEqual(store.list_routes('owner')[0]['name'], '旧线路')
        self.assertTrue((root/'drafts.v1.readonly.json').exists())


if __name__ == '__main__': unittest.main()
