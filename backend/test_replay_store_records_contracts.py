"""Characterize record reads and cache behavior using isolated JSON jobs only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from core import climb_replay as replay


class ReplayStoreRecordsContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = replay.ClimbReplayStore(Path(self.temp.name))
        self.job = {
            'id': 'recorda', 'owner': 'alice', 'status': 'succeeded',
            'created_at': '2026-10-01T00:00:00Z', 'progress': 10,
            'label': '构造记录', 'result': None,
            'media': {'source_video': {'status': 'available', 'note': '原片'}},
            'metadata': {'nested': [1]},
        }
        self.write(self.job)

    def write(self, job):
        replay._atomic_json(self.store._path(job['id']), job)

    def assert_not_found(self, call):
        with self.assertRaises(HTTPException) as failure:
            call()
        self.assertEqual(failure.exception.status_code, 404)
        self.assertEqual(failure.exception.detail, '未找到复盘任务')

    def test_cold_and_warm_public_snapshots_isolate_nested_json(self):
        with patch.object(self.store, '_read', wraps=self.store._read) as read:
            first = self.store.get('recorda', 'alice')
            first['media']['source_video']['note'] = 'caller changed cold result'
            first['metadata']['nested'].append(2)
            second = self.store.get('recorda', 'alice')
            self.assertEqual(second['media']['source_video']['note'], '原片')
            self.assertEqual(second['metadata']['nested'], [1])
            second['media']['source_video']['status'] = 'deleted'
            second['metadata']['nested'].append(3)
            third = self.store.get('recorda', 'alice')
            self.assertEqual(third['media'], self.job['media'])
            self.assertEqual(third['metadata'], self.job['metadata'])
            self.assertEqual(read.call_count, 1)
        self.assertEqual(json.loads(self.store._path('recorda').read_text(encoding='utf-8')), self.job)

    def test_private_reads_stay_fresh_and_independent_of_public_cache(self):
        with patch.object(self.store, '_read', wraps=self.store._read) as read:
            self.store.get('recorda', 'alice')
            first = self.store.get('recorda', 'alice', private=True)
            first['metadata']['nested'].append('private caller mutation')
            self.assertEqual(self.store.get('recorda', 'alice', private=True)['metadata']['nested'], [1])
            self.assertEqual(self.store.get('recorda', 'alice')['metadata']['nested'], [1])
            self.assertEqual(read.call_count, 3)
            self.write({**self.job, 'progress': 99})
            self.assertEqual(self.store.get('recorda', 'alice', private=True)['progress'], 99)
            self.assertEqual(read.call_count, 4)

    def test_wrong_owner_remains_not_found_for_cold_hot_and_private_reads(self):
        self.assert_not_found(lambda: self.store.get('recorda', 'other'))
        self.assert_not_found(lambda: self.store.get('recorda', 'other', private=True))
        self.store.get('recorda', 'alice')
        self.assert_not_found(lambda: self.store.get('recorda', 'other'))
        self.assert_not_found(lambda: self.store.get('recorda', 'other', private=True))
        self.assertEqual(self.store.get('recorda', private=True)['owner'], 'alice')

    def test_invalid_id_missing_record_and_malformed_json_keep_not_found_detail(self):
        for job_id in ('', '../recorda', 'record-a', 'record_a', 'record/a', 'absent'):
            for private in (False, True):
                with self.subTest(job_id=job_id, private=private):
                    self.assert_not_found(lambda: self.store.get(job_id, 'alice', private=private))
        self.store._path('recorda').write_text('{', encoding='utf-8')
        self.assert_not_found(lambda: self.store.get('recorda', 'alice'))
        self.assert_not_found(lambda: self.store.get('recorda', 'alice', private=True))

    def test_list_sorts_owned_records_skips_not_found_and_propagates_other_errors(self):
        self.write({**self.job, 'id': 'recordb', 'created_at': '2026-10-03T00:00:00Z'})
        self.write({**self.job, 'id': 'recordc', 'created_at': '2026-10-02T00:00:00Z'})
        self.write({**self.job, 'id': 'foreign', 'owner': 'other', 'created_at': '2026-10-04T00:00:00Z'})
        broken = self.store._path('broken')
        broken.parent.mkdir()
        broken.write_text('{', encoding='utf-8')
        self.assertEqual([job['id'] for job in self.store.list('alice')], ['recordb', 'recordc', 'recorda'])
        original_get = self.store.get

        def blocked(job_id, owner):
            if job_id == 'recordb':
                raise HTTPException(409, 'constructed busy record')
            return original_get(job_id, owner)

        with patch.object(self.store, 'get', side_effect=blocked):
            with self.assertRaises(HTTPException) as failure:
                self.store.list('alice')
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(failure.exception.detail, 'constructed busy record')

    def test_cache_hits_touch_lru_and_limits_count_utf8_bytes(self):
        self.store._public_cache_entries = 2
        for ident in ('recordb', 'recordc', 'recordd'):
            self.write({**self.job, 'id': ident})
        self.store.get('recorda', 'alice')
        self.store.get('recordb', 'alice')
        self.store.get('recorda', 'alice')
        self.store.get('recordc', 'alice')
        self.assertEqual(list(self.store._public_cache), ['recorda', 'recordc'])
        encoded = self.store._public_cache['recorda'][2]
        self.assertGreater(len(encoded), len(encoded.decode('utf-8')))
        self.assertEqual(self.store._public_cache_bytes, sum(len(item[2]) for item in self.store._public_cache.values()))
        self.store._public_cache_limit = len(encoded)
        self.store.get('recordd', 'alice')
        self.assertEqual(list(self.store._public_cache), ['recordd'])
        self.assertEqual(self.store._public_cache_bytes, len(encoded))
        self.store._public_cache_limit = len(encoded) - 1
        self.write({**self.job, 'id': 'recordd'})
        self.store.get('recordd', 'alice')
        self.assertEqual(list(self.store._public_cache), [])
        self.assertEqual(self.store._public_cache_bytes, 0)

    def test_public_projection_runs_while_the_store_lock_is_held(self):
        entered, release = threading.Event(), threading.Event()
        failures, results = [], []
        original_public = self.store._public

        def blocked_projection(job):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('constructed projection was not released')
            return original_public(job)

        def read_job():
            try:
                results.append(self.store.get('recorda', 'alice'))
            except BaseException as error:
                failures.append(error)

        with patch.object(self.store, '_public', side_effect=blocked_projection):
            worker = threading.Thread(target=read_job, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                acquired = self.store._lock.acquire(blocking=False)
                if acquired:
                    self.store._lock.release()
                self.assertFalse(acquired, 'another reader must not enter while a snapshot is projected')
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results[0]['id'], 'recorda')


if __name__ == '__main__':
    unittest.main()
