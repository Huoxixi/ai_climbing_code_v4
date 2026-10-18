"""Synthetic engineering contracts; these tests do not certify professional accuracy."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import httpx
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.climb_replay import VideoInfo, VideoLimits, ClimbReplayStore, ReplayAnalyzerBase, REPLAY_RETENTION_DELETE
from core.replay_sampling import native_plan, FocusWindow
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
from core.replay_action_features import enrich_action_features
from core.replay_vision_settings import VisionSettings, save_settings, load_settings, public_settings, settings_router
from core.replay_vision_provider import CompatibleVisionProvider, VisionAPIError
from core.replay_commentary import LegacyVisionCommentaryEngine as VisionCommentaryEngine, validate_response, ledger_cost, request_reserve
from core.replay_commentary import VERSION as COMMENTARY_VERSION
from core.replay_action_engine import ActionEngine
from core.replay_coaching_engine import CoachingEngine
from test_replay_action_trajectory import fixture, active_hand
from test_replay_pose_rtmw import fake_models


def config(**changes):
    data=dict(base_url='https://vision.invalid/v1', model='test-vl', api_key='synthetic-key',
        cost_control_enabled=True, input_cny_per_million=1, output_cny_per_million=2)
    return VisionSettings(**{**data, **changes}).model_dump()


def action_fixture():
    raw = active_hand(fixture())
    for i, row in enumerate(raw['pose_samples']):
        row['time_seconds'] = row['source_frame_id']/30
        row['kpts_xy'][9][1] = .5-i*.025
        row['kpts_xy'][7][1] = .4-i*.0125
    middle = raw['pose_samples'][4]['time_seconds']
    raw['source_duration_seconds'] = raw['video']['duration_seconds'] = 80/30
    raw['video']['frame_count'] = 80
    raw['groups'] = [{'id':'g1','start_seconds':0,'end_seconds':middle,'candidate_limbs':['left_hand'],'events':[]},
                     {'id':'g2','start_seconds':middle,'end_seconds':raw['pose_samples'][-1]['time_seconds'],'candidate_limbs':['left_hand'],'events':[]}]
    result = enrich_action_features(raw, {'result':raw})
    # Frozen v3 limb returns are still recoverable without re-sending a request.
    # Current important-event behavior has separate kinematic fixtures/tests.
    result.pop('commentary_policy', None)
    result['action_evidence'].pop('commentary_actions', None)
    return result


def prepare_paid_fixture(test_case):
    import test_replay_actions as lifecycle
    data = lifecycle.evidence()
    base = fixture()['pose_samples'][0]['kpts_xy']
    for i, row in enumerate(data['pose_samples']):
        dx = min(i,5)*.026-max(0,min(i-12,7))*.021
        row['kpts_xy'] = copy.deepcopy(base)
        for joint in range(13):row['kpts_xy'][joint][0]+=dx
        for joint in (13,14):row['kpts_xy'][joint][0]+=dx/2
        row['source_frame_id'] = i
    test_case.store.update(test_case.id, result=data)
    return test_case


class SamplingTests(unittest.TestCase):
    def test_same_original_cannot_cross_development_and_holdout(self):
        from core.replay_action_evaluation import evaluate
        data={'attempts':[
            {'attempt_id':'a','participant_group':'p1','route_group':'r1','original_video_group':'same','split':'development'},
            {'attempt_id':'b','participant_group':'p2','route_group':'r2','original_video_group':'same','split':'holdout'}]}
        self.assertTrue(evaluate(data)['development_holdout_leakage'])
    def test_default_10fps_and_native_windows_have_no_duplicates(self):
        video = VideoInfo(720,1280,30,900,30,100)
        for fps, count in ((4,120),(10,300),(15,450),(20,600)):
            effective, positions, metadata = native_plan(video,fps)
            self.assertEqual((effective,len(positions)),(fps,count))
            self.assertEqual(len(set(positions)),count)
        _, positions, metadata = native_plan(video,10,[FocusWindow(start_seconds=6,end_seconds=12,fps=20)])
        self.assertEqual(len(positions),360)
        self.assertEqual(metadata['focus_windows'][0]['reason'],'user_selected')
        self.assertEqual(LocalRTMWReplayAnalyzer().pose_fps,10)
        self.assertAlmostEqual(native_plan(video,20)[2]['max_gap_seconds'],2/30,places=6)

    def test_low_fps_is_never_upsampled_and_windows_reject_bad_time(self):
        video=VideoInfo(720,1280,7,70,10,100)
        self.assertEqual(len(native_plan(video,20,[FocusWindow(start_seconds=0,end_seconds=10)])[1]),70)
        for values in ({'start_seconds':2,'end_seconds':1},{'start_seconds':0,'end_seconds':float('nan')}):
            with self.assertRaises(ValidationError): FocusWindow(**values)
        with self.assertRaises(ValueError): native_plan(video,10,[{'start_seconds':0,'end_seconds':11}])

    def test_cache_reuses_raw_samples_and_invalidates_when_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            analyzer=LocalRTMWReplayAnalyzer(); analyzer._models=fake_models()
            path=Path(folder)/'poses.json'; binding={'source':'one','model':'fixed'}
            analyzer.configure_cache(path,binding)
            image=np.zeros((100,100,3),np.uint8)
            first=analyzer._pose_frame(image,frame_id=0,source_frame_id=3); analyzer.flush_pose_cache()
            analyzer.configure_cache(path,binding)
            second=analyzer._pose_frame(image,frame_id=9,source_frame_id=3)
            self.assertTrue(analyzer.last_pose_cache_hit)
            self.assertEqual(second['frame_id'],9); self.assertEqual(first['wholebody'],second['wholebody'])
            self.assertEqual(analyzer._models[0].call_count,1)
            analyzer.configure_cache(path,{'source':'two','model':'fixed'})
            analyzer._pose_frame(image,frame_id=0,source_frame_id=3)
            self.assertFalse(analyzer.last_pose_cache_hit); self.assertEqual(analyzer._models[0].call_count,2)

    def test_dense_short_candidate_does_not_fake_point_four_seconds_dwell(self):
        records=[{'frame_id':i,'source_frame_id':i,'kpts_xy':[[.5,.5]]*17,'kpts_score':[.9]*17} for i in range(6)]
        holds=[{'id':1,'bbox':[.4,.4,.2,.2]}]
        self.assertEqual(ReplayAnalyzerBase._contacts(records,holds,10,source_fps=30)['contacts'],[])
        self.assertEqual((VideoLimits().max_width,VideoLimits().max_height),(1280,720))

    def test_dwell_seconds_do_not_depend_on_dense_sample_count(self):
        holds=[{'id':1,'bbox':[.4,.4,.2,.2]},{'id':2,'bbox':[.4,.1,.2,.1]}]
        answers=[]
        for positions in ([0,3,6,9,12,15,18],[0,2,3,5,6,8,9,11,12,14,15,17,18]):
            records=[{'frame_id':i,'source_frame_id':p,'kpts_xy':[[.5,.5]]*17,'kpts_score':[.9]*17} for i,p in enumerate(positions)]
            answers.append(ReplayAnalyzerBase._contacts(records,holds,10,source_fps=30)['per_limb']['left_hand']['contact_seconds'])
        self.assertEqual(answers,[.2,.2])

    def test_old_expired_cleanup_cannot_delete_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'constructed.mp4'; source.write_bytes(b'synthetic')
            store=ClimbReplayStore(root/'store')
            job=store.create(owner='owner',route_id=None,route_color='黄色',source=source,original_name=source.name,
                info=VideoInfo(96,64,4,8,2,9),consent={},retention_mode=REPLAY_RETENTION_DELETE)
            private=store.get(job['id'],private=True)
            private['media']['source_video'].update(retention_mode=REPLAY_RETENTION_DELETE,delete_at='2000-01-01T00:00:00+00:00')
            store.update(job['id'],media=private['media'],status='succeeded')
            self.assertEqual(store.cleanup_due_media(),[])
            self.assertTrue(store._media_path(job['id'],store.get(job['id'],private=True),'source_video').is_file())


class VisionSettingsTests(unittest.TestCase):
    def test_saved_key_is_protected_owner_scoped_and_never_public(self):
        with tempfile.TemporaryDirectory() as folder:
            save_settings(folder,'one',VisionSettings(**config()))
            data=load_settings(folder,'one')
            self.assertEqual(data['api_key'],'synthetic-key'); self.assertTrue(public_settings(data)['ready'])
            self.assertNotIn('synthetic-key',json.dumps(public_settings(data)))
            self.assertFalse(public_settings(load_settings(folder,'two'))['configured'])
            disk=''.join(p.read_text('utf-8') for p in Path(folder).rglob('*.json'))
            import os
            if os.name=='nt': self.assertNotIn('synthetic-key',disk)
            payload=config(); payload['api_key']=None
            save_settings(folder,'one',VisionSettings(**payload))
            self.assertEqual(load_settings(folder,'one')['api_key'],'synthetic-key')

    def test_optional_pricing_only_blocks_when_enabled_and_invalid_url_rejects(self):
        self.assertFalse(public_settings(VisionSettings().model_dump())['ready'])
        optional=VisionSettings(base_url='https://vision.invalid/v1',model='test-vl',api_key='synthetic-key').model_dump()
        self.assertTrue(public_settings(optional)['ready'])
        self.assertFalse(public_settings(optional)['pricing_configured'])
        self.assertFalse(optional['cost_control_enabled'])
        self.assertFalse(public_settings({**optional,'cost_control_enabled':True})['ready'])
        for url in ('http://remote.invalid','https://key@remote.invalid','https://remote.invalid/?key=secret'):
            with self.assertRaises(ValidationError): VisionSettings(base_url=url)
        with self.assertRaises(ValueError): request_reserve(VisionSettings().model_dump(),100,1)

    def test_settings_validation_does_not_echo_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            app=FastAPI()
            @app.middleware('http')
            async def owner(request,call_next):
                request.state.pilot_user=type('User',(),{'username':'one'})()
                return await call_next(request)
            app.include_router(settings_router(folder)); client=TestClient(app)
            response=client.put('/api/settings/replay-vision',json={'api_key':'secret\nvalue'})
            self.assertEqual(response.status_code,422); self.assertNotIn('secret',response.text)
            self.assertEqual(response.headers['cache-control'],'no-store')

    def test_legacy_environment_cannot_activate_bailian(self):
        with patch.dict('os.environ',{'DASHSCOPE_API_KEY':'synthetic','REPLAY_COACHING_API_KEY':'synthetic'}):
            self.assertFalse(ActionEngine().configured); self.assertFalse(CoachingEngine().configured)

    def test_provider_exact_transport_no_retry_and_error_is_scrubbed(self):
        requests=[]
        def reply(request):
            requests.append(request)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}], 'usage':{'prompt_tokens':10,'completion_tokens':2},'model':'actual-model'})
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            result=CompatibleVisionProvider(config(),client)(messages=[],max_tokens=50,cancelled=lambda:False)
        self.assertEqual(str(requests[0].url),'https://vision.invalid/v1/chat/completions')
        self.assertEqual(result['model'],'actual-model'); self.assertEqual(len(requests),1)
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(401,text='synthetic-key'))) as client:
            with self.assertRaises(VisionAPIError) as error:
                CompatibleVisionProvider(config(),client)(messages=[],max_tokens=50,cancelled=lambda:False)
            self.assertNotIn('synthetic-key',str(error.exception))


class CommentaryTests(unittest.TestCase):
    def test_manager_starts_without_pricing_when_cost_control_is_disabled(self):
        import test_replay_actions as lifecycle
        fixture=lifecycle.ActionLifecycleTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        prepare_paid_fixture(fixture)
        optional=config(cost_control_enabled=False,input_cny_per_million=None,output_cny_per_million=None)
        save_settings(fixture.store.root.parent,'alice',VisionSettings(**optional))
        engine=Mock(); engine.run.side_effect=lambda source,job,result,**kwargs:result
        payload={'cloud_consent':True,'consent_version':COMMENTARY_VERSION,'budget_confirmed':True}
        with patch('core.replay_action_jobs.VisionCommentaryEngine',return_value=engine):
            response=fixture.client.post(fixture.url,json=payload)
            self.assertEqual(response.status_code,202,response.text)
            result=fixture.wait()
            self.assertEqual(result['task']['status'],'succeeded')
            self.assertTrue(result['cloud_configured']); self.assertIsNone(result['budget_cny'])
            self.assertEqual(engine.run.call_count,1)
        save_settings(fixture.store.root.parent,'alice',VisionSettings(**{**optional,'cost_control_enabled':True}))
        self.assertEqual(fixture.client.post(fixture.url,json=payload).status_code,503)

    def test_engine_runs_without_pricing_and_never_reports_zero_cost(self):
        for usage in ({'prompt_tokens':100,'completion_tokens':20},{}):
            with self.subTest(usage=usage):
                optional=config(cost_control_enabled=False,input_cny_per_million=None,output_cny_per_million=None)
                engine,path,ledger,calls,response=self.run_engine(settings=optional)
                def unpriced(**kwargs):
                    result=response(**kwargs); result['usage']=usage; return result
                engine.provider=unpriced
                result=engine.run(path,{},action_fixture(),cancelled=lambda:False,usage_callback=ledger.append)
                self.assertEqual(len(calls),1)
                self.assertEqual(result['action_evidence']['actions'][0]['commentary_basis'],'vision_evidence')
                self.assertIsNone(ledger[-1]['amount_cny']); self.assertIsNone(ledger[-1]['reserved_cny'])
                self.assertIsNone(ledger_cost([ledger[-1]])['known_amount'])
                self.assertFalse(ledger_cost([ledger[-1]])['usage_complete'])

    def test_enabled_budget_blocks_missing_prices_and_unpriced_previous_calls(self):
        for settings,previous in ((config(input_cny_per_million=None),()),(config(),({'amount_cny':None,'reserved_cny':None},))):
            engine,path,ledger,calls,_=self.run_engine(settings=settings)
            with self.assertRaises(ValueError):
                engine.run(path,{},action_fixture(),cancelled=lambda:False,usage_callback=ledger.append,previous_usage=previous)
            self.assertEqual(calls,[])

    def test_default_manager_uses_new_service_and_retry_sees_original_costs(self):
        import test_replay_actions as lifecycle
        fixture=lifecycle.ActionLifecycleTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        prepare_paid_fixture(fixture)
        save_settings(fixture.store.root.parent,'alice',VisionSettings(**config()))
        previous_costs=[]
        def run(source,job,result,**kwargs):
            previous_costs.append(copy.deepcopy(kwargs['previous_usage']))
            kwargs['usage_callback']({'request_id':'modern-request','stage':'action_commentary',
                'amount_cny':.6,'reserved_cny':.7,'usage_complete':True,'usage':{},'status':'succeeded'})
            return result
        engine=Mock(); engine.run.side_effect=run
        payload={'cloud_consent':True,'consent_version':COMMENTARY_VERSION,'budget_confirmed':True}
        with patch('core.replay_action_jobs.VisionCommentaryEngine',return_value=engine):
            response=fixture.client.post(fixture.url,json=payload)
            self.assertEqual(response.status_code,202,response.text)
            self.assertEqual(fixture.wait()['task']['status'],'succeeded')
            self.assertEqual(previous_costs,[[]])
            fixture.client.post(fixture.url,json={}); local=fixture.wait()
            self.assertEqual(len(fixture.store.get(fixture.id,private=True)['action_result_history']),1)
            engine.run.side_effect=VisionAPIError('safe failure')
            fixture.client.post(fixture.url,json=payload); failed=fixture.wait()
            self.assertEqual(failed['task']['status'],'failed')
            self.assertEqual(failed['result_version'],local['result_version'])
            self.assertEqual(len(fixture.fixture.engine.calls),0)
            actual_previous=engine.run.call_args.kwargs['previous_usage']
            self.assertEqual(actual_previous[0]['amount_cny'],.6)

    def test_body_translation_is_separate_from_stationary_relative_limbs(self):
        data=fixture()
        for i,row in enumerate(data['pose_samples']):
            row['kpts_xy']=(np.asarray(row['kpts_xy'])+np.array([i*.015,0])).tolist()
        actions=enrich_action_features(data,{'result':data})['action_evidence']['actions']
        body=next(a for a in actions if a['limb']=='body')
        self.assertEqual(body['commentary'],'身体向右移动。')
        self.assertTrue(all(a['commentary'] is None for a in actions if a['limb']!='body'))

    def test_features_are_grounded_and_professional_names_stay_internal(self):
        data=action_fixture(); action=data['action_evidence']['actions'][0]
        self.assertEqual(action['quality']['status'],'observed')
        self.assertEqual(action['commentary'],'左手向上移动。')
        self.assertIsNone(action['target_hold_id']); self.assertEqual(action['support_hold_candidates'],[])
        self.assertEqual(action['joint_angles']['definition'],'source_image_projected_pixel_angle')
        self.assertFalse(action['candidate_techniques'][0]['automatic_confirmation'])

    def test_invalid_id_unprovided_frames_and_unsupported_judgement_reject(self):
        action=action_fixture()['action_evidence']['actions'][0]
        ev=action['evidence_frames']
        anchors={r['frame_id']:r for r in (ev[0],ev[len(ev)//2],ev[-1])}
        base={'action_id':action['id'],'text':'左手向上移动。','evidence_frame_ids':list(anchors)}
        self.assertIn(action['id'],validate_response({'comments':[base]},[action],{action['id']:anchors}))
        for change in ({'action_id':'invented'},{'action_id':[]},{'evidence_frame_ids':['frame-999']*3},{'text':'右手向上移动。'},{'text':'右脚踩实，建议加强力量。'}):
            self.assertEqual(validate_response({'comments':[{**base,**change}]},[action],{action['id']:anchors}),{})

    def run_engine(self, settings=None, previous=(), cancelled=lambda:False, provider=None):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'synthetic.mp4'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),30,(96,64))
        self.assertTrue(writer.isOpened())
        for i in range(80): writer.write(np.full((64,96,3),i,np.uint8))
        writer.release(); ledger=[]; calls=[]
        def response(**kwargs):
            calls.append(kwargs)
            data=json.loads(kwargs['messages'][1]['content'][0]['text'])
            return {'content':json.dumps({'comments':[{'action_id':a['id'],'text':'左手向上移动。','evidence_frame_ids':list(data['frames'][a['id']])} for a in data['actions']]}),
                'usage':{'prompt_tokens':100,'completion_tokens':20}}
        engine=VisionCommentaryEngine(settings or config(),provider=provider or response)
        return engine,path,ledger,calls,response

    def test_complete_engine_images_billing_and_single_review_focus(self):
        engine,path,ledger,calls,_=self.run_engine()
        result=engine.run(path,{},action_fixture(),cancelled=lambda:False,usage_callback=ledger.append)
        self.assertEqual(len(calls),1); self.assertEqual(ledger[-1]['amount_cny'],.00014)
        self.assertEqual(result['action_evidence']['actions'][0]['commentary_basis'],'vision_evidence')
        self.assertEqual(result['priority_focus']['kind'],'review')
        self.assertEqual(len(result['priority_focus']['action_ids']),1)
        self.assertIn('image_url',str(calls[0]['messages'][1]['content']))
        self.assertEqual(ledger_cost([ledger[-1]])['request_count'],1)

    def test_retry_budget_blocks_before_network_and_cancellation_blocks(self):
        engine,path,ledger,calls,_=self.run_engine()
        with self.assertRaises(ValueError):
            engine.run(path,{},action_fixture(),cancelled=lambda:False,usage_callback=ledger.append,previous_usage=[{'amount_cny':1}])
        self.assertEqual(calls,[]); self.assertEqual(ledger,[])
        with self.assertRaises(InterruptedError): engine.run(path,{},action_fixture(),cancelled=lambda:True,usage_callback=ledger.append)
        self.assertEqual(calls,[])

    def test_inconsistent_frame_clock_is_not_uploaded(self):
        engine,path,ledger,calls,_=self.run_engine()
        data=action_fixture()
        for action in data['action_evidence']['actions']:
            for row in action['evidence_frames']:
                row['time_seconds'] += .2
        with self.assertRaises(ValueError):
            engine.run(path,{},data,cancelled=lambda:False,usage_callback=ledger.append)
        self.assertEqual(calls,[]); self.assertEqual(ledger,[])

    def test_failed_request_preserves_uncertain_reserved_cost(self):
        engine,path,ledger,calls,_=self.run_engine(provider=Mock(side_effect=VisionAPIError('safe error')))
        with self.assertRaises(VisionAPIError): engine.run(path,{},action_fixture(),cancelled=lambda:False,usage_callback=ledger.append)
        self.assertEqual(ledger[-1]['status'],'failed'); self.assertFalse(ledger[-1]['usage_complete'])
        self.assertGreater(ledger_cost([ledger[-1]])['reserved_amount'],0)


if __name__=='__main__': unittest.main()
