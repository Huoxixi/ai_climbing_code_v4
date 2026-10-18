import io
import json
import tempfile
import unittest
import uuid
import time
import zipfile
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from core.photo_route_v2 import PhotoRouteV2Store
from core.photo_route_workflow import PhotoWorkflow, Change
from core.photo_route_analysis import analyze_board_photo
from core.climb_replay import ClimbReplayStore, ClimbReplayManager, VideoInfo, REPLAY_CONSENT_VERSION
from core.replay_skeleton_mode import without_hold_data, skeleton_draft
from core.replay_actions import organize
from core.replay_route_usage import enrich_route_usage
from core.replay_export import build_bundle
import cv2
import numpy as np
def photo_bytes():
    rng=np.random.default_rng(7)
    image=np.clip(np.full((800,1200,3),(175,185,195),np.int16)+rng.integers(-24,25,(800,1200,3)),0,255).astype(np.uint8)
    cv2.circle(image,(300,300),65,(0,210,245),-1)
    cv2.circle(image,(600,300),45,(210,70,20),-1)
    return cv2.imencode('.jpg',image)[1].tobytes()
from test_climb_replay import FakeAnalyzer

class HoldSelectionTests(unittest.TestCase):
    def test_all_colors_manual_members_and_atomic_precision_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PhotoRouteV2Store(Path(directory)); flow=PhotoWorkflow(store,start=False)
            value=flow.upload('owner',uuid.uuid4().hex,'sample.jpg',photo_bytes())
            self.assertEqual(value['flow_version'],4)
            self.assertEqual(value['status'],'processing')
            seen=[]
            def local(path,root,**kw):
                seen.append(kw);return analyze_board_photo(path,root,coarse_only=True)
            with patch('core.photo_route_workflow.analyze_board_photo',side_effect=local):flow.process(value['id'])
            value=flow.get(value['id'],'owner')
            self.assertIsNone(seen[0]['color_group'])
            self.assertTrue(seen[0]['require_climbing_model'])
            self.assertEqual(value['status'],'ready');self.assertEqual(value['route']['members'],[])
            objects=value['board']['objects'];self.assertGreaterEqual(len(objects),1)
            value=flow.update(value['id'],'owner',Change(version=value['version'],member_ids=[objects[0]['id']]),'members')
            contour=[[5,5],[35,5],[35,35],[5,35]]
            change=Change(version=value['version'],board_version=value['board']['version'],object_id=objects[0]['id'],contour=contour,request_id='edit-one')
            value=flow.update(value['id'],'owner',change,'edit-contour')
            obj=next(o for o in value['board']['objects'] if o['id']==objects[0]['id'])
            self.assertEqual(obj['contour'],contour)
            self.assertEqual(obj['source_bbox_px'][:2],[5,5])
            self.assertEqual(flow.update(value['id'],'owner',change,'edit-contour')['version'],value['version'])
            with self.assertRaises(HTTPException):flow.update(value['id'],'owner',Change(version=change.version,member_ids=[]),'members')
            value=flow.update(value['id'],'owner',Change(version=value['version'],board_version=value['board']['version'],contour=[[45,45],[65,45],[65,65],[45,65]]),'add-contour')
            self.assertEqual(len(value['route']['members']),2)
            done=flow.update(value['id'],'owner',Change(version=value['version']),'save')
            self.assertEqual(done['status'],'saved')
            flow.close()

