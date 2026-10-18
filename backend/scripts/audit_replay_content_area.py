"""Read-only ten-material boundary/coordinate check for encoded-bar correction."""
import argparse
import json
from pathlib import Path
import cv2

from core.climb_replay import AliyunReplayAnalyzer, probe_video
from core.replay_hold_fusion import image_content_bounds
from scripts.accept_replay_hold_editor import digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for number,path in enumerate(sorted(args.materials.glob('[0-9][0-9]_*.mp4')),1):
        before=digest(path)
        info=probe_video(path)
        frames=AliyunReplayAnalyzer._hold_frames(path,info,None)
        bounds=[image_content_bounds(frame) for _,frame in frames]
        rows.append({'case':number,'sha256':before,'source_unchanged':before==digest(path),
                     'video':{'width':info.width,'height':info.height,'fps':info.fps,'duration_seconds':info.duration_seconds},
                     'sampled_source_frames':[index for index,_ in frames],'content_bounds':bounds,
                     'area_filter_exactly_unchanged':all(box==[0,0,1,1] for box in bounds)})
    if len(rows)!=10 or not all(row['source_unchanged'] for row in rows):
        raise RuntimeError('Ten-source integrity requirement failed')
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ten sources unchanged; cases with changed area denominator:',
          [row['case'] for row in rows if not row['area_filter_exactly_unchanged']],flush=True)


if __name__=='__main__':
    main()
