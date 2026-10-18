"""S0/S3: isolated native-frame observations and source overlays, no smoothing."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

import cv2
import numpy as np

from core.climb_replay import probe_video, build_pose_samples
from core.replay_hold_fusion import align_to_reference
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
from scripts.accept_replay_hold_editor import digest, measured_resources

EDGES=((5,6),(5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16))


def draw(frame,record):
    image=frame.copy()
    if not record:
        return image
    h,w=image.shape[:2]
    points=np.rint(np.asarray(record['kpts_xy'])*[w,h]).astype(int)
    scores=record['kpts_score']
    for a,b in EDGES:
        if min(scores[a],scores[b])>=.5:
            cv2.line(image,tuple(points[a]),tuple(points[b]),(0,255,255),2)
    for index in (9,10,15,16):
        if scores[index]>=.5:
            cv2.circle(image,tuple(points[index]),4,(255,100,0),-1)
            cv2.putText(image,str(index),tuple(points[index]+[4,-4]),0,.5,(255,100,0),1)
    x,y,ww,hh=record['bbox_xywh']
    cv2.rectangle(image,(round(x*w),round(y*h)),(round((x+ww)*w),round((y+hh)*h)),(0,200,0),1)
    cv2.putText(image,f"source {record['source_frame_id']}",(8,22),0,.6,(255,255,255),1)
    return image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases',default='1,2,9')
    parser.add_argument('--fps',type=float,default=10)
    parser.add_argument('--start',type=float,default=0)
    parser.add_argument('--end',type=float)
    parser.add_argument('--route-bounds',type=float,nargs=4,
                        help='Human diagnostic route rectangle, not an automatic accuracy result')
    parser.add_argument('--context-retry',action='store_true')
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    if not args.output.is_absolute() or not args.output.is_relative_to(project/'.tmp'):
        raise ValueError('Private absolute .tmp output required')
    args.output.mkdir(parents=True,exist_ok=False)
    sources=sorted(args.materials.glob('[0-9][0-9]_*.mp4'))
    cases={int(item) for item in args.cases.split(',')}
    manifest=[]
    for number,source in enumerate(sources,1):
        if number not in cases:
            continue
        case=args.output/f'case-{number:02}'
        case.mkdir()
        before=digest(source)
        info=probe_video(source)
        analyzer=LocalRTMWReplayAnalyzer(pose_fps=args.fps,device='cpu',context_retry=args.context_retry)
        analyzer._source_fps=info.fps
        holds=[]
        if args.route_bounds:
            x0,y0,x1,y1=args.route_bounds
            holds=[{'bbox':[x0,y0,x1-x0,y1-y0]}]
        analyzer._prepare_pose_run({'holds':holds,'skeleton_only':not bool(holds)})
        _,positions=analyzer._sampling_positions(info)
        positions=[int(p) for p in positions if args.start<=p/info.fps<(args.end or info.duration_seconds)]
        cap=cv2.VideoCapture(str(source))
        ok,reference=cap.read()
        if not ok:
            raise RuntimeError('Reference decode failed')
        records,trace=[],[]
        started=time.monotonic()
        with measured_resources() as resources:
            try:
                for index,position in enumerate(positions):
                    cap.set(cv2.CAP_PROP_POS_FRAMES,position)
                    ok,frame=cap.read()
                    if not ok:
                        raise RuntimeError('Source frame decode failed')
                    if args.route_bounds:
                        matrix,_=align_to_reference(frame,reference)
                        analyzer.set_person_reference_transform(matrix,[info.width,info.height],[info.width,info.height])
                    record=analyzer._pose_frame(frame,frame_id=index,source_frame_id=position)
                    trace.append({'source_frame_id':position,'detected_boxes':analyzer._active_frame_cache.get('boxes'),
                                  'selected_box':record['bbox_xywh'] if record else None,
                                  'reason':record['pose_evidence']['selection'] if record else analyzer.last_pose_failure})
                    records.append(record or {'frame_id':index,'source_frame_id':position,'kpts_xy':[[0,0]]*17,
                                              'kpts_score':[0.]*17,'pose_evidence':{'observed':False}})
                    if index%round(args.fps*2)==0:
                        cv2.imwrite(str(case/f'source-{position}.jpg'),draw(frame,record))
            finally:
                cap.release()
        samples=build_pose_samples(records,info)
        # Speed is an audit locator, never a rejection or a replacement point.
        speeds=[]
        for a,b in zip(samples,samples[1:]):
            dt=b['time_seconds']-a['time_seconds']
            if not a.get('observed') or not b.get('observed') or not 0<dt<=.3:
                continue
            for joint in (9,10,15,16):
                if min(a['kpts_score'][joint],b['kpts_score'][joint])>=.5:
                    delta=(np.asarray(b['kpts_xy'][joint])-a['kpts_xy'][joint])*[info.width,info.height]
                    speeds.append({'source_frame':b['source_frame_id'],'joint':joint,'px_per_second':float(np.linalg.norm(delta)/dt)})
        speeds.sort(key=lambda row:row['px_per_second'],reverse=True)
        cap=cv2.VideoCapture(str(source))
        by_source={row['source_frame_id']:row for row in records}
        for row in speeds[:8]:
            cap.set(cv2.CAP_PROP_POS_FRAMES,row['source_frame'])
            ok,frame=cap.read()
            if ok:
                cv2.imwrite(str(case/f'fast-{row["source_frame"]}.jpg'),draw(frame,by_source[row['source_frame']]))
        cap.release()
        report={'case':number,'source_sha256':before,'source_unchanged':before==digest(source),
                'video':{'width':info.width,'height':info.height,'fps':info.fps,'frame_count':info.frame_count,
                         'duration_seconds':info.duration_seconds},'requested_fps':args.fps,
                'source_interval':[args.start,args.end or info.duration_seconds],
                'human_diagnostic_route_bounds':args.route_bounds,
                'experimental_context_retry':args.context_retry,
                'checked_source_frames':[r['source_frame_id'] for r in records if r.get('pose_revision')],
                'revised_source_frames':[r['source_frame_id'] for r in records if (r.get('pose_revision') or {}).get('status')=='accepted_experimental'],
                'observed':sum(bool(s.get('observed')) for s in samples),'samples':len(samples),
                'score_eligible_counts':{str(j):sum(s.get('observed') and s['kpts_score'][j]>=.5 for s in samples)
                                         for j in (9,10,15,16)},
                'fast_observations_for_review':speeds[:8],'seconds':round(time.monotonic()-started,3),
                'resources':resources,'selection_counts':dict(Counter(row['reason'] for row in trace)),
                'runtime':analyzer.runtime_metadata(),
                'scope':'raw-source-observations; no manual location truth; score eligibility is not accuracy'}
        for name,value in [('report',report),('trace',trace),('records',records),('pose-samples',samples)]:
            (case/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        manifest.append(report)
        (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'case {number:02}: {report["observed"]}/{len(samples)} observed, {report["seconds"]}s',flush=True)


if __name__=='__main__':
    main()
