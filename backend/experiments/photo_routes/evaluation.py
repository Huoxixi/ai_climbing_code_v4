"""Kind-aware object matching and exact route-set metrics on bounded masks."""
from collections import Counter

import numpy as np

from core.photo_route_evaluation import match_instances
from .geometry import local_mask, overlap


def evaluate_sample(sample, prediction):
    shape = tuple(sample['size'][::-1])
    truth, proposed = sample['objects'], prediction.get('objects', [])
    if len(proposed) > 300 or len({o['id'] for o in proposed}) != len(proposed):
        raise ValueError('预测对象过多或 ID 重复')
    scores = np.zeros((len(truth), len(proposed)))
    for i, obj in enumerate(truth):
        a = local_mask(obj, shape)
        for j, guess in enumerate(proposed):
            if obj['kind'] == guess['kind']:
                scores[i, j] = overlap(a, local_mask(guess, shape))
    matches = match_instances(scores)
    mapping = {proposed[j]['id']: truth[i]['id'] for _, i, j in matches}
    kinds = {kind: {'truth': sum(o['kind'] == kind for o in truth),
                    'predicted': sum(o['kind'] == kind for o in proposed),
                    'matched': sum(truth[i]['kind'] == kind for _, i, _ in matches)}
             for kind in ('hold', 'volume')}
    hold_matches = [(s, i, j) for s, i, j in matches if truth[i]['kind'] == 'hold']
    color_matches = [(s, i, j) for s, i, j in hold_matches if truth[i].get('color_group') != '待确认']
    correct_colors = sum(truth[i]['color_group'] == proposed[j].get('color_group') for _, i, j in color_matches)
    confusion = Counter((truth[i]['color_group'], proposed[j].get('color_group', '待确认')) for _, i, j in color_matches)
    expected = [set(r['member_ids']) for r in sample.get('routes', []) if r['decidable']]
    automatic, exact, used = 0, 0, set()
    candidate_ids = set()
    for route in prediction.get('route_candidates', []):
        if not route.get('id') or route['id'] in candidate_ids:
            raise ValueError('候选线路 ID 缺失或重复')
        candidate_ids.add(route['id'])
        members = route['member_ids']
        if not members or len(members) != len(set(members)) or not set(members) <= {o['id'] for o in proposed}:
            raise ValueError('预测线路引用不存在、重复或空成员')
        if route['review_status'] != 'automatic':
            continue
        automatic += 1
        if prediction.get('status') != 'completed' or any(m not in mapping for m in members):
            continue
        mapped = {mapping[m] for m in members}
        for i, target in enumerate(expected):
            if i not in used and target == mapped:
                used.add(i)
                exact += 1
                break
    return {'id': sample['id'], 'kind_counts': kinds, 'hold_ious': [s for s, _, _ in hold_matches],
            'color_correct': correct_colors, 'color_matched': len(color_matches),
            'color_unknown_truth': sum(o['kind'] == 'hold' and o['color_group'] == '待确认' for o in truth),
            'color_confusion': [{'truth': a, 'prediction': b, 'count': c} for (a, b), c in confusion.items()],
            'decidable_routes': len(expected), 'undecidable_routes': sum(not r['decidable'] for r in sample.get('routes', [])),
            'automatic_routes': automatic, 'exact_routes': exact,
            'completed': prediction.get('status') == 'completed'}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(rows):
    count = lambda key: sum(r[key] for r in rows)
    per_kind = {}
    for kind in ('hold', 'volume'):
        counts = {key: sum(r['kind_counts'][kind][key] for r in rows) for key in ('truth', 'predicted', 'matched')}
        per_kind[kind] = {**counts, 'precision': ratio(counts['matched'], counts['predicted']),
                          'recall': ratio(counts['matched'], counts['truth'])}
    ious = [iou for row in rows for iou in row['hold_ious']]
    return {'per_kind': per_kind, 'hold_mean_iou': float(np.mean(ious)) if ious else None,
            'color_accuracy': ratio(count('color_correct'), count('color_matched')),
            'color_matched': count('color_matched'), 'color_unknown_truth': count('color_unknown_truth'),
            'route_coverage': ratio(count('exact_routes'), count('decidable_routes')),
            'route_precision': ratio(count('exact_routes'), count('automatic_routes')),
            'exact_routes': count('exact_routes'), 'automatic_routes': count('automatic_routes'),
            'undecidable_fraction': ratio(count('undecidable_routes'), count('undecidable_routes')+count('decidable_routes')),
            'all_completed': bool(rows) and all(r['completed'] for r in rows)}


