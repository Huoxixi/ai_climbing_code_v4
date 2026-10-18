"""Bounded extra real frames for persistent weak, thin native black candidates."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .replay_hold_expansion import _conflicts, _native_mask, dark_material_evidence
from .replay_hold_fusion import contour_overlap, transform_polygon, polygon_bbox, fuse_hold_detections
from .replay_hold_colors import observe_hold_colour, region_sample_distance
from .replay_hold_evidence import colour_support, boundary_quality

RESAMPLING_VERSION = 'bounded-clear-native-frames-v1'


def resample_weak_candidates(*, source_video, frames, outputs, detections, existing,
                             sample_group, sample_rgb, reference_frame, model_fn,
                             polygon_fn, alignment_fn, deadline, cancelled, progress):
    metadata = {'version':RESAMPLING_VERSION, 'frames':[], 'new_model_calls':0,
                'reason':'no_persistent_weak_candidate'}
    if sample_group != '黑色' or source_video is None:
        return [], [], [], metadata
    started = time.perf_counter()
    seeds = []
    for rows in detections:
        for d in rows:
            if d.get('native_class') != 0 or not .4 <= d.get('score', 0.) < .65:
                continue
            if not d.get('contour_complete') or _conflicts(d, existing):
                continue
            image, mask = _native_mask(d, frames, outputs)
            width, height = d['bbox'][2]*image.shape[1], d['bbox'][3]*image.shape[0]
            if max(width, height)/max(1., min(width,height)) < 2.:
                continue
            if d.get('boundary_quality', {}).get('edge_fraction', 0.) < .8:
                continue
            if not dark_material_evidence(image, mask, sample_rgb)['qualified']:
                continue
            seeds.append(d)
    seeds = [d for d in seeds if len({e['source_frame'] for e in seeds if contour_overlap(d,e)[0]>=.5})>=2]
    if not seeds:
        return [], [], [], metadata
    capture = cv2.VideoCapture(str(Path(source_video)))
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not capture.isOpened() or total < 1 or not np.isfinite(fps) or fps <= 0:
            metadata['reason'] = 'video_unavailable'
            return [], [], [], metadata
        old_frames = {fr for fr, _ in frames}
        anchors = sorted({d['source_frame'] for d in seeds})
        anchors = [anchors[0], anchors[-1]] if len(anchors)>1 else anchors
        selected = []
        # Pick the sharper real neighbour on each side; never manufacture frames.
        for anchor in anchors:
            for side in (-1, 1):
                choices = []
                for offset in sorted({max(1,round(fps*.1)), max(1,round(fps*.3))}):
                    if cancelled():raise InterruptedError('任务已取消')
                    if time.monotonic() > deadline:raise TimeoutError('补帧超过时限')
                    index = anchor + side*offset
                    if index in old_frames or not 0<=index<total:continue
                    capture.set(cv2.CAP_PROP_POS_FRAMES,index)
                    ok, image = capture.read()
                    if not ok:continue
                    sharpness = float(cv2.Laplacian(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var())
                    choices.append((sharpness,index,image))
                if choices:
                    _, index, image = max(choices,key=lambda item:item[0])
                    if index not in {fr for fr,_ in selected}:selected.append((index,image))
        selected = selected[:4]
    finally:
        capture.release()
    if not selected:
        metadata['reason'] = 'no_available_neighbour'
        return [], [], [], metadata
    native_metadata = []
    progress('补充清晰岩点观测',94)
    extra_outputs, version = model_fn([image for _,image in selected],deadline,cancelled,
        lambda *_:None,pack_masks=True,include_volumes=True,native_metadata=native_metadata,reuse_model=True)
    if len(extra_outputs)!=len(selected) or len(native_metadata)!=len(selected):
        raise ValueError('补帧模型返回数量不一致')
    reference = next(image for fr,image in frames if fr==reference_frame)
    extra_detections = []
    registrations = []
    for fi, ((fr,image),(masks,scores)) in enumerate(zip(selected,extra_outputs)):
        matrix, registration = alignment_fn(image,reference)
        registrations.append({'frame':fr,'aligned':matrix is not None,**registration})
        rows = []
        if matrix is not None:
            height,width=image.shape[:2]
            for mi,(encoded,score,category) in enumerate(zip(masks,scores,native_metadata[fi]['classes'])):
                if category!=0 or score<.4:continue
                mask = ((encoded>0).astype(np.uint8) if encoded.shape[1]==width
                        else np.unpackbits(encoded,axis=1,count=width).astype(np.uint8))
                polygon=polygon_fn(mask).reshape(-1,2)
                if len(polygon)<3:continue
                mapped=transform_polygon(polygon.tolist(),matrix,width,height)
                geometry={'polygon':mapped,'bbox':polygon_bbox(mapped)}
                if not any(contour_overlap(geometry,d)[0]>=.5 for d in seeds):continue
                group,interior,evidence=observe_hold_colour(image,mask)
                distance=region_sample_distance(image,interior,sample_rgb) if sample_rgb else None
                support=colour_support(image,interior,sample_rgb,group,sample_group,distance,
                    colour_evidence=evidence) if sample_rgb else None
                candidate=support['qualified'] if support else group==sample_group
                rows.append(dict(**geometry,score=round(float(score),4),color_group=group,
                    color_source='video' if sample_rgb else 'preset',color_evidence=evidence,
                    color_distance=distance,colour_support=support,route_candidate=candidate,
                    native_class=category,contour_source='climbing_model_native_mask',
                    contour_complete=all(0<x<width-1 and 0<y<height-1 for x,y in polygon),
                    boundary_quality=boundary_quality(image,mask),source_frame=fr,
                    observation_id=f'frame-{fr}-mask-{mi}',identity_source='multi_frame_geometry',
                    evidence_origin='real_neighbour_frame',model_version=version))
        extra_detections.append(rows)
    metadata.update(reason='completed',frames=[fr for fr,_ in selected],new_model_calls=len(selected),
        seed_frames=anchors,registrations=registrations,seconds=time.perf_counter()-started,
        candidates=sum(map(len,extra_detections)))
    return selected,extra_outputs,extra_detections,metadata


def refine_weak_candidates(*, frames, outputs, detections, existing, sample_group,
                           sample_rgb, reference, alignment_fn, polygon_fn,
                           deadline, cancelled, progress, trace=None,
                           prompt_masks=None, fragment_expansion=False, negative_points=None,
                           prompt_budget=8):
    """Re-segment only persistent thin native proposals in actual extra frames."""
    from .replay_hold_recovery import _predictor, MOBILE_SHA256, select_alternatives
    from .replay_hold_expansion import _conflicts
    from .replay_hold_evidence import material_observation
    metadata = {'model_source':'model_guided_mobilesam_mask', 'frames':[], 'prompts':0,
                'added':0, 'status':'not_needed'}
    if sample_group!='黑色' or len(frames)<3 or prompt_budget<3:
        return [],metadata
    candidates=[d for rows in detections for d in rows
        if (d.get('contour_source')=='climbing_model_native_mask'
            or (d.get('contour_source')=='projected_native_prompt'
                and d.get('prompt_parent_source')=='climbing_model_native_mask'))
        and d.get('native_class')==0 and d.get('contour_complete')
        and not isinstance(d.get('source_frame'),bool) and isinstance(d.get('source_frame'),int)
        and d.get('score',0.)>=.4 and not _conflicts(d,existing)]
    persistent=[d for d in candidates if len({e['source_frame'] for e in candidates
                  if contour_overlap(d,e)[0]>=.75})>=3]
    if not persistent:
        return [],metadata
    if cancelled():raise InterruptedError('任务已取消')
    if time.monotonic()>deadline:raise TimeoutError('细岩点复核超过时限')
    predictor,reason=_predictor()
    if predictor is None:
        metadata['status']=reason
        return [],metadata
    import torch
    observations=[]
    for fr,image in frames:
        rows=sorted([d for d in persistent if d['source_frame']==fr],key=lambda d:-d['score'])[:2]
        if not rows:continue
        if cancelled():raise InterruptedError('任务已取消')
        if time.monotonic()>deadline:raise TimeoutError('细岩点复核超过时限')
        matrix,registration=alignment_fn(image,reference)
        if matrix is None:continue
        progress('核对细岩点轮廓',96)
        metadata['frames'].append(fr)
        for d in rows:
            if metadata['prompts']>=prompt_budget:break
            native = prompt_masks[d['observation_id']] if prompt_masks is not None else _native_mask(d,frames,outputs)[1]
            depth=cv2.distanceTransform(native,cv2.DIST_L2,5)
            y,x=np.unravel_index(depth.argmax(),depth.shape)
            ys,xs=np.where(native)
            if not len(xs) or depth[y,x]<2:continue
            box=np.array([int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())],np.float32)
            width=max(96.,(box[2]-box[0]+1)*4)
            height=max(96.,(box[3]-box[1]+1)*(2. if fragment_expansion else 1.5))
            cx,cy=(box[:2]+box[2:])/2
            left=max(0,int(cx-width/2));right=min(image.shape[1],int(cx+width/2)+1)
            top=max(0,int(cy-height/2));bottom=min(image.shape[0],int(cy+height/2)+1)
            crop=image[top:bottom,left:right]
            with torch.inference_mode():predictor.set_image(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
            negatives=[point for point in (negative_points or {}).get(fr,[])
                       if left<=point[0]<right and top<=point[1]<bottom]
            # A centre can lie outside the crop while part of an accepted hold
            # lies inside. Sample its actual in-crop interior as exclusion too.
            for kept in (existing if fragment_expansion else []):
                pixels=np.asarray(kept['polygon'],np.float32)*[reference.shape[1],reference.shape[0]]
                local=cv2.perspectiveTransform(pixels.astype(np.float32).reshape(-1,1,2),np.linalg.inv(matrix)).reshape(-1,2)-[left,top]
                kept_mask=np.zeros(crop.shape[:2],np.uint8)
                cv2.fillPoly(kept_mask,[np.rint(local).astype(np.int32)],1)
                kept_depth=cv2.distanceTransform(np.pad(kept_mask,1),cv2.DIST_L2,5)[1:-1,1:-1]
                ky,kx=np.unravel_index(kept_depth.argmax(),kept_depth.shape)
                if kept_depth[ky,kx]>=2:negatives.append([int(kx+left),int(ky+top)])
            points=[[int(x),int(y)]]+negatives
            labels=[1]+[0]*len(negatives)
            prompt_box = box.copy()
            if fragment_expansion:
                margin=(box[2:]-box[:2])*.25
                prompt_box[:2]-=margin;prompt_box[2:]+=margin
            with torch.inference_mode():masks,scores,_=predictor.predict(
                point_coords=np.asarray(points,np.float32)-[left,top],point_labels=np.asarray(labels,np.int32),
                box=prompt_box-np.array([left,top,left,top]),multimask_output=True)
            metadata['prompts']+=1
            choices=[]
            for local_mask,score in zip(masks,scores):
                if score<.9:continue
                if (local_mask[0].any() or local_mask[-1].any()
                        or local_mask[:,0].any() or local_mask[:,-1].any()):continue
                mask=np.zeros(native.shape,dtype=bool);mask[top:bottom,left:right]=local_mask
                intersection=int((mask&(native>0)).sum())
                iou=intersection/max(1,int(mask.sum())+int(native.sum())-intersection)
                if fragment_expansion:
                    if intersection/max(1,int(native.sum()))<.8 or not .65<=int(mask.sum())/max(1,int(native.sum()))<=3.:continue
                elif iou<.65:continue
                if any(mask[int(py),int(px)] for px,py in negatives):continue
                edge=boundary_quality(image,mask)
                if not edge['not_image_clipped'] or edge['edge_fraction']<.85:continue
                material=dark_material_evidence(image,mask,sample_rgb)
                if not material['qualified']:continue
                polygon=polygon_fn(mask.astype(np.uint8)).reshape(-1,2)
                height,width=image.shape[:2]
                mapped=transform_polygon(polygon.tolist(),matrix,width,height)
                group,interior,evidence=observe_hold_colour(image,mask)
                distance=region_sample_distance(image,interior,sample_rgb) if sample_rgb else None
                support=colour_support(image,interior,sample_rgb,'黑色','黑色',distance,
                    colour_evidence=evidence) if sample_rgb else None
                choices.append((float(score),dict(polygon=mapped,bbox=polygon_bbox(mapped),score=float(score),
                    color_group='黑色',observed_color_group=group,color_source='video' if sample_rgb else 'preset',
                    color_evidence=evidence,color_distance=distance,colour_support=support,
                    route_candidate=True,contour_complete=True,contour_source='model_guided_mobilesam_mask',
                    native_class=d.get('teacher_native_class',0),source_frame=fr,observation_id='weak-sam-'+d['observation_id'],
                    evidence_origin='automatic_supplement',identity_source='multi_frame_geometry',
                    material_identity=material,material_observation=material_observation(evidence,sample_rgb),
                    boundary_quality=edge,teacher_score=d['score'],teacher_observation=d.get('teacher_observation',d['observation_id']),
                    teacher_source_frame=d.get('teacher_source_frame',d['source_frame']),
                    model_guided_prompt={'manual':False,'points':points,'point_labels':labels,
                        'box':prompt_box.tolist(),'teacher_projection':prompt_masks is not None,
                        'crop_xyxy':[left,top,right,bottom], 'model_sha256':MOBILE_SHA256},evidence_channel='weak_native_refined')))
            if choices:observations.append(max(choices,key=lambda item:item[0])[1])
    groups=[]
    for fr in sorted({d['source_frame'] for d in observations}):
        groups.append([d for d in observations if d['source_frame']==fr])
    proposals=fuse_hold_detections(groups,sample_group=sample_group,geometry='contour')
    proposals=[h for h in proposals if len(set(h['contour_evidence']['support_frames']))>=3
               and not _conflicts(h,existing,limit=.05)]
    for h in proposals:h['candidate_id']='weak-refined-'+h['observation_id']
    additions,_=select_alternatives(proposals,existing,sample_group=sample_group,trace=trace)
    metadata.update(status='completed',added=len(additions),model_sha256=MOBILE_SHA256)
    return additions,metadata


def refine_native_fragments(*, frames, outputs, detections, existing, sample_group,
                            sample_rgb, reference_frame, alignment_fn, polygon_fn,
                            deadline, cancelled, progress, trace=None, prompt_budget=8):
    """Project only model prompts; accept new masks from distinct actual images."""
    from .replay_hold_recovery import interior_point
    if sample_group!='黑色' or prompt_budget<3:return [],{'status':'not_needed','added':0,'prompts':0}
    seeds=[]
    for rows in detections:
        for d in rows:
            if d.get('contour_source')!='climbing_model_native_mask' or isinstance(d.get('source_frame'),bool):continue
            if not .4<=d.get('score',0.)<.85 or not d.get('contour_complete') or _conflicts(d,existing):continue
            image,mask=_native_mask(d,frames,outputs)
            width,height=d['bbox'][2]*image.shape[1],d['bbox'][3]*image.shape[0]
            if max(width,height)/max(1.,min(width,height))<1.5:continue
            if d.get('boundary_quality',{}).get('edge_fraction',0.)<.8:continue
            material=dark_material_evidence(image,mask,sample_rgb)
            if material['qualified']:seeds.append(d)
    persistent=[d for d in seeds if len({e['source_frame'] for e in seeds if contour_overlap(d,e)[0]>=.5})>=2
                and any(e.get('native_class')==1 and contour_overlap(d,e)[0]>=.5 for e in seeds)]
    if not persistent:return [],{'status':'no_unresolved_native_fragment','added':0}
    leaders=[]
    for d in sorted(persistent,key=lambda d:-d['score']):
        if not any(contour_overlap(d,e)[1]>=.35 for e in leaders):leaders.append(d)
        if len(leaders)==2:break
    reference=next(im for fr,im in frames if fr==reference_frame)
    selected=[frames[i] for i in sorted(set(np.rint(np.linspace(0,len(frames)-1,min(4,len(frames)))).astype(int)))]
    prompt_masks={};projected=[];negative_points={};valid=[]
    for fr,image in selected:
        matrix,_=alignment_fn(image,reference) if fr!=reference_frame else (np.eye(3),{})
        if matrix is None:continue
        height,width=image.shape[:2];inverse=np.linalg.inv(matrix);rows=[]
        negative_points[fr]=cv2.perspectiveTransform(np.asarray([interior_point(h,width,height) for h in existing],np.float32).reshape(-1,1,2),inverse).reshape(-1,2).tolist() if existing else []
        for n,d in enumerate(leaders):
            pixels=np.asarray(d['polygon'],np.float32)*[reference.shape[1],reference.shape[0]]
            points=cv2.perspectiveTransform(pixels.astype(np.float32).reshape(-1,1,2),inverse).reshape(-1,2)
            mask=np.zeros(image.shape[:2],np.uint8);cv2.fillPoly(mask,[np.rint(points).astype(np.int32)],1)
            oid=f'projected-fragment-{fr}-{n}';prompt_masks[oid]=mask
            rows.append({**d,'source_frame':fr,'observation_id':oid,'native_class':0,
                'contour_source':'projected_native_prompt','prompt_parent_source':d['contour_source'],
                'evidence_origin':'prompt_only_not_observation','teacher_observation':d['observation_id'],
                'teacher_source_frame':d['source_frame'],'teacher_native_class':d.get('native_class',0)})
        valid.append((fr,image));projected.append(rows)
    added,metadata=refine_weak_candidates(frames=valid,outputs=[],detections=projected,
        existing=existing,sample_group=sample_group,sample_rgb=sample_rgb,reference=reference,
        alignment_fn=alignment_fn,polygon_fn=polygon_fn,deadline=deadline,cancelled=cancelled,
        progress=progress,trace=trace,prompt_masks=prompt_masks,fragment_expansion=True,
        negative_points=negative_points,prompt_budget=prompt_budget)
    metadata['teacher_source_frames']=sorted({d['source_frame'] for d in persistent})
    return added,metadata
