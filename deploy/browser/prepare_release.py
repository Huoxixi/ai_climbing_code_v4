"""Package only browser assets and the static backend; never copy personal data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError('Release destination must not exist')
    profile = json.loads((ROOT/'deploy/browser/profile.json').read_text('utf-8'))
    if profile['mode'] != 'browser-only':
        raise RuntimeError('Unexpected release profile')
    package = profile['installer']
    installer = ROOT/'.tmp/browser-downloads'/package['file']
    if not installer.is_file():
        installer=ROOT/'deploy/browser/downloads'/package['file']
    with installer.open('rb') as stream:
        installer_hash=hashlib.file_digest(stream, 'sha256').hexdigest()
    if installer.stat().st_size != package['bytes'] or installer_hash != package['sha256']:
        raise RuntimeError('Desktop installer checksum mismatch')
    static = ROOT/'frontend/dist-browser'
    if not (static/profile['entry']).is_file():
        raise RuntimeError('Build the browser website first')
    expected = json.loads((ROOT/'backend/model_assets/rtmw-l-384x288/manifest.json').read_text('utf-8'))
    for asset in expected['files']:
        path = static/'browser-models'/expected['model']/asset['file']
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream,'sha256').hexdigest()
        if path.stat().st_size != asset['bytes'] or digest != asset['sha256']:
            raise RuntimeError('Shipped model checksum mismatch: '+asset['file'])
    destination.mkdir(parents=True)
    shutil.copytree(static, destination/'frontend/dist')
    shutil.copyfile(static/profile['entry'], destination/'frontend/dist/index.html')
    downloads = destination/'frontend/dist/downloads'
    downloads.mkdir()
    shutil.copyfile(installer, downloads/'climbing-assistant-windows.exe')
    backend = destination/'backend'
    backend.mkdir()
    for name in ('browser_web_app.py','requirements-browser.lock','test_browser_web_app.py'):
        shutil.copyfile(ROOT/'backend'/name, backend/name)
    (backend/'main.py').write_text(
        'from pathlib import Path\n'
        'from browser_web_app import create_app\n'
        'root = Path(__file__).resolve().parents[1]\n'
        'app = create_app(static_root=root/"frontend/dist", '
        'installer=root/"frontend/dist/downloads/climbing-assistant-windows.exe")\n', encoding='utf-8')
    shutil.copyfile(ROOT/'deploy/browser/profile.json',destination/'BROWSER_RELEASE.json')
    print('Browser-only release packaged; no legacy API, database or private media copied.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    prepare(parser.parse_args().destination)
