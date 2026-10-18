"""Refresh only newly built 0.1.13 app files after final verification changes."""
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop.sync_export_vision_update import sha
from desktop.package_scope import local_core_modules, assert_local_package

target = Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.13-export-vision-preview.20261009').resolve()
dist = (target / 'frontend/dist').resolve()
if dist != Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.13-export-vision-preview.20261009/frontend/dist').resolve():
    raise RuntimeError('Unexpected generated build directory')
if json.loads((target / 'local-update.json').read_text('utf-8'))['version'] != '0.1.13-export-vision-preview.20261009':
    raise RuntimeError('Only this newly created package may be refreshed')
rows = json.loads((target / 'file-manifest.json').read_text('utf-8'))
critical = {r['path'] for r in json.loads((target / 'resources.json').read_text('utf-8'))['critical']}
# This is this turn's generated web build, never user media or a previous package.
shutil.rmtree(dist)
shutil.copytree(PROJECT / 'frontend/dist', dist)
index = dist / 'index.html'
index.write_text(index.read_text('utf-8').replace('<head>', '<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>', 1), encoding='utf-8')
changed = set()
for name in local_core_modules(PROJECT / 'backend/core'):
    relative = 'backend/core/' + name + '.py'
    shutil.copy2(PROJECT / relative, target / relative)
    changed.add(relative)
doc = 'docs/AI复盘_数据导出与视觉接口修复_2026-10-09.md'
shutil.copy2(PROJECT / doc, target / doc)
changed.add(doc)
changed.update(p.relative_to(target).as_posix() for p in dist.rglob('*') if p.is_file())
rows = [r for r in rows if r['path'] not in changed and not r['path'].startswith('frontend/dist/')]
rows += [{'path': name, 'bytes': (target / name).stat().st_size, 'sha256': sha(target / name)} for name in sorted(changed)]
(target / 'file-manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
(target / 'resources.json').write_text(json.dumps({'critical': [r for r in rows if r['path'] in critical or r['path'].startswith('frontend/dist/')]}, ensure_ascii=False, indent=2), encoding='utf-8')
assert_local_package(target)
print(json.dumps({'refreshed_files': len(changed), 'local_scope_verified': True}))
