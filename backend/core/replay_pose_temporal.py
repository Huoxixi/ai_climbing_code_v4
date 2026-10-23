"""Isolated image-supported temporal pose candidate; never a contact detector.

Neighbour observations are transported through real images with a round-trip
Lucas-Kanade check. Two neighbours must agree in the current source image.
There is no recursive tracking, hold snapping, gap filling or side relabelling.
Raw model records remain immutable; inferred locations have separate provenance.
The optional display adapter preserves native observations and contact inputs.
"""
from copy import deepcopy
from collections import deque

import cv2
import numpy as np

VERSION = 'bidirectional-image-pose-consensus-v3'
JOINTS = (7,8,9,10,13,14,15,16,17,18,19,20,21,22)
CHAINS = ((5,7,9),(6,8,10),(11,13,15),(12,14,16))


def transport(previous, current, points, eligible):
    """Return source-pixel image tracks and explicit support/rejection metadata."""
    points=np.asarray(points,float);eligible=np.asarray(eligible,bool)
    n=len(points);result=points.copy();valid=np.zeros(n,bool)
    fb=np.full(n,np.inf);photometric=np.full(n,np.inf)
    if previous.shape!=current.shape or previous.ndim!=2:
        return result,valid,fb,photometric
    ids=np.flatnonzero(eligible & np.isfinite(points).all(axis=1))
    if not len(ids):return result,valid,fb,photometric
    p0=points[ids].astype(np.float32).reshape(-1,1,2)
    params=dict(winSize=(21,21),maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
    p1,status,error=cv2.calcOpticalFlowPyrLK(previous,current,p0,None,**params)
    if p1 is None:return result,valid,fb,photometric
    safe=np.isfinite(p1).all(axis=(1,2))
    p1[~safe]=p0[~safe]
    p2,back,_=cv2.calcOpticalFlowPyrLK(current,previous,p1,None,**params)
    if p2 is None:return result,valid,fb,photometric
    h,w=current.shape
    fb[ids]=np.linalg.norm((p2-p0).reshape(-1,2),axis=1)
    photometric[ids]=error.reshape(-1)
    okay=(status.ravel()==1)&(back.ravel()==1)&safe
    okay &= np.isfinite(p2).all(axis=(1,2))&(fb[ids]<=1.5)&(photometric[ids]<=20)
    q=p1.reshape(-1,2)
    okay &= (q[:,0]>=11)&(q[:,0]<w-11)&(q[:,1]>=11)&(q[:,1]<h-11)
    result[ids]=q;valid[ids]=okay
    return result,valid,fb,photometric


def refine_triplet(records, images, *, source_fps, source_size):
    """Produce a separate candidate for the middle observation only.

    Images may be uniformly resized for cost. Coordinates always leave in original
    source pixels. Inference is not upgraded to a verified model observation.
    """
    middle=records[1];unchanged=deepcopy(middle)
    evidence={'version':VERSION,'status':'unchanged','updates':[],
        'semantics':'image_supported_temporal_inference_not_contact_evidence'}
    def reject(reason):
        evidence['reason']=reason
        return unchanged,evidence
    if not source_fps>0 or any(r.get('pose_evidence',{}).get('observed') is not True for r in records):
        return reject('missing_source_observation')
    ids=[r.get('source_frame_id') for r in records]
    if any(not isinstance(v,int) or isinstance(v,bool) for v in ids):return reject('invalid_source_clock')
    if not all(0<(b-a)/source_fps<=.2 for a,b in zip(ids,ids[1:])):return reject('sampling_gap')
    samples=[r.get('frame_id',r.get('sample_index')) for r in records]
    if all(isinstance(v,int) and not isinstance(v,bool) for v in samples) and any(b-a!=1 for a,b in zip(samples,samples[1:])):
        return reject('missing_sample')
    if len({r.get('track_id') for r in records})!=1:return reject('track_change')
    wholes=[r.get('wholebody') or {} for r in records]
    if any(w.get('schema')!='coco-wholebody-133' or w.get('coordinates')!='source_image_normalized' for w in wholes):
        return reject('incompatible_coordinates')
    try:
        xy=[np.asarray(w['kpts_xy'],float)*source_size for w in wholes]
        flags=[np.asarray(w['joint_eligibility'],bool) for w in wholes]
        if any(p.shape!=(133,2) or m.shape!=(133,) for p,m in zip(xy,flags)):return reject('invalid_shape')
        if any(not np.all(m[[5,6,11,12]]) for m in flags):return reject('missing_body_anchor')
        torso=float(np.linalg.norm(xy[1][[5,6]].mean(axis=0)-xy[1][[11,12]].mean(axis=0)))
        if not np.isfinite(torso) or torso<30:return reject('small_body')
        scale=images[1].shape[1]/source_size[0]
        if any(im.shape!=images[1].shape for im in images):return reject('image_size_mismatch')
        left=transport(images[0],images[1],xy[0]*scale,flags[0])
        right=transport(images[2],images[1],xy[2]*scale,flags[2])
        agree=np.linalg.norm(left[0]-right[0],axis=1)/scale
        image_supported=left[1]&right[1]&flags[1]
        supported=image_supported&(agree<=max(4.,torso*.035))
        target=(left[0]+right[0])/(2*scale)
        new=xy[1].copy()
        for j in JOINTS:
            if not image_supported[j]:continue
            delta=float(np.linalg.norm(target[j]-xy[1][j]))
            # A three-frame image estimate damps noise without an accumulating
            # filter. Large deviations are retained for explicit model review.
            mode='three_image_estimate'
            if delta>max(12.,.20*torso):
                # A detached foot detail (for example a toe at the knee) is
                # reviewed using two independent image transports from plausible
                # observed feet. This exception is symmetric and foot-only.
                if j<17:continue
                ankle=15 if j<20 else 16
                if not all(m[ankle] for m in flags):continue
                far=np.linalg.norm(xy[1][j]-xy[1][ankle])>.65*torso
                attached=np.linalg.norm(target[j]-xy[1][ankle])<.35*torso
                native_support=all(np.linalg.norm(p[j]-p[ankle])<.45*torso for p in (xy[0],xy[2]))
                if not (far and attached and native_support and agree[j]<=max(8.,.1*torso)):continue
                new[j]=target[j];mode='detached_foot_detail_two_image_reconstruction'
            else:
                if not supported[j]:continue
                new[j]=(xy[1][j]+left[0][j]/scale+right[0][j]/scale)/3
            shift=float(np.linalg.norm(new[j]-xy[1][j]))
            if shift<.25:new[j]=xy[1][j];continue
            evidence['updates'].append({'joint':j,'before_xy_px':xy[1][j].tolist(),
                'after_xy_px':new[j].tolist(),'shift_px':shift,'neighbour_agreement_px':float(agree[j]),
                'mode':mode,
                'support_source_frames':[ids[0],ids[2]],
                'round_trip_px':[float(left[2][j]/scale),float(right[2][j]/scale)]})
        # One chain check, shared for both anatomical sides. No fixed 2D bone
        # length is imposed on turns or perspective changes.
        for chain in CHAINS:
            old_lengths=np.linalg.norm(np.diff(xy[1][list(chain)],axis=0),axis=1)
            new_lengths=np.linalg.norm(np.diff(new[list(chain)],axis=0),axis=1)
            if np.any(new_lengths<2) or np.any(new_lengths>3*torso) or np.any(abs(new_lengths-old_lengths)>.2*torso):
                for j in chain[1:]:new[j]=xy[1][j]
                evidence['updates']=[u for u in evidence['updates'] if u['joint'] not in chain[1:]]
        evidence['updates']=[u for u in evidence['updates'] if np.linalg.norm(new[u['joint']]-xy[1][u['joint']])>=.25]
        if not evidence['updates']:return reject('no_two_sided_image_support')
        for update in evidence['updates']:
            j=update['joint'];point=(new[j]/np.asarray(source_size)).round(6).tolist()
            if j<17:unchanged['kpts_xy'][j]=point
            unchanged['wholebody']['kpts_xy'][j]=point
        # Model scores/eligibility/raw observations stay available, but inferred
        # coordinates are explicitly barred from the default contact engine.
        unchanged['observation_kind']='image_supported_temporal_inference'
        unchanged['pose_evidence']['observation_kind']='image_supported_temporal_inference'
        unchanged['temporal_inference']=evidence
        evidence['status']='candidate'
        return unchanged,evidence
    except (KeyError,TypeError,ValueError,IndexError,cv2.error):
        return reject('unusable_image_or_record')


class TemporalDisplayWindow:
    """Bounded three-image window. Only the middle record gets derived display.

    Absolute source coordinates are stored separately. Contact, angles, mass and
    native cache consumers continue to read the unchanged model observation.
    """
    def __init__(self):
        self.window=deque(maxlen=3)
        self.updated_frames=0
        self.updated_joints=0

    def clear(self):
        self.window.clear()

    def push(self,image,record,source_fps):
        if record is None:
            self.clear();return None
        h,w=image.shape[:2];ratio=min(1.,960/max(w,h))
        gray=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(round(w*ratio),round(h*ratio)))
        self.window.append((gray,record,(w,h)))
        if len(self.window)<3:return None
        if len({entry[2] for entry in self.window})!=1:self.clear();return None
        records=[entry[1] for entry in self.window]
        candidate,evidence=refine_triplet(records,[entry[0] for entry in self.window],source_fps=source_fps,source_size=[w,h])
        if not evidence['updates']:return evidence
        middle=records[1]
        middle['temporal_display']={'version':VERSION,'source_frame_id':middle['source_frame_id'],
            'coordinates':'source_image_normalized','kind':'image_supported_temporal_inference',
            'updates':[{'joint':u['joint'],'xy':candidate['wholebody']['kpts_xy'][u['joint']],**u} for u in evidence['updates']]}
        self.updated_frames+=1;self.updated_joints+=len(evidence['updates'])
        return evidence


