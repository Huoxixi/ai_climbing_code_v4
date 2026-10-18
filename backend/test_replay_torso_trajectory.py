import copy
import unittest
import numpy as np

from core.replay_torso_trajectory import torso_trajectory, enrich_torso_trajectory, climbing_window
from core.replay_motion_summary import enrich_motion_summary


def fixture():
    samples = []
    for index, dx in enumerate((0, -.02, -.04, -.02, 0, .02, .04, .06, .08)):
        xy = [[.1, .1] for _ in range(17)]
        for joint, x, y in ((5, .4, .3), (6, .6, .3), (11, .4, .6), (12, .6, .6)):
            xy[joint] = [x + dx, y - index * .01]
        samples.append({"observed": True, "time_seconds": index / 4, "source_frame_id": index * 6,
                        "kpts_xy": xy, "kpts_score": [.9] * 17, "wall_alignment": "reference",
                        "wall_reference_transform": np.eye(3).tolist()})
    return {"video": {"width": 640, "height": 480, "duration_seconds": 2, "fps": 24, "frame_count": 48},
            "holds": [{"id": 1, "bbox": [.4,.7,.1,.1]}, {"id": 2, "bbox": [.4,.1,.1,.1]}, {"id": 3, "bbox": [.6,.7,.1,.1]}],
            "attempt": {"contacts": [{"limb": limb, "hold_id": 3 if limb == "right_foot" else 1, "start_time_seconds": 0, "end_time_seconds": 2}
                                     for limb in ("left_hand","right_hand","left_foot","right_foot")]},
            "pose_samples": samples, "source_duration_seconds": 2, "metrics": [], "motion_intervals": []}


class TorsoTrajectoryTests(unittest.TestCase):
    def test_measured_route_and_direction_metrics_without_mutating_evidence(self):
        result = fixture()
        original = copy.deepcopy(result)
        trajectory = torso_trajectory(result)
        self.assertEqual(result, original)
        self.assertEqual(trajectory["status"], "observed")
        self.assertEqual(trajectory["coverage"], 1.)
        self.assertEqual(len(trajectory["segments"]), 1)
        self.assertEqual(len(trajectory["segments"][0]), 9)
        self.assertFalse(trajectory["interpolated"])
        self.assertEqual(trajectory["metrics"]["net_horizontal_percent"], 8.)
        self.assertEqual(trajectory["metrics"]["left_extent_percent"], 4.)
        self.assertEqual(trajectory["metrics"]["right_extent_percent"], 8.)
        self.assertEqual(trajectory["metrics"]["horizontal_span_percent"], 12.)

    def test_camera_translation_does_not_become_torso_displacement(self):
        result = fixture()
        for index, sample in enumerate(result["pose_samples"]):
            sample["kpts_xy"] = copy.deepcopy(result["pose_samples"][0]["kpts_xy"])
            for point in sample["kpts_xy"]:
                point[0] += index * .01
            sample["wall_reference_transform"][0][2] = -index * .01 * 640
        trajectory = torso_trajectory(result)
        self.assertEqual(trajectory["metrics"]["horizontal_span_percent"], 0.)
        self.assertEqual(trajectory["metrics"]["net_horizontal_percent"], 0.)

    def test_missing_occluded_and_bad_registration_break_the_path(self):
        for kind in ("missing", "occluded", "registration"):
            result = fixture()
            sample = result["pose_samples"][4]
            if kind == "missing":
                sample["observed"] = False
            elif kind == "occluded":
                sample["kpts_score"][5] = sample["kpts_score"][6] = .1
            else:
                sample["wall_alignment_diagnostics"] = {"median_error_px": 10}
            trajectory = torso_trajectory(result)
            self.assertEqual([len(run) for run in trajectory["segments"]], [4, 4])
            self.assertEqual(trajectory["coverage"], .75)
            self.assertEqual(trajectory["status"], "partial")

    def test_sampling_gap_is_not_connected_or_counted(self):
        result = fixture()
        result["pose_samples"] = result["pose_samples"][:2] + result["pose_samples"][5:]
        trajectory = torso_trajectory(result)
        self.assertEqual([len(run) for run in trajectory["segments"]], [2, 4])
        self.assertEqual(trajectory["breaks"]["sampling_gap"], 1)
        self.assertEqual(trajectory["observed_seconds"], 1.)

    def test_single_spike_does_not_become_a_lateral_extreme(self):
        result = fixture()
        for joint in (5, 6, 11, 12):
            result["pose_samples"][4]["kpts_xy"][joint][0] += .35
        trajectory = torso_trajectory(result)
        self.assertEqual(trajectory["breaks"]["jump"], 1)
        self.assertNotIn("frame-24", [point["frame_id"] for run in trajectory["segments"] for point in run])
        self.assertIsNone(trajectory["metrics"])

    def test_changed_reference_joints_cannot_create_a_bias_metric(self):
        result = fixture()
        for sample in result["pose_samples"][5:]:
            sample["kpts_score"][5] = .1
        trajectory = torso_trajectory(result)
        self.assertEqual(trajectory["breaks"]["reference_joints_changed"], 1)
        self.assertIsNone(trajectory["metrics"])

    def test_unregistered_or_sparse_evidence_reports_unavailable(self):
        for result in ({}, {"video": fixture()["video"]}, fixture()):
            for sample in result.get("pose_samples", []):
                sample["wall_alignment"] = "unknown"
            self.assertEqual(torso_trajectory(result)["status"], "insufficient")
        result = fixture()
        result["pose_samples"] = result["pose_samples"][:2]
        self.assertEqual(torso_trajectory(result)["status"], "insufficient")

    def test_summary_persistence_contains_trajectory_without_overwriting_input(self):
        result = fixture()
        self.assertIn("torso_trajectory", enrich_motion_summary(result))
        enriched = enrich_torso_trajectory(result)
        self.assertEqual(enriched["torso_trajectory"]["version"], "registered-torso-center-trajectory-v2")
        self.assertNotIn("torso_trajectory", result)


