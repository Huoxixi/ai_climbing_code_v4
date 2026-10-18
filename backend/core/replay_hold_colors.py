"""Video-only colour regions. Route targets never enter colour observations."""
from __future__ import annotations

import cv2
import numpy as np

from core.photo_route_colors import CHROMATIC_COLOR_NAMES, TWELVE_COLOR_VERSION, _chromatic_color_index, classify_mask_color

REPLAY_COLOUR_VERSION = 'replay-material-distribution-v6'


def colour_region(mask, *, point=None):
    """Keep the clicked component or the component represented by the native edge."""
    binary = (np.asarray(mask) > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return binary, binary.astype(bool), {'reason': 'empty_mask', 'pixels': 0}
    if point is not None:
        px, py = point
        label = int(labels[py, px])
        if label == 0:
            return np.zeros_like(binary), np.zeros_like(binary, dtype=bool), {'reason': 'click_outside_mask', 'pixels': 0}
    else:
        # Largest native contour, not a union of disconnected islands.
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        px, py = contour[0, 0]
        label = int(labels[py, px])
    component = (labels == label).astype(np.uint8)
    # Padding supplies a real exterior even when a tiny mask fills the image.
    distances = cv2.distanceTransform(np.pad(component, 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    interior = distances > max(1., float(distances.max()) * .18)
    fallback = bool(np.count_nonzero(interior) < 12)
    if fallback:
        interior = component.astype(bool)
    info = {'pixels': int(component.sum()), 'interior_pixels': int(interior.sum()),
            'component_fraction': round(float(component.sum()) / max(1, int(binary.sum())), 4),
            'interior_fallback': fallback, 'reason': None}
    if point is not None:
        info['click_depth'] = float(distances[point[1], point[0]])
    return component, interior, info


def region_sample_distance(image, interior, rgb):
    pixels = image[interior]
    if len(pixels) < 3:
        return None
    lab = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB)[:, 0]
    target = cv2.cvtColor(np.asarray(rgb, np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0]
    return float(np.linalg.norm(np.median(lab, axis=0) - target.astype(float)))


def sample_clicked_hold(image, masks, point):
    candidates = []
    for index, mask in enumerate(masks):
        if not mask[point[1], point[0]]:
            continue
        component, interior, info = colour_region(mask, point=point)
        if info['interior_pixels'] < 3:
            continue
        rgb = np.median(image[interior][:, ::-1], axis=0).astype(int).tolist()
        candidates.append((info['click_depth'], info['component_fraction'], index, component, interior, rgb, info))
    if not candidates:
        raise ValueError('所点位置未落在清晰岩点内，请选择清晰且未被遮挡的岩点')
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = candidates[0]
    # Similar geometric support with conflicting colours is unresolved ownership.
    for other in candidates[1:]:
        if other[0] >= best[0] * .8 and region_sample_distance(image, other[4], best[5]) > 20:
            raise ValueError('此处岩点重叠，无法确定取色对象，请选择岩点内部清晰位置')
    return best[3], best[5], {**best[6], 'mask_index': best[2], 'overlapping_masks': len(candidates),
                            'version': REPLAY_COLOUR_VERSION}


def _observe_region_colour(image, mask):
    component, interior, info = colour_region(mask)
    if info['interior_pixels'] < 3:
        return '待确认', interior, {**info, 'version': REPLAY_COLOUR_VERSION, 'reason': 'insufficient_colour_pixels'}
    pixels = image[interior].reshape(-1, 1, 3)
    hsv = cv2.cvtColor(pixels, cv2.COLOR_BGR2HSV)[:, 0]
    lab = cv2.cvtColor(pixels, cv2.COLOR_BGR2LAB)[:, 0].astype(float)
    chroma = np.linalg.norm(lab[:, 1:] - 128., axis=1)
    # Low light alone is insufficient: genuinely chromatic dark blue/green/brown
    # must retain their hue. Low-chroma warm reflections can still belong to black.
    black = (hsv[:, 2] < 70) & (chroma < 16)
    white = (hsv[:, 2] > 185) & (hsv[:, 1] < 38)
    grey = (hsv[:, 2] >= 70) & (hsv[:, 2] <= 185) & (hsv[:, 1] < 38)
    proportions = {name: float(np.mean(values)) for name, values in
                   [('黑色', black), ('白色', white), ('灰色', grey)]}
    hue_summary = {}
    if proportions['黑色'] >= .55:
        name = '黑色'
        fraction = proportions[name]
    elif max(proportions['白色'], proportions['灰色']) >= .72:
        name = max(('白色', '灰色'), key=proportions.get)
        fraction = proportions[name]
    else:
        chromatic = (hsv[:, 1] >= 38) & (hsv[:, 2] >= 45) & (chroma >= 16)
        chromatic_fraction = float(np.mean(chromatic))
        name, fraction = '待确认', None
        if chromatic_fraction >= .25:
            coloured = hsv[chromatic]
            weights = chroma[chromatic]
            counts = np.bincount(coloured[:, 0], weights=weights, minlength=180)
            # A circular hue distribution keeps shadows within one colour body;
            # value is evaluated after hue, rather than splitting yellow pixels
            # into yellow/brown votes solely because of a shadow.
            smooth = sum(np.roll(counts, shift) * np.exp(-shift * shift / 8.)
                         for shift in range(-6, 7))
            hue = int(smooth.argmax())
            offsets = np.abs(coloured[:, 0].astype(float) - hue)
            concentrated = np.minimum(offsets, 180-offsets) <= 8
            fraction = float(weights[concentrated].sum() / weights.sum())
            boundaries = np.array([8,20,38,78,100,125,145,172])
            margin = float(np.min(np.abs(boundaries-hue)))
            hue_summary = {'hue_peak': hue, 'boundary_margin': margin,
                           'chromatic_fraction': chromatic_fraction,
                           'hue_concentration': fraction}
            if fraction >= .72 and margin >= 2:
                sat = int(np.median(coloured[concentrated, 1]))
                value = int(np.percentile(coloured[concentrated, 2], 75))
                name = CHROMATIC_COLOR_NAMES[_chromatic_color_index(hue, sat, value, candidate=True)]
            elif fraction >= .72:
                # At a palette boundary require the independent pixel-vote
                # observation; a histogram peak alone can flip orange metal
                # to yellow. Preserve confident small cyan bodies as well.
                name = classify_mask_color(image, component, version=TWELVE_COLOR_VERSION)
                hue_summary['boundary_pixel_vote'] = name
    prior_name=name
    resolution=None
    # A coherent, strongly chromatic warm body straddling the orange/yellow
    # vote boundary is distinct from weakly coloured metal. Keep that measured
    # body observation; the sample identity gate remains separate.
    if name=='待确认' and 20<=hue_summary.get('hue_peak',-1)<=21 \
            and hue_summary.get('hue_concentration',0)>=.9 \
            and hue_summary.get('chromatic_fraction',0)>=.65 \
            and float(np.median(hsv[:,1]))>=100:
        name='黄色';resolution='continuous_warm_body'
    if name=='待确认' and proportions['黑色']>=.35 \
            and proportions['黑色']+proportions['灰色']>=.75 \
            and proportions['白色']<=.1 and float(np.median(hsv[:,2]))<100:
        name='黑色';resolution='mixed_dark_neutral_body'
    evidence = {**info, **hue_summary, 'version': REPLAY_COLOUR_VERSION, 'neutral_fractions': proportions,
                'legacy_group':name,'lab_median':np.median(lab,axis=0).tolist(),
                'value_percentiles':np.percentile(hsv[:,2],[25,50,75]).tolist(),
                'saturation_median':float(np.median(hsv[:,1])),
                'body_fraction': fraction, 'reason': 'ambiguous_body_colour' if name == '待确认' else None}
    if resolution:evidence.update(prior_colour_group=prior_name,body_resolution=resolution)
    return name, interior, evidence


def observe_hold_colour(image, mask):
    """Equivalent body observations in a small ROI; return source-size interior."""
    binary=np.asarray(mask)>0
    ys,xs=np.where(binary)
    if not len(xs):return _observe_region_colour(image,mask)
    x,y=max(0,int(xs.min())-2),max(0,int(ys.min())-2)
    x2,y2=min(binary.shape[1],int(xs.max())+3),min(binary.shape[0],int(ys.max())+3)
    name,local,evidence=_observe_region_colour(image[y:y2,x:x2],mask[y:y2,x:x2])
    interior=np.zeros(binary.shape,dtype=bool);interior[y:y2,x:x2]=local
    return name,interior,evidence
