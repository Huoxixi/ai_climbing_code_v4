import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import cv2
import numpy as np

from core.replay_commentary import validate_response, apply_comments, VERSION
from core.replay_analysis_view import AnalysisView, visual_evidence, COLORS
from core.replay_torso_trajectory import WINDOW_BASIS
from core.replay_center_of_mass import VERSION as MASS_VERSION, center_of_mass_point
from core.replay_action_renderer import make_plan, validate, ActionComposition
from core.replay_template_renderer import _render
from core.replay_actions import organize
from core.replay_vision_settings import save_settings, VisionSettings
import test_replay_professional as professional
import test_replay_actions as lifecycle


def scene():
    poses=[]
    for frame in (0,2,4,6):
        xy=[[.5,.5] for _ in range(17)]
        for i,p in {5:[.4,.3],6:[.6,.3],7:[.3,.4],8:[.7,.4],9:[.2,.2],10:[.8,.2],11:[.4,.6],12:[.6,.6],13:[.35,.75],14:[.65,.75],15:[.3,.9],16:[.7,.9]}.items():xy[i]=p
        poses.append({'observed':True,'source_frame_id':frame,'time_seconds':frame/4,
            'kpts_xy':xy,'kpts_score':[.9]*17,'wall_alignment':'reference',
            'wall_reference_transform':[[1,0,0],[0,1,0],[0,0,1]]})
    return {'video':{'width':96,'height':64,'fps':4,'frame_count':8,'duration_seconds':2},
        'holds':[{'id':1,'polygon':[[.1,.1],[.3,.1],[.3,.3],[.1,.3]]}],
        'pose_samples':poses,'attempt':{'contacts':[{'limb':'left_hand','hold_id':1,'start_source_frame':0,'end_source_frame':1}]},
        'center_of_mass_trajectory':{'version':MASS_VERSION,'climbing_window':{'basis':WINDOW_BASIS},'segments':[[{'time_seconds':0,'xy':[.5,.7]},{'time_seconds':1,'xy':[.3,.7]},{'time_seconds':1.5,'xy':[.3,.9]}]]}}


class VisionSegmentTests(unittest.TestCase):
    def inputs(self):
        action=professional.action_fixture()['action_evidence']['actions'][0]
        ev=action['evidence_frames']; chosen=[ev[round(i*(len(ev)-1)/6)] for i in range(7)]
        anchors={p['frame_id']:p for p in chosen};ids=list(anchors)
        parts=[{'start_frame_id':ids[0],'end_frame_id':ids[3],'evidence_frame_ids':ids[:4],'text':'左手向上移动。'},
               {'start_frame_id':ids[3],'end_frame_id':ids[-1],'evidence_frame_ids':ids[3:],'text':'左手继续向右移动。'}]
        return action,anchors,{'comments':[{'action_id':action['id'],'segments':parts}]}

    def test_model_cannot_replace_local_event_boundaries(self):
        action,anchors,answer=self.inputs()
        comments=validate_response(answer,[action],{action['id']:anchors})
        self.assertEqual(comments,{})
        ids=list(anchors)
        answer['comments'][0]['segments']=[{'start_frame_id':ids[0],'end_frame_id':ids[-1],
            'evidence_frame_ids':ids,'text':'左手向上移动。'}]
        comments=validate_response(answer,[action],{action['id']:anchors})
        result=apply_comments(professional.action_fixture(),comments,{'model':'synthetic'})
        self.assertEqual(len(result['commentary_segments']),1)
        self.assertEqual(result['commentary_segments'][0]['start_seconds'],action['start_seconds'])
        self.assertEqual(result['commentary_segments'][0]['end_seconds'],action['end_seconds'])
        self.assertEqual(result['commentary_segments'][0]['segmentation_basis'],'local_trajectory_event')

    def test_invented_or_overlapping_or_wrong_limb_segments_are_rejected(self):
        action,anchors,answer=self.inputs()
        for change in ('invented','overlap','side','reversed'):
            bad=copy.deepcopy(answer)
            parts=bad['comments'][0]['segments']
            if change=='invented':parts[0]['start_frame_id']='frame-999999'
            if change=='overlap':parts[1]=copy.deepcopy(parts[0])
            if change=='side':parts[0]['text']='右手向上移动。'
            if change=='reversed':parts[0]['evidence_frame_ids'].reverse()
            self.assertEqual(validate_response(bad,[action],{action['id']:anchors}),{})

    def test_export_uses_exact_vision_segment_range(self):
        result=organize({'result':lifecycle.evidence()})
        group=result['groups'][0]
        start,end=group['start_seconds']+.1,group['end_seconds']-.1
        result['commentary_segments']=[{'id':'segment-1','group_id':group['id'],'start_seconds':start,'end_seconds':end}]
        plan=make_plan(result,scope='group',group_id=group['id'],segment_id='segment-1',analysis_right=True)
        self.assertEqual(plan['source_start_frame'],int(np.floor(start*4)))
        self.assertEqual(plan['source_stop_frame'],int(np.ceil(end*4)))
        self.assertEqual(plan['width'],result['video']['width']*2)
        with self.assertRaises(ValueError):make_plan(result,scope='group',group_id=group['id'],segment_id='invented')

    def test_paid_commentary_does_not_read_or_encode_old_overlay(self):
        fixture=lifecycle.ActionLifecycleTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        professional.prepare_paid_fixture(fixture)
        save_settings(fixture.store.root.parent,'alice',VisionSettings(**professional.config()))
        engine=Mock();engine.run.side_effect=lambda source,job,result,**kwargs:result
        fixture.manager.renderer=Mock(side_effect=RuntimeError('must not run'))
        fixture.manager.presentation_source=Mock(side_effect=RuntimeError('must not read old overlay'))
        with patch('core.replay_action_jobs.VisionCommentaryEngine',return_value=engine):
            response=fixture.client.post(fixture.url,json={'cloud_consent':True,'consent_version':VERSION,'budget_confirmed':True})
            self.assertEqual(response.status_code,202)
            result=fixture.wait()
        self.assertEqual(result['task']['status'],'succeeded')
        self.assertFalse(result['media_ready'])
        self.assertIn('replay_visualization',result['result'])
        fixture.manager.renderer.assert_not_called()
        fixture.manager.presentation_source.assert_not_called()


