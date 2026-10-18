import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from core.climb_replay import _atomic_json


class AtomicReceiptTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_real_windows_reader_releases_lock_during_commit(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            _atomic_json(path, {'status': 'queued'})
            handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)

            def release():
                time.sleep(0.15)
                kernel.CloseHandle(handle)

            reader = threading.Thread(target=release)
            reader.start()
            try:
                _atomic_json(path, {'status': 'running'})
            finally:
                reader.join()
            self.assertEqual(json.loads(path.read_text()), {'status': 'running'})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_transient_lock_retries_without_losing_previous_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            _atomic_json(path, {'status': 'queued'})
            replace = os.replace
            calls = []

            def briefly_locked(source, destination):
                calls.append(1)
                if len(calls) < 4:
                    self.assertEqual(json.loads(path.read_text()), {'status': 'queued'})
                    raise PermissionError('constructed file lock')
                return replace(source, destination)

            with patch('core.climb_replay.os.replace', side_effect=briefly_locked), patch('core.climb_replay.time.sleep'):
                _atomic_json(path, {'status': 'running'})
            self.assertEqual(len(calls), 4)
            self.assertEqual(json.loads(path.read_text()), {'status': 'running'})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_persistent_denial_is_bounded_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            _atomic_json(path, {'status': 'queued'})
            with patch('core.climb_replay.os.replace', side_effect=PermissionError('constructed denial')) as replace, patch('core.climb_replay.time.sleep') as sleep:
                with self.assertRaises(PermissionError):
                    _atomic_json(path, {'status': 'running'})
            self.assertEqual(replace.call_count, 8)
            self.assertLessEqual(sum(call.args[0] for call in sleep.call_args_list), 1.2)
            self.assertEqual(json.loads(path.read_text()), {'status': 'queued'})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_other_io_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            with patch('core.climb_replay.os.replace', side_effect=OSError('constructed disk failure')) as replace, patch('core.climb_replay.time.sleep') as sleep:
                with self.assertRaises(OSError):
                    _atomic_json(path, {'status': 'running'})
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
