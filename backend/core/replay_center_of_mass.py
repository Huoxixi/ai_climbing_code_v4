"""Projected whole-body mass estimate; no depth or force measurement.

Mass fractions and limb COM ratios: de Leva (1996), sex-table mean.
COCO lacks anatomical head/hand/foot endpoints: visible head landmarks,
wrists and ankles are explicit proxies, never substituted for missing limbs.
"""
import math

VERSION = 'projected-segment-mass-mean-v1'
PARAMETERS = {'head': (.0681, None), 'trunk': (.43015, .5051),
              'upper_arm': (.0263, .5763), 'forearm': (.015, .45665),
              'hand': (.00585, None), 'thigh': (.1447, .38535),
              'shank': (.0457, .44375), 'foot': (.0133, None)}
SOURCE = 'https://doi.org/10.1016/0021-9290(95)00178-6'


def estimate_center_of_mass(sample):
    if not sample or sample.get('observed') is False:
        return None
    points, scores = sample.get('kpts_xy') or [], sample.get('kpts_score') or []
    flags=sample.get('joint_eligibility')
    if flags is not None and (not isinstance(flags,list) or len(flags)!=17 or not all(isinstance(v,bool) for v in flags)):
        return None
    def valid(i):
        try:
            x, y = points[i]
            score = scores[i]
            return (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                        for v in (x, y, score))
                    and (flags[i] and score>0 if flags is not None else .5 <= score <= 1)
                    and 0 < x < 1 and 0 < y < 1)
        except (IndexError, TypeError, ValueError):
            return False
    if not all(valid(i) for i in range(5, 17)):
        return None
    head = [i for i in (0, 3, 4) if valid(i)]
    if not head:
        return None
    mean = lambda indices: [sum(points[i][axis] for i in indices) / len(indices) for axis in (0, 1)]
    blend = lambda a, b, ratio: [a[axis] + ratio * (b[axis]-a[axis]) for axis in (0, 1)]
    segments = [('head', mean(head)), ('trunk', blend(mean([5,6]), mean([11,12]), PARAMETERS['trunk'][1]))]
    for shoulder, elbow, wrist, hip, knee, ankle in ((5,7,9,11,13,15), (6,8,10,12,14,16)):
        for name, a, b in (('upper_arm',shoulder,elbow), ('forearm',elbow,wrist),
                           ('thigh',hip,knee), ('shank',knee,ankle)):
            segments.append((name, blend(points[a], points[b], PARAMETERS[name][1])))
        segments.extend([('hand', points[wrist]), ('foot', points[ankle])])
    total = sum(PARAMETERS[name][0] for name, _ in segments)
    return {'xy':[sum(PARAMETERS[name][0]*xy[axis] for name, xy in segments)/total for axis in (0,1)],
            'joints': head + list(range(5,17)), 'version':VERSION, 'status':'estimated',
            'basis':'segment_mass_weighted_2d_head_wrist_ankle_proxies', 'mass_coverage':1.}


def center_of_mass_point(sample):
    estimate = estimate_center_of_mass(sample)
    return estimate['xy'] if estimate else None