class AnalysisViewTests(unittest.TestCase):
    def test_invalid_contact_intervals_do_not_light_export_or_final_summary(self):
        result=scene(); result['pose_samples']=[]
        raw=np.full((64,96,3),30,np.uint8)
        result['attempt']['contacts']=[]
        expected=AnalysisView(result).frame(raw,0,(192,64))
        for start,end in [(-1,2),(float('-inf'),2),(0,float('inf')),(2,1),(float('nan'),2)]:
            result['attempt']['contacts']=[{'limb':'left_hand','hold_id':1,
                                          'start_source_frame':start,'end_source_frame':end}]
            np.testing.assert_array_equal(AnalysisView(result).frame(raw,0,(192,64)),expected)
            final=AnalysisView(result).frame(raw,7,(192,64))
            self.assertLess(final[10,122].mean(),40)

    def test_final_frame_lights_used_holds_and_seeking_back_clears_history(self):
        result=scene()
        result['holds'].extend([{'id':2,'polygon':[[.6,.1],[.8,.1],[.8,.3],[.6,.3]]},
            {'id':3,'polygon':[[.1,.75],[.25,.75],[.25,.9],[.1,.9]]}])
        result['attempt']['contacts'].append({'limb':'right_foot','hold_id':2,'start_source_frame':2,'end_source_frame':3})
        view=AnalysisView(result);raw=np.full((64,96,3),30,np.uint8)
        early=view.frame(raw,4,(192,64));final=view.frame(raw,7,(192,64));back=view.frame(raw,4,(192,64))
        for x in (110,163):
            self.assertLess(early[10,x].mean(),40)
            np.testing.assert_allclose(final[10,x],(75,208,241),atol=1)
        self.assertLess(final[53,112].mean(),40,'unused hold remains unfilled')
        np.testing.assert_array_equal(back,early)

    def test_old_four_limb_trajectory_is_rebuilt_without_rewriting_record(self):
        from test_replay_important_actions import important_fixture
        result=important_fixture('WEIGHT_SHIFT')
        result['holds']=[{'id':1,'bbox':[.3,.7,.1,.1]}, {'id':2,'bbox':[.6,.7,.1,.1]}]
        result['attempt']={'contacts':[{'limb':limb,'hold_id':hold,'start_time_seconds':.4,'end_time_seconds':4}
            for limb,hold in [('left_hand',1),('right_foot',2)]]}
        result['center_of_mass_trajectory']={'version':MASS_VERSION,'segments':[],
            'climbing_window':{'basis':'four_limb_overlap_to_two_hand_finish_overlap'}}
        original=copy.deepcopy(result)
        trajectory=visual_evidence(result)['center_of_mass_trajectory']
        self.assertEqual(trajectory['climbing_window']['start_seconds'],.4)
        self.assertTrue(trajectory['segments'])
        self.assertEqual(result,original)

    def test_reviewed_time_intervals_override_stale_frame_bounds(self):
        result=scene()
        result['attempt']['contacts'][0].update(start_time_seconds=1,end_time_seconds=1.25)
        view=AnalysisView(result);raw=np.full((64,96,3),30,np.uint8)
        self.assertLess(view.frame(raw,0,(192,64))[10,122].mean(),40)
        np.testing.assert_allclose(view.frame(raw,4,(192,64))[10,122],COLORS['left_hand'],atol=1)

    def test_display_never_bridges_missing_pose_or_low_confidence_joint(self):
        result=scene()
        result['pose_samples'][1]['observed']=False
        view=AnalysisView(result)
        self.assertNotIn(1,view.timeline)
        self.assertNotIn(3,view.timeline)
        result=scene()
        result['pose_samples'][1]['kpts_score'][9]=0
        view=AnalysisView(result)
        self.assertEqual(view.timeline[1]['kpts_score'][9],0)
        result['pose_samples']=[result['pose_samples'][0],result['pose_samples'][-1]]
        self.assertNotIn(3,AnalysisView(result).timeline)

    def test_left_pixels_are_exact_original_and_right_has_pose_and_current_hold(self):
        result=scene();view=AnalysisView(result);raw=np.full((64,96,3),30,np.uint8)
        frame=view.frame(raw,0,(192,64))
        np.testing.assert_array_equal(frame[:,:96],raw)
        np.testing.assert_allclose(frame[10,122],COLORS['left_hand'],atol=1)
        center=center_of_mass_point(result['pose_samples'][0])
        self.assertGreater(frame[round(center[1]*64),96+round(center[0]*96)].mean(),235)
        departed=view.frame(raw,2,(192,64))
        self.assertLess(departed[10,122].mean(),40)

    def test_registered_skeleton_moves_into_same_wall_coordinate_plane(self):
        result=scene()
        for sample in result['pose_samples']:sample['wall_reference_transform'][0][2]=9.6
        evidence=visual_evidence(result)
        self.assertAlmostEqual(evidence['pose_samples'][0]['kpts_xy'][5][0],.5)
        result['pose_samples'][0]['wall_alignment']='failed'
        self.assertFalse(visual_evidence(result)['pose_samples'][0]['observed'])

    def test_route_is_progressive_and_seeking_back_does_not_leave_future_points(self):
        result=scene();view=AnalysisView(result);raw=np.full((64,96,3),30,np.uint8)
        early=view.frame(raw,0,(192,64));late=view.frame(raw,6,(192,64));back=view.frame(raw,0,(192,64))
        self.assertLess(early[51,125].mean(),40)
        self.assertGreater(late[51,125].mean(),100)
        np.testing.assert_array_equal(back,early)

    def test_encoded_export_keeps_left_clean_and_does_not_bake_commentary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.mp4';target=root/'export.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),4,(96,64))
            for _ in range(8):writer.write(np.full((64,96,3),30,np.uint8))
            writer.release()
            result=organize({'result':scene()});result['center_of_mass_trajectory']=scene()['center_of_mass_trajectory']
            plan=make_plan(result,speed=1,analysis_right=True)
            meta=_render(source,plan,target,root/'metrics.json',composition_factory=ActionComposition,validator=validate)
            self.assertEqual(meta['frame_count'],8)
            capture=cv2.VideoCapture(str(target));okay,frame=capture.read();capture.release()
            self.assertTrue(okay)
            self.assertLess(float(frame[:,:96].std()),3)
            self.assertGreater(float(frame[:,96:].std()),15)


if __name__=='__main__':unittest.main()

