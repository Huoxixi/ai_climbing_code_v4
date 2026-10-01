import copy
import unittest
import numpy as np

from core.replay_action_trajectory import analyze_event, enrich_trajectories, registered_points
from core.replay_action_naming import enrich_names, caption_entries
from core.replay_action_engine import track_conflicts
from core.replay_actions import motion_intervals


def fixture(count=9):
    points = np.asarray([[.45, .22]] * 17, float)
    points[5:17] = [[.35, .30], [.55, .30], [.29, .40], [.61, .40], [.27, .50], [.63, .50],
                    [.40, .60], [.50, .60], [.37, .74], [.53, .74], [.36, .88], [.54, .88]]
    return {"source_duration_seconds": (count - 1) / 4, "video": {"width": 720, "height": 880, "fps": 30, "frame_count": count * 8, "duration_seconds": (count - 1) / 4},
            "pose_samples": [{"time_seconds": i / 4, "source_frame_id": i * 8, "observed": True,
                              "kpts_xy": points.tolist(), "kpts_score": [.95] * 17,
                              "wall_alignment": "reference", "wall_reference_transform": np.eye(3).tolist()} for i in range(count)],
            "groups": [{"id": "g", "start_seconds": 0., "end_seconds": (count - 1) / 4,
                        "events": [], "evidence_status": "needs_local_review"}]}


def active_hand(result):
    for i, row in enumerate(result['pose_samples']):
        row['kpts_xy'][9][1] -= i * .012
        row['kpts_xy'][7][1] -= i * .006
    return result


