"""Sync only the two-choice export UI, preserving a recoverable frontend backup."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop.package_scope import assert_local_frontend, assert_local_package


def main():
    target = Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.13-export-vision-preview.20261009').resolve()
    backup = Path('D:/ai_climbing_code/verification/export-choices-20261009').resolve()
    if target.parent != Path('D:/ai_climbing_code/desktop-deliveries').resolve() or backup.parent != Path('D:/ai_climbing_code/verification').resolve():
        raise RuntimeError('Unexpected package or backup path')
    dist = (target / 'frontend/dist').resolve()
    if dist != target / 'frontend/dist' or backup.exists():
        raise RuntimeError('Unexpected frontend target or backup already exists')
    assert_local_frontend(PROJECT / 'frontend/dist')
    update = json.loads((target / 'local-update.json').read_text('utf-8'))
    if update['version'] != '0.1.13-export-vision-preview.20261009':
        raise RuntimeError('Unexpected installed version')
    backup.mkdir()
    for name in ('file-manifest.json', 'resources.json', 'local-update.json'):
        shutil.copy2(target / name, backup / name)
    staging = backup / 'new-dist'
    shutil.copytree(PROJECT / 'frontend/dist', staging)
    index = staging / 'index.html'
    index.write_text(index.read_text('utf-8').replace('<head>', '<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>', 1), encoding='utf-8')
    # Both exact paths are confined above; old UI is moved intact, never deleted.
    shutil.move(str(dist), str(backup / 'previous-dist'))
    try:
        shutil.move(str(staging), str(dist))
        assert_local_package(target)
        rows = json.loads((target / 'file-manifest.json').read_text('utf-8'))
        critical = {r['path'] for r in json.loads((target / 'resources.json').read_text('utf-8'))['critical']}
        rows = [r for r in rows if not r['path'].startswith('frontend/dist/') and r['path'] != 'local-update.json']
        update['ui_hotfix'] = 'two export choices; remove more materials'
        (target / 'local-update.json').write_text(json.dumps(update, ensure_ascii=False, indent=2), encoding='utf-8')
        for path in [target / 'local-update.json', *sorted(p for p in dist.rglob('*') if p.is_file())]:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            rows.append({'path': path.relative_to(target).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest})
        (target / 'file-manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        (target / 'resources.json').write_text(json.dumps({'critical': [r for r in rows if r['path'] in critical or r['path'].startswith('frontend/dist/')]}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        if dist.exists():
            shutil.move(str(dist), str(backup / 'failed-dist'))
        shutil.move(str(backup / 'previous-dist'), str(dist))
        for name in ('file-manifest.json', 'resources.json', 'local-update.json'):
            shutil.copy2(backup / name, target / name)
        raise
    print(json.dumps({'frontend_synced': True, 'backup': str(backup), 'user_data_modified': False}))


if __name__ == '__main__':
    main()
