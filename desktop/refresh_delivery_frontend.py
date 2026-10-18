"""Refresh only the current new package's compiled UI and its manifest entries."""
import hashlib,json,shutil,sys
from pathlib import Path


def main():
    project=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(project))
    from desktop import VERSION
    from desktop.package_scope import assert_local_frontend
    target=Path(sys.argv[1]).resolve()
    deliveries=Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    if target.parent!=deliveries or target.name!='AiClimbing-'+VERSION:
        raise RuntimeError('Only the current newly created delivery may be refreshed')
    frontend=target/'frontend/dist'
    source=project/'frontend/dist'
    assert_local_frontend(source)
    shutil.copytree(source,frontend,dirs_exist_ok=True)
    for path in frontend.rglob('*'):
        if path.is_file() and not (source/path.relative_to(frontend)).is_file():
            if frontend.resolve() not in path.resolve().parents:
                raise RuntimeError('Unexpected frontend path')
            path.unlink()
    index=frontend/'index.html'
    index.write_text(index.read_text('utf-8').replace('<head>','<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>',1),'utf-8')
    entries=[]
    for path in sorted(frontend.rglob('*')):
        if path.is_file():
            entries.append({'path':path.relative_to(target).as_posix(),'bytes':path.stat().st_size,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest=json.loads((target/'file-manifest.json').read_text('utf-8'))
    manifest=[e for e in manifest if not e['path'].startswith('frontend/dist/')]+entries
    (target/'file-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    resources=json.loads((target/'resources.json').read_text('utf-8'))
    resources['critical']=[e for e in resources['critical'] if not e['path'].startswith('frontend/dist/')]+entries
    (target/'resources.json').write_text(json.dumps(resources,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'version':VERSION,'frontend_files':len(entries),'current_frontend':True}))


if __name__=='__main__':main()
