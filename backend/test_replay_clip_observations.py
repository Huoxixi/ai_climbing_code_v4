"""Meaningful identity and source-observation contract regressions."""
import itertools
import unittest
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path
import cv2
import csv
import io
import zipfile

import numpy as np

from core.replay_person_tracks import ClipPersonTracks, assignment, consolidate_bodies
from core.replay_pose_observation import observation_record
from core.replay_pose_clip import LocalClipReplayAnalyzer
from core.replay_hold_fusion import align_pose_record
from core.replay_action_trajectory import registered_points
from core.replay_analysis_view import visual_evidence
from core.climb_replay import build_pose_samples, VideoInfo
from core.replay_export import build_bundle
from core.replay_center_of_mass import center_of_mass_point


def person(box, colour):
    return {'box':box,'box_xyxy_px':(np.array(box)*100).tolist(),
            'association_box':box,'appearance':colour}


class ClipIdentityTests(unittest.TestCase):
    def test_assignment_is_global_minimum_not_greedy_array_order(self):
        costs=np.array([[1,1.1,3],[1.01,4,5]])
        pairs=assignment(costs)
        actual=sum(costs[i,j] for i,j in pairs)
        expected=min(sum(costs[i,j] for i,j in enumerate(columns))
                     for columns in itertools.permutations(range(3),2))
        self.assertAlmostEqual(actual,expected)
        self.assertEqual(set(pairs),{(0,1),(1,0)})

    def test_target_uses_whole_clip_and_maps_back_to_early_real_detection(self):
        tracks=ClipPersonTracks()
        tracks.add_frame(0,0,[person([0,0,.4,.6],[1,0]),person([.5,.2,.7,.8],[0,1])])
        for i in range(1,12):
            tracks.add_frame(i*3,i*.1,[person([.5,.2,.7,.8],[0,1])])
        selected=tracks.select_target()
        self.assertEqual(selected['target_track_id'],2)
        self.assertEqual(tracks.target_observation(0)['box'],[.5,.2,.7,.8])
        self.assertIsNone(tracks.target_observation(2))

    def test_crossing_association_retains_each_colour_identity(self):
        tracks=ClipPersonTracks()
        for i,(x,y) in enumerate(((.1,.6),(.25,.45),(.4,.3),(.55,.15))):
            rows=[person([x,.2,x+.2,.8],[1,0]),person([y,.2,y+.2,.8],[0,1])]
            if i%2: rows.reverse()
            tracks.add_frame(i*3,i*.1,rows)
        self.assertEqual(len(tracks.tracks),2)
        for track in tracks.tracks:
            self.assertEqual(len({tuple(row['appearance']) for row in track.observations}),1)

    def test_ambiguous_people_remain_ambiguous_instead_of_array_order_winner(self):
        tracks=ClipPersonTracks()
        for i in range(4):
            tracks.add_frame(i,i,[person([.1,.1,.3,.7],[1,0]),person([.6,.1,.8,.7],[0,1])])
        self.assertEqual(tracks.select_target()['status'],'ambiguous')
        self.assertIsNone(tracks.target_observation(0))

    def test_overlapping_boxes_need_same_shoulders_and_hips_to_merge(self):
        torso=np.array([[.3,.3],[.4,.3],[.3,.5],[.4,.5]])
        a=person([.1,.1,.6,.8],[1,0]); a['body']={'torso_xy':torso.tolist()}
        b=person([.2,.2,.5,.7],[1,0]); b['body']={'torso_xy':(torso+.001).tolist()}
        merged=consolidate_bodies([a,b])
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['box'],b['box'])
        self.assertEqual(len(merged[0]['detector_proposals']),2)
        b['body']['torso_xy']=(torso+[.03,0]).tolist()
        self.assertEqual(len(consolidate_bodies([a,b])),2)
        del b['body']
        self.assertEqual(len(consolidate_bodies([a,b])),2)

    def test_missing_frames_do_not_reuse_a_previous_body_or_take_a_bystander(self):
        tracks=ClipPersonTracks()
        for i in range(8):
            rows=[person([.2,.2,.6,.9],[1,0])] if i not in (4,5) else []
            rows += [person([.8,.3,.9,.7],[0,1])]
            tracks.add_frame(i*3,i*.1,rows)
        tracks.select_target()
        self.assertIsNone(tracks.target_observation(12))
        self.assertIsNone(tracks.target_observation(15))
        self.assertEqual(tracks.target_observation(18)['track_id'],1)

    def test_pose_cannot_execute_single_frame_identity_lock(self):
        analyzer=LocalClipReplayAnalyzer()
        with self.assertRaisesRegex(RuntimeError,'Complete clip'):
            analyzer._pose_frame(np.zeros((100,100,3),np.uint8),frame_id=0,source_frame_id=0)

    def test_duplicate_torso_context_does_not_cut_off_observed_legs(self):
        torso=[[.3,.3],[.4,.3],[.3,.5],[.4,.5]]
        a=person([.1,.1,.6,.9],[1,0]);a['body']={'torso_xy':torso,'body_xy':[[.35,.4]]*10+[[.3,.8],[.4,.85]]}
        b=person([.2,.2,.5,.6],[1,0]);b['body']={**a['body']}
        merged=consolidate_bodies([a,b])
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['box'],a['box'])

    def test_registration_loss_does_not_compare_different_coordinate_spaces(self):
        tracks=ClipPersonTracks()
        for i,registered in enumerate((True,True,False,True)):
            row=person([.5,.2,.8,.9],[1,0])
            row['association_space']='reference' if registered else 'source'
            row['association_box']=[.01,.02,.11,.09] if registered else row['box']
            tracks.add_frame(i*3,i*.1,[row])
        self.assertEqual(len(tracks.tracks),1)
        self.assertEqual(len(tracks.tracks[0].observations),4)


