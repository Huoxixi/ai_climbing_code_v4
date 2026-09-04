"""Build a separate repaired wall and original-pixel route composite from reviewed masks."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from core.photo_route_processing import decode_photo
from core.photo_wall_processing import restore_wall
from scripts.benchmark_photo_routes import save_image
from scripts.evaluate_photo_routes import result_fingerprint


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_mask(folder, item, shape):
    path=folder/f'{item["id"]}-mask.png'
    if file_hash(path)!=item['mask_sha256']:
        raise ValueError('Saved mask changed after review')
    mask=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE)
    if mask is None or mask.shape!=shape:
        raise ValueError('Reviewed mask dimensions differ from the source')
    return mask


def reviewed_masks(image, source_sha, route_folder, scene_folder, review):
    route=json.loads((route_folder/'report.json').read_text('utf-8'))
    scene=json.loads((scene_folder/'report.json').read_text('utf-8'))
    if not source_sha==route['source_sha256']==scene['source_sha256']==review['source_sha256']:
        raise ValueError('Review, route and scene must refer to the same original photo')
    if (review['route_result_sha256']!=result_fingerprint(route)
            or review['scene_report_sha256']!=file_hash(scene_folder/'report.json')):
        raise ValueError('Review no longer matches extraction results')
    masks=[]
    for folder,report,key in [(route_folder,route,'target_ids'),(scene_folder,scene,'remove_ids')]:
        selected=review[key]
        if len(set(selected))!=len(selected):
            raise ValueError('Duplicate reviewed object IDs')
        objects={item['id']:item for item in report['objects']}
        if not set(selected)<=objects.keys():
            raise ValueError('Review contains unknown objects')
        mask=np.zeros(image.shape[:2],np.uint8)
        for object_id in selected:
            mask|=read_mask(folder,objects[object_id],image.shape[:2])
        masks.append(mask)
    target,removal=masks
    for polygon in review.get('extra_removal_polygons',[]):
        points=np.asarray(polygon['points'],dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or not np.isfinite(points).all() or np.any((points<0)|(points>1)):
            raise ValueError('Manual removal polygon must use normalized image coordinates')
        pixels=np.rint(points*np.array([image.shape[1]-1,image.shape[0]-1])).astype(np.int32)
        cv2.fillPoly(removal,[pixels],255)
    preserve=np.zeros(image.shape[:2],np.uint8)
    scene_objects={item['id']:item for item in scene['objects']}
    for object_id in review.get('preserve_scene_ids',[]):
        if object_id not in scene_objects:raise ValueError('Unknown preserved scene object')
        preserve|=read_mask(scene_folder,scene_objects[object_id],image.shape[:2])
    return target,removal,preserve


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--route-evidence',type=Path,required=True)
    parser.add_argument('--scene-evidence',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--method',choices=['opencv','lama'],default='opencv')
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--margin',type=int,default=8)
    parser.add_argument('--working-edge',type=int,default=768)
    args=parser.parse_args()
    if args.output.exists():parser.error('Use a new output directory')
    start=time.monotonic()
    cv2.setNumThreads(1)
    data=args.image.read_bytes()
    source_sha=hashlib.sha256(data).hexdigest()
    image=decode_photo(data)
    review=json.loads(args.review.read_text('utf-8'))
    target,removal,preserve=reviewed_masks(image,source_sha,args.route_evidence,args.scene_evidence,review)
    result=restore_wall(image,removal,target,method=args.method,checkpoint=args.checkpoint,
                        margin=args.margin,working_edge=args.working_edge,preserve_mask=preserve)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,value in [('background',result.background),('composite',result.composite),
                       ('repair-mask',result.repair_mask),('display-repair-mask',result.display_repair_mask),
                       ('target-mask',target),('removal-mask',removal),('preserve-mask',preserve)]:
        save_image(args.output/f'{name}.png',value)
    overlay=image.copy()
    red=np.zeros_like(image);red[:]=(30,30,240)
    affected=(removal>0)&(target==0)
    overlay[affected]=cv2.addWeighted(image,.5,red,.5,0)[affected]
    contours,_=cv2.findContours(target,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay,contours,-1,(40,220,40),2)
    save_image(args.output/'removal-preview.jpg',overlay)
    report={'source_sha256':source_sha,'algorithm':f'local-wall-{args.method}-v1',
            'model_sha256':file_hash(args.checkpoint) if args.method=='lama' else None,
            'review_sha256':file_hash(args.review),'reviewer':review['reviewer'],
            'human_confirmed':review.get('human_confirmed',False),'status':'needs_visual_review',
            'selected_target_count':len(review['target_ids']),'removal_proposal_count':len(review['remove_ids']),
            'manual_polygon_count':len(review.get('extra_removal_polygons',[])),
            'source_dimensions':[image.shape[1],image.shape[0]],'working_edge':args.working_edge,'margin':args.margin,
            'repair_fraction':round(float(np.mean(result.repair_mask>0)),4),
            'target_changed_pixels':int(np.count_nonzero(np.any(result.composite!=image,axis=2)&(target>0))),
            'unmasked_changed_pixels':int(np.count_nonzero(np.any(result.composite!=image,axis=2)&(result.repair_mask==0))),
            'elapsed_seconds':round(time.monotonic()-start,3),
            'note':'Repair is synthetic wall appearance; hidden holes, seams and texture are not observed measurements. Original and target pixels are preserved.'}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
