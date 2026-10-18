"""Install accepted scored-person recovery; back up program files only."""
import hashlib,json,os,shutil,sys
from pathlib import Path
from datetime import datetime
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from desktop import VERSION
from desktop.paths import resolve_paths
from desktop.launcher import verify_resources
from desktop.package_scope import assert_local_package


def write(path,value):
    temporary=path.with_suffix(path.suffix+'.pose-detection.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
    os.replace(temporary,path)


def main():
    acceptance=json.loads((PROJECT/'.tmp/pose-repair-20261016/detection-acceptance.json').read_text('utf8'))
    if (acceptance['cases']!=10 or acceptance['lost'] or acceptance['changed_common_body']
        or acceptance['changed_common_boxes'] or acceptance['recovered']!=14):
        raise RuntimeError('Accepted original-source regression required')
    deliveries=Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target=(deliveries/('AiClimbing-'+VERSION)).resolve()
    if target.parent!=deliveries:raise ValueError('Unexpected program destination')
    paths=resolve_paths(install=target,user=PROJECT/'.tmp/pose-repair-20261016/install-check')
    verify_resources(paths)
    names=['backend/vendor/rtmlib/tools/object_detection/yolox.py',
           'backend/core/replay_pose_clip.py','backend/core/replay_pose_rtmw.py','backend/core/replay_person_tracks.py']
    metadata=['resources.json','file-manifest.json','local-update.json']
    backup=Path('D:/ai_climbing_code/verification/pose-detection-20261016')/datetime.now().strftime('%Y%m%d%H%M%S')
    backup.mkdir(parents=True,exist_ok=False)
    for name in names+metadata:
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target/name,dest)
    try:
        for name in names:shutil.copy2(PROJECT/name,target/name)
        update=json.loads((target/'local-update.json').read_text('utf8'))
        update['pose_detection_recovery']='2026-10-16: scored two-stage person recovery; 10 original clips, 14 recovered observations, unchanged prior boxes/body coordinates; wrist accuracy remains open'
        write(target/'local-update.json',update)
        changed=names+['local-update.json'];rows=[]
        for name in changed:
            path=target/name
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            rows.append({'path':name,'bytes':path.stat().st_size,'sha256':digest})
        manifest=json.loads((target/'file-manifest.json').read_text('utf8'))
        resources=json.loads((target/'resources.json').read_text('utf8'))
        write(target/'file-manifest.json',[r for r in manifest if r['path'] not in changed]+rows)
        write(target/'resources.json',{**resources,'critical':[r for r in resources['critical'] if r['path'] not in changed]+rows})
        assert_local_package(target);verify_resources(paths)
    except BaseException:
        for name in names+metadata:shutil.copy2(backup/name,target/name)
        raise
    receipt={'target':str(target),'backup':str(backup),'files':names,'resources_verified':True,
        'running_app_restarted':False,'experimental_models_installed':False,'user_data_modified':False}
    write(PROJECT/'.tmp/pose-repair-20261016/install-receipt.json',receipt)
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':main()
