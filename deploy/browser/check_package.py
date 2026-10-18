"""Check the actual production package, including same-origin URLs and old API removal."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

from fastapi.testclient import TestClient

parser=argparse.ArgumentParser()
parser.add_argument('package',type=Path)
args=parser.parse_args()
root=args.package.resolve()
sys.path.insert(0,str(root/'backend'))
spec=importlib.util.spec_from_file_location('browser_release_entry',root/'backend/main.py')
entry=importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
files={str(p.relative_to(root)).replace('\\','/') for p in root.rglob('*') if p.is_file()}
for forbidden in ('backend/data/','.local/','.private/','frontend/src/','frontend/public/'):
    assert not any(name.startswith(forbidden) for name in files),forbidden
assert not any(name.endswith(('.sqlite3','.pth','.pt')) for name in files)
with TestClient(entry.app) as client:
    html=client.get('/')
    assert html.status_code==200 and '浏览器本地复盘' in html.text
    assert client.get('/api/health').json()['compute']=='browser-only'
    for url in re.findall(r'(?:src|href)="([^\"]+)"',html.text):
        if url.startswith('/assets/'):
            response=client.get(url)
            assert response.status_code==200,url
            if url.endswith('.js'):
                assert 'javascript' in response.headers['content-type']
    with client.stream('GET','/downloads/climbing-assistant-windows.exe',headers={'Range':'bytes=0-1'}) as response:
        assert response.status_code==206 and response.read()==b'MZ'
    for path in ('/api/member/login','/api/save-board','/api/local-replay/upload','/api/browser/admin/users'):
        assert client.post(path,json={}).status_code==404,path
    for path in ('/docs','/openapi.json','/api/photo-routes','/api/browser/session'):
        assert client.get(path).status_code==404,path
manifest=json.loads((root/'BROWSER_RELEASE.json').read_text('utf-8'))
installer=root/'frontend/dist/downloads/climbing-assistant-windows.exe'
with installer.open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['installer']['sha256']
print('Production package verified: browser entry, assets, installer range, and removed legacy APIs.')