def quality_gate(metrics):
    hold = metrics['per_kind']['hold']
    thresholds = {'hold_precision': (hold['precision'], .95), 'hold_recall': (hold['recall'], .90),
                  'hold_mean_iou': (metrics['hold_mean_iou'], .80), 'color_accuracy': (metrics['color_accuracy'], .95),
                  'route_coverage': (metrics['route_coverage'], .80), 'route_precision': (metrics['route_precision'], .95)}
    failures = [key for key, (value, minimum) in thresholds.items() if value is None or value < minimum]
    if not metrics['all_completed']:
        failures.append('存在未完成任务')
    if metrics['color_unknown_truth']:
        failures.append('岩点颜色真值不完整')
    return failures


def validation_failures(report):
    """Return reasons a validation report is ineligible for freezing.

    Validation is allowed to choose a configuration, but it may not bypass the
    same quality/resource thresholds later applied to holdout data.
    """
    failures = list(quality_gate(report.get('metrics', {}))) if report.get('metrics') else ['缺少质量指标']
    audit = report.get('dataset_audit', {})
    if audit.get('eligible') is not True:
        failures.append('数据集尚未满足正式训练/验证/留出要求')
    performance = report.get('performance', {})
    if (not performance.get('all_successful') or
            not isinstance(performance.get('peak_bytes'), int) or performance['peak_bytes'] > 1_000_000_000 or
            not isinstance(performance.get('p95_seconds'), (int, float)) or performance['p95_seconds'] > 120):
        failures.append('验证集资源或任务完成门槛不通过')
    recipe = report.get('recipe', {})
    if recipe.get('scheme') == 'C' and not recipe.get('quality'):
        failures.append('C 尚缺训练集训练的边界质量判断器')
    return failures


def rank_validation(reports):
    """Rank only fully qualified reports from the same validation set."""
    if not reports:
        return []
    identity = (reports[0].get('manifest_sha256'), reports[0].get('sample_ids'))
    for report in reports:
        if report.get('split') != 'validation':
            raise ValueError('验证选优只能使用 validation 报告')
        if (report.get('manifest_sha256'), report.get('sample_ids')) != identity:
            raise ValueError('不能跨验证集选优')
    eligible = [report for report in reports if not validation_failures(report)]
    return sorted(eligible, key=lambda report: (
        -report['metrics']['exact_routes'],
        report['performance']['peak_bytes'],
        report['performance']['p95_seconds'],
    ))


def compare_quantization(fp32, int8):
    """Match evaluation identities; weights necessarily differ between precisions."""
    for field in ('manifest_sha256', 'split', 'source_sha256', 'sample_ids'):
        if fp32[field] != int8[field]:
            raise ValueError(f'量化对照不一致: {field}')
    if fp32['recipe']['scheme'] != int8['recipe']['scheme'] or fp32['recipe']['precision'] != 'fp32' or int8['recipe']['precision'] != 'int8':
        raise ValueError('需要同方案 FP32/INT8 对照')
    # Only detector/segmenter weights and precision may differ.
    def comparable(recipe):
        result = {k: v for k, v in recipe.items() if k not in ('precision', 'detector', 'segmenter')}
        for key in ('detector', 'segmenter'):
            if key in recipe:
                result[key] = {k: v for k, v in recipe[key].items() if k not in ('path', 'sha256', 'quantized_from')}
        return result
    if comparable(fp32['recipe']) != comparable(int8['recipe']):
        raise ValueError('量化对照同时改变了预处理、阈值或后处理')
    for key in ('detector', 'segmenter'):
        if key in int8['recipe'] and int8['recipe'][key].get('quantized_from') != fp32['recipe'][key]['sha256']:
            raise ValueError('INT8 产物未绑定对应 FP32 权重')
    def values(m):
        return [m['per_kind']['hold']['precision'], m['per_kind']['hold']['recall'],
                m['hold_mean_iou'], m['color_accuracy'], m['route_coverage'], m['route_precision']]
    pairs = zip(values(fp32['metrics']), values(int8['metrics']))
    losses = [a-b if a is not None and b is not None else None for a, b in pairs]
    return {'losses': losses, 'passed': not quality_gate(int8['metrics'])
            and all(loss is not None and loss <= .01+1e-12 for loss in losses)}


def rank_reports(reports):
    if not reports:
        return []
    identity = (reports[0]['manifest_sha256'], reports[0]['sample_ids'])
    for report in reports:
        if (report['manifest_sha256'], report['sample_ids']) != identity:
            raise ValueError('不能跨测试集排名')
    eligible = [r for r in reports if r.get('passed') is True and r.get('split') == 'holdout']
    return sorted(eligible, key=lambda r: (-r['metrics']['exact_routes'],
                  r['human_member_edits'], r['performance']['peak_bytes'], r['performance']['p95_seconds']))
