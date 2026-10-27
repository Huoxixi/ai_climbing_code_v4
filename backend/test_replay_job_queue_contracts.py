"""Legacy queue admission/recovery with constructed JSON and no worker execution."""
from pathlib import Path
import queue
import tempfile
import threading
import unittest

from fastapi import HTTPException

from core import climb_replay as replay


class ReplayJobQueueContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = replay.ClimbReplayStore(Path(self.temp.name))
        # Avoid constructing or starting either actual manager thread.
        self.manager = replay.ClimbReplayManager.__new__(replay.ClimbReplayManager)
        self.manager.store = self.store
        self.manager._queue = queue.Queue(maxsize=8)
        self.manager._queued = set()
        self.manager._queue_lock = threading.Lock()
        self.manager._stop = threading.Event()

    def write_job(self, ident, **changes):
        value = {'id': ident, 'status': 'succeeded', 'created_at': '2026-10-27T00:00:00Z'}
        value.update(changes)
        replay._atomic_json(self.store._path(ident), value)
        return value

    def drain(self):
        items = []
        while True:
            try:
                item = self.manager._queue.get_nowait()
            except queue.Empty:
                return items
            items.append(item)
            self.manager._queue.task_done()

    def test_concurrent_duplicates_share_action_job_key_but_distinct_actions_remain(self):
        start, errors = threading.Event(), []

        def enqueue(action):
            start.wait()
            try:
                action('samejob')
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=enqueue, args=(action,), daemon=True)
                   for action in (self.manager.enqueue, self.manager.enqueue_delete, self.manager.enqueue_visual)
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(1)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        expected = {('analysis', 'samejob'), ('delete', 'samejob'), ('visual', 'samejob')}
        self.assertEqual(self.manager._queued, expected)
        self.assertEqual(set(self.drain()), expected)

    def test_full_queue_does_not_erase_durable_work_and_refill_recovers_it(self):
        for index in range(9):
            self.write_job(f'job{index}', status='queued', created_at=f'2026-10-27T00:00:0{index}Z')
            self.manager.enqueue(f'job{index}')
        self.assertEqual(self.manager._queue.qsize(), 8)
        self.assertNotIn(('analysis', 'job8'), self.manager._queued)
        self.assertIn('job8', self.store.queued())
        first = self.manager._queue.get_nowait()
        self.manager._queued.discard(first)
        self.manager._queue.task_done()
        self.store.update(first[1], status='succeeded')
        self.manager._refill_queue()
        items = self.drain()
        self.assertEqual(len(items), 8)
        self.assertEqual(items.count(('analysis', 'job8')), 1)
        self.assertEqual(self.store._read('job8')['status'], 'queued')

    def test_refill_preserves_delete_analysis_visual_priority_and_skips_bad_json(self):
        replay._atomic_json(self.store._deletion_path('deleteone'), {'job_id': 'deleteone', 'state': 'queued'})
        self.write_job('late', status='queued', created_at='2026-10-27T00:02:00Z')
        self.write_job('early', status='queued', created_at='2026-10-27T00:01:00Z')
        self.write_job('visual', result={'visual_replay': {'status': 'queued'}})
        broken = self.store._path('broken')
        broken.parent.mkdir()
        broken.write_text('{', encoding='utf-8')
        self.manager._refill_queue()
        self.assertEqual(self.drain(), [('delete', 'deleteone'), ('analysis', 'early'),
                                        ('analysis', 'late'), ('visual', 'visual')])

    def test_refill_visual_qualification_keeps_distinct_analysis_and_visual_actions(self):
        self.write_job('both', status='queued', result={'visual_replay': {'status': 'queued'}})
        self.write_job('visualonly', result={'visual_replay': {'status': 'queued'}})
        self.write_job('runningvisual', result={'visual_replay': {'status': 'running'}})
        self.write_job('failedvisual', result={'visual_replay': {'status': 'failed'}})
        self.write_job('complete')
        self.manager._refill_queue()
        self.assertEqual(set(self.drain()), {('analysis', 'both'), ('visual', 'both'),
                                            ('visual', 'visualonly')})

    def test_capacity_counts_durable_pending_jobs_once_not_memory_queue_size(self):
        for index in range(5):
            self.write_job(f'analysis{index}', status='queued' if index < 4 else 'running',
                           result={'visual_replay': {'status': 'queued'}} if index == 0 else None)
        self.write_job('visualqueued', result={'visual_replay': {'status': 'queued'}})
        self.write_job('visualrunning', result={'visual_replay': {'status': 'running'}})
        self.write_job('failed', status='failed')
        broken = self.store._path('broken')
        broken.parent.mkdir()
        broken.write_text('{', encoding='utf-8')
        for index in range(8):
            self.manager.enqueue(f'memoryonly{index}')
        self.manager.ensure_capacity()  # Seven durable pending jobs, despite eight memory items.
        self.write_job('eighth', status='running')
        with self.assertRaises(HTTPException) as failure:
            self.manager.ensure_capacity()
        self.assertEqual(failure.exception.status_code, 429)
        self.assertEqual(failure.exception.detail, '复盘处理队列已满，请稍后再试')
        self.write_job('eighth')
        self.manager.ensure_capacity()

    def test_valid_json_with_invalid_visual_shape_keeps_legacy_attribute_error(self):
        self.write_job('legacy', result={'visual_replay': None})
        with self.assertRaises(AttributeError):
            self.manager.ensure_capacity()
        with self.assertRaises(AttributeError):
            self.manager._refill_queue()

    def test_queued_visual_without_id_keeps_legacy_key_error_and_no_partial_admission(self):
        self.write_job('analysis', status='queued')
        replay._atomic_json(self.store._path('legacy'), {
            'status': 'succeeded', 'created_at': '2026-10-27T00:00:00Z',
            'result': {'visual_replay': {'status': 'queued'}},
        })
        with self.assertRaises(KeyError) as failure:
            self.manager._refill_queue()
        self.assertEqual(failure.exception.args, ('id',))
        self.assertTrue(self.manager._queue.empty())
        self.assertEqual(self.manager._queued, set())

    def test_stop_flag_preserves_legacy_nonblocking_enqueue_admission(self):
        # This records existing behavior; adding a closed-service rejection is
        # a separate behavior change, not part of moving queue methods.
        self.manager._stop.set()
        self.manager.enqueue('afterstop')
        self.assertEqual(self.drain(), [('analysis', 'afterstop')])
        self.assertIn(('analysis', 'afterstop'), self.manager._queued)


if __name__ == '__main__':
    unittest.main()