class ClimbingWindowTests(unittest.TestCase):
    def test_starts_at_two_distinct_lit_holds_and_stops_when_both_hands_reach_top(self):
        result = fixture()
        rows = result["attempt"]["contacts"]
        rows[3]["start_time_seconds"] = .5
        rows[0]["end_time_seconds"] = 1.25
        rows[1]["end_time_seconds"] = 1.5
        rows.extend([{"limb": limb,"hold_id":2,"start_time_seconds":start,"end_time_seconds":2}
                     for limb,start in (("left_hand",1.25),("right_hand",1.5))])
        window = climbing_window(result)
        self.assertEqual((window["start_seconds"],window["end_seconds"]),(.5,1.5))
        self.assertEqual(window["status"],"finish_observed")
        route = torso_trajectory(result)
        self.assertEqual(route["segments"][0][0]["time_seconds"],.5)
        self.assertEqual(route["segments"][-1][-1]["time_seconds"],1.5)
        self.assertEqual(route["coverage"],1)

    def test_same_lower_hold_is_not_a_finish_and_one_top_hand_is_not_enough(self):
        result = fixture()
        self.assertEqual(climbing_window(result)["status"],"finish_unconfirmed")
        result["attempt"]["contacts"].append({"limb":"left_hand","hold_id":2,"start_time_seconds":1,"end_time_seconds":2})
        self.assertEqual(climbing_window(result)["status"],"finish_unconfirmed")

    def test_single_lit_hold_does_not_start_route(self):
        result = fixture()
        result["attempt"]["contacts"][3]["hold_id"] = 1
        self.assertEqual(torso_trajectory(result)["segments"],[])

    def test_two_limbs_are_enough_and_no_earlier_pose_is_included(self):
        result = fixture()
        result["attempt"]["contacts"] = result["attempt"]["contacts"][2:]
        result["attempt"]["contacts"][1]["start_time_seconds"] = .5
        self.assertEqual(climbing_window(result)["start_seconds"], .5)
        self.assertEqual(torso_trajectory(result)["segments"][0][0]["time_seconds"], .5)

    def test_non_overlapping_distinct_holds_do_not_start(self):
        result = fixture()
        result["attempt"]["contacts"] = result["attempt"]["contacts"][2:]
        result["attempt"]["contacts"][0]["end_time_seconds"] = .25
        result["attempt"]["contacts"][1]["start_time_seconds"] = .5
        self.assertIsNone(climbing_window(result)["start_seconds"])
        result.pop("attempt")
        self.assertEqual(torso_trajectory(result)["segments"],[])

    def test_explicit_finish_overrides_highest_candidate_and_frame_intervals_work(self):
        result = fixture()
        result["holds"][0]["is_finish"] = True
        rows=result["attempt"]["contacts"]
        for row in rows:
            row.pop("start_time_seconds");row.pop("end_time_seconds")
            row.update(start_source_frame=12,end_source_frame=48)
        self.assertEqual(climbing_window(result)["finish_basis"],"marked_finish")
        self.assertEqual(climbing_window(result)["end_seconds"],.5)
