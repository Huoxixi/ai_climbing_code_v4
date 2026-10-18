"""Constructed media only: composition, empty-scene gates and private export boundary."""
import copy
import io
import itertools
import json
import subprocess
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import cv2
import numpy as np

from core.replay_analysis_view import AnalysisView, visual_evidence
from core.replay_action_renderer import make_plan, render_actions
from core.replay_background import contains_person, prepare_background, VERSION as BACKGROUND_VERSION
from core.replay_export import build_bundle, PACKAGE_VERSION
from test_replay_pose_start import clip


def movie(path, count=8):
    random = np.random.default_rng(3)
    wall = random.integers(30, 120, (96,128,3), dtype=np.uint8)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 4, (128,96))
    for _ in range(count):
        writer.write(wall)
    writer.release()
    return wall


def evidence():
    raw = clip()
    raw.update(source_duration_seconds=2)
    raw['video'].update(width=128,height=96,fps=4,frame_count=8,duration_seconds=2)
    raw['pose_samples'] = [{**p,'source_frame_id':i,'time_seconds':i/4} for i,p in enumerate(raw['pose_samples'][:8])]
    return raw


class PictureTests(unittest.TestCase):
    def test_all_seven_compositions_keep_independent_diagram_and_proportions(self):
        raw=evidence(); view=AnalysisView(raw)
        human=np.full((96,128,3),(30,40,200),np.uint8)
        background=np.full_like(human,(100,50,20))
        diagram=view.frame(human,0,(256,96))[:,128:]
        for skeleton,human_visible,diagram_visible in itertools.product((False,True),repeat=3):
            if not any((skeleton,human_visible,diagram_visible)):
                continue
            with self.subTest(skeleton=skeleton,human=human_visible,diagram=diagram_visible):
                panes=int(skeleton or human_visible)+int(diagram_visible)
                selection=dict(show_skeleton=skeleton,show_human=human_visible,show_diagram=diagram_visible)
                plan=make_plan(raw,**selection,background={'status':'ready'})
                self.assertEqual((plan['width'],plan['height']),(128*panes,96))
                frame=view.compose(human,0,(128*panes,96),**selection,background=background,reference_to_background=np.eye(3))
                if diagram_visible:
                    np.testing.assert_array_equal(frame[:,-128:],diagram)
                if skeleton or human_visible:
                    np.testing.assert_array_equal(frame[2,2],human[2,2] if human_visible else background[2,2])
                if not human_visible:
                    self.assertFalse(np.any(np.all(frame==human[0,0],axis=2)))

    def test_source_and_background_skeleton_use_different_coordinate_spaces(self):
        raw=evidence()
        for sample in raw['pose_samples']:
            sample['wall_reference_transform'][0][2]=10
        view=AnalysisView(raw)
        self.assertAlmostEqual(view.timeline[0]['kpts_xy'][9][0]-view.source_timeline[0]['kpts_xy'][9][0],10/128,places=5)
        visual=visual_evidence(raw)
        self.assertEqual(visual['pose_samples'][0]['source_kpts_xy'],raw['pose_samples'][0]['kpts_xy'])
        source=np.zeros((96,128,3),np.uint8)
        human=view.compose(source,0,(128,96),show_skeleton=True,show_human=True,show_diagram=False)
        scene=view.compose(source,0,(128,96),show_skeleton=True,show_human=False,show_diagram=False,
                           background=source,reference_to_background=[[1,0,-10],[0,1,0],[0,0,1]])
        np.testing.assert_array_equal(human,scene)

    def test_unavailable_background_and_empty_selection_are_rejected(self):
        with self.assertRaises(ValueError):
            make_plan(evidence(),show_skeleton=True,show_human=False,show_diagram=True)
        with self.assertRaises(ValueError):
            make_plan(evidence(),show_human=False,show_diagram=False)
        make_plan(evidence(),show_skeleton=True,show_human=True,show_diagram=False)

    def test_missing_observations_remain_missing_in_both_skeleton_spaces(self):
        raw=evidence();raw['pose_samples'][2]['observed']=False
        view=AnalysisView(raw)
        self.assertNotIn(2,view.timeline)
        self.assertNotIn(2,view.source_timeline)

    def test_real_encoder_all_seven_combinations_decode_without_human_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';movie(source)
            from core.replay_template_renderer import _ffmpeg
            with_audio=root/'source-audio.mp4'
            subprocess.run([_ffmpeg(),'-hide_banner','-loglevel','error','-i',str(source),'-f','lavfi',
                '-i','sine=frequency=440:duration=2','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac',
                '-shortest',str(with_audio)],check=True,capture_output=True)
            source=with_audio
            background=root/'background.png';cv2.imencode('.png',np.full((96,128,3),30,np.uint8))[1].tofile(background)
            for skeleton,human,diagram in itertools.product((False,True),repeat=3):
                if not any((skeleton,human,diagram)):continue
                plan=make_plan(evidence(),speed=.5,show_skeleton=skeleton,show_human=human,show_diagram=diagram,
                    background={'status':'ready','path':str(background),'reference_to_background':np.eye(3).tolist()})
                target=root/f'{int(skeleton)}{int(human)}{int(diagram)}.mp4'
                render_actions(source,plan,target)
                capture=cv2.VideoCapture(str(target));count=0
                while True:
                    okay,frame=capture.read()
                    if not okay:break
                    count+=1
                    self.assertEqual(frame.shape[:2],(96,plan['width']))
                capture.release()
                self.assertEqual(count,16)
                streams=subprocess.run([_ffmpeg(),'-hide_banner','-i',str(target)],capture_output=True).stderr.decode('utf8','replace')
                self.assertIn('Video:',streams)
                self.assertNotIn('Audio:',streams)


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.mp4';movie(self.source)
        self.target=self.root/'empty.png'
    def tearDown(self):self.temp.cleanup()
    def run_background(self,**kwargs):
        return prepare_background(self.source,self.target,evidence(),**kwargs)

    def test_actual_static_wall_passes_and_preserves_actual_frame(self):
        result=self.run_background(detect=lambda frame:[])
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['checked_frames'],1)
        capture=cv2.VideoCapture(str(self.source));capture.set(cv2.CAP_PROP_POS_FRAMES,result['source_frame_id'])
        okay,frame=capture.read();capture.release();self.assertTrue(okay)
        np.testing.assert_array_equal(cv2.imdecode(np.fromfile(self.target,dtype=np.uint8),cv2.IMREAD_COLOR),frame)

    def test_person_detections_not_missing_pose_control_empty_scene(self):
        raw=evidence()
        raw['pose_samples']=[]
        result=prepare_background(self.source,self.target,raw,detect=lambda frame:[[0,0,8,8]])
        self.assertEqual(result['reason'],'no_empty_frame')
        self.assertFalse(self.target.exists())

    def test_partial_edge_person_seen_only_in_crop_is_rejected(self):
        def detector(frame):return [[0,0,3,20]] if frame.shape[1]<128 else []
        self.assertTrue(contains_person(np.zeros((96,128,3),np.uint8),detector))
        self.assertEqual(self.run_background(detect=detector)['reason'],'no_empty_frame')

    def test_empty_frame_registration_not_whole_clip_stationarity_controls_background(self):
        matrix=np.array([[1,0,12],[0,1,0],[0,0,1]],float)
        calls=[]
        def align(frame,reference):
            calls.append(True)
            # Later source-camera movement is already handled by each pose's
            # saved transform; it must not block this verified empty frame.
            if len(calls)>1:raise AssertionError('Unnecessary whole-clip registration')
            return matrix,{'inliers':30,'median_error_px':.5}
        result=self.run_background(detect=lambda frame:[],align=align)
        self.assertEqual(result['status'],'ready')
        np.testing.assert_allclose(result['reference_to_background'],np.linalg.inv(matrix))
        self.assertEqual(len(calls),1)

    def test_failed_alignment_never_writes_background(self):
        for matrix,diagnostics,reason in ((None,{},'unverified'),(np.eye(3),{'inliers':2},'unverified')):
            with self.subTest(reason=reason):
                result=self.run_background(detect=lambda frame:[],align=lambda a,b:(matrix,diagnostics))
                self.assertEqual(result['reason'],reason)
                self.assertFalse(self.target.exists())

    def test_cancellation_creates_no_background(self):
        with self.assertRaises(InterruptedError):
            self.run_background(detect=lambda frame:[],cancelled=lambda:True)
        self.assertFalse(self.target.exists())


