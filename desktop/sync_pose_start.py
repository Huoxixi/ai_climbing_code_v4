"""Sync pose-only start selection; preserve program backups and user files."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_frontend, assert_local_package


def main():
    deliveries = Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target = (deliveries / ('AiClimbing-' + VERSION)).resolve()
    dist = (target / 'frontend/dist').resolve()
    if target.parent != deliveries or dist != target / 'frontend/dist':
        raise RuntimeError('Unexpected program destination')
    paths = resolve_paths(install=target, user=PROJECT / '.tmp/pose-start-sync-check')
    verify_resources(paths)
    assert_local_frontend(PROJECT / 'frontend/dist')
    backup = Path('D:/ai_climbing_code/verification/pose-start-20261010') / datetime.now().strftime('%Y%m%d%H%M%S')
    backup.mkdir(parents=True, exist_ok=False)
    names = ['backend/core/' + name for name in ('replay_pose_start.py', 'replay_torso_trajectory.py',
             'replay_action_jobs.py', 'replay_action_renderer.py')]
    metadata = ['resources.json','file-manifest.json','local-update.json']
    existing = []
    for name in names + metadata:
        if (target / name).exists():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / name, destination)
            existing.append(name)
    staging = backup / 'new-dist'
    shutil.copytree(PROJECT / 'frontend/dist', staging)
    index = staging / 'index.html'
    index.write_text(index.read_text('utf-8').replace('<head>', '<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>', 1), 'utf-8')
    shutil.move(str(dist), str(backup / 'previous-dist'))
    try:
        shutil.move(str(staging), str(dist))
        for name in names: shutil.copy2(PROJECT / name, target / name)
        update = json.loads((target / 'local-update.json').read_text('utf-8'))
        update['pose_start_hotfix'] = '2026-10-10: pose-only automatic onset and persistent user start, shared with exports'
        (target / 'local-update.json').write_text(json.dumps(update, ensure_ascii=False, indent=2), 'utf-8')
        resources = json.loads((target / 'resources.json').read_text('utf-8'))
        rows = json.loads((target / 'file-manifest.json').read_text('utf-8'))
        changed = names + ['local-update.json']
        rows = [r for r in rows if r['path'] not in changed and not r['path'].startswith('frontend/dist/')]
        critical = {r['path'] for r in resources['critical']}
        for path in [*(target / name for name in changed), *sorted(p for p in dist.rglob('*') if p.is_file())]:
            with path.open('rb') as stream: checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            rows.append({'path':path.relative_to(target).as_posix(), 'bytes':path.stat().st_size, 'sha256':checksum})
        for name, value in [('file-manifest.json',rows), ('resources.json', {**resources,'critical':[
                r for r in rows if r['path'] in critical or r['path'] in changed or r['path'].startswith('frontend/dist/')]})]:
            temporary = target / (name + '.pose-start.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
            os.replace(temporary, target / name)
        assert_local_package(target)
        verify_resources(paths)
    except BaseException:
        if dist.exists(): shutil.move(str(dist), str(backup / 'failed-dist'))
        shutil.move(str(backup / 'previous-dist'), str(dist))
        for name in existing: shutil.copy2(backup / name, target / name)
        for name in names:
            if name not in existing: (target / name).unlink(missing_ok=True)
        raise
    print(json.dumps({'synced':str(target), 'backup':str(backup), 'resources_verified':True}))


if __name__ == '__main__': main()
