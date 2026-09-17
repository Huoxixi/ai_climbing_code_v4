"""Conservative original-photo boundary refinement of existing SAM proposals."""
import cv2
import numpy as np


def separate_mask_components(mask, minimum_area):
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8))
    return [(labels == label).astype(np.uint8) * 255 for label in range(1, count)
            if stats[label, cv2.CC_STAT_AREA] >= minimum_area]


def refine_boundary(image, mask):
    """Refine only a narrow uncertain band; preserve the proposal's interior.

    Returns an original-resolution crop and its origin. This does not classify
    a proposal as a climbing hold or invent missing objects.
    """
    height, width = image.shape[:2]
    sy, sx = height / mask.shape[0], width / mask.shape[1]
    x, y, w, h = cv2.boundingRect(mask)
    radius = max(2, min(8, round(max(sx, sy) * 2)))
    left, top = max(0, int(x*sx)-radius*2), max(0, int(y*sy)-radius*2)
    right, bottom = min(width, int(np.ceil((x+w)*sx))+radius*2), min(height, int(np.ceil((y+h)*sy))+radius*2)
    # Map directly to this crop; avoid full-resolution masks for every object.
    transform = np.array([[sx, 0, -left], [0, sy, -top]], np.float32)
    initial = cv2.warpAffine(mask, transform, (right-left, bottom-top), flags=cv2.INTER_NEAREST)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius*2+1, radius*2+1))
    core = cv2.erode(initial, kernel) > 0
    outer = cv2.dilate(initial, kernel) > 0
    if not core.any() or outer.all(): return left, top, initial
    labels = np.where(initial > 0, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
    labels[~outer] = cv2.GC_BGD
    labels[core] = cv2.GC_FGD
    try:
        cv2.grabCut(image[top:bottom, left:right], labels, None,
                    np.zeros((1,65),np.float64), np.zeros((1,65),np.float64), 2, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return left, top, initial
    refined = np.isin(labels, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype(np.uint8) * 255
    parts = separate_mask_components(refined, 1)
    refined = max(parts, key=lambda part: np.count_nonzero((part > 0) & core), default=initial)
    overlap = np.count_nonzero((refined > 0) & (initial > 0))
    union = np.count_nonzero((refined > 0) | (initial > 0))
    if overlap / max(1, union) < .8: return left, top, initial
    return left, top, refined
