"""Back up only the active isolated photo preview and copy to durable dev data."""
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[2]
boards=httpx.get('http://127.0.0.1:8004/api/photo-routes/v2/boards',timeout=10).json()
if not boards: raise SystemExit('No current preview photos to migrate.')
board_id=boards[0]['id']
sources=[]
for folder in Path(tempfile.gettempdir()).glob('boulder-ui-test-*'):
    database=folder/'photo_routes_v2.sqlite3'
    if not database.is_file(): continue
    with sqlite3.connect(str(database)) as db:
        if db.execute('SELECT 1 FROM board_versions WHERE id=?',(board_id,)).fetchone(): sources.append(folder)
if len(sources)!=1: raise SystemExit('Active preview database could not be uniquely identified.')
source=sources[0]
backup=root/'.local/backups'/('photo-preview-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
target=root/'.local/photo-development/data/photo_routes'
if (target/'photo_routes_v2.sqlite3').exists():
    with sqlite3.connect(str(target/'photo_routes_v2.sqlite3')) as db:
        if db.execute('SELECT COUNT(*) FROM board_versions').fetchone()[0]: raise SystemExit('Durable store already contains photos; no overwrite performed.')
backup.mkdir(parents=True);target.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(str(source/'photo_routes_v2.sqlite3')) as src, sqlite3.connect(str(backup/'photo_routes_v2.sqlite3')) as dst: src.backup(dst)
shutil.copytree(source/'assets',backup/'assets')
with sqlite3.connect(str(backup/'photo_routes_v2.sqlite3')) as src, sqlite3.connect(str(target/'photo_routes_v2.sqlite3')) as dst: src.backup(dst)
shutil.copytree(backup/'assets',target/'assets',dirs_exist_ok=True)
with sqlite3.connect(str(target/'photo_routes_v2.sqlite3')) as db:
    # This is an isolated single-user preview, mapped to the full app local owner.
    for table in ['board_versions','routes','processing_jobs']:
        db.execute(f'UPDATE {table} SET owner=? WHERE owner=?',('owner','boulder-ui-test'))
    db.execute("UPDATE processing_jobs SET status='cancelled' WHERE status IN ('queued','running')")
    db.commit()
(backup/'migration.json').write_text(json.dumps({'source':str(source),'target':str(target),'boards':len(boards)},indent=2),encoding='utf-8')
print('Photo-only backup and migration complete:',len(boards),'boards')