def display_sample(sample):
    """Apply supported display fields to a copy, with no raw-data side effects."""
    payload=sample.get('temporal_display') or {}
    if (payload.get('version')!=VERSION or payload.get('source_frame_id')!=sample.get('source_frame_id')
            or payload.get('coordinates')!='source_image_normalized'
            or payload.get('kind')!='image_supported_temporal_inference'):
        return sample
    result=deepcopy(sample);whole=result.get('wholebody') or {}
    if whole.get('coordinates')!='source_image_normalized' or len(whole.get('kpts_xy',[]))!=133:return sample
    applied=[]
    for update in payload.get('updates',[]):
        try:
            joint=update['joint'];point=np.asarray(update['xy'],float)
            if (joint not in JOINTS or isinstance(joint,bool) or point.shape!=(2,)
                    or not np.isfinite(point).all() or not ((point>0)&(point<1)).all()
                    or whole.get('joint_eligibility',[False]*133)[joint] is not True):continue
            whole['kpts_xy'][joint]=point.tolist()
            if joint<17:result['kpts_xy'][joint]=point.tolist()
            applied.append(joint)
        except (KeyError,ValueError,TypeError,IndexError):continue
    result['display_basis']={'version':VERSION,'inferred_joints':applied,'contact_evidence':False}
    return result
