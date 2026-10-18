"""Continuous sample identity must recover uncertainty without overriding colours."""
import copy
import unittest
import cv2
import numpy as np
from core.replay_hold_colors import observe_hold_colour, region_sample_distance
from core.replay_hold_evidence import material_observation, continuous_sample_identity, colour_support
from core.replay_hold_fusion import fuse_hold_detections, select_sampled_route_holds


class SampleIdentityTests(unittest.TestCase):
    def evidence(self, **changes):
        result={'legacy_group':'待确认','lab_median':[120.,163.,167.],
                'neutral_fractions':{'白色':0.,'灰色':0.,'黑色':0.},
                'value_percentiles':[122.,178.,186.],'saturation_median':197.,
                'hue_peak':9,'hue_concentration':1.,'chromatic_fraction':1.}
        result.update(changes)
        return result

    def test_unresolved_red_orange_boundary_uses_real_sample_family(self):
        e=self.evidence()
        self.assertEqual(continuous_sample_identity(e,[214,64,48])['group'],'红色')
        self.assertEqual(e['legacy_group'],'待确认')

    def test_confident_other_colour_is_never_overridden(self):
        for name in ['橙色','灰色','蓝色','棕色']:
            self.assertIsNone(continuous_sample_identity(self.evidence(legacy_group=name),[214,64,48])['group'])

    def test_weak_metal_pastel_and_wrong_hue_do_not_gain_identity(self):
        for change in [{'saturation_median':30.}, {'chromatic_fraction':.2},
                       {'hue_concentration':.6}, {'hue_peak':40}, {'lab_median':[140.,130.,133.]}]:
            self.assertIsNone(continuous_sample_identity(self.evidence(**change),[214,64,48])['group'])

    def frames(self, values=(220,170), count=3, fragmented=False):
        image=np.full((60,60,3),values[1],np.uint8);image[:30]=values[0]
        if fragmented:
            image[:]=0
            for y in range(0,60,10):image[y:y+5]=220
        mask=np.ones((60,60),np.uint8)
        group,interior,evidence=observe_hold_colour(image,mask)
        rgb=[220,220,220];distance=region_sample_distance(image,interior,rgb)
        evidence['interior_pixels']=int(interior.sum())
        return [[{'source_frame':i,'observation_id':f'frame-{i}-mask-0',
                  'polygon':[[.1,.1],[.3,.1],[.3,.3],[.1,.3]],'bbox':[.1,.1,.2,.2],
                  'score':.96,'native_class':0,'contour_source':'climbing_model_native_mask',
                  'contour_complete':True,'color_group':group,'color_distance':distance,
                  'route_candidate':False,'color_evidence':copy.deepcopy(evidence),
                  'material_observation':material_observation(evidence,rgb),
                  'colour_support':colour_support(image,interior,rgb,group,'白色',distance,colour_evidence=evidence)}]
                for i in range(count)]

    def test_shadowed_white_recovers_automatically_and_keeps_real_contour(self):
        frames=self.frames();original=copy.deepcopy(frames)
        fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
        selected,_,_=select_sampled_route_holds(fused,sample_group='白色')
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['polygon'],original[0][0]['polygon'])
        self.assertEqual(selected[0]['sample_identity_resolution']['shape_frames'],[0,1,2])
        self.assertEqual(frames,original)

    def test_two_frames_or_repeated_frame_cannot_resolve_ambiguity(self):
        for frames in [self.frames(count=2),self.frames()]:
            if len(frames)==3:
                for row in frames:row[0]['source_frame']=0
            fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
            self.assertFalse(any(h.get('sample_identity_resolution') for h in fused))

    def test_gray_body_and_disconnected_white_islands_remain_unqualified(self):
        for frames in [self.frames(values=(180,100)),self.frames(fragmented=True)]:
            fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
            self.assertFalse(any(h.get('sample_identity_resolution') for h in fused))

    def test_clipped_or_temporally_inconsistent_shape_does_not_get_rescued(self):
        for mode in ['clipped','different_shape']:
            frames=self.frames()
            if mode=='clipped':
                for row in frames:row[0]['contour_complete']=False
            else:frames[2][0]['polygon']=[[.1,.1],[.2,.1],[.2,.3],[.1,.3]]
            fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
            self.assertFalse(any(h.get('sample_identity_resolution') for h in fused))

    def test_existing_qualified_observation_is_not_replaced(self):
        frames=self.frames(values=(220,220))
        fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
        self.assertFalse(fused[0].get('sample_identity_resolution'))

    def test_bright_gray_body_and_printed_outline_are_not_promoted(self):
        gray=self.evidence(lab_median=[160.,127.,135.],saturation_median=20.,
            neutral_fractions={'白色':.33,'灰色':.4},value_percentiles=[120.,155.,195.])
        self.assertIsNone(continuous_sample_identity(gray,[202,200,192])['group'])
        frames=self.frames()
        for row in frames:
            row[0]['polygon']=[[.1,.1],[.3,.1],[.3,.14],[.14,.14],[.14,.3],[.1,.3]]
        fused=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')
        self.assertFalse(fused[0].get('sample_identity_resolution'))

    def test_resolution_never_displaces_previously_qualified_overlapping_hold(self):
        frames=self.frames();new=fuse_hold_detections(frames,sample_group='白色',evidence_policy='material_boundary')[0]
        old=copy.deepcopy(new);old.pop('sample_identity_resolution');old['candidate_id']='prior'
        old['score']=.7;old['contour_evidence']['support_frames']=[0,1]
        selected,_,_=select_sampled_route_holds([new,old],sample_group='白色')
        self.assertEqual([h['candidate_id'] for h in selected],['prior'])


if __name__=='__main__':unittest.main()
