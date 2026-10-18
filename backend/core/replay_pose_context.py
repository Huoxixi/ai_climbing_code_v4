"""Offline crop-retry candidate. Temporal context locates a crop, not a joint.

No smoothing, left/right relabelling, hold snapping or generated coordinates.
Only a new inference on the same native image may propose revised locations.
"""
import numpy as np

VERSION='same-frame-two-context-consensus-v2'
ENDPOINTS=(9,10,15,16)


def _pixels(points,scores,size):
    xy=np.asarray(points,float)
    score=np.asarray(scores,float)
    if xy.shape!=(17,2) or score.shape!=(17,) or not np.isfinite(xy).all() or not np.isfinite(score).all():
        return None
    if np.any(score[[5,6,11,12,*ENDPOINTS]]<.5):
        return None
    return xy*np.asarray(size)


def context_proposal(previous,current_points,current_scores,size,dt):
    if not previous or not 0<dt<=.25:
        return None
    old=_pixels(previous['kpts_xy'],previous['kpts_score'],size)
    new=_pixels(current_points,current_scores,size)
    if old is None or new is None:
        return None
    span=old.max(axis=0)-old.min(axis=0)
    scale=float(max(span))
    if scale<32:
        return None
    def conflicts(points):
        return [j for j in ENDPOINTS if np.linalg.norm(points[j]-old[j])>=.5*scale
                and min(np.linalg.norm(points[j]-old[k]) for k in ENDPOINTS
                        if (k in (9,10))!=(j in (9,10)))<=.2*scale]
    suspect=conflicts(new)
    if not suspect:
        return None
    margin=max(16.,scale*.1)
    box=np.r_[np.maximum(old.min(axis=0)-margin,0),np.minimum(old.max(axis=0)+margin,size)]
    return {'box':box,'suspect_joints':suspect,'scale':scale,'previous':old,
            'current':new,'conflicts':conflicts}


def supports_retry(proposal,points,scores,size):
    candidate=_pixels(points,scores,size)
    if candidate is None or proposal['conflicts'](candidate):
        return False
    scale=proposal['scale']
    # Re-inference must remain anchored to locations also supported by the raw
    # frame inference, and cannot drag the torso back through a genuine dyno.
    if any(np.linalg.norm(candidate[j]-proposal['previous'][j])>.15*scale for j in (5,6,11,12)):
        return False
    for j in ENDPOINTS:
        references=ENDPOINTS if j in proposal['suspect_joints'] else (j,)
        if min(np.linalg.norm(candidate[j]-proposal['current'][k]) for k in references)>.15*scale:
            return False
    return True


def consensus_retry(proposal, candidates, current_points, size):
    """Two independent same-image crops support locations, not old endpoints.

    Temporal conflicts trigger scrutiny only. High steps and fast hands may
    remain far from the preceding frame if both crops agree on the new chain.
    """
    if len(candidates) != 2:
        return False
    bodies = [_pixels(points, scores, size) for points, scores in candidates]
    if any(body is None for body in bodies):
        return False
    scale = proposal['scale']
    for body in bodies:
        torso = np.linalg.norm(body[[5,6]].mean(axis=0)-body[[11,12]].mean(axis=0))
        if torso < 8:
            return False
        for a,b,c in ((5,7,9),(6,8,10),(11,13,15),(12,14,16)):
            lengths = [np.linalg.norm(body[a]-body[b]),np.linalg.norm(body[b]-body[c])]
            if min(lengths) < 2 or max(lengths) > 3*torso:
                return False
    checked = [5,6,11,12,*ENDPOINTS]
    return bool(np.all(np.linalg.norm(bodies[0][checked]-bodies[1][checked], axis=1) <= .12*scale))


def expanded_box_proposal(previous, points, scores, size, dt, detected_box):
    if not previous or not 0 < dt <= .25:
        return None
    old = _pixels(previous['kpts_xy'], previous['kpts_score'], size)
    new = _pixels(points, scores, size)
    if old is None or new is None:
        return None
    extent = old.max(axis=0)-old.min(axis=0)
    scale = float(max(extent))
    box_extent = np.asarray(detected_box)[2:]-np.asarray(detected_box)[:2]
    old_box = previous.get('box_xyxy_px')
    if old_box is None:
        return None
    old_extent = np.asarray(old_box)[2:]-np.asarray(old_box)[:2]
    if np.prod(box_extent) <= 1.8*np.prod(np.maximum(old_extent,1)):
        return None
    if scale < 32 or np.prod(box_extent) <= 2.5*np.prod(np.maximum(extent,1)):
        return None
    context = np.vstack((old,new[[5,6,11,12]]))
    margin = max(16.,scale*.1)
    box = np.r_[np.maximum(context.min(axis=0)-margin,0),np.minimum(context.max(axis=0)+margin,size)]
    return {'box':box,'scale':scale,'suspect_joints':list(ENDPOINTS),'trigger':'expanded_person_box'}
