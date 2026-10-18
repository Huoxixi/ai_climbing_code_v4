import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

from core.climb_replay import AliyunReplayAnalyzer, VideoInfo
from core.replay_hold_fusion import align_pose_record, align_to_reference, fuse_hold_detections, match_confirmed_route, select_sampled_route_holds, polygon_bbox


class ReplayHoldFusionTests(unittest.TestCase):
    def test_full_video_colour_gate_excludes_close_high_score_neighbour(self):
        import time
        frame=np.full((200,200,3),128,np.uint8)
        yellow,green=np.zeros((200,200),np.uint8),np.zeros((200,200),np.uint8)
        yellow[20:60,20:60]=255;green[100:140,100:140]=255
        outputs=[([yellow,green],[.9,.999]),([yellow,green],[.9,.999])]
        with patch('core.climb_replay._climbing_model_masks_batch',return_value=(outputs,'fixture')), \
             patch('core.climb_replay.align_to_reference',return_value=(np.eye(3),{'inliers':100,'median_error_px':0})), \
             patch('core.climb_replay.observe_hold_colour',side_effect=[(c,m.astype(bool),{}) for c,m in [('黄色',yellow),('绿色',green),('黄色',yellow),('绿色',green)]]), \
             patch('core.climb_replay.region_sample_distance',return_value=5.):
            holds,rejected,_,_,_=AliyunReplayAnalyzer._video_holds(
                frames=[(0,frame),(3,frame)],route_color='黄色',
                route_color_sample={'source':'video','rgb':[19,161,67]},saved_route_reference=None,
                deadline=time.monotonic()+30,progress=lambda *_:None,cancelled=lambda:False)
        self.assertEqual(len(holds),1)
        self.assertEqual(holds[0]['color_group'],'黄色')
        wrong=next(h for h in rejected if h['color_group']=='绿色')
        self.assertEqual(wrong['contour_evidence']['support_frames'],[])
        self.assertTrue(all(not o['evidence_checked'] for o in wrong['contour_evidence']['observations']))

    def test_sample_colour_boundary_is_inclusive_through_full_video_selection(self):
        import time
        frame = np.full((200, 200, 3), 128, np.uint8)
        near, far = np.zeros((200, 200), np.uint8), np.zeros((200, 200), np.uint8)
        near[20:60, 20:60] = 255
        far[100:140, 100:140] = 255
        outputs = [([near, far], [.95, .95]), ([near, far], [.95, .95])]
        with patch('core.climb_replay._climbing_model_masks_batch', return_value=(outputs, 'fixture')), \
             patch('core.climb_replay.align_to_reference', return_value=(np.eye(3), {'inliers': 100, 'median_error_px': 0})), \
             patch('core.climb_replay.observe_hold_colour', return_value=('黄色',near.astype(bool),{})), \
             patch('core.climb_replay.region_sample_distance', side_effect=[60., 60.01, 60., 60.01]):
            holds, rejected, _, _, _ = AliyunReplayAnalyzer._video_holds(
                frames=[(0, frame), (3, frame)], route_color='黄色',
                route_color_sample={'source': 'video', 'rgb': [230, 195, 10]},
                saved_route_reference=None, deadline=time.monotonic()+30,
                progress=lambda *_: None, cancelled=lambda: False)
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]['color_distance'], 60.)
        self.assertTrue(any(h.get('color_distance') == 60.01 and not h['route_candidate'] for h in rejected))

    def test_sampled_route_keeps_real_small_foothold_and_demotes_specks(self):
        def item(box, color, distance, appearances, score, identity="multi_frame_geometry"):
            return {"bbox": box, "color_group": color, "color_distance": distance,
                    "appearances": appearances, "score": score,
                    "identity_source": identity, "route_candidate": True,
                    "contour_source": "climbing_model_native_mask",
                    "polygon": [[box[0],box[1]],[box[0]+box[2],box[1]],
                                [box[0]+box[2],box[1]+box[3]],[box[0],box[1]+box[3]]],
                    "contour_evidence": {"version": "native-colour-contour-support-v1",
                                         "support_frames": list(range(appearances))}}
        large = item([.2, .2, .14, .15], "青色", 10, 5, .98)
        fragment = item([.22, .22, .08, .11], "青色", 9, 1, .6, "user_sampled_hold")
        foothold = item([.7, .7, .043, .04], "青色", 14, 5, .95)
        speck = item([.1, .1, .02, .02], "青色", 14, 5, .95)
        speck['contour_evidence']['support_frames'] = []  # cropped/unsupported, not rejected by size
        wrong_color = item([.5, .3, .08, .06], "紫色", 32, 5, .99)
        top = item([.5, .1, .14, .04], "绿色", 29, 5, .99)
        selected, rejected, evidence = select_sampled_route_holds(
            [large, fragment, foothold, speck, wrong_color, top], sample_group="青色")
        self.assertEqual(len(selected), 2)
        self.assertIn(foothold, selected)
        self.assertNotIn(top, selected)
        self.assertEqual(large["identity_source"], "user_sampled_hold")
        self.assertEqual(len(rejected), 4)
        self.assertEqual(evidence["selection_reasons"]["insufficient_colour_contour_support"], 1)
        self.assertEqual(evidence["selection_reasons"]["outside_sample_colour"], 2)
        self.assertEqual(evidence["selection_reasons"]["overlapping_mask"], 1)

    def test_colour_failures_never_reach_contour_or_evidence_checks(self):
        values=[{'route_candidate':True,'color_group':'绿色','color_distance':5.,
                 'score':1.,'appearances':100,'identity_source':'user_sampled_hold'},
                {'route_candidate':True,'color_group':'青色','color_distance':60.01,
                 'score':1.,'appearances':100}]
        with patch('core.replay_hold_fusion.valid_native_contour',side_effect=AssertionError('colour failure reached evidence')):
            selected,rejected,evidence=select_sampled_route_holds(values,sample_group='青色')
        self.assertEqual(selected,[])
        self.assertEqual(len(rejected),2)
        self.assertEqual(evidence['selection_reasons'],{'outside_sample_colour':2})

    def test_other_colours_do_not_supply_multiframe_support(self):
        box=[.2,.3,.01,.015];polygon=[[.2,.3],[.21,.3],[.21,.315],[.2,.315]]
        def detection(frame,colour,eligible):
            return {'bbox':box,'polygon':polygon,'score':.99,'source_frame':frame,
                    'contour_source':'climbing_model_native_mask','contour_complete':True,
                    'route_candidate':eligible,'color_distance':10.,'color_group':colour}
        fused=fuse_hold_detections([[detection(0,'青色',True)],
                                   [detection(3,'绿色',False)]],sample_group='青色')
        self.assertEqual(fused[0]['contour_evidence']['support_frames'],[0])
        self.assertEqual(select_sampled_route_holds(fused,sample_group='青色')[0],[])

    def test_tiny_native_contours_need_distinct_complete_colour_agreement(self):
        box=[.2,.3,.01,.015]
        polygon=[[.2,.3],[.21,.3],[.21,.315],[.2,.315]]
        def detection(frame, **changes):
            return {'bbox':box,'polygon':polygon,'score':.99,'source_frame':frame,
                    'contour_source':'climbing_model_native_mask','contour_complete':True,
                    'route_candidate':True,'color_distance':25.,'color_group':'黄色',**changes}
        frames=[[detection(0)],[detection(3)],[detection(6)]]
        good=fuse_hold_detections(frames)
        self.assertEqual(len(select_sampled_route_holds(good,sample_group='黄色')[0]),1)
        for observations in (
            [[detection(0)],[detection(0)],[detection(0)]],
            [[detection(0,contour_complete=False)],[detection(3,contour_complete=False)]],
            [[detection(0)],[detection(3,route_candidate=False,color_distance=70.)]],
        ):
            selected,rejected,_=select_sampled_route_holds(fuse_hold_detections(observations),sample_group='黄色')
            self.assertEqual(selected,[])
            self.assertTrue(rejected)

    def test_same_boxes_do_not_prove_consistent_contours(self):
        box=[.2,.3,.01,.015]
        a=[[.2,.3],[.21,.3],[.2,.315]]
        b=[[.21,.315],[.2,.315],[.21,.3]]
        def item(frame,polygon,score):
            return {'bbox':box,'polygon':polygon,'score':score,'source_frame':frame,
                    'contour_source':'climbing_model_native_mask','contour_complete':True,
                    'route_candidate':True,'color_distance':25.,'color_group':'黄色'}
        fused=fuse_hold_detections([[item(0,a,.99)],[item(3,b,.98)]])
        self.assertEqual(fused[0]['appearances'],2)
        selected,rejected,_=select_sampled_route_holds(fused,sample_group='黄色')
        self.assertEqual(selected,[])
        self.assertEqual(len(rejected),1)

    def test_clicked_time_is_resolved_after_video_trim(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trimmed.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 6, (80, 80))
            for index in range(12):
                writer.write(np.full((80, 80, 3), index * 15, np.uint8))
            writer.release()
            info = VideoInfo(width=80, height=80, fps=6, frame_count=12,
                             duration_seconds=2, size_bytes=path.stat().st_size)
            sample = {"source": "video", "time_seconds": 5.5,
                      "trim_start_seconds": 5, "point_xy": [.5, .5]}
            frames = AliyunReplayAnalyzer._hold_frames(path, info, sample)
            self.assertIn(3, [index for index, _ in frames])

    def test_alignment_recovers_wall_translation(self):
        rng = np.random.default_rng(17)
        source = rng.integers(30, 225, (400, 500, 3), dtype=np.uint8)
        source = cv2.GaussianBlur(source, (3, 3), 0)
        target = cv2.warpAffine(source, np.float32([[1, 0, 12], [0, 1, -8]]), (500, 400))
        matrix, evidence = align_to_reference(source, target)
        self.assertIsNotNone(matrix, evidence)
        self.assertAlmostEqual(matrix[0, 2], 12, delta=2)
        self.assertAlmostEqual(matrix[1, 2], -8, delta=2)

    def test_experimental_frames_preserve_sample_and_cancel_before_decode(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/"frames.mp4"
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),10,(80,80))
            for index in range(100):
                writer.write(np.full((80,80,3),index,np.uint8))
            writer.release()
            info=VideoInfo(80,80,10,100,10,path.stat().st_size)
            sample={"source":"video","time_seconds":5.1,"point_xy":[.5,.5]}
            for profile in ("6","8"):
                with patch.dict(os.environ,{"CLIMB_REPLAY_HOLD_FRAME_PROFILE":profile}):
                    indices=[index for index,_ in AliyunReplayAnalyzer._hold_frames(path,info,sample)]
                    self.assertIn(51,indices)
                    self.assertLessEqual(len(indices),int(profile)+1)
                    self.assertLess(min(indices),10)
                    self.assertGreater(max(indices),90)
                    with self.assertRaises(InterruptedError):
                        AliyunReplayAnalyzer._hold_frames(path,info,sample,cancelled=lambda:True)

    def test_fused_box_always_encloses_the_chosen_native_contour(self):
        a={"bbox":[.1,.2,.1,.1],"polygon":[[.1,.2],[.2,.2],[.2,.3],[.1,.3]],"score":.8}
        b={"bbox":[.12,.21,.12,.11],"polygon":[[.12,.21],[.24,.21],[.24,.32],[.12,.32]],"score":.9}
        fused=fuse_hold_detections([[a],[b]])
        self.assertEqual(len(fused),1)
        self.assertEqual(fused[0]["bbox"],polygon_bbox(fused[0]["polygon"]))

    def test_video_pipeline_merges_same_hold_across_aligned_frames(self):
        rng = np.random.default_rng(31)
        first_frame = rng.integers(20, 180, (360, 480, 3), dtype=np.uint8)
        first_frame = cv2.GaussianBlur(first_frame, (3, 3), 0)
        first_frame[100:170, 130:200] = [35, 35, 220]
        shift = np.float32([[1, 0, 9], [0, 1, 6]])
        second_frame = cv2.warpAffine(first_frame, shift, (480, 360))
        first_mask = np.zeros((360, 480), np.uint8)
        first_mask[100:170, 130:200] = 255
        second_mask = cv2.warpAffine(first_mask, shift, (480, 360))
        sample = {"source": "palette", "hex": "#dc2323", "rgb": [220, 35, 35]}
        with patch("core.climb_replay._climbing_model_masks_batch", return_value=(
                [([np.packbits(first_mask > 0, axis=1)], [.9]),
                 ([np.packbits(second_mask > 0, axis=1)], [.85])], "test-model")):
            holds, candidates, evidence, _, _ = AliyunReplayAnalyzer._video_holds(
                frames=[(0, first_frame), (30, second_frame)], route_color="红色",
                route_color_sample=sample, saved_route_reference=None, deadline=10**12,
                progress=lambda *_: None, cancelled=lambda: False)
        self.assertEqual(evidence["frames_aligned"], 2)
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["appearances"], 2)
        self.assertEqual(candidates, [])

    def test_multiframe_fusion_does_not_merge_two_same_frame_holds(self):
        first = {"bbox": [.10, .2, .1, .1], "polygon": [[.1, .2], [.2, .2], [.2, .3]], "score": .8}
        close = {"bbox": [.11, .2, .1, .1], "polygon": [[.11, .2], [.21, .2], [.21, .3]], "score": .9}
        distant = {"bbox": [.7, .7, .1, .1], "polygon": [[.7, .7], [.8, .7], [.8, .8]], "score": .8}
        merged = fuse_hold_detections([[first, close, distant], [close]])
        self.assertEqual(len(merged), 3)
        self.assertEqual(max(hold["appearances"] for hold in merged), 2)

    def test_confirmed_route_identity_beats_color_candidate(self):
        blue = {"bbox": [.1, .1, .1, .1], "color_group": "蓝色", "route_candidate": False}
        red = {"bbox": [.6, .6, .1, .1], "color_group": "红色", "route_candidate": True}
        chosen, remaining = match_confirmed_route(
            [blue, red], [{"object_id": "saved-blue", "bbox": [.105, .1, .1, .1]}])
        self.assertEqual(chosen[0]["saved_object_id"], "saved-blue")
        self.assertEqual(chosen[0]["color_group"], "蓝色")
        self.assertEqual(remaining, [red])

    def test_unobserved_saved_contour_is_review_candidate_not_active_hold(self):
        member = {"object_id": "saved", "bbox": [.2, .3, .1, .1],
                  "polygon": [[.2, .3], [.3, .3], [.3, .4], [.2, .4]]}
        selected, remaining = match_confirmed_route([], [member], include_projected_unmatched=True)
        self.assertEqual(selected, [])
        self.assertEqual(remaining[0]["saved_object_id"], "saved")
        self.assertEqual(remaining[0]["appearances"], 0)
        self.assertEqual(remaining[0]["identity_source"], "unverified_saved_photo_projection")

    def test_failed_pose_alignment_suppresses_contacts(self):
        record = {"kpts_xy": [[.5, .5]], "kpts_score": [.9]}
        self.assertEqual(align_pose_record(record, None, 100, 100)["kpts_score"], [0.0])
        self.assertEqual(record["kpts_score"], [.9])

    def test_clicked_hold_uses_segmented_interior_not_nearby_pixel(self):
        frame = np.zeros((120, 220, 3), np.uint8)
        frame[20:90, 20:90] = [190, 170, 40]
        frame[20:90, 130:200] = [40, 40, 220]
        first = np.zeros(frame.shape[:2], np.uint8)
        second = first.copy()
        first[20:90, 20:90] = 255
        second[20:90, 130:200] = 255
        sample = {"source": "video", "hex": "#ffffff", "rgb": [255, 255, 255],
                  "time_seconds": 0, "point_xy": [.25, .45], "prepared_frame_index": 0}
        with patch("core.climb_replay._climbing_model_masks_batch",
                   return_value=([([np.packbits(first > 0, axis=1),
                                    np.packbits(second > 0, axis=1)], [.9, .9])], "test-model")):
            holds, candidates, evidence, actual, _ = AliyunReplayAnalyzer._video_holds(
                frames=[(0, frame)], route_color="青色", route_color_sample=sample,
                saved_route_reference=None, deadline=10**12,
                progress=lambda *_: None, cancelled=lambda: False)
        self.assertEqual(actual["rgb"], [40, 170, 190])
        self.assertEqual(actual["evidence"], "segmented_hold_interior")
        self.assertEqual(len(holds), 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(holds[0]["identity_source"], "user_sampled_hold")
        self.assertEqual(evidence["frames_decoded"], 1)

    def test_saved_confirmed_hold_is_selected_even_when_color_differs(self):
        rng = np.random.default_rng(27)
        frame = rng.integers(20, 180, (400, 500, 3), dtype=np.uint8)
        frame = cv2.GaussianBlur(frame, (3, 3), 0)
        frame[60:130, 60:130] = [220, 80, 30]
        frame[260:330, 350:420] = [30, 30, 220]
        blue_mask = np.zeros(frame.shape[:2], np.uint8)
        red_mask = blue_mask.copy()
        blue_mask[60:130, 60:130] = 255
        red_mask[260:330, 350:420] = 255
        with TemporaryDirectory() as directory:
            photo = Path(directory) / "wall.png"
            encoded, data = cv2.imencode(".png", frame)
            self.assertTrue(encoded)
            data.tofile(str(photo))
            saved = {"asset_path": str(photo), "members": [{"object_id": "confirmed-blue",
                     "contour": [[60, 60], [129, 60], [129, 129], [60, 129]]}]}
            with patch("core.climb_replay._climbing_model_masks_batch",
                       return_value=([([blue_mask, red_mask], [.9, .9])], "test-model")):
                holds, candidates, evidence, _, _ = AliyunReplayAnalyzer._video_holds(
                    frames=[(0, frame)], route_color="红色", route_color_sample=None,
                    saved_route_reference=saved, deadline=10**12,
                    progress=lambda *_: None, cancelled=lambda: False)
        self.assertEqual(len(holds), 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(holds[0]["saved_object_id"], "confirmed-blue")
        self.assertEqual(holds[0]["identity_source"], "confirmed_saved_route")
        self.assertEqual(evidence["confirmed_members_matched"], 1)


if __name__ == "__main__":
    unittest.main()
