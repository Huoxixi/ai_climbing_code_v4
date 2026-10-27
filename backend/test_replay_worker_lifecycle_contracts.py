"""Deterministic worker lifecycle and failure policy, with no inference or services."""
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from core import climb_replay as replay


class ReplayWorkerLifecycleContracts(unittest.TestCase):
    def manager(self):
        manager = replay.ClimbReplayManager.__new__(replay.ClimbReplayManager)
        manager.store = SimpleNamespace(process_delete=Mock(), fail_deletion=Mock(),
            get=Mock(return_value={'status': 'queued'}), schedule_source_cleanup=Mock(), update=Mock())
        manager._queue = queue.Queue(maxsize=8)
        manager._queued = set()
        manager._queue_lock = threading.Lock()
        manager._stop = threading.Event()
        manager._refill_queue = Mock()
        manager._execute = Mock()
        manager._execute_visual = Mock()
        return manager

    def run_items(self, manager, *items):
        for item in items:
            manager._queued.add(item)
            manager._queue.put_nowait(item)
        manager._queue.put_nowait(None)
        manager._run()

    def test_worker_routes_actions_and_discards_marker_before_dispatch(self):
        manager = self.manager()
        events = []
        for action, callback in [('delete', manager.store.process_delete),
                                 ('visual', manager._execute_visual), ('analysis', manager._execute)]:
            callback.side_effect = lambda job, action=action: events.append((action, job, (action, job) in manager._queued))
        self.run_items(manager, ('delete', 'd'), ('visual', 'v'), ('analysis', 'a'), ('legacy-action', 'u'))
        self.assertEqual(events, [('delete', 'd', False), ('visual', 'v', False),
                                  ('analysis', 'a', False), ('analysis', 'u', False)])
        self.assertEqual(manager._queued, set())
        self.assertEqual(manager._refill_queue.call_count, 4)
        self.assertEqual(manager._queue.unfinished_tasks, 1)  # Sentinel has no task_done in the existing protocol.

    def test_worker_failure_keeps_safe_diagnostic_and_reads_legacy_clock_and_logger(self):
        manager = self.manager()
        manager._execute.side_effect = NameError('secret credentials /private/path', name='missing_symbol')
        with patch.object(replay, 'utcnow', return_value='late-clock') as clock, \
             patch.object(replay.logging, 'getLogger') as logger:
            self.run_items(manager, ('analysis', 'a'))
        clock.assert_called_once_with()
        logger.assert_called_once_with('core.climb_replay')
        fields = manager.store.update.call_args.kwargs
        self.assertEqual(fields['status'], 'failed')
        self.assertEqual(fields['finished_at'], 'late-clock')
        self.assertEqual(fields['error_code'], 'worker_failed')
        diagnostic = fields['worker_failure']
        self.assertEqual(diagnostic['exception_type'], 'NameError')
        self.assertEqual(diagnostic['identifier'], 'missing_symbol')
        self.assertGreater(len(diagnostic['frames']), 0)
        self.assertLessEqual(len(diagnostic['frames']), 8)
        for frame in diagnostic['frames']:
            self.assertEqual(set(frame), {'file', 'function', 'line'})
            self.assertEqual(frame['file'], Path(frame['file']).name)
            self.assertIsInstance(frame['line'], int)
        self.assertNotIn('secret credentials', json.dumps(diagnostic))
        self.assertNotIn('/private/path', str(logger.return_value.error.call_args))
        manager.store.get.assert_called_once_with('a', private=True)
        manager.store.schedule_source_cleanup.assert_called_once_with('a', outcome='failed')
        manager._refill_queue.assert_called_once_with()

    def test_delete_failure_records_only_deletion_failure_and_refills(self):
        manager = self.manager()
        manager.store.process_delete.side_effect = ValueError('sensitive')
        with patch.object(replay.logging, 'getLogger'):
            self.run_items(manager, ('delete', 'd'))
        manager.store.fail_deletion.assert_called_once_with('d')
        manager.store.get.assert_not_called()
        manager.store.update.assert_not_called()
        manager._refill_queue.assert_called_once_with()

    def test_failure_does_not_overwrite_completed_job_and_ignores_nonidentifier_name(self):
        manager = self.manager()
        error = NameError('private', name='not.an.identifier')
        manager._execute_visual.side_effect = error
        manager.store.get.return_value = {'status': 'succeeded'}
        with patch.object(replay.logging, 'getLogger') as logger:
            self.run_items(manager, ('visual', 'v'))
        manager.store.schedule_source_cleanup.assert_not_called()
        manager.store.update.assert_not_called()
        diagnostic = json.loads(logger.return_value.error.call_args.args[1])
        self.assertNotIn('identifier', diagnostic)
        manager._refill_queue.assert_called_once_with()

    def test_failure_while_reading_failed_job_is_contained_and_worker_continues(self):
        manager = self.manager()
        manager._execute.side_effect = [RuntimeError('failed'), None]
        manager.store.get.side_effect = RuntimeError('record unavailable')
        with patch.object(replay.logging, 'getLogger'):
            self.run_items(manager, ('analysis', 'a'), ('analysis', 'b'))
        self.assertEqual(manager._execute.call_count, 2)
        self.assertEqual(manager._refill_queue.call_count, 2)
        manager.store.update.assert_not_called()

    def test_refill_error_propagates_after_task_done(self):
        manager = self.manager()
        manager._refill_queue.side_effect = RuntimeError('refill failed')
        manager._queue.put_nowait(('analysis', 'a'))
        with self.assertRaisesRegex(RuntimeError, 'refill failed'):
            manager._run()
        self.assertEqual(manager._queue.unfinished_tasks, 0)

    def test_failure_record_error_propagates_after_task_done_and_refill(self):
        manager = self.manager()
        manager.store.process_delete.side_effect = RuntimeError('delete failed')
        manager.store.fail_deletion.side_effect = RuntimeError('write failed')
        manager._queue.put_nowait(('delete', 'd'))
        manager._refill_queue.side_effect = lambda: self.assertEqual(manager._queue.unfinished_tasks, 0)
        with patch.object(replay.logging, 'getLogger'):
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                manager._run()
        manager._refill_queue.assert_called_once_with()

    def test_stop_flag_prevents_another_queue_get(self):
        manager = self.manager()
        manager._stop.set()
        manager._queue.put_nowait(('analysis', 'a'))
        manager._run()
        manager._execute.assert_not_called()
        self.assertEqual(manager._queue.qsize(), 1)
        manager._refill_queue.assert_not_called()

    def test_initialization_order_targets_and_recovery_order_remain_stable(self):
        events = []
        created = []
        class DormantThread:
            def __init__(self, *, target, name, daemon):
                self.target, self.name, self.daemon = target, name, daemon
                created.append(self)
                events.append(('thread', name))
            def start(self):
                events.append(('start', self.name))
        with tempfile.TemporaryDirectory() as directory:
            store = SimpleNamespace(root=Path(directory),
                cleanup_due_media=Mock(side_effect=lambda: events.append('cleanup')),
                pending_deletions=Mock(side_effect=lambda: events.append('deletions') or ['d']),
                queued=Mock(side_effect=lambda: events.append('queued') or ['a']))
            with patch.object(replay.threading, 'Thread', DormantThread):
                manager = replay.ClimbReplayManager(store, object(), cleanup_interval_seconds=.1)
        self.assertEqual(events, ['cleanup', ('thread', 'climb-replay-worker'),
            ('thread', 'climb-replay-cleanup'), ('start', 'climb-replay-worker'),
            ('start', 'climb-replay-cleanup'), 'deletions', 'queued'])
        self.assertEqual([thread.target for thread in created], [manager._run, manager._cleanup_loop])
        self.assertTrue(all(thread.daemon for thread in created))
        self.assertEqual(manager._cleanup_interval_seconds, 1.0)
        self.assertEqual(manager._queue.get_nowait(), ('delete', 'd'))
        self.assertEqual(manager._queue.get_nowait(), ('analysis', 'a'))

    def test_close_preserves_service_order_stop_sentinel_and_join_timeouts(self):
        manager = self.manager()
        events = []
        for name in ('prepared_previews', 'action_manager', 'template_manager', 'coaching_manager'):
            setattr(manager.store, name, SimpleNamespace(close=Mock(side_effect=lambda name=name: events.append(name))))
        manager._stop = SimpleNamespace(set=lambda: events.append('stop'))
        manager._thread = SimpleNamespace(join=lambda **kw: events.append(('worker', kw)))
        manager._cleanup_thread = SimpleNamespace(join=lambda **kw: events.append(('cleanup', kw)))
        manager.close()
        self.assertEqual(events, ['prepared_previews', 'action_manager', 'template_manager', 'coaching_manager',
                                 'stop', ('worker', {'timeout': 2}), ('cleanup', {'timeout': 2})])
        self.assertIsNone(manager._queue.get_nowait())

    def test_close_with_full_queue_preserves_pending_items_and_still_joins(self):
        manager = self.manager()
        for index in range(8):
            manager._queue.put_nowait(('analysis', str(index)))
        manager._thread, manager._cleanup_thread = SimpleNamespace(join=Mock()), SimpleNamespace(join=Mock())
        manager.close()
        self.assertTrue(manager._stop.is_set())
        self.assertEqual(manager._queue.qsize(), 8)
        manager._thread.join.assert_called_once_with(timeout=2)
        manager._cleanup_thread.join.assert_called_once_with(timeout=2)

    def test_cleanup_loop_waits_and_recovers_after_one_cleanup_error(self):
        manager = self.manager()
        manager._cleanup_interval_seconds = 7
        manager._stop = SimpleNamespace(wait=Mock(side_effect=[False, False, True]))
        manager.store.cleanup_due_media = Mock(side_effect=[RuntimeError('legacy malformed'), None])
        manager._cleanup_loop()
        self.assertEqual(manager._stop.wait.call_args_list, [call(7)] * 3)
        self.assertEqual(manager.store.cleanup_due_media.call_count, 2)


if __name__ == '__main__':
    unittest.main()
