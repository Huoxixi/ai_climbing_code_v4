"""Constructed HTTP upload, duplicate launch, abrupt exit and restart checks."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    data = args.output / '生命周期 数据'
    import httpx
    from PIL import Image, ImageDraw
    python = Path(sys.executable)
    checks = {}
    owned = []
    sentinel = subprocess.Popen([str(python), '-c', 'import time; time.sleep(180)'], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def start():
            process = subprocess.Popen([str(python), '-m', 'desktop.launcher', '--headless', '--data-root', str(data)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append(process)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Constructed desktop service exited')
                try:
                    item = json.loads((data / 'instance.json').read_text(encoding='utf-8'))
                    if item['pid'] != process.pid:
                        raise ValueError('stale instance')
                    client = httpx.Client(base_url=f"http://127.0.0.1:{item['port']}", headers={'X-Desktop-Token': item['token']}, timeout=5)
                    if client.get('/api/health').status_code == 200:
                        return process, client, item
                    client.close()
                except Exception:
                    time.sleep(.2)
            raise RuntimeError('Constructed service readiness timed out')
        first, client, identity = start()
        checks['independent_port'] = identity['port'] not in {4176, 8004}
        duplicate = subprocess.run([str(python), '-m', 'desktop.launcher', '--headless', '--data-root', str(data)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        checks['duplicate_reuses_existing_instance'] = duplicate.returncode == 0 and first.poll() is None
        image = Image.new('RGB', (800, 600), '#777777')
        draw = ImageDraw.Draw(image)
        for x in range(10, 780, 45):
            for y in range(10, 580, 45):
                draw.ellipse((x, y, x + 20, y + 20), fill='#ddbd22')
        payload = io.BytesIO()
        image.save(payload, format='JPEG')
        response = client.post('/api/photo-routes/workflow/upload', data={'request_id': uuid.uuid4().hex},
                               files={'photo': ('构造 照片.jpg', payload.getvalue(), 'image/jpeg')})
        response.raise_for_status()
        draft = response.json()
        checks['upload_waits_for_colour'] = draft['status'] == 'awaiting_color'
        checks['no_automatic_inference'] = draft.get('flow_version') == 3 and not draft['board'].get('model_version') and not draft['board'].get('objects')
        job_id = draft['id']
        asset = draft.get('source_photo') or draft.get('photo')
        client.close()
        first.terminate()
        first.wait(timeout=10)
        checks['unrelated_process_survives'] = sentinel.poll() is None
        second, restored, second_identity = start()
        result = restored.get('/api/photo-routes/workflow/current')
        result.raise_for_status()
        current = result.json()
        checks['draft_recovers_after_abrupt_exit'] = current['id'] == job_id and current['status'] == draft['status']
        checks['new_instance_rejects_old_token'] = restored.get('/api/health', headers={'X-Desktop-Token': identity['token']}).status_code == 403
        checks['no_cloud_configuration'] = not restored.get('/desktop/status').json().get('pose_requires_credentials', True) and not restored.get('/desktop/status').json()['action_configured']
        restored.close()
        second.terminate()
        second.wait(timeout=10)
        checks['unrelated_process_survives_restart'] = sentinel.poll() is None
    finally:
        for process in owned:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        sentinel.terminate()
        sentinel.wait(timeout=10)
    report = {'checks': checks, 'paid_requests': 0, 'constructed_only': True,
              'python_runtime': str(python), 'clean_windows_environment': False}
    (args.output / 'lifecycle-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
