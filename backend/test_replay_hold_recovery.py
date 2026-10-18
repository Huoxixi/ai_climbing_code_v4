import copy
import unittest
import cv2
import numpy as np
from core.replay_hold_colors import observe_hold_colour
from core.replay_hold_evidence import colour_support,measure_material_quality
from core.replay_hold_fusion import native_contour_support
from core.replay_hold_recovery import select_alternatives,retry_frames,interior_point

class RecoveryContractTests(unittest.TestCase):
    def test_warm_body_boundary_does_not_admit_orange_or_weak_metal(self):
        mask=np.ones((40,40),np.uint8)
        body=cv2.cvtColor(np.full((40,40,3),(21,180,210),np.uint8),cv2.COLOR_HSV2BGR)
        body[:20]=cv2.cvtColor(np.full((20,40,3),(19,180,210),np.uint8),cv2.COLOR_HSV2BGR)
        name,inside,e=observe_hold_colour(body,mask)
        self.assertEqual(name,'黄色')
        self.assertEqual(e['body_resolution'],'continuous_warm_body')
        orange=cv2.cvtColor(np.full((40,40,3),(17,180,210),np.uint8),cv2.COLOR_HSV2BGR)
        self.assertEqual(observe_hold_colour(orange,mask)[0],'橙色')
        metal=cv2.cvtColor(np.full((40,40,3),(23,58,195),np.uint8),cv2.COLOR_HSV2BGR)
        group,inside,e=observe_hold_colour(metal,mask)
        s=colour_support(metal,inside,[222,176,10],group,'黄色',57.,colour_evidence=e)
        self.assertFalse(s['qualified']);self.assertIn('weak_sample_chroma',s['identity_reasons'])

    def test_yellow_sample_preserves_colour_identity_against_lime_green(self):
        image=cv2.cvtColor(np.full((40,40,3),(35,190,201),np.uint8),cv2.COLOR_HSV2BGR)
        group,inside,e=observe_hold_colour(image,np.ones((40,40),np.uint8))
        s=colour_support(image,inside,[222,176,10],group,'黄色',50.,colour_evidence=e)
        self.assertTrue(s['distance_metric_qualified'])
        self.assertFalse(s['metric_qualified']);self.assertFalse(s['qualified'])
        self.assertIn('sample_hue_incompatible',s['identity_reasons'])

    def test_dark_neutral_mixture_is_not_a_bright_grey_body(self):
        for grey,expected in [(95,'黑色'),(170,'待确认')]:
            image=np.full((50,50,3),grey,np.uint8);image[:20]=45
            group,_,e=observe_hold_colour(image,np.ones((50,50),np.uint8))
            self.assertEqual(group,expected)

    def partial(self,fr):
        return dict(source_frame=fr,observation_id=str(fr),polygon=[[0,.2],[.1,.2],[.1,.3],[0,.3]],bbox=[0,.2,.1,.1],
            contour_source='climbing_model_native_mask',contour_complete=False,native_class=0,color_group='青色',route_candidate=True,color_distance=10,
            material_observation=dict(lab_median=[100,120,128]),boundary_quality=dict(edge_fraction=.9))

    def test_clipped_visible_evidence_does_not_claim_a_complete_hidden_outline(self):
        rows=[self.partial(fr) for fr in (0,1,2)];measure_material_quality(rows)
        evidence=native_contour_support(rows,rows[0],sample_group='青色')
        self.assertEqual(evidence['visible_partial_frames'],[0,1,2])
        self.assertFalse(evidence['partial_contour_complete'])
        self.assertTrue(all(not d['contour_complete'] for d in rows))
        copies=[self.partial(0) for _ in range(3)];measure_material_quality(copies)
        self.assertFalse(native_contour_support(copies,copies[0],sample_group='青色')['support_frames'])

    def alternative(self,frames):
        return dict(candidate_id='auto',polygon=[[.2,.2],[.3,.2],[.3,.3],[.2,.3]],bbox=[.2,.2,.1,.1],
            contour_source='model_guided_mobilesam_mask',contour_complete=True,evidence_origin='automatic_supplement',
            color_group='黑色',route_candidate=True,color_distance=10,native_class=1,
            contour_evidence=dict(support_frames=frames,observations=[dict(source_frame=fr,complete=True,colour_candidate=True,iou=.95) for fr in frames]))

    def test_alternatives_require_distinct_real_source_frames(self):
        for frames in ([0,0],[True,False]):
            selected,rejected=select_alternatives([self.alternative(frames)],[],sample_group='黑色')
            self.assertFalse(selected);self.assertEqual(len(rejected),1)
        selected,_=select_alternatives([self.alternative([0,30])],[],sample_group='黑色')
        self.assertEqual(len(selected),1);self.assertEqual(selected[0]['native_class'],1)

    def test_existing_contour_has_priority_over_any_new_model_score(self):
        new=self.alternative([0,30]);old=copy.deepcopy(new);old['score']=.5;new['score']=.999
        selected,rejected=select_alternatives([new],[old],sample_group='黑色')
        self.assertFalse(selected);self.assertEqual(rejected,[new]);self.assertEqual(old['score'],.5)

    def test_manual_geometry_is_not_automatic_model_evidence(self):
        h=self.alternative([0,30]);h['contour_source']='user_drawn_polygon'
        self.assertFalse(select_alternatives([h],[],sample_group='黑色')[0])

    def test_expanded_fragment_requires_three_consistent_distinct_times(self):
        for frames,expected in [([0,30],0),([0,30,60],1)]:
            h=self.alternative(frames);h.update(evidence_channel='fragment',large_expansion=True)
            self.assertEqual(len(select_alternatives([h],[],sample_group='黑色')[0]),expected)

    def test_fragment_recovery_cannot_replace_an_accepted_separate_instance(self):
        paired=self.alternative([0,30]);paired.update(candidate_id='paired',evidence_channel='paired')
        fragment=self.alternative([0,30,60]);fragment.update(candidate_id='fragment',evidence_channel='fragment',large_expansion=True)
        selected,rejected=select_alternatives([fragment,paired],[],sample_group='黑色')
        self.assertEqual(selected,[paired]);self.assertEqual(rejected,[fragment])

    def test_retry_budget_uses_source_observations_without_candidate_id_rules(self):
        anchors=[dict(source_frame=117,candidate_id='anything'),dict(source_frame=117),dict(source_frame=938)]
        self.assertEqual(retry_frames(anchors,{0:None,117:None,938:None},0),[117,0])
        self.assertEqual(retry_frames([],{},0),[])

    def test_native_prompt_is_inside_actual_concave_contour(self):
        hold=dict(polygon=[[.1,.1],[.5,.1],[.5,.2],[.2,.2],[.2,.5],[.1,.5]])
        point=interior_point(hold,100,100)
        self.assertGreater(cv2.pointPolygonTest((np.asarray(hold['polygon'],np.float32)*100).astype(np.float32),tuple(map(float,point)),True),0)

if __name__=='__main__':unittest.main()
