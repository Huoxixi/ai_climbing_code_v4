"""Simple observed foot shapes for display; never contact evidence."""
import numpy as np
from .replay_action_trajectory import registered_points
from .replay_observation_validity import joint_mask

INDICES=(15,17,19,16,20,22)
EDGES=((0,1),(0,2),(3,4),(3,5))

def registered_feet(sample,video):
    body=registered_points(sample,video)
    whole=sample.get('wholebody') or {}
    if body is None or whole.get('schema')!='coco-wholebody-133': return None
    try:
        xy=np.asarray(whole['kpts_xy'],float); scores=np.asarray(whole['kpts_score'],float)
        if xy.shape!=(133,2) or scores.shape!=(133,): return None
        selected=xy[list(INDICES)]; selected_scores=scores[list(INDICES)]
        w,h=video['width'],video['height']
        if whole.get('coordinates')=='source_image_normalized':
            matrix=np.asarray(sample['wall_reference_transform'],float)
            homogeneous=np.c_[selected*[w,h],np.ones(6)]@matrix.T
            denominator=homogeneous[:,2:]
            points=homogeneous[:,:2]/np.where(abs(denominator)>1e-6,denominator,np.nan)/[w,h]
        elif whole.get('coordinates')=='wall_reference_image_normalized': points=selected.copy()
        else: return None
        flags=whole.get('joint_eligibility')
        flags=[flags[i] for i in INDICES] if flags is not None and len(flags)==133 else flags
        valid=joint_mask(selected,points,selected_scores,flags)
        if flags is not None: selected_scores=valid.astype(float)
        for position,joint in ((0,15),(3,16)):
            points[position]=body[0][joint]; valid[position]=body[1][joint]
        return {'kpts_xy':np.where(valid[:,None],points,0).round(6).tolist(),
                'kpts_score':np.where(valid,selected_scores,0).tolist(),'basis':'model_observation_display_only'}
    except (KeyError,ValueError,TypeError,IndexError): return None

def interpolate_feet(left,right,alpha):
    if not left or not right: return None
    xy=np.asarray(left['kpts_xy'])*(1-alpha)+np.asarray(right['kpts_xy'])*alpha
    scores=np.minimum(left['kpts_score'],right['kpts_score'])
    return {'kpts_xy':np.where((scores>=.5)[:,None],xy,0).round(6).tolist(),
            'kpts_score':scores.tolist(),'basis':'display_interpolation'}
