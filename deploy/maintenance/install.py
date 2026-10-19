"""One-time root installation from an immutable, reviewed GitHub tag."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ACTIONS = ('maintenance-status', 'maintenance-network', 'maintenance-tools',
           'maintenance-cleanup-plan', 'maintenance-cleanup', 'maintenance-cancel-download')
MARKER = '# ai-climbing fixed maintenance wrapper v1'


def secure(path, directory=False, owner=0):
    info = path.lstat()
    if path.is_symlink() or path.resolve() != path or info.st_uid != owner or info.st_mode & 0o022:
        raise RuntimeError('Unsafe existing tool or directory; unchanged: '+str(path))
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise RuntimeError('Unexpected file type')


def directory(path, mode=0o755, owner=0):
    path.mkdir(parents=True,exist_ok=True,mode=mode)
    for parent in (path, *path.parents):
        secure(parent,directory=True,owner=owner)


def atomic(path, body, mode):
    fd, name = tempfile.mkstemp(prefix='.maintenance-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            if hasattr(os,'fchmod'): os.fchmod(output.fileno(),mode)
            else: os.chmod(name,mode)
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def install_files(source, sha, root=Path('/'), run=subprocess.run):
    """Root override and command injection exist only for isolated integration tests."""
    def p(value): return root/value.lstrip('/')
    dispatcher=p('/usr/local/sbin/codex-ssh-dispatch')
    launcher=p('/usr/local/sbin/ai-climbing-maintenance')
    sudoers=p('/etc/sudoers.d/ai-climbing-maintenance')
    base=p('/usr/local/sbin/ai-climbing-legacy-ssh-dispatch')
    version=p('/usr/local/lib/ai-climbing/maintenance')/sha
    backups=p('/var/backups/ai-climbing/maintenance-tools')
    for folder,mode in [(dispatcher.parent,0o755),(sudoers.parent,0o750),(base.parent,0o755),(version,0o755),(backups,0o700)]:
        directory(folder,mode)
    secure(dispatcher)
    for file in (launcher,sudoers,base):
        if file.exists() or file.is_symlink(): secure(file)
    if base.exists():
        if MARKER not in dispatcher.read_text() and base.read_bytes()!=dispatcher.read_bytes():
            raise RuntimeError('Original dispatcher differs from retained baseline; preserved')
    elif MARKER in dispatcher.read_text():
        raise RuntimeError('Previous dispatcher baseline missing; unchanged')
    else:
        atomic(base,dispatcher.read_bytes(),0o755)
    contents={'maintenance.py':(source/'deploy/maintenance/maintenance.py').read_bytes(),
              'profile.json':(source/'deploy/browser/profile.json').read_bytes(),
              'SOURCE_SHA':(sha+'\n').encode()}
    compile(contents['maintenance.py'],'maintenance.py','exec')
    for name,body in contents.items():
        file=version/name
        if file.exists() or file.is_symlink():
            secure(file)
            if file.read_bytes()!=body: raise RuntimeError('Immutable tool version differs; preserved')
        else: atomic(file,body,0o644)
    # Installed paths are fixed production paths, even in the isolated installer test.
    dispatch_body=('#!/bin/bash\nset -Eeuo pipefail\n'+MARKER+'\n'
        'original="${SSH_ORIGINAL_COMMAND:-}"\ncase "$original" in\n  '+ '|'.join(ACTIONS)+')\n'
        '    exec /usr/bin/sudo -n /usr/local/sbin/ai-climbing-maintenance "$original" ;;\n'
        '  maintenance-*) echo "Invalid fixed maintenance action." >&2; exit 64 ;;\n'
        '  *) exec /usr/local/sbin/ai-climbing-legacy-ssh-dispatch ;;\nesac\n').encode()
    launcher_body=("#!/bin/bash\nset -Eeuo pipefail\n"
        "exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 "
        f"/usr/bin/python3.12 -I /usr/local/lib/ai-climbing/maintenance/{sha}/maintenance.py \"$@\"\n").encode()
    sudoers_body=('codex-ops ALL=(root) NOPASSWD: NOSETENV: '+', '.join(
        '/usr/local/sbin/ai-climbing-maintenance '+action for action in ACTIONS)+'\n').encode()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup=backups/stamp
    backup.mkdir(mode=0o700)
    previous={}
    for name,file in [('dispatcher',dispatcher),('launcher',launcher),('sudoers',sudoers)]:
        previous[file]=(file.read_bytes(),stat.S_IMODE(file.stat().st_mode)) if file.exists() else None
        if previous[file]: shutil.copy2(file,backup/name)
    staged=[]
    try:
        for file,body,mode in [(dispatcher,dispatch_body,0o755),(launcher,launcher_body,0o755),(sudoers,sudoers_body,0o440)]:
            temporary=file.parent/('.maintenance-check-'+stamp+'-'+file.name)
            atomic(temporary,body,mode)
            staged.append(temporary)
            command=['/usr/sbin/visudo','-cf',str(temporary)] if file==sudoers else ['/usr/bin/bash','-n',str(temporary)]
            run(command,check=True,capture_output=True,text=True,timeout=10)
        for file,body,mode in [(launcher,launcher_body,0o755),(sudoers,sudoers_body,0o440),(dispatcher,dispatch_body,0o755)]:
            atomic(file,body,mode)
        run(['/usr/sbin/visudo','-c'],check=True,capture_output=True,text=True,timeout=10)
        probe=run(['/usr/sbin/runuser','-u','codex-ops','--','/usr/bin/sudo','-n',
                   '/usr/local/sbin/ai-climbing-maintenance','maintenance-tools'],check=True,capture_output=True,text=True,timeout=10)
        if json.loads(probe.stdout)['source_sha']!=sha: raise RuntimeError('Restricted sudo probe failed')
    except BaseException:
        for file,old in previous.items():
            if old is None: file.unlink(missing_ok=True)
            else: atomic(file,*old)
        raise
    finally:
        for file in staged: file.unlink(missing_ok=True)
    receipt={'source_sha':sha,'actions':ACTIONS,'existing_dispatcher_sha256':hashlib.sha256(previous[dispatcher][0]).hexdigest(),
             'authorized_keys_modified':False,'sshd_modified':False,'data_modified':False,'application_configuration_modified':False,
             'ssh_dispatcher_and_sudoers_modified':True,
             'backup':str(backup),'status':'installed'}
    atomic(backup/'receipt.json',json.dumps(receipt,indent=2).encode(),0o600)
    return receipt


def main(tag):
    import fcntl
    if os.geteuid()!=0: raise RuntimeError('Run once in the existing root console')
    if not re.fullmatch(r'pilot-v\d{4}\.\d{2}\.\d{2}-rc\d+',tag): raise RuntimeError('Invalid immutable tag')
    source=Path(__file__).resolve().parents[2]
    secure(source,directory=True)
    def git(*args): return subprocess.check_output(['git','-C',str(source),*args],text=True).strip()
    sha=git('rev-parse','HEAD')
    if sha!=git('rev-parse',f'refs/tags/{tag}^{{commit}}'): raise RuntimeError('Source does not match tag')
    subprocess.run(['git','-C',str(source),'merge-base','--is-ancestor','HEAD','origin/main'],check=True)
    subprocess.run(['git','-C',str(source),'diff-index','--quiet','HEAD','--'],check=True)
    subprocess.run(['/usr/sbin/visudo','-c'],check=True,capture_output=True)
    lock=Path('/run/ai-climbing-deploy/release.lock')
    directory(lock.parent,0o700)
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if info.st_uid!=0 or info.st_mode&0o077: raise RuntimeError('Deployment lock is not private')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=install_files(source,sha)
    finally: os.close(fd)
    print(json.dumps(receipt))
    print('MAINTENANCE_READY='+sha)


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('One reviewed immutable tag is required')
    main(sys.argv[1])
