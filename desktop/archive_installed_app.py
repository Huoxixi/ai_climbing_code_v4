"""Archive an installed desktop program, excluding user data and machine credentials."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import zipfile

DIRECTORIES={'backend','frontend','desktop','installer','licenses','models','runtime','scripts','third_party_source','vendor','.github'}
ROOT_FILES={'ClimbingAssistant.exe','run-local.py','setup.ps1','install.cmd','LICENSE','README.md','SECURITY.md',
            'CONTRIBUTING.md','THIRD_PARTY_NOTICES.md','THIRD_PARTY_UPDATE_NOTICES.md','安装指引.txt','.gitattributes','.gitignore'}
FORBIDDEN={'.local','.private','.git','.venv','node_modules','__pycache__','logs','cache','tmp'}

def allowed(relative):
    parts=relative.parts
    if any(part in FORBIDDEN or part.startswith('.tmp') for part in parts):return False
    if relative.as_posix()=='backend/data' or relative.as_posix().startswith('backend/data/'):return False
    if any(part=='.env' or part.startswith('.env.') and not part.endswith('.example') for part in parts):return False
    if relative.suffix.lower() in {'.log','.sqlite','.sqlite3','.db','.pyc','.pyo','.pem','.key'}:
        # The bundled CA certificates are public runtime dependencies.
        return parts[:2]==('runtime','Lib') and relative.name=='cacert.pem'
    if parts[0] not in {'runtime','vendor','third_party_source'} and relative.suffix.lower() in {'.mp4','.mov','.webm','.jpg','.jpeg','.png'}:
        # Keep hashed, shipped interface artwork; never include user/test media.
        return parts[:3]==('frontend','dist','assets') and len(parts)==4 and bool(re.search(r'-[A-Za-z0-9_-]{8,}\.(jpg|jpeg|png)$',relative.name))
    return parts[0] in DIRECTORIES or len(parts)==1 and parts[0] in ROOT_FILES

def archive(source,output,version,commit):
    if not re.fullmatch(r'[0-9A-Za-z._-]+',version) or not re.fullmatch(r'[0-9a-f]{40}',commit):
        raise RuntimeError('Expected a version and immutable source commit')
    if source.is_symlink():raise RuntimeError('A linked install directory is not an archive input')
    source=source.resolve(strict=True)
    if source.is_symlink() or not (source/'ClimbingAssistant.exe').is_file() or not (source/'runtime/python.exe').is_file():
        raise RuntimeError('Expected the real installed desktop application')
    if output.exists():raise RuntimeError('Existing archive preserved; use a new output path')
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest=[]
    prefix='ClimbingAssistant-'+version
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as bundle:
        paths=[]
        for directory,directories,files in os.walk(source,followlinks=False):
            base=Path(directory)
            directories[:]=sorted(name for name in directories if allowed((base/name).relative_to(source)))
            for name in sorted(files):
                path=base/name
                if allowed(path.relative_to(source)):paths.append(path)
        for path in paths:
            relative=path.relative_to(source)
            if not allowed(relative):continue
            if path.is_symlink():raise RuntimeError('Unexpected program link: '+str(relative))
            if not path.is_file():continue
            before=path.stat()
            digest=hashlib.sha256()
            with path.open('rb') as incoming,bundle.open(prefix+'/'+relative.as_posix(),'w',force_zip64=True) as outgoing:
                while chunk:=incoming.read(1024*1024):digest.update(chunk);outgoing.write(chunk)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('Program changed during snapshot')
            manifest.append({'path':relative.as_posix(),'bytes':before.st_size,'sha256':digest.hexdigest()})
            if len(manifest)%1000==0:print('ARCHIVED_PROGRAM_FILES='+str(len(manifest)),flush=True)
        update={'version':version,'update_label':'本机已更新：2026.10.17','head':'circle-head-display-v2','background':'empty-scene-wall-reference-v2'}
        bundle.writestr(prefix+'/local-update.json',json.dumps(update,ensure_ascii=False,indent=2))
        bundle.writestr(prefix+'/程序快照说明.txt','解压完整文件夹后，双击 ClimbingAssistant.exe 启动。\n这是当前实际安装程序的完整程序快照，包含运行环境和模型；不含个人视频、记录、密钥或安装器的机器所有权信息。\n程序继续使用既有公开版的独立数据位置。源码提交：'+commit+'\n')
        bundle.writestr(prefix+'/PROGRAM_SNAPSHOT.json',json.dumps({'runtime_version':version,'source_commit':commit,
            'scope':'installed program, runtime, fixed model assets and licenses; no user data or machine credentials',
            'files':manifest},ensure_ascii=False,indent=2))
    with output.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if output.stat().st_size>=2*1024**3:raise RuntimeError('Archive exceeds the GitHub asset limit; preserved locally')
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n',encoding='ascii')
    print(json.dumps({'file':str(output),'bytes':output.stat().st_size,'program_files':len(manifest),'sha256':digest}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--source-commit',required=True)
    args=parser.parse_args()
    archive(args.source,args.output,args.version,args.source_commit)