def observed_record():
    xy=np.full((133,2),50.)
    xy[[5,6,11,12]]=[[40,30],[60,30],[40,60],[60,60]]
    xy[[7,8,9,10,13,14,15,16]]=[[35,35],[65,35],[30,25],[70,25],[35,70],[65,70],[30,85],[70,85]]
    response=np.linspace(.1,2.9,133)
    record=observation_record(xy,response,frame_id=0,source_frame_id=0,track_id=2,
        size=[100,100],box=[20,20,80,90],model='test',model_evidence={},selection={'target_track_id':2})
    record.update(wall_reference_transform=np.eye(3).tolist(),wall_alignment='reference',
                  wall_alignment_diagnostics={})
    return record


class ObservationContractTests(unittest.TestCase):
    def test_raw_response_is_not_saturated_or_relabelled_as_probability(self):
        record=observed_record()
        self.assertLess(record['kpts_score'][10],.5)
        self.assertTrue(record['joint_eligibility'][10])
        self.assertEqual(record['kpts_score'][10],record['joint_observations']['raw_response'][10])
        self.assertEqual(record['wholebody']['raw_scores'][-1],2.9)
        self.assertEqual(record['wholebody']['kpts_score'][-1],2.9)
        self.assertEqual(record['pose_evidence']['location_uncertainty'],'not_calibrated')
        self.assertEqual(record['joint_observations']['hand_region_status'],'not_independently_observed')

    def test_body17_provider_cannot_claim_wholebody_or_generate_foot_points(self):
        original=observed_record()
        record=observation_record(np.asarray(original['joint_observations']['raw_xy_px'])[:17],
            original['kpts_score'],frame_id=0,source_frame_id=0,track_id=2,size=[100,100],
            box=[20,20,80,90],model='body17-test',model_evidence={},selection={})
        self.assertNotIn('wholebody',record)
        self.assertEqual(record['joint_observations']['schema'],'coco17')
        self.assertEqual(len(record['joint_observations']['raw_response']),17)

    def test_display_and_contact_use_same_boolean_eligibility_with_raw_response_preserved(self):
        record=observed_record()
        sample=build_pose_samples([record],VideoInfo(100,100,30,60,2,10))[0]
        displayed=registered_points(sample,{'width':100,'height':100})
        aligned=align_pose_record(record,np.eye(3),100,100)
        self.assertTrue(displayed[1][10])
        self.assertEqual(aligned['kpts_score'][10],1)
        self.assertEqual(aligned['contact_source_responses'][10],record['kpts_score'][10])
        self.assertLess(sample['kpts_score'][10],.5)
        rendered=visual_evidence({'video':{'width':100,'height':100},'pose_samples':[sample]})
        self.assertEqual(rendered['pose_samples'][0]['kpts_score'][10],1)
        record['joint_eligibility'][10]=False
        sample=build_pose_samples([record],VideoInfo(100,100,30,60,2,10))[0]
        self.assertFalse(registered_points(sample,{'width':100,'height':100})[1][10])
        self.assertEqual(align_pose_record(record,np.eye(3),100,100)['kpts_score'][10],0)

    def test_malformed_eligibility_cannot_bypass_common_rule(self):
        record=observed_record()
        record['joint_eligibility'][10]=1
        sample=build_pose_samples([record],VideoInfo(100,100,30,60,2,10))[0]
        self.assertFalse(sample['observed'])
        self.assertIsNone(registered_points(sample,{'width':100,'height':100}))
        self.assertFalse(any(align_pose_record(record,np.eye(3),100,100)['kpts_score']))

    def test_raw_response_and_eligibility_reach_export_without_confidence_claim(self):
        record=observed_record()
        sample=build_pose_samples([record],VideoInfo(100,100,30,60,2,10))[0]
        self.assertIsNone(sample['confidence'])
        self.assertIsNotNone(center_of_mass_point(sample))
        sample['joint_eligibility'][10]=False
        self.assertIsNone(center_of_mass_point(sample))
        stream=build_bundle({'video':{'width':100,'height':100,'fps':30,'duration_seconds':2},
            'source_duration_seconds':2,'pose_samples':[sample],'skeleton_only':True},mapping={})
        try:
            with zipfile.ZipFile(stream) as bundle:
                rows=list(csv.DictReader(io.StringIO(bundle.read('pose_samples.csv').decode('utf-8-sig'))))
                left=next(r for r in rows if r['joint']=='left_wrist')
                right=next(r for r in rows if r['joint']=='right_wrist')
                self.assertEqual(left['observed'],'True')
                self.assertEqual(float(left['score']),record['kpts_score'][9])
                self.assertEqual(right['observed'],'False')
                self.assertEqual(right['x_normalized'],'')
                self.assertEqual(right['score_basis'],'native_response_uncalibrated')
        finally:stream.close()

    def test_fast_observed_movement_does_not_get_pulled_to_previous_position(self):
        first=observed_record()
        second=observed_record()
        second['kpts_xy'][10]=[.85,.1]
        second['source_frame_id']=3
        sample=build_pose_samples([second],VideoInfo(100,100,30,60,2,10))[0]
        points,valid=registered_points(sample,{'width':100,'height':100})
        self.assertTrue(valid[10])
        np.testing.assert_allclose(points[10],[.85,.1])
        self.assertNotEqual(first['kpts_xy'][10],points[10].tolist())


