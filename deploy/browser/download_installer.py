"""Obtain the existing public installer without putting binaries in Git history."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
profile=json.loads((ROOT/'deploy/browser/profile.json').read_text('utf-8'))['installer']
target=ROOT/'.tmp/browser-downloads'/profile['file']
target.parent.mkdir(parents=True,exist_ok=True)
if not target.is_file():
    partial=target.with_suffix('.partial')
    with urllib.request.urlopen(profile['url'],timeout=90) as incoming,partial.open('wb') as outgoing:
        shutil.copyfileobj(incoming,outgoing)
    with partial.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if partial.stat().st_size!=profile['bytes'] or digest!=profile['sha256']:
        raise RuntimeError('Public installer failed size/checksum verification')
    partial.replace(target)
with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
if target.stat().st_size!=profile['bytes'] or digest!=profile['sha256']:
    raise RuntimeError('Cached public installer failed verification; preserved')
print('Existing public desktop installer downloaded and SHA-256 verified.')
