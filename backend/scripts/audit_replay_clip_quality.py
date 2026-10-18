"""Native-source integration audit of the new clip pipeline, without user stores."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from core.climb_replay import probe_video, build_pose_samples
from core.replay_pose_clip import LocalClipReplayAnalyzer
from core.replay_analysis_view import visual_evidence, AnalysisView


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',type=Path)
    parser.add_argument('--cache-from',type=Path)
    parser.add_argument('--reuse',type=Path)
    parser.add_argument('--baseline',type=Path)
    args=parser.parse_args()
    print('Validating source and cache',flush=True)
    project=Path(__file__).resolve().parents[2]
    if not args.output.resolve().is_relative_to(project/'.tmp'):
        raise ValueError('Private output required')
    args.output.mkdir(parents=True,exist_ok=False)
    before=digest(args.video)
    info=probe_video(args.video)
    analyzer=LocalClipReplayAnalyzer(observation_model=args.model,device='cpu')
    analyzer.configure_cache(args.output/'raw-cache.json',{'source_sha256':before})
    if args.cache_from:
        saved=json.loads((args.cache_from/'raw-cache.json').read_text('utf-8'))
        if saved['binding'].get('source_sha256')!=before:
            raise ValueError('Cache source mismatch')
        analyzer._pose_cache=saved['frames']
    if args.reuse:
        report=json.loads((args.reuse/'tracks.json').read_text('utf-8'))
        if report['source_sha256']!=before:
            raise ValueError('Cache source mismatch')
        analyzer._pose_cache=json.loads((args.reuse/'raw-cache.json').read_text('utf-8'))
    analyzer._prepare_pose_run({'holds':[],'skeleton_only':True})
    print('Models prepared',flush=True)
    _,positions=analyzer._sampling_positions(info)
    print('Native sampling prepared',len(positions),flush=True)
    cap=cv2.VideoCapture(str(args.video))
    print('Decoder opened',cap.isOpened(),flush=True)
    ok,reference=cap.read()
    print('Reference decoded',ok,flush=True)
    if not ok:
        raise RuntimeError('Reference decode failed')
    started=time.perf_counter()
    def progress(stage,value):
        if value!=progress.last:
            print(f'{stage}: {value}',flush=True)
            progress.last=value
    progress.last=None
    records=[]
    try:
        analyzer._prepare_clip_observations(args.video,info,positions,reference,
                                           progress=progress,cancelled=lambda:False)
        for index,source in enumerate(positions):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(source))
            ok,frame=cap.read()
            record=analyzer._pose_frame(frame,frame_id=index,source_frame_id=int(source)) if ok else None
            if record is None:
                record={'frame_id':index,'source_frame_id':int(source),'bbox_xywh':[0.]*4,
                        'kpts_xy':[[0.,0.]]*17,'kpts_score':[0.]*17,
                        'pose_evidence':{'observed':False,'reason':analyzer.last_pose_failure or 'decode_failed'}}
            matrix,diag=analyzer._person_alignment(int(source)) or (None,{})
            record.update(wall_alignment='aligned' if matrix is not None else 'failed',
                wall_alignment_diagnostics=diag,wall_reference_transform=matrix.tolist() if matrix is not None else None)
            records.append(record)
            if index%50==0:
                print(f'Pose {index+1}/{len(positions)}',flush=True)
        analyzer.flush_pose_cache()
    finally:
        cap.release()
    samples=build_pose_samples(records,info)
    video={'width':info.width,'height':info.height,'fps':info.fps,'frame_count':info.frame_count}
    result={'video':video,'pose_samples':samples,'holds':[],'attempt':{}}
    display=visual_evidence(result)
    native={r['source_frame_id']:r for r in records}
    baseline=json.loads(args.baseline.read_text('utf-8')) if args.baseline else []
    old={r['source_frame_id']:r for r in baseline}
    frames=([42,48,174,180,186,300,510,516,519,522,600,720] if args.video.name.startswith('02_')
            else [0,33,36,39,54,120,180,300,462,480,600,720] if args.video.name.startswith('01_')
            else [0,60,120,180,240,258,261,264,267,270,300,390])
    cap=cv2.VideoCapture(str(args.video))
    from scripts.audit_replay_pose_quality import draw
    view=AnalysisView(result)
    for source in frames:
        if source not in native:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES,source)
        ok,frame=cap.read()
        if not ok:
            continue
        # Draw admissibility separately from model amplitude. This is an audit
        # image, not a calibrated correctness or physical-contact claim.
        shown=deepcopy_record(native[source])
        if shown.get('joint_eligibility') is not None:
            shown['kpts_score']=np.asarray(shown['joint_eligibility'],float).tolist()
        previous=old.get(source)
        if previous is not None and 'bbox_xywh' not in previous:
            previous=None
        panels=[frame,draw(frame,previous),draw(frame,shown)]
        cv2.imwrite(str(args.output/f'comparison-{source}.jpg'),np.hstack(panels))
        rendered=view.frame(frame,source,(info.width*2,info.height))
        cv2.imwrite(str(args.output/f'current-display-{source}.jpg'),rendered)
    cap.release()
    report={'source_sha256':before,'source_unchanged':before==digest(args.video),
        'video':video,
        'seconds':time.perf_counter()-started,'source_sample_count':len(positions),
        'observed':sum(s['observed'] for s in samples),'selection':analyzer._clip_tracks.selection,
        'runtime':analyzer.runtime_metadata(),'model_responses_preserved':True,
        'confidence_calibrated':False,'independent_hand_region_verified':False,
        'scope':'same-source development audit, no independent anatomical/identity truth'}
    for name,value in [('report',report),('records',records),('pose-samples',samples),
                       ('display',display),('tracks',{'source_sha256':before,**analyzer._clip_tracks.evidence()})]:
        (args.output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


def deepcopy_record(record):
    return json.loads(json.dumps(record))


if __name__=='__main__':
    main()
