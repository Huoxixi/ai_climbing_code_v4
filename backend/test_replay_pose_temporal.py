"""Behaviour checks against actual image motion, gaps and observation provenance."""
import copy
import unittest

import cv2
import numpy as np

from core.replay_pose_temporal import transport,refine_triplet,TemporalDisplayWindow,display_sample,VERSION
from test_replay_contact_quality import sequence,HOLD
from core.climb_replay import AliyunReplayAnalyzer


class TemporalImageTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(2)
        rng=np.random.default_rng(631)
        self.image=rng.integers(0,256,(240,320),np.uint8)
        self.image=cv2.GaussianBlur(self.image,(3,3),0)
        xy=np.full((133,2),[150.,160.])
        xy[[5,6,11,12]]=[[110,65],[170,65],[115,145],[165,145]]
        xy[[7,8,9,10,13,14,15,16]]=[[90,90],[190,90],[75,115],[205,115],[110,170],[170,170],[100,200],[180,200]]
        self.xy=xy

    def record(self,frame,delta=(0,0)):
        points=(self.xy+delta)/[320,240]
        return {'frame_id':frame//3,'source_frame_id':frame,'track_id':1,
                'kpts_xy':points[:17].tolist(),'kpts_score':[.9]*17,'joint_eligibility':[True]*17,
                'pose_evidence':{'observed':True,'observation_kind':'model_observation'},
                'wholebody':{'schema':'coco-wholebody-133','coordinates':'source_image_normalized',
                    'kpts_xy':points.tolist(),'kpts_score':[.9]*133,'joint_eligibility':[True]*133}}

    def test_real_translation_is_followed_not_frozen(self):
        moved=cv2.warpAffine(self.image,np.float32([[1,0,8],[0,1,3]]),(320,240))
        predicted,valid,fb,_=transport(self.image,moved,self.xy,np.ones(133,bool))
        ids=np.array([9,10,15,16]);supported=ids[valid[ids]]
        self.assertGreaterEqual(len(supported),3)
        np.testing.assert_allclose(predicted[supported],self.xy[supported]+[8,3],atol=.25)
        self.assertLess(max(fb[supported]),.5)

    def test_image_supported_jitter_reduced_without_mutating_raw(self):
        records=[self.record(i) for i in (0,3,6)]
        records[1]['wholebody']['kpts_xy'][15][0]+=6/320
        records[1]['kpts_xy'][15][0]+=6/320
        original=copy.deepcopy(records)
        candidate,evidence=refine_triplet(records,[self.image]*3,source_fps=30,source_size=[320,240])
        self.assertEqual(evidence['status'],'candidate')
        self.assertAlmostEqual(candidate['kpts_xy'][15][0]*320,102.,places=2)
        self.assertEqual(records,original)
        self.assertEqual(candidate['kpts_score'],records[1]['kpts_score'])
        self.assertEqual(candidate['joint_eligibility'],records[1]['joint_eligibility'])
        self.assertEqual(candidate['wholebody']['joint_eligibility'],records[1]['wholebody']['joint_eligibility'])
        self.assertEqual(candidate['kpts_xy'][5],records[1]['kpts_xy'][5])

    def test_fast_consistent_motion_retains_location_and_timing(self):
        records=[self.record(f,delta=(d,0)) for f,d in ((0,-8),(3,0),(6,8))]
        images=[cv2.warpAffine(self.image,np.float32([[1,0,d],[0,1,0]]),(320,240)) for d in (-8,0,8)]
        candidate,_=refine_triplet(records,images,source_fps=30,source_size=[320,240])
        np.testing.assert_allclose(candidate['kpts_xy'],records[1]['kpts_xy'],atol=1e-5)
        self.assertEqual(candidate['source_frame_id'],3)

    def test_gaps_missing_images_and_identity_changes_are_not_bridged(self):
        for variant in ('gap','missing','track','coordinates','decoded_gap'):
            records=[self.record(i) for i in (0,3,6)]
            if variant=='gap':records[2]['source_frame_id']=30
            if variant=='missing':records[0]['pose_evidence']['observed']=False
            if variant=='track':records[0]['track_id']=7
            if variant=='coordinates':records[0]['wholebody']['coordinates']='wall_reference_image_normalized'
            if variant=='decoded_gap':records[2]['frame_id']=3
            candidate,evidence=refine_triplet(records,[self.image]*3,source_fps=30,source_size=[320,240])
            self.assertEqual(candidate,records[1])
            self.assertEqual(evidence['updates'],[])

    def test_weak_joint_is_never_promoted_and_large_error_is_not_silently_repaired(self):
        records=[self.record(i) for i in (0,3,6)]
        records[1]['wholebody']['joint_eligibility'][15]=False
        records[1]['wholebody']['kpts_xy'][16]=[.9,.1]
        candidate,evidence=refine_triplet(records,[self.image]*3,source_fps=30,source_size=[320,240])
        self.assertFalse(candidate['wholebody']['joint_eligibility'][15])
        self.assertEqual(candidate['wholebody']['kpts_xy'][16],[.9,.1])
        self.assertFalse(any(u['joint'] in (15,16) for u in evidence['updates']))

    def test_no_texture_provides_no_image_support(self):
        blank=np.zeros_like(self.image)
        _,valid,_,_=transport(blank,blank,self.xy,np.ones(133,bool))
        self.assertFalse(valid.any())

    def test_detached_toe_reconstructed_only_with_two_real_image_tracks(self):
        records=[self.record(i) for i in (0,3,6)]
        for r in records:r['wholebody']['kpts_xy'][17]=[95/320,205/240]
        records[1]['wholebody']['kpts_xy'][17]=[95/320,100/240]
        candidate,evidence=refine_triplet(records,[self.image]*3,source_fps=30,source_size=[320,240])
        np.testing.assert_allclose(candidate['wholebody']['kpts_xy'][17],[95/320,205/240],atol=1e-5)
        update=next(u for u in evidence['updates'] if u['joint']==17)
        self.assertEqual(update['mode'],'detached_foot_detail_two_image_reconstruction')
        # A foot detail supplied by only one neighbour is not reconstructed.
        records[0]['wholebody']['joint_eligibility'][17]=False
        rejected,_=refine_triplet(records,[self.image]*3,source_fps=30,source_size=[320,240])
        self.assertEqual(rejected['wholebody']['kpts_xy'][17],records[1]['wholebody']['kpts_xy'][17])

    def test_temporal_inference_cannot_create_contact(self):
        for nested in (False,True):
            records=sequence()
            for r in records:
                if nested:r['pose_evidence']={'observation_kind':'image_supported_temporal_inference'}
                else:r['observation_kind']='image_supported_temporal_inference'
            self.assertEqual(AliyunReplayAnalyzer._contacts(records,[HOLD],10,source_fps=30)['contacts'],[])

    def test_streaming_adapter_preserves_raw_and_uses_bounded_image_memory(self):
        window=TemporalDisplayWindow();records=[self.record(i) for i in (0,3,6)]
        records[1]['wholebody']['kpts_xy'][15][0]+=6/320
        records[1]['kpts_xy'][15][0]+=6/320
        original=copy.deepcopy(records)
        for record in records:window.push(cv2.cvtColor(self.image,cv2.COLOR_GRAY2BGR),record,30)
        self.assertIn('temporal_display',records[1])
        self.assertEqual(len(window.window),3)
        for before,after in zip(original,records):
            self.assertEqual({k:v for k,v in after.items() if k!='temporal_display'},before)
        shown=display_sample(records[1]);self.assertAlmostEqual(shown['kpts_xy'][15][0]*320,102,places=2)
        self.assertEqual(records[1]['kpts_xy'],original[1]['kpts_xy'])
        window.push(None,None,30);self.assertEqual(len(window.window),0)

    def test_payload_is_preserved_through_samples_and_shared_scene_diagram(self):
        from core.climb_replay import VideoInfo,build_pose_samples
        from core.replay_analysis_view import visual_evidence,AnalysisView
        r=self.record(3);r.update(wall_alignment='reference',wall_reference_transform=np.eye(3).tolist())
        r['temporal_display']={'version':VERSION,'source_frame_id':3,'kind':'image_supported_temporal_inference',
            'coordinates':'source_image_normalized','updates':[{'joint':15,'xy':[.32,.83]},{'joint':17,'xy':[.30,.84]}]}
        original=copy.deepcopy(r)
        info=VideoInfo(width=320,height=240,fps=30,frame_count=10,duration_seconds=1/3,size_bytes=0)
        samples=build_pose_samples([r],info)
        result={'video':dict(width=320,height=240,fps=30,frame_count=10),'pose_samples':samples,'holds':[],'attempt':{}}
        e=visual_evidence(result)['pose_samples'][0]
        np.testing.assert_allclose(e['source_kpts_xy'][15],[.32,.83])
        np.testing.assert_allclose(e['feet']['kpts_xy'][1],[.30,.84])
        view=AnalysisView(result)
        np.testing.assert_allclose(view.timeline[3]['kpts_xy'][15],view.source_timeline[3]['kpts_xy'][15])
        self.assertEqual(r,original)
        self.assertEqual(samples[0]['kpts_xy'],original['kpts_xy'])


if __name__=='__main__':unittest.main()
