"""Exercise delivery file effects without loading models or updating an installation."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from desktop import build, finalize


RUNTIME_FILES = {
    '__init__.py', 'paths.py', 'credentials.py', 'server.py', 'launcher.py',
    'storage.py', 'window_check.py', 'verify_package.py',
}


class BuildScopeTests(unittest.TestCase):
    def make_source(self, root):
        source = root / 'source'
        files = {
            'frontend/dist/index.html': '<html><head></head></html>',
            'frontend/dist/index.js': 'const title="boulder"',
            'backend/boulder_local_app.py': 'from core.photo_route import run\n',
            'backend/core/photo_route.py': 'def run(): pass\n',
            'backend/core/replay_hidden_candidate.py': 'raise RuntimeError("experiment")',
            'backend/vendor/NotoSansSC-VF.ttf': 'font',
            'backend/vendor/NotoSansSC-OFL.txt': 'license',
            'backend/vendor/__init__.py': '',
            'desktop/dependencies.lock.json': '{}',
            'desktop/THIRD_PARTY.md': 'licenses',
            'desktop/使用说明.md': 'instructions',
            'desktop/独立电脑验收.ps1': 'acceptance',
            'desktop/sync_old_install.py': 'raise RuntimeError("do not run")',
            'desktop/test_hidden.py': 'raise RuntimeError("do not run")',
            **{'desktop/' + name: '' for name in RUNTIME_FILES},
        }
        for name, content in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        for name in ('backend/model_assets', 'backend/vendor/rtmlib', 'docs/bouldering-knowledge'):
            (source / name).mkdir(parents=True)
        runtime = root / 'python'
        runtime.mkdir()
        for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll',
                     'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
            (runtime / name).write_text('runtime', encoding='utf-8')
        (runtime / 'DLLs').mkdir()
        (runtime / 'Lib').mkdir()
        detectron = root / 'detectron'
        (detectron / 'detectron2').mkdir(parents=True)
        (detectron / 'LICENSE').write_text('license', encoding='utf-8')
        return source, runtime, detectron

    def build_fixture(self, root):
        source, runtime, detectron = self.make_source(root)
        output = root / 'output'
        fake_pose = ModuleType('core.replay_pose_rtmw')
        fake_pose.LocalRTMWReplayAnalyzer = lambda **kwargs: SimpleNamespace(_load_models=lambda: None)
        arguments = SimpleNamespace(output=output, site=[], detectron=detectron,
                                    write_lock=False, checkpoint=None)
        with patch.object(build, 'PROJECT', source), \
             patch.object(build.sys, 'base_prefix', str(runtime)), \
             patch.object(build.sys, 'version_info', (3, 12)), \
             patch.object(build.sys, 'platform', 'win32'), \
             patch.object(build, 'distributions', return_value={}), \
             patch.object(build.subprocess, 'run'), \
             patch.dict('sys.modules', {'core.replay_pose_rtmw': fake_pose}), \
             redirect_stdout(io.StringIO()):
            build.build(arguments)
        return source, output

    def test_build_copies_complete_desktop_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output = self.build_fixture(Path(directory))
            self.assertEqual({path.name for path in (output / 'desktop').glob('*.py')}, RUNTIME_FILES)

    def test_build_excludes_unreferenced_pose_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output = self.build_fixture(Path(directory))
            self.assertEqual({path.name for path in (output / 'backend/core').glob('*.py')}, {'photo_route.py'})

    def test_finalize_does_not_copy_maintenance_or_test_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.build_fixture(Path(directory))
            # The source fixture supplies a complete runtime even on the legacy builder.
            (output / 'desktop/storage.py').write_text('', encoding='utf-8')
            (output / 'AiClimbing.exe').write_text('executable', encoding='utf-8')
            with patch.object(finalize, 'PROJECT', source), \
                 patch.object(finalize.sys, 'argv', ['finalize', '--package', str(output)]), \
                 patch.object(finalize.subprocess, 'check_output', side_effect=['fixture-sha\n', '']), \
                 redirect_stdout(io.StringIO()):
                finalize.main()
            self.assertEqual({path.name for path in (output / 'desktop').glob('*.py')}, RUNTIME_FILES)
            manifest = json.loads((output / 'file-manifest.json').read_text('utf-8'))
            self.assertIn('desktop/storage.py', {row['path'] for row in manifest})

    def test_finalize_scopes_git_trust_to_its_two_metadata_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = self.build_fixture(Path(directory))
            (output / 'AiClimbing.exe').write_text('executable', encoding='utf-8')
            with patch.object(finalize, 'PROJECT', source), \
                 patch.object(finalize.sys, 'argv', ['finalize', '--package', str(output)]), \
                 patch.object(finalize.subprocess, 'check_output', side_effect=['fixture-sha\n', '']) as query, \
                 redirect_stdout(io.StringIO()):
                finalize.main()
            self.assertEqual([call.args[0] for call in query.call_args_list], [
                ['git', '-c', 'safe.directory=' + source.resolve().as_posix(), 'rev-parse', 'HEAD'],
                ['git', '-c', 'safe.directory=' + source.resolve().as_posix(), '-c', 'core.quotepath=false', 'status', '--short'],
            ])
            baseline = json.loads((output / 'source-baseline.json').read_text('utf-8'))
            reference = baseline['runtime_source_manifest']
            self.assertEqual(reference['file'], 'file-manifest.json')
            manifest = json.loads((output / reference['file']).read_text('utf-8'))
            self.assertTrue(set(reference['paths']).issubset({row['path'] for row in manifest}))
            self.assertIn('desktop/storage.py', reference['paths'])


if __name__ == '__main__':
    unittest.main()
