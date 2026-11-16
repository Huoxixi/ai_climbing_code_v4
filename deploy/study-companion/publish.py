"""Companion-only publication through the existing reviewed GitHub release channel.

Does not switch /opt/ai-climbing/current or change SSH permissions.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parent
CURRENT=Path('/opt/ai-climbing/current')
RUNTIME=Path('/opt/study-friends-node24')

def load_module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def preflight(metadata,current=CURRENT):
    if metadata.get('schema')!=1 or metadata.get('mode')!='study-companion':
        raise RuntimeError('Unexpected companion manifest')
    if not re.fullmatch('[a-f0-9]{40}',metadata.get('expectedClimbingCommit','')):
        raise RuntimeError('Invalid climbing baseline')
    if (current/'RELEASE_SHA').read_text().strip()!=metadata['expectedClimbingCommit']:
        raise RuntimeError('Climbing changed since review; refusing publication')
    if shutil.disk_usage('/opt').free<300*1024*1024:
        raise RuntimeError('Companion requires 300 MiB of free space')

def node_runtime(config):
    existing=shutil.which('node')
    if existing:
        version=subprocess.check_output([existing,'--version'],text=True).strip()
        match=re.fullmatch(r'v24\.(\d+)\.(\d+)',version)
        if match and int(match[1])>=11:return existing
    if platform.machine() not in ('x86_64','amd64'):
        raise RuntimeError('This reviewed runtime is Linux x86_64 only')
    if RUNTIME.exists():
        binary=RUNTIME/'bin/node'
        if binary.is_symlink() or binary.stat().st_uid!=0 or binary.stat().st_mode&0o022 or subprocess.check_output([str(binary),'--version'],text=True).strip()!='v'+config['version']:raise RuntimeError('Unexpected existing companion runtime')
        return str(binary)
    with tempfile.TemporaryDirectory(prefix='study-runtime-') as temporary:
        archive=Path(temporary)/'node.tar.xz'
        request=urllib.request.Request(config['url'],headers={'User-Agent':'Study-Companion-Release'})
        with urllib.request.urlopen(request,timeout=90) as response,archive.open('wb') as output:
            shutil.copyfileobj(response,output)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=config['sha256']:
            raise RuntimeError('Official runtime checksum mismatch')
        prefix=f"node-v{config['version']}-linux-x64/"
        staged=Path(temporary)/'runtime';(staged/'bin').mkdir(parents=True)
        with tarfile.open(archive) as bundle:
            for name,target in [('bin/node','bin/node'),('LICENSE','LICENSE')]:
                member=bundle.getmember(prefix+name)
                if not member.isfile():raise RuntimeError('Unexpected runtime member')
                with bundle.extractfile(member) as source:(staged/target).write_bytes(source.read())
        (staged/'bin/node').chmod(0o755)
        expected='v'+config['version']
        if subprocess.check_output([str(staged/'bin/node'),'--version'],text=True).strip()!=expected:
            raise RuntimeError('Downloaded runtime version mismatch')
        shutil.copytree(staged,RUNTIME)
        RUNTIME.chmod(0o755);(RUNTIME/'bin').chmod(0o755);(RUNTIME/'bin/node').chmod(0o755)
    return str(RUNTIME/'bin/node')

def publish(tag):
    if os.name!='posix' or os.geteuid()!=0:raise RuntimeError('Use the reviewed standard server deployment command')
    if not re.fullmatch(r'pilot-v\d{4}\.\d{2}\.\d{2}-rc\d+',tag):raise RuntimeError('Invalid immutable tag')
    metadata,_=load_module('study_bundle_check','check_bundle.py').check()
    if metadata.get('tag')!=tag:raise RuntimeError('Tag does not match the reviewed companion release')
    preflight(metadata)
    installer=load_module('study_companion_install','install.py')
    node=node_runtime(metadata['runtime'])
    if any(p.exists() for p in [installer.BASE,installer.DATA,installer.SNIPPET,installer.UNIT,installer.ENV]):
        result=load_module('study_companion_recovery','recover.py').recover(installer,metadata,load_module('study_recovery_payload','check_bundle.py').check()[1],node)
    else:
        installer.plan_vhost(installer.VHOST.read_bytes())
        installer.install(ROOT/'app.zip',node,apply=False)
        result=installer.install(ROOT/'app.zip',node,apply=True)
    if (CURRENT/'RELEASE_SHA').read_text().strip()!=metadata['expectedClimbingCommit']:
        raise RuntimeError('Climbing release changed during companion publication')
    result.update(tag=tag,climbingCommitPreserved=metadata['expectedClimbingCommit'],publicationMode='companion-only')
    print('STUDY_COMPANION_PUBLICATION='+json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('One immutable tag required')
    publish(sys.argv[1])
