"""Atomically install the locally verified route expansion; preserve rollback."""
import hashlib,json,os,shutil,sys
from datetime import datetime
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from desktop import VERSION
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_package

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    workspace=Path('D:/ai_climbing_code').resolve()
    target=(workspace/'desktop-deliveries'/('AiClimbing-'+VERSION)).resolve()
    assert target.is_relative_to(workspace/'desktop-deliveries')
    evidence=PROJECT/'.tmp/hold-expansion-20261014-02'
    cache=json.loads((evidence/'product-source-final/acceptance.json').read_text('utf8'))
    live=json.loads((evidence/'product-live/acceptance.json').read_text('utf8'))
    assert cache['cases']==12 and cache['prior_objects_preserved']==108 and cache['prior_pixel_difference']==0 and cache['new_unconfirmed_additions']==0
    assert live['cases']==2 and live['prior_pixel_difference']==0 and live['all_requested_misses_recovered']
    final_black=json.loads((evidence/'product-black-final/10-new/report.json').read_text('utf8'))
    assert final_black['summary']['selected']==8 and final_black['summary']['added']==5
    paths=resolve_paths(install=target,user=evidence/'resource-check')
    verify_resources(paths);assert_local_package(target)
    backup=(workspace/'verification/replay-route-expansion-20261014'/datetime.now().strftime('%Y%m%d%H%M%S')).resolve()
    assert backup.is_relative_to(workspace/'verification/replay-route-expansion-20261014')
    backup.mkdir(parents=True,exist_ok=False)
    changed={f'backend/core/{name}':PROJECT/'backend/core'/name for name in (
        'climb_replay.py','replay_hold_expansion.py','replay_hold_resampling.py')}
    names=list(changed)+['local-update.json','file-manifest.json','resources.json']
    old=set()
    for name in names:
        source=target/name
        if source.is_file():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);old.add(name)
    def atomic(path,data):
        temp=path.with_name(path.name+'.route-update.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf8');os.replace(temp,path)
    try:
        for name,source in changed.items():
            destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
            temp=destination.with_name(destination.name+'.route-update.tmp');shutil.copy2(source,temp);os.replace(temp,destination)
        update=json.loads((target/'local-update.json').read_text('utf8'))
        update['hold_route_expansion_hotfix']={
            'date':'2026-10-14','version':'native-route-evidence-expansion-v1',
            'corrected_targets':{'08':'绿色','10':'黑色'},'old_ten_targets_preserved':True,
            'prior_raster_pixel_difference':0,'old_ten_selected':96,
            'corrected_before':{'08':9,'10':3},'corrected_after':{'08':11,'10':8},
            'independently_supported_recovered_misses':7,'new_unconfirmed_additions_in_development_cases':0,
            'full_route_membership_verified':False,'independent_generalization_verified':False,
            'real_extra_frame_budget':4,'local_prompt_budget':8,
            'previous_updates_preserved':True,'user_data_modified':False,'production_deployed':False}
        atomic(target/'local-update.json',update)
        manifest=json.loads((target/'file-manifest.json').read_text('utf8'))
        resources=json.loads((target/'resources.json').read_text('utf8'))
        modified=set(changed)|{'local-update.json'}
        manifest=[r for r in manifest if r['path'] not in modified]
        for name in sorted(modified):
            path=target/name;manifest.append({'path':name,'bytes':path.stat().st_size,'sha256':digest(path)})
        critical={r['path'] for r in resources['critical']}|modified
        atomic(target/'file-manifest.json',manifest)
        atomic(target/'resources.json',{**resources,'critical':[r for r in manifest if r['path'] in critical]})
        verify_resources(paths);assert_local_package(target)
    except Exception:
        for name in names:
            destination=(target/name).resolve()
            assert destination.is_relative_to(target)
            if name in old:shutil.copy2(backup/name,destination)
            elif name in changed:destination.unlink(missing_ok=True)
        raise
    result={'installed':str(target),'backup':str(backup),'files':list(changed),
            'resources_verified':True,'source_hashes_match':all(digest(target/name)==digest(source) for name,source in changed.items())}
    (backup/'installation-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    (evidence/'installation-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main()