class SafeBundleTests(unittest.TestCase):
    def test_nested_private_metadata_images_and_provider_return_cannot_escape(self):
        raw=evidence();raw.pop('skeleton_only')
        secret='PRIVATE_ACCOUNT_PATH_TOKEN'
        raw['video']['filename']=secret
        raw['video']['camera']={'serial':secret}
        raw['pose_samples'][0]['pose_evidence']={'private_path':secret,'response':secret}
        raw['holds']=[{'id':secret,'name':secret,'polygon':[[.1,.1],[.2,.1],[.2,.2]],'bbox':[.1,.1,.1,.1]}]
        raw['attempt']={'contacts':[{'hold_id':secret,'limb':'left_hand','start_time_seconds':0,'end_time_seconds':1}]}
        raw['groups']=[{'description':secret,'events':[{'description':secret,'start_seconds':0,'end_seconds':1}]}]
        raw['ai_analysis']={'raw':secret}
        original=copy.deepcopy(raw)
        stream=build_bundle(raw,mapping={'scope':'full','speed':.75,'private_path':secret,'show_human':False,'show_diagram':True},
                            source_path=Path('MUST_NOT_BE_READ.mp4'),vision={'raw':secret})
        with zipfile.ZipFile(stream) as archive:
            names=archive.namelist()
            self.assertFalse(any(n.endswith(('.png','.jpg','.mp4')) for n in names))
            self.assertNotIn('vision.json',names)
            for name in names:self.assertNotIn(secret,archive.read(name).decode('utf8'))
            data=json.loads(archive.read('analysis.json'))
            self.assertEqual(data['export_version'],PACKAGE_VERSION)
            self.assertEqual(data['holds'][0]['id'],data['attempt']['contacts'][0]['hold_id'])
            self.assertIn('不含原片',archive.read('README.txt').decode('utf8'))
        self.assertEqual(raw,original)
        stream.close()

    def test_selected_video_only_is_added_and_prompt_describes_actual_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'selected.mp4';video.write_bytes(b'selected-video-only')
            stream=build_bundle(evidence(),mapping={'show_skeleton':True,'show_human':False,'show_diagram':False},video_path=video)
            with zipfile.ZipFile(stream) as archive:
                self.assertEqual(archive.read('replay.mp4'),b'selected-video-only')
                self.assertIn('骨架',archive.read('presentation.txt').decode('utf8'))
                self.assertNotIn('source.mp4',archive.namelist())
            stream.close()


