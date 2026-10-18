import copy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from core.replay_hold_expansion import expand_native_evidence, dark_material_evidence, _conflicts
from core.replay_hold_resampling import resample_weak_candidates,refine_weak_candidates,refine_native_fragments


class NativeExpansionContractTests(unittest.TestCase):
    def detection(self, frame, *, partial=False, category=1, colour='绿色'):
        x = 0. if partial else .2
        return dict(source_frame=frame, observation_id=f'frame-{frame}-mask-0',
            polygon=[[x,.2],[.4,.2],[.4,.4],[x,.4]],bbox=[x,.2,.4-x,.2],
            contour_source='climbing_model_native_mask',contour_complete=not partial,
            native_class=category,color_group=colour,route_candidate=True,score=.95,
            boundary_quality={'edge_fraction':.95})

    def select(self, rows, existing=(), **kw):
        return expand_native_evidence(frames=[],outputs=[],detections=[rows],
            existing=list(existing),sample_group='绿色',material=False,**kw)[0]

    def test_stable_native_volume_can_be_added(self):
        rows=[self.detection(fr) for fr in [0,30,60]]
        selected=self.select(rows)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['support_frames'],[0,30,60])
        self.assertEqual(selected[0]['contour_source'],'climbing_model_native_mask')

    def test_repeated_same_frame_masks_are_not_independent_support(self):
        rows=[self.detection(0) for _ in range(5)]
        self.assertFalse(self.select(rows))

    def test_two_frames_do_not_satisfy_stricter_volume_acceptance(self):
        self.assertFalse(self.select([self.detection(fr) for fr in [0,30]]))

    def test_existing_correct_or_unknown_contour_is_never_replaced(self):
        old=self.detection(5);old.update(score=.4,unknown=True)
        before=copy.deepcopy(old)
        self.assertFalse(self.select([self.detection(fr) for fr in [0,30,60]],[old]))
        self.assertEqual(old,before)

    def test_visible_partial_masks_never_claim_hidden_completeness(self):
        rows=[self.detection(fr,partial=True) for fr in [0,30,60]]
        h,=self.select(rows)
        self.assertFalse(h['contour_complete'])
        self.assertFalse(h['contour_evidence']['partial_contour_complete'])
        self.assertEqual(h['polygon'],rows[0]['polygon'])

    def test_partial_masks_need_high_cross_frame_shape_agreement(self):
        rows=[self.detection(fr,partial=True) for fr in [0,30,60]]
        rows[-1]['polygon'][1][0]=.6
        self.assertFalse(self.select(rows))

    def test_another_colour_or_unqualified_metric_cannot_contribute(self):
        rows=[self.detection(fr) for fr in [0,30,60]]
        for key,value in [('color_group','青色'),('route_candidate',False)]:
            altered=copy.deepcopy(rows);altered[-1][key]=value
            self.assertFalse(self.select(altered))

    def test_manual_geometry_does_not_count_as_native_evidence(self):
        rows=[self.detection(fr) for fr in [0,30,60]]
        rows[-1]['contour_source']='user_drawn_polygon'
        self.assertFalse(self.select(rows))

    def test_bool_frame_ids_do_not_count_as_real_independent_frames(self):
        self.assertFalse(self.select([self.detection(fr) for fr in [True,False,30]]))

    def test_different_volume_predictions_are_deduplicated(self):
        rows=[self.detection(fr) for fr in [0,30,60]]*2
        self.assertEqual(len(self.select(rows)),1)

    def test_true_grey_white_and_coloured_bodies_are_not_black(self):
        mask=np.zeros((80,80),np.uint8);mask[10:70,10:70]=1
        for value in [100,160,220]:
            image=np.full((80,80,3),value,np.uint8)
            self.assertFalse(dark_material_evidence(image,mask,[50,50,50])['qualified'])
        green=np.full((80,80,3),(40,130,60),np.uint8)
        self.assertFalse(dark_material_evidence(green,mask,[50,50,50])['qualified'])

    def test_small_dark_hole_in_grey_body_is_not_black_material(self):
        image=np.full((80,80,3),130,np.uint8);image[35:40,35:40]=40
        self.assertFalse(dark_material_evidence(image,np.ones((80,80),np.uint8),[50,50,50])['qualified'])

    def test_chalk_over_connected_dark_material_has_separate_surface_identity(self):
        image=np.full((80,80,3),100,np.uint8);image[15:45,15:45]=45
        evidence=dark_material_evidence(image,np.ones((80,80),np.uint8),[50,50,50])
        self.assertTrue(evidence['qualified'])
        self.assertIn(evidence['surface_colour'],['灰色','待确认'])

    def test_no_extra_inference_without_video_or_for_other_target_colours(self):
        def forbidden(*args,**kwargs):raise AssertionError('unexpected model call')
        args=dict(source_video=None,frames=[],outputs=[],detections=[],existing=[],
            sample_group='黑色',sample_rgb=None,reference_frame=0,model_fn=forbidden,
            polygon_fn=forbidden,alignment_fn=forbidden,deadline=0,cancelled=lambda:False,progress=forbidden)
        self.assertEqual(resample_weak_candidates(**args)[0],[])
        args.update(source_video='does-not-exist.mp4',sample_group='绿色')
        self.assertEqual(resample_weak_candidates(**args)[0],[])

    def pipeline(self):
        from core.climb_replay import AliyunReplayAnalyzer
        image=np.full((80,80,3),(45,140,60),np.uint8)
        mask=np.zeros((80,80),np.uint8);mask[20:60,20:60]=255
        frames=[(fr,image.copy()) for fr in (0,30,60)]
        def detector(images,*args,**kw):
            if kw.get('native_metadata') is not None:kw['native_metadata'].extend({'classes':[0]} for _ in images)
            return [([mask.copy()],[.99]) for _ in images],'constructed'
        with patch('core.climb_replay._climbing_model_masks_batch',side_effect=detector),patch('core.climb_replay.align_to_reference',return_value=(np.eye(3),{})):
            return AliyunReplayAnalyzer._video_holds(frames=frames,route_color='绿色',route_color_sample=None,
                saved_route_reference=None,deadline=1000000000,progress=lambda *_:None,cancelled=lambda:False,
                reference_source_frame=0)

    def test_additional_inference_failure_preserves_working_base_route(self):
        with patch('core.replay_hold_expansion.expand_native_evidence',return_value=([],{'version':'test','added':0})):
            expected=self.pipeline()[0]
        with patch('core.replay_hold_expansion.expand_native_evidence',side_effect=RuntimeError('unavailable')):
            result=self.pipeline()
        self.assertEqual(result[0],expected)
        self.assertEqual(result[2]['native_route_expansion']['status'],'native_expansion_unavailable')

    def test_cancelled_additional_work_is_not_swallowed_as_fallback(self):
        from core.climb_replay import ReplayCancelled
        for exception in (ReplayCancelled('cancelled'),InterruptedError('cancelled')):
            with patch('core.replay_hold_resampling.resample_weak_candidates',side_effect=exception):
                with self.assertRaises(type(exception)):self.pipeline()

    def test_model_refinement_must_not_invade_an_existing_instance(self):
        old=self.detection(0)
        new=self.detection(1);new['polygon']=[[.35,.2],[.55,.2],[.55,.4],[.35,.4]]
        self.assertFalse(_conflicts(new,[old]))
        self.assertTrue(_conflicts(new,[old],limit=.05))

    def test_prompt_copies_do_not_become_independent_model_observations(self):
        image=np.ones((80,80,3),np.uint8)*50
        d=self.detection(0);d['native_class']=0
        with patch('core.replay_hold_recovery._predictor',side_effect=AssertionError('no model should be called')):
            added,_=refine_weak_candidates(frames=[(0,image)]*4,outputs=[],detections=[[d]]*4,
                existing=[],sample_group='黑色',sample_rgb=[50,50,50],reference=image,
                alignment_fn=lambda *_:None,polygon_fn=lambda *_:None,deadline=1000000000,
                cancelled=lambda:False,progress=lambda *_:None)
        self.assertFalse(added)

    def test_manual_shapes_cannot_supply_projected_native_fragment_prompts(self):
        rows=[self.detection(fr) for fr in [0,30,60]]
        for d in rows:d.update(contour_source='user_drawn_polygon',score=.6)
        added,_=refine_native_fragments(frames=[],outputs=[],detections=[rows],existing=[],
            sample_group='黑色',sample_rgb=None,reference_frame=0,alignment_fn=lambda *_:None,
            polygon_fn=lambda *_:None,deadline=1000000000,cancelled=lambda:False,progress=lambda *_:None)
        self.assertFalse(added)


if __name__=='__main__':unittest.main()