class ClipPipelineTests(unittest.TestCase):
    def test_shared_pipeline_uses_final_identity_and_never_invokes_legacy_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),4,(100,100))
            if not writer.isOpened():self.skipTest('Local encoder unavailable')
            for _ in range(4):writer.write(np.full((100,100,3),170,np.uint8))
            writer.release()
            xy=np.asarray(observed_record()['joint_observations']['raw_xy_px'])
            pose=Mock(return_value=(xy[None],np.full((1,133),1.8)))
            pose.ort.__version__='test';pose.session.get_providers.return_value=['CPUExecutionProvider'];pose.fallback_reason=None
            detector=Mock(return_value=np.array([[20,20,80,90]]))
            detector.session.get_providers.return_value=['CPUExecutionProvider'];detector.fallback_reason=None
            analyzer=LocalClipReplayAnalyzer(pose_fps=4,device='cpu')
            analyzer._models=pose,detector
            with (patch.object(analyzer,'_select_box',side_effect=AssertionError('legacy person lock')),
                 patch.object(analyzer,'_infer_pose_frame',side_effect=AssertionError('legacy identity branch')),
                 patch('core.replay_pose_clip.align_to_reference',return_value=(np.eye(3),{})),
                 patch('core.climb_replay.render_replay_overlay_video',return_value={'test':True})):
                result=analyzer.analyze(source,route_color='',video_info=VideoInfo(100,100,4,4,1,source.stat().st_size),
                    confirmed_holds={'holds':[],'hold_candidates':[],'hold_evidence':{'reference_frame':0},
                                     'models':{'holds':'confirmed'},'skeleton_only':True},
                    progress=lambda *_:None,cancelled=lambda:False,telemetry=lambda *_:None)
            self.assertEqual(len(result['pose_samples']),4)
            self.assertTrue(all(s['kpts_score'][10]==1.8 for s in result['pose_samples']))
            self.assertTrue(all(s['pose_evidence']['track_id']==1 for s in result['pose_samples']))
            self.assertEqual(result['analysis']['runtime']['target_selection']['target_track_id'],1)
            self.assertEqual(result['analysis']['usage']['actual_requests'],0)


if __name__=='__main__':
    unittest.main()
