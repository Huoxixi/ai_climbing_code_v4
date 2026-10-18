"""Bounded automatic observations for unresolved native hold instances.

Existing accepted contours take precedence. Alternative inference never uses
reference labels, user-drawn shapes, video names, or candidate-number rules.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import os
from pathlib import Path
import sys
import time
import warnings
import cv2
import numpy as np

from .replay_hold_colors import observe_hold_colour, region_sample_distance
from .replay_hold_evidence import (material_observation, sample_compatible_group,
    colour_support, boundary_quality)
from .replay_hold_fusion import (contour_overlap, polygon_bbox, transform_polygon,
    sampled_colour_matches, fuse_hold_detections)
from .replay_hold_fusion import valid_native_contour

RECOVERY_VERSION='model-guided-hold-recovery-v1'
MOBILE_SHA256='6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f'

def retry_frames(anchors, frames, reference_frame):
    counts=Counter(h['source_frame'] for h in anchors)
    if not counts:return []
    primary=min(counts,key=lambda fr:(-counts[fr],fr))
    secondary=reference_frame if reference_frame!=primary else next((fr for fr in frames if fr!=primary),None)
    return [fr for fr in (primary,secondary) if fr is not None and fr in frames]

def interior_point(hold,width,height):
    mask=np.zeros((height,width),np.uint8)
    cv2.fillPoly(mask,[np.rint(np.asarray(hold['polygon'])*[width,height]).astype(np.int32)],1)
    depth=cv2.distanceTransform(mask,cv2.DIST_L2,5)
    y,x=np.unravel_index(depth.argmax(),depth.shape)
    return [int(x),int(y)]

def _predictor():
    root=Path(__file__).resolve().parents[2]
    repo=Path(os.getenv('PHOTO_ROUTE_MOBILESAM_REPO',str(root/'vendor/MobileSAM')))
    checkpoint=Path(os.getenv('PHOTO_ROUTE_MOBILESAM_CHECKPOINT',str(root/'models/mobile_sam.pt')))
    if not (repo/'mobile_sam').is_dir() or not checkpoint.is_file():return None,'model_assets_unavailable'
    with checkpoint.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=MOBILE_SHA256:return None,'model_digest_mismatch'
    dependency=os.getenv('PHOTO_ROUTE_MOBILESAM_DEPENDENCIES')
    if dependency and Path(dependency).is_dir():sys.path.append(dependency)
    sys.path.insert(0,str(repo))
    os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    try:
        import torch
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            from mobile_sam import sam_model_registry, SamPredictor
    except (ImportError,OSError):return None,'model_runtime_unavailable'
    from .replay_model_cache import cached_local_model
    def load():
        torch.set_num_threads(2);torch.manual_seed(0)
        model=sam_model_registry['vit_t']()
        model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True));model.eval()
        return model
    identity=('hold-recovery-mobile',str(checkpoint.resolve()),checkpoint.stat().st_mtime_ns)
    model,_=cached_local_model(identity,load,checkpoint)
    return SamPredictor(model),None

def _observation(image,mask,score,source_frame,matrix,rgb,target,observation_id,native_class,source,polygon_fn):
    polygon=polygon_fn(mask.astype(np.uint8)).reshape(-1,2)
    if len(polygon)<3:return None
    h,w=image.shape[:2];mapped=transform_polygon(polygon.tolist(),matrix,w,h)
    group,interior,evidence=observe_hold_colour(image,mask)
    distance=region_sample_distance(image,interior,rgb)
    material=material_observation(evidence,rgb)
    group=sample_compatible_group(group,material,target)
    support=colour_support(image,interior,rgb,group,target,distance,colour_evidence=evidence)
    return dict(bbox=polygon_bbox(mapped),polygon=mapped,score=round(float(score),4),
        color_group=group,color_source='video',color_evidence=evidence,color_distance=round(distance,4),
        material_observation=material,new_body_resolution=bool(evidence.get('body_resolution')),
        colour_support=support,boundary_quality=boundary_quality(image,mask),native_class=native_class,
        route_candidate=support['qualified'],route_candidate_reason='color_sample',
        contour_source=source,contour_complete=all(0<x<w-1 and 0<y<h-1 for x,y in polygon),
        contour_points=len(mapped),source_frame=source_frame,observation_id=observation_id,
        identity_source='multi_frame_geometry',evidence_origin='automatic_supplement')

def select_alternatives(proposals,existing,*,sample_group,trace=None):
    selected=[];rejected=[]
    for hold in sorted(proposals,key=lambda h:(h.get('evidence_channel')=='fragment',-len(h['contour_evidence']['support_frames']))):
        supports=[r for r in hold['contour_evidence']['observations'] if r.get('complete') and r.get('colour_candidate') and (r.get('iou') or 0)>=.85]
        reason=None
        if not valid_native_contour(hold) or hold.get('evidence_origin')!='automatic_supplement':reason='supplement_invalid_model_origin'
        elif not sampled_colour_matches(hold,sample_group):reason='supplement_colour_unsupported'
        elif len({r['source_frame'] for r in supports if isinstance(r.get('source_frame'),int) and not isinstance(r['source_frame'],bool)})<2:reason='supplement_independent_shape_unsupported'
        elif hold.get('large_expansion') and len({r['source_frame'] for r in supports if (r.get('iou') or 0)>=.9 and isinstance(r.get('source_frame'),int) and not isinstance(r['source_frame'],bool)})<3:reason='expanded_shape_requires_three_frames'
        elif not hold.get('contour_complete'):reason='supplement_clipped'
        elif any(contour_overlap(hold,kept)[1]>=.7 for kept in existing+selected):reason='supplement_overlaps_existing'
        if trace is not None:trace.append(dict(stage='selection',candidate_id=hold['candidate_id'],
            status='rejected' if reason else 'selected',**({'reason':reason} if reason else {})))
        (rejected if reason else selected).append(hold)
    return selected,rejected

def recover_hold_candidates(*,frames,matrices,reference_frame,detections,native_outputs,
                            all_holds,existing,sample_group,sample_rgb,model_fn,polygon_fn,
                            deadline,cancelled,progress,trace=None,native_retries=False):
    """Retain original evidence; add at most two native retries and bounded SAM prompts."""
    started=time.perf_counter();metadata=dict(version=RECOVERY_VERSION,native_retry_frames=[],
        sam_encoded_frames=[],sam_prompt_count=0,original_selected_contours_preserved=True)
    valid_frames={fr:(i,image,matrices[i]) for i,(fr,image) in enumerate(frames) if matrices[i] is not None}
    anchors=[h for h in all_holds if h.get('appearances')==1 and h.get('native_class')==0
        and h.get('score',0)>=.9 and not h.get('new_body_resolution') and sampled_colour_matches(h,sample_group)]
    extra=[]
    # Native flips were tested independently. Layered SAM recovery achieves
    # better coverage here without their extra whole-image inference cost.
    retries=retry_frames(anchors,valid_frames,reference_frame) if native_retries else []
    if retries:
        native_meta=[]
        outputs,_=model_fn([cv2.flip(valid_frames[fr][1],1) for fr in retries],deadline,cancelled,progress,
            include_volumes=True,native_metadata=native_meta,reuse_model=True)
        metadata['native_retry_frames']=retries
        for fr,(masks,scores),meta in zip(retries,outputs,native_meta):
            _,image,matrix=valid_frames[fr]
            for mi,(mask,score,cls) in enumerate(zip(masks,scores,meta['classes'])):
                if cls!=0 or score<.65:continue
                mask=cv2.flip(mask,1)
                polygon=polygon_fn(mask.astype(np.uint8)).reshape(-1,2)
                if len(polygon)<3:continue
                mapped=transform_polygon(polygon.tolist(),matrix,image.shape[1],image.shape[0])
                geometry=dict(polygon=mapped,bbox=polygon_bbox(mapped))
                if not any(contour_overlap(geometry,h)[0]>=.5 for h in anchors):continue
                d=_observation(image,mask,score,fr,matrix,sample_rgb,sample_group,f'flip-{fr}-{mi}',0,'climbing_model_native_mask',polygon_fn)
                if d:extra.append(d)
    by_id={h['candidate_id']:h for h in all_holds}
    selected_ids={h['candidate_id'] for h in existing}
    sparse={}
    for merged in all_holds:
        if merged.get('native_class')!=0:continue
        for link in merged.get('merge_relations',[]):
            for a,b in [link['parts'],list(reversed(link['parts']))]:
                h=by_id[a]
                if h.get('appearances')==1 and h.get('native_class')==0 and h.get('score',0)>=.65 \
                        and sampled_colour_matches(h,sample_group) and b in selected_ids:
                    sparse[a]=[b]
    fragments={h['candidate_id']:h for h in all_holds if h.get('appearances')==1 and h.get('native_class')==0
        and h.get('score',0)>=.65 and not h.get('new_body_resolution') and sampled_colour_matches(h,sample_group)
        and h['candidate_id'] not in sparse and not any(contour_overlap(h,kept)[1]>=.7 for kept in existing)}
    prompts={fr:[] for fr in valid_frames}
    for fr,(fi,image,matrix) in valid_frames.items():
        def raw_mask(d):
            index=int(d['observation_id'].split('-')[-1]);encoded=native_outputs[fi][0][index]
            return (encoded>0).astype(np.uint8) if encoded.shape[1]==image.shape[1] else np.unpackbits(encoded,axis=1,count=image.shape[1]).astype(np.uint8)
        volumes=[d for d in detections[fi] if d.get('native_class')==1 and d.get('score',0)>=.8 and sampled_colour_matches(d,sample_group)]
        masks={d['observation_id']:raw_mask(d) for d in volumes}
        seeds={};neighbors={}
        for d in volumes:
            oid=d['observation_id'];mask=masks[oid]
            linked=[e['observation_id'] for e in volumes if e is not d and int((mask&masks[e['observation_id']]).sum())/max(1,min(int(mask.sum()),int(masks[e['observation_id']].sum())))>=.15]
            if not linked:continue
            exclusive=mask&(1-np.maximum.reduce([masks[n] for n in linked]))
            depth=cv2.distanceTransform(exclusive,cv2.DIST_L2,5);y,x=np.unravel_index(depth.argmax(),depth.shape)
            if depth[y,x]<2:continue
            seeds[oid]=[int(x),int(y)];neighbors[oid]=linked
        for oid,point in seeds.items():
            negatives=[seeds[n] for n in neighbors[oid] if n in seeds]
            if negatives:prompts[fr].append(dict(points=[point]+negatives,native_class=1,parent_area=int(masks[oid].sum()),observation_id='sam-volume-'+oid,channel='paired'))
        for cid,linked in sparse.items():
            height,width=image.shape[:2]
            ref_points=[interior_point(by_id[cid],width,height)]+[interior_point(by_id[n],width,height) for n in linked]
            points=cv2.perspectiveTransform(np.asarray(ref_points,np.float32).reshape(-1,1,2),np.linalg.inv(matrix)).reshape(-1,2)
            if not (0<=points[0,0]<width and 0<=points[0,1]<height):continue
            area=cv2.contourArea(np.asarray(by_id[cid]['polygon'],np.float32)*np.array([width,height],np.float32))
            prompts[fr].append(dict(points=points.tolist(),native_class=0,parent_area=area,observation_id=f'sam-sparse-{fr}-{cid}',channel='paired'))
        for cid,parent in fragments.items():
            height,width=image.shape[:2]
            point=interior_point(parent,width,height)
            points=cv2.perspectiveTransform(np.asarray([point],np.float32).reshape(-1,1,2),np.linalg.inv(matrix)).reshape(-1,2)
            if not (0<=points[0,0]<width and 0<=points[0,1]<height):continue
            area=cv2.contourArea(np.asarray(parent['polygon'],np.float32)*np.array([width,height],np.float32))
            prompts[fr].append(dict(points=points.tolist(),native_class=0,parent_area=area,observation_id=f'sam-fragment-{fr}-{cid}',channel='fragment',parent=parent))
    if any(prompts.values()):
        predictor,reason=_predictor();metadata['sam_status']=reason or 'completed'
        if predictor is not None:
            import torch
            for fr,rows in prompts.items():
                if not rows:continue
                if cancelled():raise InterruptedError('任务已取消')
                if time.monotonic()>deadline:raise TimeoutError('岩点复核超过时限')
                _,image,matrix=valid_frames[fr]
                progress('核对相邻岩点轮廓',93)
                with torch.inference_mode():predictor.set_image(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
                metadata['sam_encoded_frames'].append(fr);accepted=[]
                for prompt in rows:
                    points=np.asarray(prompt['points'],np.float32);labels=np.asarray([1]+[0]*(len(points)-1),np.int32)
                    with torch.inference_mode():masks,scores,_=predictor.predict(point_coords=points,point_labels=labels,multimask_output=True)
                    metadata['sam_prompt_count']+=1;choices=[]
                    fragment=prompt['channel']=='fragment'
                    for mask,score in zip(masks,scores):
                        if score<.9 or not .25<=int(mask.sum())/max(1,prompt['parent_area'])<=(6. if fragment else 2.5):continue
                        if any(mask[min(image.shape[0]-1,max(0,round(y))),min(image.shape[1]-1,max(0,round(x)))] for x,y in points[1:]):continue
                        edge=boundary_quality(image,mask)
                        if not edge['not_image_clipped'] or edge['edge_fraction']<(.8 if fragment else .85):continue
                        choices.append((float(score),mask))
                    if not choices:continue
                    score,mask=max(choices,key=lambda item:item[0])
                    d=_observation(image,mask,score,fr,matrix,sample_rgb,sample_group,prompt['observation_id'],prompt['native_class'],'model_guided_mobilesam_mask',polygon_fn)
                    if d:
                        if fragment and contour_overlap(d,prompt['parent'])[1]<.7:continue
                        d['evidence_channel']=prompt['channel']
                        d['large_expansion']=fragment and int(mask.sum())/max(1,prompt['parent_area'])>2.5
                        d['model_guided_prompt']={'points':prompt['points'],'point_labels':labels.tolist(),'manual':False,'model_sha256':MOBILE_SHA256}
                        accepted.append(d)
                volumes=[d for d in accepted if d['native_class']==1]
                bad={d['observation_id'] for i,a in enumerate(volumes) for b in volumes[i+1:] if contour_overlap(a,b)[1]>.05 for d in (a,b)}
                extra.extend(d for d in accepted if d['observation_id'] not in bad)
    grouped={}
    for d in extra:grouped.setdefault((d['contour_source'],d.get('evidence_channel')),{}).setdefault(d['source_frame'],[]).append(d)
    proposals=[]
    for source,observations in grouped.items():
        proposals.extend(fuse_hold_detections(list(observations.values()),sample_group=sample_group,evidence_policy='material_boundary'))
    for index,h in enumerate(proposals,1):h['candidate_id']=f'automatic-{index}'
    if trace is not None:
        trace.extend(dict(stage='supplement_observation',**d) for d in extra)
        trace.extend(dict(stage='supplement_fusion',**h) for h in proposals)
    added,rejected=select_alternatives(proposals,existing,sample_group=sample_group,trace=trace)
    metadata.update(seconds=time.perf_counter()-started,added=len(added),rejected=len(rejected))
    return added,rejected,metadata
