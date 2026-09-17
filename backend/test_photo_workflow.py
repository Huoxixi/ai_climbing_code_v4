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
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=lambda path,root,**kw:analyze_board_photo(path,root,coarse_only=True)):
            self.flow.process(value['id'])
        return self.flow.get(value['id'],'owner')
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
        value=self.ready();self.assertEqual(value['status'],'ready');self.assertTrue(value['route']['members']);self.assertEqual(value['ai']['status'],'not_requested')
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
    def test_failed_add_can_return_to_editor_without_losing_route(self):
        value=self.ready(); original=value['route']; objects=value['board']['objects']
        with self.store.transaction() as db:
            db.execute('UPDATE photo_work_sessions SET flow_version=1 WHERE id=?',(value['id'],))
        self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.99,.99)),'add')
        with self.store.transaction() as db:
            db.execute("UPDATE photo_work_sessions SET status='failed',error='这个位置暂未找到可靠岩点' WHERE id=?",(value['id'],))
        failed=self.flow.get(value['id'],'owner')
        change=Change(version=failed['version'],request_id='return-once')
        with self.assertRaises(HTTPException): self.flow.update(value['id'],'other',change,'resume')
        result=self.flow.update(value['id'],'owner',change,'resume')
        self.assertEqual(result['status'],'ready'); self.assertIsNone(result['error'])
        self.assertEqual(result['route'],original); self.assertEqual(result['board']['objects'],objects)
        self.assertEqual(self.flow.update(value['id'],'owner',change,'resume')['version'],result['version'])
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT point_json FROM photo_work_sessions WHERE id=?',(value['id'],)).fetchone()[0])
        recovered=PhotoWorkflow(self.store,start=False)
        try:
            self.assertEqual(recovered.current('owner')['status'],'ready')
            saved=recovered.update(value['id'],'owner',Change(version=result['version']),'save')
            self.assertEqual(saved['status'],'saved')
        finally: recovered.close()

    def test_resume_rejects_processing_or_missing_draft(self):
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
        with self.assertRaises(HTTPException): self.flow.update(value['id'],'owner',Change(version=value['version']),'resume')
        with self.store.transaction() as db:
            db.execute("UPDATE photo_work_sessions SET status='failed' WHERE id=?",(value['id'],))
        with self.assertRaises(HTTPException): self.flow.update(value['id'],'owner',Change(version=value['version']),'resume')

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
            db.execute('UPDATE photo_work_sessions SET flow_version=1 WHERE id=?',(value['id'],))
            db.execute('UPDATE board_versions SET calibration_json=NULL WHERE id=?',(value['board_id'],))
        value=self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.99,.99)),'add')
        with patch('core.photo_route_workflow.segment_point',return_value=[[100,100],[140,100],[140,140],[100,140]]):
            self.flow.process(value['id']); self.flow.process(value['id'])
        result=self.flow.get(value['id'],'owner')
        self.assertEqual(result['status'],'ready');self.assertEqual(len(result['board']['objects']),count+1)
        self.assertEqual(len(result['route']['members']),count+1)

    def test_full_model_flow_rejects_legacy_mobilesam_add(self):
        value=self.ready()
        with self.assertRaises(HTTPException) as error:
            self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.5,.5)),'add')
        self.assertEqual(error.exception.status_code,409)
        self.assertIn('专项模型',error.exception.detail)

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
        with self.store.transaction() as db:
            db.execute('UPDATE photo_work_sessions SET flow_version=1 WHERE id=?',(value['id'],))
        value=self.flow.update(value['id'],'owner',Change(version=value['version'],point=(.99,.99)),'add')
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER interrupt_add BEFORE UPDATE ON photo_work_sessions WHEN NEW.status='ready' BEGIN SELECT RAISE(ABORT,'simulated interruption'); END")
        with patch('core.photo_route_workflow.segment_point',return_value=[[100,100],[140,100],[140,140],[100,140]]):
            with self.assertRaises(sqlite3.IntegrityError):self.flow.process(value['id'])
            self.assertEqual(len(self.flow.get(value['id'],'owner')['board']['objects']),count)
            with self.store.transaction() as db:db.execute('DROP TRIGGER interrupt_add')
            self.flow.process(value['id'])
        self.assertEqual(len(self.flow.get(value['id'],'owner')['board']['objects']),count+1)

    def test_preview_members_match_confirmation_without_inference(self):
        value=self.palette();group=next(g for g in value['color_groups'] if g['color']=='黄色')
        payload=Change(version=value['version'],color='黄色',request_id='confirm-once')
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=AssertionError('no inference')), patch('core.photo_route_workflow.review_objects',side_effect=AssertionError('no network')):
            result=self.flow.select(value['id'],'owner',payload)
            repeated=self.flow.select(value['id'],'owner',payload)
        self.assertEqual(result['board_id'],value['board_id'])
        self.assertEqual(set(group['member_ids']),{m['object_id'] for m in result['route']['members']})
        self.assertEqual(repeated['route_id'],result['route_id'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM routes').fetchone()[0],1)

    def test_assign_color_persists_and_isolates_owners(self):
        value=self.palette();oid=value['board']['objects'][0]['id']
        payload=Change(version=value['version'],color='蓝色',member_ids=[oid],request_id='assign-once')
        with self.assertRaises(HTTPException):self.flow.update(value['id'],'other',payload,'assign-color')
        updated=self.flow.update(value['id'],'owner',payload,'assign-color')
        replay=self.flow.update(value['id'],'owner',payload,'assign-color')
        self.assertEqual(updated['version'],replay['version'])
        restored=PhotoWorkflow(self.store,start=False).current('owner')
        self.assertIn(oid,next(g for g in restored['color_groups'] if g['color']=='蓝色')['member_ids'])
        with self.assertRaises(HTTPException):self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))

    def test_legacy_task_keeps_legacy_confirmation(self):
        value=self.palette()
        with self.store.transaction() as db:db.execute('UPDATE photo_work_sessions SET flow_version=1 WHERE id=?',(value['id'],))
        result=self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))
        self.assertEqual(result['status'],'processing');self.assertNotEqual(result['board_id'],value['board_id'])

    def test_legacy_preview_reprocesses_with_full_model_without_deleting_old_board(self):
        value=self.palette(); old_board=value['board']; calls=[]
        with self.store.transaction() as db:db.execute('UPDATE photo_work_sessions SET flow_version=1 WHERE id=?',(value['id'],))
        legacy=self.flow.get(value['id'],'owner')
        reprocessing=self.flow.update(value['id'],'owner',Change(version=legacy['version'],request_id='upgrade-once'),'reprocess')
        self.assertEqual(reprocessing['flow_version'],2); self.assertEqual(reprocessing['status'],'processing')
        self.assertNotEqual(reprocessing['board_id'],old_board['id'])
        self.assertEqual(self.store.get_board(old_board['id'],'owner')['objects'],old_board['objects'])
        def full_model(path,root,**kwargs):
            calls.append(kwargs)
            return analyze_board_photo(path,root,coarse_only=True)
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=full_model): self.flow.process(value['id'])
        upgraded=self.flow.get(value['id'],'owner')
        self.assertEqual(upgraded['status'],'awaiting_color')
        self.assertTrue(calls[0]['require_climbing_model']); self.assertFalse(calls[0]['coarse_only'])

    def test_reprocess_rejects_a_current_full_model_flow(self):
        value=self.palette()
        with self.assertRaises(HTTPException) as error:
            self.flow.update(value['id'],'owner',Change(version=value['version']),'reprocess')
        self.assertEqual(error.exception.status_code,409)

    def test_new_upload_requires_full_model_analysis(self):
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=ValueError('model unavailable')) as analyze:
            with self.assertRaises(ValueError):self.flow.process(value['id'])
        self.assertTrue(analyze.call_args.kwargs['require_climbing_model'])
        self.assertNotIn('require_mobilesam',analyze.call_args.kwargs)
        self.assertFalse(analyze.call_args.kwargs['coarse_only'])
        self.assertEqual(analyze.call_args.kwargs['color_version'],'interior-v4')

    def test_confirmation_rejects_changed_preview(self):
        value=self.palette()
        for extra in [{'member_ids':[]},{'board_version':value['board']['version']+1}]:
            with self.assertRaises(HTTPException) as error:
                self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色',**extra))
            self.assertEqual(error.exception.status_code,409)
        self.assertIsNone(self.flow.get(value['id'],'owner')['route'])


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
