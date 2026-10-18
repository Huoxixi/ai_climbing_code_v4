"""Video-only sample, material and native boundary evidence.

Measurements are compatibility statistics, not calibrated probabilities. No
video/candidate IDs, manual labels or reference annotations enter these rules.
"""
from __future__ import annotations

import cv2
import numpy as np
import copy

COLOUR_SUPPORT_VERSION = 'replay-connected-sample-support-v1'
MATERIAL_VERSION = 'replay-material-observation-v1'
SAMPLE_IDENTITY_VERSION = 'unresolved-continuous-sample-identity-v1'


def material_observation(evidence, rgb=None):
    if 'lab_median' not in evidence:
        return None
    name=evidence['legacy_group']
    h=evidence.get('hue_peak')
    supports=[name] if name!='待确认' else []
    state='legacy_confident' if supports else 'unresolved_distribution'
    concentrated=evidence.get('hue_concentration',0)>=.72
    chromatic=evidence.get('chromatic_fraction',0)>=.25
    if h is not None and concentrated and chromatic and abs(h-78)<=2:
        supports=['绿色','青色'];state='palette_boundary'
    if h is not None and concentrated and chromatic and 20<=h<38:
        if name in ('黄色','棕色'):supports=['黄色','棕色']
        if name=='棕色':state='warm_low_value_material_unresolved'
    sample_hue=None
    if rgb is not None:
        sample_hue=int(cv2.cvtColor(np.uint8([[rgb]]),cv2.COLOR_RGB2HSV)[0,0,0])
    delta=min(abs(h-sample_hue),180-abs(h-sample_hue)) if h is not None and sample_hue is not None else None
    return {'version':MATERIAL_VERSION,'legacy_group':name,'supports':supports,'state':state,
        'effective_pixels':evidence['interior_pixels'],'lab_median':evidence['lab_median'],
        'value_percentiles':evidence['value_percentiles'],'saturation_median':evidence['saturation_median'],
        'hue_peak':h,'sample_hue':sample_hue,'sample_hue_difference':delta,
        'compatibility_is_probability':False,
        'continuous_sample_identity': continuous_sample_identity(evidence, rgb)}


def continuous_sample_identity(evidence, rgb):
    """Describe unresolved surface compatibility without changing its colour label.

    A palette-boundary body needs coherent hue/chroma; a white body needs a
    bright neutral component despite shadows. Distance alone is not identity.
    This observation is not an admission: registered native shape support and
    connected sample pixels are checked separately by the cluster resolver.
    """
    result = {'version': SAMPLE_IDENTITY_VERSION, 'group': None}
    if rgb is None or evidence.get('legacy_group') != '待确认':
        return result
    from .photo_route_colors import lab_color_name
    sample = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(float)
    hsv = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HSV)[0, 0].astype(float)
    family = lab_color_name(sample.astype(np.uint8), twelve_colors=True)
    body = np.asarray(evidence.get('lab_median'), float)
    if body.shape != (3,) or not np.isfinite(body).all():
        return result
    chroma = float(np.linalg.norm(body[1:] - 128.))
    chroma_delta = float(np.linalg.norm(body[1:] - sample[1:]))
    hue = evidence.get('hue_peak')
    delta = (min(abs(hue-hsv[0]), 180-abs(hue-hsv[0]))
             if hue is not None else None)
    ratio = chroma / max(1., float(np.linalg.norm(sample[1:] - 128.)))
    if family == '白色':
        neutral = evidence.get('neutral_fractions') or {}
        values = evidence.get('value_percentiles') or [0., 0., 0.]
        compatible = (neutral.get('白色', 0.) >= .25 and chroma <= 16.
                      and chroma_delta <= 12. and evidence.get('saturation_median', 255.) <= 55.
                      and abs(body[0]-sample[0]) <= 30. and values[2] > 185.)
        reason = 'bright_neutral_body_with_shadow'
    elif family in {'红色','橙色','黄色','绿色','青色','蓝色','紫色','粉色','棕色'}:
        compatible = (hsv[1] >= 80. and delta is not None and delta <= 8.
                      and evidence.get('hue_concentration', 0.) >= .9
                      and evidence.get('chromatic_fraction', 0.) >= .65
                      and evidence.get('saturation_median', 0.) >= 80.
                      and .6 <= ratio <= 1.5)
        reason = 'coherent_chromatic_body_near_sample'
    else:
        compatible = False
        reason = 'unsupported_sample_family'
    result.update(group=family if compatible else None, reason=reason,
                  hue_difference=delta, chroma=chroma, chroma_difference=chroma_delta,
                  chroma_ratio=ratio)
    return result


