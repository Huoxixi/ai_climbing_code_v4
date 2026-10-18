"""Isolated real-frame tracking audit. No replay database or external API access."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

import cv2
import numpy as np

from core.climb_replay import probe_video, build_pose_samples, align_to_reference
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer


def run(video, draft, output):
    output.mkdir(parents=True, exist_ok=False)
    info = probe_video(video)
    analyzer = LocalRTMWReplayAnalyzer(pose_fps=10)
    _, positions = analyzer._sampling_positions(info)
    analyzer._prepare_pose_run(draft)
    capture = cv2.VideoCapture(str(video))
    capture.set(cv2.CAP_PROP_POS_FRAMES,int((draft.get('hold_evidence') or {}).get('reference_frame') or 0))
    ok, reference = capture.read()
    if not ok:
        capture.release()
        raise RuntimeError('reference-frame decode failed')
    capture.set(cv2.CAP_PROP_POS_FRAMES,0)
    records, trace, tiles = [], [], []
    started = time.perf_counter()
    try:
        cursor = 0
        for index, source in enumerate(positions):
            while cursor < int(source):
                capture.grab()
                cursor += 1
            ok, frame = capture.read()
            cursor += 1
            if not ok:
                raise RuntimeError('native-frame decode failed')
            matrix, _ = align_to_reference(frame,reference)
            analyzer.set_person_reference_transform(matrix,[info.width,info.height],[info.width,info.height])
            record = analyzer._pose_frame(frame, frame_id=index, source_frame_id=int(source))
            trace.append({'source_frame_id': int(source), 'time_seconds': int(source)/info.fps,
                          'selected_box': record['bbox_xywh'] if record else None,
                          'reason': record['pose_evidence']['selection'] if record else analyzer.last_pose_failure,
                          'detected_boxes': analyzer._active_frame_cache['boxes']})
            records.append(record or {'frame_id': index, 'source_frame_id': int(source),
                                      'kpts_xy': [[0,0]]*17, 'kpts_score': [0]*17,
                                      'bbox_xywh': [0,0,0,0], 'pose_evidence': {
                                          'observed': False, 'reason': analyzer.last_pose_failure}})
            if index % 30 == 0:
                if record:
                    x,y,w,h = record['bbox_xywh']
                    cv2.rectangle(frame,(round(x*info.width),round(y*info.height)),
                                  (round((x+w)*info.width),round((y+h)*info.height)), (0,255,255),3)
                cv2.putText(frame,f'{source/info.fps:.1f}s {trace[-1]["reason"]}',(10,30),0,.65,(255,255,255),2)
                tiles.append(cv2.resize(frame,(216,384)))
    finally:
        capture.release()
    samples = build_pose_samples(records,info)
    valid = [s['source_frame_id'] for s in samples if s.get('observed')]
    profile = {'video': str(video), 'sample_count': len(samples), 'observed_samples': len(valid),
               'first_observed_seconds': valid[0]/info.fps if valid else None,
               'last_observed_seconds': valid[-1]/info.fps if valid else None,
               'longest_between_observations_seconds': max(np.diff(valid),default=0)/info.fps,
               'selection_counts': dict(Counter(t['reason'] for t in trace)),
               'elapsed_seconds': round(time.perf_counter()-started,3), 'runtime': analyzer.runtime_metadata(),
               'scope': 'engineering diagnosis; supplied holds may be synthetic; identity accuracy unscored'}
    for name,value in [('profile',profile),('trace',trace),('pose-samples',samples)]:
        (output/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    if tiles:
        while len(tiles)%5:
            tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(str(output/'contact-sheet.jpg'),np.vstack([np.hstack(tiles[i:i+5]) for i in range(0,len(tiles),5)]))
    print(json.dumps(profile,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--holds-result',type=Path,required=True,help='Isolated result JSON containing holds, never a private job')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.video,json.loads(args.holds_result.read_text('utf-8')),args.output)
