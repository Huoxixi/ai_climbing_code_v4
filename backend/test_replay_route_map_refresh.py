import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from core.climb_replay import ClimbReplayStore, VideoInfo


class ReplayRouteMapRefreshTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source.mp4'
        source.write_bytes(b'original-source')
        store = ClimbReplayStore(root / 'store')
        job = store.create(owner='alice', route_id=None, route_color='黄色', source=source,
                           original_name='clip.mp4', info=VideoInfo(96, 64, 4, 8, 2, source.stat().st_size),
                           consent={'event': 'granted'}, retention_mode='keep_private_original')
        directory = store._path(job['id']).parent
        old = directory / ('overlay-visual-' + 'a'*32 + '.webm')
        old.write_bytes(b'previous-reviewed-video')
        media = copy.deepcopy(job['media'])
        media['reviewed_overlay_video'] = {'status': 'available', 'storage_name': old.name,
                                          'checksum_sha256': 'previous', 'delete_at': None}
        result = {'holds': [{'id': 1, 'bbox': [.1, .1, .2, .2]}],
                  'pose_samples': [{'observed': True, 'source_frame_id': 0}],
                  'attempt': {'contacts': [{'limb': 'left_hand', 'hold_id': 1}]},
                  'analysis': {'usage': {'actual_requests': 3}}, 'overlay': {'layout': 'old'}}
        store.update(job['id'], status='succeeded', result=result, media=media)
        return store, job['id'], old, result

    def render(self, source, target, result, **options):
        self.assertFalse(options['cancelled']())
        target.write_bytes(b'new-current-hold-video')
        return {'layout': 'split_route_map_actions_v8', 'touch_markers': 'none'}

    def test_refresh_reuses_evidence_preserves_old_video_and_cleanup_history(self):
        with tempfile.TemporaryDirectory() as temp:
            store, job_id, old, original = self.fixture(Path(temp))
            with patch('core.climb_replay.render_replay_overlay_video', side_effect=self.render), \
                 patch('core.climb_replay.AliyunReplayAnalyzer._request_pose', side_effect=AssertionError('paid request')), \
                 patch('core.climb_replay.AliyunReplayAnalyzer._contacts', side_effect=AssertionError('contact recomputation')):
                updated = store.refresh_route_map(job_id, 'alice')
            for key in ('holds', 'pose_samples', 'attempt', 'analysis'):
                self.assertEqual(updated['result'][key], original[key])
            self.assertEqual(updated['result']['overlay']['layout'], 'split_route_map_actions_v8')
            path, _ = store.media_file(job_id, 'alice', 'reviewed_overlay_video')
            self.assertEqual(path.read_bytes(), b'new-current-hold-video')
            self.assertNotEqual(path, old)
            store.cleanup_due_media()
            self.assertEqual(old.read_bytes(), b'previous-reviewed-video')
            self.assertNotIn('overlay_history', updated)
            self.assertEqual(len(store.get(job_id, private=True)['overlay_history']), 1)

    def test_failure_keeps_current_result_and_media(self):
        with tempfile.TemporaryDirectory() as temp:
            store, job_id, old, original = self.fixture(Path(temp))
            def fail(source, target, result, **options):
                target.write_bytes(b'partial')
                raise RuntimeError('constructed render failure')
            with patch('core.climb_replay.render_replay_overlay_video', side_effect=fail):
                with self.assertRaises(RuntimeError):
                    store.refresh_route_map(job_id, 'alice')
            self.assertEqual(store.get(job_id)['result'], original)
            self.assertEqual(old.read_bytes(), b'previous-reviewed-video')
            self.assertEqual(list(old.parent.glob('overlay-map-*.webm')), [])
            self.assertNotIn(job_id, store._active_hold_renders)

    def test_ownership_missing_source_and_active_tasks_block_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            store, job_id, old, original = self.fixture(Path(temp))
            with patch('core.climb_replay.render_replay_overlay_video') as render:
                with self.assertRaises(HTTPException) as denied:
                    store.refresh_route_map(job_id, 'bob')
                self.assertEqual(denied.exception.status_code, 404)
                store.update(job_id, action_export={'status': 'running'})
                with self.assertRaises(HTTPException):
                    store.refresh_route_map(job_id, 'alice')
                store.update(job_id, action_export=None)
                media = store.get(job_id)['media']
                media['source_video']['status'] = 'deleted'
                store.update(job_id, media=media)
                with self.assertRaises(HTTPException):
                    store.refresh_route_map(job_id, 'alice')
                render.assert_not_called()
