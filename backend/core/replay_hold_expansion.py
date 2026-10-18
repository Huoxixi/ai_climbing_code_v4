"""Add independently supported native route objects without replacing accepted masks.

Route colours and model evidence are inputs; case names and scoring annotations
are never inputs. Surface appearance remains separate from material identity.
"""
from __future__ import annotations

import copy
import time
import cv2
import numpy as np

from .replay_hold_colors import observe_hold_colour
from .replay_hold_evidence import colour_support
from .replay_hold_fusion import contour_overlap, valid_native_contour

EXPANSION_VERSION = 'native-route-evidence-expansion-v1'


def _distinct_frame(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _conflicts(hold, others, limit=.35):
    # Keep every accepted contour. A new mask cannot cover or replace it.
    return any(contour_overlap(hold, other)[1] >= limit for other in others)


def _native_mask(detection, frames, outputs):
    fi = next(i for i, (fr, _) in enumerate(frames) if fr == detection['source_frame'])
    index = int(detection['observation_id'].rsplit('-', 1)[1])
    encoded = outputs[fi][0][index]
    image = frames[fi][1]
    mask = ((encoded > 0).astype(np.uint8) if encoded.shape[1] == image.shape[1]
            else np.unpackbits(encoded, axis=1, count=image.shape[1]).astype(np.uint8))
    return image, mask


def dark_material_evidence(image, mask, rgb=None):
    """Measure connected dark neutral body regions, not a brightness relabel."""
    surface, interior, evidence = observe_hold_colour(image, mask)
    result = {'version': EXPANSION_VERSION, 'surface_colour': surface,
              'qualified': False, 'dark_fraction': 0., 'connected_dark_fraction': 0.}
    if surface not in {'黑色', '灰色', '待确认'} or interior.sum() < 3:
        return result
    ys, xs = np.where(interior)
    y, y2, x, x2 = int(ys.min()), int(ys.max())+1, int(xs.min()), int(xs.max())+1
    image = image[y:y2, x:x2]
    interior = interior[y:y2, x:x2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    neutral = np.linalg.norm(lab[:, :, 1:] - 128., axis=2) < 16
    dark = interior & neutral & (hsv[:, :, 2] < 70)
    # Remove isolated pixels; preserve no fabricated geometry.
    connected = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(connected, 8)
    largest = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
    pixels = int(interior.sum())
    fractions = evidence.get('neutral_fractions') or {}
    metric = True
    if rgb is not None:
        support = colour_support(image, interior, rgb, '黑色', '黑色', None, colour_evidence=evidence)
        metric = support['metric_qualified']
        result['sample_support'] = support
    result.update(dark_fraction=float(dark.sum()/pixels), connected_dark_fraction=largest/pixels,
                  neutral_fraction=sum(fractions.get(k, 0.) for k in ('黑色', '灰色', '白色')),
                  white_fraction=fractions.get('白色', 0.),
                  value_percentiles=evidence.get('value_percentiles'), metric_qualified=metric)
    result['strong_anchor'] = bool(metric and result['neutral_fraction'] >= .85
                                   and result['white_fraction'] <= .15
                                   and result['dark_fraction'] >= .12
                                   and result['connected_dark_fraction'] >= .025)
    result['qualified'] = bool(metric and result['white_fraction'] <= .15 and (
        (result['neutral_fraction'] >= .85 and result['dark_fraction'] >= .07
         and result['connected_dark_fraction'] >= .025)
        or (result['neutral_fraction'] >= .65 and result['dark_fraction'] >= .45
            and result['connected_dark_fraction'] >= .20)))
    return result


def expand_native_evidence(*, frames, outputs, detections, existing, sample_group,
                           sample_rgb=None, trace=None, volumes=True, edges=True,
                           material=True):
    """Select additions supported by three distinct native source frames."""
    started = time.perf_counter()
    observations = []
    for rows in detections:
        for raw in rows:
            if not _distinct_frame(raw.get('source_frame')) or not valid_native_contour(raw):
                continue
            if _conflicts(raw, existing):
                continue
            d = copy.deepcopy(raw)
            d.pop('stage', None)
            category = d.get('native_class', 0)
            partial = d.get('contour_complete') is not True
            same_colour = d['color_group'] == sample_group and d.get('route_candidate') is True
            if category == 1 and same_colour and ((partial and edges) or (not partial and volumes)):
                d['expansion_channel'] = 'native_volume_visible' if partial else 'native_volume'
            elif material and sample_group == '黑色' and d['color_group'] in {'灰色', '待确认'}:
                image, mask = _native_mask(d, frames, outputs)
                measurement = dark_material_evidence(image, mask, sample_rgb)
                if not measurement['qualified'] or partial:
                    continue
                d['observed_color_group'] = d['color_group']
                d['color_group'] = '黑色'
                d['material_identity'] = measurement
                d['surface_colour_support'] = d.get('colour_support')
                d['colour_support'] = measurement.get('sample_support')
                d['route_candidate'] = True
                aspect = max(d['bbox'][2]*image.shape[1], d['bbox'][3]*image.shape[0])/max(1., min(d['bbox'][2]*image.shape[1], d['bbox'][3]*image.shape[0]))
                d['expansion_channel'] = 'weak_native' if aspect >= 2. else 'dark_material'
            elif material and sample_group == '黑色' and same_colour and category == 0 and not partial:
                image, mask = _native_mask(d, frames, outputs)
                aspect = max(d['bbox'][2]*image.shape[1], d['bbox'][3]*image.shape[0])/max(1., min(d['bbox'][2]*image.shape[1], d['bbox'][3]*image.shape[0]))
                measurement = dark_material_evidence(image, mask, sample_rgb)
                if aspect < 2. or not measurement['qualified']:
                    continue
                d['material_identity'] = measurement
                d['expansion_channel'] = 'weak_native'
            else:
                continue
            if d.get('score', 0.) < (.4 if d['expansion_channel'] == 'weak_native' else (.45 if d['expansion_channel'] == 'dark_material' else .65)):
                continue
            if (d.get('boundary_quality') or {}).get('edge_fraction', 0.) < .55:
                continue
            observations.append(d)
    # Pair by actual polygon agreement and provenance. Duplicate same-frame
    # predictions supply one observation, never independent support.
    observations.sort(key=lambda d: (-d.get('score', 0.), d['source_frame']))
    proposals = []
    for d in observations:
        channel = d['expansion_channel']
        neighbours = [e for e in observations if e['expansion_channel'] == channel
                      and contour_overlap(d, e)[0] >= (.9 if not d['contour_complete'] else .75)]
        per_frame = {}
        for e in neighbours:
            if e['source_frame'] not in per_frame:
                per_frame[e['source_frame']] = e
        supports = list(per_frame.values())
        if len(supports) < 3:
            continue
        if channel == 'dark_material':
            anchors = {e['source_frame'] for e in supports if e['material_identity'].get('strong_anchor')}
            if len(anchors) < 2 or max(e['score'] for e in supports) < .65:
                continue
        if channel == 'weak_native' and max(e['score'] for e in supports) < .65:
            continue
        h = copy.deepcopy(d)
        h['route_candidate_reason'] = h['expansion_channel']+'-independent-evidence'
        h.update(candidate_id='expanded-'+d['observation_id'], appearances=len(supports),
                 support_frames=sorted(per_frame), observation_ids=[e['observation_id'] for e in supports],
                 evidence_origin='native_route_expansion',
                 contour_evidence={'version':'native-colour-contour-support-v1',
                     'support_frames':sorted(per_frame), 'observations':[
                         {'source_frame':e['source_frame'], 'observation_id':e['observation_id'],
                          'complete':e['contour_complete'], 'colour_candidate':True,
                          'iou':contour_overlap(d,e)[0]} for e in supports]})
        if not h['contour_complete']:
            h['visible_partial_support'] = True
            h['contour_evidence'].update(visible_partial_frames=sorted(per_frame), partial_contour_complete=False)
        if h.get('material_identity'):
            h['material_identity']['source_surface_colours'] = [
                {'source_frame':e['source_frame'], 'surface_colour':e.get('observed_color_group', e['color_group'])}
                for e in supports]
            h['material_identity']['dark_anchor_frames'] = sorted(
                e['source_frame'] for e in supports if e['material_identity'].get('strong_anchor'))
        proposals.append(h)
    proposals.sort(key=lambda h: (-len(h['support_frames']), -h['score']))
    selected = []
    for h in proposals:
        if _conflicts(h, existing+selected):
            continue
        selected.append(h)
        if trace is not None:
            trace.append({**h, 'stage':'expansion_selection', 'status':'selected'})
    return selected, {'version': EXPANSION_VERSION, 'added':len(selected),
                      'channels':dict((channel, sum(h['expansion_channel']==channel for h in selected))
                                      for channel in {h['expansion_channel'] for h in selected}),
                      'seconds':time.perf_counter()-started, 'accepted_contours_preserved':True}
