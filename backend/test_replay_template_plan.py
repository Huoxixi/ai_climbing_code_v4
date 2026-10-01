"""Pure source-time template tests; synthetic evidence is not visual acceptance."""
from copy import deepcopy
import math
import unittest

from core.replay_template_plan import build_template_plan
from core.replay_template_renderer import validate_plan


def job(duration=8.):
    limbs = ("left_hand", "right_hand", "left_foot", "right_foot")
    return {"result": {"video": {"width": 720, "height": 880, "fps": 30.,
                                 "frame_count": round(duration * 30), "duration_seconds": duration},
        "pose_samples": [{"time_seconds": n / 4, "observed": True,
            "kpts_xy": [[.6, .4]] * 17, "kpts_score": [1.] * 17,
            "private_unused_field": "omit"} for n in range(int(duration * 4) + 1)],
        "attempt": {"topped_out": True, "elapsed_seconds": 999,
                    "contacts": [{"limb": limb, "hold_id": n + 1,
                         "start_time_seconds": 0., "end_time_seconds": duration} for n, limb in enumerate(limbs)]}}}


def evidence(start, end):
    return [{"frame_id": f"frame-{round(t * 30)}", "time_seconds": t} for t in (start, (start + end) / 2, end)]


def group(start, end, caption="左脚位置抬高，右手向上移动。"):
    return {"caption": caption, "start_seconds": start, "end_seconds": end,
            "limb": "left_foot", "evidence_status": "sampled_observation", "evidence": evidence(start, end)}


def fact(start=2., end=4., key="observation-1"):  # gitleaks:allow -- constructed evidence ID
    return {"id": key, "observation": "前后画面中的左脚位置不同。", "start_seconds": start,
            "end_seconds": end, "limb": "left_foot", "fact_kind": "position_change",
            "review_worthy": True, "review_question": "左脚变化前后的落点是否相同？",
            "evidence": evidence(start, end), "independent_review": {"status": "verified", "visible": True,
                "temporal_coverage": True, "record_conflict": False, "label_dependent": False,
                "normal_explanation": "ruled_out"}}


def report_with_advice():
    observation = fact()
    return {"action_groups": [group(0., 4.), group(4., 8. - 1 / 30)], "observations": [observation],
        "knowledge_status": {"eligible_advice_claims": 1},
        "provenance": {"knowledge_versions": {"claim-test": 2}, "analysis_version": "fixture"},
        "improvements": [{"observation_id": observation["id"], "claim_id": "claim-test", "claim_version": 2,
            "adjustment": "保留原动作方案，先确认下一步已有脚序。", "verification": "核对是否仍出现相同调整。",
            "condition_checks": [{"condition_id": "feet-visible", "verified": True, "state": "satisfied"}],
            "knowledge_refs": [{"claim_id": "claim-test", "version": 2}]}]}