def resolve_unresolved_sample_cluster(hold, members, sample_group, overlap, matches):
    """Resolve only previously unqualified native clusters, preserving accepted ones.

    Two real frames must independently establish sample identity and three
    must agree on the complete native contour. Original raw labels, distances,
    and contours remain evidence; no manual candidate identities are accepted.
    """
    if matches(hold, sample_group) or hold.get('native_class', 0) != 0:
        return hold
    from .replay_hold_fusion import valid_native_contour
    eligible = []
    for original in members:
        identity = (original.get('material_observation') or {}).get('continuous_sample_identity') or {}
        support = original.get('colour_support') or {}
        if (identity.get('group') != sample_group
                or not (original.get('material_quality') or {}).get('eligible', True)
                or original.get('contour_complete') is not True
                or original.get('contour_source') != 'climbing_model_native_mask'
                or not valid_native_contour(original)
                or support.get('metric_qualified') is not True
                or support.get('within60_fraction', 0.) < .5
                or support.get('largest_fraction', 0.) < .5):
            continue
        polygon = np.asarray(original['polygon'], np.float32)
        convex_area = cv2.contourArea(cv2.convexHull(polygon))
        # An ambiguous printed outline is not a compact material body. This
        # conservative requirement applies only to the new fallback; ordinary
        # qualified concave/thin holds keep their existing selection path.
        solidity = cv2.contourArea(polygon) / max(convex_area, 1e-12)
        if solidity < .8:
            continue
        if not isinstance(original.get('source_frame'), int) or isinstance(original['source_frame'], bool):
            continue
        d = copy.deepcopy(original)
        d['observed_color_group'] = original['color_group']
        d['color_group'] = sample_group
        d['route_candidate'] = True
        d['colour_support'].update(qualified=True, class_matches=True,
                                   unresolved_sample_identity={**identity, 'native_solidity': solidity})
        eligible.append(d)
    if len({d['source_frame'] for d in eligible}) < 2:
        return hold
    viable = []
    for d in eligible:
        shape_frames = {e.get('source_frame') for e in members
                        if e.get('contour_complete') is True
                        and e.get('contour_source') == 'climbing_model_native_mask'
                        and (e.get('material_quality') or {}).get('eligible', True)
                        and isinstance(e.get('source_frame'), int)
                        and not isinstance(e['source_frame'], bool)
                        and overlap(d, e)[0] >= .85}
        colour_frames = {e['source_frame'] for e in eligible if overlap(d, e)[0] >= .85}
        if len(shape_frames) >= 3 and len(colour_frames) >= 2:
            viable.append((len(shape_frames), len(colour_frames), d['score'], d, shape_frames))
    if not viable:
        return hold
    _, _, _, chosen, shape_frames = max(viable, key=lambda t: t[:3])
    from .replay_hold_fusion import native_contour_support, polygon_bbox
    result = {**hold, **chosen}
    # Keep cluster identity/references, replacing only the representative with
    # a real independently qualified observation, never a merged drawing.
    for key in ('candidate_id','score','appearances','support_frames','observation_ids','native_observations',
                'material_identity','merge_relations','color_votes'):
        if key in hold: result[key] = copy.deepcopy(hold[key])
    result['bbox'] = polygon_bbox(result['polygon'])
    result['contour_evidence'] = native_contour_support(eligible, result, sample_group=sample_group)
    result['sample_identity_resolution'] = {
        'version': SAMPLE_IDENTITY_VERSION,
        'colour_frames': sorted({d['source_frame'] for d in eligible if overlap(d, chosen)[0] >= .85}),
        'shape_frames': sorted(shape_frames), 'raw_labels_preserved': True,
        'prior_qualified_representative_preserved': False,
    }
    result['route_candidate_reason'] = 'independent_native_continuous_sample_identity'
    return result


def sample_compatible_group(name, material, target):
    if material and material['state']=='palette_boundary' and target in material['supports'] \
            and material['sample_hue_difference'] is not None and material['sample_hue_difference']<=8:
        return target
    return name


