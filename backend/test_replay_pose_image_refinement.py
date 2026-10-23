"""Current-image localization, inverse transforms and evidence isolation."""
from copy import deepcopy
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np

from core.replay_pose_image_refinement import observe_rotated,select_observations,ANGLE,JOINTS
from core.replay_pose_observation import observation_record
from core.replay_pose_clip import LocalClipReplayAnalyzer
from core.climb_replay import build_pose_samples,VideoInfo


class ImageObservationTests(unittest.TestCase):
    def setUp(self):
        xy=np.full((133,2),[200.,220.])
        xy[[5,6,11,12]]=[[150,100],[250,100],[160,220],[240,220]]
        xy[[7,8,9,10,13,14,15,16]]=[[130,150],[270,150],[110,170],[290,170],[160,270],[240,270],[150,330],[250,330]]
        xy[17:20]=[[145,340],[140,340],[155,335]]
        xy[20:23]=[[255,340],[260,340],[245,335]]
        self.xy=xy
        self.record=observation_record(xy,np.full(133,.9),frame_id=2,source_frame_id=6,
            track_id=3,size=[400,500],box=[80,50,320,360],model='pinned-test',
            model_evidence={},selection={'target_track_id':3},minimum_response=.5)
        self.evidence={'angle_degrees':ANGLE,'basis':'same_source_image_model_inference'}

    def test_inverse_input_rotation_restores_source_pixels(self):
        points=self.xy.copy()
        class Pose:
            model_input_size=(288,384)
            mean=np.array([123.675,116.28,103.53]);std=np.array([58.395,57.12,57.375])
            def preprocess(self,image,box):
                self.center=np.array([210.,245.]);self.scale=np.array([300.,400.])
                return np.zeros((384,288,3),np.float32),self.center,self.scale
            def inference(self,image):
                assert image.shape==(384,288,3)
                return image
            def postprocess(self,outputs,center,scale):
                model=(points-center+scale/2)/scale*self.model_input_size
                matrix=cv2.getRotationMatrix2D((144,192),ANGLE,1.)
                transformed=cv2.transform(model[None].astype(np.float32),matrix)[0]
                xy=transformed/self.model_input_size*scale+center-scale/2
                return xy[None],np.full((1,133),.9)
        xy,response,proof=observe_rotated(Pose(),np.zeros((500,400,3),np.uint8),[80,50,320,360])
        np.testing.assert_allclose(xy,points,atol=.0001)
        self.assertEqual(proof['source_size_wh'],[400,500])
        self.assertEqual(len(response),133)

    def test_selected_current_image_points_keep_native_evidence_and_identity(self):
        original=deepcopy(self.record);xy=self.xy.copy();xy[list(JOINTS)]+=[8,-4]
        result=select_observations(self.record,xy,np.full(133,1.2),self.evidence)
        self.assertEqual(self.record,original)
        self.assertEqual(result['joint_observations']['raw_xy_px'],original['joint_observations']['raw_xy_px'])
        self.assertEqual(result['wholebody']['raw_xy_px'],original['wholebody']['raw_xy_px'])
        self.assertEqual(result['wholebody']['raw_scores'],original['wholebody']['raw_scores'])
        self.assertEqual(result['joint_eligibility'],original['joint_eligibility'])
        self.assertEqual(result['track_id'],3)
        np.testing.assert_allclose(result['kpts_xy'][9],xy[9]/[400,500],atol=1e-6)
        self.assertEqual(result['kpts_score'][9],1.2)
        for j in set(range(133))-set(JOINTS):
            self.assertEqual(result['wholebody']['kpts_xy'][j],original['wholebody']['kpts_xy'][j])
        self.assertEqual(result['pose_evidence']['observation_kind'],'model_observation')
        self.assertNotIn('temporal_display',result)

    def test_weak_outside_nonfinite_and_ineligible_candidates_fall_back(self):
        xy=self.xy.copy();response=np.full(133,.9)
        xy[7]=[20,30];self.record['wholebody']['joint_eligibility'][7]=False
        xy[8]=[500,150];xy[9]=[np.nan,30];response[10]=.49
        result=select_observations(self.record,xy,response,self.evidence)
        for j in (7,8,9,10):self.assertEqual(result['kpts_xy'][j],self.record['kpts_xy'][j])
        self.assertNotIn(7,result['image_observation_refinement']['selected_joints'])
        self.assertFalse(result['wholebody']['joint_eligibility'][7])

    def test_detached_foot_and_impossible_limb_do_not_replace_primary(self):
        xy=self.xy.copy();xy[17]=[120,80];xy[9]=[399,499]
        result=select_observations(self.record,xy,np.full(133,.9),self.evidence)
        self.assertEqual(result['wholebody']['kpts_xy'][17],self.record['wholebody']['kpts_xy'][17])
        self.assertIn(17,result['image_observation_refinement']['rejected_joints'])
        self.assertEqual(result['kpts_xy'][9],self.record['kpts_xy'][9])

    def test_new_sample_retains_selected_native_and_primary_provenance(self):
        xy=self.xy.copy();xy[9]+=[10,5]
        result=select_observations(self.record,xy,np.full(133,1.2),self.evidence)
        sample=build_pose_samples([result],VideoInfo(400,500,30,60,2,10))[0]
        self.assertEqual(sample['image_observation_refinement'],result['image_observation_refinement'])
        self.assertEqual(sample['kpts_xy'][9],result['kpts_xy'][9])
        self.assertEqual(sample['joint_observations']['raw_xy_px'],self.record['joint_observations']['raw_xy_px'])

    def test_streaming_view_cache_reuses_inference_and_keeps_primary_context(self):
        analyzer=LocalClipReplayAnalyzer(image_refinement=True,temporal_display=False)
        analyzer._clip_tracks=Mock();analyzer._clip_tracks.selection={'target_track_id':3}
        analyzer._clip_tracks.target_observation.return_value={'box_xyxy_px':[80,50,320,360],'track_id':3}
        analyzer._pose_cache={'6':{'poses':{}}}
        xy=self.xy.copy();xy[9]+=[10,5]
        with (patch.object(analyzer,'_observe_pose_in_box',return_value=(self.xy,np.full(133,.9),None,None)),
              patch.object(analyzer,'_load_models',return_value=(object(),object())),
              patch('core.replay_pose_image_refinement.observe_rotated',return_value=(xy,np.full(133,1.2),self.evidence)) as infer):
            first=analyzer._pose_frame(np.zeros((500,400,3),np.uint8),frame_id=2,source_frame_id=6)
            second=analyzer._pose_frame(np.zeros((500,400,3),np.uint8),frame_id=2,source_frame_id=6)
        self.assertEqual(infer.call_count,1)
        self.assertEqual(first,second)
        self.assertEqual(analyzer.inference_counts['pose_image_refinement'],1)
        self.assertEqual(analyzer._previous_pose['kpts_xy'][9],self.record['kpts_xy'][9])
        self.assertNotEqual(first['kpts_xy'][9],self.record['kpts_xy'][9])

    def test_other_provider_cannot_accidentally_enable_rtmw_view(self):
        self.assertTrue(LocalClipReplayAnalyzer().image_refinement)
        analyzer=LocalClipReplayAnalyzer(observation_model='explicit.onnx',image_refinement=True)
        self.assertFalse(analyzer.image_refinement)

    def test_opposite_torso_assignment_cannot_mix_crossed_limbs(self):
        xy=self.xy.copy()
        xy[[5,6]]=xy[[6,5]];xy[[11,12]]=xy[[12,11]]
        xy[list(JOINTS)]+=[12,5]
        result=select_observations(self.record,xy,np.full(133,.9),self.evidence)
        self.assertEqual(result['kpts_xy'],self.record['kpts_xy'])
        self.assertEqual(result['wholebody']['kpts_xy'],self.record['wholebody']['kpts_xy'])
        self.assertEqual(result['image_observation_refinement']['selected_joints'],[])


if __name__=='__main__':unittest.main()
