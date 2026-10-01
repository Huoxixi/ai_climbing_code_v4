"""Offline instance metrics. Never treat predictions as reviewed ground truth."""
from collections import Counter

import cv2
import numpy as np
from core.photo_route_instance_masks import decode_mask


CONDITIONS = ('low_saturation', 'shadow', 'chalk')


def mask_for(contour, shape):
    points = np.asarray(contour, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('轮廓必须包含至少三个有限坐标点')
    if (points < 0).any() or (points[:, 0] >= shape[1]).any() or (points[:, 1] >= shape[0]).any():
        raise ValueError('轮廓超出原图范围')
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [points.astype(np.int32)], 1)
    return mask


def iou(first, second):
    union = np.count_nonzero((first > 0) | (second > 0))
    return np.count_nonzero((first > 0) & (second > 0)) / union if union else 0.0


def mask_for_object(obj, shape):
    return decode_mask(obj['mask_rle'],shape) if 'mask_rle' in obj else mask_for(obj['contour'],shape)


def match_instances(scores, threshold=.5):
    """Maximum-cardinality one-to-one matching; deterministic IoU tie ordering.

    Greedy highest-IoU matching can undercount valid objects. Augmenting paths
    maximize the number of valid matches; this is not COCO confidence-ranked AP.
    """
    edges = [sorted(np.flatnonzero(row >= threshold), key=lambda p: (-row[p], p)) for row in scores]
    owners = {}

    def assign(ti, visited):
        for pi in edges[ti]:
            if pi in visited:
                continue
            visited.add(pi)
            if pi not in owners or assign(owners[pi], visited):
                owners[pi] = ti
                return True
        return False

    for ti in range(len(edges)):
        assign(ti, set())
    return sorted((float(scores[ti, pi]), ti, int(pi)) for pi, ti in owners.items())


def boundary_f1(first, second, tolerance=2):
    if not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError('边界容差必须为非负整数像素')
    boxes = [cv2.boundingRect(m) for m in (first, second)]
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[0]+b[2] for b in boxes), max(b[1]+b[3] for b in boxes)
    if right <= left or bottom <= top: return 0.0
    first, second = first[top:bottom,left:right], second[top:bottom,left:right]
    kernel = np.ones((3, 3), np.uint8)
    edges = [(m > cv2.erode(m, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)) for m in (first, second)]
    if not all(e.any() for e in edges):
        return 0.0
    distances = [cv2.distanceTransform((~e).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) for e in edges]
    recall = float(np.mean(distances[1][edges[0]] <= tolerance))
    precision = float(np.mean(distances[0][edges[1]] <= tolerance))
    return 2 * recall * precision / (recall + precision) if recall + precision else 0.0


