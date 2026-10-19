"""Explicit reviewed tools-only tags; all other tags keep website deployment."""
import json
from pathlib import Path
import re
import sys


def mode(tag, manifest):
    if not re.fullmatch(r'pilot-v\d{4}\.\d{2}\.\d{2}-rc\d+',tag):
        raise RuntimeError('Invalid release tag')
    if manifest.get('schema')!=1 or not isinstance(manifest.get('tags'),dict):
        raise RuntimeError('Invalid bootstrap manifest')
    for name, value in manifest['tags'].items():
        if not re.fullmatch(r'pilot-v\d{4}\.\d{2}\.\d{2}-rc\d+',name) or value!='ssh-maintenance':
            raise RuntimeError('Unsupported bootstrap mode')
    return manifest['tags'].get(tag,'browser')


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('One immutable tag required')
    print(mode(sys.argv[1],json.loads(Path(__file__).with_name('bootstrap_tags.json').read_text())))
