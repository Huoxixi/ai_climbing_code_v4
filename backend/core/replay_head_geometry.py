"""Read-only head artwork. Never an observation, joint or measurement input."""
import math

VERSION = 'circle-head-display-v2'


def head_geometry(sample, width, height):
    """Return a circle in normalized image coordinates, or no artwork.

    Only qualified face observations locate the head. Torso length controls its
    size; shoulders alone cannot locate a hidden face. No state or extrapolation.
    Keep this contract in sync with frontend replayHeadGeometry.js.
    """
    if not sample or not sample.get('observed', True) or width <= 0 or height <= 0:
        return None
    xy, scores = sample.get('kpts_xy', []), sample.get('kpts_score', [])
    if len(xy) != 17 or len(scores) != 17:
        return None
    flags = sample.get('joint_eligibility')
    if flags is not None and (len(flags) != 17 or any(type(v) is not bool for v in flags)):
        return None

    def point(i):
        p, s = xy[i], scores[i]
        if (not isinstance(s, (int, float)) or isinstance(s, bool) or not math.isfinite(s)
                or not (flags[i] and s > 0 if flags is not None else .5 <= s <= 1)
                or not isinstance(p, (list, tuple)) or len(p) != 2
                or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                       or not math.isfinite(v) or not 0 < v < 1 for v in p)):
            return None
        return [p[0]*width, p[1]*height]

    shoulders = [point(i) for i in (5, 6)]
    hips = [p for i in (11, 12) if (p := point(i)) is not None]
    face = [p for i in range(5) if (p := point(i)) is not None]
    if any(p is None for p in shoulders) or not hips or len(face) < 2:
        return None
    mean = lambda points: [sum(p[j] for p in points)/len(points) for j in (0, 1)]
    neck, hip = mean(shoulders), mean(hips)
    up = [neck[j]-hip[j] for j in (0, 1)]
    torso = math.hypot(*up)
    if torso < 4 or math.dist(*shoulders) > torso*1.5:
        return None
    # Duplicated placeholders and scattered face predictions are not evidence.
    spread = max(math.dist(a, b) for a in face for b in face)
    if not .025*torso <= spread <= .8*torso:
        return None
    def median(values):
        values = sorted(values)
        n = len(values)
        return (values[(n-1)//2]+values[n//2])/2
    face_center = [median([p[j] for p in face]) for j in (0, 1)]
    axis = [face_center[j]-neck[j] for j in (0, 1)]
    distance = math.hypot(*axis)
    if not .15*torso <= distance <= 1.05*torso or sum(axis[j]*up[j] for j in (0, 1)) < -.15*distance*torso:
        return None
    u = [v/distance for v in axis]
    center = [face_center[j]+u[j]*torso*.04 for j in (0, 1)]
    rx = ry = .22*torso
    outline = [[(center[0]+rx*math.cos(t)*(-u[1])+ry*math.sin(t)*u[0])/width,
                (center[1]+rx*math.cos(t)*u[0]+ry*math.sin(t)*u[1])/height]
               for t in (i*math.tau/40 for i in range(40))]
    return dict(center=[center[0]/width, center[1]/height],
                neck=[neck[0]/width, neck[1]/height], outline=outline)


def project_head(geometry, project, pixel_ratio=1):
    """Apply the caller's image transform, then a capped display-only minimum."""
    if not geometry:
        return None
    center, neck = project(geometry['center']), project(geometry['neck'])
    outline = [project(p) for p in geometry['outline']]
    if center is None or neck is None or any(p is None for p in outline):
        return None
    radius = sum(math.dist(center, p) for p in outline)/len(outline)
    if radius <= 0 or not math.isfinite(radius):
        return None
    factor = max(1., min(1.6, 7/max(.01, pixel_ratio)/radius))
    # The artwork stays circular after wall perspective and pane transforms.
    radius *= factor
    outline = [[center[0]+radius*math.cos(i*math.tau/40),
                center[1]+radius*math.sin(i*math.tau/40)] for i in range(40)]
    # Intersect the neck ray with the circle; never draw a line through its face.
    dx, dy = neck[0]-center[0], neck[1]-center[1]
    direction = math.atan2(dy, dx)
    edge = min(outline, key=lambda p: abs(math.atan2(math.sin(math.atan2(p[1]-center[1], p[0]-center[0])-direction),
                                                       math.cos(math.atan2(p[1]-center[1], p[0]-center[0])-direction))))
    return dict(outline=outline, neck=[edge, neck] if math.dist(center, neck) > math.dist(center, edge) else [])


def draw_head(image, sample, width, height, project):
    """Paint only to the supplied canvas. Original samples remain untouched."""
    import cv2
    import numpy as np
    art = project_head(head_geometry(sample, width, height), project)
    if not art:
        return
    poly = np.rint(art['outline']).astype(np.int32)
    # Limit blending to the head region and keep image detail visible.
    x, y, w, h = cv2.boundingRect(poly)
    left, top = max(0, x-4), max(0, y-4)
    right, bottom = min(image.shape[1], x+w+4), min(image.shape[0], y+h+4)
    if left >= right or top >= bottom:
        return
    crop = image[top:bottom, left:right]
    layer = crop.copy()
    local = poly-[left, top]
    cv2.fillPoly(layer, [local], (202,233,241), cv2.LINE_AA)
    cv2.addWeighted(layer, .08, crop, .92, 0, dst=crop)
    for color, stroke in (((24,29,28), 4), ((202,233,241), 2)):
        if art['neck']:
            a, b = np.rint(art['neck']).astype(np.int32)
            cv2.line(image, tuple(a), tuple(b), color, stroke, cv2.LINE_AA)
        cv2.polylines(image, [poly], True, color, stroke, cv2.LINE_AA)
