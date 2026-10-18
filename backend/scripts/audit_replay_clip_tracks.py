"""Build all source-person observations, then select a clip target; no user store."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from core.climb_replay import probe_video
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
from core.replay_person_tracks import ClipPersonTracks, consolidate_bodies
from core.replay_person_tracking import appearance


def scan(video, output, reuse=None):
    output.mkdir(parents=True, exist_ok=False)
    info = probe_video(video)
    analyzer = LocalRTMWReplayAnalyzer(device='cpu')
    pose, detector = analyzer._load_models()
    _, positions = analyzer._sampling_positions(info)
    tracks = ClipPersonTracks()
    cap = cv2.VideoCapture(str(video))
    started = time.perf_counter()
    raw = json.loads(reuse.read_text('utf-8')) if reuse else {}
    try:
        for index, source in enumerate(positions):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(source))
            ok, frame = cap.read()
            if not ok:
                tracks.add_frame(int(source),source/info.fps,[])
                continue
            entry = raw.setdefault(str(source), {})
            if 'boxes' not in entry:
                entry['boxes'] = np.asarray(detector(frame)).reshape(-1,4).tolist()
            boxes = np.asarray(entry['boxes']).reshape(-1,4)
            observations = []
            entry.setdefault('poses',{})
            for box in boxes:
                if not np.isfinite(box).all() or min(box[2:]-box[:2])<=4:
                    continue
                box = np.clip(box,[0,0,0,0],[info.width,info.height,info.width,info.height])
                body = None
                if index % 5 == 0 or len(boxes)>1:
                    key = json.dumps(box.round(6).tolist())
                    if key not in entry['poses']:
                        xy, response = pose(frame,[box.tolist()])
                        entry['poses'][key] = [xy.tolist(), response.tolist()]
                    xy,response = map(np.asarray,entry['poses'][key])
                    finite = np.isfinite(xy[0,:17]).all(axis=1) & np.isfinite(response[0,:17]) & (response[0,:17]>.0)
                    body = {'visible_fraction':float(np.mean(finite[5:17])),
                            'torso_xy':(xy[0,[5,6,11,12]]/[info.width,info.height]).tolist() if np.all(finite[[5,6,11,12]]) else None,
                            'torso_center':(xy[0,[5,6,11,12]].mean(axis=0)/[info.width,info.height]).tolist()}
                hist = appearance(frame,box)
                normalized = (box/[info.width,info.height,info.width,info.height]).tolist()
                observations.append({'box':normalized, 'box_xyxy_px':box.tolist(),
                    'association_box':normalized, 'appearance':hist.flatten().tolist() if hist is not None else None,
                    'body':body})
            tracks.add_frame(int(source),source/info.fps,consolidate_bodies(observations))
            raw[str(source)] = entry
            if index%50==0:
                print(f'Observed {index+1}/{len(positions)} frames; {len(tracks.tracks)} tracks',flush=True)
    finally:
        cap.release()
    selection = tracks.select_target()
    with video.open('rb') as stream:
        digest = hashlib.file_digest(stream,'sha256').hexdigest()
    report = {'source_sha256':digest,'elapsed_seconds':time.perf_counter()-started,
              'video':{'width':info.width,'height':info.height,'fps':info.fps}, **tracks.evidence()}
    for name,value in [('tracks',report),('raw-cache',raw)]:
        (output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    cap = cv2.VideoCapture(str(video))
    for source in (42,48,174,180,186,300,516,519,522,600,720):
        if source not in tracks.frames:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES,source)
        ok,frame=cap.read()
        if not ok:
            continue
        for row in tracks.frames[source]['observations']:
            x1,y1,x2,y2=np.rint(row['box_xyxy_px']).astype(int)
            colour=(0,255,0) if row['track_id']==selection['target_track_id'] else (100,100,255)
            cv2.rectangle(frame,(x1,y1),(x2,y2),colour,2)
            cv2.putText(frame,str(row['track_id']),(x1,y1+20),0,.7,colour,2)
        cv2.imwrite(str(output/f'tracks-{source}.jpg'),frame)
    cap.release()
    print(json.dumps(selection,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reuse',type=Path)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]/'.tmp'):
        raise ValueError('Private output required')
    scan(args.video,args.output,args.reuse)