def evaluate_objects(truth, predictions, shape, tolerance=2):
    if any(o.get('kind') not in ('hold', 'volume') for o in truth + predictions):
        raise ValueError('实例类别必须明确映射为 hold 或 volume')
    excluded = [t for t in truth if t.get('disputed') or t.get('ignore')]
    truth_indices = [i for i,t in enumerate(truth) if not t.get('disputed') and not t.get('ignore')]
    truth = [t for t in truth if not t.get('disputed') and not t.get('ignore')]
    tm = [mask_for_object(t, shape) for t in truth]
    pm = [mask_for_object(p, shape) for p in predictions]
    truth_areas = [np.count_nonzero(t) for t in tm]
    prediction_areas = [np.count_nonzero(p) for p in pm]
    truth_boxes, prediction_boxes = [cv2.boundingRect(t) for t in tm], [cv2.boundingRect(p) for p in pm]
    intersections = np.zeros((len(tm),len(pm)))
    scores = np.zeros_like(intersections)
    for ti, (tx,ty,tw,th) in enumerate(truth_boxes):
        for pi, (px,py,pw,ph) in enumerate(prediction_boxes):
            left,top,right,bottom = max(tx,px),max(ty,py),min(tx+tw,px+pw),min(ty+th,py+ph)
            if right<=left or bottom<=top: continue
            overlap = np.count_nonzero(tm[ti][top:bottom,left:right] & pm[pi][top:bottom,left:right])
            intersections[ti,pi] = overlap
            scores[ti,pi] = overlap / max(1,truth_areas[ti]+prediction_areas[pi]-overlap)
    pairs = match_instances(scores)
    used = {pi for _, _, pi in pairs}
    matched_truth = {ti for _, ti, _ in pairs}
    # Exclude predictions only when unmatched and predominantly on a disputed
    # instance. A merged mask cannot hide behind an arbitrary tiny ignore region.
    ignored_masks = [mask_for_object(t, shape) for t in excluded]
    ignored_predictions = {pi for pi, p in enumerate(pm) if pi not in used
                           and any(iou(p, t) >= .5 for t in ignored_masks)}
    correct = wrong = pending = color_total = 0
    confusion = {}; class_matches = Counter(); color_matches = Counter()
    condition_truth = Counter()
    condition_matched = Counter()
    condition_correct = Counter()
    for item in truth:
        if item.get('color_group') in (None, '待确认'):
            continue
        for condition in set(item.get('conditions', [])):
            if condition in CONDITIONS:
                condition_truth[condition] += 1
    kind_scores = scores.copy()
    for ti,t in enumerate(truth):
        for pi,p in enumerate(predictions):
            if t['kind'] != p['kind'] or pi in ignored_predictions: kind_scores[ti,pi] = -1
    for _,ti,_ in match_instances(kind_scores): class_matches[truth[ti]['kind']] += 1
    for _, ti, pi in pairs:
        t, p = truth[ti], predictions[pi]
        color = t.get('color_group')
        if color and color != '待确认':
            color_total += 1
            proposed = p.get('color_group', '待确认')
            confusion.setdefault(color, Counter())[proposed] += 1
            for condition in set(t.get('conditions', [])):
                if condition in CONDITIONS:
                    condition_matched[condition] += 1
            if proposed == color:
                correct += 1; color_matches[color] += 1
                for condition in set(t.get('conditions', [])):
                    if condition in CONDITIONS:
                        condition_correct[condition] += 1
            elif proposed == '待确认':
                pending += 1
            else:
                wrong += 1
    # Diagnostics, not inferred semantic labels: overlapping duplicates and a
    # prediction covering >=50% of two non-nested truth masks are flagged.
    duplicates = sum(pi not in used and pi not in ignored_predictions and bool(len(tm))
                     and float(scores[:, pi].max()) >= .5 for pi in range(len(pm)))
    merges = 0
    for pi in range(len(pm)):
        covered = [i for i in range(len(tm)) if intersections[i,pi] / max(1,truth_areas[i]) >= .5]
        merges += any(np.count_nonzero((tm[a] > 0) & (tm[b] > 0)) / max(1, min(np.count_nonzero(tm[a]), np.count_nonzero(tm[b]))) < .1
                      for offset, a in enumerate(covered) for b in covered[offset+1:])
    low_iou = sum(score < .65 for score, _, _ in pairs)
    partial_misses = sum(ti not in matched_truth and any(
        intersections[ti, pi] / max(1, truth_areas[ti]) >= .25 for pi in range(len(pm)))
        for ti in range(len(tm)))
    severe = low_iou + partial_misses + duplicates + merges
    return {'truth': len(truth), 'predictions': len(predictions)-len(ignored_predictions), 'matched': len(pairs),
            'excluded_truth': len(excluded), 'excluded_predictions': len(ignored_predictions),
            'severe_contour_failures': int(severe),
            'severe_contour_breakdown': {'substantial_missing_or_excess': int(low_iou + partial_misses),
                                         'unmatched_partial_objects': int(partial_misses),
                                         'duplicates': int(duplicates), 'merges': int(merges)},
            'duplicate_predictions': int(duplicates), 'merge_flags': int(merges),
            'ious': [s for s, _, _ in pairs],
            'boundary_f1_values': [boundary_f1(tm[ti], pm[pi], tolerance) for _, ti, pi in pairs],
            'color_correct': correct, 'color_wrong': wrong, 'color_pending': pending, 'color_matched': color_total,
            'color_truth': dict(Counter(t['color_group'] for t in truth if t.get('color_group') not in (None, '待确认'))),
            'color_matches': dict(color_matches), 'color_confusion': {k: dict(v) for k, v in confusion.items()},
            'condition_color_truth': dict(condition_truth),
            'condition_color_matched': dict(condition_matched),
            'condition_color_correct': dict(condition_correct),
            'kind_truth': dict(Counter(t['kind'] for t in truth)),
            'kind_predictions': dict(Counter(p['kind'] for i, p in enumerate(predictions) if i not in ignored_predictions)),
            'kind_matches': dict(class_matches),
            'matches': [{'truth_index': truth_indices[ti], 'prediction_index': pi, 'iou': s} for s, ti, pi in pairs]}


