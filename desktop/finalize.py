"""Reconcile reviewed preview changes, audit, hash and archive owned build output."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from desktop.package_scope import assert_local_package, copy_desktop_runtime


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    package = args.package.resolve()
    if not (package / 'runtime/python312._pth').is_file() or not (package / 'AiClimbing.exe').is_file():
        raise RuntimeError('Not an owned desktop build output')
    assert_local_package(package)
    copy_desktop_runtime(PROJECT / 'desktop', package / 'desktop')
    for name in ('使用说明.md', 'THIRD_PARTY.md'):
        shutil.copy2(PROJECT / 'desktop' / name, package / ('licenses' if name == 'THIRD_PARTY.md' else '') / name)
    shutil.copy2(PROJECT / 'desktop/独立电脑验收.ps1', package / '独立电脑验收.ps1')
    git_query = ['git', '-c', 'safe.directory=' + PROJECT.resolve().as_posix()]
    runtime_sources = ['backend/boulder_local_app.py'] + sorted(
        path.relative_to(package).as_posix()
        for folder in ('backend/core', 'desktop') for path in (package / folder).glob('*.py'))
    baseline = {'commit': subprocess.check_output([*git_query, 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip(),
                'working_tree_changes': subprocess.check_output([*git_query, '-c', 'core.quotepath=false', 'status', '--short'], cwd=PROJECT, text=True, encoding='utf-8').splitlines(),
                'includes_uncommitted_features': True,
                'runtime_source_manifest': {'file': 'file-manifest.json', 'paths': runtime_sources}}
    (package / 'source-baseline.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf-8')
    records = []
    forbidden = {'.local', '.private', 'node_modules', '.git', 'accounts.sqlite3', 'photo-vision.env', '.env', 'cloud.dpapi', 'instance.json'}
    for path in sorted(package.rglob('*')):
        if not path.is_file() or path.name in {'file-manifest.json', 'resources.json'} or '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
            continue
        if forbidden.intersection(path.relative_to(package).parts):
            raise RuntimeError('Forbidden distribution entry: ' + path.name)
        records.append({'path': path.relative_to(package).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
    (package / 'file-manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    critical = [r for r in records if r['path'].endswith(('verified-model_final.pth', 'rtmw.onnx', 'detector.onnx', 'manifest.json', 'index.html', 'python312.dll', '_C.cp312-win_amd64.pyd', 'NotoSansSC-VF.ttf', 'ffmpeg-win-x86_64-v7.1.exe')) or r['path'].startswith(('desktop/', 'backend/core/')) or r['path'] == 'backend/boulder_local_app.py']
    (package / 'resources.json').write_text(json.dumps({'critical': critical}, indent=2), encoding='utf-8')
    if args.archive:
        archive = package.parent / (package.name + '.zip')
        if archive.exists():
            raise RuntimeError('Archive exists; choose a new version instead of overwriting')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
            for path in sorted(package.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}:
                    bundle.write(path, Path(package.name) / path.relative_to(package))
        checksum = digest(archive)
        archive.with_suffix('.zip.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='utf-8')
        print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': checksum}))
    else:
        print(json.dumps({'audited_files': len(records), 'bytes': sum(r['bytes'] for r in records)}))


if __name__ == '__main__':
    main()
