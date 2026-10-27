"""Protect existing replay input contracts and drawing during module extraction."""
import copy
import dataclasses
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from core import climb_replay as replay


CONTRACT_MODELS = (
    'ReplayColorSample', 'ReplayUploadCreate', 'ReplayRetryCreate',
    'ReplayHoldsConfirmation', 'ReplayComparisonCreate', 'ReplaySegmentReview',
    'ReplayHoldPoint',
)
SCHEMA_BASELINE = Path(__file__).parent / 'tests/fixtures/replay-input-contracts.json'


class ReplayFoundationsCharacterizationTests(unittest.TestCase):
    def test_existing_input_json_schemas_remain_compatible(self):
        expected = json.loads(SCHEMA_BASELINE.read_text(encoding='utf-8'))
        actual = {name: getattr(replay, name).model_json_schema() for name in CONTRACT_MODELS}
        self.assertEqual(actual, expected)

    def test_upload_defaults_and_extra_field_rejection(self):
        payload = dict(filename='clip.mov', content_type='video/quicktime', size_bytes=123,
                       consent_version='existing-consent', consent_granted=True)
        self.assertEqual(replay.ReplayUploadCreate(**payload).model_dump(), {
            **payload, 'skip_holds': False, 'route_id': '', 'route_color': '',
            'retention_mode': 'keep_private_original', 'trim_start_seconds': 0,
            'trim_end_seconds': None, 'route_color_sample': None,
        })
        with self.assertRaises(ValidationError) as error:
            replay.ReplayUploadCreate(**payload, unexpected=True)
        self.assertEqual(error.exception.errors()[0]['type'], 'extra_forbidden')

    def test_retry_sampling_and_focus_window_validation_are_preserved(self):
        retry = replay.ReplayRetryCreate(consent_version='existing', consent_granted=True)
        self.assertEqual(retry.model_dump(), {
            'skip_holds': False, 'consent_version': 'existing', 'consent_granted': True,
            'pose_fps': None, 'focus_windows': [],
        })
        for fps in (0, 5, 30):
            with self.subTest(fps=fps), self.assertRaises(ValidationError):
                replay.ReplayRetryCreate(consent_version='existing', consent_granted=True, pose_fps=fps)

    def test_color_sample_forms_and_error_text_are_preserved(self):
        sample = dict(source='video', hex='#00aAFF', rgb=[0, 170, 255],
                      point_xy=[0.25, 0.75], time_seconds=2.5)
        expected = replay.ReplayColorSample(**sample).model_dump()
        for value in (sample, json.dumps(sample), replay.ReplayColorSample(**sample)):
            self.assertEqual(replay.parse_color_sample(value), expected)
        for value in (None, ''):
            self.assertIsNone(replay.parse_color_sample(value))
        for value in ('{', {**sample, 'rgb': [-1, 0, 0]},
                      {**sample, 'time_seconds': None}, {**sample, 'point_xy': [float('nan'), 0]}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^视频取色样本无效，请重新取色$'):
                replay.parse_color_sample(value)

    def test_point_and_region_boundaries_keep_existing_errors(self):
        point = dict(point_xy=[0, 1], time_seconds=0)
        self.assertEqual(replay.ReplayHoldPoint(**point).point_xy, [0, 1])
        for values in ([-0.01, 0], [float('inf'), 0], [0, 1.01]):
            with self.subTest(point=values), self.assertRaisesRegex(ValidationError, '补点位置必须位于视频画面内'):
                replay.ReplayHoldPoint(**{**point, 'point_xy': values})
        for region in ([0, 0, .01, .1], [0, 0, .36, .1], [.1, .1, 0, 0]):
            with self.subTest(region=region), self.assertRaisesRegex(ValidationError, '请框出画面中单个岩点的大概范围'):
                replay.ReplayHoldPoint(**point, region_xyxy=region)

    def test_video_metadata_and_limit_defaults_are_unchanged(self):
        self.assertEqual(dataclasses.asdict(replay.VideoLimits()), {
            'max_bytes': 200*1024*1024, 'max_input_bytes': 500*1024*1024,
            'max_duration_seconds': 90.0, 'max_width': 1280, 'max_height': 720,
            'max_frames': 2700,
        })
        info = replay.VideoInfo(96, 64, 4.0, 8, 2.0, 100)
        self.assertEqual(dataclasses.asdict(info), dict(width=96, height=64, fps=4.0,
            frame_count=8, duration_seconds=2.0, size_bytes=100))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.width = 1

    def test_hold_review_precedence_and_copy_boundary_are_preserved(self):
        draft = {'holds': [{'id': 1, 'polygon': [[0, 0], [1, 0], [0, 1]]}],
                 'hold_evidence': {'reference_frame': 0}, 'hold_review_version': 2,
                 'private_path': 'must-not-be-copied'}
        job = {'hold_edit_draft': draft, 'result': {'holds': [2]}, 'hold_draft': {'holds': [3]}}
        self.assertIs(replay.hold_review_input(job), draft)
        self.assertEqual(replay.hold_review_input({**job, 'hold_edit_draft': {}}), job['result'])
        self.assertEqual(replay.hold_review_input({}), {})
        safe = replay.hold_geometry(draft)
        self.assertNotIn('private_path', safe)
        safe['holds'][0]['polygon'][0][0] = .9
        self.assertEqual(draft['holds'][0]['polygon'][0][0], 0)
        revision = replay.holds_revision(draft)
        self.assertEqual(replay.holds_revision(copy.deepcopy(draft)), revision)
        self.assertNotEqual(replay.holds_revision({**draft, 'hold_review_version': 3}), revision)
        self.assertEqual(replay.holds_revision({**draft, 'private_path': 'different'}), revision)

    def test_timeline_preserves_order_interpolation_confidence_and_edge_frames(self):
        samples = [
            {'source_frame_id': 3, 'observed': True, 'kpts_xy': [[.6, .8], [.5, .4]], 'kpts_score': [.9, .1]},
            {'source_frame_id': 1, 'observed': True, 'kpts_xy': [[.2, .4], [.1, .2]], 'kpts_score': [.5, .8]},
        ]
        before = copy.deepcopy(samples)
        timeline = replay.build_pose_render_timeline(samples, 6)
        self.assertEqual(timeline[2], {'source_frame_id': 2, 'kpts_xy': [[.4, .6], [.1, .2]],
            'kpts_score': [.7, .4], 'render_mode': 'interpolated',
            'left_sample_frame': 1, 'right_sample_frame': 3})
        self.assertEqual(timeline[0]['render_mode'], 'edge_hold')
        self.assertEqual(timeline[1]['render_mode'], 'measured')
        self.assertEqual(timeline[5]['source_frame_id'], 3)
        self.assertNotIn(6, timeline)
        self.assertEqual(samples, before)

    def test_timeline_missing_evidence_and_large_gap_are_not_filled(self):
        samples = [{'source_frame_id': frame, 'observed': frame in (0, 10),
                    'kpts_xy': [[.2, .4]], 'kpts_score': [.9]} for frame in range(11)]
        self.assertEqual(set(replay.build_pose_render_timeline(samples, 11)), {0, 10})
        self.assertEqual(replay.build_pose_render_timeline([], 10), {})
        self.assertEqual(replay.build_pose_render_timeline([{'source_frame_id': -1, 'observed': True}], 0), {})

    def test_label_fallback_draws_without_mutating_label_evidence(self):
        labels = [{'text': '左手', 'fallback': 'L', 'origin': [4, 20], 'size': 12}]
        before = copy.deepcopy(labels)
        frame = np.zeros((32, 64, 3), np.uint8)
        replay.draw_cjk_labels(frame, [])
        self.assertFalse(frame.any())
        # Patch the defining namespace, so this protects behavior across extraction.
        with patch.dict(replay.draw_cjk_labels.__globals__, {'_CJK_FONT_PATH': None}):
            replay.draw_cjk_labels(frame, labels)
        self.assertTrue(frame.any())
        self.assertEqual(labels, before)


if __name__ == '__main__':
    unittest.main()
