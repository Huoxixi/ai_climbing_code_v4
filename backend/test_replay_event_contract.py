"""Regression contracts for event structure and immutable paid visual returns."""
import copy
import json
import time
import unittest
from unittest.mock import Mock, patch
import cv2
import numpy as np
from fastapi import HTTPException

from core.replay_actions import organize
from core.replay_event_validation import validate_event_sequence
from core.replay_action_jobs import ActionCreate, ActionManager
from core.replay_commentary import VERSION, VisionCommentaryEngine
from core.replay_vision_settings import save_settings, VisionSettings
from test_replay_action_trajectory import fixture as pose_fixture
import test_replay_professional as professional
import test_replay_actions as lifecycle


class EventTimelineTests(unittest.TestCase):
    def test_long_body_motion_cannot_merge_sequential_hand_and_foot_actions(self):
        data = pose_fixture(49)
        for i, row in enumerate(data['pose_samples']):
            row['kpts_xy'] = (np.asarray(row['kpts_xy']) + [i*.002,0]).tolist()
            hand = max(0,min(i-4,8))*.012
            foot = max(0,min(i-24,8))*.012
            row['kpts_xy'][9][1] -= hand
            row['kpts_xy'][7][1] -= hand/2
            row['kpts_xy'][15][1] -= foot
            row['kpts_xy'][13][1] -= foot/2
        groups = organize({'result':data})['groups']
        hands = [g for g in groups if 'left_hand' in g['candidate_limbs']]
        feet = [g for g in groups if 'left_foot' in g['candidate_limbs']]
        self.assertTrue(hands); self.assertTrue(feet)
        self.assertLessEqual(hands[-1]['end_seconds'],feet[0]['start_seconds'])
        self.assertTrue(validate_event_sequence({'groups':groups,'source_duration_seconds':12})['analysis_valid'])

    def test_reversal_without_stable_end_keeps_one_unfinished_event(self):
        data = pose_fixture(25)
        for i,row in enumerate(data['pose_samples']):
            shift = min(i,12)*.014 - max(0,i-12)*.014
            row['kpts_xy'] = (np.asarray(row['kpts_xy'])+[shift,0]).tolist()
        groups = organize({'result':data})['groups']
        self.assertEqual(len(groups),1)
        self.assertFalse(groups[0]['ending_stable'])
        self.assertTrue(all(a['end_seconds'] <= b['start_seconds'] for a,b in zip(groups,groups[1:])))

    def test_five_parts_of_one_whole_video_are_never_a_valid_sequence(self):
        groups = [{'id':str(i),'start_seconds':1.,'end_seconds':20.7} for i in range(5)]
        self.assertFalse(validate_event_sequence({'groups':groups,'source_duration_seconds':21})['analysis_valid'])
        distinct = [{'start_seconds':i,'end_seconds':i+.5} for i in range(2)]
        self.assertTrue(validate_event_sequence({'groups':distinct,'source_duration_seconds':21})['analysis_valid'])


