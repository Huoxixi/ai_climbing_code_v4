"""Exercise installed local import through HTTP with isolated disposable data."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.14-replay.20261009')


def main():
    root = PROJECT / '.tmp/video-preview-20261015' / ('startup-' + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=False)
    code = "import sys;sys.path.insert(0,sys.argv[1]);from desktop.launcher import main;raise SystemExit(main(['--headless','--data-root',sys.argv[2]]))"
    process = subprocess.Popen([str(PACKAGE / 'runtime/python.exe'), '-c', code, str(PACKAGE), str(root)],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = {'isolated_user_data': True, 'user_app_not_restarted': True}
    try:
        deadline = time.monotonic() + 45
        while not (root / 'instance.json').is_file():
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Isolated application readiness failed')
            time.sleep(0.3)
        data = json.loads((root / 'instance.json').read_text('utf8'))
        assert data['pid'] == process.pid
        base = f'http://127.0.0.1:{data["port"]}'
        def request(path, body=None, method=None, content_type='application/json'):
            req = urllib.request.Request(base + path, data=body, method=method,
                headers={'X-Desktop-Token': data['token'], 'Content-Type': content_type})
            return urllib.request.urlopen(req, timeout=60)
        with request('/api/health') as response:
            result['healthy'] = response.status == 200
        with request('/api/climb-replay/preview-capability') as response:
            result['local_conversion_available'] = json.load(response)['local_conversion'] is True
        import sys
        sys.path.insert(0, str(PACKAGE / 'backend'))
        from core.replay_template_renderer import _ffmpeg
        from core.climb_replay import probe_video
        source = root / 'hevc.mp4'
        subprocess.run([_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=96x128:rate=25:duration=0.4', '-an', '-c:v', 'libx265',
            '-preset', 'ultrafast', '-x265-params', 'log-level=error:pools=none:frame-threads=1',
            '-y', str(source)], check=True, capture_output=True)
        boundary = 'climb-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="hevc.mp4"\r\n'
                'Content-Type: video/mp4\r\n\r\n').encode() + source.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        with request('/api/climb-replay/preview-video', body, content_type='multipart/form-data; boundary=' + boundary) as response:
            key = response.headers['X-Prepared-Video-Id']
            preview = root / 'canonical.mp4'
            preview.write_bytes(response.read())
        info = probe_video(preview)
        assert info.width == 96 and info.height == 128
        streams = subprocess.run([_ffmpeg(), '-hide_banner', '-i', str(preview)], capture_output=True).stderr.decode('utf8', 'replace')
        assert 'Video: h264' in streams and 'yuv420p' in streams and 'Audio:' not in streams
        result['hevc_imported_as_h264'] = True
        with request('/api/climb-replay/preview-video/' + key, method='DELETE') as response:
            result['temporary_copy_discarded'] = json.load(response)['discarded']
        with request('/api/climb-replay/jobs') as response:
            jobs = json.load(response)
            result['no_recognition_jobs'] = not (jobs if isinstance(jobs, list) else jobs.get('jobs', []))
        assert all(result.values())
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        result['own_test_process_stopped'] = process.poll() is not None
        (root.parent / 'installed-startup.json').write_text(json.dumps(result, indent=2), 'utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
