import importlib.util
import json
from pathlib import Path
import tempfile
import sqlite3
import os
import hashlib
from types import SimpleNamespace
from contextlib import closing
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('companion_publish',ROOT/'publish.py')
publish=importlib.util.module_from_spec(spec);spec.loader.exec_module(publish)
check=publish.load_module('bundle_check_test','check_bundle.py')

class CompanionSafetyTests(unittest.TestCase):
    @unittest.skipIf(os.name=='nt','Linux symlink and service recovery guard')
    def test_only_exact_failed_installation_is_recovered_without_changing_data(self):
        recovery=publish.load_module('exact_recovery_test','recover.py')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);m=SimpleNamespace(BASE=root/'app',ENV=root/'env',UNIT=root/'unit',DATA=root/'data',SNIPPET=root/'snippet',PORT=18876,ORIGIN='https://example.test',digest=lambda b:hashlib.sha256(b).hexdigest())
            release=m.BASE/'releases'/'fixture';release.mkdir(parents=True);(m.BASE/'current').symlink_to(release,target_is_directory=True);m.DATA.mkdir();saved=m.DATA/'study.sqlite';saved.write_bytes(b'existing learning records')
            payload={'server.mjs':b'known code'};(release/'server.mjs').write_bytes(payload['server.mjs']);m.ENV.write_bytes(f'PORT={m.PORT}\nPUBLIC_ORIGIN={m.ORIGIN}\nDATA_DIR={m.DATA}\nTRUST_PROXY=1\n'.encode());m.UNIT.write_bytes(recovery.expected_unit(m,'/usr/bin/node'));m.SNIPPET.write_bytes(b'known snippet')
            metadata={'release':'fixture','recoverRelease':'fixture','expectedSnippetSHA256':m.digest(b'known snippet')}
            self.assertEqual(recovery.validate_existing(m,metadata,payload,'/usr/bin/node'),b'known snippet');self.assertEqual(saved.read_bytes(),b'existing learning records')
            (release/'server.mjs').write_bytes(b'changed code')
            with self.assertRaisesRegex(RuntimeError,'no overwrite'):recovery.validate_existing(m,metadata,payload,'/usr/bin/node')
            self.assertEqual(saved.read_bytes(),b'existing learning records')

    def test_wait_accepts_only_real_study_json_after_stale_nginx_responses(self):
        installer=publish.load_module('install_wait_test','install.py')
        with patch.object(installer,'request',side_effect=[b'<html>old climbing</html>',b'<html>old climbing</html>',b'<a href="/study/">workshop</a>',b'{"app":"study-friends","ok":true}']),patch.object(installer.time,'sleep') as sleep:
            installer.wait_publication(attempts=2,delay=.1)
            sleep.assert_called_once_with(.1)

    def test_wait_refuses_spa_fallback_even_when_it_has_study_link(self):
        installer=publish.load_module('install_wait_reject_test','install.py')
        with patch.object(installer,'request',return_value=b'<a href="/study/">old page</a>'),patch.object(installer.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'did not become ready'):installer.wait_publication(attempts=2,delay=0)

    def test_recovery_backs_up_database_without_resetting_existing_records(self):
        recovery=publish.load_module('recovery_db_test','recover.py')
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'data';data.mkdir();backup=Path(folder)/'backup';backup.mkdir()
            with closing(sqlite3.connect(data/'study.sqlite')) as db,db:db.execute('CREATE TABLE saved(value TEXT)');db.execute('INSERT INTO saved VALUES(?)',('keep-existing-progress',))
            recovery.backup_database(data,backup)
            for database in [data/'study.sqlite',backup/'study.sqlite']:
                with closing(sqlite3.connect(database)) as db:self.assertEqual(db.execute('SELECT value FROM saved').fetchone()[0],'keep-existing-progress')

    def test_stale_climbing_baseline_refuses_before_runtime_or_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            current=Path(folder);(current/'RELEASE_SHA').write_text('b'*40)
            metadata={'schema':1,'mode':'study-companion','expectedClimbingCommit':'a'*40}
            with patch.object(publish.shutil,'disk_usage') as disk:
                with self.assertRaisesRegex(RuntimeError,'Climbing changed'):publish.preflight(metadata,current)
                disk.assert_not_called()

    def test_bundle_content_is_the_verified_application_without_private_data(self):
        metadata,payload=check.check()
        self.assertIn('public/ui.js',payload);self.assertIn('public/THIRD_PARTY_NOTICES.txt',payload)
        self.assertNotIn('data/study.sqlite',payload)
        self.assertEqual(json.loads(payload['package.json'])['version'],'0.2.0')
        self.assertEqual(len(payload),21)

    def test_tampered_archive_rejected(self):
        with patch.object(check.hashlib,'sha256') as digest:
            digest.return_value.hexdigest.return_value='0'*64
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):check.check()

    def test_vhost_plan_preserves_climbing_and_ai41_configuration(self):
        installer=publish.load_module('install_test','install.py')
        original=b'server {\n    root /opt/ai-climbing/current/frontend/dist;\n    include /etc/nginx/snippets/ai41-study.conf;\n    location / { try_files $uri $uri/ /index.html; }\n}\n'
        result=installer.plan_vhost(original)
        self.assertEqual(result.replace(b'\n    include /etc/nginx/snippets/study-friends.conf;',b''),original)

if __name__=='__main__':unittest.main()
