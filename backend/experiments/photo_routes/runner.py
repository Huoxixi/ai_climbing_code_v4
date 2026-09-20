"""Supervised subprocess inference; RSS sampling does not claim a server test."""
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from core.photo_route_inference_lock import serialized_inference
from .data import (audit_manifest, read_json, write_new, digest_json, digest_file,
                   source_digest, image_path)
from .inference import check_recipe, run_pipeline
from .evaluation import evaluate_sample, summarize, quality_gate, validation_failures


def identity(recipe, audit):
    import cv2
    import onnxruntime
    return {'recipe_sha256': digest_json(recipe), 'manifest_sha256': audit['manifest_sha256'],
            'source_sha256': source_digest(), 'runtime_sha256': digest_json({
                'python': platform.python_version(), 'numpy': np.__version__,
                'opencv': cv2.__version__, 'onnxruntime': onnxruntime.__version__})}


def validate_lock(path, expected):
    lock = read_json(path)
    identity_keys = ('recipe_sha256', 'manifest_sha256', 'source_sha256', 'runtime_sha256')
    if (lock.get('schema_version') != 1 or not lock.get('validation_report_sha256') or
            any(key not in expected or lock.get(key) != expected[key] for key in identity_keys)):
        raise ValueError('留出锁不一致：模型、参数、源码或数据已变化')
    return lock


def freeze_report(report_path, output):
    report = read_json(report_path)
    if report.get('split') != 'validation' or not report.get('sample_ids'):
        raise ValueError('只能从非空验证集报告冻结配置')
    if report['source_sha256'] != source_digest() or report['recipe_sha256'] != digest_json(report['recipe']):
        raise ValueError('验证报告已过期或 recipe 摘要不符')
    failures = validation_failures(report)
    if failures:
        raise ValueError('验证报告未达到冻结条件: ' + '、'.join(failures))
    lock = {key: report[key] for key in ('recipe_sha256', 'manifest_sha256', 'source_sha256', 'runtime_sha256')}
    lock.update(schema_version=1, validation_report_sha256=digest_file(report_path))
    write_new(output, lock)
    return lock


def worker(manifest_path, recipe_path, sid, output):
    # Parent already audits the dataset; child reads only the selected photo.
    manifest, recipe = read_json(manifest_path), read_json(recipe_path)
    sample = next(s for s in manifest['samples'] if s['id'] == sid)
    try:
        result = run_pipeline(image_path(Path(manifest_path).parent, sample['image']), recipe, Path(recipe_path).parent)
    except Exception as exc:
        result = {'schema_version': 1, 'status': 'failed', 'objects': [], 'route_candidates': [],
                  'error': f'{type(exc).__name__}: {exc}'}
    from scripts.run_climbing_instance_model import peak_memory_bytes
    result.update(id=sid, image_sha256=sample['image_sha256'], recipe_sha256=digest_json(recipe),
                  peak_process_bytes=peak_memory_bytes())
    write_new(output, result)


def supervise(command, output, companion_pids=(), cancelled=lambda: False):
    import psutil
    parent = psutil.Process()
    companions = [psutil.Process(pid) for pid in companion_pids]
    if any(p.pid == parent.pid for p in companions):
        raise ValueError('companion PID 不可重复包含测量进程')
    start, peak, unavailable, reason = time.monotonic(), 0, False, None
    companion_identity = [(p.pid, p.create_time()) for p in companions]
    log = Path(output).with_suffix('.log')
    with log.open('x', encoding='utf-8') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        try:
            process = psutil.Process(child.pid)
            while child.poll() is None:
                try:
                    processes = {p.pid: p for p in [parent, process]+process.children(recursive=True)}
                    for companion, (pid, created) in zip(companions, companion_identity):
                        if companion.create_time() != created or not companion.is_running():
                            raise psutil.NoSuchProcess(pid)
                        processes[pid] = companion
                        processes.update({p.pid: p for p in companion.children(recursive=True)})
                    current = sum(p.memory_info().rss for p in processes.values())
                    peak = max(peak, current)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    unavailable = True
                if cancelled():
                    reason = 'cancelled'
                elif peak > 1_000_000_000:
                    reason = 'memory_limit'
                elif time.monotonic()-start > 120:
                    reason = 'timeout'
                if reason:
                    # Only terminate this run's owned worker tree, never companion services.
                    try:
                        for descendant in process.children(recursive=True):
                            descendant.kill()
                    except psutil.NoSuchProcess:
                        pass
                    child.kill()
                    break
                time.sleep(.02)
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    return {'seconds': time.monotonic()-start, 'peak_bytes': peak, 'sampling_interval_ms': 20,
            'measurement_incomplete': unavailable, 'termination': reason, 'exit_code': child.returncode,
            'scope': 'offline-plus-companion-processes' if companions else 'offline-process-tree'}


