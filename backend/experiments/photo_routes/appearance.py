"""Original bounded colour/relationship implementation; no third-party code copy."""
import cv2
import numpy as np

from core.photo_route_colors import classify_mask_color
from .geometry import local_mask, box_iou


def mask_pixels(image, obj):
    (x, y), mask = local_mask(obj, image.shape[:2])
    crop = image[y:y+mask.shape[0], x:x+mask.shape[1]]
    interior = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
    if interior.sum() < 12:
        interior = mask > 0
    pixels = crop[interior]
    if len(pixels) > 2048:
        pixels = pixels[np.linspace(0, len(pixels)-1, 2048, dtype=int)]
    return pixels


def color_descriptor(pixels):
    if len(pixels) < 3:
        return np.zeros(3), 0., np.zeros(3)
    samples = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_BGR2LAB)[0].astype(float)
    centers = samples[np.linspace(0, len(samples)-1, min(3, len(samples)), dtype=int)]
    # Deterministic Lloyd iterations. Input is capped before Lab conversion.
    for _ in range(15):
        labels = ((samples[:, None] - centers)**2).sum(2).argmin(1)
        updated = np.array([samples[labels == i].mean(0) if (labels == i).any() else c
                            for i, c in enumerate(centers)])
        if np.allclose(updated, centers, atol=.01):
            break
        centers = updated
    counts = np.bincount(labels, minlength=len(centers))
    index = int(counts.argmax())
    return centers[index], float(counts[index]/len(samples)), samples.std(0)


def assign_colors(image, objects, palette=None, mode='lab', threshold=.7):
    if mode not in ('lab', 'hsv'):
        raise ValueError('未知分色方式')
    for obj in objects:
        center, share, texture = color_descriptor(mask_pixels(image, obj))
        obj['lab'] = center.tolist()
        obj['appearance_std'] = texture.tolist()
        obj['color_group'], obj['color_confidence'] = '待确认', 0.
        if mode == 'hsv':
            (x, y), mask = local_mask(obj, image.shape[:2])
            name = classify_mask_color(image[y:y+mask.shape[0], x:x+mask.shape[1]], mask,
                                       version='interior-v4')
            obj['color_group'] = name
            obj['color_confidence'] = share if name != '待确认' else 0.
        elif palette:
            distances = sorted((float(np.linalg.norm((center - np.asarray(anchor['lab'])) /
                                                     np.asarray(anchor['scale']))), name)
                               for name, anchor in palette['anchors'].items())
            if len(distances) < 2:
                raise ValueError('校准色板至少需要两种颜色')
            best, name = distances[0]
            margin = distances[1][0] - best
            confidence = share * max(0., min(1., margin / 2.)) * np.exp(-best / 6.)
            obj['color_confidence'] = float(confidence)
            if confidence >= threshold:
                obj['color_group'] = name


def pair_features(a, b, size):
    """Symmetric features: two members' colour, position, size and texture."""
    width, height = size
    x, y, w, h = a['source_bbox_px']
    u, v, bw, bh = b['source_bbox_px']
    lab = np.abs(np.asarray(a['lab']) - b['lab']) / 255.
    position = [abs(x+w/2-u-bw/2)/width, abs(y+h/2-v-bh/2)/height]
    area = abs(np.log(max(1, w*h)/max(1, bw*bh))) / 5.
    texture = np.abs(np.asarray(a['appearance_std']) - b['appearance_std']) / 128.
    return np.r_[lab, position, area, texture]


def probability(model, features):
    value = np.asarray(features, dtype=float)
    weights = np.asarray(model['weights'], dtype=float)
    mean, scale = np.asarray(model['mean']), np.asarray(model['scale'])
    if value.shape[-1] != len(weights) or not np.isfinite(value).all() or np.any(scale <= 0):
        raise ValueError('分类器特征不兼容')
    logits = ((value-mean)/scale) @ weights + float(model['bias'])
    return 1. / (1. + np.exp(-np.clip(logits, -40, 40)))


def quality_features(obj):
    _, _, w, h = obj['source_bbox_px']
    return [obj['confidence'], obj.get('stability', 0.), float(obj.get('truncated', False)),
            float(obj.get('conflict', False)), np.log1p(w*h)/15., min(w, h)/max(w, h)]


def group_routes(objects, size, model=None, threshold=.95):
    """Complete-link merging avoids connected-component bridge chains.

    Shared volumes do not connect hold groups. Competing memberships and
    uncalibrated classifications require review instead of confident guesses.
    """
    holds = [o for o in objects if o['kind'] == 'hold']
    n = len(holds)
    scores = np.eye(n)
    for i in range(n):
        for j in range(i):
            a, b = holds[i], holds[j]
            if model is None:
                same = a['color_group'] == b['color_group'] != '待确认'
                f = pair_features(a, b, size)
                scores[i, j] = scores[j, i] = .8 if same and np.linalg.norm(f[3:5]) < .22 else 0.
            else:
                scores[i, j] = scores[j, i] = float(probability(model, pair_features(a, b, size)))
    grouping_threshold = threshold if model else .75
    groups = [[i] for i in range(n)]
    while True:
        options = [(float(scores[np.ix_(a, b)].min()), i, j)
                   for i, a in enumerate(groups) for j, b in enumerate(groups[:i])]
        if not options:
            break
        value, i, j = max(options)
        if value < grouping_threshold:
            break
        groups[j] += groups.pop(i)
    routes = []
    for group in groups:
        members = [holds[i] for i in group]
        outside = [i for i in range(n) if i not in group]
        competing = bool(outside and (scores[np.ix_(group, outside)] >= grouping_threshold).any())
        reasons = []
        if model is None:
            reasons.append('线路关系分类器未训练；仅为空间颜色候选')
        if competing:
            reasons.append('存在竞争线路成员，请确认起点或成员')
        if len(group) < 3:
            reasons.append('可见成员不足')
        if any(o['color_group'] == '待确认' or o.get('needs_review') or o.get('conflict') or o.get('truncated') for o in members):
            reasons.append('成员颜色或轮廓需要确认')
        # Volumes may belong to several routes. Offer separately; no automatic assignment.
        nearby = [v['id'] for v in objects if v['kind'] == 'volume'
                  and any(box_iou(v['source_bbox_px'], m['source_bbox_px']) > 0 for m in members)]
        if nearby:
            reasons.append('邻近或承载造型的线路归属待确认')
        score = float(scores[np.ix_(group, group)].min()) if len(group) > 1 else 0.
        routes.append({'id': f'candidate-{len(routes)+1:03d}', 'member_ids': [o['id'] for o in members],
                       'confidence': score, 'review_status': 'needs_review' if reasons else 'automatic',
                       'reasons': reasons, 'unassigned_volume_ids': nearby})
    return routes