def colour_support(image, interior, rgb, group, target, raw_distance, *, colour_evidence=None):
    count=int(interior.sum())
    result={'version':COLOUR_SUPPORT_VERSION,'pixel_limit':60.,'minimum_fraction':.25,
        'minimum_connected_fraction':.20,'pixels':count,'median_distance':raw_distance,
        'within60_fraction':0.,'largest_fraction':0.,'matching_region_distance':None,
        'qualified':False,'class_matches':group==target,'source':'insufficient_pixels'}
    if count<3:return result
    median_pass=raw_distance is not None and np.isfinite(raw_distance) and 0<=raw_distance<=60.
    ys,xs=np.where(interior)
    x,y,x2,y2=int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1
    inside=interior[y:y2,x:x2]
    lab=cv2.cvtColor(image[y:y2,x:x2],cv2.COLOR_BGR2LAB).astype(float)
    sample=cv2.cvtColor(np.uint8([[rgb]]),cv2.COLOR_RGB2LAB)[0,0].astype(float)
    matched=inside&(np.linalg.norm(lab-sample,axis=2)<=60.)
    n,labels,stats,_=cv2.connectedComponentsWithStats(matched.astype(np.uint8),8)
    label=int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))+1 if n>1 else 0
    largest=labels==label if label else np.zeros_like(inside)
    area=int(largest.sum())
    result.update(within60_fraction=float(matched.sum()/count),largest_fraction=area/count,
        matching_region_distance=float(np.linalg.norm(np.median(lab[largest],axis=0)-sample)) if area>=3 else None)
    region_pass=result['within60_fraction']>=.25 and result['largest_fraction']>=.20 and area>=3
    identity=True
    if group==target=='黄色' and colour_evidence:
        hue=colour_evidence.get('hue_peak')
        sample_hue=int(cv2.cvtColor(np.uint8([[rgb]]),cv2.COLOR_RGB2HSV)[0,0,0])
        delta=min(abs(hue-sample_hue),180-abs(hue-sample_hue)) if hue is not None else None
        body=np.asarray(colour_evidence['lab_median'],float)
        ratio=float(np.linalg.norm(body[1:]-128)/max(1,np.linalg.norm(sample[1:]-128)))
        reasons=[]
        if delta is not None and delta>8:reasons.append('sample_hue_incompatible')
        if ratio<1/3:reasons.append('weak_sample_chroma')
        identity=not reasons
        result.update(sample_hue_difference=delta,sample_chroma_ratio=ratio,
            identity_compatible=identity,identity_reasons=reasons)
    result.update(distance_metric_qualified=bool(median_pass or region_pass),
        metric_qualified=bool(identity and (median_pass or region_pass)),
        qualified=bool(group==target and identity and (median_pass or region_pass)),
        source='median' if median_pass else ('connected_region' if region_pass else 'unsupported'))
    return result


def measure_material_quality(members):
    observed=[d for d in members if d.get('material_observation')]
    if len({d.get('source_frame') for d in observed})<2:
        return
    labs=np.asarray([d['material_observation']['lab_median'] for d in observed])
    areas=[cv2.contourArea(np.asarray(d['polygon'],np.float32)) for d in observed]
    centre=np.median(labs[:,1:],axis=0);median_area=float(np.median(areas))
    for d,lab,area in zip(observed,labs,areas):
        residual=float(np.linalg.norm(lab[1:]-centre));ratio=float(area/max(median_area,1e-12))
        reasons=[]
        if residual>18:reasons.append('temporal_chroma_outlier')
        if ratio<.65 or ratio>1.55:reasons.append('temporal_shape_area_outlier')
        if not d.get('contour_complete'):reasons.append('image_clipped')
        d['material_quality']={'version':'replay-target-independent-consistency-v1',
            'chroma_residual':residual,'area_ratio':ratio,'reasons':reasons,
            'eligible':not reasons,'occlusion_confirmed':False}
    # Stable clipped observations support only the visible partial shape.
    # They never change contour_complete or invent an off-image boundary.
    from .replay_hold_fusion import contour_overlap
    clipped=[d for d in observed if not d.get('contour_complete') and d.get('native_class')==0]
    if len({d['source_frame'] for d in clipped})<3:return
    for d in clipped:
        stable=[e for e in clipped if contour_overlap(d,e)[0]>=.9]
        if len({e['source_frame'] for e in stable})>=3 \
                and (d.get('boundary_quality') or {}).get('edge_fraction',0)>=.65 \
                and d['material_quality'].get('reasons')==['image_clipped']:
            d['visible_partial_support']=True
            d['material_quality']['eligible']=True


