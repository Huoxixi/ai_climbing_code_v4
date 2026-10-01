import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from core.replay_visual_renderer import (VisualInputError, build_visual_manifest, camera_matrix,
                                         iter_visual_frames, render_visual_tail, visual_output_size,
                                         visual_event_state)


def fixture(width=160, height=240, fps=24):
    holds = [{"id": i + 1, "polygon": [[x, y], [x + .1, y], [x + .1, y + .08], [x, y + .08]]}
             for i, (x, y) in enumerate(((.25, .70), (.55, .5), (.32, .25)))]
    contacts = [{"hold_id": 1, "limb": "left_hand", "start_time_seconds": 1},
                {"hold_id": 2, "limb": "right_hand", "start_time_seconds": 1},
                {"hold_id": 3, "limb": "left_hand", "start_time_seconds": 4}]
    result = {"holds": holds, "attempt": {"contacts": contacts, "topped_out": True}}
    reference = {"width": width, "height": height, "source_frame_id": 0, "source_sha256": "fixture"}
    return result, reference, build_visual_manifest(result, reference, fps=fps)


class ReplayVisualRendererTests(unittest.TestCase):
    def test_limb_identity_is_kept_on_shared_hold_and_old_lines_disappear(self):
        result, reference, _ = fixture()
        result["attempt"]["contacts"].extend([
            {"hold_id": 3, "limb": "right_hand", "start_time_seconds": 4},
            {"hold_id": 3, "limb": "left_foot", "start_time_seconds": 4},
            {"hold_id": 3, "limb": "right_foot", "start_time_seconds": 4}])
        manifest = build_visual_manifest(result, reference)
        state = visual_event_state(manifest, 6.2)
        self.assertEqual(len(state["hold_limb_groups"]["3"]), 4)
        self.assertEqual(set(state["positions"]), {"left_hand", "right_hand", "left_foot", "right_foot"})
        self.assertEqual(len(state["transitions"]), 2)
        self.assertEqual(visual_event_state(manifest, 7)["transitions"], [])
        self.assertEqual(len(visual_event_state(manifest, 7)["hold_limb_groups"]["3"]), 4)

    def test_four_limb_demo_has_start_and_multiple_changes_without_fake_real_contacts(self):
        from scripts.build_replay_visual_sample import illustrative_contacts
        holds = [{"id": i, "polygon": [[.2, .9 - i * .08], [.3, .9 - i * .08], [.3, .95 - i * .08]]}
                 for i in range(8)]
        contacts = illustrative_contacts(holds)
        for limb in ("left_hand", "right_hand", "left_foot", "right_foot"):
            events = [e for e in contacts if e["limb"] == limb]
            self.assertGreaterEqual(len(events), 3)
            self.assertEqual(events[0]["start_time_seconds"], 0)
        self.assertTrue(all(e["source"] == "illustrative_demo_order" for e in contacts))
        result, reference, real = fixture()
        self.assertEqual({e["limb"] for e in real["events"]}, {"left_hand", "right_hand"})

    def test_non_numeric_ids_get_distinct_readable_numbers(self):
        result, reference, _ = fixture()
        for hold, ident in zip(result["holds"], ("object-01-long-id", "object-02-long-id", "object-03-long-id")):
            old = hold["id"]
            hold["id"] = ident
            for event in result["attempt"]["contacts"]:
                if event["hold_id"] == old:
                    event["hold_id"] = ident
        manifest = build_visual_manifest(result, reference)
        self.assertEqual([h["display_number"] for h in manifest["holds"]], [1, 2, 3])

    def test_nearby_aligned_person_box_disables_only_overlapped_hold_texture(self):
        result, reference, original = fixture()
        result["video"] = {"width": 160, "height": 240, "fps": 24}
        reference["source_frame_id"] = 10
        # Translate the source person box 16 px right into hold 1's reference
        # coordinates, proving the saved homography is used before overlap.
        result["pose_samples"] = [{"source_frame_id": 8, "observed": True,
                                   "wall_alignment": "aligned", "confidence": .8,
                                   "bbox_xywh": [.13, .68, .13, .13],
                                   "wall_reference_transform": [[1, 0, 16], [0, 1, 0], [0, 0, 1]]}]
        manifest = build_visual_manifest(result, reference, fps=24)
        self.assertTrue(manifest["holds"][0]["possible_person_occlusion"])
        self.assertFalse(manifest["holds"][0]["texture_reliable"])
        self.assertTrue(manifest["holds"][1]["texture_reliable"])
        self.assertEqual(manifest["events"], original["events"])
        self.assertEqual(manifest["reference_person_region"]["source_frame_id"], 8)

    def test_no_close_or_reliable_person_observation_means_no_occlusion_guess(self):
        result, reference, _ = fixture()
        reference["source_frame_id"] = 24
        sample = {"source_frame_id": 0, "observed": True, "wall_alignment": "aligned", "confidence": .8,
                  "bbox_xywh": [.1, .1, .8, .8], "wall_reference_transform": np.eye(3).tolist()}
        for change in ({}, {"source_frame_id": 24, "observed": False},
                       {"source_frame_id": 24, "wall_alignment": "failed"},
                       {"source_frame_id": 24, "confidence": .2},
                       {"source_frame_id": 24, "wall_reference_transform": None}):
            result["pose_samples"] = [sample | change]
            manifest = build_visual_manifest(result, reference, fps=24)
            self.assertIsNone(manifest["reference_person_region"])
            self.assertTrue(all(h["texture_reliable"] for h in manifest["holds"]))

    def test_events_keep_simultaneity_and_only_link_same_limb(self):
        result, reference, manifest = fixture()
        before = copy.deepcopy(result)
        self.assertEqual(manifest["events"][0]["tail_time_seconds"], manifest["events"][1]["tail_time_seconds"])
        self.assertIsNone(manifest["events"][1]["previous_hold_id"])
        self.assertEqual(manifest["events"][2]["previous_hold_id"], 1)
        self.assertEqual(manifest["title"], "本次用点回顾")
        self.assertEqual(result, before)
        self.assertEqual(manifest, build_visual_manifest(result, reference, fps=24))
        result["attempt"]["contacts"][2]["start_time_seconds"] = 5
        self.assertNotEqual(manifest["input_digest"], build_visual_manifest(result, reference)["input_digest"])

    def test_rejected_contacts_and_ambiguous_simultaneous_limb_have_no_false_lines(self):
        result, reference, _ = fixture()
        result["attempt"]["contacts"].extend([
            {"hold_id": 2, "limb": "left_hand", "start_time_seconds": 4},
            {"hold_id": 2, "limb": "left_foot", "start_time_seconds": 5, "status": "rejected"},
            {"hold_id": 3, "limb": "right_foot", "start_time_seconds": 6, "confidence": .2},
        ])
        manifest = build_visual_manifest(result, reference)
        self.assertEqual(len(manifest["events"]), 4)
        self.assertTrue(all(e["previous_hold_id"] is None for e in manifest["events"]))

    def test_dense_sequence_extends_without_changing_original_times(self):
        result, reference, _ = fixture()
        result["attempt"]["contacts"] = [{"hold_id": i % 3 + 1, "limb": "left_hand", "start_time_seconds": i / 5}
                                           for i in range(25)]
        manifest = build_visual_manifest(result, reference, fps=30)
        self.assertEqual(manifest["duration_seconds"], 10)
        self.assertEqual(manifest["frame_count"], 300)
        self.assertEqual([e["source_time_seconds"] for e in manifest["events"]], [i / 5 for i in range(25)])

    def test_bad_reference_rejects_and_limited_reference_reduces_motion(self):
        result, reference, normal = fixture()
        reference["quality"] = "limited"
        limited = build_visual_manifest(result, reference)
        self.assertLess(limited["camera"]["motion_scale"], normal["camera"]["motion_scale"])
        reference["registration_valid"] = False
        with self.assertRaises(VisualInputError):
            build_visual_manifest(result, reference)

    def test_camera_never_exposes_an_edge_in_both_orientations(self):
        for w, h in ((720, 1280), (1280, 720)):
            _, _, manifest = fixture(w, h)
            corners = np.float32([[[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]])
            for seconds in np.linspace(0, 8, 81):
                inverse = np.linalg.inv(camera_matrix(manifest, seconds))
                mapped = cv2.perspectiveTransform(corners, inverse)[0]
                self.assertTrue(np.all(mapped >= -.01), (seconds, mapped))
                self.assertTrue(np.all(mapped <= [w - 1 + .01, h - 1 + .01]), (seconds, mapped))
            self.assertTrue(np.array_equal(camera_matrix(manifest, 7), camera_matrix(manifest, 7.99)))

    def test_native_mask_texture_unavailable_uses_neutral_marker(self):
        result, reference, _ = fixture()
        result["holds"][0].pop("polygon")
        result["holds"][0]["bbox"] = [.25, .7, .1, .08]
        self.assertFalse(build_visual_manifest(result, reference)["holds"][0]["texture_reliable"])

    def test_output_limits_and_source_aspect(self):
        self.assertEqual(visual_output_size(1920, 1080), (1280, 720))
        self.assertEqual(visual_output_size(1080, 1920), (720, 1280))
        result, reference, _ = fixture()
        with self.assertRaises(VisualInputError):
            build_visual_manifest(result, reference, output_size=(1280, 720))

    def test_source_frame_uses_source_fps_and_checksum_alias_is_enforced(self):
        result, reference, _ = fixture()
        result["video"] = {"fps": 30}
        result["attempt"]["contacts"] = [{"hold_id": 1, "limb": "left_hand", "start_source_frame": 90}]
        manifest = build_visual_manifest(result, reference, fps=24)
        self.assertEqual(manifest["events"][0]["source_time_seconds"], 3)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            cv2.imencode(".png", np.full((240, 160, 3), 100, np.uint8))[1].tofile(str(source))
            manifest["reference"]["checksum_sha256"] = "incorrect"
            with self.assertRaisesRegex(VisualInputError, "版本已改变"):
                next(iter_visual_frames(source, manifest))

    def test_streamed_frames_have_a_full_second_still_and_atomic_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wall.png"
            y, x = np.mgrid[:240, :160]
            pixels = np.stack((x % 255, y % 255, (x + y) % 255), axis=2).astype(np.uint8)
            cv2.imencode(".png", pixels)[1].tofile(str(source))
            _, _, manifest = fixture()
            manifest["reference"]["reference_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            frames = iter_visual_frames(source, manifest)
            still = None
            count = 0
            for index, frame in enumerate(frames):
                count += 1
                self.assertEqual(frame.shape, (240, 160, 3))
                if index >= 7 * 24:
                    if still is None:
                        still = frame.copy()
                    self.assertTrue(np.array_equal(still, frame))
            self.assertEqual(count, 192)
            target = root / "tail.webm"
            target.write_bytes(b"existing-playable-version")
            with self.assertRaisesRegex(RuntimeError, "取消"):
                render_visual_tail(source, manifest, target, cancelled=lambda: True)
            self.assertEqual(target.read_bytes(), b"existing-playable-version")
            self.assertFalse(list(root.glob("*.partial.webm")))
            metrics = render_visual_tail(source, manifest, target)
            self.assertEqual(metrics["frame_count"], 192)
            self.assertGreater(metrics["size_bytes"], 1000)


if __name__ == "__main__":
    unittest.main()
