import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from core import simulation
from core.models import HoldPhysicsProfile, HoldType, SimulationFeedback, SimulationRequest
from core.simulation_physics import (
    _two_link_joint,
    body_dimension_errors,
    body_dimensions_valid,
    contact_point,
    coord,
    normal_bend_is_valid,
    pose_has_crossing,
)
from core.simulation_solver import RouteSimulationSolver, state_dict
from core.standard_board import detail_for, find_standard_route, query_standard_routes


class SimulationEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_id = query_standard_routes(difficulty="6B+", limit=1).routes[0].source_id
        cls.direct_detail = detail_for(find_standard_route("171108"))
        cls.dynamic_detail = detail_for(find_standard_route("21396"))
        cls.reference_profile = {
            profile.id: profile
            for profile in simulation.get_climber_profiles("6B+")
        }["reference"]
        cls.hold_profiles = {
            profile.variant_id: profile
            for profile in simulation.get_hold_profiles()
        }
        cls.direct_solver = RouteSimulationSolver(
            cls.direct_detail,
            cls.reference_profile,
            cls.hold_profiles,
        )
        cls.direct_outcome = cls.direct_solver.solve("static")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = patch.multiple(
            simulation,
            LOCAL_DIR=root,
            REPORTS_DIR=root / "reports",
            LATEST_INDEX_PATH=root / "latest.json",
            HOLD_OVERRIDES_PATH=root / "holds.json",
            FEEDBACK_PATH=root / "feedback.json",
            MODIFICATION_LOG_PATH=root / "modification_log.json",
        )
        self.patches.start()

    def tearDown(self):
        self.patches.stop()
        self.temp.cleanup()

    def test_default_cohort_has_three_distinct_body_profiles(self):
        profiles = simulation.get_climber_profiles("6C")
        self.assertEqual([profile.id for profile in profiles], ["compact", "reference", "tall-reach"])
        self.assertLess(profiles[0].arm_span_cm, profiles[1].arm_span_cm)
        self.assertLess(profiles[1].arm_span_cm, profiles[2].arm_span_cm)
        self.assertEqual(profiles[0].capabilities.ability_grade, "6C")

    def test_hold_profile_update_is_local_and_versioned(self):
        original = simulation.get_hold_profiles()[0]
        payload = original.model_dump()
        payload.update({"quality": 4, "confidence": 0.9, "notes": "人工标定"})
        updated = HoldPhysicsProfile(**payload)
        simulation.update_hold_profile(original.variant_id, updated)
        saved = {item.variant_id: item for item in simulation.get_hold_profiles()}[original.variant_id]
        self.assertEqual(saved.quality, 4)
        self.assertEqual(saved.confidence, 0.9)

    def test_default_hand_holds_are_usable_by_feet_but_foot_holds_are_not_usable_by_hands(self):
        profiles = simulation.get_hold_profiles()
        for profile in profiles:
            if profile.hold_type in {HoldType.JUG, HoldType.CRIMP}:
                self.assertEqual(profile.usable_by, "both")
            if profile.hold_type == HoldType.FOOT:
                self.assertEqual(profile.usable_by, "foot")

    def test_request_maps_legacy_mode_and_rejects_conflicts(self):
        self.assertEqual(SimulationRequest(static_only=True).motion_mode, "static")
        self.assertFalse(SimulationRequest(static_only=False).static_only)
        self.assertEqual(SimulationRequest().motion_mode, "static_then_single_dynamic")
        with self.assertRaises(ValidationError):
            SimulationRequest(motion_mode="static", static_only=False)

    def test_unreachable_two_link_ik_is_not_clamped(self):
        joint = _two_link_joint(
            np.array([0.0, 0.0]),
            np.array([1.0, 0.0]),
            0.3,
            0.3,
            1.0,
        )
        self.assertIsNone(joint)

    def test_direct_static_beta_uses_only_route_holds_and_has_no_deletable_action(self):
        self.assertEqual(self.direct_outcome.solution_mode, "static")
        self.assertGreaterEqual(len(self.direct_outcome.paths), 1)
        path = self.direct_outcome.paths[0]
        allowed = {
            hold_id
            for role in ("start", "mid", "end")
            for hold_id in self.direct_detail.roles[role]
        }
        setup = {hold.id: hold for hold in self.direct_detail.board_setup}

        for state, evaluation in zip(path.states, path.evaluations):
            contacts = state_dict(state)
            self.assertTrue(evaluation.valid)
            self.assertTrue(any(contacts[limb] for limb in ("lh", "rh")))
            self.assertTrue(any(contacts[limb] for limb in ("lf", "rf")))
            self.assertTrue(all(not hold_id or hold_id in allowed for hold_id in contacts.values()))
            for limb in ("lh", "rh"):
                if contacts[limb]:
                    self.assertNotEqual(setup[contacts[limb]].hold_type, HoldType.FOOT)

        end_id = self.direct_detail.roles["end"][0]
        final_contacts = state_dict(path.states[-1])
        self.assertEqual(final_contacts["lh"], end_id)
        self.assertEqual(final_contacts["rh"], end_id)
        self.assertTrue(
            any(
                action.limb in {"lf", "rf"} and setup[action.target_id].hold_type != HoldType.FOOT
                for action in path.actions
            )
        )
        for index in range(len(path.actions)):
            self.assertIsNone(
                self.direct_solver.replay(
                    path.start_state,
                    [*path.actions[:index], *path.actions[index + 1 :]],
                )
            )
        for index, action in enumerate(path.actions):
            if action.limb not in {"lf", "rf"}:
                continue
            previous = state_dict(path.states[index]).get(action.limb)
            if previous:
                self.assertLessEqual(int(action.target_id[1:]) - int(previous[1:]), 4)

    def test_static_beta_has_coordinated_motion_grammar_and_discrete_centered_frames(self):
        path = self.direct_outcome.paths[0]
        self.assertGreaterEqual(
            sum(action.limb in {"lf", "rf"} for action in path.actions),
            2,
        )
        consecutive_hands = 0
        for action in path.actions:
            if action.limb in {"lf", "rf"}:
                consecutive_hands = 0
            elif action.action_type != "match":
                consecutive_hands += 1
                self.assertLessEqual(consecutive_hands, 2)
            if action.preparation_required:
                self.assertIsNotNone(action.preparation_pose)
        for state, evaluation in zip(path.states, path.evaluations):
            contacts = state_dict(state)
            if contacts["lh"] and contacts["rh"] and contacts["lh"] != contacts["rh"]:
                self.assertLessEqual(coord(contacts["lh"])[0], coord(contacts["rh"])[0])
            if contacts["lf"] and contacts["rf"] and contacts["lf"] != contacts["rf"]:
                self.assertLessEqual(coord(contacts["lf"])[0], coord(contacts["rf"])[0])
            self.assertFalse(pose_has_crossing(evaluation.pose.joints))

        frames, actions, _, _ = simulation._frames_and_actions(
            path,
            self.direct_detail,
            self.reference_profile,
            self.hold_profiles,
        )
        self.assertEqual(len(frames), len(path.actions) + 1)
        self.assertEqual(len(actions), len(path.actions))
        self.assertEqual(frames[0].phase, "rest")
        self.assertTrue({frame.phase for frame in frames[1:]} <= {"settle", "recovery"})
        self.assertTrue(all(frame.stable for frame in frames))
        self.assertTrue(all(action.technique for action in actions))
        self.assertTrue(all(frame.timestamp_seconds >= 0 for frame in frames))
        self.assertEqual(
            [frame.timestamp_seconds for frame in frames],
            sorted(frame.timestamp_seconds for frame in frames),
        )
        pelvis_positions = {
            (frame.joints["pelvis"].x, frame.joints["pelvis"].y)
            for frame in frames
            if "pelvis" in frame.joints
        }
        self.assertGreater(len(pelvis_positions), 2)
        setup = {hold.id: hold for hold in self.direct_detail.board_setup}
        endpoint_names = {
            "lh": "left_hand",
            "rh": "right_hand",
            "lf": "left_foot",
            "rf": "right_foot",
        }
        for frame in frames:
            self.assertLessEqual(frame.shoulder_wall_distance, 0.30)
            self.assertLessEqual(frame.hip_wall_distance, 0.35)
            for limb, hold_id in frame.contacts.items():
                if not hold_id:
                    continue
                endpoint = frame.joints[endpoint_names[limb]]
                center = coord(hold_id)
                self.assertLessEqual(
                    float(np.linalg.norm(np.array([endpoint.x, endpoint.y]) - center)),
                    1e-6,
                )
                self.assertEqual(frame.contact_anchors[limb], endpoint)

        foot_moves = 0
        for index, action in enumerate(path.actions):
            frame = frames[index + 1]
            self.assertEqual(frame.step, index + 1)
            self.assertEqual(frame.contacts[action.limb], action.target_id)
            if action.limb not in {"lf", "rf"}:
                continue
            foot_moves += 1
            endpoint_name = endpoint_names[action.limb]
            before = frames[index].joints[endpoint_name]
            after = frame.joints[endpoint_name]
            self.assertNotEqual((before.x, before.y), (after.x, after.y))
            self.assertTrue(np.allclose([after.x, after.y], coord(action.target_id), atol=1e-8))
        self.assertGreaterEqual(foot_moves, 2)

    def test_body_proportions_and_normal_joint_bends_stay_fixed(self):
        path = self.direct_outcome.paths[0]
        frames, actions, _, _ = simulation._frames_and_actions(
            path,
            self.direct_detail,
            self.reference_profile,
            self.hold_profiles,
        )
        segment_lengths = {}
        for frame in frames:
            self.assertTrue(
                body_dimensions_valid(frame.joints, self.reference_profile),
                body_dimension_errors(frame.joints, self.reference_profile),
            )
            for segment, error in body_dimension_errors(
                frame.joints,
                self.reference_profile,
            ).items():
                self.assertLessEqual(error, 0.001)
                segment_lengths.setdefault(segment, []).append(error)

        for errors in segment_lengths.values():
            self.assertLessEqual(max(errors) - min(errors), 0.001)

        for evaluation in path.evaluations:
            self.assertTrue(normal_bend_is_valid(evaluation.pose, "lh"))
            self.assertTrue(normal_bend_is_valid(evaluation.pose, "rh"))
        for action, evaluation in zip(actions, path.evaluations[1:]):
            moving = action.moving_limbs[0].value.lower()
            if (
                moving in {"lf", "rf"}
                and action.technique not in {"backstep", "drop_knee", "rock_over"}
            ):
                self.assertTrue(normal_bend_is_valid(evaluation.pose, moving))

    def test_contact_anchor_offsets_are_ignored_and_all_contacts_use_hold_center(self):
        hold = self.direct_detail.board_setup[0]
        profile = self.hold_profiles[hold.variant]
        centered = contact_point(hold.id, "lh", {hold.id: hold}, self.hold_profiles)
        self.assertTrue(np.allclose(centered, coord(hold.id)))

        rotated_hold = hold.model_copy(update={"rotation": 90})
        calibrated = profile.model_copy(
            update={"hand_contact_anchor": profile.hand_contact_anchor.model_copy(update={"x": 1.0, "y": 0.0})}
        )
        point = contact_point(
            hold.id,
            "lh",
            {hold.id: rotated_hold},
            {hold.variant: calibrated},
        )
        recovered = contact_point(
            hold.id,
            "rf",
            {hold.id: rotated_hold},
            {hold.variant: calibrated},
            anchor_kind="recovery",
        )
        self.assertTrue(np.allclose(point, coord(hold.id), atol=1e-8))
        self.assertTrue(np.allclose(recovered, coord(hold.id), atol=1e-8))

    def test_deprecated_contact_anchor_fields_do_not_change_input_hash(self):
        hold_profiles = list(self.hold_profiles.values())
        request = SimulationRequest()
        first_hash = simulation._input_hash(
            self.direct_detail,
            [self.reference_profile],
            hold_profiles,
            request,
        )
        first = hold_profiles[0]
        changed = first.model_copy(
            update={
                "hand_contact_anchor": first.hand_contact_anchor.model_copy(
                    update={"x": 1.0, "y": -1.0}
                )
            }
        )
        second_hash = simulation._input_hash(
            self.direct_detail,
            [self.reference_profile],
            [changed, *hold_profiles[1:]],
            request,
        )
        self.assertEqual(first_hash, second_hash)

    def test_mid_holds_are_optional_and_outside_holds_are_rejected(self):
        detail = self.direct_detail.model_copy(deep=True)
        optional_hold = "K18"
        detail.roles["mid"].append(optional_hold)
        solver = RouteSimulationSolver(detail, self.reference_profile, self.hold_profiles)
        outcome = solver.solve("static")
        self.assertEqual(outcome.solution_mode, "static")
        used = {hold_id for state in outcome.paths[0].states for hold_id in state if hold_id}
        self.assertNotIn(optional_hold, used)

        start = outcome.paths[0].start_state
        contacts = state_dict(start)
        contacts["lh"] = "outside-route"
        self.assertEqual(solver._state_contact_rules(tuple(contacts[key] for key in ("lh", "rh", "lf", "rf"))), "线路外岩点")

    def test_search_budget_exhaustion_is_not_reported_as_no_solution(self):
        solver = RouteSimulationSolver(
            self.direct_detail,
            self.reference_profile,
            self.hold_profiles,
            search_budget=1,
        )
        outcome = solver.solve("static")
        self.assertFalse(outcome.search_complete)
        self.assertEqual(outcome.solution_mode, "none")
        self.assertIn("search_budget", outcome.rejection_counts)

    def test_single_dynamic_solution_stays_in_review(self):
        run, _ = simulation._simulate_profile(
            self.dynamic_detail,
            self.reference_profile,
            self.hold_profiles,
            "static_then_single_dynamic",
        )
        self.assertEqual(run.solution_mode, "single_dynamic")
        self.assertEqual(run.status, "review")
        self.assertEqual(run.dynamic_action_count, 1)
        self.assertTrue(any(action.dynamic for action in run.actions))
        self.assertEqual(len(run.frames), len(run.actions) + 1)
        self.assertFalse(any(frame.phase in {"crouch", "push", "flight", "catch"} for frame in run.frames))
        self.assertTrue(any(frame.dynamic for frame in run.frames))
        self.assertTrue(all(frame.stable for frame in run.frames))
        allowed = {
            hold_id
            for role in ("start", "mid", "end")
            for hold_id in self.dynamic_detail.roles[role]
        }
        for frame in run.frames:
            self.assertTrue(all(not hold_id or hold_id in allowed for hold_id in frame.contacts.values()))

    def test_simulation_is_deterministic_and_cacheable(self):
        first = simulation.simulate_route(self.source_id, SimulationRequest(force_refresh=True))
        second = simulation.simulate_route(self.source_id, SimulationRequest())

        self.assertEqual(first.report_id, second.report_id)
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(len(first.runs), 3)
        self.assertTrue(any(run.frames for run in first.runs))
        self.assertIn(first.verdict, {"pass", "pass_body_bias", "review", "fail"})
        for run in first.runs:
            self.assertIn(run.status, {"passed", "failed", "review"})
        simulation.save_report(first.model_copy(update={"engine_version": "outdated-engine"}))
        self.assertIsNone(simulation.get_latest_report(self.source_id))

    def test_feedback_links_to_report_without_changing_rules(self):
        report = simulation.simulate_route(self.source_id, SimulationRequest(force_refresh=True))
        record = simulation.record_feedback(
            report.report_id,
            SimulationFeedback(outcome="attempt", profile_id="compact", perceived_grade="6B+", system_correct=True),
        )
        self.assertEqual(record.report_id, report.report_id)
        self.assertEqual(record.source_id, self.source_id)
        self.assertFalse((Path(self.temp.name) / "optimal_patterns.json").exists())

    def test_reuse_thresholds_match_route_expert_rules(self):
        self.assertEqual(simulation._reuse_quality(0.39), "below_pass")
        self.assertEqual(simulation._reuse_quality(0.4), "pass")
        self.assertEqual(simulation._reuse_quality(0.7), "optimal")


class SimulationApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_id = query_standard_routes(difficulty="6B+", limit=1).routes[0].source_id

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = patch.multiple(
            simulation,
            LOCAL_DIR=root,
            REPORTS_DIR=root / "reports",
            LATEST_INDEX_PATH=root / "latest.json",
            HOLD_OVERRIDES_PATH=root / "holds.json",
            FEEDBACK_PATH=root / "feedback.json",
            MODIFICATION_LOG_PATH=root / "modification_log.json",
        )
        self.patches.start()
        main.active_tasks.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.patches.stop()
        self.temp.cleanup()

    def test_profiles_and_async_route_simulation_api(self):
        profiles = self.client.get("/api/simulation/climber-profiles", params={"ability_grade": "6B+"})
        self.assertEqual(profiles.status_code, 200)
        self.assertEqual(len(profiles.json()), 3)

        started = self.client.post(
            f"/api/standard-board/routes/{self.source_id}/simulation",
            json={"ability_grade": "6B+", "static_only": True, "force_refresh": True},
        )
        self.assertEqual(started.status_code, 202)
        result = self.client.get(f"/api/result/{started.json()['task_id']}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "completed")
        self.assertEqual(result.json()["result"]["source_id"], self.source_id)

        latest = self.client.get(f"/api/standard-board/routes/{self.source_id}/simulation/latest")
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["report_id"], result.json()["result"]["report_id"])

    def test_conflicting_motion_fields_return_422(self):
        response = self.client.post(
            f"/api/standard-board/routes/{self.source_id}/simulation",
            json={"motion_mode": "static", "static_only": False},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