@serialized_inference
def run_dataset(manifest_path, recipe_path, output, *, split='validation', lock=None,
                repeat=1, companion_pids=(), cancelled=lambda: False):
    manifest_path, recipe_path, output = Path(manifest_path).resolve(), Path(recipe_path).resolve(), Path(output).resolve()
    manifest, audit = audit_manifest(manifest_path)
    recipe = check_recipe(read_json(recipe_path), recipe_path.parent)
    evidence = identity(recipe, audit)
    if split == 'holdout':
        if lock is None:
            raise ValueError('留出运行必须先锁定验证报告')
        validate_lock(lock, evidence)
    if not 1 <= repeat <= 100:
        raise ValueError('repeat 必须在 1 到 100 之间')
    samples = [s for s in manifest['samples'] if s['split'] == split]
    if not samples:
        raise ValueError('所选集合没有照片')
    # Exclude training leakage from models carrying training provenance.
    for key in ('palette', 'relation', 'quality'):
        if recipe.get(key):
            model = read_json(recipe_path.parent/recipe[key]['path'])
            held_out = [s for s in manifest['samples'] if s['split'] in ('validation', 'holdout')]
            if any(s['image_sha256'] in model.get('training_image_sha256', []) or
                   s['wall_id'] in model.get('training_wall_ids', []) for s in held_out):
                raise ValueError(f'{key} 训练与验证/留出重合')
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'recipe.json', recipe)
    runs = []
    for repetition in range(repeat):
        for sample in samples:
            if cancelled():
                break
            name = f'prediction-{len(runs)+1:05d}.json'
            destination = output/name
            command = [sys.executable, '-B', '-m', 'experiments.photo_routes', '_worker',
                       '--manifest', str(manifest_path), '--recipe', str(recipe_path),
                       '--sample', sample['id'], '--output', str(destination)]
            measurement = supervise(command, destination, companion_pids, cancelled)
            if not destination.is_file():
                write_new(destination, {'schema_version': 1, 'id': sample['id'], 'status': 'failed',
                    'image_sha256': sample['image_sha256'], 'recipe_sha256': evidence['recipe_sha256'],
                    'objects': [], 'route_candidates': [], 'error': measurement['termination'] or 'worker_failed'})
            result = read_json(destination)
            if measurement['termination'] or measurement['exit_code']:
                measurement['success'] = False
            else:
                measurement['success'] = result['status'] == 'completed'
            # OS process HWM catches short spikes missed by the sampler. This is
            # additional evidence, not a sum of asynchronous process high-water marks.
            measurement['peak_bytes'] = max(measurement['peak_bytes'], result.get('peak_process_bytes') or 0)
            runs.append({'sample_id': sample['id'], 'repetition': repetition, 'prediction': name, **measurement})
            print({'sample': sample['id'], 'repetition': repetition, 'seconds': round(measurement['seconds'], 2),
                   'peak_bytes': measurement['peak_bytes'], 'success': measurement['success']}, flush=True)
        if cancelled():
            break
    report = {'schema_version': 1, **evidence, 'recipe': recipe, 'dataset_audit': audit,
              'split': split, 'sample_ids': [s['id'] for s in samples], 'repeat': repeat, 'runs': runs,
              'platform': {'system': platform.platform(), 'processor': platform.processor(),
                          'logical_cpus': os.cpu_count(), 'python': sys.version},
              'companion_pids': list(companion_pids), 'server_acceptance_passed': False}
    write_new(output/'run.json', report)
    return report


def evaluate_run(manifest_path, run_path, output):
    manifest, audit = audit_manifest(manifest_path)
    run_path = Path(run_path)
    run = read_json(run_path)
    if run['manifest_sha256'] != audit['manifest_sha256'] or run['source_sha256'] != source_digest():
        raise ValueError('数据或源码已变化，实验报告失效')
    samples = {s['id']: s for s in manifest['samples'] if s['split'] == run['split']}
    if set(samples) != set(run['sample_ids']):
        raise ValueError('报告缺失或添加了测试照片')
    rows, seen = [], set()
    for row in run['runs']:
        if row['sample_id'] not in samples:
            raise ValueError('未知测试照片')
        sample = samples[row['sample_id']]
        result = read_json(run_path.parent/row['prediction'])
        if result.get('image_sha256') != sample['image_sha256'] or result.get('recipe_sha256') != run['recipe_sha256']:
            raise ValueError('预测结果与照片/模型配置不一致')
        if row['repetition'] == 0:
            if sample['id'] in seen:
                raise ValueError('重复首轮结果')
            seen.add(sample['id'])
            if not row['success']:
                result = {**result, 'status': 'failed'}
            rows.append(evaluate_sample(sample, result))
    if seen != set(samples):
        raise ValueError('测试中断或首轮结果不完整')
    metrics = summarize(rows)
    performance = {'peak_bytes': max(r['peak_bytes'] for r in run['runs']),
                   'p95_seconds': float(np.percentile([r['seconds'] for r in run['runs']], 95)),
                   'all_successful': all(r['success'] and not r['measurement_incomplete'] for r in run['runs']),
                   'runs': len(run['runs']), 'scope': run['runs'][0]['scope'],
                   'full_service_verified': False, 'queue_verified': False}
    failures = quality_gate(metrics)
    if run['recipe']['scheme'] == 'C' and not run['recipe'].get('quality'):
        failures.append('C 尚缺经过训练的边界质量判断器，当前仅为规则消融')
    if performance['peak_bytes'] > 1_000_000_000 or performance['p95_seconds'] > 120 or not performance['all_successful']:
        failures.append('离线资源或任务完成门槛不通过')
    offline_passed = not failures and audit['eligible'] and run['split'] == 'holdout'
    # The production service is deliberately unchanged. Never pretend that an
    # offline subprocess test covered HTTP concurrency, queueing or server hardware.
    blockers = [*audit['blockers'], *failures, '尚缺目标服务器完整服务及多用户排队验收']
    report = {k: run[k] for k in ('recipe', 'recipe_sha256', 'source_sha256', 'runtime_sha256', 'manifest_sha256', 'split', 'sample_ids')}
    report.update(schema_version=1, dataset_audit=run['dataset_audit'], metrics=metrics, per_image=rows, performance=performance,
                  offline_passed=offline_passed, passed=False, blockers=blockers)
    write_new(output, report)
    return report
