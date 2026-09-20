"""Run from backend: python -m experiments.photo_routes --help."""
import argparse
import json
import sys
from pathlib import Path

from .data import audit_manifest, read_json, write_new, digest_file


def main():
    parser = argparse.ArgumentParser(description='离线 A/B/C 岩点与真实线路对照；不访问生产数据库')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('audit', 'run', '_worker', 'evaluate', 'train-aux', 'train-roi', 'export-coco', 'quantize'):
        sub = commands.add_parser(name)
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
        if name in ('run', '_worker', 'quantize'):
            sub.add_argument('--recipe', type=Path, required=True)
        if name == 'run':
            sub.add_argument('--split', choices=('train', 'validation', 'holdout', 'diagnostic'), default='validation')
            sub.add_argument('--lock', type=Path)
            sub.add_argument('--repeat', type=int, default=1)
            sub.add_argument('--companion-pid', type=int, action='append', default=[])
            sub.add_argument('--cancel-file', type=Path)
        if name == '_worker':
            sub.add_argument('--sample', required=True)
        if name == 'evaluate':
            sub.add_argument('--run', type=Path, required=True)
        if name == 'train-roi':
            sub.add_argument('--epochs', type=int, default=20)
    for name in ('freeze', 'rank', 'compare-int8', 'select-validation'):
        sub = commands.add_parser(name)
        sub.add_argument('--reports', type=Path, nargs='+' if name != 'freeze' else 1, required=True)
        sub.add_argument('--output', type=Path, required=True)
    sub = commands.add_parser('train-quality')
    sub.add_argument('--manifest', type=Path, required=True)
    sub.add_argument('--labels', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True)
    sub = commands.add_parser('train-detector')
    sub.add_argument('--coco-root', type=Path, required=True)
    sub.add_argument('--base-config', type=Path, required=True)
    sub.add_argument('--initial-checkpoint', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True)
    sub.add_argument('--epochs', type=int, default=100)
    sub = commands.add_parser('accept-service')
    sub.add_argument('--report', type=Path, required=True)
    sub.add_argument('--evidence', type=Path, required=True)
    sub.add_argument('--parity-report', type=Path)
    sub.add_argument('--output', type=Path, required=True)
    sub = commands.add_parser('probe-roi')
    sub.add_argument('--manifest', type=Path, required=True)
    sub.add_argument('--model', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True)
    sub.add_argument('--limit', type=int, default=0)
    sub = commands.add_parser('import-indoor')
    sub.add_argument('--source-root', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True)
    sub.add_argument('--download', action='store_true')
    sub.add_argument('--training-pilot', action='store_true', help='全部公开数据仅用于训练先导，不建立验证/留出集')
    sub.add_argument('--image-cache', type=Path, help='复用之前导入的公开图片，只读')
    args = parser.parse_args()
    if args.command == 'audit':
        _, result = audit_manifest(args.manifest)
        write_new(args.output, result)
    elif args.command == 'run':
        from .runner import run_dataset
        result = run_dataset(args.manifest, args.recipe, args.output, split=args.split, lock=args.lock,
                             repeat=args.repeat, companion_pids=args.companion_pid,
                             cancelled=lambda: bool(args.cancel_file and args.cancel_file.exists()))
        result = {'output': str(args.output/'run.json'), 'runs': len(result['runs'])}
    elif args.command == '_worker':
        from .runner import worker
        worker(args.manifest, args.recipe, args.sample, args.output)
        return
    elif args.command == 'evaluate':
        from .runner import evaluate_run
        result = evaluate_run(args.manifest, args.run, args.output)
    elif args.command == 'freeze':
        from .runner import freeze_report
        result = freeze_report(args.reports[0], args.output)
    elif args.command in ('rank', 'compare-int8', 'select-validation'):
        from .evaluation import rank_reports, compare_quantization, rank_validation, validation_failures
        reports = [read_json(p) for p in args.reports]
        if args.command == 'compare-int8':
            if len(reports) != 2:
                raise ValueError('依次提供 FP32 与 INT8 两份报告')
            result = compare_quantization(*reports)
            result.update(fp32_report_sha256=digest_file(args.reports[0]), int8_report_sha256=digest_file(args.reports[1]))
        elif args.command == 'rank':
            result = {'ranked': rank_reports(reports), 'unqualified': sum(not r.get('passed') for r in reports)}
        else:
            ranked = rank_validation(reports)
            def report_hash(report):
                return next(digest_file(path) for path, value in zip(args.reports, reports) if value == report)
            result = {'selected_report_sha256': report_hash(ranked[0]) if ranked else None,
                      'qualified': len(ranked), 'unqualified': len(reports)-len(ranked),
                      'ranked': [{'scheme': report['recipe']['scheme'], 'precision': report['recipe']['precision'],
                                  'report_sha256': report_hash(report),
                                  'exact_routes': report['metrics']['exact_routes'],
                                  'peak_bytes': report['performance']['peak_bytes'],
                                  'p95_seconds': report['performance']['p95_seconds']}
                                 for report in ranked]}
        write_new(args.output, result)
    elif args.command in ('train-aux', 'train-roi', 'export-coco'):
        from .training import train_auxiliary, train_roi, export_coco
        action = {'train-aux': train_auxiliary, 'train-roi': train_roi, 'export-coco': export_coco}[args.command]
        result = action(args.manifest, args.output, **({'epochs': args.epochs} if args.command == 'train-roi' else {}))
    elif args.command == 'train-quality':
        from .training import train_quality
        result = train_quality(args.manifest, args.labels, args.output)
    elif args.command == 'train-detector':
        from .training import train_detector
        result = train_detector(args.coco_root, args.base_config, args.initial_checkpoint, args.output, args.epochs)
    elif args.command == 'accept-service':
        from .acceptance import attach_service
        result = attach_service(args.report, args.evidence, args.output, args.parity_report)
    elif args.command == 'probe-roi':
        from .probe import probe_roi
        result = probe_roi(args.manifest, args.model, args.output, args.limit)
    elif args.command == 'quantize':
        from .quantization import quantize_recipe
        result = quantize_recipe(args.manifest, args.recipe, args.output)
    elif args.command == 'import-indoor':
        from .public_data import import_indoor
        result = import_indoor(args.source_root, args.output, download=args.download,
                               training_pilot=args.training_pilot, image_cache=args.image_cache)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ImportError, KeyError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
