"""Constructed-only portable runtime check; no development configuration/data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest

from desktop.paths import resolve_paths, isolated_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tests', type=Path)
    parser.add_argument('--model', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    install = Path(__file__).resolve().parents[1]
    paths = resolve_paths(install=install, user=args.output / '中文 用户 空格')
    paths.prepare()
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.chdir(paths.user)
    (paths.user / '.env').write_text('OPENAI_API_KEY=constructed-must-not-load\n', encoding='utf-8')
    started = time.monotonic()
    import psutil
    import torch
    import cv2
    import numpy as np
    import detectron2
    from detectron2 import _C
    from imageio_ffmpeg import get_ffmpeg_exe
    from fastapi.testclient import TestClient
    from desktop.server import create_app
    from desktop.credentials import crypt, save, load
    from desktop.launcher import require_webview2
    checks = {}
    save(paths.config, {'DASHSCOPE_API_KEY': 'constructed-fake-key'})
    checks['dpapi_roundtrip'] = load(paths.config) == {'DASHSCOPE_API_KEY': 'constructed-fake-key'}
    checks['dpapi_not_plaintext'] = b'constructed-fake-key' not in (paths.config / 'cloud.dpapi').read_bytes()
    save(paths.config, {})
    require_webview2()
    checks['webview2_prerequisite'] = True
    app = create_app(paths, 'verification-token', 'http://127.0.0.1:53291')
    checks['dotenv_not_loaded'] = os.getenv('OPENAI_API_KEY') != 'constructed-must-not-load'
    with TestClient(app, base_url='http://127.0.0.1:53291') as client:
        checks['unauthenticated_denied'] = client.get('/api/health').status_code == 403
        response = client.get('/desktop/bootstrap/verification-token')
        checks['static_ui'] = response.status_code == 200 and '__AI_CLIMBING_DESKTOP__' in response.text
        checks['setter_routes_removed'] = all(client.get(path).status_code == 404 for path in ('/api/my-boards','/api/holds/mapping','/api/standard-board/routes','/api/generate'))
        checks['health'] = client.get('/api/health').status_code == 200
        session = client.get('/api/auth/session').json()
        checks['local_account'] = not session.get('auth_enabled', True)
        checks['no_development_test_videos'] = client.get('/api/climb-replay/test-videos').json().get('items') == []
        checks['no_cloud_pose_credentials'] = not bool(os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID'))
        checks['no_supabase'] = os.getenv('DISABLE_SUPABASE') == 'true'
        checks['status'] = client.get('/desktop/status').status_code == 200
        policy = client.get('/api/climb-replay/consent-policy').json()
        checks['local_pose_policy'] = policy.get('execution') == 'local' and not policy.get('uploads_frames', True)
        from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
        pose, detector = LocalRTMWReplayAnalyzer()._load_models()
        pose_frame = np.full((640, 480, 3), 150, dtype=np.uint8)
        xy, scores = pose(pose_frame, [[60, 40, 420, 600]])
        detections = detector(pose_frame)
        checks['packaged_rtmw_inference'] = bool(xy.shape == (1, 133, 2) and scores.shape == (1, 133) and np.isfinite(xy).all() and np.isfinite(scores).all())
        checks['packaged_yolox_inference'] = isinstance(detections, np.ndarray)
        checks['pose_ready_without_credentials'] = client.get('/desktop/status').json().get('pose_configured') and not client.get('/desktop/status').json().get('pose_requires_credentials', True)
        vision = client.get('/api/settings/replay-vision')
        checks['vision_settings_available'] = vision.status_code == 200
        checks['vision_default_budget_and_no_implicit_paid_call'] = vision.status_code == 200 and vision.json().get('budget_cny') == 1 and not vision.json().get('ready', True) and 'api_key' not in vision.json()
        checks['native_pose_default_10fps'] = LocalRTMWReplayAnalyzer().pose_fps == 10
        from core.climb_replay import VideoLimits
        checks['analysis_copy_720_landscape_bound'] = VideoLimits().max_width == 1280 and VideoLimits().max_height == 720
        if args.model:
            from core.photo_route_analysis import _climbing_model_masks_batch
            image = np.full((520, 800, 3), 150, dtype=np.uint8)
            cv2.rectangle(image, (200, 240), (260, 285), (15, 180, 220), -1)
            tick = time.monotonic()
            masks, version = _climbing_model_masks_batch([image], time.monotonic() + 180, lambda: False)
            checks['native_model_inference'] = len(masks) == 1 and 'min1200-cap300' in version
            model_report = {'seconds': round(time.monotonic() - tick, 3), 'version': version,
                            'mask_count': len(masks[0][0]), 'constructed_only': True}
            (args.output / 'model-report.json').write_text(json.dumps(model_report, indent=2), encoding='utf-8')
            print(json.dumps(model_report), flush=True)
        else:
            model_report = {'not_run': True}
    import subprocess
    # HEVC decode -> H.264 compatibility path, with Chinese/spaced filenames.
    media = paths.user / '构造 视频.mp4'
    result = subprocess.run([get_ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i',
                             'testsrc2=size=320x240:rate=8:duration=1', '-c:v', 'libx265',
                             '-x265-params', 'log-level=error', str(media)], capture_output=True, timeout=30)
    checks['ffmpeg_hevc_encode'] = result.returncode == 0
    from core.climb_replay import probe_video, convert_video_to_mp4
    info = probe_video(media)
    normalized = paths.user / '兼容 视频.mp4'
    convert_video_to_mp4(media, normalized, cancelled=lambda: False)
    checks['hevc_normalization'] = normalized.is_file() and probe_video(normalized).frame_count > 0
    from core.replay_visual_renderer import build_visual_manifest
    from core.replay_resources import run_visual_worker
    reference = paths.user / '构造 参考.png'
    cv2.imencode('.png', np.full((240, 160, 3), 180, dtype=np.uint8))[1].tofile(str(reference))
    holds = [{'id': n + 1, 'polygon': [[x, y], [x + .1, y], [x + .1, y + .08], [x, y + .08]]}
             for n, (x, y) in enumerate(((.25, .7), (.55, .5), (.32, .25)))]
    visual = build_visual_manifest({'holds': holds, 'attempt': {'contacts': [
        {'hold_id': 1, 'limb': 'left_hand', 'start_time_seconds': 1},
        {'hold_id': 2, 'limb': 'right_hand', 'start_time_seconds': 2}], 'topped_out': True}},
        {'width': 160, 'height': 240, 'source_frame_id': 0, 'source_sha256': 'constructed'})
    manifest = paths.user / '构造 清单.json'
    manifest.write_text(json.dumps(visual), encoding='utf-8')
    worker_output, metrics = paths.user / '构造 尾段.webm', paths.user / '构造 资源.json'
    worker = run_visual_worker(reference, manifest, worker_output, metrics)
    checks['packaged_visual_subprocess'] = worker_output.is_file() and metrics.is_file()
    # Load test files as modules without replacing the packaged core import path.
    test_report = None
    if args.tests:
        # Historical fake render callbacks assume the optional visual tail is off.
        # Test that branch separately from the real packaged visual worker below.
        os.environ['CLIMB_REPLAY_VISUAL_ENABLED'] = '0'
        import importlib.util
        test_root = args.tests.resolve()
        for name in ('test_climb_replay', 'test_photo_route_v2'):
            spec = importlib.util.spec_from_file_location(name, test_root / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        suite = unittest.TestSuite()
        for name in ('test_replay_paid_gate', 'test_replay_hold_review', 'test_replay_route_map_refresh', 'test_photo_workflow'):
            spec = importlib.util.spec_from_file_location(name, test_root / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        checks['workflow_regressions'] = result.wasSuccessful()
        test_report = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped)}
    report = {'platform': platform.platform(), 'cpu': platform.processor(),
              'logical_processors': psutil.cpu_count(), 'ram_bytes': psutil.virtual_memory().total,
              'process_peak_working_set': getattr(psutil.Process().memory_info(), 'peak_wset', None),
              'python': sys.version.split()[0], 'torch': torch.__version__, 'detectron2': detectron2.__version__,
              'checks': checks, 'model': model_report, 'regressions': test_report,
              'seconds': round(time.monotonic() - started, 3),
              'independent_clean_windows': False, 'paid_requests': 0,
              'core_loaded_from_package': str(Path(sys.modules['core.climb_replay'].__file__)).startswith(str(install))}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
