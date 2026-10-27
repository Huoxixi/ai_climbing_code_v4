"""Persistence effects before extraction; every record is synthetic and temporary."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import climb_replay as replay


class ObservedLock:
    def __init__(self, events):
        self.events = events
        self.depth = 0

    def __enter__(self):
        self.depth += 1
        self.events.append('enter')

    def __exit__(self, *error):
        self.events.append('exit')
        self.depth -= 1


class ReplayJobRecordsContractsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = replay.ClimbReplayStore(Path(self.temp.name))
        self.job = dict(id='sample', owner='alice', status='succeeded', progress=0,
                        created_at='2026-10-26T00:00:00Z', updated_at='before', result=None)
        replay._atomic_json(self.store._path('sample'), self.job)

    def write_job(self, name, **values):
        job = {**self.job, 'id': name, **values}
        replay._atomic_json(self.store._path(name), job)
        return job

    def test_records_module_import_does_not_initialize_replay_jobs_or_services(self):
        script = (
            'import core.replay_job_records; import sys; '
            'assert "core.climb_replay" not in sys.modules; '
            'assert "core.replay_hold_editor" not in sys.modules'
        )
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_update_keeps_legacy_clock_commit_order_lock_and_return_identity(self):
        events = []
        lock = ObservedLock(events)
        self.store._lock = lock
        record = dict(self.job)
        path = self.store._path('sample')

        def read(job_id):
            self.assertEqual(lock.depth, 1)
            self.assertEqual(job_id, 'sample')
            events.append('read')
            return record

        def clock():
            self.assertEqual(lock.depth, 1)
            self.assertEqual(record['progress'], 25)
            events.append('clock')
            return 'fixed-clock'

        def locate(job_id):
            self.assertEqual(lock.depth, 1)
            self.assertEqual(record['updated_at'], 'fixed-clock')
            events.append('path')
            return path

        def commit(destination, payload):
            self.assertEqual(lock.depth, 1)
            self.assertEqual(destination, path)
            self.assertIs(payload, record)
            events.append('commit')

        with patch.object(self.store, '_read', side_effect=read), \
             patch.object(self.store, '_path', side_effect=locate), \
             patch.object(replay, 'utcnow', side_effect=clock), \
             patch.object(replay, '_atomic_json', side_effect=commit):
            result = self.store.update('sample', progress=25)
        self.assertIs(result, record)
        self.assertEqual(events, ['enter', 'read', 'clock', 'path', 'commit', 'exit'])
        self.assertEqual(lock.depth, 0)

    def test_update_propagates_commit_failure_and_releases_lock_without_changing_disk(self):
        events = []
        lock = ObservedLock(events)
        self.store._lock = lock
        failure = OSError('synthetic write failure')

        def fail_commit(path, job):
            self.assertEqual(lock.depth, 1)
            self.assertEqual(job['progress'], 25)
            self.assertEqual(job['updated_at'], 'fixed-clock')
            raise failure

        with patch.object(replay, 'utcnow', return_value='fixed-clock'), \
             patch.object(replay, '_atomic_json', side_effect=fail_commit):
            with self.assertRaises(OSError) as raised:
                self.store.update('sample', progress=25)
        self.assertIs(raised.exception, failure)
        self.assertEqual(lock.depth, 0)
        self.assertEqual(json.loads(self.store._path('sample').read_text('utf-8')), self.job)

    def test_old_visual_flag_replacement_invalidates_an_existing_public_snapshot(self):
        with patch.object(self.store, '_read', wraps=self.store._read) as read, \
             patch.object(self.store, '_public', wraps=self.store._public) as public:
            with patch.object(replay, 'replay_visual_enabled', return_value=False):
                first = self.store.get('sample', 'alice')
                self.assertEqual(self.store.get('sample', 'alice'), first)
            self.assertEqual((read.call_count, public.call_count), (1, 1))
            with patch.object(replay, 'replay_visual_enabled', return_value=True):
                self.assertEqual(self.store.get('sample', 'alice'), first)
            self.assertEqual((read.call_count, public.call_count), (2, 2))

    def test_projection_race_returns_observed_snapshot_without_caching_stale_bytes(self):
        project = self.store._public

        def project_then_replace(job):
            public = project(job)
            replay._atomic_json(self.store._path('sample'), {**job, 'progress': 12345})
            return public

        with patch.object(replay, 'replay_visual_enabled', return_value=False):
            with patch.object(self.store, '_public', side_effect=project_then_replace):
                self.assertEqual(self.store.get('sample', 'alice')['progress'], 0)
            self.assertNotIn('sample', self.store._public_cache)
            self.assertEqual(self.store._public_cache_bytes, 0)
            self.assertEqual(self.store.get('sample', 'alice')['progress'], 12345)

    def test_queued_scan_skips_bad_json_and_keeps_created_at_ascending(self):
        self.write_job('late', status='queued', created_at='2026-10-26T03:00:00Z')
        self.write_job('early', status='queued', created_at='2026-10-26T01:00:00Z')
        self.write_job('running', status='running', created_at='2026-10-26T00:00:00Z')
        broken = self.store._path('broken')
        broken.parent.mkdir()
        broken.write_text('{', encoding='utf-8')
        self.assertEqual(self.store.queued(), ['early', 'late'])

    def test_queued_scan_does_not_hide_valid_json_with_missing_job_id(self):
        path = self.store._path('incomplete')
        replay._atomic_json(path, dict(status='queued', created_at='2026-10-26T01:00:00Z'))
        with self.assertRaises(KeyError) as raised:
            self.store.queued()
        self.assertEqual(raised.exception.args, ('id',))

    def test_sha256_keeps_streamed_digest_for_more_than_one_read_chunk(self):
        payload = b'constructed-record-data' * 60000 + b'\0'
        path = self.store.root / 'digest.bin'
        path.write_bytes(payload)
        self.assertEqual(self.store._sha256(path), hashlib.sha256(payload).hexdigest())


if __name__ == '__main__':
    unittest.main()
