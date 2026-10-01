"""Local masks only: no N x original-height x original-width allocations."""
import cv2
import numpy as np

from core.photo_route_instance_masks import encode_mask, decode_mask


def local_mask(obj, shape):
    if 'mask_rle' in obj:
        data = obj['mask_rle']
        x, y = data['origin']
        h, w = data['size']
        if any(type(v) is not int or v < 0 for v in (x, y, h, w)) or x+w > shape[1] or y+h > shape[0]:
            raise ValueError('局部掩膜越界')
        return (x, y), decode_mask({**data, 'origin': [0, 0]}, (h, w))
    points = np.asarray(obj['contour'], dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('无效轮廓')
    # VIA/COCO polygons use continuous edge coordinates: x==width/y==height
    # is a valid image border, unlike an out-of-range pixel index.
    if (points < 0).any() or (points[:, 0] > shape[1]).any() or (points[:, 1] > shape[0]).any():
        raise ValueError('轮廓越界')
    points = np.minimum(points.astype(np.int32), [shape[1]-1, shape[0]-1])
    x, y, w, h = cv2.boundingRect(points)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [points - [x, y]], 1)
    return (x, y), mask


def intersection(a, b):
    (ax, ay), am = a
    (bx, by), bm = b
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax+am.shape[1], bx+bm.shape[1]), min(ay+am.shape[0], by+bm.shape[0])
    if right <= left or bottom <= top:
        return 0
    return int(np.count_nonzero(am[top-ay:bottom-ay, left-ax:right-ax] & bm[top-by:bottom-by, left-bx:right-bx]))


def overlap(a, b, metric='iou'):
    value = intersection(a, b)
    areas = [np.count_nonzero(m) for _, m in (a, b)]
    divisor = sum(areas)-value if metric == 'iou' else min(areas)
    return value / max(1, divisor)


def box_iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    area = max(0, min(ax+aw, bx+bw)-max(ax, bx))*max(0, min(ay+ah, by+bh)-max(ay, by))
    return area / max(1, aw*ah+bw*bh-area)


def tiles(width, height, edge=640, overlap_ratio=.2):
    """Yield coordinates; never materialize the image slices."""
    def starts(length):
        values = list(range(0, max(1, length-edge+1), int(edge*(1-overlap_ratio))))
        last = max(0, length-edge)
        if values[-1] != last:
            values.append(last)
        return values
    for y in starts(height):
        for x in starts(width):
            yield x, y, min(edge, width-x), min(edge, height-y)


def object_from_mask(mask, origin, kind, score, **extra):
    data = encode_mask(mask, origin)
    x, y = data['origin']
    h, w = data['size']
    (_, _), cropped = local_mask({'mask_rle': data}, (y+h, x+w))
    contours, _ = cv2.findContours(cropped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)[:, 0] + [x, y]
    return {'kind': kind, 'confidence': float(score), 'mask_rle': data,
            'contour': contour.tolist(), 'source_bbox_px': [x, y, w, h], **extra}


def merge_candidate(objects, candidate, shape, threshold=.5):
    """Class-aware suppression preserves native masks instead of unioning neighbours.

    Prefer untruncated masks. Nested hold/volume pairs never suppress each other.
    Same-class strong containment is flagged, not silently collapsed.
    """
    for i, previous in enumerate(objects):
        if previous['kind'] != candidate['kind']:
            continue
        if not box_iou(previous['source_bbox_px'], candidate['source_bbox_px']):
            continue
        if 'mask_rle' in previous and 'mask_rle' in candidate:
            a, b = local_mask(previous, shape), local_mask(candidate, shape)
            match = overlap(a, b)
            if match < threshold and overlap(a, b, 'ios') > .8:
                previous['conflict'] = candidate['conflict'] = True
        else:
            match = box_iou(previous['source_bbox_px'], candidate['source_bbox_px'])
        if match >= threshold:
            rank = lambda o: (not o.get('truncated', False), o['confidence'])
            if rank(candidate) > rank(previous):
                candidate['conflict'] = candidate.get('conflict', False) or previous.get('conflict', False)
                objects[i] = candidate
            return
    objects.append(candidate)
