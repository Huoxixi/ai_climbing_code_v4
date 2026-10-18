"""Sync the verified backend hotfix, backing up program files only."""
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
from desktop.package_scope import assert_local_package


def write_json(path, value):
    temporary = path.with_suffix('.performance.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
    os.replace(temporary, path)


def main():
    deliveries = Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target = (deliveries / ('AiClimbing-' + VERSION)).resolve()
    if target.parent != deliveries:
        raise RuntimeError('Unexpected package path')
    paths = resolve_paths(install=target, user=PROJECT / '.tmp/backend-sync-check')
    verify_resources(paths)
    backup = Path('D:/ai_climbing_code/verification/backend-performance-20261009') / ('app-backup-' + datetime.now().strftime('%Y%m%d%H%M%S'))
    backup.mkdir(parents=True, exist_ok=False)
    names = ['backend/core/climb_replay.py', 'backend/core/photo_route_v2.py', 'backend/core/photo_route_workflow.py']
    saved = names + ['resources.json', 'file-manifest.json', 'local-update.json']
    for name in saved:
        destination = backup / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, destination)
    try:
        for name in names:
            shutil.copy2(PROJECT / name, target / name)
        update = json.loads((target / 'local-update.json').read_text('utf-8'))
        update['backend_hotfix'] = '2026-10-09: nonblocking uploads, bounded replay cache, skeleton upload repair'
        write_json(target / 'local-update.json', update)
        changed = names + ['local-update.json']
        entries = []
        for name in changed:
            path = target / name
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            entries.append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest})
        manifest = json.loads((target / 'file-manifest.json').read_text('utf-8'))
        write_json(target / 'file-manifest.json', [item for item in manifest if item['path'] not in changed] + entries)
        resources = json.loads((target / 'resources.json').read_text('utf-8'))
        resources['critical'] = [item for item in resources['critical'] if item['path'] not in changed] + entries
        write_json(target / 'resources.json', resources)
        assert_local_package(target)
        verify_resources(paths)
    except BaseException:
        for name in saved:
            shutil.copy2(backup / name, target / name)
        raise
    print(json.dumps({'synchronized': str(target), 'program_backup': str(backup), 'resources_verified': True}))


if __name__ == '__main__':
    main()
