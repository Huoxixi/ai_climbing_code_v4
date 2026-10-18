"""Sync the user's requested combined progress; preserve rollback and data."""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_package


def main():
    deliveries=Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target=(deliveries/('AiClimbing-'+VERSION)).resolve()
    if target.parent!=deliveries:raise RuntimeError('Unexpected install path')
    paths=resolve_paths(install=target,user=PROJECT/'.tmp/progress-resource-check')
    verify_resources(paths);assert_local_package(target)
    backup=Path('D:/ai_climbing_code/verification/replay-progress-20261013')/('app-'+datetime.now().strftime('%Y%m%d%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    names=['backend/core/'+n for n in ('climb_replay.py','replay_hold_colors.py','replay_hold_fusion.py',
        'replay_hold_evidence.py','photo_route_analysis.py','replay_pose_rtmw.py')]
    metadata=['local-update.json','file-manifest.json','resources.json']
    existing=[]
    for name in names+metadata:
        if (target/name).exists():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target/name,dest);existing.append(name)
    def atomic(path,value):
        temp=path.with_name(path.name+'.progress-update.tmp')
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8');os.replace(temp,path)
    try:
        for name in names:
            temp=(target/name).with_suffix('.progress-update.tmp')
            shutil.copy2(PROJECT/name,temp);os.replace(temp,target/name)
        update=json.loads((target/'local-update.json').read_text('utf-8'))
        update['hold_progress_hotfix']={'date':'2026-10-13','user_authorized_before_full_accuracy_gate':True,
            'colour_version':'replay-material-distribution-v4',
            'included':['previous connected click / neutral / chroma-weighted colour fixes',
                'continuous sample-region support at pixel Lab60 with original median distance preserved',
                'green/cyan boundary sample compatibility','target-independent temporal observation quality',
                'warm material identity requiring distinct confident frames and compatible whole-body distributions',
                'native image-edge / independent-frame representative selection',
                'merge relationship provenance and video volume review candidates'],
            'not_automatic':['manual diagnosis overrides','failed 0.9 masks','failed local crop inference',
                'volume instance overlap repair','single-frame admission'],
            'full_accuracy_verified':False,'user_data_modified':False,'production_deployed':False}
        atomic(target/'local-update.json',update)
        rows=json.loads((target/'file-manifest.json').read_text('utf-8'))
        resources=json.loads((target/'resources.json').read_text('utf-8'))
        changed=names+['local-update.json']
        rows=[r for r in rows if r['path'] not in changed]
        for name in changed:
            p=target/name
            with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            rows.append({'path':name,'bytes':p.stat().st_size,'sha256':digest})
        critical={r['path'] for r in resources['critical']}|set(changed)
        atomic(target/'file-manifest.json',rows)
        atomic(target/'resources.json',{**resources,'critical':[r for r in rows if r['path'] in critical]})
        verify_resources(paths);assert_local_package(target)
    except BaseException:
        for name in existing:shutil.copy2(backup/name,target/name)
        for name in names:
            if name not in existing:(target/name).unlink(missing_ok=True)
        raise
    result={'synced':str(target),'backup':str(backup),'files':names,'resources_verified':True,
        'user_data_modified':False,'production_deployed':False}
    (backup/'sync-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
