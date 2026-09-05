import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from core.photo_route_v2 import PhotoRouteV2Store
from core.photo_route_workflow import PhotoWorkflow, Change, Notes
from core.photo_route_analysis import analyze_board_photo
from core.photo_route_vision import review_objects
from test_photo_route_v2 import photo_bytes


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=PhotoRouteV2Store(Path(self.tmp.name));self.flow=PhotoWorkflow(self.store,start=False)
    def tearDown(self):self.flow.close();self.tmp.cleanup()
    def palette(self):
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes());self.flow.process(value['id']);return self.flow.get(value['id'],'owner')
    def ready(self):
        value=self.palette();value=self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))
        def local(path,root,**kwargs):
            return analyze_board_photo(path,root,coarse_only=True)
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=local), patch.dict('os.environ',{'DEEPSEEK_API_KEY':'','PHOTO_ROUTE_VISION_KEY':''}):self.flow.process(value['id'])
        return self.flow.get(value['id'],'owner')
    def test_confirmation_is_idempotent_and_one_current_route(self):
        sid=uuid.uuid4().hex;data=photo_bytes()
        a=self.flow.upload('owner',sid,'sample.jpg',data)
        self.assertEqual(a['id'],self.flow.upload('owner',sid,'sample.jpg',data)['id'])
        with self.assertRaises(HTTPException) as error:self.flow.upload('owner','another','sample.jpg',data)
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(HTTPException):self.flow.get(sid,'other')
    def test_palette_survives_reopen_and_selected_color_is_single(self):
        value=self.palette();self.assertEqual(value['status'],'awaiting_color');self.assertIn('黄色',value['colors'])
        restored=PhotoWorkflow(self.store,start=False);self.assertEqual(restored.current('owner')['id'],value['id'])
        self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))
        with self.assertRaises(HTTPException):self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))
    def test_ready_default_members_save_without_holes_roles_setter(self):
        value=self.ready();self.assertEqual(value['status'],'ready');self.assertTrue(value['route']['members']);self.assertEqual(value['ai']['status'],'unavailable')
        done=self.flow.update(value['id'],'owner',Change(version=value['version']),'save')
        self.assertEqual(done['status'],'saved');self.assertEqual(done['route']['status'],'completed');self.assertIsNone(self.flow.current('owner'))
        result=self.flow.notes(done['route_id'],'owner',Notes(version=done['route']['version'],name='黄色测试',notes='类型和动作自由填写',members=done['route']['members']))
        self.assertEqual(result['notes'],'类型和动作自由填写');self.assertEqual(len(self.store.revisions(result['id'],'owner')),2)
    def test_remove_readd_and_stale_writes(self):
        value=self.ready();ids=[m['object_id'] for m in value['route']['members']]
        empty=self.flow.update(value['id'],'owner',Change(version=value['version'],member_ids=[]),'members')
        self.assertTrue(empty['board']['objects']);self.assertFalse(empty['route']['members'])
        with self.assertRaises(HTTPException):self.flow.update(value['id'],'owner',Change(version=empty['version']),'save')
        with self.assertRaises(HTTPException):self.flow.update(value['id'],'owner',Change(version=value['version'],member_ids=ids),'members')
        readded=self.flow.update(value['id'],'owner',Change(version=empty['version'],member_ids=ids),'members');self.assertEqual(len(readded['route']['members']),len(ids))
    def test_retry_does_not_duplicate_route_or_erase_selection(self):
        value=self.ready();ids=[m['object_id'] for m in value['route']['members']]
        value=self.flow.update(value['id'],'owner',Change(version=value['version'],member_ids=ids[:1]),'members')
        retried=self.flow.update(value['id'],'owner',Change(version=value['version']),'retry')
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'','PHOTO_ROUTE_VISION_KEY':''}):self.flow.process(value['id'])
        result=self.flow.get(value['id'],'owner');self.assertEqual(result['route_id'],value['route_id']);self.assertEqual(len(result['route']['members']),1)
    def test_abandon_preserves_photo_and_prevents_late_result(self):
        value=self.palette();abandoned=self.flow.update(value['id'],'owner',Change(version=value['version']),'abandon')
        self.flow.process(value['id']);self.assertEqual(self.flow.get(value['id'],'owner')['status'],'abandoned');self.assertTrue(self.store.asset_path(value['board']['original_asset']['filename']).exists())

    def test_response_lost_save_replays_without_duplicate_revision(self):
        value=self.ready(); change=Change(version=value['version'],request_id='save-once')
        first=self.flow.update(value['id'],'owner',change,'save')
        second=self.flow.update(value['id'],'owner',change,'save')
        self.assertEqual(first['route_id'],second['route_id'])
        self.assertEqual(len(self.store.revisions(first['route_id'],'owner')),1)

    def test_manual_add_is_atomic_and_does_not_require_calibration(self):
        value=self.ready(); count=len(value['board']['objects'])
        with self.store.transaction() as db:
            db.execute('UPDATE board_versions SET calibration_json=NULL WHERE id=?',(value['board_id'],))
        value=self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.99,.99)),'add')
        with patch('core.photo_route_workflow.segment_point',return_value=[[100,100],[140,100],[140,140],[100,140]]):
            self.flow.process(value['id']); self.flow.process(value['id'])
        result=self.flow.get(value['id'],'owner')
        self.assertEqual(result['status'],'ready');self.assertEqual(len(result['board']['objects']),count+1)
        self.assertEqual(len(result['route']['members']),count+1)

    def test_restart_after_local_result_does_not_run_segmentation_again(self):
        value=self.ready()
        value=self.flow.update(value['id'],'owner',Change(version=value['version']),'retry')
        recovered=PhotoWorkflow(self.store,start=False)
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=AssertionError('must reuse completed local result')),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'','PHOTO_ROUTE_VISION_KEY':''}):
            recovered.process(value['id'])
        result=recovered.get(value['id'],'owner')
        self.assertEqual(result['status'],'ready');self.assertEqual(result['route_id'],value['route_id'])

    def test_empty_optional_name_keeps_default(self):
        value=self.ready(); value=self.flow.update(value['id'],'owner',Change(version=value['version']),'save')
        result=self.flow.notes(value['route_id'],'owner',Notes(version=value['route']['version'],name=''))
        self.assertEqual(result['name'],value['route']['name'])

    def test_concurrent_confirmation_creates_only_one_board(self):
        from concurrent.futures import ThreadPoolExecutor
        sid=uuid.uuid4().hex; data=photo_bytes()
        with ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:self.flow.upload('owner',sid,'sample.jpg',data),range(4)))
        self.assertEqual({v['id'] for v in values},{sid})
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM board_versions').fetchone()[0],1)

    def test_note_response_replay_preserves_single_revision_and_stale_edit_fails(self):
        value=self.ready();value=self.flow.update(value['id'],'owner',Change(version=value['version']),'save')
        payload=Notes(version=value['route']['version'],name='',notes='kept',request_id='notes-once')
        first=self.flow.notes(value['route_id'],'owner',payload)
        second=self.flow.notes(value['route_id'],'owner',payload)
        self.assertEqual(first['version'],second['version']);self.assertEqual(len(self.store.revisions(first['id'],'owner')),2)
        with self.assertRaises(HTTPException):self.flow.notes(first['id'],'owner',Notes(version=payload.version,notes='stale'))

    def test_interrupted_add_rolls_back_and_can_resume_once(self):
        import sqlite3
        value=self.ready();count=len(value['board']['objects'])
        value=self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.99,.99)),'add')
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER interrupt_add BEFORE UPDATE ON photo_work_sessions WHEN NEW.status='ready' BEGIN SELECT RAISE(ABORT,'simulated interruption'); END")
        with patch('core.photo_route_workflow.segment_point',return_value=[[100,100],[140,100],[140,140],[100,140]]):
            with self.assertRaises(sqlite3.IntegrityError):self.flow.process(value['id'])
            self.assertEqual(len(self.flow.get(value['id'],'owner')['board']['objects']),count)
            with self.store.transaction() as db:db.execute('DROP TRIGGER interrupt_add')
            self.flow.process(value['id'])
        self.assertEqual(len(self.flow.get(value['id'],'owner')['board']['objects']),count+1)


