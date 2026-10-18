import copy
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from core.replay_actions import organize
from core.replay_motion_summary import prepare_motion_evidence, enrich_motion_summary
from test_replay_action_trajectory import fixture


def translate(result, offsets):
    for row, delta in zip(result['pose_samples'], offsets):
        row['kpts_xy'] = (np.asarray(row['kpts_xy']) + delta).tolist()
    return result


class DisplacementSegmentationTests(unittest.TestCase):
    def test_ending_includes_whole_body_settling_not_just_hand_stop(self):
        result=fixture(25)
        for i,row in enumerate(result['pose_samples']):
            row['kpts_xy'][9][1]-=min(i,6)*.018
            row['kpts_xy'][7][1]-=min(i,6)*.009
            row['kpts_xy'][13][0]+=max(0,min(i-5,7))*.004
        groups=organize({'result':result})['groups']
        self.assertEqual(len(groups),1)
        self.assertTrue(groups[0]['ending_stable'])
        self.assertGreaterEqual(groups[0]['end_seconds'],3.5)

    def test_video_ending_mid_motion_is_not_a_complete_commentary_clip(self):
        result=translate(fixture(17),[[i*.006,0] for i in range(17)])
        groups=organize({'result':result})['groups']
        self.assertEqual(len(groups),1)
        self.assertFalse(groups[0]['ending_stable'])

    def test_contact_labels_and_long_clip_do_not_split_continuous_motion(self):
        result = translate(fixture(33), [[i * .003, 0] for i in range(33)])
        result['attempt'] = {'segments': [
            {'start_time_seconds': at-1, 'end_time_seconds': at,
             'source_hold_id': 1, 'target_hold_id': 2, 'landing_stabilization_seconds': .5}
            for at in (2, 3, 5, 6)]}
        self.assertEqual(len(organize({'result': result})['groups']), 1)

    def test_short_pause_and_small_tail_adjustment_remain_one_action(self):
        offsets = [[min(i, 7) * .008 + max(0, min(i-9, 4)) * .008, 0]
                   for i in range(21)]
        result = translate(fixture(21), offsets)
        self.assertEqual(len(organize({'result': result})['groups']), 1)

    def test_settled_position_followed_by_clear_vertical_change_is_another_action(self):
        offsets = [[min(i, 8) * .01, -max(0, min(i-16, 8)) * .01]
                   for i in range(33)]
        groups = organize({'result': translate(fixture(33), offsets)})['groups']
        self.assertEqual(len(groups), 2)
        self.assertLess(groups[0]['end_seconds'], groups[1]['start_seconds'])

    def test_small_jitter_or_contact_change_without_displacement_creates_no_action(self):
        result = translate(fixture(25), [[(-1)**i * .012, 0] for i in range(25)])
        result['attempt'] = {'segments': [{'start_time_seconds': 1, 'end_time_seconds': 2,
            'source_hold_id': 1, 'target_hold_id': 2, 'limb': 'left_hand'}]}
        self.assertEqual(organize({'result': result})['groups'], [])

    def test_one_frame_jump_and_missing_observations_are_not_motion(self):
        result = fixture(25)
        result['pose_samples'][8]['kpts_xy'][9][0] += .2
        self.assertEqual(organize({'result': result})['groups'], [])
        for row in result['pose_samples']:
            row['wall_alignment'] = 'unknown'
        self.assertEqual(organize({'result': result})['groups'], [])

    def test_active_hand_is_located_without_body_translation(self):
        result = fixture(13)
        for i, row in enumerate(result['pose_samples']):
            row['kpts_xy'][9][1] -= min(i, 8) * .012
            row['kpts_xy'][7][1] -= min(i, 8) * .006
        groups = organize({'result': result})['groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['candidate_limbs'], ['left_hand'])

    def test_legacy_wall_recovery_restores_rhythm_without_changing_saved_poses(self):
        result = translate(fixture(13), [[min(i, 5) * .013, 0] for i in range(13)])
        result['video'].update(width=320, height=320, fps=4, frame_count=13)
        for i, row in enumerate(result['pose_samples']):
            row['source_frame_id'] = i
            row.pop('wall_reference_transform')
        original = copy.deepcopy(result)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'constructed.mp4'
            pixels = np.random.default_rng(42).integers(0, 256, (320, 320, 3), dtype=np.uint8)
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 4, (320, 320))
            for _ in range(13):
                writer.write(pixels)
            writer.release()
            recovered = prepare_motion_evidence(result, source)
        summary = enrich_motion_summary(organize({'result': recovered}))['motion_summary']
        self.assertGreater(summary['coverage'], .95)
        self.assertGreater(summary['totals'][0]['seconds'], 0)
        self.assertGreater(summary['totals'][1]['seconds'], 0)
        self.assertEqual(result, original)


if __name__ == '__main__':
    unittest.main()
