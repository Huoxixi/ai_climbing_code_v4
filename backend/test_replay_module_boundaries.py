"""Foundation imports must not initialize replay job services."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReplayModuleBoundaryTests(unittest.TestCase):
    def assert_isolated_import(self, module):
        code = (f'import {module}\nimport sys\n'
                'assert "core.climb_replay" not in sys.modules\n'
                'assert "core.replay_hold_editor" not in sys.modules\n')
        completed = subprocess.run([sys.executable, '-B', '-c', code],
            cwd=Path(__file__).parent, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_request_contracts_do_not_import_job_services(self):
        self.assert_isolated_import('core.replay_contracts')

    def test_drawing_primitives_do_not_import_job_services(self):
        self.assert_isolated_import('core.replay_render_primitives')

    def test_analysis_view_no_longer_imports_job_services(self):
        self.assert_isolated_import('core.replay_analysis_view')

    def test_legacy_imports_reexport_the_canonical_contracts(self):
        from core import climb_replay, replay_contracts, replay_render_primitives
        for name in ('VideoInfo', 'VideoLimits', 'ReplayCancelled', 'ReplayUploadCreate',
                     'ReplayAnalyzer', 'parse_color_sample', 'holds_revision'):
            with self.subTest(name=name):
                self.assertIs(getattr(climb_replay, name), getattr(replay_contracts, name))
        for name in ('build_pose_render_timeline', 'draw_cjk_labels'):
            with self.subTest(name=name):
                self.assertIs(getattr(climb_replay, name), getattr(replay_render_primitives, name))


if __name__ == '__main__':
    unittest.main()
