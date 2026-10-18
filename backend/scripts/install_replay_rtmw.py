"""Explicit weight installation; runtime inference never downloads anything."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ASSETS = [
    ('rtmw.onnx', 'rtmw-l-384x288.zip',
     'https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip',
     'a87e1af41a0a067776dba7d46e1c21c8f6e9f18e247e0e606718dd1f31e96ffd'),
    ('detector.onnx', 'yolox-s.zip',
     'https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_s_8xb8-300e_humanart-3ef259a7.zip',
     'e8e8f51cb9c70ed1c3781ed12f1debf918d78cf94638554f1a467f704f627349'),
]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install(cache):
    directory = ROOT / 'backend/model_assets/rtmw-l-384x288'
    manifest = json.loads((directory / 'manifest.json').read_text('utf-8'))
    expected = {entry['file']: entry for entry in manifest['files']}
    cache.mkdir(parents=True, exist_ok=True)
    for name, archive_name, url, digest in ASSETS:
        target = directory / name
        if target.is_file():
            if sha(target) != expected[name]['sha256']:
                raise RuntimeError('Existing model failed verification; preserved: ' + name)
            continue
        archive = cache / archive_name
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=60) as response, archive.open('xb') as out:
                shutil.copyfileobj(response, out)
        if sha(archive) != digest:
            raise RuntimeError('Download checksum mismatch: ' + archive_name)
        with zipfile.ZipFile(archive) as bundle:
            candidates = [item for item in bundle.namelist() if item.rsplit('/', 1)[-1] == 'end2end.onnx']
            if len(candidates) != 1:
                raise RuntimeError('Unexpected model archive layout')
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as out:
                temporary = Path(out.name)
                with bundle.open(candidates[0]) as source:
                    shutil.copyfileobj(source, out)
        try:
            if sha(temporary) != expected[name]['sha256']:
                raise RuntimeError('Extracted model checksum mismatch')
            temporary.rename(target)
        finally:
            temporary.unlink(missing_ok=True)
    print('RTMW-L 384x288 and YOLOX-S weights verified; no cloud pose API used.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=ROOT / '.tmp/rtmw-downloads')
    install(parser.parse_args().cache)
