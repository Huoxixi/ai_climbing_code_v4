"""Fixed maintenance actions. No shell, arbitrary paths, URLs or process IDs."""
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import urllib.parse
import urllib.request

ACTIONS = ('maintenance-status', 'maintenance-network', 'maintenance-tools',
           'maintenance-cleanup-plan', 'maintenance-cleanup', 'maintenance-cancel-download')
TAG = re.compile(r'pilot-v(\d{4})\.(\d{2})\.(\d{2})-rc(\d+)\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')


def download_identity(uid, args, cwd, cwd_uid):
    return (uid == 0 and cwd_uid == 0 and args == [b'python3.12', b'deploy/browser/download_installer.py']
            and bool(re.fullmatch(r'/tmp/ai-climbing-release\.[A-Za-z0-9]+/source', cwd)))


class Maintenance:
    def __init__(self, root=Path('/'), owner=0):
        self.root, self.owner = Path(root), owner
        self.releases = self.path('/opt/ai-climbing/releases')
        self.current = self.path('/opt/ai-climbing/current')
        self.lock = self.path('/run/ai-climbing-deploy/release.lock')

    def path(self, absolute):
        return self.root / absolute.lstrip('/')

    def secure(self, path, directory=False):
        info = path.lstat()
        if path.is_symlink() or path.resolve() != path or info.st_uid != self.owner or info.st_mode & 0o022:
            raise RuntimeError('Unexpected ownership, permissions or redirected path; preserved: ' + str(path))
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise RuntimeError('Unexpected file type; preserved')
        return path

    @contextlib.contextmanager
    def locked(self):
        import fcntl
        self.lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secure(self.lock.parent, directory=True)
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if info.st_uid != self.owner or info.st_mode & 0o077:
                raise RuntimeError('Deployment lock is not private')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def active(self):
        self.secure(self.current.parent, directory=True)
        self.secure(self.releases, directory=True)
        if not self.current.is_symlink():
            raise RuntimeError('Current release link missing')
        current = self.current.resolve(strict=True)
        if current.parent != self.releases or not TAG.fullmatch(current.name):
            raise RuntimeError('Unexpected current release')
        self.validate_release(current)
        return current

    def validate_release(self, release):
        self.secure(release, directory=True)
        if release.parent != self.releases or not TAG.fullmatch(release.name):
            raise RuntimeError('Unknown release; preserved')
        if set(p.name for p in release.iterdir()) != {'backend', 'frontend', 'RELEASE_SHA', 'BROWSER_RELEASE.json'}:
            raise RuntimeError('Unexpected release contents; preserved')
        for name in ('RELEASE_SHA', 'BROWSER_RELEASE.json'):
            self.secure(release/name)
        if not SHA.fullmatch((release/'RELEASE_SHA').read_text().strip()):
            raise RuntimeError('Invalid release SHA; preserved')
        if json.loads((release/'BROWSER_RELEASE.json').read_text())['mode'] != 'browser-only':
            raise RuntimeError('Only browser releases may be pruned')
        for name in ('backend', 'frontend', 'frontend/dist', 'backend/.venv'):
            self.secure(release/name, directory=True)
        if set(p.name for p in (release/'backend').iterdir()) - {
            'main.py', 'browser_web_app.py', 'requirements-browser.lock', 'test_browser_web_app.py', '.venv', '__pycache__'}:
            raise RuntimeError('Unexpected backend or user data; preserved')
        if set(p.name for p in (release/'frontend').iterdir()) != {'dist'}:
            raise RuntimeError('Unexpected frontend contents; preserved')
        if set(p.name for p in (release/'frontend/dist').iterdir()) - {
            'assets', 'browser-fonts', 'browser-models', 'downloads', 'browser-replay.html', 'index.html'}:
            raise RuntimeError('Unexpected static contents; preserved')
        if not (release/'backend/.venv/bin/python').is_file() or not (release/'frontend/dist/index.html').is_file():
            raise RuntimeError('Incomplete release; preserved')

    def health(self, current):
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5) as response:
            data = json.load(response)
        if data.get('status') != 'success' or data.get('compute') != 'browser-only' or data.get('release_sha') != (current/'RELEASE_SHA').read_text().strip():
            raise RuntimeError('Current browser release is not healthy; no mutation performed')
        return data

    def plan(self):
        current = self.active()
        self.health(current)
        backup = self.path('/var/lib/ai-climbing/ops/last-backup.env')
        self.secure(backup)
        fields = dict(line.split('=', 1) for line in backup.read_text().splitlines() if '=' in line)
        if fields.get('RESULT') != 'success' or fields.get('REMOTE_VERIFIED') != 'true':
            raise RuntimeError('Verified remote backup required before pruning')
        releases = []
        for release in self.releases.iterdir():
            if not TAG.fullmatch(release.name):
                raise RuntimeError('Unknown or unfinished release exists; cleanup stopped')
            self.validate_release(release)
            releases.append(release)
        releases.sort(key=lambda path: tuple(map(int, TAG.fullmatch(path.name).groups())), reverse=True)
        keep = {current, *[p for p in releases if p != current][:2]}
        return current, [p for p in releases if p in keep], [p for p in releases if p not in keep]

    def cleanup(self, execute=False):
        with self.locked():
            current, keep, remove = self.plan()
            result = {'current':current.name, 'keep':[p.name for p in keep],
                      'remove':[{'tag':p.name, 'sha':(p/'RELEASE_SHA').read_text().strip()} for p in remove]}
            if execute and remove:
                if not getattr(shutil.rmtree, 'avoids_symlink_attacks', False):
                    raise RuntimeError('Symlink-safe deletion is required')
                receipt_dir = self.path('/var/backups/ai-climbing/maintenance')
                receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.secure(receipt_dir, directory=True)
                receipt = receipt_dir/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-cleanup.json')
                with receipt.open('x') as out:
                    os.chmod(receipt, 0o600)
                    json.dump({**result, 'state':'prepared'}, out)
                for release in remove:
                    if self.current.resolve(strict=True) != current:
                        raise RuntimeError('Current changed; cleanup stopped')
                    self.validate_release(release)
                    shutil.rmtree(release)
                with receipt.open('w') as out:
                    json.dump({**result, 'state':'complete', 'data_modified':False, 'configuration_modified':False}, out)
                result['receipt'] = str(receipt)
            result['executed'] = execute
            return result

    def downloads(self):
        result = []
        for checkout in self.path('/tmp').glob('ai-climbing-release.*/source'):
            if checkout.is_symlink() or checkout.resolve() != checkout:
                continue
            for file in (checkout/'.tmp/browser-downloads').glob('*'):
                if file.is_file() and not file.is_symlink():
                    result.append({'file':file.name, 'bytes':file.stat().st_size})
        return result

    def cancel_download(self):
        current = self.active()
        self.health(current)
        try:
            with self.locked():
                raise RuntimeError('No active deployment; nothing cancelled')
        except BlockingIOError:
            pass
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise RuntimeError('Stable process handles are required')
        cancelled = []
        for process in self.path('/proc').iterdir():
            if not process.name.isdecimal():
                continue
            try:
                args = (process/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
                cwd = (process/'cwd').resolve(strict=True)
                if not download_identity(process.stat().st_uid,args,str(cwd),cwd.stat().st_uid):
                    continue
                fd = os.pidfd_open(int(process.name))
            except (ProcessLookupError, FileNotFoundError):
                continue
            try:
                args = (process/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
                cwd = (process/'cwd').resolve(strict=True)
                if download_identity(process.stat().st_uid,args,str(cwd),cwd.stat().st_uid):
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                    cancelled.append(int(process.name))
            except (FileNotFoundError, ProcessLookupError):
                continue
            finally:
                os.close(fd)
        return {'cancelled_downloads':cancelled}

    def status(self):
        current = self.active()
        return {'current':str(current), 'health':self.health(current),
                'free_bytes':shutil.disk_usage(self.releases).free,
                'downloads':self.downloads(),
                'nginx':subprocess.run(['/usr/bin/systemctl','is-active','nginx'],capture_output=True,text=True,timeout=5).stdout.strip()}


def main(args):
    if len(args) != 1 or args[0] not in ACTIONS:
        raise RuntimeError('Exactly one fixed maintenance action is required')
    if os.geteuid() != 0:
        raise RuntimeError('Use the restricted sudo maintenance entry point')
    action = args[0]
    subprocess.run(['/usr/bin/logger','-t','ai-climbing-maintenance','--','action='+action],check=True)
    worker = Maintenance()
    if action == 'maintenance-tools':
        result = {'source_sha':(Path(__file__).parent/'SOURCE_SHA').read_text().strip(), 'actions':ACTIONS}
    elif action == 'maintenance-status': result = worker.status()
    elif action == 'maintenance-cleanup-plan': result = worker.cleanup()
    elif action == 'maintenance-cleanup': result = worker.cleanup(execute=True)
    elif action == 'maintenance-cancel-download': result = worker.cancel_download()
    else:
        profile = json.loads((Path(__file__).parent/'profile.json').read_text())
        urls = [profile['installer']['url'], 'https://www.panyandingxian.cn/api/health']
        result = []
        for url in urls:
            try:
                request = urllib.request.Request(url,method='HEAD' if urllib.parse.urlparse(url).hostname=='github.com' else 'GET')
                with urllib.request.urlopen(request,timeout=8) as response:
                    result.append({'host':urllib.parse.urlparse(url).hostname,'status':response.status,'bytes':response.headers.get('Content-Length')})
            except Exception as error:
                # Never print signed redirect URLs, tokens or headers.
                result.append({'host':urllib.parse.urlparse(url).hostname,'error_type':type(error).__name__})
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    try: main(sys.argv[1:])
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        sys.exit(1)
