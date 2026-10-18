"""Private, controlled H0/H2/H3 evidence. Never edits app records or sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from core.climb_replay import AliyunReplayAnalyzer, probe_video
from core.photo_route_analysis import _climbing_model_masks_batch
from scripts.accept_replay_hold_editor import measured_resources


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', default='1,8,9')
    parser.add_argument('--profile', choices=['4', '6', '8', 'seconds'], default='4')
    parser.add_argument('--reference-frame',type=int)
    args = parser.parse_args()
    # Private artifacts cannot accidentally enter tracked source directories.
    private_root = Path(__file__).resolve().parents[2] / '.tmp'
    output = Path(os.path.abspath(args.output)).resolve()
    if not output.is_relative_to(private_root.resolve()) or '.local' in args.materials.parts:
        raise ValueError('Use the project .tmp output and designated materials, never .local')
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(args.materials.glob('[0-9][0-9]_*.mp4'))
    if len(sources) != 10:
        raise ValueError('Expected ten designated recuts')
    selected = {int(item) for item in args.cases.split(',')}
    os.environ['CLIMB_REPLAY_HOLD_FRAME_PROFILE'] = args.profile
    config = Path(os.environ.get('PHOTO_ROUTE_CLIMBING_MODEL_CONFIG',
                                str(Path(__file__).resolve().parents[1] / 'model_assets/climbing-mask-rcnn-r50-fpn-1200.yaml')))
    checkpoint = Path(os.environ['PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT'])
    manifest = {'scope': 'controlled-candidates-not-accuracy', 'profile': args.profile,
                'development_cases': [1, 2, 3, 4, 8, 9], 'holdout_cases': [5, 6, 7, 10],
                'holdout_limit': 'Previously used engineering materials; no population-independent claim',
                'model_config_sha256': digest(config), 'checkpoint_sha256': digest(checkpoint),
                'source_code_sha256': {name: digest(Path(__file__).resolve().parents[1] / 'core' / name)
                                       for name in ['climb_replay.py', 'replay_hold_fusion.py', 'photo_route_analysis.py']},
                'cases': []}
    for number, path in enumerate(sources, 1):
        if number not in selected:
            continue
        case = output / f'case-{number:02}'
        case.mkdir()
        before = digest(path)
        info = probe_video(path)
        frames = AliyunReplayAnalyzer._hold_frames(path, info, None)
        if args.reference_frame is not None and args.reference_frame not in [index for index,_ in frames]:
            cap = cv2.VideoCapture(str(path))
            cap.set(cv2.CAP_PROP_POS_FRAMES,args.reference_frame)
            ok,image = cap.read()
            cap.release()
            if not ok:
                raise RuntimeError('Cannot decode frozen reference frame')
            frames.append((args.reference_frame,image))
            frames.sort(key=lambda pair:pair[0])
        started = time.monotonic()
        with measured_resources() as resources:
            outputs, version = _climbing_model_masks_batch([frame for _, frame in frames],
                time.monotonic() + 900, lambda: False, pack_masks=True, reuse_model=True)
        np.savez_compressed(case / 'model-output.npz', **{
            f'f{i}_m{j}': mask for i, (masks, _) in enumerate(outputs) for j, mask in enumerate(masks)})
        native = {'frames': [index for index, _ in frames], 'scores': [scores for _, scores in outputs]}
        (case / 'native.json').write_text(json.dumps(native), encoding='utf-8')
        traces = []
        # Reuse exactly the same inference output to isolate downstream effects.
        with patch('core.climb_replay._climbing_model_masks_batch', return_value=(outputs, version)):
            holds, rejects, diagnostics, _, _ = AliyunReplayAnalyzer._video_holds(frames=frames,
                route_color='全部待核验', route_color_sample=None, saved_route_reference=None,
                deadline=time.monotonic() + 900, progress=lambda *_: None, cancelled=lambda: False, trace=traces,
                reference_source_frame=args.reference_frame)
        # No route color has been guessed: this is an all-candidate map audit.
        fused = [row for row in traces if row['stage'] == 'fusion']
        ref = next(frame for index, frame in frames if index == diagnostics['reference_frame']).copy()
        for row in fused:
            polygon = np.rint(np.asarray(row['polygon']) * [ref.shape[1], ref.shape[0]]).astype(np.int32)
            cv2.polylines(ref, [polygon], True, (0, 220, 255), 1)
            cv2.putText(ref, row['candidate_id'].split('-')[-1], tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX,
                        .45, (0, 220, 255), 1)
        cv2.imwrite(str(case / 'fused.jpg'), ref)
        for frame_index, frame in frames:
            cv2.imwrite(str(case / f'source-{frame_index}.jpg'), frame)
        row = {'case': number, 'source_sha256': before, 'source_unchanged': before == digest(path),
               'width': info.width, 'height': info.height, 'source_fps': info.fps,
               'duration': info.duration_seconds, 'model_version': version,
               'seconds': round(time.monotonic() - started, 3), 'resources': resources,
               'diagnostics': diagnostics, 'trace': traces,
               'accuracy_status': 'not_scored_without_verified_reference'}
        (case / 'report.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest['cases'].append({k: v for k, v in row.items() if k != 'trace'})
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"case {number:02}: {sum(len(m) for m, _ in outputs)} model candidates -> {len(fused)} fused; "
              f"{row['seconds']}s; source unchanged={row['source_unchanged']}", flush=True)


if __name__ == '__main__':
    main()