class PaidStageTests(unittest.TestCase):
    def test_valid_ordinary_events_allow_authorized_full_analysis(self):
        case=self.setup_fixture()
        data=copy.deepcopy(case.store.get(case.id,'alice',private=True)['result'])
        for row in data['pose_samples']:
            dx=row['kpts_xy'][11][0]-.4
            for joint in (15,16):row['kpts_xy'][joint][0]+=dx
        case.store.update(case.id,result=data)
        state=case.manager.get(case.id,'alice')
        self.assertTrue(state['result']['event_validation']['analysis_valid'])
        self.assertEqual(state['result']['commentary_policy']['selected_event_count'],0)
        with patch('core.replay_action_jobs.VisionCommentaryEngine') as engine:
            engine.return_value.run.side_effect=lambda source,job,result,**kw: result
            case.manager.enqueue(case.id,'alice','action_task',ActionCreate(
                cloud_consent=True,consent_version=VERSION,budget_confirmed=True))
            self.assertEqual(self.wait(case.manager,case.id)['task']['status'],'succeeded')
            self.assertEqual(engine.return_value.run.call_count,1)

    def test_partial_old_policy_return_cannot_be_reshaped_and_charged_again(self):
        case=self.setup_fixture()
        from core.climb_replay import _atomic_json
        job=case.store.get(case.id,'alice',private=True)
        _atomic_json(case.manager.vision_cache_path(job),{'responses':{'old-batch':{'content':'saved'}},
            'vision_status':'partial','input':{'groups':[]}})
        self.assertTrue(case.manager.get(case.id,'alice')['legacy_saved_vision_return'])
        with patch('core.replay_action_jobs.VisionCommentaryEngine') as engine:
            with self.assertRaises(HTTPException) as error:
                case.manager.enqueue(case.id,'alice','action_task',ActionCreate(
                    cloud_consent=True,consent_version=VERSION,budget_confirmed=True))
            self.assertEqual(error.exception.status_code,409)
            engine.assert_not_called()

    def setup_fixture(self):
        case=lifecycle.ActionLifecycleTests();case.setUp();self.addCleanup(case.tearDown)
        professional.prepare_paid_fixture(case)
        save_settings(case.store.root.parent,'alice',VisionSettings(**professional.config()))
        path=case.manager.source(case.store.get(case.id,'alice',private=True))
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),4,(96,64))
        self.assertTrue(writer.isOpened())
        for i in range(24):writer.write(np.full((64,96,3),i,np.uint8))
        writer.release()
        return case

    def wait(self, manager, job_id):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            state=manager.get(job_id,'alice')
            if state['task']['status'] not in {'running','queued'}:
                return state
            time.sleep(.02)
        self.fail('local action task timed out')

    def test_invalid_sequence_rejected_at_api_before_vision_or_ledger(self):
        case=self.setup_fixture()
        invalid={'result':{'source_duration_seconds':6,'groups':[
            {'start_seconds':0,'end_seconds':4},{'start_seconds':2,'end_seconds':5}]}}
        with patch.object(case.manager,'get',return_value=invalid), patch('core.replay_action_jobs.VisionCommentaryEngine') as engine:
            with self.assertRaises(HTTPException) as error:
                case.manager.enqueue(case.id,'alice','action_task',ActionCreate(
                    cloud_consent=True,consent_version=VERSION,budget_confirmed=True))
            self.assertEqual(error.exception.status_code,422)
            engine.assert_not_called()
        self.assertEqual(case.manager.get(case.id,'alice')['task']['status'],'idle')

    def test_invalid_return_survives_restart_duplicate_upload_and_settings_change_without_new_calls(self):
        case=self.setup_fixture()
        provider=Mock(return_value={'content':'invalid-json','model':'paid-model',
            'provider_request_id':'remote-1','usage':{'prompt_tokens':100,'completion_tokens':20}})
        with patch('core.replay_commentary.CompatibleVisionProvider',return_value=provider):
            case.manager.enqueue(case.id,'alice','action_task',ActionCreate(
                cloud_consent=True,consent_version=VERSION,budget_confirmed=True))
            failed=self.wait(case.manager,case.id)
            self.assertEqual(failed['task']['failed_stage'],'commentary')
            self.assertEqual(failed['vision_status'],'succeeded')
            self.assertTrue(failed['local_commentary_retry_available'])
            self.assertEqual(failed['vision_request_count'],1)
            saved=case.manager.vision_checkpoint(case.store.get(case.id,'alice',private=True))
            raw=next(iter(saved['responses'].values()))
            self.assertEqual(raw['provider_request_id'],'remote-1')
            self.assertEqual(raw['content'],'invalid-json')
            case.manager.close()
            manager=ActionManager(case.store,renderer=Mock(side_effect=AssertionError('no encoding')))
            self.addCleanup(manager.close)
            save_settings(case.store.root.parent,'alice',VisionSettings())
            manager.enqueue(case.id,'alice','action_task',ActionCreate(retry_saved_response=True))
            retry=self.wait(manager,case.id)
            self.assertEqual(retry['task']['failed_stage'],'commentary')
            self.assertEqual(retry['task']['usage'],[])
            # Another upload with identical bytes receives the same immutable
            # vision record, even with a different job id and file timestamp.
            original=case.store.get(case.id,'alice',private=True)
            fresh_id=case.fixture.make_job()
            fresh=case.store.get(fresh_id,'alice',private=True)
            case.store.media_file(fresh_id,'alice','source_video')[0].write_bytes(manager.source(original).read_bytes())
            fresh_result=copy.deepcopy(original['result'])
            fresh_result['center_of_mass_trajectory']={'version':'new-display-model','segments':[]}
            case.store.update(fresh_id,result=fresh_result,video=original['video'])
            self.assertTrue(manager.get(fresh_id,'alice')['local_commentary_retry_available'])
            manager.enqueue(fresh_id,'alice','action_task',ActionCreate(retry_saved_response=True))
            self.assertEqual(self.wait(manager,fresh_id)['task']['usage'],[])
            self.assertEqual(provider.call_count,1)
            # No raw response or owner-private evidence is leaked in public API.
            self.assertNotIn('invalid-json',json.dumps(manager.get(fresh_id,'alice')))
            with self.assertRaises(HTTPException):manager.get(fresh_id,'bob')

    def test_complete_return_can_recover_after_failure_between_raw_save_and_success_ledger(self):
        helper=professional.CommentaryTests(); self.addCleanup(helper.doCleanups)
        engine,path,ledger,calls,response=helper.run_engine()
        saved={}
        def ledger_failure(event):
            if event['status']=='succeeded':raise OSError('synthetic persistence failure')
        with self.assertRaises(OSError):
            engine.run(path,{},professional.action_fixture(),cancelled=lambda:False,
                usage_callback=ledger_failure,response_callback=lambda key,r:saved.update({key:r}))
        self.assertEqual(len(calls),1)
        engine.provider=Mock(side_effect=AssertionError('no network'))
        result=engine.recover(professional.action_fixture(),saved.values(),cancelled=lambda:False)
        self.assertEqual(result['commentary_status']['accepted_comments'],2)

    def test_legacy_paid_return_blocks_new_calls_after_local_reorganization_and_duplicate_upload(self):
        case=self.setup_fixture()
        job=case.store.get(case.id,'alice',private=True)
        old_algorithm='source-axis-time-window-local-naming-v8'
        old_fingerprint=case.manager.fingerprint(job,old_algorithm)
        case.store.update(case.id,action_commentary_checkpoint={'fingerprint':old_fingerprint,
            'responses':{'old-paid-return':{'content':'saved-legacy-response','usage':{}}}})
        before=copy.deepcopy(case.store.get(case.id,'alice',private=True))
        state=case.manager.get(case.id,'alice')
        self.assertTrue(state['legacy_saved_vision_return'])
        self.assertEqual(case.store.get(case.id,'alice',private=True),before)
        paid=ActionCreate(cloud_consent=True,consent_version=VERSION,budget_confirmed=True)
        with patch('core.replay_action_jobs.VisionCommentaryEngine') as engine:
            with self.assertRaises(HTTPException) as error:case.manager.enqueue(case.id,'alice','action_task',paid)
            self.assertEqual(error.exception.status_code,409)
            case.manager.enqueue(case.id,'alice','action_task',ActionCreate())
            self.assertEqual(self.wait(case.manager,case.id)['task']['status'],'succeeded')
            self.assertTrue(case.manager.get(case.id,'alice')['legacy_saved_vision_return'])
            engine.assert_not_called()
        case.manager.close()
        manager=ActionManager(case.store,renderer=Mock())
        self.addCleanup(manager.close)
        fresh_id=case.fixture.make_job()
        original=case.store.get(case.id,'alice',private=True)
        case.store.media_file(fresh_id,'alice','source_video')[0].write_bytes(manager.source(original).read_bytes())
        case.store.update(fresh_id,result=copy.deepcopy(original['result']),video=original['video'])
        self.assertTrue(manager.get(fresh_id,'alice')['legacy_saved_vision_return'])
        with self.assertRaises(HTTPException):manager.enqueue(fresh_id,'alice','action_task',paid)


if __name__=='__main__':unittest.main()
