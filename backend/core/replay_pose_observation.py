"""Versioned observation evidence, distinct from a model's uncalibrated response.

Eligibility flags represent candidate admissibility, never probability. Raw
responses, structure diagnostics and unknown visibility/side certainty survive.
This supplies observable candidates; accuracy still requires external labels.
"""
import numpy as np

VERSION = 'source-pose-observation-v1'
CHAINS = ((5,7,9),(6,8,10),(11,13,15),(12,14,16))


def observation_record(xy, raw, *, frame_id, source_frame_id, track_id, size, box,
                       model, model_evidence, selection, minimum_response=0.):
    xy, raw = np.asarray(xy,float), np.asarray(raw,float)
    if xy.shape not in ((17,2),(133,2)) or raw.shape != (len(xy),):
        raise RuntimeError('Expected native COCO body17 or wholebody133 observation')
    count=len(xy)
    width,height = size
    finite = np.isfinite(xy).all(axis=1) & np.isfinite(raw)
    inside = (xy>0).all(axis=1) & (xy<[width,height]).all(axis=1)
    candidate = finite & inside & (raw>0) & (raw>=minimum_response)
    reasons = ['nonfinite' if not finite[i] else 'outside_source' if not inside[i]
               else 'no_positive_response' if raw[i]<=0 else 'native_response_ineligible' if raw[i]<minimum_response
               else 'candidate_unverified' for i in range(count)]
    structure = {}
    torso = np.linalg.norm(xy[[5,6]].mean(axis=0)-xy[[11,12]].mean(axis=0))
    for a,b,c in CHAINS:
        lengths = np.linalg.norm(np.diff(xy[[a,b,c]],axis=0),axis=1)
        measured = np.isfinite(lengths).all() and np.isfinite(torso) and torso>0
        admissible = measured and np.all(lengths>0) and np.all(lengths<=3*torso)
        structure[str(c)] = {'lengths_px':np.nan_to_num(lengths).tolist(),
                            'torso_length_px':float(torso) if np.isfinite(torso) else None,
                            'status':'admissible_not_verified' if admissible else 'structural_conflict'}
        if not admissible:
            candidate[[b,c]] = False
            reasons[b] = reasons[c] = 'structural_conflict'
    # These are separate fields on purpose: heatmap amplitudes do not share the
    # historical RTMW score scale. No guessed probability mapping or per-video
    # confidence threshold is introduced to get a specific frame accepted.
    eligibility = candidate.tolist()
    responses = np.where(np.isfinite(raw),raw,0.).tolist()
    points = np.where(np.isfinite(xy),xy,0)/[width,height]
    raw_xy = [[float(v) if np.isfinite(v) else None for v in point] for point in xy]
    evidence = {'version':VERSION,'source_frame_id':source_frame_id,'track_id':track_id,
                'provider':'local-clip-pose','model':model,'source_size_wh':list(size),
                'person_box_xyxy_px':list(box),'observation_kind':'model_observation',
                'observed':True,'selection':'offline_clip_target','selection_evidence':selection,
                'joint_status_basis':'source_finite_positive_response_and_body_chain_candidate_not_ground_truth',
                'score_transform':'raw_response_preserved_separate_boolean_eligibility',
                'location_uncertainty':'not_calibrated','visibility':'not_verified',
                'native_response_minimum':minimum_response,
                'response_gate_semantics':'legacy_provider_admissibility_not_correctness_calibration' if minimum_response else 'positive_model_candidate_not_correctness_calibration',
                'side_status':'model_assignment_not_verified','body_structure':structure,
                'model_input':model_evidence}
    record = {'frame_id':frame_id,'source_frame_id':source_frame_id,'track_id':track_id,
            'kpts_xy':points[:17].round(6).tolist(),'kpts_score':responses[:17],
            'joint_eligibility':eligibility[:17],
            'bbox_xywh':np.r_[np.asarray(box[:2])/[width,height],
                (np.asarray(box[2:])-box[:2])/[width,height]].round(6).tolist(),
            'pose_evidence':evidence,
            'joint_observations':{'version':VERSION,'coordinates':'source_image_pixels',
                'schema':'coco17' if count==17 else 'coco-wholebody-133',
                'raw_xy_px':raw_xy,'raw_response':[float(v) if np.isfinite(v) else None for v in raw],
                'candidate_eligible':candidate.tolist(),'visibility':['unknown']*count,
                'location_uncertainty':['not_calibrated']*count,
                'hand_region_status':'not_independently_observed'}}
    if count==133:
        record['wholebody']={'schema':'coco-wholebody-133','coordinates':'source_image_normalized',
                'kpts_xy':points.round(6).tolist(),'kpts_score':responses,
                'joint_eligibility':eligibility,'raw_xy_px':raw_xy,
                'raw_scores':[float(v) if np.isfinite(v) else None for v in raw],
                'joint_status':reasons,'location_support':['model_candidate_not_verified']*count,
                'score_semantics':'native_model_response_not_calibrated_probability'}
    return record
