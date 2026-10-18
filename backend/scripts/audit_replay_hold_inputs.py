"""Same-frame input/context comparison; sources and app records are read-only."""
import argparse
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

from core.climb_replay import native_mask_polygon, probe_video
from core.photo_route_analysis import _climbing_model_masks_batch
from scripts.accept_replay_hold_editor import digest, measured_resources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    if not args.output.is_absolute() or not args.output.is_relative_to(project / '.tmp'):
        raise ValueError('Absolute private .tmp output required')
    args.output.mkdir(parents=True, exist_ok=False)
    sources = sorted(args.materials.glob('[0-9][0-9]_*.mp4'))
    results = []
    # Freeze previously reported failure regions before any new inference.
    for number, region in [(1,[.23,.55,.38,.62]), (9,[.22,.55,.39,.66])]:
        source = sources[number-1]
        before = digest(source)
        cap = cv2.VideoCapture(str(source))
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError('Cannot decode exact first frame')
        h,w = frame.shape[:2]
        inputs = [('whole',frame,[0,0,w,h])]
        # Exact replay preparation keeps these 720x1280 materials at this size.
        # A half-size image is an attribution experiment, not a claimed current copy.
        inputs.append(('half_pixels',cv2.resize(frame,(w//2,h//2),interpolation=cv2.INTER_AREA),[0,0,w,h]))
        for context in (.25, .5, 1.):
            x0,y0,x1,y1 = region
            dx,dy = (x1-x0)*context,(y1-y0)*context
            crop = [max(0,math.floor((x0-dx)*w)),max(0,math.floor((y0-dy)*h)),
                    min(w,math.ceil((x1+dx)*w)),min(h,math.ceil((y1+dy)*h))]
            left,top,right,bottom = crop
            inputs.append((f'context_{context}',frame[top:bottom,left:right],crop))
        for name,image,crop in inputs:
            started = time.monotonic()
            with measured_resources() as resources:
                outputs, version = _climbing_model_masks_batch([image],time.monotonic()+300,
                                                               lambda:False,reuse_model=True)
            polygons = []
            overlay = frame.copy()
            left,top,right,bottom = crop
            for mask,score in zip(*outputs[0]):
                contour = native_mask_polygon(mask, max_points=160)
                if len(contour)<3:
                    continue
                xy = np.asarray(contour).reshape(-1,2).astype(float)
                xy = xy / [image.shape[1],image.shape[0]] * [right-left,bottom-top] + [left,top]
                polygons.append({'polygon': (xy/[w,h]).tolist(),'score':score})
                cv2.polylines(overlay,[np.rint(xy).astype(np.int32)],True,(0,220,255),1)
            cv2.rectangle(overlay,(round(region[0]*w),round(region[1]*h)),
                          (round(region[2]*w),round(region[3]*h)),(255,100,0),1)
            cv2.imwrite(str(args.output / f'case-{number:02}-{name}.jpg'),overlay)
            results.append({'case':number,'source_frame':0,'input':name,'region':region,
                            'crop_xyxy_px':crop,'input_size_wh':[image.shape[1],image.shape[0]],
                            'source_sha256':before,'source_unchanged':before==digest(source),
                            'model_version':version,'seconds':round(time.monotonic()-started,3),
                            'resources':resources,'candidates':polygons,
                            'accuracy_status':'requires_visual_reference_verification'})
            (args.output/'report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(f'case {number:02} {name}: {len(polygons)} candidates, {results[-1]["seconds"]}s',flush=True)


if __name__ == '__main__':
    main()
