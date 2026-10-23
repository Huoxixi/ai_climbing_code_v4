"""Current-image pose observations from a fixed rotated model input.

This is an image-inference candidate, not smoothing or hold attraction. The
primary native response stays in joint_observations; selected current-image
observations have their own provenance. Experimental until local acceptance.
"""
from copy import deepcopy

import cv2
import numpy as np

VERSION='rotated-source-observation-v3'
ANGLE=15.0
# The full-body trial increased knee/ankle jumps. Only the image-localization
# branches that passed the per-component review are eligible for adoption.
JOINTS=(7,8,9,10,17,18,19,20,21,22)
CHAINS=((5,7,9),(6,8,10),(11,13,15),(12,14,16))


def observe_rotated(pose,image,box):
    """Infer all native landmarks, then undo only the input's image transform."""
    img,center,scale=pose.preprocess(image,list(box))
    rotation=cv2.getRotationMatrix2D(tuple(np.array(pose.model_input_size)/2),ANGLE,1.)
    border=tuple((-np.asarray(pose.mean)/np.asarray(pose.std)).tolist())
    rotated=cv2.warpAffine(img,rotation,tuple(pose.model_input_size),flags=cv2.INTER_LINEAR,borderValue=border)
    outputs=pose.inference(rotated)
    xy,response=pose.postprocess(outputs,center,scale)
    model_xy=(xy[0]-center+scale/2)/scale*pose.model_input_size
    restored=cv2.transform(model_xy[None].astype(np.float32),cv2.invertAffineTransform(rotation))[0]
    source_xy=restored/pose.model_input_size*scale+center-scale/2
    return source_xy,np.asarray(response[0],float),{
        'version':VERSION,'angle_degrees':ANGLE,'box_xyxy_px':list(map(float,box)),
        'source_to_model_rotation':rotation.tolist(),'source_size_wh':[image.shape[1],image.shape[0]],
        'basis':'same_source_image_model_inference_inverse_affine_not_temporal_coordinates'}


def select_observations(record,xy,response,evidence):
    """Select qualified limb predictions while retaining primary raw evidence.

    No new eligibility is granted. An invalid candidate falls back to the
    primary observation; torso, face, hands' fine landmarks and identity stay.
    """
    result=deepcopy(record)
    if not record.get('pose_evidence',{}).get('observed'):return result
    whole=result.get('wholebody') or {}
    if whole.get('schema')!='coco-wholebody-133' or whole.get('coordinates')!='source_image_normalized':return result
    xy=np.asarray(xy,float);response=np.asarray(response,float)
    if xy.shape!=(133,2) or response.shape!=(133,):raise ValueError('Expected native133 current-image predictions')
    size=np.asarray(record['pose_evidence']['source_size_wh'],float)
    primary=np.asarray(whole['kpts_xy'],float)*size
    old_scores=np.asarray(whole['kpts_score'],float)
    flags=np.asarray(whole['joint_eligibility'],bool)
    if primary.shape!=(133,2) or flags.shape!=(133,):return result
    good=flags & np.isfinite(xy).all(axis=1)&np.isfinite(response)&(response>=.5)
    good &= (xy>0).all(axis=1)&(xy<size).all(axis=1)
    selected=primary.copy();scores=old_scores.copy();chosen=[]
    for j in JOINTS:
        if good[j]:selected[j]=xy[j];scores[j]=response[j];chosen.append(j)
    torso=float(np.linalg.norm(primary[[5,6]].mean(axis=0)-primary[[11,12]].mean(axis=0)))
    if not np.isfinite(torso) or torso<1:return result
    rejected=[]
    anchor_agreement={}
    # Mixing native elbows/knees from a view that assigned the opposite torso
    # sides creates crossed chains. Retain primary limbs in that ambiguous view;
    # never swap labels or let this view redefine the clip's body identity.
    for anchors,joints,name in (((5,6),(7,8,9,10),'shoulders'),
                                ((11,12),(17,18,19,20,21,22),'hips')):
        own=float(np.linalg.norm(xy[list(anchors)]-primary[list(anchors)],axis=1).sum())
        opposite=float(np.linalg.norm(xy[list(anchors)]-primary[list(anchors[::-1])],axis=1).sum())
        margin=max(4.,.04*torso)
        supported=bool(np.all(good[list(anchors)]) and
                       np.linalg.norm(primary[anchors[0]]-primary[anchors[1]])>=margin)
        compatible=supported and not opposite+margin<own
        anchor_agreement[name]={'same_side_distance_px':own if np.isfinite(own) else None,
            'opposite_side_distance_px':opposite if np.isfinite(opposite) else None,
            'compatible_with_primary_assignment':compatible}
        if not compatible:rejected.extend(joints)
    # Reuse the existing observation contract's chain limit, without a fixed 2D
    # bone length or restricting true fast motion to the previous pose.
    for chain in CHAINS:
        lengths=np.linalg.norm(np.diff(selected[list(chain)],axis=0),axis=1)
        if np.any(lengths<=0) or np.any(lengths>3*torso):rejected.extend(chain[1:])
    for j in range(17,23):
        ankle=15 if j<20 else 16
        if np.linalg.norm(selected[j]-selected[ankle])>max(30.,.65*torso):rejected.append(j)
    for j in rejected:selected[j]=primary[j];scores[j]=old_scores[j]
    chosen=[j for j in chosen if j not in rejected]
    for j in chosen:
        point=(selected[j]/size).round(6).tolist()
        whole['kpts_xy'][j]=point;whole['kpts_score'][j]=float(scores[j])
        if j<17:result['kpts_xy'][j]=point;result['kpts_score'][j]=float(scores[j])
        if whole.get('location_support'):whole['location_support'][j]='same_source_image_rotated_model_observation'
    result['image_observation_refinement']={**evidence,'version':VERSION,'anchor_agreement':anchor_agreement,
        'selected_joints':chosen,'rejected_joints':sorted(set(rejected)),
        'knees_ankles':'primary_native_retained_rotated_branch_not_accepted',
        'primary_raw_preserved':True,
        'candidate_raw_xy_px':np.where(np.isfinite(xy),xy,0).tolist(),
        'candidate_native_response':np.where(np.isfinite(response),response,0).tolist()}
    selected_native=np.asarray(record['joint_observations']['raw_xy_px'],float).copy()
    selected_native[chosen]=xy[chosen]
    result['joint_observations']['selected_raw_xy_px']=np.where(np.isfinite(selected_native),selected_native,0).tolist()
    result['joint_observations']['selected_native_response']=scores.tolist()
    result['joint_observations']['selected_source']=[
        'same_source_image_rotated_native' if j in chosen else 'primary_native' for j in range(133)]
    result['pose_evidence']['selected_joint_source']='primary_native_or_current_image_rotated_native'
    result['pose_evidence']['body_structure_basis']='primary_native_observation'
    return result
