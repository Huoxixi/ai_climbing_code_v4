"""Verify and extract the explicit application bundle for CI; no production writes."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('study_install',ROOT/'install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

def check():
    manifest=json.loads((ROOT/'release.json').read_text())
    archive=ROOT/'app.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archiveSHA256']:
        raise RuntimeError('Companion archive checksum mismatch')
    payload,release=installer.unpack(archive)
    if release['version']!=manifest['release'] or len(payload)!=21:
        raise RuntimeError('Unexpected companion release')
    if any(not (name in ('server.mjs','package.json') or name.startswith('public/')) for name in payload):
        raise RuntimeError('Private or unexpected application files')
    return manifest,payload

if __name__=='__main__':
    metadata,payload=check()
    for name,content in payload.items():
        target=ROOT/'candidate'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    print(f"Verified companion {metadata['release']}: {len(payload)} whitelisted files; private data excluded")