def summarize(rows):
    def total(key): return sum(r[key] for r in rows)
    def ratio(n, d): return n / d if d else None
    def combined(key):
        result = Counter()
        for row in rows: result.update(row[key])
        return result
    counts = {k: total(k) for k in ('truth', 'predictions', 'matched',
        'excluded_truth', 'excluded_predictions', 'severe_contour_failures', 'duplicate_predictions', 'merge_flags',
        'color_correct', 'color_wrong', 'color_pending', 'color_matched')}
    kinds = [combined(k) for k in ('kind_truth', 'kind_predictions', 'kind_matches')]
    colors, successes = combined('color_truth'), combined('color_matches')
    condition_counts = [combined(k) for k in ('condition_color_truth', 'condition_color_matched',
                                               'condition_color_correct')]
    ious = [v for r in rows for v in r['ious']]
    boundaries = [v for r in rows for v in r['boundary_f1_values']]
    confusion = {}
    for row in rows:
        for color, values in row['color_confusion'].items(): confusion.setdefault(color, Counter()).update(values)
    return {'counts': counts, 'object_recall': ratio(counts['matched'], counts['truth']),
        'object_precision': ratio(counts['matched'], counts['predictions']),
        'severe_contour_failures': counts['severe_contour_failures'],
        'mean_iou': float(np.mean(ious)) if ious else None, 'median_iou': float(np.median(ious)) if ious else None,
        'boundary_f1': float(np.mean(boundaries)) if boundaries else None,
        'boundary_f1_median': float(np.median(boundaries)) if boundaries else None,
        'boundary_f1_p10': float(np.percentile(boundaries, 10)) if boundaries else None,
        'correct_group_recall': ratio(counts['color_correct'], sum(colors.values())),
        'color_accuracy': ratio(counts['color_correct'], counts['color_matched']),
        'wrong_color_rate': ratio(counts['color_wrong'], counts['color_matched']),
        'pending_color_rate': ratio(counts['color_pending'], counts['color_matched']),
        'per_color': {c: {'truth': n, 'correct': successes[c], 'recall': ratio(successes[c], n)} for c, n in colors.items()},
        'color_confusion': {c: dict(v) for c, v in confusion.items()},
        'color_by_condition': {condition: {
            'truth': condition_counts[0][condition],
            'matched': condition_counts[1][condition],
            'correct': condition_counts[2][condition],
            'accuracy': ratio(condition_counts[2][condition], condition_counts[1][condition]),
            'correct_group_recall': ratio(condition_counts[2][condition], condition_counts[0][condition]),
        } for condition in CONDITIONS},
        'per_kind': {k: {'truth': kinds[0][k], 'predictions': kinds[1][k], 'matched': kinds[2][k],
                         'recall': ratio(kinds[2][k], kinds[0][k]), 'precision': ratio(kinds[2][k], kinds[1][k])}
                     for k in ('hold', 'volume')}}