def warm_material_supported(reliable):
    if not reliable or any(not d.get('material_observation') for d in reliable):return False
    anchors={d.get('source_frame') for d in reliable if d.get('color_group')=='黄色'
        and isinstance(d.get('source_frame'),int) and not isinstance(d['source_frame'],bool)}
    peaks=[d['material_observation'].get('hue_peak') for d in reliable]
    return len(anchors)>=2 and all(h is not None and 20<=h<38 for h in peaks) \
        and max(peaks)-min(peaks)<=4 \
        and all('黄色' in d['material_observation']['supports'] for d in reliable)


def boundary_quality(image, mask):
    binary=(mask>0).astype(np.uint8);ys,xs=np.where(binary)
    if not len(xs):return {'edge_fraction':0.,'edge_mean_distance':None}
    x,y=max(0,int(xs.min())-6),max(0,int(ys.min())-6)
    x2,y2=min(mask.shape[1],int(xs.max())+7),min(mask.shape[0],int(ys.max())+7)
    grey=cv2.cvtColor(image[y:y2,x:x2],cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(grey,40,100)
    distances=cv2.distanceTransform((edges==0).astype(np.uint8),cv2.DIST_L2,5)
    local=binary[y:y2,x:x2]
    perimeter=local&~cv2.erode(local,np.ones((3,3),np.uint8)).astype(bool)
    values=distances[perimeter.astype(bool)]
    return {'edge_fraction':float(np.mean(values<=3)) if len(values) else 0.,
        'edge_mean_distance':float(np.mean(values)) if len(values) else None,'edge_tolerance_px':3.,
        'not_image_clipped':not bool(binary[0].any() or binary[-1].any() or binary[:,0].any() or binary[:,-1].any())}


def choose_native_representative(members, sample_group, matches, overlap, *, partial_boundary_members=None):
    fallback=max(members,key=lambda d:d['score'])
    eligible=[d for d in members if matches(d,sample_group) and d.get('contour_complete') is True
        and not d.get('new_body_resolution',False)
        and (d.get('material_quality') or {}).get('eligible',True)]
    if len({d.get('source_frame') for d in eligible})<2:return fallback
    # Partial native observations may support a locally visible edge, while
    # never becoming the representative or a complete colour/contour support.
    partial_boundary_members=partial_boundary_members or []
    boundary_members=eligible+partial_boundary_members
    points=np.concatenate([np.asarray(d['polygon']) for d in boundary_members])
    lo=points.min(axis=0);span=points.max(axis=0)-lo
    if np.any(span<=0):return fallback
    rasters=[];bands=[]
    for d in boundary_members:
        raster=np.zeros((514,514),np.uint8)
        cv2.fillPoly(raster,[np.rint((np.asarray(d['polygon'])-lo)/span*511+1).astype(np.int32)],1)
        edge=raster&~cv2.erode(raster,np.ones((3,3),np.uint8)).astype(bool)
        rasters.append(raster);bands.append(cv2.dilate(edge.astype(np.uint8),np.ones((11,11),np.uint8)))
    scored=[]
    for i,d in enumerate(eligible):
        edge=rasters[i]&~cv2.erode(rasters[i],np.ones((3,3),np.uint8)).astype(bool)
        others=[bands[j] for j,e in enumerate(boundary_members) if e['source_frame']!=d['source_frame']]
        supported=np.maximum.reduce(others)>0
        agreement=float(supported[edge.astype(bool)].mean())
        image_support=(d.get('boundary_quality') or {}).get('edge_fraction',0.)
        ious=[overlap(d,e)[0] for e in boundary_members if e['source_frame']!=d['source_frame']]
        median_iou=float(np.median(ious));q=.5*agreement+.25*image_support+.25*median_iou
        detail={'version':'replay-native-boundary-selection-v1','boundary_agreement':agreement,
            'image_edge_support':image_support,'median_iou':median_iou,'quality':q,
            'partial_boundary_frames':sorted({d['source_frame'] for d in partial_boundary_members}),
            'partial_boundary_is_complete_contour_support':False}
        scored.append((q,d['score'],d,detail))
    _,_,chosen,detail=max(scored,key=lambda item:item[:2])
    return {**chosen,'representative_quality':detail}
