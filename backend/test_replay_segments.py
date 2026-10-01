import unittest

from core.replay_segments import build_segments, compare_segments, effective_segments, measured_joint_angles


def sample_result(*, second_duration=1.5, confirmed=True, aligned=True):
    identity = "confirmed_saved_route" if confirmed else "multi_frame_geometry"
    last_frame = round(second_duration / .25)
    return {
        "holds": [{"id": 1, "saved_object_id": "H04", "identity_source": identity, "saved_route_iou": .8},
                  {"id": 2, "saved_object_id": "H09", "identity_source": identity, "saved_route_iou": .8}],
        "pose_samples": [
            {"sample_index": frame, "source_frame_id": frame, "time_seconds": frame * .25,
             "wall_alignment": "failed" if frame == 0 and not aligned else "aligned"}
            for frame in range(last_frame + 1)
        ],
        "attempt": {"action_steps": [
            {"step": 1, "limb": "right_hand", "hold_id": 1,
             "start_source_frame": 0, "start_time_seconds": 0,
             "stable_source_frame": 0, "stable_time_seconds": 0},
            {"step": 2, "limb": "right_hand", "hold_id": 2,
             "start_source_frame": last_frame, "start_time_seconds": second_duration,
             "stable_source_frame": last_frame, "stable_time_seconds": second_duration},
        ]},
    }


class ReplaySegmentTests(unittest.TestCase):
    def test_angles_use_pixel_aspect_and_visibility(self):
        points = [[0, 0] for _ in range(17)]
        scores = [0.0] * 17
        points[5], points[7], points[9] = [.2, .5], [.5, .5], [.5, .7]
        for index in (5, 7, 9):
            scores[index] = 1.0
        self.assertEqual(measured_joint_angles(points, scores, 1920, 1080), {"left_elbow": 90.0})
        scores[9] = .1
        self.assertEqual(measured_joint_angles(points, scores, 1920, 1080), {})

    def test_unconfirmed_or_unaligned_hold_never_comparable(self):
        for kwargs, reason in [({"confirmed": False}, "unconfirmed_hold_identity"),
                               ({"aligned": False}, "wall_alignment_insufficient")]:
            segment = build_segments(sample_result(**kwargs))[0]
            self.assertFalse(segment["comparable"])
            self.assertEqual(segment["reason"], reason)

    def test_comparison_requires_same_route_version_and_climber_confirmation(self):
        first = {"id": "a", "owner": "alice", "route_id": "route", "route_version_id": "v1",
                 "result": sample_result()}
        second = {"id": "b", "owner": "alice", "route_id": "route", "route_version_id": "v1",
                  "result": sample_result(second_duration=1.25)}
        first["result"]["attempt"]["segments"] = build_segments(first["result"])
        second["result"]["attempt"]["segments"] = build_segments(second["result"])
        with self.assertRaisesRegex(ValueError, "same_climber_unconfirmed"):
            compare_segments(first, second, same_climber_confirmed=False)
        second["route_version_id"] = "v2"
        with self.assertRaisesRegex(ValueError, "route_version_mismatch"):
            compare_segments(first, second, same_climber_confirmed=True)
        second["route_version_id"] = "v1"
        pair = compare_segments(first, second, same_climber_confirmed=True)["segments"][0]
        self.assertEqual(pair["status"], "uncertain")
        self.assertEqual(pair["delta_seconds"], -.25)
        first["result"] = sample_result(second_duration=2.0)
        first["result"]["attempt"]["segments"] = build_segments(first["result"])
        second["result"] = sample_result(second_duration=.25)
        second["result"]["attempt"]["segments"] = build_segments(second["result"])
        self.assertEqual(compare_segments(first, second, same_climber_confirmed=True)["segments"][0]["status"], "shorter")

    def test_manual_review_preserves_automatic_segment(self):
        original = sample_result(confirmed=False)
        original["attempt"]["segments"] = build_segments(original)
        job = {"video": {"fps": 4}, "result": original, "segment_reviews": {
            "right_hand:1:2": {"limb": "right_hand", "source_route_hold_id": "H04",
                               "target_route_hold_id": "H09", "start_time_seconds": .1,
                               "end_time_seconds": 1.4, "technique_label": "锁臂", "version": 1},
        }}
        reviewed = effective_segments(job)[0]
        self.assertTrue(reviewed["comparable"])
        self.assertEqual(reviewed["source"], "user_confirmed")
        self.assertEqual(reviewed["technique_labels"][0]["source"], "user_confirmed")
        self.assertFalse(original["attempt"]["segments"][0]["comparable"])


if __name__ == "__main__":
    unittest.main()
