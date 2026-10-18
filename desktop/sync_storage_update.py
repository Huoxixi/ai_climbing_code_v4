"""Refresh current local delivery without touching any user data."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
target = Path('D:/ai_climbing_code/desktop-deliveries') / ('AiClimbing-' + VERSION)
verify_resources(resolve_paths(install=target, user=project / '.tmp/storage-sync-check'))
backup = Path('D:/ai_climbing_code/.tmp') / ('storage-app-backup-' + datetime.now().strftime('%Y%m%d%H%M%S'))
backup.mkdir()
files = ['desktop/paths.py', 'desktop/storage.py', 'desktop/server.py', 'desktop/launcher.py']
for name in files + ['resources.json', 'file-manifest.json']:
    if (target / name).is_file():
        destination = backup / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, destination)
shutil.copytree(target / 'frontend/dist', backup / 'frontend/dist')
entries = []
for name in files:
    shutil.copy2(project / name, target / name)
    file = target / name
    entries.append({'path': name, 'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
names = set(files)
manifest = json.loads((target / 'file-manifest.json').read_text('utf-8'))
manifest = [item for item in manifest if item['path'] not in names] + entries
(target / 'file-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
resources = json.loads((target / 'resources.json').read_text('utf-8'))
resources['critical'] = [item for item in resources['critical'] if item['path'] not in names] + entries
(target / 'resources.json').write_text(json.dumps(resources, ensure_ascii=False, indent=2), 'utf-8')
from desktop.refresh_delivery_frontend import main
sys.argv = ['refresh', str(target)]
main()
verify_resources(resolve_paths(install=target, user=project / '.tmp/storage-sync-check'))
print('Storage update synchronized; package resource checks passed.')
