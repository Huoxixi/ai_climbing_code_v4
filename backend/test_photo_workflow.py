import tempfile
import unittest
import uuid
import io
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image
from pillow_heif import register_heif_opener
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
        # Construct a historical v2 task to keep its recovery contract covered.
        with self.store.transaction() as db:
            db.execute("UPDATE photo_work_sessions SET flow_version=2,status='processing' WHERE id=?",(value['id'],))
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
    def test_heic_upload_is_converted_without_browser_decoder(self):
        register_heif_opener()
        encoded=io.BytesIO()
        Image.open(io.BytesIO(photo_bytes())).save(encoded,format='HEIF')
        session=self.flow.upload('owner',uuid.uuid4().hex,'phone.heic',encoded.getvalue(),'image/heic')
        asset=session['board']['original_asset']
        self.assertTrue(asset['filename'].endswith('.jpg'))
        with Image.open(self.store.asset_path(asset['filename'])) as stored:
            self.assertEqual(stored.format,'JPEG')
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

    def test_drawn_hold_commits_membership_once_without_inference_or_calibration(self):
        value=self.ready(); count=len(value['board']['objects'])
        with self.store.transaction() as db:
            db.execute('UPDATE board_versions SET calibration_json=NULL WHERE id=?',(value['board_id'],))
        change=Change(version=value['version'],board_version=value['board']['version'],
            contour=[[100,100],[140,100],[140,140],[100,140]],request_id='drawn-hold-once')
        with patch('core.photo_route_workflow.segment_point',side_effect=AssertionError('no legacy inference')):
            result=self.flow.update(value['id'],'owner',change,'add-contour')
            repeated=self.flow.update(value['id'],'owner',change,'add-contour')
        self.assertEqual(result['version'],repeated['version'])
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['board']['objects']),count+1)
        oid=result['route']['members'][-1]['object_id']
        obj=next(obj for obj in result['board']['objects'] if obj['id']==oid)
        self.assertEqual(obj['color_group'],value['color'])
        self.assertEqual(obj['review_status'],'needs_review')
        self.assertTrue(self.store.asset_path(obj['mask']['filename']).exists())
        restored=self.flow.current('owner')
        self.assertEqual(restored['route']['members'][-1]['object_id'],oid)

    def test_drawn_hold_rejects_wrong_owner_stale_board_and_invalid_boundary(self):
        value=self.ready()
        base=dict(version=value['version'],board_version=value['board']['version'],contour=[[100,100],[140,100],[140,140]])
        for owner,payload in [('other',base),('owner',{**base,'board_version':base['board_version']+1}),
                ('owner',{**base,'contour':[[1,1],[2,2],[3,3]]}),('owner',{**base,'contour':[[-1,1],[20,1],[20,20]]})]:
            with self.assertRaises(HTTPException):self.flow.update(value['id'],owner,Change(**payload),'add-contour')
        unchanged=self.flow.get(value['id'],'owner')
        self.assertEqual(unchanged['version'],value['version'])
        self.assertEqual(len(unchanged['board']['objects']),len(value['board']['objects']))

    def test_drawn_hold_rolls_back_if_membership_commit_is_interrupted(self):
        value=self.ready()
        change=Change(version=value['version'],board_version=value['board']['version'],
            contour=[[100,100],[140,100],[140,140]],request_id='interrupted-drawn-hold')
        with self.store.transaction() as db:
            db.execute("CREATE TRIGGER interrupt_contour BEFORE UPDATE ON photo_work_sessions BEGIN SELECT RAISE(ABORT,'simulated interruption'); END")
        with self.assertRaises(Exception):self.flow.update(value['id'],'owner',change,'add-contour')
        unchanged=self.flow.get(value['id'],'owner')
        self.assertEqual(len(unchanged['board']['objects']),len(value['board']['objects']))
        self.assertEqual(len(unchanged['route']['members']),len(value['route']['members']))
        with self.store.transaction() as db:db.execute('DROP TRIGGER interrupt_contour')
        result=self.flow.update(value['id'],'owner',change,'add-contour')
        self.assertEqual(len(result['board']['objects']),len(value['board']['objects'])+1)

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
        self.flow.select(value['id'],'owner',Change(version=value['version'],color='黄色'))
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=ValueError('model unavailable')) as analyze:
            with self.assertRaises(ValueError):self.flow.process(value['id'])
        self.assertTrue(analyze.call_args.kwargs['require_climbing_model'])
        self.assertNotIn('require_mobilesam',analyze.call_args.kwargs)
        self.assertFalse(analyze.call_args.kwargs['coarse_only'])
        self.assertEqual(analyze.call_args.kwargs['color_version'],'interior-v4')

    def test_new_upload_waits_for_color_without_queuing_or_running_inference(self):
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=AssertionError('must wait for color')):
            value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
            self.flow.process(value['id'])
            recovered=PhotoWorkflow(self.store,start=False)
            recovered.process(value['id'])
        self.assertEqual(value['flow_version'],3)
        self.assertEqual(value['status'],'awaiting_color')
        self.assertEqual(value['board']['objects'],[])
        self.assertIsNone(value['route'])
        self.assertTrue(self.flow.queue.empty())
        self.assertEqual(recovered.current('owner')['status'],'awaiting_color')
        recovered.close()

    def test_color_selection_queues_once_then_builds_only_selected_color_route(self):
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
        payload=Change(version=value['version'],board_version=value['board']['version'],color='黄色',request_id='start-recognition-once')
        selected=self.flow.select(value['id'],'owner',payload)
        repeated=self.flow.select(value['id'],'owner',payload)
        self.assertEqual(selected['status'],'processing')
        self.assertEqual(selected['version'],repeated['version'])
        self.assertIsNone(selected['route'])
        self.assertEqual(self.flow.queue.qsize(),1)
        def constructed(path,root,**kwargs):
            result=analyze_board_photo(path,root,coarse_only=True)
            other=dict(result['objects'][0],id='other-color',color_group='蓝色')
            result['objects'].append(other)
            return result
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=constructed) as analyze,patch('core.photo_route_workflow.review_objects',side_effect=AssertionError('no visual review')):
            self.flow.process(value['id']); self.flow.process(value['id'])
        self.assertEqual(analyze.call_count,1)
        self.assertEqual(analyze.call_args.kwargs['color_group'],'黄色')
        result=self.flow.get(value['id'],'owner')
        self.assertEqual(result['status'],'ready')
        selected_ids={obj['id'] for obj in result['board']['objects'] if obj['color_group']=='黄色'}
        self.assertEqual({m['object_id'] for m in result['route']['members']},selected_ids)
        self.assertTrue(any(obj['color_group']=='蓝色' for obj in result['board']['objects']))
        self.assertEqual(self.flow.select(value['id'],'owner',payload)['route_id'],result['route_id'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM routes').fetchone()[0],1)

    def test_zero_detected_holds_still_enters_manual_repair(self):
        value=self.flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
        selected=self.flow.select(value['id'],'owner',Change(version=value['version'],color='红色'))
        def empty(path,root,**kwargs):
            result=analyze_board_photo(path,root,coarse_only=True);result['objects']=[];return result
        with patch('core.photo_route_workflow.analyze_board_photo',side_effect=empty):self.flow.process(selected['id'])
        ready=self.flow.get(value['id'],'owner')
        self.assertEqual(ready['status'],'ready');self.assertEqual(ready['route']['members'],[])
        repaired=self.flow.update(value['id'],'owner',Change(version=ready['version'],board_version=ready['board']['version'],contour=[[100,100],[140,100],[140,140]]),'add-contour')
        self.assertEqual(len(repaired['route']['members']),1)
        self.assertEqual(repaired['board']['objects'][0]['color_group'],'红色')

    def test_unfinished_v2_draft_can_restart_from_color_without_overwriting_old_masks(self):
        value=self.palette(); old_board=value['board']
        selected=self.flow.select(value['id'],'owner',Change(version=value['version'],board_version=old_board['version'],color='蓝色',recognize=True,request_id='restart-from-color'))
        self.assertEqual(selected['flow_version'],3)
        self.assertEqual(selected['status'],'processing')
        self.assertNotEqual(selected['board_id'],old_board['id'])
        self.assertEqual(selected['board']['objects'],[])
        self.assertEqual(self.store.get_board(old_board['id'],'owner')['objects'],old_board['objects'])
        self.assertEqual(self.flow.queue.qsize(),1)

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
