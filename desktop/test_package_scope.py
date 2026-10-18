import tempfile
from pathlib import Path
import unittest
from desktop.package_scope import assert_local_frontend, assert_local_package, local_core_modules


class PackageScopeTests(unittest.TestCase):
    def test_shared_import_closure_and_setter_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            core=Path(directory)
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
            package=Path(directory)
            dist=package/'frontend/dist';dist.mkdir(parents=True)
            (dist/'index.html').write_text('<html></html>');(dist/'index.js').write_text('const title="boulder"')
            backend=package/'backend';(backend/'core').mkdir(parents=True)
            (backend/'boulder_local_app.py').write_text('')
            assert_local_package(package)
            (backend/'main.py').write_text('')
            with self.assertRaises(RuntimeError):assert_local_package(package)


if __name__=='__main__':unittest.main()
