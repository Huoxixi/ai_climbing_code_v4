"""Install the verified local video import normalization, with a program-only rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_frontend, assert_local_package

BACKEND_FILES = ['backend/core/climb_replay.py', 'backend/core/replay_preview.py']


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    workspace = Path('D:/ai_climbing_code').resolve()
    deliveries = workspace / 'desktop-deliveries'
    target = (deliveries / ('AiClimbing-' + VERSION)).resolve()
    backup_root = workspace / 'verification/video-preview-20261015'
    backup = (backup_root / datetime.now().strftime('%Y%m%d%H%M%S')).resolve()
    dist = (target / 'frontend/dist').resolve()
    if target.parent != deliveries or not dist.is_relative_to(target) or not backup.is_relative_to(backup_root):
        raise RuntimeError('Unexpected program or backup destination')
    paths = resolve_paths(install=target, user=PROJECT / '.tmp/video-preview-20261015/resource-check')
    verify_resources(paths)
    assert_local_package(target)
    assert_local_frontend(PROJECT / 'frontend/dist')
    backup.mkdir(parents=True, exist_ok=False)
    metadata = ['resources.json', 'file-manifest.json', 'local-update.json']
    names = BACKEND_FILES + metadata
    previous = set()
    for name in names:
        if (target / name).is_file():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / name, destination)
            previous.add(name)
    staging = backup / 'new-dist'
    shutil.copytree(PROJECT / 'frontend/dist', staging)
    index = staging / 'index.html'
    index.write_text(index.read_text('utf8').replace('<head>', '<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>', 1), 'utf8')
    shutil.move(str(dist), str(backup / 'previous-dist'))
    def atomic(name, value):
        path = target / name
        temporary = path.with_name(path.name + '.composition.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
        os.replace(temporary, path)
    try:
        shutil.move(str(staging), str(dist))
        for name in BACKEND_FILES:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + '.composition.tmp')
            shutil.copy2(PROJECT / name, temporary)
            os.replace(temporary, destination)
        update = json.loads((target / 'local-update.json').read_text('utf8'))
        update['video_import_hotfix'] = {
            'date': '2026-10-15', 'version': 'upload-first-canonical-h264-v1',
            'preview_before_color': True, 'canonical': 'H264 MP4 yuv420p upright silent <=30fps',
            'reuse_prepared_copy': True, 'preserve_original': True,
            'real_first_ten_previews_verified': True, 'generated_format_cases': 13,
            'user_data_modified': False, 'production_deployed': False}
        atomic('local-update.json', update)
        rows = json.loads((target / 'file-manifest.json').read_text('utf8'))
        resources = json.loads((target / 'resources.json').read_text('utf8'))
        changed = set(BACKEND_FILES) | {'local-update.json'}
        rows = [r for r in rows if r['path'] not in changed and not r['path'].startswith('frontend/dist/')]
        for path in [*(target / name for name in sorted(changed)), *sorted(p for p in dist.rglob('*') if p.is_file())]:
            rows.append({'path': path.relative_to(target).as_posix(), 'bytes': path.stat().st_size, 'sha256': checksum(path)})
        critical = {r['path'] for r in resources['critical']} | changed
        atomic('file-manifest.json', rows)
        atomic('resources.json', {**resources, 'critical': [r for r in rows if r['path'] in critical or r['path'].startswith('frontend/dist/')]})
        verify_resources(paths)
        assert_local_package(target)
        assert all(checksum(target / name) == checksum(PROJECT / name) for name in BACKEND_FILES)
    except BaseException:
        if dist.exists():
            shutil.move(str(dist), str(backup / 'failed-dist'))
        shutil.move(str(backup / 'previous-dist'), str(dist))
        for name in names:
            if name in previous:
                shutil.copy2(backup / name, target / name)
            elif name in BACKEND_FILES:
                (target / name).unlink(missing_ok=True)
        raise
    result = {'installed': str(target), 'backup': str(backup), 'source_hashes_match': True,
              'resources_verified': True, 'user_app_not_restarted': True, 'production_deployed': False}
    evidence = PROJECT / '.tmp/video-preview-20261015'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'installation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
