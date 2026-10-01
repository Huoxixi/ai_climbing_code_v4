import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

from core.climb_replay import AliyunReplayAnalyzer, VideoInfo
from core.replay_hold_fusion import align_pose_record, align_to_reference, fuse_hold_detections, match_confirmed_route, select_sampled_route_holds


class ReplayHoldFusionTests(unittest.TestCase):
    def test_sampled_route_keeps_real_small_foothold_and_demotes_specks(self):
        def item(box, color, distance, appearances, score, identity="multi_frame_geometry"):
            return {"bbox": box, "color_group": color, "color_distance": distance,
                    "appearances": appearances, "score": score,
                    "identity_source": identity, "route_candidate": True,
                    "contour_source": "climbing_model_native_mask"}
        large = item([.2, .2, .14, .15], "青色", 10, 5, .98)
        fragment = item([.22, .22, .08, .11], "青色", 9, 1, .6, "user_sampled_hold")
        foothold = item([.7, .7, .043, .04], "蓝色", 14, 5, .95)
        speck = item([.1, .1, .02, .02], "灰色", 14, 5, .95)
        wrong_color = item([.5, .3, .08, .06], "紫色", 32, 5, .99)
        top = item([.5, .1, .14, .04], "绿色", 29, 5, .99)
        selected, rejected, evidence = select_sampled_route_holds(
            [large, fragment, foothold, speck, wrong_color, top], sample_group="青色")
        self.assertEqual(len(selected), 3)
        self.assertIn(foothold, selected)
        self.assertIn(top, selected)
        self.assertEqual(large["identity_source"], "user_sampled_hold")
        self.assertEqual(len(rejected), 3)
        self.assertEqual(evidence["selection_reasons"]["tiny_mask"], 1)
        self.assertEqual(evidence["selection_reasons"]["unrelated_colour"], 1)
        self.assertEqual(evidence["selection_reasons"]["overlapping_mask"], 1)

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
                frames=[(0, frame)], route_color="红色", route_color_sample=sample,
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
