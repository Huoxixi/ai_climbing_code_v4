"""Resume only the exact failed companion installation, preserving its database."""
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from datetime import datetime,timezone

def expected_unit(m,node):
 return f'''[Unit]
Description=Friends study library
After=network.target
[Service]
Type=simple
User=study-friends
Group=study-friends
WorkingDirectory={m.BASE}/current
EnvironmentFile={m.ENV}
ExecStart={node} {m.BASE}/current/server.mjs
Restart=on-failure
RestartSec=4
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={m.DATA}
UMask=0077
[Install]
WantedBy=multi-user.target
'''.encode()

def validate_existing(m,metadata,payload,node):
 if metadata.get('recoverRelease')!=metadata['release']:raise RuntimeError('No explicit failed release to recover')
 release=m.BASE/'releases'/metadata['recoverRelease']
 if not (m.BASE/'current').is_symlink() or (m.BASE/'current').resolve()!=release.resolve():raise RuntimeError('Unexpected existing study release')
 if set(p.relative_to(release).as_posix() for p in release.rglob('*') if p.is_file())!=set(payload):raise RuntimeError('Unexpected files in existing study release')
 for name,body in payload.items():
  p=release/name
  if p.is_symlink() or p.read_bytes()!=body:raise RuntimeError('Existing application changed; no overwrite performed')
 expected_env=f'PORT={m.PORT}\nPUBLIC_ORIGIN={m.ORIGIN}\nDATA_DIR={m.DATA}\nTRUST_PROXY=1\n'.encode()
 if m.ENV.is_symlink() or m.ENV.read_bytes()!=expected_env:raise RuntimeError('Unexpected existing environment')
 if m.UNIT.is_symlink() or m.UNIT.read_bytes()!=expected_unit(m,node):raise RuntimeError('Unexpected existing unit')
 if m.DATA.is_symlink() or not m.DATA.is_dir():raise RuntimeError('Unexpected data directory')
 snippet=m.SNIPPET.read_bytes()
 if m.SNIPPET.is_symlink() or m.digest(snippet)!=metadata['expectedSnippetSHA256']:raise RuntimeError('Unexpected existing Nginx snippet')
 return snippet

def backup_database(data,backup):
 database=data/'study.sqlite'
 if database.exists():
  with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup/'study.sqlite')) as target:source.backup(target)
  (backup/'study.sqlite').chmod(0o600)

def recover(m,metadata,payload,node):
 snippet=validate_existing(m,metadata,payload,node)
 original=m.VHOST.read_bytes();edited=m.plan_vhost(original);m.run('nginx','-t')
 before={'climbingHome':m.digest(m.request('/')),'health':m.digest(m.request('/api/health')),'ai41':m.digest(m.request('/ai41/'))}
 backup=Path('/var/backups/study-friends')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-recovery');backup.mkdir(parents=True,mode=0o700)
 (backup/m.VHOST.name).write_bytes(original);(backup/m.VHOST.name).chmod(0o600);backup_database(m.DATA,backup)
 changed=False
 try:
  m.run('systemctl','start','study-friends')
  for attempt in range(30):
   try:
    with m.urllib.request.urlopen(f'http://127.0.0.1:{m.PORT}/study/api/health',timeout=2) as response:
     if json.load(response).get('ok'):break
   except Exception:
    if attempt==29:raise RuntimeError('Study service not healthy')
   m.time.sleep(.2)
  if m.VHOST.read_bytes()!=original:raise RuntimeError('Virtual host changed during preparation')
  m.atomic(m.VHOST,edited);changed=True;m.run('nginx','-t');m.run('systemctl','reload','nginx');m.wait_publication()
  after={'climbingHome':m.digest(m.request('/?project=climbing')),'health':m.digest(m.request('/api/health')),'ai41':m.digest(m.request('/ai41/'))}
  if before!=after:raise RuntimeError('Original website changed during recovery')
  m.run('systemctl','enable','study-friends')
  report={'status':'published','release':metadata['release'],'origin':m.ORIGIN,'studyURL':m.ORIGIN+'/study/','climbingURL':m.ORIGIN+'/?project=climbing','registrationURL':m.ORIGIN+'/study/#register','before':before,'after':after,'backup':str(backup),'recoveredExactRelease':True,'existingDatabasePreserved':True,'node':m.run(node,'--version')}
  m.atomic(backup/'receipt.json',json.dumps(report,ensure_ascii=False,indent=2).encode(),0o600);return report
 except Exception:
  if changed:m.atomic(m.VHOST,original);m.run('nginx','-t');m.run('systemctl','reload','nginx')
  m.subprocess.run(['systemctl','stop','study-friends'],capture_output=True);raise
