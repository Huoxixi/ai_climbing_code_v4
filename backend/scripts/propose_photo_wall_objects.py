"""Propose local scene segments for removal review; no semantic labels are inferred."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from core.photo_route_processing import decode_photo, PhotoProcessingError
from scripts.benchmark_photo_routes import save_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mobile-sam-repo', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output directory')
    started=time.monotonic()
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    sys.path.insert(0,str(args.mobile_sam_repo.resolve()))
    import torch
    from mobile_sam import SamAutomaticMaskGenerator, sam_model_registry
    torch.set_num_threads(2)
    torch.manual_seed(0)
    cv2.setNumThreads(1)
    source=args.image.read_bytes()
    full=decode_photo(source)
    height,width=full.shape[:2]
    ratio=min(1,1280/max(height,width))
    work=cv2.resize(full,(round(width*ratio),round(height*ratio)))
    model=sam_model_registry['vit_t']()
    model.load_state_dict(torch.load(args.checkpoint,map_location='cpu',weights_only=True))
    model.eval()

    class Generator(SamAutomaticMaskGenerator):
        def _process_batch(self,*a,**kw):
            if time.monotonic()-started>175:
                raise PhotoProcessingError('Scene proposal stage exceeded its time budget')
            return super()._process_batch(*a,**kw)

    generator=Generator(model,points_per_side=24,points_per_batch=2,pred_iou_thresh=.82,
                        stability_score_thresh=.9,box_nms_thresh=.7,min_mask_region_area=40)
    with torch.inference_mode():
        proposals=generator.generate(cv2.cvtColor(work,cv2.COLOR_BGR2RGB))
    proposals.sort(key=lambda p:(p['bbox'][1],p['bbox'][0]))
    args.output.mkdir(parents=True,exist_ok=False)
    objects=[]
    tiles=[]
    overlay=full.copy()
    for proposal in proposals:
        if not 100 <= proposal['area'] <= work.shape[0]*work.shape[1]*.7:
            continue
        index=len(objects)+1
        mask=cv2.resize(proposal['segmentation'].astype(np.uint8)*255,(width,height),interpolation=cv2.INTER_NEAREST)
        x,y,w,h=cv2.boundingRect(mask)
        if not w or not h:continue
        name=f'scene-{index:03d}'
        save_image(args.output/f'{name}-mask.png',mask)
        crop=full[y:y+h,x:x+w].copy()
        crop[mask[y:y+h,x:x+w]==0]=242
        scale=min(180/w,180/h)
        thumbnail=cv2.resize(crop,(max(1,round(w*scale)),max(1,round(h*scale))))
        tile=np.full((216,200,3),242,np.uint8)
        th,tw=thumbnail.shape[:2]
        tile[30:30+th,(200-tw)//2:(200-tw)//2+tw]=thumbnail
        cv2.putText(tile,f'{index} ({proposal["predicted_iou"]:.2f})',(8,20),0,.55,(0,0,0),1)
        tiles.append(tile)
        cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,200,80),1)
        cv2.putText(overlay,str(index),(x,y+20),0,.55,(0,0,255),2)
        objects.append({'id':name,'bbox':[x,y,w,h],'area':int(np.count_nonzero(mask)),
                        'mask_sha256':hashlib.sha256((args.output/f'{name}-mask.png').read_bytes()).hexdigest(),
                        'predicted_iou':proposal['predicted_iou']})
    for page in range(0,len(tiles),30):
        group=tiles[page:page+30]
        while len(group)%6:group.append(np.full_like(group[0],255))
        sheet=np.concatenate([np.concatenate(group[i:i+6],axis=1) for i in range(0,len(group),6)],axis=0)
        save_image(args.output/f'catalog-{page//30+1}.jpg',sheet)
    save_image(args.output/'overlay.jpg',overlay)
    report={'source_sha256':hashlib.sha256(source).hexdigest(),'source_dimensions':[width,height],
            'working_dimensions':[work.shape[1],work.shape[0]],'objects':objects,
            'model_sha256':hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
            'algorithm':'mobilesam-scene-proposals-v1','elapsed_seconds':round(time.monotonic()-started,3),
            'review_required':True,'note':'Segments may include wall, signs and people; no semantic removal decision is made'}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'count':len(objects),'elapsed_seconds':report['elapsed_seconds']}),flush=True)


if __name__=='__main__':main()
