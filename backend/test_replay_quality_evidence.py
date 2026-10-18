"""Evidence conservation checks; these are not model accuracy scores."""
import unittest
from unittest.mock import patch

import numpy as np
import cv2

from core.climb_replay import AliyunReplayAnalyzer
from core.replay_hold_fusion import fuse_hold_detections, select_sampled_route_holds, contour_overlap, image_content_bounds, align_pose_record


class HoldEvidenceTests(unittest.TestCase):
    def test_retry_reinfers_cross_group_conflict_without_smoothing_fast_real_motion(self):
        from core.replay_pose_context import context_proposal,supports_retry
        points=[[.5,.3]]*17
        for joint,xy in {5:[.4,.4],6:[.6,.4],11:[.4,.65],12:[.6,.65],
                         9:[.35,.35],10:[.65,.35],15:[.4,.85],16:[.6,.85]}.items():
            points[joint]=xy
        scores=[.9]*17
        previous={'kpts_xy':points,'kpts_score':scores}
        corrupt=list(points)
        for a,b in [(9,15),(10,16)]:
            corrupt[a],corrupt[b]=points[b],points[a]
        proposal=context_proposal(previous,corrupt,scores,[720,1280],.1)
        self.assertIsNotNone(proposal)
        self.assertTrue(supports_retry(proposal,points,scores,[720,1280]))
        fast=list(points);fast[9]=[.3,.05]
        self.assertIsNone(context_proposal(previous,fast,scores,[720,1280],.1))
        high_step=list(points);high_step[15]=points[9]
        proposal=context_proposal(previous,high_step,scores,[720,1280],.1)
        self.assertIsNotNone(proposal)
        self.assertFalse(supports_retry(proposal,high_step,scores,[720,1280]))

    def test_saturated_pose_response_is_recorded_without_changing_location_or_inventing_probability(self):
        from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
        from test_replay_pose_rtmw import fake_models
        analyzer=LocalRTMWReplayAnalyzer()
        scores=[.8]*133
        scores[9]=4.5
        analyzer._models=fake_models(scores=scores)
        record=analyzer._pose_frame(np.zeros((100,100,3),np.uint8),frame_id=0,source_frame_id=0)
        self.assertEqual(record['wholebody']['raw_scores'][9],4.5)
        self.assertEqual(record['wholebody']['joint_status'][9],'response_saturated')
        self.assertEqual(record['wholebody']['raw_xy_px'][9],[50.,50.])
        self.assertEqual(record['kpts_xy'][9],[.5,.5])

    def test_wholebody_and_body_map_together_without_mutating_source_evidence(self):
        import copy
        source={'kpts_xy':[[.5,.5]]*17,'kpts_score':[.9]*17,
                'wholebody':{'kpts_xy':[[.5,.5]]*133,'kpts_score':[.9]*133,
                             'coordinates':'source_image_normalized','raw_xy_px':[[50,100]]*133}}
        before=copy.deepcopy(source)
        mapped=align_pose_record(source,np.array([[1.,0,10],[0,1,20],[0,0,1.]]),100,200)
        self.assertEqual(mapped['kpts_xy'][9],[.6,.6])
        self.assertEqual(mapped['wholebody']['kpts_xy'][99],[.6,.6])
        self.assertEqual(mapped['wholebody']['raw_xy_px'][99],[50,100])
        self.assertEqual(source,before)
        missing=align_pose_record(source,None,100,200)
        self.assertEqual(missing['wholebody']['kpts_score'],[0.]*133)
        self.assertEqual(source,before)

    def test_same_hold_has_same_area_filter_with_or_without_encoded_bars(self):
        image = np.full((300,200,3),100,np.uint8)
        padded = cv2.copyMakeBorder(image,0,0,200,200,cv2.BORDER_CONSTANT,value=0)
        bounds = image_content_bounds(padded)
        hold = {'bbox':[.1,.2,.045,.045],'contour_source':'climbing_model_native_mask',
                'route_candidate':True,'color_group':'青色','appearances':3,'score':.95,
                'polygon':[[.1,.2],[.145,.2],[.145,.245],[.1,.245]],
                'contour_evidence':{'version':'native-colour-contour-support-v1','support_frames':[0,3,6]}}
        padded_hold = {**hold,'bbox':[(200+20)/600,.2,.045/3,.045],
                       'polygon':[[(200+x*200)/600,y] for x,y in hold['polygon']]}
        first = select_sampled_route_holds([hold],sample_group='青色')[0]
        legacy = select_sampled_route_holds([padded_hold],sample_group='青色')[0]
        fixed = select_sampled_route_holds([padded_hold],sample_group='青色',content_bounds=bounds)[0]
        self.assertEqual((len(first),len(legacy),len(fixed)),(1,1,1))
        self.assertEqual(padded_hold['bbox'],[(200+20)/600,.2,.045/3,.045])

    def test_dark_content_and_small_borders_keep_the_full_area_basis(self):
        self.assertEqual(image_content_bounds(np.zeros((300,200,3),np.uint8)),[0,0,1,1])
        image = np.full((300,200,3),100,np.uint8)
        image[:5] = 0
        image[:, :5] = 0
        self.assertEqual(image_content_bounds(image),[0,0,1,1])
        image[:,80:120] = 0
        self.assertEqual(image_content_bounds(image),[0,0,1,1])

    def test_contour_policy_keeps_disjoint_shapes_with_the_same_box(self):
        a = {'bbox':[.1,.1,.1,.1], 'polygon':[[.1,.1],[.19,.1],[.1,.19]], 'score':.9}
        b = {'bbox':[.1,.1,.1,.1], 'polygon':[[.2,.2],[.11,.2],[.2,.11]], 'score':.9}
        self.assertEqual(len(fuse_hold_detections([[a],[b]])), 1)
        self.assertEqual(len(fuse_hold_detections([[a],[b]], geometry='contour')), 2)
        self.assertEqual(contour_overlap(a,b),(0.,0.))
        self.assertEqual(contour_overlap(a,a),(1.,1.))

    def test_fusion_retains_observations_from_discarded_contour(self):
        def hold(frame, score):
            return {'bbox': [.1, .2, .1, .1], 'score': score, 'source_frame': frame,
                    'observation_id': f'{frame}-0', 'polygon': [[.1,.2],[.2,.2],[.2,.3],[.1,.3]]}
        result = fuse_hold_detections([[hold(4, .95)], [hold(17, .8)]])[0]
        self.assertEqual(result['support_frames'], [4, 17])
        self.assertEqual(result['observation_ids'], ['4-0', '17-0'])
        self.assertEqual(result['source_frame'], 4)

    def test_selection_assigns_a_reason_to_every_candidate_without_changing_input(self):
        common = {'contour_source': 'climbing_model_native_mask', 'route_candidate': True,
                  'appearances': 3, 'score': .9, 'color_group': '红色',
                  'polygon':[[.1,.1],[.2,.1],[.2,.2],[.1,.2]],
                  'contour_evidence':{'version':'native-colour-contour-support-v1','support_frames':[0,3,6]}}
        values = [{**common, 'bbox': [.1,.1,.1,.1], 'candidate_id': 'good'},
                  {**common, 'bbox': [.8,.8,.01,.01], 'candidate_id': 'small',
                   'polygon':[[.8,.8],[.81,.8],[.81,.81],[.8,.81]],
                   'contour_evidence':{'version':'native-colour-contour-support-v1','support_frames':[0]}},
                  {**common, 'bbox': [.1,.1,.1,.1], 'candidate_id': 'duplicate'}]
        trace = []
        selected, rejects, _ = select_sampled_route_holds(values, sample_group='红色', trace=trace)
        self.assertEqual(len(trace), len(values))
        self.assertEqual({row['candidate_id'] for row in trace}, {'good','small','duplicate'})
        self.assertEqual({row.get('reason') for row in trace}, {None,'insufficient_colour_contour_support','overlapping_mask'})
        self.assertTrue(all('selection_reason' not in hold for hold in values))

    def test_failed_registration_keeps_frame_position_and_reason(self):
        frame = np.zeros((60, 80, 3), np.uint8)
        mask = np.zeros((60, 80), np.uint8)
        mask[10:30, 20:40] = 255
        outputs = [([mask],[.9]), ([mask],[.9]), ([mask],[.9])]
        trace = []
        with patch('core.climb_replay._climbing_model_masks_batch', return_value=(outputs,'test')):
            _, _, diagnostics, _, _ = AliyunReplayAnalyzer._video_holds(frames=[(0,frame),(6,frame),(12,frame)],
                route_color='红色', route_color_sample=None, saved_route_reference=None,
                deadline=10**12, progress=lambda *_: None, cancelled=lambda: False, trace=trace)
        self.assertEqual(diagnostics['sampled_source_frames'], [0,6,12])
        self.assertEqual(diagnostics['aligned_candidates_by_frame'], [1,0,0])
        self.assertEqual([row['source_frame'] for row in trace if row['stage']=='registration'], [6,12])
        self.assertEqual([row['model_candidates'] for row in trace if row['stage']=='registration'], [1,1])


if __name__ == '__main__':
    unittest.main()
