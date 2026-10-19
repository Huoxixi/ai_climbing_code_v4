"""Download the fixed public installer with bounded, verified parallel ranges."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CHUNK_BYTES = 1024 * 1024
CURRENT_PUBLIC_INSTALLER = Path('/opt/ai-climbing/current/frontend/dist/downloads/climbing-assistant-windows.exe')


def verify(path, profile):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if path.stat().st_size != profile['bytes'] or digest != profile['sha256']:
        raise RuntimeError('Public installer failed size/checksum verification; existing file preserved')


def download(profile, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        verify(target, profile)
        return target
    partial = target.with_suffix('.partial')
    # The standard deployer holds the release lock. Reuse only the fixed public
    # artifact from the active release; never inspect application data/config.
    # A new installer version or a damaged cache falls back to the pinned URL.
    try:
        cached = CURRENT_PUBLIC_INSTALLER.resolve(strict=True)
        if cached.stat().st_size != profile['bytes']:
            cached = None
        else:
            verify(cached, profile)
    except (OSError, RuntimeError):
        cached = None
    if cached is not None:
        try:
            shutil.copyfile(cached, partial)
            verify(partial, profile)
            partial.replace(target)
            print('Active release public installer reused and SHA-256 verified.', flush=True)
            return target
        finally:
            partial.unlink(missing_ok=True)
    cancelled = threading.Event()
    total = profile['bytes']

    def part(start):
        end = min(start + CHUNK_BYTES, total) - 1
        for attempt in range(3):
            try:
                deadline = time.monotonic() + 120
                request = urllib.request.Request(profile['url'], headers={
                    'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity',
                    'User-Agent': 'ClimbingAssistant-release/1',
                })
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{total}':
                        raise RuntimeError('Installer server did not honor the exact requested range')
                    chunks = []
                    received = 0
                    while True:
                        if cancelled.is_set() or time.monotonic() > deadline:
                            raise TimeoutError('Installer range deadline exceeded or download cancelled')
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > end - start + 1:
                            raise RuntimeError('Installer range exceeded its expected size')
                        chunks.append(chunk)
                    if received != end - start + 1:
                        raise RuntimeError('Installer range was truncated')
                    return start, b''.join(chunks)
            except Exception:
                if cancelled.is_set() or attempt == 2:
                    raise
                time.sleep(attempt + 1)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool, partial.open('wb') as outgoing:
            futures = [pool.submit(part, start) for start in range(0, total, CHUNK_BYTES)]
            received = 0
            try:
                for future in as_completed(futures, timeout=600):
                    start, body = future.result()
                    outgoing.seek(start)
                    outgoing.write(body)
                    received += len(body)
                    print(f'Public installer: {received}/{total} bytes received', flush=True)
            except BaseException:
                cancelled.set()
                for future in futures:
                    future.cancel()
                raise
        verify(partial, profile)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


if __name__ == '__main__':
    profile = json.loads((ROOT/'deploy/browser/profile.json').read_text('utf-8'))['installer']
    download(profile, ROOT/'.tmp/browser-downloads'/profile['file'])
    print('Public desktop installer downloaded and SHA-256 verified.', flush=True)
