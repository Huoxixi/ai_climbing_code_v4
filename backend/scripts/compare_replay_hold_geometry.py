"""H3: compare association on exactly the same saved observations, no inference."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from core.replay_hold_fusion import fuse_hold_detections, select_sampled_route_holds, image_content_bounds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--materials',type=Path)
    args = parser.parse_args()
    rows = []
    for case in sorted(args.input.glob('case-*')):
        old = json.loads((case/'report.json').read_text('utf-8'))
        frames = old['diagnostics']['sampled_source_frames']
        detections = [[row for row in old['trace'] if row['stage']=='mapping'
                       and row['status']=='retained' and row['source_frame']==frame] for frame in frames]
        number = old['case']
        # These preset color memberships are explicitly candidates for review.
        color = {1:'青色',8:'青色',9:'黄色'}[number]
        detections = [[{**hold,'route_candidate':hold.get('color_group')==color}
                       for hold in frame] for frame in detections]
        for policy in ('bbox','contour','content_area'):
            geometry = 'contour' if policy=='contour' else 'bbox'
            fused = fuse_hold_detections(detections,geometry=geometry)
            trace = []
            overlay = cv2.imread(str(case/f'source-{old["diagnostics"]["reference_frame"]}.jpg'))
            bounds = None
            if policy=='content_area':
                if not args.materials:
                    raise ValueError('Original material directory required for content area measurement')
                source = sorted(args.materials.glob('[0-9][0-9]_*.mp4'))[number-1]
                cap = cv2.VideoCapture(str(source))
                cap.set(cv2.CAP_PROP_POS_FRAMES,old['diagnostics']['reference_frame'])
                ok,native = cap.read()
                cap.release()
                if not ok:
                    raise RuntimeError('Cannot decode original reference frame')
                bounds = image_content_bounds(native)
            selected,rejected,selection = select_sampled_route_holds(fused,sample_group=color,trace=trace,
                                                                   geometry=geometry,content_bounds=bounds)
            for hold in selected:
                xy = np.rint(np.asarray(hold['polygon'])*[overlay.shape[1],overlay.shape[0]]).astype(np.int32)
                cv2.polylines(overlay,[xy],True,(0,220,255),2)
                cv2.putText(overlay,hold['candidate_id'].split('-')[-1],tuple(xy[0]),0,.5,(0,220,255),1)
            cv2.imwrite(str(case/f'route-{policy}.jpg'),overlay)
            rows.append({'case':number,'geometry':policy,'fused_count':len(fused),
                         'selected_count':len(selected),'selection':selection,'selected':selected,
                         'rejected':rejected,'trace':trace,'scope':'same-outputs-association-not-accuracy'})
    (args.input/'geometry-comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in row.items() if k not in {'selected','rejected','trace'}} for row in rows],ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
