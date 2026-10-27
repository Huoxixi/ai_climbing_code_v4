import ast
import tempfile
from pathlib import Path
import unittest
from desktop.package_scope import assert_local_frontend, assert_local_package, local_core_modules


class PackageScopeTests(unittest.TestCase):
    def make_package(self, root):
        package = Path(root)
        dist = package / 'frontend/dist'
        dist.mkdir(parents=True)
        (dist / 'index.html').write_text('<html></html>', encoding='utf-8')
        (dist / 'index.js').write_text('const title="boulder"', encoding='utf-8')
        core = package / 'backend/core'
        core.mkdir(parents=True)
        (package / 'backend/boulder_local_app.py').write_text('from core.photo_route import run\n', encoding='utf-8')
        (core / 'photo_route.py').write_text('def run(): pass\n', encoding='utf-8')
        desktop = package / 'desktop'
        desktop.mkdir()
        for name in ('__init__', 'paths', 'credentials', 'server', 'launcher', 'storage', 'window_check', 'verify_package'):
            (desktop / (name + '.py')).write_text('', encoding='utf-8')
        return package, core

    def test_shared_import_closure_and_setter_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            _, core = self.make_package(directory)
            for name,text in {'photo_route.py':'def worker():\n from core.shared_media import decode','shared_media.py':'from core.common import decode','common.py':'','standard_board.py':''}.items():
                (core/name).write_text(text)
            self.assertEqual(local_core_modules(core),{'photo_route','shared_media','common'})

    def test_full_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dist=Path(directory)
            (dist/'index.html').write_text('<html></html>')
            (dist/'index.js').write_text('const title="定线项目"',encoding='utf-8')
            with self.assertRaises(RuntimeError):assert_local_frontend(dist)

    def test_package_must_not_contain_full_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            package, _ = self.make_package(directory)
            assert_local_package(package)
            (package/'backend/main.py').write_text('')
            with self.assertRaises(RuntimeError):assert_local_package(package)

    def test_current_runtime_keeps_pose_and_privacy_modules(self):
        core = Path(__file__).resolve().parents[1] / 'backend/core'
        selected = local_core_modules(core)
        self.assertTrue({
            'replay_pose_clip', 'replay_pose_rtmw', 'replay_pose_temporal',
            'replay_pose_image_refinement', 'replay_pose_context', 'replay_pose_observation',
            'replay_observation_validity', 'replay_analysis_view', 'replay_export',
            'replay_secret', 'photo_route_settings', 'replay_resources',
        }.issubset(selected))

    def test_current_runtime_keeps_every_registered_subprocess_worker(self):
        core = Path(__file__).resolve().parents[1] / 'backend/core'
        tree = ast.parse((core / 'replay_resources.py').read_text('utf-8-sig'))
        declaration = next(node for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == 'VISUAL_WORKER_MODULES'
                                   for target in node.targets))
        workers = ast.literal_eval(declaration.value.args[0])
        self.assertTrue({name.split('.')[1] for name in workers}.issubset(local_core_modules(core)))

    def test_unreferenced_replay_candidate_is_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, core = self.make_package(directory)
            (core / 'replay_hidden_candidate.py').write_text('raise RuntimeError("experiment")', encoding='utf-8')
            self.assertEqual(local_core_modules(core), {'photo_route'})

    def test_relative_package_import_is_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, core = self.make_package(directory)
            (core / 'photo_route.py').write_text('from . import shared_media\n', encoding='utf-8')
            (core / 'shared_media.py').write_text('', encoding='utf-8')
            self.assertEqual(local_core_modules(core), {'photo_route', 'shared_media'})

    def test_missing_runtime_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, core = self.make_package(directory)
            (core / 'photo_route.py').write_text('from core.missing_media import decode\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'missing_media'):
                local_core_modules(core)

    def test_missing_backend_entrypoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            package, core = self.make_package(directory)
            (package / 'backend/boulder_local_app.py').unlink()
            with self.assertRaisesRegex(RuntimeError, 'boulder_local_app'):
                local_core_modules(core)

    def test_package_rejects_unreferenced_prefixed_core_module(self):
        with tempfile.TemporaryDirectory() as directory:
            package, core = self.make_package(directory)
            (core / 'replay_hidden_candidate.py').write_text('', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'replay_hidden_candidate'):
                assert_local_package(package)

    def test_package_requires_storage_module(self):
        with tempfile.TemporaryDirectory() as directory:
            package, _ = self.make_package(directory)
            (package / 'desktop/storage.py').unlink()
            with self.assertRaisesRegex(RuntimeError, 'storage.py'):
                assert_local_package(package)

    def test_package_rejects_maintenance_script(self):
        with tempfile.TemporaryDirectory() as directory:
            package, _ = self.make_package(directory)
            (package / 'desktop/sync_old_install.py').write_text('raise RuntimeError("do not run")', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'sync_old_install.py'):
                assert_local_package(package)

    def test_runtime_import_cannot_reenable_rejected_pose_candidates(self):
        rejected = (
            'replay_pose_candidates', 'replay_pose_chain_evidence',
            'replay_pose_coverage_selection', 'replay_pose_candidate_sequence',
            'replay_pose_occlusion_heatmaps', 'replay_pose_occlusion_heatmaps_v2',
        )
        for name in rejected:
            with self.subTest(candidate=name), tempfile.TemporaryDirectory() as directory:
                _, core = self.make_package(directory)
                (core / 'photo_route.py').write_text(f'from core.{name} import run\n', encoding='utf-8')
                (core / (name + '.py')).write_text('def run(): pass\n', encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'Rejected pose candidate.*' + name):
                    local_core_modules(core)

    def test_package_explicitly_rejects_unused_rejected_pose_candidates(self):
        rejected = (
            'replay_pose_candidates', 'replay_pose_chain_evidence',
            'replay_pose_coverage_selection', 'replay_pose_candidate_sequence',
            'replay_pose_occlusion_heatmaps', 'replay_pose_occlusion_heatmaps_v2',
        )
        for name in rejected:
            with self.subTest(candidate=name), tempfile.TemporaryDirectory() as directory:
                package, core = self.make_package(directory)
                (core / (name + '.py')).write_text('', encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'Rejected pose candidate.*' + name):
                    assert_local_package(package)


if __name__=='__main__':unittest.main()