class VisionTests(unittest.TestCase):
    def test_structured_rejection_and_invalid_output_fallback(self):
        import httpx, cv2, numpy as np
        image=cv2.imdecode(np.frombuffer(photo_bytes(),np.uint8),cv2.IMREAD_COLOR)
        objects=[{'id':'a','color_group':'黄色','source_bbox_px':[200,200,100,100]}, {'id':'b','color_group':'黄色','source_bbox_px':[400,200,100,100]}]
        for content,status in [('{"rejected":["b"],"missing":[]}','completed'),('{"rejected":["foreign"]}','unavailable'),('not json','unavailable'),('[]','unavailable'),('{}','unavailable'),('{"rejected":[],"missing":[[2,0.5]]}','unavailable'),('{"rejected":[],"missing":[[true,0.5]]}','unavailable')]:
            client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':content}}]})))
            with patch.dict('os.environ',{'PHOTO_ROUTE_VISION_KEY':'test-only'}): result=review_objects(image,objects,None,client=client)
            self.assertEqual(result['status'],status);client.close()
    def test_timeout_returns_local_fallback(self):
        import httpx, numpy as np
        def timeout(request): raise httpx.ReadTimeout('simulated')
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client,patch.dict('os.environ',{'PHOTO_ROUTE_VISION_KEY':'test-only'}):
            value=review_objects(np.ones((100,100,3),np.uint8),[{'id':'a','color_group':'黄色','source_bbox_px':[10,10,20,20]}],None,client=client)
        self.assertEqual(value['status'],'unavailable');self.assertFalse(value['rejected'])


if __name__=='__main__':unittest.main()