class TrajectoryTests(unittest.TestCase):
    def test_common_body_rotation_is_not_four_active_limb_movements(self):
        result = fixture()
        aspect, pivot = np.array([720., 880.]) / 720., np.array([.45, .6])
        for i, row in enumerate(result['pose_samples']):
            angle = np.deg2rad(i * 3)
            rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            points = np.asarray(row['kpts_xy'])
            row['kpts_xy'] = (((points - pivot) * aspect) @ rotation.T / aspect + pivot).tolist()
        for limb in ('left_hand', 'right_hand', 'left_foot', 'right_foot'):
            detail = analyze_event(result, limb, 0, 2)
            self.assertEqual(detail['status'], 'body_carried')
            self.assertIn('旋转', detail['summary'])
            self.assertAlmostEqual(detail['measurements']['relative_displacement_body_units'], 0, places=3)
        self.assertEqual(enrich_names(result)['groups'][0]['events'], [])
        self.assertTrue(all(not r['candidate_limbs'] for r in motion_intervals(result)))

    def test_common_body_scale_change_is_not_two_high_steps(self):
        result = fixture()
        pivot = np.array([.45, .6])
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'] = ((np.asarray(row['kpts_xy']) - pivot) * (1 - i * .025) + pivot).tolist()
        for limb in ('left_hand', 'right_hand', 'left_foot', 'right_foot'):
            detail = analyze_event(result, limb, 0, 2)
            self.assertNotEqual(detail['status'], 'observed')
            self.assertAlmostEqual(detail['measurements']['torso_scale_ratio'], .8, places=3)
        self.assertEqual(enrich_names(result)['groups'][0]['events'], [])
        self.assertTrue(all(not r['candidate_limbs'] for r in motion_intervals(result)))

    def test_active_rigid_arm_rotation_is_still_observed_with_common_rotation(self):
        for common_rotation in (False, True):
            result = fixture()
            aspect, pivot = np.array([720., 880.]) / 720., np.array([.45, .6])
            for i, row in enumerate(result['pose_samples']):
                points = np.asarray(row['kpts_xy'])
                angle = i * .06
                rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
                # Both bones rotate around the fixed left shoulder; elbow angle
                # remains constant, so an angle-change-only detector is wrong.
                points[[7, 9]] = ((points[[7, 9]] - points[5]) * aspect) @ rotation.T / aspect + points[5]
                if common_rotation:
                    angle = np.deg2rad(i * 3)
                    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
                    points = ((points - pivot) * aspect) @ rotation.T / aspect + pivot
                row['kpts_xy'] = points.tolist()
            detail = analyze_event(result, 'left_hand', 0, 2)
            self.assertEqual(detail['status'], 'observed')
            self.assertAlmostEqual(detail['measurements']['joint_angle_change_deg'], 0, places=1)
            self.assertGreater(detail['measurements']['relative_displacement_body_units'], .25)
            self.assertNotEqual(analyze_event(result, 'right_hand', 0, 2)['status'], 'observed')

    def test_degenerate_torso_small_rotation_plus_scale_cannot_confirm_active_limbs(self):
        result = fixture()
        result['source_duration_seconds'] = result['video']['duration_seconds'] = 1.
        result['groups'][0]['end_seconds'] = 1.
        aspect, pivot = np.array([720., 880.]) / 720., np.array([.45, .6])
        for i, row in enumerate(result['pose_samples']):
            row['time_seconds'] = i / 8
            points = np.asarray(row['kpts_xy'])
            points[[5, 6, 11, 12], 0] = .45
            angle = np.deg2rad(i * .875)
            rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            row['kpts_xy'] = (((points - pivot) * aspect) @ rotation.T * .9875 ** i / aspect + pivot).tolist()
        for limb in ('left_foot', 'right_foot'):
            detail = analyze_event(result, limb, 0, 1)
            self.assertEqual(detail['status'], 'insufficient')
            self.assertIn('torso_transform', detail['reasons'])
            self.assertEqual(detail['phases'], [])
        self.assertTrue(all(not r['candidate_limbs'] for r in motion_intervals(result)))
        self.assertEqual(enrich_names(result)['groups'][0]['events'], [])

    def test_whole_body_translation_is_not_four_reaches(self):
        result = fixture()
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'] = (np.asarray(row['kpts_xy']) + [i * .01, -i * .015]).tolist()
        for limb in ('left_hand', 'right_hand', 'left_foot', 'right_foot'):
            detail = analyze_event(result, limb, 0, 2)
            self.assertEqual(detail['status'], 'body_carried')
            self.assertEqual(detail['phases'], [])
        self.assertTrue(all(not r['candidate_limbs'] for r in motion_intervals(result)))
        output = enrich_names(result)
        self.assertEqual(output['groups'][0]['events'], [])

    def test_camera_translation_is_removed_before_active_motion(self):
        result = fixture()
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'] = (np.asarray(row['kpts_xy']) + [i * .01, i * .006]).tolist()
            row['wall_reference_transform'][0][2] = -i * .01 * 720
            row['wall_reference_transform'][1][2] = -i * .006 * 880
        self.assertEqual(analyze_event(result, 'left_hand', 0, 2)['status'], 'stationary')
        self.assertTrue(all(row['kind'] == 'relative_still' for row in motion_intervals(result)))

    def test_fixed_hand_during_body_raise_is_not_a_reach(self):
        result = fixture()
        for i, row in enumerate(result['pose_samples']):
            points = np.asarray(row['kpts_xy'])
            points[:, 1] -= i * .008
            points[9] = [.27, .5]
            row['kpts_xy'] = points.tolist()
        detail = analyze_event(result, 'left_hand', 0, 2)
        self.assertEqual(detail['status'], 'stationary')
        event = {'limb': 'left_hand', 'action': 'reach', 'frame_ids': ['a', 'b', 'c']}
        checked = {'events': [{**event, 'verified': True, 'conflict': False}]}
        checked = track_conflicts({'events': [event]}, checked, result, [{'frame_id': k, 'time_seconds': t} for k, t in zip(('a', 'b', 'c'), (0, 1, 2))])
        self.assertFalse(checked['events'][0]['verified'])

    def test_single_active_hand_has_direction_and_native_evidence(self):
        result = active_hand(fixture())
        detail = analyze_event(result, 'left_hand', 0, 2)
        self.assertEqual(detail['status'], 'observed')
        self.assertEqual(detail['direction'], 'up')
        self.assertIn('抬手', detail['summary'])
        self.assertEqual(detail['evidence'][1], {'frame_id': 'frame-8', 'time_seconds': .25})
        self.assertEqual(analyze_event(result, 'right_hand', 0, 2)['status'], 'stationary')
        before = copy.deepcopy(result)
        output = enrich_names(result)
        self.assertEqual(result, before)
        event = output['groups'][0]['events'][0]
        self.assertEqual(event['evidence_status'], 'trajectory_observed')
        self.assertEqual(event['facts'], [])
        self.assertEqual(event['technique_tags'], [])
        self.assertEqual(len(caption_entries(output['groups'], 1)), 1)
        self.assertEqual(enrich_names(output), output)

    def test_active_foot_direction_and_joint_change_are_observations(self):
        result = fixture()
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'][15][0] += i * .008
            row['kpts_xy'][15][1] -= i * .008
            row['kpts_xy'][13][0] += i * .002
            row['kpts_xy'][13][1] -= i * .001
        detail = analyze_event(result, 'left_foot', 0, 2)
        self.assertEqual(detail['status'], 'observed')
        self.assertEqual(detail['direction'], 'up_right')
        self.assertNotIn('踩实', detail['summary'])
        self.assertNotIn('岩点', detail['summary'])
        self.assertIn('joint_angle_change_deg', detail['measurements'])

    def test_independent_pose_detail_never_overwrites_a_human_correction(self):
        result = active_hand(fixture())
        result['groups'][0]['events'] = [{'id': 'manual', 'limb': 'left_hand', 'action': 'adjust', 'start_seconds': 0., 'end_seconds': 2.,
                                        'evidence_status': 'human_confirmed', 'event_status': 'human_confirmed', 'facts': [], 'technique_tags': []}]
        output = enrich_names(result)
        event = next(e for e in output['groups'][0]['events'] if e['id'] == 'manual')
        self.assertEqual(event['trajectory_details']['status'], 'observed')
        self.assertIn('调整手部位置', event['display_name'])
        self.assertNotIn('抬手', event['caption_parts'][0]['text'])

    def test_occlusion_and_registration_failure_do_not_get_interpolated(self):
        for kind in ('occlusion', 'registration'):
            result = active_hand(fixture())
            for row in result['pose_samples'][2:7]:
                if kind == 'occlusion': row['kpts_score'][9] = .1
                else: row['wall_alignment'] = 'failed'
            detail = analyze_event(result, 'left_hand', 0, 2)
            self.assertEqual(detail['status'], 'insufficient')
            self.assertLess(detail['coverage'], .5)
            self.assertEqual(detail['phases'], [])
            self.assertEqual(enrich_names(result)['groups'][0]['events'], [])

    def test_whole_left_right_chain_swap_is_rejected_not_relabelled(self):
        result = fixture()
        row = result['pose_samples'][4]
        for a, b in ((5, 6), (7, 8), (9, 10)):
            row['kpts_xy'][a], row['kpts_xy'][b] = row['kpts_xy'][b], row['kpts_xy'][a]
        detail = analyze_event(result, 'left_hand', 0, 2)
        self.assertEqual(detail['status'], 'conflict')
        self.assertIn('side_identity_conflict', detail['reasons'])
        self.assertEqual(detail['phases'], [])
        self.assertEqual(enrich_names(result)['groups'][0]['events'], [])

    def test_crossing_wrists_alone_does_not_flip_anatomical_identity(self):
        result = fixture()
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'][9][0] += i * .01
            row['kpts_xy'][10][0] -= i * .01
            row['kpts_xy'][7][0] += i * .003
            row['kpts_xy'][8][0] -= i * .003
        detail = analyze_event(result, 'left_hand', 0, 2)
        self.assertNotIn('side_identity_conflict', detail['reasons'])
        self.assertEqual(detail['direction'], 'right')

    def test_single_joint_jump_and_jitter_never_create_an_action(self):
        result = fixture()
        result['pose_samples'][4]['kpts_xy'][9] = [.85, .14]
        detail = analyze_event(result, 'left_hand', 0, 2)
        self.assertEqual(detail['status'], 'conflict')
        self.assertTrue({'chain_length_change', 'trajectory_jump'} & set(detail['reasons']))
        jitter = fixture()
        for i, row in enumerate(jitter['pose_samples']):
            row['kpts_xy'][9][0] += (.005 if i % 2 else -.005)
        self.assertNotEqual(analyze_event(jitter, 'left_hand', 0, 2)['status'], 'observed')

    def test_two_phases_require_measured_directions_and_stable_tail(self):
        result = fixture(17)
        for i, row in enumerate(result['pose_samples']):
            up, right = min(max(0, i - 2), 5), min(max(0, i - 7), 5)
            row['kpts_xy'][9][1] -= up * .012
            row['kpts_xy'][9][0] += right * .012
            row['kpts_xy'][7][1] -= up * .003
            row['kpts_xy'][7][0] += right * .003
        detail = analyze_event(result, 'left_hand', 0, 4)
        self.assertEqual(detail['status'], 'observed')
        phases = detail['phases']
        self.assertIn('preparation', [p['code'] for p in phases])
        self.assertIn('transport_second', [p['code'] for p in phases])
        self.assertEqual(phases[-1]['code'], 'settling')
        self.assertIn('接触仍未确认', phases[-1]['text'])
        self.assertIn('先', detail['summary'])

    def test_poor_homography_and_nonfinite_or_outside_points_fail_closed(self):
        result = fixture()
        row = result['pose_samples'][0]
        row['wall_alignment_diagnostics'] = {'inliers': 40, 'median_error_px': 4.2}
        self.assertIsNone(registered_points(row, result['video']))
        row.pop('wall_alignment_diagnostics')
        row['kpts_xy'][9] = [float('nan'), .3]
        self.assertIsNone(registered_points(row, result['video']))


if __name__ == '__main__':
    unittest.main()
