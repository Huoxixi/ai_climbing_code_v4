"""Kinematic selection and mass estimates, with synthetic pixels only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from core.replay_center_of_mass import center_of_mass_point
from core.replay_important_actions import enrich_important_actions
from core.replay_action_features import enrich_action_features
from core.replay_commentary import VisionCommentaryEngine, validate_response
from core.replay_torso_trajectory import center_of_mass_trajectory
from test_replay_action_trajectory import fixture
from test_replay_professional import config


def important_fixture(kind='HIGH_STEP'):
    data = fixture(21)
    data['video'].update(fps=30,frame_count=121,duration_seconds=4)
    data['source_duration_seconds'] = 4
    for i, row in enumerate(data['pose_samples']):
        row.update(time_seconds=i/5,source_frame_id=i*6)
        progress=min(i,4)/4 if kind=='LEG_DRIVE' else min(i,10)/10
        if kind=='HIGH_STEP':
            row['kpts_xy'][13] = [.37+.13*progress,.74-.22*progress]
            row['kpts_xy'][15] = [.36+.12*progress,.88-.28*progress]
        elif kind=='LEG_DRIVE':
            for joint in range(13):row['kpts_xy'][joint][1]-=.18*progress
            row['kpts_xy'][13]=[.52-.14*progress,.74-.06*progress]
            row['kpts_xy'][14]=[.53,.74-.06*progress]
        elif kind=='WEIGHT_SHIFT':
            for joint in range(13):row['kpts_xy'][joint][0]+=.12*progress
            for joint in (13,14):row['kpts_xy'][joint][0]+=.06*progress
        if i>10:
            row['kpts_xy'][9][1]-=(i-10)*.018
            row['kpts_xy'][7][1]-=(i-10)*.009
    data['groups']=[{'id':'important','start_seconds':0,'end_seconds':2,'events':[]},
                    {'id':'ordinary','start_seconds':2.2,'end_seconds':4,'events':[]}]
    return data


class MassTests(unittest.TestCase):
    def test_raised_leg_changes_mass_point_without_moving_torso_center(self):
        data=important_fixture()
        a,b=data['pose_samples'][0],data['pose_samples'][10]
        self.assertEqual([a['kpts_xy'][i] for i in (5,6,11,12)], [b['kpts_xy'][i] for i in (5,6,11,12)])
        self.assertLess(center_of_mass_point(b)[1],center_of_mass_point(a)[1]-.02)

    def test_missing_leg_or_head_does_not_become_a_torso_fallback(self):
        for joint in (13,15,9):
            sample=important_fixture()['pose_samples'][0]
            sample['kpts_score'][joint]=.1
            self.assertIsNone(center_of_mass_point(sample))
        sample=important_fixture()['pose_samples'][0]
        for joint in (0,3,4):sample['kpts_score'][joint]=.1
        self.assertIsNone(center_of_mass_point(sample))

    def test_missing_mass_sample_breaks_trajectory_and_registration_removes_camera_motion(self):
        data=important_fixture('WEIGHT_SHIFT')
        data['holds']=[{'id':1,'bbox':[.3,.7,.1,.1]}, {'id':2,'bbox':[.3,.1,.1,.1]}, {'id':3,'bbox':[.6,.7,.1,.1]}]
        data['attempt']={'contacts':[{'limb':limb,'hold_id':3 if limb=='right_foot' else 1,'start_time_seconds':0,'end_time_seconds':4}
            for limb in ('left_hand','right_hand','left_foot','right_foot')]}
        data['pose_samples'][5]['kpts_score'][13]=.1
        route=center_of_mass_trajectory(data)
        self.assertEqual(route['label'],'估算重心')
        self.assertNotIn('frame-30',[p['frame_id'] for run in route['segments'] for p in run])
        self.assertGreaterEqual(len(route['segments']),2)
        before=center_of_mass_trajectory(copy.deepcopy(data))
        for i,row in enumerate(data['pose_samples']):
            dx=i*.001
            row['kpts_xy']=[[x+dx,y] for x,y in row['kpts_xy']]
            row['wall_reference_transform']=[[1,0,-dx*720],[0,1,0],[0,0,1]]
        self.assertEqual(center_of_mass_trajectory(data)['segments'],before['segments'])


class SelectionTests(unittest.TestCase):
    def test_slow_extension_and_unfinished_action_are_silent(self):
        data=important_fixture('LEG_DRIVE')
        for i,row in enumerate(data['pose_samples']):
            row['time_seconds']=i*.6
        data['groups'][0]['end_seconds']=6
        self.assertIsNone(enrich_important_actions(data)['groups'][0]['important_action'])
        data=important_fixture('HIGH_STEP')
        data['groups'][0]['ending_stable']=False
        self.assertIsNone(enrich_important_actions(data)['groups'][0]['important_action'])

    def test_sustained_side_lean_and_brief_swing(self):
        data=important_fixture('SIDE_HANG')
        aspect=np.array([720.,880.])/720.
        pivot=np.array([.45,.6])*aspect
        for i,row in enumerate(data['pose_samples']):
            angle=np.deg2rad(min(i,5)*6)
            rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
            points=np.array(row['kpts_xy'])*aspect
            row['kpts_xy']=((points-pivot)@rotation.T+pivot).__truediv__(aspect).tolist()
        selected=enrich_important_actions(data)['groups'][0]['important_action']
        self.assertEqual(selected['kind'],'SIDE_HANG')
        self.assertAlmostEqual(abs(selected['relative_displacement']['projected_torso_tilt_degrees']),30,delta=2)
        data['pose_samples'][8]['kpts_score'][5]=.1
        self.assertIsNone(enrich_important_actions(data)['groups'][0]['important_action'])

    def test_each_important_mechanism_is_selected_and_ordinary_hand_motion_is_silent(self):
        for kind in ('HIGH_STEP','LEG_DRIVE','WEIGHT_SHIFT'):
            with self.subTest(kind=kind):
                result=enrich_important_actions(important_fixture(kind))
                self.assertEqual(result['groups'][0]['important_action']['kind'],kind)
                self.assertIsNone(result['groups'][1]['important_action'])
                self.assertEqual(result['commentary_policy']['selected_event_count'],1)

    def test_normal_movement_noisy_angles_and_missing_evidence_are_not_key_actions(self):
        data=fixture()
        for i,row in enumerate(data['pose_samples']):row['kpts_xy'][9][1]-=i*.015
        self.assertEqual(enrich_important_actions(data)['commentary_policy']['selected_event_count'],0)
        for joint in (13,15):
            data=important_fixture()
            data['pose_samples'][5]['kpts_score'][joint]=.1
            self.assertIsNone(enrich_important_actions(data)['groups'][0]['important_action'])

    def test_only_key_event_is_sent_and_generic_one_line_return_is_rejected(self):
        data=important_fixture()
        data=enrich_action_features(data,{'result':data})
        self.assertTrue(data['event_validation']['analysis_valid'])
        self.assertEqual(data['commentary_policy']['selected_event_count'],1)
        requests=[]
        def provider(**kwargs):
            facts=json.loads(kwargs['messages'][1]['content'][0]['text'])
            requests.append(facts)
            self.assertEqual(len(facts['actions']),1)
            action=facts['actions'][0]
            return {'content':json.dumps({'comments':[{'action_id':action['id'],
                'text':'左腿屈膝抬高，膝部接近髋部高度，随后保持较高脚位，形成高抬腿动作。',
                'evidence_frame_ids':list(facts['frames'][action['id']])}]}),'usage':{}}
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),30,(96,64))
            for _ in range(121):writer.write(np.zeros((64,96,3),np.uint8))
            writer.release()
            output=VisionCommentaryEngine(config(cost_control_enabled=False),provider=provider).run(
                source,{},data,cancelled=lambda:False,usage_callback=lambda event:None)
        self.assertEqual(len(requests),1)
        self.assertEqual(len(output['commentary_segments']),1)
        self.assertEqual(output['commentary_segments'][0]['group_id'],'important')
        action=data['action_evidence']['commentary_actions'][0]
        anchors={r['frame_id']:r for r in action['evidence_frames']}
        answer={'comments':[{'action_id':action['id'],'text':'左脚向上移动。','evidence_frame_ids':list(anchors)}]}
        self.assertEqual(validate_response(answer,[action],{action['id']:anchors}),{})

    def test_no_important_actions_never_opens_provider(self):
        data=enrich_action_features(important_fixture(),{'result':important_fixture()})
        data['action_evidence']['commentary_actions']=[]
        provider=Mock(side_effect=AssertionError('No paid calls'))
        with self.assertRaisesRegex(ValueError,'重要动作'):
            VisionCommentaryEngine(config(),provider=provider).run(Path('unused.mp4'),{},data,
                cancelled=lambda:False,usage_callback=lambda event:None)
        provider.assert_not_called()

    def test_saved_explicit_omission_is_silent_after_local_recovery(self):
        data=enrich_action_features(important_fixture(),{'result':important_fixture()})
        action=data['action_evidence']['commentary_actions'][0]
        response={'content':json.dumps({'comments':[],'omitted_action_ids':[action['id']]}),
            '_actions':[action], '_frames':{action['id']:{r['frame_id']:r for r in action['evidence_frames']}}}
        provider=Mock(side_effect=AssertionError('No network'))
        result=VisionCommentaryEngine(config(),provider=provider).recover(data,[response],cancelled=lambda:False)
        self.assertEqual(result['commentary_segments'],[])
        self.assertEqual(enrich_important_actions(result)['commentary_policy']['selected_event_count'],0)
        provider.assert_not_called()


if __name__=='__main__':unittest.main()
