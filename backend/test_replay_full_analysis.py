import copy
import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from core.replay_commentary import VisionCommentaryEngine
from core.replay_full_analysis import validate_input, compact_geometry
from core.replay_vision_provider import supports_video, VisionAPIError
from core.replay_actions import organize
from test_replay_action_trajectory import fixture
from test_replay_action_segmentation import translate


class FullAnalysisTests(unittest.TestCase):
    def test_vectors_keep_all_samples_gaps_and_hold_geometry_without_diagnostics(self):
        result = fixture(300)
        result['holds'] = [{'id':'h1','bbox':[.1,.2,.03,.04], 'polygon':[[.1,.2],[.13,.2],[.1,.24]],'debug':'do not send'}]
        for sample in result['pose_samples']:
            sample['wall_alignment_diagnostics'] = {'matches':[1]*10000}
        result['pose_samples'][4]['observed'] = False
        data = compact_geometry(result)
        self.assertEqual(len(data['pose_samples']),300)
        self.assertEqual(data['holds'][0]['polygon'],result['holds'][0]['polygon'])
        self.assertNotIn('debug',data['holds'][0])
        self.assertFalse(data['pose_samples'][4][2])
        self.assertIsNone(data['pose_samples'][4][3])
        self.assertIsNone(data['pose_samples'][4][7])
        self.assertEqual(data['pose_samples'][5][3],result['pose_samples'][5]['kpts_xy'])
        self.assertLess(len(json.dumps(data)),len(json.dumps(result))*.1)
        self.assertNotIn('wall_alignment_diagnostics',json.dumps(data))

    def test_hidden_wrist_does_not_merge_two_visible_body_moves(self):
        result = translate(fixture(41), [[min(i,8)*.01,-max(0,min(i-20,8))*.01] for i in range(41)])
        for row in result['pose_samples']:
            row['kpts_score'][9] = .1
        groups = organize({'result':result})['groups']
        self.assertEqual(len(groups),2)
        self.assertTrue(all(g['ending_stable'] for g in groups))
        self.assertLess(groups[0]['end_seconds'],groups[1]['start_seconds'])

    def test_empty_and_single_action_are_valid_context_not_fake_sequences(self):
        result = fixture()
        self.assertEqual(validate_input(result),2)
        result['groups'] = []
        self.assertEqual(validate_input(result),2)
        result['groups'] = [{'start_seconds':0,'end_seconds':1},{'start_seconds':.5,'end_seconds':2}]
        with self.assertRaises(ValueError):
            validate_input(result)

    def run_case(self, content_error=False):
        result = fixture(17)
        result['commentary_policy'] = {'important_only':True,'selected_event_count':0}
        for i,row in enumerate(result['pose_samples']):
            row['source_frame_id'] = i
        result['video'].update(width=96,height=64,fps=4,frame_count=17)
        calls, saved, bills = [],{},[]
        def provider(**kwargs):
            calls.append(kwargs)
            data=json.loads(kwargs['messages'][1]['content'][0]['text'])
            self.assertEqual(len(data['pose_samples']),17)
            self.assertTrue(data['joint_angles'])
            self.assertTrue(any(row[1]=='torso_lean_from_vertical' for row in data['joint_angles']))
            self.assertIn('frame-16',data['frames'])
            self.assertIn('frame-0',data['frames'])
            return {'content':'bad json' if content_error else json.dumps({'overview':'整体移动连贯，随后稳定。',
                'actions':[{'title':'身体移动','start_seconds':0,'end_seconds':4,'observation':'身体上移后保持稳定。',
                    'evaluation':'可见前后动作衔接。','evidence_frame_ids':['frame-0','frame-8','frame-16']}],
                'priority_focus':'回看身体移动与下一步的衔接。','limitations':['二维画面无法判断承重。']}),
                'model':'test','usage':{'prompt_tokens':10,'completion_tokens':20}}
        engine = VisionCommentaryEngine({'base_url':'https://gateway.invalid/v1','model':'test','api_key':'fake'},provider=provider)
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'video.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),4,(96,64))
            for _ in range(17):
                writer.write(np.zeros((64,96,3),np.uint8))
            writer.release()
            args=dict(cancelled=lambda:False,usage_callback=bills.append,
                response_callback=lambda k,r:saved.update({k:r}))
            if content_error:
                with self.assertRaises(json.JSONDecodeError):
                    engine.run(source,{},result,**args)
            else:
                output=engine.run(source,{},result,**args)
                self.assertEqual(output['ai_analysis']['actions'][0]['end_seconds'],4)
                self.assertFalse(output['commentary_policy']['important_only'])
                restored=engine.run(Path(temp)/'missing.mp4',{},result,previous_responses=saved,**args)
                self.assertEqual(restored['ai_analysis'],output['ai_analysis'])
        self.assertEqual(len(calls),1)
        self.assertEqual(len(saved),1)
        self.assertEqual(bills[-1]['status'],'succeeded')

    def test_full_context_and_saved_recovery_without_new_request(self):
        self.run_case()

    def test_invalid_json_is_saved_before_parsing(self):
        self.run_case(True)

    def test_unknown_request_does_not_send(self):
        def provider(**kwargs):
            self.fail('must not send')
        engine=VisionCommentaryEngine({'model':'test'},provider=provider)
        with self.assertRaises(ValueError):
            engine.run('missing.mp4',{},fixture(),cancelled=lambda:False,usage_callback=lambda r:None,
                previous_usage=[{'status':'started'}])

    def test_video_capability_requires_verified_service_and_model(self):
        cfg={'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','model':'qwen3.8-max'}
        self.assertTrue(supports_video(cfg))
        self.assertFalse(supports_video({**cfg,'model':'gpt-6-sol'}))
        self.assertFalse(supports_video({**cfg,'base_url':'https://unverified.invalid/v1'}))

    def test_independent_analysis_action_can_export_its_exact_time(self):
        from core.replay_actions import organize
        from core.replay_action_renderer import make_plan,validate
        result=organize({'result':fixture(17)})
        result['video']['frame_count']=120
        result['commentary_segments']=[{'id':'analysis-001','group_id':None,'start_seconds':1,'end_seconds':2}]
        plan=make_plan(result,scope='group',group_id=None,segment_id='analysis-001',analysis_right=True)
        self.assertEqual(plan['source_start_frame'],30)
        self.assertEqual(plan['source_stop_frame'],60)
        self.assertGreater(validate(plan),0)
        result['commentary_segments'][0]['end_seconds']=1000
        with self.assertRaises(ValueError):
            make_plan(result,scope='group',group_id=None,segment_id='analysis-001')


if __name__=='__main__':
    unittest.main()
