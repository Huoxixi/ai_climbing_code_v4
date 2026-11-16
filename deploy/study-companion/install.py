"""Initial independent installation. Dry-run by default; never changes climbing code/data."""
import argparse,hashlib,json,os,re,shutil,socket,subprocess,tempfile,time,urllib.request,zipfile
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
VHOST=Path('/etc/nginx/conf.d/panyandingxian-public.conf');BASE=Path('/opt/study-friends');DATA=Path('/var/lib/study-friends');SNIPPET=Path('/etc/nginx/snippets/study-friends.conf');UNIT=Path('/etc/systemd/system/study-friends.service');ENV=Path('/etc/study-friends.env');PORT=18876;ORIGIN='https://www.panyandingxian.cn'
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout.strip()
def digest(b):return hashlib.sha256(b).hexdigest()
def request(path):
 with urllib.request.urlopen(urllib.request.Request(ORIGIN+path,headers={'Cache-Control':'no-cache'}),timeout=20) as r:return r.read()

def wait_publication(attempts=20,delay=.5):
 last={}
 for attempt in range(attempts):
  try:
   home=request('/');health=request('/study/api/health');last={'homeSHA256':digest(home),'studyHealthSHA256':digest(health)}
   if b'/study/' in home and json.loads(health).get('app')=='study-friends' and json.loads(health).get('ok'):return
  except Exception as e:last={'type':type(e).__name__}
  if attempt+1<attempts:time.sleep(delay)
 raise RuntimeError('Public portal did not become ready: '+json.dumps(last))
def atomic(path,data,mode=0o644):
 f=tempfile.NamedTemporaryFile(dir=path.parent,delete=False);name=f.name
 try:f.write(data);f.close();os.chmod(name,mode);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
def plan_vhost(original):
 anchor=b'    root /opt/ai-climbing/current/frontend/dist;'
 lines=original.splitlines(keepends=True);matches=[i for i,line in enumerate(lines) if line.rstrip(b'\r\n')==anchor]
 if len(matches)!=1 or b'location = / {' in original or b'study-friends' in original:raise ValueError('Original virtual host needs review; no configuration changed')
 i=matches[0];newline=b'\r\n' if lines[i].endswith(b'\r\n') else b'\n'
 lines[i]=lines[i]+b'    include /etc/nginx/snippets/study-friends.conf;'+newline
 return b''.join(lines)
def unpack(archive):
 with zipfile.ZipFile(archive) as z:
  names=z.namelist();manifest=json.loads(z.read('release.json'));expected=set(manifest['files'])|{'release.json'}
  if len(names)!=len(set(names)) or set(names)!=expected:raise ValueError('Unexpected release entries')
  out={}
  for n,want in manifest['files'].items():
   p=PurePosixPath(n)
   if p.is_absolute() or '..' in p.parts or '\\' in n or not (n in ['server.mjs','package.json'] or n.startswith('public/')):raise ValueError('Unsafe archive path')
   if z.getinfo(n).file_size>2*1024*1024:raise ValueError('Unexpected release file size')
   b=z.read(n)
   if digest(b)!=want:raise ValueError('Release checksum mismatch')
   out[n]=b
 return out,manifest
