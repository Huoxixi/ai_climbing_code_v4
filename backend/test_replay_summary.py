import copy
import unittest

from core.replay_summary import LIMBS, build_replay_summary


def evidence(duration=4):
    return {"video": {"duration_seconds": duration, "fps": 30},
            "analysis": {"sampling": {"effective_fps": 4}},
            "pose_samples": [{"time_seconds": index / 4, "observed": True,
                              "wall_alignment": "aligned", "kpts_xy": [[.5, .5] for _ in range(17)],
                              "kpts_score": [1.0] * 17} for index in range(int(duration * 4) + 1)],
            "attempt": {"elapsed_seconds": 999, "topped_out": True, "contacts": [
                {"limb": limb, "hold_id": index + 1, "start_time_seconds": 0,
                 "end_time_seconds": duration} for index, limb in enumerate(LIMBS)]}}


def reviewed_contacts(result):
    return [{"limb": row["limb"], "hold_id": row["hold_id"],
             "start_seconds": row["start_time_seconds"], "end_seconds": row["end_time_seconds"],
             "status": "reviewed"} for row in result["attempt"]["contacts"]]


class ReplaySummaryTests(unittest.TestCase):
    def test_automatic_timing_does_not_claim_lift_off_or_completion(self):
        summary = build_replay_summary(evidence())
        self.assertIsNone(summary["timing"]["start_seconds"])
        self.assertIsNone(summary["timing"]["elapsed_seconds"])
        self.assertEqual(summary["timing"]["observed_duration_seconds"], 4)
        self.assertEqual(summary["timing"]["outcome"], "unconfirmed")

    def test_counts_unique_holds_separately_from_contact_intervals_and_merges_regrip(self):
        result = evidence()
        result["attempt"]["contacts"][0]["end_time_seconds"] = 1
        result["attempt"]["contacts"].append({"limb": "left_hand", "hold_id": 1,
                                                "start_time_seconds": 1.5, "end_time_seconds": 4})
        summary = build_replay_summary(result)
        self.assertEqual(summary["limbs"]["left_hand"]["count"], 1)
        self.assertEqual(summary["limbs"]["left_hand"]["contact_count"], 2)
        self.assertEqual(len(summary["phases"]), 1)
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 4)
        self.assertIn("left_hand:same_hold_regrip_merged", summary["phases"][0]["notes"])

    def test_different_hold_gap_is_transition_and_not_part_of_longest_hold(self):
        result = evidence()
        result["attempt"]["contacts"][0]["end_time_seconds"] = 1
        result["attempt"]["contacts"].append({"limb": "left_hand", "hold_id": 5,
                                                "start_time_seconds": 2, "end_time_seconds": 4})
        summary = build_replay_summary(result)
        self.assertEqual([row["kind"] for row in summary["phases"]], ["hold", "transition", "hold"])
        self.assertIsNone(summary["phases"][1]["contacts"]["left_hand"])
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 2)
        self.assertEqual(summary["limbs"]["left_hand"]["hold_ids"], [1, 5])

    def test_missing_joint_breaks_hold_and_is_not_a_release(self):
        result = evidence()
        result["pose_samples"][8]["kpts_score"][10] = 0
        summary = build_replay_summary(result)
        unknown = [row for row in summary["phases"] if row["kind"] == "unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["contacts"]["right_hand"], "unknown")
        self.assertEqual((unknown[0]["start_seconds"], unknown[0]["end_seconds"]), (1.75, 2.25))
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 1.75)

    def test_missing_sample_gap_is_not_filled_from_neighboring_poses(self):
        result = evidence()
        result["pose_samples"] = [row for row in result["pose_samples"] if not 1 < row["time_seconds"] < 3]
        summary = build_replay_summary(result)
        self.assertEqual(summary["coverage"]["unknown_seconds"], 2)
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 1)

    def test_review_window_clips_contacts_including_contacts_started_before_lift_off(self):
        result = evidence()
        contacts = reviewed_contacts(result)
        contacts += [{"limb": "left_hand", "hold_id": 9, "start_seconds": 0, "end_seconds": 1},
                     {"limb": "right_hand", "hold_id": 9, "start_seconds": 3, "end_seconds": 4}]
        summary = build_replay_summary(result, {"timing": {"start_seconds": 1, "end_seconds": 3,
                                                           "outcome": "completed"}, "contacts": contacts})
        self.assertEqual(summary["timing"]["elapsed_seconds"], 2)
        self.assertEqual(summary["limbs"]["left_hand"]["hold_ids"], [1])
        self.assertEqual(summary["limbs"]["right_hand"]["hold_ids"], [2])
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 2)

    def test_review_unknown_overrides_even_reviewed_contacts(self):
        result = evidence()
        review = {"contacts": reviewed_contacts(result), "uncertainties": [
            {"start_seconds": 1, "end_seconds": 3, "limbs": ["left_foot"], "reason": "occluded"}]}
        summary = build_replay_summary(result, review)
        self.assertEqual(summary["coverage"]["unknown_seconds"], 2)
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 1)
        self.assertEqual(summary["phases"][1]["contacts"]["left_foot"], "unknown")

    def test_reviewed_null_noncontact_is_distinct_from_unknown_and_does_not_count_as_point(self):
        result = evidence()
        contacts = reviewed_contacts(result)
        contacts[0]["hold_id"] = None
        summary = build_replay_summary(result, {"contacts": contacts})
        self.assertEqual(summary["limbs"]["left_hand"]["count"], 0)
        self.assertEqual(summary["phases"][0]["kind"], "hold")
        self.assertIsNone(summary["phases"][0]["contacts"]["left_hand"])
        contacts[0]["hold_id"] = "unknown"
        summary = build_replay_summary(result, {"contacts": contacts})
        self.assertIsNone(summary["longest_hold"])

    def test_explicit_reviewed_release_between_different_points_is_a_transition(self):
        result = evidence()
        contacts = reviewed_contacts(result)
        contacts[0]["end_seconds"] = 1
        contacts.extend([{"limb": "left_hand", "hold_id": None, "start_seconds": 1, "end_seconds": 2},
                         {"limb": "left_hand", "hold_id": 8, "start_seconds": 2, "end_seconds": 4}])
        summary = build_replay_summary(result, {"contacts": contacts})
        self.assertEqual([phase["kind"] for phase in summary["phases"]], ["hold", "transition", "hold"])
        self.assertEqual(summary["limbs"]["left_hand"]["contact_count"], 2)
        contacts[-1]["hold_id"] = 1
        summary = build_replay_summary(result, {"contacts": contacts})
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 4)

    def test_review_is_reversible_and_does_not_mutate_inputs(self):
        result = evidence()
        review = {"contacts": reviewed_contacts(result)}
        review["contacts"][0]["hold_id"] = 8
        original_result, original_review = copy.deepcopy(result), copy.deepcopy(review)
        summary = build_replay_summary(result, review)
        self.assertEqual(summary["limbs"]["left_hand"]["hold_ids"], [8])
        self.assertEqual(summary["automatic_summary"]["limbs"]["left_hand"]["hold_ids"], [1])
        self.assertEqual(summary["provenance"]["review"], review)
        self.assertEqual(result, original_result)
        self.assertEqual(review, original_review)

    def test_truncated_or_fallen_attempt_does_not_become_completed(self):
        for outcome in ("truncated", "fallen", "incomplete"):
            summary = build_replay_summary(evidence(), {"timing": {"outcome": outcome,
                "observed_start_seconds": .5, "observed_end_seconds": 3.5}})
            self.assertIsNone(summary["timing"]["elapsed_seconds"])
            self.assertEqual(summary["timing"]["observed_duration_seconds"], 3)
            self.assertEqual(summary["timing"]["outcome"], outcome)
            self.assertEqual(summary["coverage"]["duration_seconds"], 3)

    def test_phase_reviews_preserve_gaps_and_uncertainties_and_recompute_durations(self):
        result = evidence()
        group = {limb: index + 1 for index, limb in enumerate(LIMBS)}
        review = {"phase_reviews": [{"kind": "hold", "start_seconds": 1, "end_seconds": 4,
                                     "duration_seconds": 99, "contacts": group}],
                  "uncertainties": [{"start_seconds": 2, "end_seconds": 3,
                                     "limbs": ["right_foot"], "reason": "not_visible"}]}
        summary = build_replay_summary(result, review)
        self.assertEqual(summary["coverage"]["unknown_seconds"], 2)
        self.assertEqual(summary["coverage"]["hold_seconds"], 2)
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 1)
        self.assertEqual(summary["longest_hold"]["source"], "reviewed_phases")
        self.assertEqual(summary["automatic_summary"]["longest_hold"]["duration_seconds"], 4)

    def test_conflicting_contacts_are_unknown_and_invalid_reviews_rejected(self):
        result = evidence()
        result["attempt"]["contacts"].append({"limb": "left_hand", "hold_id": 99,
                                                "start_time_seconds": 1, "end_time_seconds": 3})
        summary = build_replay_summary(result)
        self.assertEqual(summary["coverage"]["unknown_seconds"], 2)
        for review in ({"timing": {"start_seconds": -1, "end_seconds": 3}},
                       {"contacts": [{"limb": "left_hand", "hold_id": 1,
                                      "start_seconds": float("nan"), "end_seconds": 3}]},
                       {"phase_reviews": [{"kind": "hold", "start_seconds": 0, "end_seconds": 3},
                                          {"kind": "hold", "start_seconds": 2, "end_seconds": 4}]}):
            with self.assertRaises(ValueError):
                build_replay_summary(evidence(), review)

    def test_no_samples_does_not_create_a_certain_hold_but_manual_review_can(self):
        result = evidence()
        result["pose_samples"] = []
        self.assertIsNone(build_replay_summary(result)["longest_hold"])
        summary = build_replay_summary(result, {"contacts": reviewed_contacts(result)})
        self.assertEqual(summary["longest_hold"]["duration_seconds"], 4)


if __name__ == "__main__":
    unittest.main()
