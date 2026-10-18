"""Smoke-test the installed local backend with fresh, isolated test data."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.14-replay.20261009')


def main():
    root = PROJECT / '.tmp/replay-composition-20261015' / ('startup-' + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    code = "import sys;sys.path.insert(0,sys.argv[1]);from desktop.launcher import main;raise SystemExit(main(['--headless','--data-root',sys.argv[2]]))"
    process = subprocess.Popen([str(PACKAGE / 'runtime/python.exe'), '-c', code, str(PACKAGE), str(root)],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = {'isolated_user_data': True, 'user_app_not_restarted': True, 'healthy': False}
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Isolated application startup failed')
            instance = root / 'instance.json'
            if instance.is_file():
                data = json.loads(instance.read_text('utf8'))
                if data['pid'] != process.pid:
                    raise RuntimeError('Unexpected isolated instance')
                def fetch(path, payload=None):
                    request = urllib.request.Request(f'http://127.0.0.1:{data["port"]}' + path,
                        data=json.dumps(payload).encode() if payload is not None else None,
                        headers={'X-Desktop-Token': data['token'], 'Content-Type': 'application/json'})
                    try:
                        response = urllib.request.urlopen(request, timeout=5)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        return response.status, json.load(response)
                status, _ = fetch('/api/health')
                export_status, export_error = fetch('/api/climb-replay/jobs/nonexistent/actions/export', {})
                background_status, background_error = fetch('/api/climb-replay/jobs/nonexistent/actions/background')
                result.update(healthy=status == 200,
                    export_route_loaded=export_status == 422 and any('result_version' in e.get('loc', []) for e in export_error.get('detail', [])),
                    authenticated_background_route=background_status == 422 and any('version' in e.get('loc', []) for e in background_error.get('detail', [])))
                if not all((result['healthy'], result['export_route_loaded'], result['authenticated_background_route'])):
                    raise RuntimeError('Installed routes are incomplete')
                break
            time.sleep(.3)
        if not result['healthy']:
            raise RuntimeError('Isolated application readiness timed out')
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        result['own_test_process_stopped'] = process.poll() is not None
        (root.parent / 'installed-startup.json').write_text(json.dumps(result, indent=2), 'utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