class CompositionApiTests(unittest.TestCase):
    def setUp(self):
        from test_replay_actions import ActionLifecycleTests
        self.fixture=ActionLifecycleTests();self.fixture.setUp()
        self.client,self.store,self.manager,self.id=self.fixture.client,self.fixture.store,self.fixture.manager,self.fixture.id
        self.url=self.fixture.url
        response=self.client.post(self.url,json={})
        self.assertEqual(response.status_code,202)
        self.state=self.fixture.wait()
        self.assertEqual(self.state['task']['status'],'succeeded')

    def tearDown(self):self.fixture.tearDown()

    def ready_background(self):
        job=self.store.get(self.id,'alice',private=True)
        binding=self.manager.background_binding(job)
        target=self.store._path(self.id).parent/'constructed-background.png'
        cv2.imencode('.png',np.full((64,96,3),30,np.uint8))[1].tofile(target)
        self.store.update(self.id,replay_background={'binding':binding,'status':'ready','version':BACKGROUND_VERSION,
            'storage_name':target.name,'reference_to_background':np.eye(3).tolist(),'message':''})
        return binding

    def export(self,**selection):
        payload={'result_version':self.state['result_version'],'scope':'full','speed':.75,**selection}
        response=self.client.post(self.url+'/export',json=payload)
        self.assertEqual(response.status_code,202,response.text)
        state=self.fixture.wait('export')
        self.assertEqual(state['export']['status'],'succeeded',state['export'])
        return state,payload

    def test_seven_choices_cached_separately_and_old_default_preserved(self):
        self.ready_background()
        ids=set()
        for skeleton,human,diagram in itertools.product((False,True),repeat=3):
            if not any((skeleton,human,diagram)):continue
            state,payload=self.export(show_skeleton=skeleton,show_human=human,show_diagram=diagram)
            ids.add(state['export_media']['id'])
            plan=self.fixture.calls[-1]
            self.assertEqual((plan['show_skeleton'],plan['show_human'],plan['show_diagram']),(skeleton,human,diagram))
            count=len(self.fixture.calls)
            again=self.client.post(self.url+'/export',json=payload).json()
            self.assertEqual(again['export_media']['id'],state['export_media']['id'])
            self.assertEqual(len(self.fixture.calls),count)
        self.assertEqual(len(ids),7)
        self.export()
        self.assertFalse(self.fixture.calls[-1]['show_skeleton'])
        self.assertTrue(self.fixture.calls[-1]['show_human'])
        self.assertTrue(self.fixture.calls[-1]['show_diagram'])

    def test_data_only_never_calls_renderer_and_package_is_safe(self):
        state,_=self.export(show_skeleton=False,show_human=False,show_diagram=False,include_data=True)
        self.assertEqual(self.fixture.calls,[])
        response=self.client.get(self.url+'/package',params={'version':self.state['result_version'],
            'exported':True,'data_only':True,'export_id':state['export_media']['id']})
        self.assertEqual(response.status_code,200,response.text)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertFalse(any(n.endswith(('.mp4','.png','.jpg')) for n in archive.namelist()))
            self.assertNotIn('vision.json',archive.namelist())
        self.assertEqual(self.client.get(self.url+'/package',params={'version':self.state['result_version'],
            'exported':True,'data_only':True,'export_id':'stale-id'}).status_code,409)

    def test_empty_selection_and_unavailable_scene_are_rejected_server_side(self):
        common={'result_version':self.state['result_version'],'show_human':False,'show_diagram':False}
        self.assertEqual(self.client.post(self.url+'/export',json=common).status_code,400)
        self.assertEqual(self.client.post(self.url+'/export',json={**common,'show_skeleton':True}).status_code,400)
        self.assertEqual(self.fixture.calls,[])

    def test_background_is_versioned_and_owner_scoped(self):
        version=self.ready_background()
        url=self.url+'/background'
        self.assertEqual(self.client.get(url,params={'version':version}).status_code,200)
        self.assertEqual(self.client.get(url,params={'version':version},headers={'x-user':'bob'}).status_code,404)
        self.assertEqual(self.client.post(url,headers={'x-user':'bob'}).status_code,404)
        self.assertEqual(self.client.get(url,params={'version':'stale'}).status_code,409)
        self.assertNotIn('storage_name',self.client.get(self.url).json()['background'])
        with patch('core.replay_action_jobs.ActionManager.background_status',return_value={'status':'not_started'}):
            with patch('core.replay_action_jobs.threading.Thread') as worker:
                self.client.post(url)
                worker.assert_called_once()

    def test_background_version_change_invalidates_export_cache(self):
        self.ready_background()
        first,payload=self.export(show_skeleton=True,show_human=False,show_diagram=False)
        job=self.store.get(self.id,'alice',private=True)
        self.store.update(self.id,replay_background={**job['replay_background'],'binding':'invalidated'})
        self.assertEqual(self.client.post(self.url+'/export',json=payload).status_code,400)
        self.assertEqual(self.store.get(self.id,'alice',private=True)['action_export_media']['id'],first['export_media']['id'])

    def test_failed_export_preserves_previous_download(self):
        first,_=self.export(show_human=True,show_diagram=False)
        self.fixture.render_failure=True
        response=self.client.post(self.url+'/export',json={'result_version':self.state['result_version'],
            'show_human':False,'show_diagram':True,'show_skeleton':False})
        self.assertEqual(response.status_code,202)
        failed=self.fixture.wait('export')
        self.assertEqual(failed['export']['status'],'failed')
        self.assertEqual(failed['export_media']['id'],first['export_media']['id'])
        self.assertEqual(self.client.get(self.url+'/media',params={'version':first['export_media']['id'],'exported':True}).status_code,200)

    def test_background_worker_commits_private_new_media_without_pose_calls(self):
        def prepare(source,target,result,**kwargs):
            self.assertFalse(kwargs['cancelled']())
            cv2.imencode('.png',np.full((64,96,3),30,np.uint8))[1].tofile(target)
            return {'status':'ready','version':BACKGROUND_VERSION,'reference_to_background':np.eye(3).tolist(),'message':''}
        with patch('core.replay_background.prepare_background',side_effect=prepare) as local:
            response=self.client.post(self.url+'/background')
            self.assertEqual(response.status_code,202)
            for _ in range(200):
                status=self.client.get(self.url).json()['background']
                if status['status']!='running':break
                time.sleep(.01)
            self.assertEqual(status['status'],'ready',status)
            local.assert_called_once()
            self.assertEqual(self.client.get(self.url+'/background',params={'version':status['binding']}).status_code,200)
        self.assertEqual(self.fixture.calls,[])


if __name__=='__main__':unittest.main()
