"""Same source frames and weights, varying only a pose input box (S1)."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np

from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
from scripts.audit_replay_pose_quality import draw
from scripts.accept_replay_hold_editor import digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--records',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    records=json.loads(args.records.read_text('utf-8'))
    analyzer=LocalRTMWReplayAnalyzer(device='cpu')
    pose,_=analyzer._load_models()
    rows=[]
    cap=cv2.VideoCapture(str(args.video))
    before=digest(args.video)
    for source in (516,519,522):
        cap.set(cv2.CAP_PROP_POS_FRAMES,source)
        ok,frame=cap.read()
        if not ok:
            raise RuntimeError('Native source frame decode failed')
        h,w=frame.shape[:2]
        record=next(r for r in records if r['source_frame_id']==source)
        x,y,ww,hh=record['bbox_xywh']
        legacy=np.array([x*w,y*h,(x+ww)*w,(y+hh)*h])
        previous=next(r for r in records if r['source_frame_id']==510)
        px,py,pw,ph=previous['bbox_xywh']
        prior_points=np.asarray(previous['kpts_xy'])*[w,h]
        low,high=prior_points.min(axis=0),prior_points.max(axis=0)
        margin=max(16.,float(np.max(high-low))*.1)
        prior_joint_box=np.r_[np.maximum(low-margin,0),np.minimum(high+margin,[w,h])]
        # A human checked crop is an attribution control, never an automatic result.
        for label,box in [('detected',legacy),('previous_510',np.array([px*w,py*h,(px+pw)*w,(py+ph)*h])),
                          ('previous_joint_context',prior_joint_box),
                          ('human_context',np.array([185.,265.,400.,735.]))]:
            started=time.monotonic()
            xy,scores=pose(frame,[box.tolist()])
            points=np.asarray(xy[0])/[w,h]
            shown={'source_frame_id':source,'kpts_xy':points.tolist(),
                   'kpts_score':np.clip(scores[0],0,1).tolist(),
                   'bbox_xywh':[box[0]/w,box[1]/h,(box[2]-box[0])/w,(box[3]-box[1])/h]}
            cv2.imwrite(str(args.output/f'{source}-{label}.jpg'),draw(frame,shown))
            rows.append({'source_frame':source,'box_condition':label,'box_xyxy_px':box.tolist(),
                         'points_px':np.asarray(xy[0]).tolist(),'raw_responses':np.asarray(scores[0]).tolist(),
                         'seconds':round(time.monotonic()-started,4),'source_sha256':before,
                         'scope':'input attribution; human and previous boxes not automatically verified'})
    cap.release()
    (args.output/'report.json').write_text(json.dumps({'source_unchanged':before==digest(args.video),'rows':rows},indent=2),encoding='utf-8')
    print('twelve same-frame box comparisons saved; source unchanged',flush=True)


if __name__=='__main__':
    main()
