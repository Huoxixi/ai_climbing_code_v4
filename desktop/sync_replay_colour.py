"""Sync verified video colour modules only; preserve install rollback and user data."""
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
    if target.parent!=deliveries:raise RuntimeError('Unexpected installation path')
    paths=resolve_paths(install=target,user=PROJECT/'.tmp/colour-install-check')
    verify_resources(paths);assert_local_package(target)
    backup=Path('D:/ai_climbing_code/verification/replay-colour-20261012')/datetime.now().strftime('%Y%m%d%H%M%S')
    backup.mkdir(parents=True,exist_ok=False)
    names=['backend/core/'+n for n in ['climb_replay.py','replay_hold_colors.py','replay_pose_rtmw.py']]
    metadata=['local-update.json','file-manifest.json','resources.json']
    existing=[]
    for name in names+metadata:
        if (target/name).exists():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target/name,dest);existing.append(name)
    def write_atomic(path,value):
        temporary=path.with_name(path.name+'.colour-update.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
        os.replace(temporary,path)
    try:
        for name in names:
            temporary=(target/name).with_suffix('.colour-update.tmp')
            shutil.copy2(PROJECT/name,temporary);os.replace(temporary,target/name)
        update=json.loads((target/'local-update.json').read_text('utf-8'))
        update['colour_hotfix']='2026-10-12 replay-body-distribution-v3: clicked connected region, unified body statistics, neutral colour body and chroma-weighted hue distribution. Requested colour, raw Lab <=60 and colour-first contour evidence unchanged. Residual contour truncation, sample-distance failures and false hold detections remain.'
        write_atomic(target/'local-update.json',update)
        resources=json.loads((target/'resources.json').read_text('utf-8'))
        rows=json.loads((target/'file-manifest.json').read_text('utf-8'))
        changed=names+['local-update.json']
        rows=[r for r in rows if r['path'] not in changed]
        for name in changed:
            path=target/name
            with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            rows.append({'path':name,'bytes':path.stat().st_size,'sha256':checksum})
        critical={r['path'] for r in resources['critical']}|set(changed)
        write_atomic(target/'file-manifest.json',rows)
        write_atomic(target/'resources.json',{**resources,'critical':[r for r in rows if r['path'] in critical]})
        verify_resources(paths);assert_local_package(target)
    except BaseException:
        for name in existing:shutil.copy2(backup/name,target/name)
        for name in names:
            if name not in existing:(target/name).unlink(missing_ok=True)
        raise
    print(json.dumps({'synced':str(target),'backup':str(backup),'resources_verified':True,
                      'scope':'three video backend modules; frontend and user files untouched'}))


if __name__=='__main__':main()