class SkeletonTests(unittest.TestCase):
    def test_direct_skeleton_upload_never_runs_hold_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';source.write_bytes(b'fake-video')
            store=ClimbReplayStore(root)
            job=store.create(owner='owner',route_id=None,route_color='',source=source,original_name='sample.mp4',info=VideoInfo(96,64,4.,8,2.,4),consent={'event':'local_processing_granted','attempt':1,'version':REPLAY_CONSENT_VERSION,'skip_holds':True},retention_mode='keep_private_original')
            analyzer=FakeAnalyzer();analyzer.detect_holds=lambda *a,**k:self.fail('Direct skeleton upload ran hold detection')
            manager=ClimbReplayManager(store,analyzer)
            try:
                deadline=time.monotonic()+5
                while store.get(job['id'])['status'] in {'queued','running'} and time.monotonic()<deadline:time.sleep(.05)
                value=store.get(job['id'])
                self.assertEqual(value['status'],'succeeded',value.get('error'))
                self.assertTrue(value['skeleton_only']);self.assertNotIn('hold_draft',value)
                self.assertNotIn('holds',value['result'])
            finally:manager.close()
    def test_complete_pose_pipeline_without_contact_computation(self):
        from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
        from test_replay_pose_rtmw import fake_models
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'pose.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),4,(100,100))
            self.assertTrue(writer.isOpened())
            for i in range(8):writer.write(np.full((100,100,3),120,np.uint8))
            writer.release()
            analyzer=LocalRTMWReplayAnalyzer(pose_fps=4);analyzer._models=fake_models()
            with patch('core.climb_replay.align_to_reference',return_value=(np.eye(3),{})),patch('core.climb_replay.render_replay_overlay_video',return_value={'layout':'test'}),patch.object(analyzer,'_contacts',side_effect=AssertionError('No contact computation in skeleton mode')):
                result=analyzer.analyze(source,route_color='',video_info=VideoInfo(100,100,4.,8,2.,source.stat().st_size),confirmed_holds=skeleton_draft(),progress=lambda *a:None,cancelled=lambda:False,telemetry=lambda *a:None)
            self.assertGreater(result['frames_with_pose'],0)
            self.assertTrue(result['pose_samples'])
            self.assertNotIn('holds',result);self.assertNotIn('contacts',result['attempt'])
            self.assertNotIn('holds',result['analysis']['models'])
    def test_pose_only_worker_bypasses_confirmation_and_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';source.write_bytes(b'fake-video')
            store=ClimbReplayStore(root)
            job=store.create(owner='owner',route_id=None,route_color='',source=source,original_name='sample.mp4',info=VideoInfo(96,64,4.,8,2.,4),consent={'event':'granted','attempt':1,'version':'test'},retention_mode='keep_private_original')
            store.update(job['id'],status='awaiting_hold_review',hold_draft={'holds':[]})
            with self.assertRaises(HTTPException):store.start_analysis(job['id'],'owner',{'version':'test'})
            started=store.start_analysis(job['id'],'owner',{'event':'granted','version':REPLAY_CONSENT_VERSION,'skip_holds':True})
            self.assertTrue(started['skeleton_only'])
            analyzer=FakeAnalyzer()
            analyzer.detect_holds=lambda *a,**k: self.fail('Skeleton mode invoked hold model')
            manager=ClimbReplayManager(store,analyzer)
            deadline=time.monotonic()+5
            while store.get(job['id'])['status'] in {'queued','running'} and time.monotonic()<deadline:time.sleep(.05)
            value=store.get(job['id'],private=True)
            self.assertEqual(value['status'],'succeeded',value.get('error'))
            self.assertTrue(value['result']['skeleton_only'])
            self.assertNotIn('holds',value['result']);self.assertNotIn('contacts',value['result'].get('attempt',{}))
            manager.close()

    def test_statistics_and_export_omit_hold_fields(self):
        raw={'video':{'width':100,'height':100,'fps':10,'frame_count':20,'duration_seconds':2},'holds':[{'id':1}], 'pose_samples':[], 'attempt':{'contacts':[{'hold_id':1}]},'models':{'holds':'test','pose':'test'}}
        result=without_hold_data(raw)
        self.assertIn('holds',raw)
        organized=enrich_route_usage(organize({'result':result,'video':result['video']}),result)
        self.assertNotIn('route_usage',organized);self.assertNotIn('holds',organized)
        from core.replay_full_analysis import compact_geometry
        data=compact_geometry(organized)
        self.assertNotIn('holds',data);self.assertNotIn('holds',data['coordinates'])
        with build_bundle(organized,mapping={}) as stream, zipfile.ZipFile(stream) as bundle:
            analysis=json.loads(bundle.read('analysis.json'))
        self.assertNotIn('holds',analysis);self.assertNotIn('contacts',analysis.get('attempt',{}))
        self.assertTrue(analysis['skeleton_only'])

if __name__=='__main__':unittest.main()

