import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from core.climb_replay import (ClimbReplayStore, ReplayHoldPoint, VideoInfo,
                               _interpolated_hold_polygons, _multi_frame_clicked_polygon,
                               _registered_hold_polygons,
                               boxed_hold_polygon, clicked_hold_polygon)


class ReplayHoldReviewTests(unittest.TestCase):
    def test_rough_region_finds_hold_even_when_center_is_wall(self):
        frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
        cv2.rectangle(frame, (42, 60), (59, 76), (170, 125, 20), -1)
        cv2.circle(frame, (75, 58), 2, (0, 0, 0), -1)
        region = [35 / 120, .50, 84 / 120, .84]
        polygon = boxed_hold_polygon(frame, region)
        self.assertLess(min(point[0] for point in polygon), 48)
        self.assertLess(max(point[0] for point in polygon), 65)
        self.assertGreater(max(point[1] for point in polygon), 70)
        with self.assertRaises(ValueError):
            ReplayHoldPoint(point_xy=[.5, .5], time_seconds=0,
                            region_xyxy=[.4, .4, .405, .5])

    def test_rough_region_expands_across_shaded_hold(self):
        frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
        cv2.rectangle(frame, (42, 60), (59, 66), (170, 125, 20), -1)
        cv2.rectangle(frame, (42, 67), (59, 76), (105, 70, 12), -1)
        polygon = boxed_hold_polygon(frame, [35 / 120, .52, 68 / 120, .84])
        self.assertLessEqual(min(point[1] for point in polygon), 62)
        self.assertGreaterEqual(max(point[1] for point in polygon), 74)

    def test_nearby_clear_frames_remove_person_coloured_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "occluded.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (120, 100))
            if not writer.isOpened():
                self.skipTest("MP4 encoder unavailable")
            frames = []
            for index in range(8):
                frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
                cv2.rectangle(frame, (42, 60), (59, 76), (170, 125, 20), -1)
                if index == 4:
                    cv2.rectangle(frame, (58, 68), (65, 72), (170, 125, 20), -1)
                writer.write(frame)
                frames.append(frame)
            writer.release()
            initial = clicked_hold_polygon(frames[4], [50 / 120, .68])
            normalized = [[x / 120, y / 100] for x, y in initial]
            info = VideoInfo(width=120, height=100, fps=4, frame_count=8,
                             duration_seconds=2, size_bytes=source.stat().st_size)
            with patch("core.climb_replay.align_to_reference", return_value=(np.eye(3), {})):
                refined, support = _multi_frame_clicked_polygon(
                    source, info, 4, 0, frames[0], normalized)
            self.assertGreaterEqual(support, 3)
            self.assertLess(max(point[0] for point in refined), .53)

    def test_wall_contours_follow_camera_and_disappear_when_alignment_is_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "moving.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (120, 80))
            if not writer.isOpened():
                self.skipTest("MP4 encoder unavailable")
            for shift in (0, 8, 16, 24):
                frame = np.zeros((80, 120, 3), dtype=np.uint8)
                cv2.rectangle(frame, (20 + shift, 20), (39 + shift, 39), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()
            reference = cv2.VideoCapture(str(source))
            ok, first = reference.read()
            reference.release()
            self.assertTrue(ok)
            hold = {"id": 1, "bbox": [20 / 120, .25, 20 / 120, .25],
                    "polygon": [[20 / 120, .25], [40 / 120, .25],
                                [40 / 120, .5], [20 / 120, .5]]}

            def translated(frame, _):
                left = int(np.where(frame[:, :, 0] > 180)[1].min())
                return np.array([[1, 0, -(left - 20)], [0, 1, 0], [0, 0, 1]], float), {}

            capture = cv2.VideoCapture(str(source))
            with patch("core.climb_replay.align_to_reference", side_effect=translated):
                registered = _registered_hold_polygons(capture, first, [hold], 4, 4, 0)
            capture.release()
            self.assertEqual(len(registered), 4)
            self.assertAlmostEqual(registered[3][0][0][0], 44 / 120, delta=.02)
            self.assertIsNone(_interpolated_hold_polygons({0: registered[0]}, 3, 4))
            halfway = _interpolated_hold_polygons({0: registered[0], 2: registered[2]}, 1, 4)
            self.assertAlmostEqual(halfway[0][0][0], 28 / 120, delta=.02)

    def test_legacy_preset_colour_auto_refine_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (96, 64))
            if not writer.isOpened():
                self.skipTest("MP4 encoder unavailable")
            for _ in range(8):
                writer.write(np.full((64, 96, 3), 64, dtype=np.uint8))
            writer.release()
            info = VideoInfo(width=96, height=64, fps=4, frame_count=8,
                             duration_seconds=2, size_bytes=source.stat().st_size)
            store = ClimbReplayStore(root / "store")
            job = store.create(owner="alice", route_id=None, route_color="灰色",
                               source=source, original_name="clip.mp4", info=info,
                               consent={"event": "granted"}, retention_mode="keep_private_original")
            keep = {"id": 1, "bbox": [.1, .1, .12, .12], "polygon": [[.1, .1], [.22, .1],
                    [.22, .22], [.1, .22]], "contour_source": "climbing_model_native_mask",
                    "identity_source": "multi_frame_geometry", "route_candidate": True,
                    "appearances": 3, "score": .9, "color_group": "灰色"}
            reject = {"id": 2, "bbox": [.6, .5, .12, .12], "polygon": [[.6, .5], [.72, .5],
                      [.72, .62], [.6, .62]], "contour_source": "climbing_model_native_mask",
                      "identity_source": "multi_frame_geometry", "route_candidate": False,
                      "appearances": 1, "score": .5, "color_group": "红色"}
            points = [[0.0, 0.0] for _ in range(17)]
            result = {"route": {"color": "灰色", "color_sample": None},
                      "holds": [keep, reject], "hold_candidates": [],
                      "hold_evidence": {"selection": "color_candidates_need_review",
                                        "reference_frame": 0, "frames_aligned": 3},
                      "pose_samples": [{"sample_index": i, "source_frame_id": i,
                                        "observed": True, "wall_alignment": "aligned",
                                        "kpts_xy": points, "kpts_score": [1.0] * 17,
                                        "time_seconds": i / 4} for i in range(4)],
                      "analysis": {"sampling": {"effective_fps": 4}},
                      "attempt": {"contacts": [], "segments": []}}
            store.update(job["id"], status="succeeded", result=result)
            def fake_render(_, target, __):
                target.write_bytes(b"reviewed-overlay")
                return {"rendered": True}
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                updated = store.refine_sampled_holds(job["id"], "alice")
            self.assertEqual(len(updated["result"]["holds"]), 1)
            self.assertEqual(updated["result"]["hold_evidence"]["selection"],
                             "minimal_colour_geometry_needs_review")
            repeated = store.refine_sampled_holds(job["id"], "alice")
            self.assertEqual(len(repeated["hold_review_history"]), 1)

    def test_click_near_bottom_traces_hold_and_rejects_wall(self):
        frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
        cv2.rectangle(frame, (42, 82), (59, 96), (170, 125, 20), -1)
        polygon = clicked_hold_polygon(frame, [50 / 120, 90 / 100])
        self.assertGreaterEqual(len(polygon), 4)
        self.assertGreaterEqual(min(point[1] for point in polygon), 80)
        with self.assertRaises(HTTPException):
            clicked_hold_polygon(frame, [.1, .2])

    def test_clicked_hold_is_saved_and_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (120, 100))
            if not writer.isOpened():
                self.skipTest("MP4 encoder unavailable")
            frame = np.full((100, 120, 3), (180, 205, 220), dtype=np.uint8)
            cv2.rectangle(frame, (42, 82), (59, 96), (170, 125, 20), -1)
            cv2.rectangle(frame, (16, 30), (32, 44), (170, 125, 20), -1)
            for _ in range(8):
                writer.write(frame)
            writer.release()
            info = VideoInfo(width=120, height=100, fps=4, frame_count=8,
                             duration_seconds=2, size_bytes=source.stat().st_size)
            store = ClimbReplayStore(root / "store")
            job = store.create(owner="alice", route_id=None, route_color="青色",
                               source=source, original_name="clip.mp4", info=info,
                               consent={"event": "granted"}, retention_mode="keep_private_original")
            points = [[0.0, 0.0] for _ in range(17)]
            result = {"holds": [], "hold_candidates": [],
                      "hold_evidence": {"reference_frame": 0},
                      "pose_samples": [{"sample_index": i, "source_frame_id": i,
                                        "observed": True, "wall_alignment": "aligned",
                                        "kpts_xy": points, "kpts_score": [1.0] * 17,
                                        "time_seconds": i / 4} for i in range(4)],
                      "analysis": {"sampling": {"effective_fps": 4}},
                      "attempt": {"contacts": [], "segments": []}}
            store.update(job["id"], status="succeeded", result=result)
            def fake_render(_, target, __):
                target.write_bytes(b"reviewed-overlay")
                return {"rendered": True}
            preview = store.preview_hold_at_point(job["id"], "alice", ReplayHoldPoint(
                point_xy=[50 / 120, .9], time_seconds=0))
            self.assertGreaterEqual(len(preview["source_polygon"]), 4)
            self.assertEqual(store.get(job["id"], "alice").get("hold_review_history"), None)
            region = [40 / 120, .79, 66 / 120, .99]
            boxed_preview = store.preview_hold_at_point(job["id"], "alice", ReplayHoldPoint(
                point_xy=[53 / 120, .89], time_seconds=0, region_xyxy=region))
            self.assertGreaterEqual(len(boxed_preview["source_polygon"]), 4)
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                updated = store.add_hold_at_point(job["id"], "alice", ReplayHoldPoint(
                    point_xy=[53 / 120, .89], time_seconds=0, region_xyxy=region))
            self.assertEqual(updated["result"]["holds"][0]["polygon"], boxed_preview["reference_polygon"])
            self.assertEqual(updated["hold_review_history"][0]["region_xyxy"], region)
            self.assertEqual(updated["result"]["holds"][0]["identity_source"],
                             "user_confirmed_video_click")
            self.assertEqual(updated["hold_review_history"][0]["operation"], "add_hold_at_point")
            with self.assertRaises(HTTPException) as error:
                store.add_hold_at_point(job["id"], "alice", ReplayHoldPoint(
                    point_xy=[50 / 120, .9], time_seconds=0))
            self.assertEqual(error.exception.status_code, 409)
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                twice = store.add_hold_at_point(job["id"], "alice", ReplayHoldPoint(
                    point_xy=[24 / 120, .37], time_seconds=0))
            self.assertEqual(len(twice["result"]["holds"]), 2)
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                undone = store.undo_clicked_hold(job["id"], "alice", 1)
            self.assertEqual(len(undone["result"]["holds"]), 1)
            self.assertEqual(undone["result"]["holds"][0]["review_version"], 2)
            self.assertEqual(undone["hold_review_history"][-1]["target_review_version"], 1)
            with self.assertRaises(HTTPException) as error:
                store.undo_clicked_hold(job["id"], "alice", 1)
            self.assertEqual(error.exception.status_code, 409)
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                last_undone = store.undo_last_clicked_hold(job["id"], "alice")
            self.assertEqual(last_undone["result"]["holds"], [])
            self.assertEqual(last_undone["hold_review_history"][-1]["target_review_version"], 2)

    def test_repeated_candidate_is_promoted_and_contacts_are_recomputed_without_cloud(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (96, 64))
            if not writer.isOpened():
                self.skipTest("MP4 encoder unavailable")
            for _ in range(8):
                writer.write(np.full((64, 96, 3), 64, dtype=np.uint8))
            writer.release()
            info = VideoInfo(width=96, height=64, fps=4, frame_count=8,
                             duration_seconds=2, size_bytes=source.stat().st_size)
            store = ClimbReplayStore(root / "store")
            job = store.create(owner="alice", route_id=None, route_color="蓝色",
                               source=source, original_name="clip.mp4", info=info,
                               consent={"event": "granted"}, retention_mode="keep_private_original")
            points = [[0.0, 0.0] for _ in range(17)]
            points[15] = [.5, .78]
            candidate = {"bbox": [.45, .75, .1, .1], "polygon": [[.45, .75], [.55, .75],
                         [.55, .85], [.45, .85]], "appearances": 4, "score": .97,
                         "color_group": "青色", "contour_source": "climbing_model_native_mask"}
            result = {"holds": [{"id": 1, "bbox": [.1, .1, .1, .1]}],
                      "hold_candidates": [candidate], "hold_evidence": {"reference_frame": 0},
                      "pose_samples": [{"sample_index": i, "source_frame_id": i,
                                        "observed": True, "wall_alignment": "aligned",
                                        "kpts_xy": points, "kpts_score": [1.0] * 17,
                                        "time_seconds": i / 4} for i in range(4)],
                      "analysis": {"sampling": {"effective_fps": 4}},
                      "attempt": {"contacts": [], "segments": []}}
            store.update(job["id"], status="succeeded", result=result)

            def fake_render(_, target, __):
                target.write_bytes(b"reviewed-overlay")
                return {"rendered": True}

            with self.assertRaises(HTTPException):
                store.promote_hold_candidate(job["id"], "bob", 0)
            with patch("core.climb_replay.align_to_reference", return_value=(np.eye(3), {})), \
                 patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                updated = store.promote_hold_candidate(job["id"], "alice", 0)
            self.assertEqual(updated["result"]["holds"][-1]["id"], 2)
            self.assertEqual(updated["result"]["holds"][-1]["identity_source"],
                             "user_confirmed_video_candidate")
            self.assertEqual(updated["result"]["hold_candidates"], [])
            self.assertTrue(any(item["limb"] == "left_foot" and item["hold_id"] == 2
                                for item in updated["result"]["attempt"]["contacts"]))
            self.assertEqual(updated["media"]["reviewed_overlay_video"]["status"], "available")
            self.assertEqual(updated["hold_review_history"][0]["version"], 1)
            self.assertEqual(store.get(job["id"], "alice", private=True)["automatic_result"], result)
            with self.assertRaises(HTTPException):
                store.promote_hold_candidate(job["id"], "alice", 0)
            with patch("core.climb_replay.render_replay_overlay_video", side_effect=fake_render):
                reverted = store.undo_clicked_hold(job["id"], "alice", 1)
            self.assertEqual(len(reverted["result"]["holds"]), 1)
            self.assertEqual(reverted["hold_review_history"][-1]["operation"], "undo_promote_candidate")


if __name__ == "__main__":
    unittest.main()