class TemplatePlanTests(unittest.TestCase):
    def test_first_pass_covers_start_and_full_finish_then_data_and_focus(self):
        plan = build_template_plan(job(), report_with_advice())
        self.assertEqual([row["kind"] for row in plan["shots"]], ["action", "action", "data", "data", "focus"])
        actions = plan["shots"][:2]
        self.assertEqual([(row["source_start_seconds"], row["source_end_seconds"]) for row in actions], [(0., 4.), (4., 8.)])
        self.assertEqual([row["transition_seconds"] for row in plan["shots"]], [0., 0., .3, .3, .3])
        self.assertEqual(plan["frame_count"], validate_plan(plan))
        self.assertEqual(plan["duration_seconds"], plan["frame_count"] / 30)

    def test_absent_report_is_honest_full_video_not_sample_hardcoded_values(self):
        data = job(11.5)
        data["result"]["attempt"]["contacts"] = []
        plan = build_template_plan(data, {})
        self.assertEqual(plan["shots"][0]["source_end_seconds"], 11.5)
        self.assertEqual(plan["shots"][0]["evidence_status"], "unknown")
        self.assertEqual(plan["shots"][1]["metrics"]["timing"]["label"], "已观察时长")
        self.assertEqual(plan["shots"][1]["metrics"]["timing"]["outcome"], "unconfirmed")
        self.assertTrue(all(row["count"] is None for row in plan["shots"][1]["metrics"]["limbs"]))
        self.assertFalse(any(row["kind"] == "focus" for row in plan["shots"]))
        self.assertTrue(any("没有通过" in text for text in plan["notices"]))

    def test_gaps_are_unknown_and_overlaps_do_not_skip_original_intervals(self):
        plan = build_template_plan(job(), {"action_groups": [group(1., 3.), group(2., 5.), group(6., 7.)]})
        actions = [row for row in plan["shots"] if row["kind"] == "action"]
        self.assertEqual([(row["source_start_seconds"], row["source_end_seconds"]) for row in actions],
                         [(0., 1.), (1., 3.), (3., 6.), (6., 7.), (7., 8.)])
        self.assertEqual([row["evidence_status"] for row in actions],
                         ["unknown", "sampled_observation", "unknown", "sampled_observation", "unknown"])
        self.assertEqual(validate_plan(plan), plan["frame_count"])

    def test_unanchored_or_prescriptive_group_is_not_a_valid_explanation(self):
        rows = [group(0., 3., "你必须抬高左脚。"), group(3., 5.)]
        rows[1]["evidence"][0]["time_seconds"] = 2.
        plan = build_template_plan(job(), {"action_groups": rows})
        self.assertEqual(len([row for row in plan["shots"] if row["kind"] == "action"]), 1)
        self.assertEqual(plan["shots"][0]["evidence_status"], "unknown")

    def test_sampled_observation_cannot_become_focused_advice(self):
        report = report_with_advice()
        report["observations"][0].pop("independent_review")
        plan = build_template_plan(job(), report)
        self.assertFalse(any(row["kind"] == "focus" for row in plan["shots"]))

    def test_knowledge_and_condition_checks_are_required_for_adjustment_pages(self):
        for mutate in (lambda r: r["knowledge_status"].update(eligible_advice_claims=0),
                       lambda r: r["provenance"]["knowledge_versions"].clear(),
                       lambda r: r["improvements"][0]["condition_checks"][0].update(verified=False),
                       lambda r: r["improvements"][0].update(knowledge_refs=[]),
                       lambda r: r["observations"][0]["independent_review"].update(normal_explanation="unknown")):
            with self.subTest(mutate=mutate):
                report = report_with_advice()
                mutate(report)
                focus = build_template_plan(job(), report)["shots"][-1]
                self.assertEqual(focus["kind"], "focus")
                self.assertIsNone(focus["claim_id"])
                self.assertNotIn("保留原动作方案", str(focus))

    def test_adjustment_and_next_practice_keep_reading_time(self):
        plan = build_template_plan(job(), report_with_advice())
        shot = plan["shots"][-1]
        self.assertEqual(len(shot["caption_steps"]), 3)
        self.assertIn("调整", shot["caption_steps"][1]["detail"])
        self.assertIn("下次练习", shot["caption_steps"][2]["detail"])
        self.assertEqual(shot["caption_steps"][-1]["end_seconds"], shot["duration_seconds"])
        self.assertTrue(all(row["end_seconds"] - row["start_seconds"] >= 3 for row in shot["caption_steps"]))
        self.assertEqual(shot["source_end_seconds"], 4.)

    def test_at_most_two_independently_reviewed_focus_groups(self):
        report = {"observations": [fact(0, 2, "one"), fact(2, 4, "two"), fact(4, 6, "three")]}
        plan = build_template_plan(job(), report)
        self.assertEqual(sum(row["kind"] == "focus" for row in plan["shots"]), 2)

    def test_duplicate_contacts_count_once_and_initial_contacts_are_included(self):
        data = job()
        data["result"]["attempt"]["contacts"].append({"limb": "left_hand", "hold_id": 1,
            "start_time_seconds": 2., "end_time_seconds": 4.})
        plan = build_template_plan(data, {})
        rows = plan["shots"][1]["metrics"]["limbs"]
        self.assertEqual([row["count"] for row in rows], [1, 1, 1, 1])
        self.assertTrue(all(row["status"] == "automatic" for row in rows))

    def test_unknown_rhythm_is_preserved_not_renormalized_into_movement(self):
        data = job()
        data["result"]["pose_samples"] = []
        plan = build_template_plan(data, {})
        rhythm = plan["shots"][2]["metrics"]["rhythm"]
        self.assertEqual(rhythm["percentages"], {"hold": 0., "transition": 0., "unknown": 100.})
        self.assertEqual(rhythm["segments"], [{"kind": "unknown", "start_seconds": 0., "end_seconds": 8.}])
        self.assertIsNone(plan["shots"][2]["metrics"]["longest_hold"])

    def test_review_boundaries_completed_fall_and_cutoff_keep_distinct_labels(self):
        for outcome, label in (("completed", "攀爬用时"), ("fell", "攀爬用时"), ("truncated", "已观察时长")):
            plan = build_template_plan(job(), {}, {"timing": {"start_seconds": 1., "end_seconds": 7.,
                "observed_start_seconds": 1., "observed_end_seconds": 7., "outcome": outcome}})
            timing = plan["shots"][1]["metrics"]["timing"]
            self.assertEqual(timing["label"], label)
            self.assertEqual(timing["value_seconds"], 6.)
            self.assertEqual(plan["shots"][0]["source_end_seconds"], 8.)

    def test_reviewed_no_contact_can_be_zero_without_unknown_becoming_zero(self):
        plan = build_template_plan(job(), {}, {"contacts": []})
        self.assertEqual([row["count"] for row in plan["shots"][1]["metrics"]["limbs"]], [0, 0, 0, 0])

    def test_all_display_timing_quantized_but_source_timing_unchanged(self):
        plan = build_template_plan(job(), {"action_groups": [group(0., 2.137), group(2.137, 8.)]})
        self.assertEqual(plan["shots"][0]["source_end_seconds"], 2.137)
        cursor = 0
        for shot in plan["shots"]:
            cursor += round(shot["transition_seconds"] * 30)
            self.assertAlmostEqual(shot["start_seconds"], cursor / 30)
            self.assertAlmostEqual(shot["duration_seconds"] * 30, round(shot["duration_seconds"] * 30))
            self.assertGreaterEqual(shot["duration_seconds"] + 1e-8,
                                    (shot["source_end_seconds"] - shot["source_start_seconds"]) / shot["playback_rate"])
            cursor += round(shot["duration_seconds"] * 30)
        self.assertEqual(cursor, plan["frame_count"])

    def test_input_evidence_unchanged_and_tracking_allowlist(self):
        data, report = job(), report_with_advice()
        before = deepcopy((data, report))
        plan = build_template_plan(data, report)
        self.assertEqual((data, report), before)
        self.assertNotIn("private_unused_field", str(plan["tracking_samples"]))

    def test_invalid_source_metadata_rejected(self):
        for value in (0, -1, float("nan"), 1801):
            data = job()
            data["result"]["video"]["duration_seconds"] = value
            if math.isnan(value):
                data["result"]["video"].pop("frame_count")
            with self.assertRaises(ValueError):
                build_template_plan(data, {})


if __name__ == "__main__":
    unittest.main()
