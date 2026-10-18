"""Conservative image-space identity cues, not a verified person identity model."""
import cv2
import numpy as np

VERSION = 'multi-observation-route-recheck-v5'
MAX_RECOVERY_SECONDS = 1.5


def route_in_frame(bounds, matrix, reference_size, frame_size):
    if bounds is None or matrix is None:
        return None
    try:
        inverse = np.linalg.inv(np.asarray(matrix, dtype=float))
        left, top, right, bottom = bounds
        corners = np.array([[left,top], [right,top], [right,bottom], [left,bottom]]) * reference_size
        mapped = np.column_stack((corners, np.ones(4))) @ inverse.T
        if not np.isfinite(mapped).all() or np.any(np.abs(mapped[:,2]) < 1e-8):
            return None
        xy = mapped[:,:2] / mapped[:,2:] / frame_size
        return [*xy.min(axis=0), *xy.max(axis=0)]
    except (ValueError, np.linalg.LinAlgError):
        return None


def appearance(frame, box):
    # The inner upper body reduces background contamination from extended limbs.
    x, y, right, bottom = box
    w, h = right - x, bottom - y
    crop = frame[int(y + .2*h):int(y + .65*h), int(x + .25*w):int(x + .75*w)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, None, alpha=1, norm_type=cv2.NORM_L1)


def appearance_distance(a, b):
    if a is None or b is None:
        return 1.
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


def near_route(box, bounds, width, height):
    if bounds is None:
        return True
    cx, cy = (box[:2] + box[2:]) / 2 / [width, height]
    left, top, right, bottom = bounds
    # Permit the body below the lowest foot hold at the start, but not a
    # disjoint person at the side of the wall merely because they appear first.
    return left - .06 <= cx <= right + .06 and top - .12 <= cy <= bottom + .18


def recovery_geometry(previous, current):
    old_size, size = previous[2:] - previous[:2], current[2:] - current[:2]
    ratio = size / np.maximum(old_size, 1.)
    distance = np.linalg.norm((current[:2] + current[2:] - previous[:2] - previous[2:]) / 2)
    return bool(np.all((ratio >= .5) & (ratio <= 2.))) and distance <= .6 * np.linalg.norm(old_size)
