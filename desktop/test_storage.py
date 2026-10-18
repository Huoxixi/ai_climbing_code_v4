import json
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from desktop.paths import resolve_paths, isolated_environment
from desktop.server import create_app
from desktop.storage import schedule_change, apply_pending_change, read_settings


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = resolve_paths(self.root / 'install', self.root / 'user')
        self.paths.prepare()
        self.target = self.root / '自选 存储'
        self.target.mkdir()
        ui = self.paths.install / 'frontend/dist'
        ui.mkdir(parents=True)
        (ui / 'index.html').write_text('ok')

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_copies_and_relocates_media_without_removing_original(self):
        media = self.paths.data / 'photo_routes/片段.mp4'
        media.parent.mkdir()
        media.write_bytes(b'constructed-video')
        record = media.parent / 'job.json'
        record.write_text(json.dumps({'input_path': str(media), 'nested': [media.as_posix()]}), 'utf-8')
        schedule_change(self.paths, self.target)
        self.assertFalse((self.target / 'photo_routes').exists())
        updated = apply_pending_change(self.paths)
        self.assertEqual(updated.data, self.target)
        self.assertEqual(media.read_bytes(), (self.target / 'photo_routes/片段.mp4').read_bytes())
        copied = json.loads((self.target / 'photo_routes/job.json').read_text('utf-8'))
        self.assertEqual(copied['input_path'], str(self.target / 'photo_routes/片段.mp4'))
        restarted = resolve_paths(self.paths.install, self.paths.user)
        self.assertEqual(restarted.data, self.target)
        self.assertEqual(restarted.config, self.paths.config)
        self.assertEqual(isolated_environment(restarted)['PHOTO_ROUTE_DATA_DIR'], str(self.target / 'photo_routes'))

    def test_existing_files_and_nested_or_private_targets_rejected(self):
        (self.target / 'precious.txt').write_text('keep')
        for target in (self.target, self.paths.data / 'nested', self.paths.install, self.root / '.local'):
            with self.assertRaises(ValueError):
                schedule_change(self.paths, target)
        self.assertEqual((self.target / 'precious.txt').read_text(), 'keep')

    def test_destination_changed_before_restart_preserves_source_and_setting(self):
        schedule_change(self.paths, self.target)
        (self.target / 'precious.txt').write_text('keep')
        with self.assertRaises(ValueError):
            apply_pending_change(self.paths)
        self.assertEqual(resolve_paths(self.paths.install, self.paths.user).data, self.paths.data)
        self.assertIn('pending_directory', read_settings(self.paths))

    def test_invalid_metadata_does_not_commit_or_leave_partial_copy(self):
        (self.paths.data / 'bad.json').write_text('{')
        schedule_change(self.paths, self.target)
        with self.assertRaises(ValueError):
            apply_pending_change(self.paths)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(list(self.root.glob('.ai-climbing-copy-*')), [])

    def test_missing_active_device_is_not_replaced_by_empty_default(self):
        schedule_change(self.paths, self.target)
        apply_pending_change(self.paths)
        import shutil
        shutil.rmtree(self.target)
        with self.assertRaises(RuntimeError):
            resolve_paths(self.paths.install, self.paths.user)

    def test_folder_picker_guard_cancel_and_selection(self):
        chosen = [None]
        client = TestClient(create_app(self.paths, 'test', 'http://127.0.0.1:51234',
            backend=FastAPI(), choose_storage=lambda: chosen[0]), base_url='http://127.0.0.1:51234')
        self.assertEqual(client.post('/desktop/storage/choose').status_code, 403)
        client.get('/desktop/bootstrap/test')
        self.assertTrue(client.post('/desktop/storage/choose').json()['cancelled'])
        self.assertFalse((self.paths.config / 'storage.json').exists())
        chosen[0] = str(self.target)
        self.assertTrue(client.post('/desktop/storage/choose').json()['restart_required'])
        self.assertEqual(client.get('/desktop/status').json()['pending_data_directory'], str(self.target))


if __name__ == '__main__':
    unittest.main()
