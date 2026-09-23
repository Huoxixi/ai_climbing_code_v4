import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.photo_route_analysis import (assess_capture_quality, board_holes, compute_homography, detect_photo_hole_grid,
                                       map_point, nearest_hole, projected_bbox_scale_mm_per_px)
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
            'calibration': {'matrix': [[3.4167,0,0],[0,-7.75,6200],[0,0,1]], 'status':'confirmed'},
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
        self.assertEqual((holes[0]['id'], holes[-1]['id']), ('A1', 'T30'))
        matrix = compute_homography([[0,0],[100,0],[100,100],[0,100]],
                                    [[0,6200],[4100,6200],[4100,0],[0,0]])
        self.assertAlmostEqual(map_point(matrix, 50, 50)[0], 2050, places=4)
        self.assertEqual(nearest_hole(205, 103)[0]['id'], 'A1')
        self.assertAlmostEqual(projected_bbox_scale_mm_per_px([[2,0,0],[0,-8,1000],[0,0,1]], [10,20,100,50]), 4)

    def test_real_hole_lattice_fit_survives_missing_and_occluded_points(self):
        image = np.full((1200, 720, 3), 188, np.uint8)
        origin = np.asarray([22.0, 43.0]); column = np.asarray([34.0, 2.0]); row = np.asarray([-1.8, 36.0])
        for y in range(30):
            for x in range(20):
                if not (6 <= x <= 11 and 8 <= y <= 14):
                    point = origin + x * column + y * row
                    cv2.circle(image, tuple(np.rint(point).astype(int)), 2, (38,38,38), -1)
        cv2.rectangle(image, (205,330), (410,575), (235,205,30), -1)
        fitted = detect_photo_hole_grid(image)
        self.assertIsNotNone(fitted)
        self.assertGreater(fitted['detected_hole_count'], 250)
        mapped = map_point(fitted['matrix'], *origin)
        self.assertLess(abs(mapped[0]-200), 35)
        self.assertLess(abs(mapped[1]-5900), 35)

    def test_processing_config_persists_without_rewriting_completed_results(self):
        board=self.create_board()['board']; original=board['quality']
        config={'color_version':'interior-v3','boundary_version':'grabcut-band-v1'}
        self.store.set_analysis_result(board['id'],{'calibration':{},'model_version':'test',
            'processing_config':config,'objects':[]})
        reopened=PhotoRouteV2Store(Path(self.tmp.name)).get_board(board['id'],'owner')
        self.assertEqual(reopened['quality']['processing_config'],config)
        for key,value in original.items():self.assertEqual(reopened['quality'][key],value)
        self.store.set_analysis_result(board['id'],{'calibration':{},'model_version':'new',
            'processing_config':{'color_version':'interior-v4'},'objects':[]})
        self.assertEqual(self.store.get_board(board['id'],'owner')['quality']['processing_config'],config)

    def test_capture_gate_rejects_blur_and_upload_queues_job(self):
        blur = np.full((800, 1200, 3), 170, np.uint8)
        self.assertFalse(assess_capture_quality(blur).accepted)
        rejected = self.client.post('/api/photo-routes/v2/boards/upload',
                                    files={'photo': ('blur.jpg', cv2.imencode('.jpg', blur)[1].tobytes(), 'image/jpeg')})
        self.assertEqual(rejected.status_code, 422)
        created = self.create_board()
        self.assertEqual(created['board']['status'], 'processing')
        self.assertEqual(self.jobs.enqueued, [created['job']['id']])

    def test_board_returns_recognition_job_for_resume_without_exposing_payload(self):
        created = self.create_board()
        board_id, job_id = created['board']['id'], created['job']['id']
        for board in (self.store.get_board(board_id, 'owner'), self.store.list_boards('owner')[0]):
            self.assertEqual(board['latest_job']['id'], job_id)
            self.assertEqual(board['latest_job']['status'], 'queued')
            self.assertNotIn('payload_json', board['latest_job'])
        self.store.mark_job(job_id, 'failed', 'failed', 20, 'test failure')
        self.assertEqual(self.store.get_board(board_id, 'owner')['latest_job']['status'], 'failed')
        self.assertEqual(self.store.list_boards('another-owner'), [])

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

    def test_route_accepts_multiple_private_photos_and_videos_with_v1_limits(self):
        created = self.create_board(); board = self.seed_analysis(created['board']['id'])
        route = self.store.create_route_from_color('owner', ColorRouteCreate(
            board_version_id=board['id'], color_group='黄色', name='黄色横移'))
        photo = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/media",
                                 files={'media': ('try-1.jpg', photo_bytes(120, 80), 'image/jpeg')})
        self.assertEqual(photo.status_code, 200, photo.text)
        videos = []
        for index in range(2):
            response = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/media",
                                        files={'media': (f'try-{index}.mp4', b'local-test-video-'+bytes([index]), 'video/mp4')})
            self.assertEqual(response.status_code, 200, response.text); videos.append(response.json())
        overflow = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/media",
                                    files={'media': ('try-3.mp4', b'another-video', 'video/mp4')})
        self.assertEqual(overflow.status_code, 422)
        saved = self.client.get(f"/api/photo-routes/v2/routes/{route['id']}").json()
        self.assertEqual([item['kind'] for item in saved['media']].count('photo'), 1)
        self.assertEqual([item['kind'] for item in saved['media']].count('video'), 2)
        asset_url = f"/api/photo-routes/v2/assets/{videos[0]['asset']['filename']}"
        self.assertEqual(self.client.get(asset_url).status_code, 200)
        self.assertEqual(self.client.get(asset_url, headers={'x-test-owner':'another-owner'}).status_code, 404)

    def test_heic_board_and_route_photo_are_converted_by_server(self):
        register_heif_opener()
        source = cv2.imdecode(np.frombuffer(photo_bytes(), np.uint8), cv2.IMREAD_COLOR)
        encoded = io.BytesIO()
        Image.fromarray(cv2.cvtColor(source, cv2.COLOR_BGR2RGB)).save(encoded, format='HEIF')
        heic = encoded.getvalue()
        upload = self.client.post('/api/photo-routes/v2/boards/upload',
                                  files={'photo': ('wall.heic', heic, 'image/heic')})
        self.assertEqual(upload.status_code, 200, upload.text)
        board = upload.json()['board']
        self.assertTrue(board['original_asset']['filename'].endswith('.jpg'))
        board = self.seed_analysis(board['id'])
        route = self.store.create_route_from_color('owner', ColorRouteCreate(
            board_version_id=board['id'], color_group='黄色'))
        root = f"/api/photo-routes/v2/routes/{route['id']}/media/uploads"
        started = self.client.post(root, json={
            'filename': 'attempt.heic', 'content_type': 'image/heic', 'size_bytes': len(heic),
        })
        self.assertEqual(started.status_code, 200, started.text)
        upload_id = started.json()['id']
        self.client.put(f'{root}/{upload_id}', content=heic, headers={'x-upload-offset': '0'})
        completed = self.client.post(f'{root}/{upload_id}/complete')
        self.assertEqual(completed.status_code, 200, completed.text)
        photo = completed.json()
        self.assertEqual(photo['mime_type'], 'image/jpeg')
        self.assertTrue(photo['asset']['filename'].endswith('.jpg'))
        self.assertEqual(Image.open(io.BytesIO(self.client.get(
            f"/api/photo-routes/v2/assets/{photo['asset']['filename']}").content)).format, 'JPEG')
        direct = self.client.post(f"/api/photo-routes/v2/routes/{route['id']}/media",
                                  files={'media': ('second.heif', heic, 'application/octet-stream')})
        self.assertEqual(direct.status_code, 200, direct.text)
        self.assertEqual(direct.json()['mime_type'], 'image/jpeg')
        self.assertTrue(direct.json()['asset']['filename'].endswith('.jpg'))

    def test_route_media_supports_proxy_safe_chunk_uploads(self):
        created = self.create_board(); board = self.seed_analysis(created['board']['id'])
        route = self.store.create_route_from_color('owner', ColorRouteCreate(
            board_version_id=board['id'], color_group='黄色', name='分片视频'))
        content = b'chunk-one-' + b'chunk-two'
        root = f"/api/photo-routes/v2/routes/{route['id']}/media/uploads"
        started = self.client.post(root, json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
        })
        self.assertEqual(started.status_code, 200, started.text)
        upload_id = started.json()['id']
        first = self.client.put(f'{root}/{upload_id}', content=content[:10], headers={'x-upload-offset':'0'})
        self.assertEqual(first.json()['offset'], 10)
        second = self.client.put(f'{root}/{upload_id}', content=content[10:], headers={'x-upload-offset':'10'})
        self.assertTrue(second.json()['complete'])
        completed = self.client.post(f'{root}/{upload_id}/complete')
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()['size_bytes'], len(content))
        asset_url = f"/api/photo-routes/v2/assets/{completed.json()['asset']['filename']}"
        self.assertEqual(self.client.get(asset_url).content, content)

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
