"""Run experiment A without importing or changing the production workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.hole_grid_topology import render_hole_grid_overlay, run_topology_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description='离线孔阵拓扑优先基线（不接入正式应用）')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='新建结果 JSON；拒绝覆盖')
    parser.add_argument('--overlay', type=Path, required=True, help='新建分层诊断图；拒绝覆盖')
    parser.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'WIDTH', 'HEIGHT'))
    parser.add_argument('--show-rejected', action='store_true')
    args = parser.parse_args()
    if args.output.exists() or args.overlay.exists():
        raise FileExistsError('输出文件已存在；为保护实验证据，本命令不会覆盖')
    try:
        encoded_source = np.frombuffer(args.image.read_bytes(), dtype=np.uint8)
    except OSError as exc:
        raise ValueError('无法读取输入图片') from exc
    image = cv2.imdecode(encoded_source, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('无法读取输入图片')
    result = run_topology_experiment(image, tuple(args.roi) if args.roi else None)
    overlay = render_hole_grid_overlay(image, result, show_rejected=args.show_rejected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.overlay.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2)
    suffix = args.overlay.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
        args.output.unlink(missing_ok=True)
        raise ValueError('诊断图只支持 PNG、JPEG 或 WebP')
    ok, encoded_overlay = cv2.imencode('.jpg' if suffix == '.jpeg' else suffix, overlay)
    if not ok:
        args.output.unlink(missing_ok=True)
        raise OSError('无法写入诊断图')
    try:
        with args.overlay.open('xb') as handle:
            handle.write(encoded_overlay.tobytes())
    except OSError:
        args.output.unlink(missing_ok=True)
        raise
    print(json.dumps({'status': result['status'], 'result': str(args.output),
                      'overlay': str(args.overlay), 'diagnostics': result.get('diagnostics', {})},
                     ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
