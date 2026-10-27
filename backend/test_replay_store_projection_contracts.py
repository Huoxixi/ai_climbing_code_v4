"""Characterize the existing public projection using constructed dictionaries only."""
import copy
import unittest
from unittest.mock import patch

from core.climb_replay import ClimbReplayStore, visual_input_version
from core.replay_visual_renderer import VISUAL_VERSION


PRIVATE_FIELDS = (
    "input_path", "source_path", "saved_route_reference", "automatic_result",
    "coaching", "coaching_history", "template_video", "action_task", "action_result",
    "action_export", "action_export_media", "action_history", "action_revisions",
    "action_revision_audit", "action_result_history", "action_commentary_checkpoint",
    "worker_failure", "overlay_history",
)


def visual_job():
    result = {
        "holds": [], "attempt": {"contacts": [], "segments": []},
        "visual_replay": {
            "status": "ready", "visual_version": VISUAL_VERSION,
            "tail_duration_seconds": 3, "message": "saved-note",
        },
    }
    result["visual_replay"]["input_version"] = visual_input_version(result)
    return {"id": "synthetic", "owner": "alice", "status": "succeeded",
            "result": result, "media": {"source_video": {"status": "available"}}}


class ReplayStoreProjectionContracts(unittest.TestCase):
    def project(self, job, *, enabled=True):
        # Preserve the existing late-bound patch location during store extraction.
        with patch("core.climb_replay.replay_visual_enabled", return_value=enabled):
            return ClimbReplayStore._public(job)

    def test_known_private_fields_and_overlay_history_are_excluded(self):
        job = {"id": "synthetic", "owner": "alice", "status": "succeeded"}
        job.update({key: {"private": "constructed"} for key in PRIVATE_FIELDS})
        public = self.project(job)
        self.assertEqual(set(public), {"id", "owner", "status", "holds_pending_local_analysis"})
        self.assertFalse(public["holds_pending_local_analysis"])
        self.assertTrue(all(key in job for key in PRIVATE_FIELDS))

    def test_unknown_legacy_fields_remain_passthrough_with_shallow_identity(self):
        job = {"id": "synthetic", "owner": "alice", "progress": 37,
               "created_at": "2026-01-02T03:04:00Z",
               "legacy_extension": {"values": [1, 2]}, "warnings": ["constructed"],
               "media": {"source_video": {"status": "available"}}}
        public = self.project(job)
        self.assertIsNot(public, job)
        for key in ("id", "owner", "progress", "created_at"):
            self.assertEqual(public[key], job[key])
        for key in ("legacy_extension", "warnings", "media"):
            self.assertIs(public[key], job[key])

    def test_truthy_result_is_deep_copied_without_mutating_private_evidence(self):
        job = {"result": {"pose_samples": [{"kpts_xy": [[0.1, 0.2]]}],
                          "attempt": {}, "legacy_result_field": {"values": [1]}}}
        original = copy.deepcopy(job)
        public = self.project(job)
        self.assertEqual(job, original)
        self.assertIsNot(public["result"], job["result"])
        public["result"]["pose_samples"][0]["kpts_xy"][0][0] = 0.9
        public["result"]["legacy_result_field"]["values"].append(2)
        self.assertEqual(job, original)

    def test_empty_result_retains_the_existing_shallow_identity(self):
        job = {"result": {}, "reviewed_segments": ["legacy-value"]}
        public = self.project(job)
        self.assertIs(public["result"], job["result"])
        self.assertIs(public["reviewed_segments"], job["reviewed_segments"])

    def test_hold_revision_uses_edit_result_then_initial_draft_priority(self):
        job = {
            "result": {"holds": [{"id": 1}], "hold_evidence": {"reference_frame": 5}, "hold_review_version": 2},
            "hold_draft": {"holds": [{"id": 2}], "hold_evidence": {"reference_frame": 7}, "hold_review_version": 3},
            "hold_edit_draft": {"holds": [{"id": 3}], "hold_evidence": {"reference_frame": 9}, "hold_review_version": 4},
        }
        public = self.project(job)
        self.assertEqual(public["holds_revision"], "8a7645c8211ce6df6e2cda17cf34bc83c2ca6f5c7689eea2008073f45884b9a1")
        self.assertTrue(public["holds_pending_local_analysis"])
        self.assertIs(public["hold_edit_draft"], job["hold_edit_draft"])
        job["hold_edit_draft"] = {}
        public = self.project(job)
        self.assertFalse(public["holds_pending_local_analysis"])
        self.assertEqual(public["holds_revision"], "b8a6368b3fcde47aa8f1457d522f78453618fe50a063fc18dc1bd336b3597e97")
        del job["result"]
        self.assertEqual(self.project(job)["holds_revision"], "5238d5929d84562053c86a158eae2344799574603c2eaded79946e82dae0f8ee")

    def test_no_hold_input_does_not_discard_a_legacy_revision_field(self):
        public = self.project({"holds_revision": "legacy-revision", "holds_pending_local_analysis": True})
        self.assertEqual(public["holds_revision"], "legacy-revision")
        self.assertFalse(public["holds_pending_local_analysis"])
        self.assertNotIn("holds_revision", self.project({}))

    def test_review_overlay_is_derived_without_rewriting_automatic_segments(self):
        segment = {"id": "segment", "limb": "left_hand", "metadata": {"basis": "synthetic"},
                   "boundary_uncertainty_seconds": 0.05, "start_time_seconds": 0, "end_time_seconds": 1}
        job = {"video": {"fps": 25}, "result": {"attempt": {"segments": [segment]}},
               "segment_reviews": {"segment": {"limb": "right_hand", "source_route_hold_id": "a",
                   "target_route_hold_id": "b", "start_time_seconds": 1.0, "end_time_seconds": 2.2,
                   "version": 3, "technique_label": "constructed-label"}}}
        original = copy.deepcopy(job)
        public = self.project(job)
        reviewed = public["reviewed_segments"][0]
        self.assertEqual(reviewed["limb"], "right_hand")
        self.assertEqual(reviewed["duration_seconds"], 1.2)
        self.assertEqual(reviewed["boundary_uncertainty_seconds"], 0.08)
        self.assertEqual(reviewed["source"], "user_confirmed")
        self.assertEqual(reviewed["review_version"], 3)
        self.assertEqual(reviewed["technique_labels"], [{"name": "constructed-label", "source": "user_confirmed"}])
        self.assertIs(reviewed["metadata"], segment["metadata"])
        self.assertIsNot(public["result"]["attempt"]["segments"][0]["metadata"], segment["metadata"])
        self.assertEqual(job, original)

    def test_current_visual_version_retains_status_and_saved_metadata(self):
        job = visual_job()
        public = self.project(job)
        visual = public["result"]["visual_replay"]
        self.assertEqual(visual["status"], "ready")
        self.assertEqual(visual["message"], "saved-note")
        self.assertNotIn("stale", visual)
        self.assertTrue(visual["can_retry"])
        self.assertNotIn("can_retry", job["result"]["visual_replay"])

    def test_old_visual_version_with_positive_tail_is_marked_stale_on_public_copy(self):
        job = visual_job()
        job["result"]["visual_replay"]["visual_version"] = "legacy-renderer"
        original = copy.deepcopy(job)
        visual = self.project(job)["result"]["visual_replay"]
        self.assertEqual(visual["status"], "stale")
        self.assertTrue(visual["stale"])
        self.assertEqual(visual["visual_version"], "legacy-renderer")
        self.assertEqual(visual["message"], "复核内容或视觉版本已更新，请重新制作线路回放")
        self.assertEqual(job, original)

    def test_changed_review_input_also_invalidates_a_saved_positive_tail(self):
        job = visual_job()
        job["segment_reviews"] = {"synthetic-segment": {"version": 2}}
        visual = self.project(job)["result"]["visual_replay"]
        self.assertEqual(visual["status"], "stale")
        self.assertTrue(visual["stale"])

    def test_missing_zero_and_negative_tail_do_not_invent_a_stale_transition(self):
        for tail in ("missing", None, 0, -1):
            with self.subTest(tail=tail):
                job = visual_job()
                visual = job["result"]["visual_replay"]
                visual["visual_version"] = "legacy-renderer"
                if tail == "missing":
                    visual.pop("tail_duration_seconds")
                else:
                    visual["tail_duration_seconds"] = tail
                projected = self.project(job)["result"]["visual_replay"]
                self.assertEqual(projected["status"], "ready")
                self.assertEqual(projected["message"], "saved-note")
                self.assertNotIn("stale", projected)

    def test_outdated_failed_visual_keeps_failure_status_while_exposing_staleness(self):
        job = visual_job()
        job["result"]["visual_replay"].update(status="failed", visual_version="legacy-renderer")
        visual = self.project(job)["result"]["visual_replay"]
        self.assertEqual(visual["status"], "failed")
        self.assertEqual(visual["message"], "saved-note")
        self.assertTrue(visual["stale"])

    def test_retry_eligibility_uses_source_or_reference_plus_either_overlay(self):
        for source, reference, overlay, reviewed, expected in (
            (True, False, False, False, True),
            (False, True, True, False, True),
            (False, True, False, True, True),
            (False, True, False, False, False),
            (False, False, True, False, False),
            (False, False, False, True, False),
            (False, False, False, False, False),
        ):
            with self.subTest(source=source, reference=reference, overlay=overlay, reviewed=reviewed):
                job = visual_job()
                job["media"] = {key: {"status": "available" if present else "deleted"} for key, present in (
                    ("source_video", source), ("wall_reference", reference),
                    ("overlay_video", overlay), ("reviewed_overlay_video", reviewed))}
                self.assertEqual(self.project(job)["result"]["visual_replay"]["can_retry"], expected)

    def test_disabled_visual_or_non_successful_job_overrides_saved_retry_flag(self):
        for enabled, status, expected in ((False, "succeeded", False), (True, "failed", False),
                (True, "running", False), (True, "queued", False), (True, "cancelled", False),
                (True, "succeeded", True)):
            with self.subTest(enabled=enabled, status=status):
                job = visual_job()
                job["status"] = status
                job["result"]["visual_replay"]["can_retry"] = True
                self.assertEqual(self.project(job, enabled=enabled)["result"]["visual_replay"]["can_retry"], expected)

    def test_absent_or_empty_visual_metadata_remains_absent_or_empty(self):
        self.assertNotIn("visual_replay", self.project({"result": {"attempt": {}}})["result"])
        self.assertEqual(self.project({"result": {"visual_replay": {}}})["result"]["visual_replay"], {})

    def test_skeleton_projection_cleans_hold_data_recursively_without_changing_source(self):
        job = {"id": "synthetic", "skeleton_only": True, "route_id": "legacy-route", "route_color": "黄色",
               "hold_edit_draft": {"holds": [{"id": 1}]},
               "media": {"source_video": {"status": "available"}},
               "legacy_extension": {"notes": ["keep"]},
               "result": {"holds": [{"id": 1}], "models": {"holds": "synthetic-hold", "pose": "synthetic-pose"},
                   "pose_samples": [{"kpts_xy": [[0.1, 0.2]], "contact_score": 0.5}],
                   "attempt": {"contacts": [{"hold_id": 1}], "elapsed_seconds": 2},
                   "metrics": [{"key": "route_used", "value": 1}, {"key": "movement", "label": "移动", "value": 2},
                               {"key": "legacy_metric", "label": "岩点数", "value": 1}]}}
        original = copy.deepcopy(job)
        public = self.project(job)
        self.assertTrue(public["skeleton_only"])
        self.assertEqual(public["route_id"], "legacy-route")
        for key in ("route_color", "hold_edit_draft", "holds_revision", "holds_pending_local_analysis"):
            self.assertNotIn(key, public)
        self.assertNotIn("holds", public["result"])
        self.assertEqual(public["result"]["models"], {"pose": "synthetic-pose"})
        self.assertNotIn("contacts", public["result"]["attempt"])
        self.assertNotIn("contact_score", public["result"]["pose_samples"][0])
        self.assertEqual(public["result"]["metrics"], [{"key": "movement", "label": "移动", "value": 2}])
        self.assertEqual(public["result"]["pose_samples"][0]["kpts_xy"], [[0.1, 0.2]])
        self.assertIsNot(public["legacy_extension"], job["legacy_extension"])
        self.assertIsNot(public["media"], job["media"])
        self.assertEqual(job, original)


if __name__ == "__main__":
    unittest.main()
