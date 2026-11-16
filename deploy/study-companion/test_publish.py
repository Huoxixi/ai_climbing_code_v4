import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('companion_publish',ROOT/'publish.py')
publish=importlib.util.module_from_spec(spec);spec.loader.exec_module(publish)
check=publish.load_module('bundle_check_test','check_bundle.py')

class CompanionSafetyTests(unittest.TestCase):
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
