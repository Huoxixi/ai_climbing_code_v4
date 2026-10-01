"""Attach externally measured service evidence to a qualified offline holdout run.

The offline runner cannot generate HTTP/queue evidence because production APIs
remain unchanged. This contract accepts measurements, not a hand-set passed flag.
"""
import math

import numpy as np

from .data import read_json, write_new, digest_file, source_digest


def attach_service(report_path, evidence_path, output, parity_path=None):
    report, evidence = read_json(report_path), read_json(evidence_path)
    if not report.get('offline_passed') or report.get('split') != 'holdout':
        raise ValueError('必须先通过独立留出集离线质量与资源验收')
    if report['source_sha256'] != source_digest():
        raise ValueError('离线报告源码已变化')
    for key in ('recipe_sha256', 'manifest_sha256', 'source_sha256'):
        if evidence.get(key) != report[key]:
            raise ValueError(f'服务证据与离线报告不匹配: {key}')
    if evidence.get('schema_version') != 1 or evidence.get('scope') != 'api-inference-images-cache' or not evidence.get('target_hardware'):
        raise ValueError('缺少目标硬件或完整服务测量范围')
    if evidence.get('synthetic') is not False:
        raise ValueError('合成测试不能用于正式服务验收')
    runs = evidence.get('runs', [])
    if len(runs) < 50 or not any(r.get('cold_start') is True for r in runs):
        raise ValueError('缺少冷启动或连续 50 次服务记录')
    run_ids = [run.get('request_id') for run in runs]
    if any(not value for value in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ValueError('服务记录缺少唯一请求 ID')
    series = {}
    for run in runs:
        if run.get('series_id'):
            series.setdefault(run['series_id'], set()).add(run.get('sequence_index'))
    if not any(set(range(50)) <= indexes for indexes in series.values()):
        raise ValueError('没有可核对的连续 50 次服务序列')
    if not any(r.get('pixels') == 12_000_000 for r in runs) or not any(r.get('ground_truth_objects') == 300 for r in runs):
        raise ValueError('缺少 1200 万像素及 300 对象边界测试')
    failures = []
    for run in runs:
        if not isinstance(run.get('peak_bytes'), int) or run['peak_bytes'] <= 0:
            raise ValueError('内存记录必须为正整数字节')
        if not isinstance(run.get('seconds'), (int, float)) or not math.isfinite(run['seconds']) or run['seconds'] <= 0:
            raise ValueError('耗时记录无效')
        if run.get('completed') is not True or run.get('measurement_complete') is not True:
            failures.append('服务任务未完成或测量不完整')
    queue = evidence.get('queue_requests', [])
    if len(queue) < 2:
        raise ValueError('缺少多用户排队事件')
    intervals, owners, request_ids = [], set(), set()
    for request in queue:
        queued, started, finished = (request.get(k) for k in ('queued_at', 'started_at', 'finished_at'))
        if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (queued, started, finished)) or not queued <= started < finished:
            raise ValueError('队列时间顺序无效')
        if not request.get('request_id') or request['request_id'] in request_ids or not request.get('owner_alias'):
            raise ValueError('缺少唯一请求 ID 或匿名用户标识')
        request_ids.add(request['request_id'])
        owners.add(request['owner_alias'])
        intervals.append((started, finished))
    intervals.sort()
    if len(owners) < 2 or not any(r['queued_at'] < intervals[0][1] and r['started_at'] >= intervals[0][1] for r in queue):
        raise ValueError('事件未证明不同用户同时请求并排队')
    if any(b[0] < a[1] for a, b in zip(intervals, intervals[1:])):
        failures.append('同时执行了多个识别任务')
    peak, p95 = max(r['peak_bytes'] for r in runs), float(np.percentile([r['seconds'] for r in runs], 95))
    if peak > 1_000_000_000 or p95 > 120:
        failures.append('完整服务内存或耗时超标')
    if report['recipe']['precision'] == 'int8':
        parity = read_json(parity_path) if parity_path else {}
        if parity.get('int8_report_sha256') != digest_file(report_path) or parity.get('passed') is not True:
            failures.append('INT8 未通过对应 FP32 最大 1 个百分点退化检查')
    manual_edits = evidence.get('human_member_edits')
    if not isinstance(manual_edits, int) or manual_edits < 0:
        raise ValueError('须提供同留出集复核时实际增删成员次数')
    result = {**report, 'passed': not failures, 'blockers': failures,
              'service_evidence_sha256': digest_file(evidence_path), 'human_member_edits': manual_edits,
              'performance': {'peak_bytes': peak, 'p95_seconds': p95,
                              'full_service_verified': not failures, 'queue_verified': not failures,
                              'target_hardware': evidence['target_hardware'], 'scope': evidence['scope']}}
    write_new(output, result)
    return result