def install(archive,node,apply=False):
 if os.name!='posix' or os.geteuid()!=0:raise RuntimeError('Run on the Linux server using its existing administrator access')
 import pwd
 if any(p.exists() for p in [BASE,DATA,SNIPPET,UNIT,ENV]):raise RuntimeError('Existing study-friends installation detected; use a reviewed update, not initial installation')
 if not re.fullmatch(r'/[A-Za-z0-9_./-]+',node):raise ValueError('Use an absolute Node executable path')
 version=run(node,'--version');m=re.fullmatch(r'v24\.(\d+)\.(\d+)',version)
 if not m or int(m[1])<11:raise RuntimeError('An isolated Node 24.11+ runtime is required; no existing runtime was changed')
 with socket.socket() as s:s.bind(('127.0.0.1',PORT))
 payload,manifest=unpack(archive);original=VHOST.read_bytes();edited=plan_vhost(original);run('nginx','-t')
 before={'climbingHome':digest(request('/')),'health':digest(request('/api/health')),'ai41':digest(request('/ai41/'))}
 report={'status':'ready','release':manifest['version'],'before':before,'origin':ORIGIN,'studyURL':ORIGIN+'/study/','climbingURL':ORIGIN+'/?project=climbing','node':version,'apply':apply}
 if not apply:return report
 backup=Path('/var/backups/study-friends')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup.mkdir(parents=True,mode=0o700);(backup/VHOST.name).write_bytes(original);os.chmod(backup/VHOST.name,0o600)
 try:pwd.getpwnam('study-friends')
 except KeyError:run('useradd','--system','--home-dir',str(DATA),'--shell','/usr/sbin/nologin','study-friends')
 owner=pwd.getpwnam('study-friends');BASE.mkdir(mode=0o755);release=BASE/'releases'/manifest['version'];release.mkdir(parents=True,mode=0o755)
 for name,b in payload.items():p=release/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);os.chmod(p,0o644)
 (BASE/'current').symlink_to(release,target_is_directory=True);DATA.mkdir(mode=0o700);os.chown(DATA,owner.pw_uid,owner.pw_gid)
 atomic(ENV,f'PORT={PORT}\nPUBLIC_ORIGIN={ORIGIN}\nDATA_DIR={DATA}\nTRUST_PROXY=1\n'.encode(),0o600)
 unit=f'''[Unit]
Description=Friends study library
After=network.target
[Service]
Type=simple
User=study-friends
Group=study-friends
WorkingDirectory={BASE}/current
EnvironmentFile={ENV}
ExecStart={node} {BASE}/current/server.mjs
Restart=on-failure
RestartSec=4
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={DATA}
UMask=0077
[Install]
WantedBy=multi-user.target
''';atomic(UNIT,unit.encode())
 snippet=f'''# Only the exact home route and /study/ are added. Existing static/API/ai41 paths remain.
location = / {{
    if ($arg_project = climbing) {{ rewrite ^ /index.html last; }}
    proxy_pass http://127.0.0.1:{PORT};
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}}
location = /study {{ return 302 /study/; }}
location ^~ /study/ {{
    client_max_body_size 46m;
    proxy_pass http://127.0.0.1:{PORT};
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 40s;
}}
'''
 changed=False
 try:
  run('systemctl','daemon-reload');run('systemctl','start','study-friends')
  import time
  for attempt in range(30):
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/study/api/health',timeout=2) as response:assert json.load(response)['ok']
    break
   except Exception:
    if attempt==29:raise RuntimeError('New service failed health check')
    time.sleep(.2)
  if VHOST.read_bytes()!=original:raise RuntimeError('Virtual host changed during preparation')
  atomic(SNIPPET,snippet.encode());atomic(VHOST,edited);changed=True;run('nginx','-t');run('systemctl','reload','nginx')
  wait_publication()
  after={'climbingHome':digest(request('/?project=climbing')),'health':digest(request('/api/health')),'ai41':digest(request('/ai41/'))}
  if before!=after:raise RuntimeError('Original project verification failed')
  run('systemctl','enable','study-friends');report.update(status='published',after=after,backup=str(backup),registrationURL=ORIGIN+'/study/#register');atomic(backup/'receipt.json',json.dumps(report,ensure_ascii=False,indent=2).encode(),0o600);return report
 except Exception:
  if changed:atomic(VHOST,original);run('nginx','-t');run('systemctl','reload','nginx')
  subprocess.run(['systemctl','stop','study-friends'],capture_output=True)
  raise
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--node',default='/usr/bin/node');p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(install(a.archive,a.node,a.apply),ensure_ascii=False,indent=2))
