"""Install verified local hold progress and its existing offline dependencies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_package

def main():
    deliveries=Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target=(deliveries/('AiClimbing-'+VERSION)).resolve()
    assert target.parent==deliveries and target.is_relative_to(Path('D:/ai_climbing_code').resolve())
    paths=resolve_paths(install=target,user=PROJECT/'.tmp/nonregression-resource-check')
    verify_resources(paths);assert_local_package(target)
    evidence=PROJECT/'.tmp/hold-nonregression-20261014-01'
    checks=json.loads((evidence/'product-layered/cache/acceptance.json').read_text('utf-8'))
    live=json.loads((evidence/'product-layered-live/live/acceptance.json').read_text('utf-8'))
    assert checks['cases']==10 and checks['known_errors']==0 and checks['unknown_added']==0
    assert live['cases']==4 and live['known_errors']==0 and live['original_contour_iou_min']==1.
    backup=Path('D:/ai_climbing_code/verification/replay-nonregression-20261014')/datetime.now().strftime('%Y%m%d%H%M%S')
    backup.mkdir(parents=True,exist_ok=False)
    changed={f'backend/core/{name}':PROJECT/f'backend/core/{name}' for name in [
        'climb_replay.py','replay_hold_colors.py','replay_hold_evidence.py','replay_hold_fusion.py','replay_hold_recovery.py','replay_hold_editor.py']}
    mobile=Path('D:/ai_climbing_code/photo-route-experiments/MobileSAM')
    for source in (mobile/'mobile_sam').rglob('*.py'):
        changed['vendor/MobileSAM/'+source.relative_to(mobile).as_posix()]=source
    if (mobile/'LICENSE').is_file():changed['vendor/MobileSAM/LICENSE']=mobile/'LICENSE'
    changed['models/mobile_sam.pt']=mobile/'weights/mobile_sam.pt'
    with changed['models/mobile_sam.pt'].open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()=='6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f'
    libs=Path('D:/ai_climbing_code/.tools/boulder-model-python')
    for source in (libs/'timm').rglob('*.py'):
        changed['runtime/Lib/site-packages/'+source.relative_to(libs).as_posix()]=source
    for source in (libs/'timm-0.9.16.dist-info').rglob('*'):
        if source.is_file():changed['runtime/Lib/site-packages/'+source.relative_to(libs).as_posix()]=source
    metadata=['local-update.json','file-manifest.json','resources.json']
    existing=[]
    for name in list(changed)+metadata:
        if (target/name).is_file():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target/name,dest);existing.append(name)
    def atomic(path,data):
        temp=path.with_name(path.name+'.nonregression-update.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8');os.replace(temp,path)
    try:
        for name,source in changed.items():
            dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.nonregression-update.tmp');shutil.copy2(source,temp);os.replace(temp,dest)
        update=json.loads((target/'local-update.json').read_text('utf-8'))
        update['hold_nonregression_hotfix']={
            'date':'2026-10-14','colour_version':'replay-material-distribution-v5',
            'recovery_version':'model-guided-hold-recovery-v1',
            'contract':'preserve prior correct/unknown objects and their contours; no new unconfirmed selected candidates',
            'known_visible_anchors':90,'confirmed_negative_anchors':4,'known_errors_before':16,'known_errors_after':0,
            'all_ten_cache_cases_verified':True,'native_live_cases':['01','03','04','10'],
            'native_binary_equal_to_frozen_cache':True,'prior_correct_unknown_contour_iou':1.,
            'native_flip_retries_default':False,'offline_mobile_model_sha256':'6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f',
            'partial_edge_masks_do_not_assert_hidden_complete_boundaries':True,
            'independent_generalization_verified':False,'unlabelled_route_membership_remains_unknown':True,
            'user_data_modified':False,'production_deployed':False}
        atomic(target/'local-update.json',update)
        manifest=json.loads((target/'file-manifest.json').read_text('utf-8'))
        resources=json.loads((target/'resources.json').read_text('utf-8'))
        names=set(changed)|{'local-update.json'}
        manifest=[r for r in manifest if r['path'] not in names]
        for name in sorted(names):
            p=target/name
            with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            manifest.append(dict(path=name,bytes=p.stat().st_size,sha256=digest))
        critical={r['path'] for r in resources['critical']}|names
        atomic(target/'file-manifest.json',manifest)
        atomic(target/'resources.json',{**resources,'critical':[r for r in manifest if r['path'] in critical]})
        verify_resources(paths);assert_local_package(target)
    except BaseException:
        for name in existing:shutil.copy2(backup/name,target/name)
        for name in changed:
            if name not in existing:
                dest=(target/name).resolve();assert dest.is_relative_to(target);dest.unlink(missing_ok=True)
        raise
    result=dict(synced=str(target),backup=str(backup),files=len(changed),code_files=[n for n in changed if n.startswith('backend/core/')],
        resources_verified=True,previous_progress_metadata_preserved=True,user_data_modified=False,production_deployed=False)
    (backup/'sync-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main()
