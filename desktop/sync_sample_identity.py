"""Install only the verified continuous sample-identity correction locally."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop.launcher import verify_resources
from desktop.paths import resolve_paths
from desktop.package_scope import assert_local_package


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    deliveries = Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    target = (deliveries / 'AiClimbing-0.1.14-replay.20261009').resolve()
    assert target.parent == deliveries
    paths = resolve_paths(install=target, user=PROJECT / '.tmp/sample-identity-resource-check')
    verify_resources(paths)
    assert_local_package(target)
    evidence = PROJECT / '.tmp/hold-sample-identity-20261015'
    matrix = json.loads((evidence / 'frozen-matrix.json').read_text('utf-8'))
    assert len(matrix) == 18 and all(r['all_prior_selected_contours_preserved'] and not r['lost'] for r in matrix)
    live_root = Path('D:/ai_climbing_code/素材/视频复盘第二批10段_20261014/岩点提取_20261015/07_08算法自动结果')
    live = json.loads((live_root / '验收.json').read_text('utf-8'))
    assert [(r['before'], r['after']) for r in live] == [(6, 7), (6, 9)]
    assert all(r['prior_objects_and_contours_preserved'] and r['source_unchanged'] and not r['manual_selection_applied'] for r in live)
    changed = {f'backend/core/{name}': PROJECT / 'backend/core' / name for name in (
        'replay_hold_evidence.py', 'replay_hold_fusion.py', 'replay_hold_colors.py')}
    hashes = {Path(n).name: digest(p) for n, p in changed.items()}
    for row in live:
        report = json.loads((live_root / row['case'] / '自动结果.json').read_text('utf-8'))
        assert report['code_sha256'] == hashes
    backup = Path('D:/ai_climbing_code/verification/sample-identity-20261015') / datetime.now().strftime('%Y%m%d%H%M%S')
    backup.mkdir(parents=True, exist_ok=False)
    names = list(changed) + ['local-update.json', 'file-manifest.json', 'resources.json']
    for name in names:
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / name, dest)

    def atomic(path, value):
        temp = path.with_name(path.name + '.sample-identity.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
        os.replace(temp, path)

    try:
        for name, source in changed.items():
            dest = target / name
            temp = dest.with_name(dest.name + '.sample-identity.tmp')
            shutil.copy2(source, temp)
            os.replace(temp, dest)
        update = json.loads((target / 'local-update.json').read_text('utf-8'))
        update['continuous_sample_identity_hotfix'] = {
            'date': '2026-10-15', 'version': 'unresolved-continuous-sample-identity-v1',
            'colour_version': 'replay-material-distribution-v6',
            'frozen_fusion_cases': 18, 'targeted_tests': 77,
            'live_cases': live, 'manual_selection_in_inference': False,
            'prior_contours_preserved': True, 'preexisting_sign_false_positive_resolved': False,
            'independent_generalization_verified': False,
            'user_data_modified': False, 'production_deployed': False}
        atomic(target / 'local-update.json', update)
        manifest = json.loads((target / 'file-manifest.json').read_text('utf-8'))
        resources = json.loads((target / 'resources.json').read_text('utf-8'))
        updated = set(changed) | {'local-update.json'}
        manifest = [r for r in manifest if r['path'] not in updated]
        for name in sorted(updated):
            path = target / name
            manifest.append(dict(path=name, bytes=path.stat().st_size, sha256=digest(path)))
        critical = {r['path'] for r in resources['critical']} | updated
        atomic(target / 'file-manifest.json', manifest)
        atomic(target / 'resources.json', {**resources, 'critical': [r for r in manifest if r['path'] in critical]})
        verify_resources(paths)
        assert_local_package(target)
        assert all(digest(target / name) == digest(source) for name, source in changed.items())
    except BaseException:
        for name in names:
            shutil.copy2(backup / name, target / name)
        raise
    result = dict(installed=str(target), backup=str(backup), files=list(changed),
                  resources_verified=True, hashes=hashes, existing_update_metadata_preserved=True,
                  user_data_modified=False, production_deployed=False, restart_performed=False)
    (backup / 'sync-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    (evidence / 'install-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
