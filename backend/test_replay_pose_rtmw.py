"""Offline replacement regressions: evidence, gate, history and cloud isolation."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from fastapi import HTTPException

from core.climb_replay import (AliyunReplayAnalyzer, ClimbReplayStore, REPLAY_CONSENT_VERSION,
                               VideoInfo, build_pose_samples)
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer, MODEL


def fake_models(boxes=None, coordinates=None, scores=None):
    detector = Mock(return_value=np.array(boxes if boxes is not None else [[10, 10, 90, 90]]))
    pose = Mock(return_value=(np.array([coordinates if coordinates is not None else [[50., 50.]] * 133]),
                              np.array([scores if scores is not None else [.8] * 133])))
    for model in (pose, detector):
        model.session.get_providers.return_value = ['CPUExecutionProvider']
        model.fallback_reason = None
    pose.ort.__version__ = 'test'
    return pose, detector


class LocalPoseTests(unittest.TestCase):
    def test_partial_entry_does_not_lock_identity_before_full_body_arrives(self):
        analyzer = LocalRTMWReplayAnalyzer()
        scores = [.8] * 133
        scores[11] = .0
        analyzer._models = fake_models(boxes=[[16, 82, 33, 100]], scores=scores)
        image = np.zeros((100, 100, 3), np.uint8)
        self.assertIsNone(analyzer._pose_frame(image, frame_id=0, source_frame_id=42))
        self.assertEqual(analyzer.last_pose_failure, 'initial_body_incomplete')
        self.assertIsNone(analyzer._previous_box)
        analyzer._models = fake_models(boxes=[[0, 40, 60, 100]])
        record = analyzer._pose_frame(image, frame_id=1, source_frame_id=48)
        self.assertEqual(record['pose_evidence']['selection'], 'route_initial_selection')
        self.assertEqual(record['bbox_xywh'], [0., .4, .6, .6])

    def test_current_contract_is_local_with_zero_cloud_usage_and_no_credentials(self):
        with patch.dict('os.environ', {'ALIBABA_CLOUD_ACCESS_KEY_ID': 'irrelevant',
                                       'ALIBABA_CLOUD_ACCESS_KEY_SECRET': 'irrelevant'}):
            analyzer = LocalRTMWReplayAnalyzer(pose_fps=4)
        contract = analyzer.analysis_contract(VideoInfo(100, 100, 30, 60, 2, 100))
        self.assertEqual(contract['provider']['execution'], 'local')
        self.assertFalse(contract['provider']['uploads_frames'])
        self.assertEqual(contract['models']['pose']['name'], MODEL)
        self.assertEqual(contract['models']['pose']['keypoints'], 133)
        self.assertEqual(contract['usage']['actual_requests'], 0)
        self.assertEqual(contract['cost']['unit_price'], 0)
        self.assertFalse(hasattr(analyzer, 'access_key_id'))
        self.assertFalse(hasattr(analyzer, '_request_pose'))

    def test_133_points_preserved_but_contact_contract_keeps_17_and_no_upload_callback(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models()
        upload = Mock(side_effect=AssertionError('must not upload'))
        record = analyzer._pose_frame(np.zeros((100, 100, 3), np.uint8),
                                      frame_id=0, source_frame_id=15, before_request=upload)
        self.assertEqual(len(record['kpts_xy']), 17)
        self.assertEqual(record['kpts_xy'][9], [.5, .5])
        self.assertEqual(len(record['wholebody']['kpts_xy']), 133)
        samples = build_pose_samples([record], VideoInfo(100, 100, 30, 60, 2, 100))
        self.assertEqual(samples[0]['time_seconds'], .5)
        self.assertEqual(len(samples[0]['wholebody']['kpts_score']), 133)
        self.assertEqual(samples[0]['pose_evidence']['model'], MODEL)
        upload.assert_not_called()

    def test_outside_image_and_nonfinite_joints_cannot_drive_contacts(self):
        xy = np.full((133, 2), 50.)
        xy[9], xy[10], xy[17] = [-10, 50], [50, 101], [np.nan, 50]
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(coordinates=xy)
        record = analyzer._pose_frame(np.zeros((100, 100, 3), np.uint8), frame_id=0, source_frame_id=0)
        self.assertEqual(record['kpts_score'][9:11], [0., 0.])
        self.assertEqual(record['wholebody']['kpts_score'][17], 0.)
        json.dumps(record, allow_nan=False)

    def test_lost_track_does_not_switch_to_bystander_or_reuse_old_skeleton(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(boxes=[[5, 5, 45, 90]])
        image = np.zeros((100, 100, 3), np.uint8)
        self.assertIsNotNone(analyzer._pose_frame(image, frame_id=0, source_frame_id=0))
        analyzer._models[1].return_value = np.array([[70, 5, 98, 90]])
        self.assertIsNone(analyzer._pose_frame(image, frame_id=1, source_frame_id=8))
        analyzer._models[1].return_value = np.array([])
        self.assertIsNone(analyzer._pose_frame(image, frame_id=2, source_frame_id=15))

    def test_new_video_resets_tracking(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models()
        analyzer._previous_box = np.array([1, 2, 3, 4])
        analyzer._prepare_pose_run({'holds': [{'bbox': [.2, .3, .4, .5]}]})
        self.assertIsNone(analyzer._previous_box)
        self.assertEqual(analyzer._route_bounds, [.2, .3, .6000000000000001, .8])

    def test_first_bystander_outside_route_is_not_locked_before_climber_enters(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(boxes=[[0, 30, 15, 95]])
        analyzer._prepare_pose_run({'holds': [{'bbox': [.4, .2, .2, .5]},
                                             {'bbox': [0, 0, .1, 1], 'route_candidate': False}]})
        image = np.zeros((100, 100, 3), np.uint8)
        self.assertIsNone(analyzer._pose_frame(image, frame_id=0, source_frame_id=0))
        self.assertEqual(analyzer.last_pose_failure, 'person_outside_confirmed_route')
        self.assertIsNone(analyzer._previous_box)
        analyzer._models[1].return_value = np.array([[0, 30, 15, 95], [35, 20, 65, 90]])
        record = analyzer._pose_frame(image, frame_id=1, source_frame_id=3)
        self.assertEqual(record['bbox_xywh'], [.35, .2, .3, .7])

    def test_ambiguous_initial_people_are_not_resolved_by_array_order(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(boxes=[[20, 20, 45, 90], [55, 20, 80, 90]])
        self.assertIsNone(analyzer._pose_frame(np.zeros((100, 100, 3), np.uint8), frame_id=0, source_frame_id=0))
        self.assertEqual(analyzer.last_pose_failure, 'initial_person_ambiguous')

    def test_short_gap_and_box_displacement_requires_two_matching_real_frames(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(boxes=[[10, 10, 30, 90]])
        image = np.zeros((100, 100, 3), np.uint8)
        analyzer._pose_frame(image, frame_id=0, source_frame_id=0)
        analyzer._models[1].return_value = np.array([])
        self.assertIsNone(analyzer._pose_frame(image, frame_id=1, source_frame_id=3))
        analyzer._models[1].return_value = np.array([[40, 10, 60, 90]])
        self.assertIsNone(analyzer._pose_frame(image, frame_id=2, source_frame_id=6))
        self.assertEqual(analyzer.last_pose_failure, 'track_recovery_pending')
        record = analyzer._pose_frame(image, frame_id=3, source_frame_id=9)
        self.assertEqual(record['pose_evidence']['selection'], 'appearance_reacquired')
        self.assertEqual(analyzer._models[0].call_count, 2)

    def test_different_clothing_overlap_and_long_gaps_do_not_switch_identity(self):
        for source_frame, image in ((3, np.full((100,100,3), (0,255,0), np.uint8)),
                                    (90, np.zeros((100,100,3), np.uint8))):
            analyzer = LocalRTMWReplayAnalyzer()
            analyzer._models = fake_models(boxes=[[10,10,50,90]])
            analyzer._pose_frame(np.zeros((100,100,3), np.uint8), frame_id=0, source_frame_id=0)
            self.assertIsNone(analyzer._pose_frame(image, frame_id=1, source_frame_id=source_frame))
            self.assertEqual(analyzer.last_pose_failure, 'track_missing_or_ambiguous')

    def test_cached_detections_are_reselected_and_missing_decisions_are_not_poisoned(self):
        with tempfile.TemporaryDirectory() as directory:
            analyzer = LocalRTMWReplayAnalyzer()
            analyzer._models = fake_models(boxes=[[10,10,30,90]])
            analyzer.configure_cache(Path(directory)/'cache.json', {'source':'same'})
            image = np.zeros((100,100,3), np.uint8)
            analyzer._pose_frame(image, frame_id=0, source_frame_id=0)
            analyzer._models[1].return_value = np.array([[40,10,60,90]])
            self.assertIsNone(analyzer._pose_frame(image, frame_id=1, source_frame_id=9))
            self.assertEqual(analyzer.last_pose_failure, 'track_recovery_pending')
            # A new dense observation supplies the missing preceding evidence.
            analyzer._pose_frame(image, frame_id=2, source_frame_id=6)
            record = analyzer._pose_frame(image, frame_id=3, source_frame_id=9)
            self.assertIsNotNone(record)
            self.assertFalse(analyzer.last_pose_cache_hit)  # new pose, cached detector
            self.assertEqual(analyzer._models[1].call_count, 3)
            analyzer.flush_pose_cache()
            saved = json.loads((Path(directory)/'cache.json').read_text('utf-8'))
            self.assertEqual(saved['binding']['cache_schema'], 3)

    def test_legacy_selected_pose_cache_cannot_reuse_wrong_person(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache.json'
            path.write_text(json.dumps({'binding':{'source':'same'}, 'frames':{'0':{'record':None}}}))
            analyzer = LocalRTMWReplayAnalyzer()
            analyzer._models = fake_models()
            analyzer.configure_cache(path, {'source':'same'})
            self.assertIsNotNone(analyzer._pose_frame(np.zeros((100,100,3),np.uint8), frame_id=0,source_frame_id=0))
            self.assertFalse(analyzer.last_pose_cache_hit)

    def test_route_bounds_follow_camera_transform_before_initial_selection(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models(boxes=[[0,20,20,80], [60,20,80,80]])
        analyzer._prepare_pose_run({'holds':[{'bbox':[.1,.2,.1,.4]}]})
        # Source -> reference translates -55 px: the route is now on the right.
        matrix = np.array([[1,0,-55],[0,1,0],[0,0,1]],float)
        analyzer.set_person_reference_transform(matrix, [100,100], [100,100])
        record = analyzer._pose_frame(np.zeros((100,100,3),np.uint8), frame_id=0,source_frame_id=0)
        self.assertEqual(record['bbox_xywh'], [.6,.2,.2,.6])

    def test_unregistered_route_does_not_guess_initial_person(self):
        analyzer = LocalRTMWReplayAnalyzer()
        analyzer._models = fake_models()
        analyzer._prepare_pose_run({'holds':[{'bbox':[.4,.2,.2,.5]}]})
        for matrix in (None, np.zeros((3,3)), np.full((3,3),np.nan)):
            analyzer.set_person_reference_transform(matrix, [100,100], [100,100])
            self.assertIsNone(analyzer._pose_frame(np.zeros((100,100,3),np.uint8), frame_id=0,source_frame_id=0))
            self.assertEqual(analyzer.last_pose_failure, 'route_reference_unavailable')

    def test_nonfinite_raw_evidence_roundtrips_cache_without_creating_valid_joints(self):
        with tempfile.TemporaryDirectory() as directory:
            analyzer = LocalRTMWReplayAnalyzer()
            xy = np.full((133,2),50.); xy[9]=[np.nan,50]
            analyzer._models = fake_models(coordinates=xy)
            path = Path(directory)/'cache.json'
            analyzer.configure_cache(path, {'source':'same'})
            image = np.zeros((100,100,3),np.uint8)
            first = analyzer._pose_frame(image,frame_id=0,source_frame_id=0)
            analyzer.flush_pose_cache()
            json.loads(path.read_text('utf-8'),parse_constant=lambda s: self.fail(s))
            analyzer.configure_cache(path, {'source':'same'})
            analyzer._prepare_pose_run({'holds':[]})
            second = analyzer._pose_frame(image,frame_id=0,source_frame_id=0)
            self.assertEqual(first,second)
            self.assertEqual(second['kpts_score'][9],0)

    def test_missing_weights_fail_locally_without_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(AliyunReplayAnalyzer, '_client', side_effect=AssertionError('no cloud')):
            analyzer = LocalRTMWReplayAnalyzer(directory=Path(directory))
            with self.assertRaisesRegex(RuntimeError, 'RTMW 本地模型'):
                analyzer._load_models()

    def test_full_shared_pipeline_preserves_raw_evidence_and_reports_zero_billing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'constructed.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 4, (100, 100))
            if not writer.isOpened():
                self.skipTest('encoder unavailable')
            for _ in range(4):
                writer.write(np.full((100, 100, 3), 170, np.uint8))
            writer.release()
            analyzer = LocalRTMWReplayAnalyzer(pose_fps=4)
            analyzer._models = fake_models()
            holds = {'holds': [{'id': 1, 'bbox': [.4, .4, .2, .2]}],
                     'hold_candidates': [], 'hold_evidence': {'reference_frame': 0},
                     'models': {'holds': 'confirmed'}, 'route': {'color': '蓝色'}}
            snapshots = []
            def measured_alignment(*_):
                time.sleep(.006)
                return np.eye(3), {}
            with patch.object(AliyunReplayAnalyzer, '_request_pose', side_effect=AssertionError('no cloud')), \
                 patch.object(analyzer, 'detect_holds', side_effect=AssertionError('keep confirmed holds')), \
                 patch('core.climb_replay.align_to_reference', side_effect=measured_alignment), \
                 patch('core.climb_replay.render_replay_overlay_video', return_value={'test': True}):
                result = analyzer.analyze(source, route_color='蓝色',
                                          video_info=VideoInfo(100, 100, 4, 4, 1, source.stat().st_size),
                                          confirmed_holds=holds, progress=lambda *_: None,
                                          cancelled=lambda: False, telemetry=snapshots.append)
            self.assertEqual(result['models']['pose'], MODEL)
            self.assertEqual(result['holds'], holds['holds'])
            self.assertEqual(len(result['pose_samples']), 4)
            self.assertEqual(len(result['pose_samples'][0]['wholebody']['kpts_xy']), 133)
            self.assertEqual(result['analysis']['usage']['local_inferences'], 4)
            self.assertEqual(result['analysis']['usage']['actual_requests'], 0)
            self.assertEqual(result['analysis']['cost']['billable_requests_estimate'], 0)
            self.assertEqual(result['analysis']['cost']['estimated_amount'], 0)
            self.assertGreaterEqual(result['analysis']['timings_ms']['registration'], 20)

    def test_confirmation_gate_and_historical_result_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'constructed.mp4'
            source.write_bytes(b'constructed')
            store = ClimbReplayStore(root / 'store')
            job = store.create(owner='test', route_id=None, route_color='蓝色', source=source,
                               original_name='constructed.mp4', info=VideoInfo(100, 100, 4, 4, 1, 11),
                               consent={}, retention_mode='keep_private_original')
            history = {'models': {'pose': 'aliyun-viapi-bodyposture-2019-12-30'},
                       'pose_samples': [{'observed': True, 'kpts_xy': [[.5, .5]] * 17}],
                       'holds': [{'id': 1, 'bbox': [.1, .1, .2, .2]}]}
            store.update(job['id'], status='succeeded', result=copy.deepcopy(history))
            with self.assertRaises(HTTPException):
                store.start_analysis(job['id'], 'test', {'event': 'granted', 'version': REPLAY_CONSENT_VERSION})
            store.confirm_all_holds(job['id'], 'test', store.get(job['id'])['holds_revision'])
            queued = store.start_analysis(job['id'], 'test', {'event': 'granted', 'version': REPLAY_CONSENT_VERSION})
            self.assertIsNone(queued['paid_analysis_request'])
            self.assertEqual(store.get(job['id'], private=True)['analysis_request']['provider'], 'local-rtmw')
            self.assertEqual(queued['result'], history)
            archived = list((store.jobs / job['id']).glob('analysis-before-*.json'))
            self.assertEqual(len(archived), 1)
            self.assertEqual(json.loads(archived[0].read_text('utf-8'))['result'], history)


if __name__ == '__main__':
    unittest.main()
