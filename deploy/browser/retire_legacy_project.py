"""Explicit old-project retirement; preserve current code until browser activation.

Only use after the user's 2026-10-18 instruction to remove the old server project.
Personal data, environment files, production configuration and backups are excluded.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

RELEASES=Path('/opt/ai-climbing/releases')
CURRENT=Path('/opt/ai-climbing/current')
SOURCE=Path('/root/ai_climbing_code')
DATA=Path('/var/lib/ai-climbing/data')
OPS=Path('/var/lib/ai-climbing/ops')
OLD_TAGS=('pilot-v2026.09.22-rc26','pilot-v2026.09.23-rc28','pilot-v2026.10.01-rc29')
OLD_SHA='fea6690e4bf4530166b1a66accbb3c3b3cfd0628'
RECEIPTS=Path('/var/backups/ai-climbing/legacy-project-retirement')
LOCK=Path('/run/ai-climbing-deploy/release.lock')

def run(*args,**kwargs):
    return subprocess.check_output(args,text=True,**kwargs).strip()

def checked_directory(path):
    if path.is_symlink() or path.resolve()!=path or not path.is_dir():
        raise RuntimeError('Unexpected or redirected program directory: '+str(path))
    return path

def protected(name):
    parts=Path(name).parts
    return (any(p in {'.local','.private','node_modules','.venv','__pycache__'} for p in parts)
            or name.startswith('backend/data/') or name=='backend/data'
            or any(p=='.env' or p.startswith('.env.') and not p.endswith('.example') for p in parts))

def validate_release(path,current):
    checked_directory(path)
    if path.parent!=RELEASES or path==current or path.name not in OLD_TAGS:
        raise RuntimeError('Refusing to remove an active/unknown release')
    if not (path/'RELEASE_SHA').is_file():
        raise RuntimeError('Incomplete old release')
    data=path/'backend/data'
    if (data.exists() or data.is_symlink()) and (not data.is_symlink() or data.resolve()!=DATA):
        raise RuntimeError('Old release contains nonstandard data; preserved')
    for item in (path/'.local',path/'.private',path/'.env',path/'backend/.env'):
        if item.exists() or item.is_symlink():
            raise RuntimeError('Protected content found in old release; preserved')

def snapshot_build_source(receipt):
    if not (SOURCE/'.git').is_dir():return []
    checked_directory(SOURCE)
    if run('git','-C',str(SOURCE),'rev-parse','HEAD')!=OLD_SHA:
        raise RuntimeError('Build source differs from the verified old release; preserved')
    if run('git','-C',str(SOURCE),'status','--porcelain','--untracked-files=no'):
        raise RuntimeError('Build source has changes; review before removing Git metadata')
    names=run('git','-C',str(SOURCE),'ls-files','-z').split('\0')
    selected=[]
    with tarfile.open(receipt/'old-build-source.tar.gz','w:gz') as archive:
        for name in names:
            if not name or protected(name):continue
            path=SOURCE/name
            if not path.exists():continue
            if path.is_symlink() or not path.is_file() or path.resolve()!=path or not path.resolve().is_relative_to(SOURCE):
                raise RuntimeError('Unexpected source link; preserved')
            archive.add(path,arcname=name,recursive=False)
            selected.append(name)
    (receipt/'source-program-files.json').write_text(json.dumps(selected),encoding='utf-8')
    return selected

def run_retirement(phase):
    if os.geteuid()!=0:raise RuntimeError('Run in the production root terminal')
    current=CURRENT.resolve(strict=True)
    if current.parent!=RELEASES or not (current/'RELEASE_SHA').is_file():raise RuntimeError('Invalid current release')
    with urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5) as response:health=json.load(response)
    if health.get('status')!='success':raise RuntimeError('Current service is not healthy')
    if phase=='finish' and (health.get('compute')!='browser-only' or not (current/'BROWSER_RELEASE.json').is_file()):
        raise RuntimeError('Verify browser-only activation before final retirement')
    candidates=[RELEASES/tag for tag in OLD_TAGS if (RELEASES/tag).exists() and (RELEASES/tag)!=current]
    for candidate in candidates:validate_release(candidate,current)
    print(json.dumps({'phase':phase,'current':str(current),'old_program_releases':[str(p) for p in candidates],
                      'free_bytes':shutil.disk_usage(RELEASES).free,'protected':['data','configuration','backups','models','resource-tests']},ensure_ascii=False),flush=True)
    if phase=='audit':return
    RECEIPTS.mkdir(parents=True,exist_ok=True,mode=0o700)
    receipt=RECEIPTS/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+phase)
    receipt.mkdir(mode=0o700)
    if phase=='prepare':
        if subprocess.run(['pgrep','-f','[d]eploy_release.sh|[p]ip (install|wheel|download)|[n]pm (ci|install)'],stdout=subprocess.DEVNULL).returncode==0:
            raise RuntimeError('A deployment or dependency installation is active; preserved')
        subprocess.run(['/usr/local/lib/ai-climbing/backup_data.sh','pre-deploy'],check=True)
        backup=(OPS/'last-backup.env').read_text()
        if 'RESULT=success\n' not in backup or 'REMOTE_VERIFIED=true\n' not in backup:
            raise RuntimeError('Verified remote pre-deploy backup is required')
        source_files=snapshot_build_source(receipt)
        # Generated build dependencies and Git checkout metadata are rebuildable.
        # Preserve the source snapshot and every untracked data/configuration file.
        build_paths=[SOURCE/'frontend/node_modules',SOURCE/'backend/.venv']
        if source_files:build_paths.append(SOURCE/'.git')
        for path in build_paths:
            if not path.exists():continue
            checked_directory(path)
            probe=subprocess.run(['pgrep','-f',str(path)],stdout=subprocess.DEVNULL)
            if probe.returncode==0:raise RuntimeError('Build directory is in use; preserved: '+str(path))
        for path in build_paths:
            if path.exists():shutil.rmtree(path)
    removed=[]
    for candidate in candidates:
        validate_release(candidate,CURRENT.resolve(strict=True))
        removed.append({'tag':candidate.name,'sha':(candidate/'RELEASE_SHA').read_text().strip()})
        shutil.rmtree(candidate)
    # After activation, retire only the source files already archived by prepare.
    if phase=='finish':
        snapshots=sorted(RECEIPTS.glob('*-prepare/source-program-files.json'))
        if snapshots:
            names=json.loads(snapshots[-1].read_text())
            for name in names:
                if protected(name):raise RuntimeError('Protected source entry')
                path=SOURCE/name
                if path.is_file() and not path.is_symlink() and path.resolve()==path and path.resolve().is_relative_to(SOURCE):path.unlink()
        # Retain historical model/test materials as private backups, away from the
        # active project. They are not uploaded to GitHub or served by the web app.
        archived=[]
        for label,path in [('models',Path('/opt/ai-climbing/models')),
                           ('resource-tests',Path('/opt/ai-climbing/resource-tests')),
                           ('source-model-assets',SOURCE/'backend/model_assets'),
                           ('source-built-frontend',SOURCE/'frontend/dist')]:
            if not path.exists():continue
            checked_directory(path)
            if subprocess.run(['pgrep','-f',str(path)],stdout=subprocess.DEVNULL).returncode==0:
                raise RuntimeError('Historical project asset is still in use; preserved')
            path.rename(receipt/label)
            archived.append(label)
        (receipt/'archived-program-assets.json').write_text(json.dumps(archived),encoding='utf-8')
    (receipt/'receipt.json').write_text(json.dumps({'phase':phase,'removed_releases':removed,'active_release':str(current),
        'free_bytes_after':shutil.disk_usage(RELEASES).free,'data_modified':False,'configuration_modified':False},indent=2),encoding='utf-8')
    print('RETIREMENT_RECEIPT='+str(receipt),flush=True)
    print('FREE_BYTES_AFTER='+str(shutil.disk_usage(RELEASES).free),flush=True)
    if phase=='prepare' and shutil.disk_usage(RELEASES).free<8*1024**3:
        raise RuntimeError('Still less than 8 GiB available. Current site retained; do not deploy yet.')

def main(phase):
    if os.geteuid()!=0:raise RuntimeError('Run in the production root terminal')
    if os.name=='posix':
        import fcntl
        LOCK.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with LOCK.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            run_retirement(phase)
    else:
        run_retirement(phase)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['audit','prepare','finish'])
    main(parser.parse_args().phase)
