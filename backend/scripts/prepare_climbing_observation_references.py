"""Export immutable source frames and blank annotation tasks; never model labels."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--videos',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--definition',type=Path)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    if not args.output.resolve().is_relative_to(project/'.tmp'):raise ValueError('Local private output required')
    args.output.mkdir(parents=True,exist_ok=False)
    definition=json.loads((args.definition or project/'backend/experiments/climbing-observation-annotations-v1.json').read_text('utf-8'))
    tasks=[]
    for clip in definition['clips']:
        matches=list(args.videos.glob(clip['case']+'_*.mp4'))
        if len(matches)!=1:raise ValueError('Unique declared source required')
        with matches[0].open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if sha!=clip['source_sha256']:raise ValueError('Source variant mismatch')
        cap=cv2.VideoCapture(str(matches[0]))
        try:
            fps=cap.get(cv2.CAP_PROP_FPS)
            for source in clip['frames']:
                cap.set(cv2.CAP_PROP_POS_FRAMES,source)
                ok,frame=cap.read()
                if not ok:raise RuntimeError('Source frame unavailable')
                name=f'case-{clip["case"]}-frame-{source}.png'
                if not cv2.imwrite(str(args.output/name),frame):raise RuntimeError('Lossless source export failed')
                tasks.append({'case':clip['case'],'source_sha256':sha,'source_frame_id':source,'time_seconds':source/fps,
                    'image':name,'size_wh':[frame.shape[1],frame.shape[0]],'annotation_status':'unannotated',
                    'target_identity':None,'candidate_people':[],
                    'joints':{joint:{'xy_px':None,'visibility':None} for joint in definition['joints']},
                    'hand_regions':{side:{'polygon_xy_px':None,'visibility':None,'side_verified':None} for side in ('left','right')},
                    'reviewer':None,'reviewed_by':None})
        finally:cap.release()
    (args.output/'annotation-tasks.json').write_text(json.dumps({'definition':definition,'tasks':tasks},indent=2),'utf-8')
    print(json.dumps({'source_frames':len(tasks),'labelled_frames':0,'scope':'development annotation preparation only'}),flush=True)


if __name__=='__main__':main()
