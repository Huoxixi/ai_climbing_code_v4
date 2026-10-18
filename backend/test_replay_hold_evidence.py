"""Product contracts for the user-requested combined local progress."""
import copy
import unittest
import cv2
import numpy as np

from core.replay_hold_colors import observe_hold_colour
from core.replay_hold_evidence import (material_observation,sample_compatible_group,colour_support,
    measure_material_quality,warm_material_supported,choose_native_representative)
from core.replay_hold_fusion import sampled_colour_matches,contour_overlap,native_contour_support,select_sampled_route_holds


class ReplayProgressTests(unittest.TestCase):
    def test_green_boundary_has_compatibility_but_clear_green_does_not(self):
        mask=np.zeros((50,50),np.uint8);mask[10:40,10:40]=1
        for hue,expected in [(78,'青色'),(60,'绿色')]:
            image=cv2.cvtColor(np.full((50,50,3),(hue,180,200),np.uint8),cv2.COLOR_HSV2BGR)
            name,_,evidence=observe_hold_colour(image,mask)
            material=material_observation(evidence,[130,216,201])
            self.assertEqual(sample_compatible_group(name,material,'青色'),expected)
            self.assertFalse(material['compatibility_is_probability'])

    def test_neutral_colour_body_remains_neutral(self):
        mask=np.ones((40,40),np.uint8)
        for v,name in [(40,'黑色'),(120,'灰色'),(220,'白色')]:
            group,_,evidence=observe_hold_colour(np.full((40,40,3),v,np.uint8),mask)
            material=material_observation(evidence,[188,152,10])
            self.assertEqual(material['supports'],[name])
            self.assertEqual(sample_compatible_group(group,material,'黄色'),name)

    def test_connected_support_preserves_original_distance_and_whole_denominator(self):
        rgb=[130,216,201]
        image=np.zeros((40,40,3),np.uint8);image[:12]=rgb[::-1]
        region=np.ones((40,40),bool)
        support=colour_support(image,region,rgb,'青色','青色',100.)
        self.assertTrue(support['qualified'])
        self.assertEqual(support['median_distance'],100.)
        self.assertAlmostEqual(support['within60_fraction'],.3)
        self.assertEqual(support['pixels'],1600)

    def test_disconnected_matching_islands_cannot_replace_connected_body(self):
        rgb=[130,216,201]
        image=np.zeros((60,60,3),np.uint8)
        for y in (0,20,40):image[y:y+6]=rgb[::-1]
        s=colour_support(image,np.ones((60,60),bool),rgb,'青色','青色',100.)
        self.assertAlmostEqual(s['within60_fraction'],.3)
        self.assertFalse(s['qualified'])

    def test_another_colour_never_gets_region_admission(self):
        rgb=[130,216,201]
        image=np.full((30,30,3),rgb[::-1],np.uint8)
        s=colour_support(image,np.ones((30,30),bool),rgb,'绿色','青色',1.)
        self.assertFalse(s['qualified'])

    def warm(self,fr,group,supports):
        return {'source_frame':fr,'color_group':group,'material_observation':{'supports':supports,'hue_peak':23}}

    def test_dark_warm_colour_needs_distinct_confident_material_anchors(self):
        brown=[self.warm(fr,'棕色',['黄色','棕色']) for fr in (0,88,395)]
        self.assertFalse(warm_material_supported(brown))
        same=[self.warm(88,'黄色',['黄色']),self.warm(88,'黄色',['黄色'])]
        self.assertFalse(warm_material_supported(same))
        mixed=[self.warm(88,'黄色',['黄色']),self.warm(395,'黄色',['黄色']),self.warm(703,'待确认',[])]
        self.assertFalse(warm_material_supported(mixed))
        good=[self.warm(88,'棕色',['黄色','棕色']),self.warm(395,'黄色',['黄色']),self.warm(703,'黄色',['黄色'])]
        self.assertTrue(warm_material_supported(good))

    def test_quality_does_not_depend_on_target_matching(self):
        rows=[{'polygon':[[0,0],[1,0],[1,1],[0,1]],'contour_complete':True,
            'material_observation':{'lab_median':[100,128+i,128]},'color_group':'青色','color_distance':1} for i in (0,1,2,30)]
        for fr,d in enumerate(rows):d['source_frame']=fr
        other=copy.deepcopy(rows)
        for d in other:d.update(color_group='黄色',color_distance=150)
        measure_material_quality(rows);measure_material_quality(other)
        self.assertEqual([d['material_quality'] for d in rows],[d['material_quality'] for d in other])
        self.assertFalse(rows[-1]['material_quality']['eligible'])

    def test_representative_is_native_agreement_not_largest_or_highest_score(self):
        def native(fr,size,score,edge):
            return {'source_frame':fr,'polygon':[[.1,.1],[.1+size,.1],[.1+size,.1+size],[.1,.1+size]],
                'bbox':[.1,.1,size,size],'route_candidate':True,'color_group':'黄色','color_distance':10.,
                'contour_complete':True,'contour_source':'climbing_model_native_mask','score':score,
                'boundary_quality':{'edge_fraction':edge}}
        large=native(0,.7,.999,0.)
        good=native(88,.1,.90,1.);agree=native(395,.1,.89,1.)
        chosen=choose_native_representative([large,good,agree],'黄色',sampled_colour_matches,contour_overlap)
        self.assertEqual(chosen['source_frame'],88)
        self.assertEqual(chosen['polygon'],good['polygon'])

    def test_video_volume_remains_reviewable_without_asserting_bad_shape(self):
        hold={'candidate_id':'volume','native_class':1,'route_candidate':True,'color_group':'黑色','color_distance':1.}
        selected,rejected,diag=select_sampled_route_holds([hold],sample_group='黑色')
        self.assertFalse(selected);self.assertEqual(rejected,[hold])
        self.assertEqual(diag['selection_reasons'],{'native_volume_needs_review':1})


if __name__=='__main__':unittest.main()
