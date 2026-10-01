"""Offline Detectron2 CPU comparison. No download, live API, or silent fallback.

Run from an isolated environment containing a compiled official Detectron2 and
its dependencies. The manifest may include unannotated photos for diagnosis.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.photo_route_analysis import _write_asset, _encode_png
from core.photo_route_colors import classify_mask_color, COLOR_VERSIONS
from core.photo_route_instance_masks import encode_mask
from core.photo_route_processing import decode_photo


def peak_memory_bytes():
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        counter=Counters();counter.cb=ctypes.sizeof(counter)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL('psapi',use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counter),counter.cb):
            return int(counter.PeakWorkingSetSize)
        return None
    import resource
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform=='darwin' else value*1024)


def export_instances(image, masks, classes, scores, output, color_version, boxes=None):
    if not len(masks)==len(classes)==len(scores) or (boxes is not None and len(boxes)!=len(masks)):
        raise ValueError('实例掩膜、类别、置信度和检测框数量不一致')
    objects=[];empty=0
    for index,(mask,kind,score) in enumerate(zip(masks,classes,scores),1):
        if int(kind) not in (0,1): raise ValueError('候选类别不是约定的 hold/volume')
        if mask.shape!=image.shape[:2]: raise ValueError('候选掩膜未映射回原图')
        if not np.isfinite(score) or not 0<=score<=1: raise ValueError('候选置信度无效')
        mask=(mask>0).astype(np.uint8)*255
        x,y,w,h=cv2.boundingRect(mask)
        if not w or not h: empty+=1;continue
        cropped=mask[y:y+h,x:x+w];rgba=cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_BGR2BGRA)
        rgba[:,:,3]=cropped
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        contours=sorted(contours,key=cv2.contourArea,reverse=True)
        objects.append({'id':f'object-{index:03d}','kind':['hold','volume'][int(kind)],
            'confidence':float(score),'color_group':classify_mask_color(image,mask,version=color_version),
            'contour':contours[0][:,0].astype(int).tolist(),
            'mask_rle':encode_mask(cropped,(x,y)), 'component_count':len(contours),
            'source_bbox_px':[x,y,w,h],
            'mask':_write_asset(output,_encode_png(cropped),'png',w,h),
            'cutout':_write_asset(output,_encode_png(rgba),'png',w,h),'anchors':[]})
        if boxes is not None:
            box=np.asarray(boxes[index-1],dtype=float)
            if box.shape!=(4,) or not np.isfinite(box).all() or not (0<=box[0]<box[2]<=image.shape[1] and 0<=box[1]<box[3]<=image.shape[0]):
                raise ValueError('检测框不是有效原图坐标')
            objects[-1]['detection_bbox_xyxy']=box.tolist()
    return objects,empty


def run(manifest_path, config_path, checkpoint, output, *, threads=2, threshold=.05,
        color_version='interior-v3', hold_only=False, min_size=None, max_detections=None):
    if not 1<=threads<=16 or not 0<=threshold<=1 or color_version not in COLOR_VERSIONS:
        raise ValueError('无效实验参数')
    if min_size is not None and (not 320 <= min_size <= 1600):
        raise ValueError('测试短边必须在 320–1600 之间')
    if max_detections is not None and (not 1 <= max_detections <= 300):
        raise ValueError('单图候选上限必须在 1–300 之间')
    if not config_path.is_file() or not checkpoint.is_file(): raise ValueError('必须提供本地专项配置和权重')
    output.mkdir(parents=True,exist_ok=False)
    import torch
    import detectron2
    from detectron2.config import get_cfg
    from detectron2.modeling import build_model
    from detectron2.data.transforms import ResizeShortestEdge
    torch.set_num_threads(threads);torch.manual_seed(0);cv2.setNumThreads(1)
    cfg=get_cfg();cfg.merge_from_file(str(config_path));cfg.MODEL.DEVICE='cpu';cfg.MODEL.WEIGHTS=''
    if min_size is not None: cfg.INPUT.MIN_SIZE_TEST=min_size
    if max_detections is not None: cfg.TEST.DETECTIONS_PER_IMAGE=max_detections
    if cfg.MODEL.ROI_HEADS.NUM_CLASSES!=2 or not cfg.MODEL.MASK_ON:
        raise ValueError('配置必须是专项两类实例分割模型')
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST=threshold;cfg.freeze()
    started=time.monotonic();model=build_model(cfg)
    weights=torch.load(checkpoint,map_location='cpu',weights_only=True)
    model.load_state_dict(weights['model'],strict=True);model.eval();del weights
    load_seconds=time.monotonic()-started
    checkpoint_digest=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    config_digest=hashlib.sha256(cfg.dump().encode()).hexdigest()
    model_version=f'indoor-maskrcnn-{checkpoint_digest[:12]}-cfg-{config_digest[:12]}'
    recipe={'detector':'climbing-mask-rcnn','segmentation_model':model_version,'color_version':color_version,
        'checkpoint_sha256':checkpoint_digest,'config_sha256':config_digest,'threads':threads,
        'score_threshold':threshold,'boundary_version':'off','mask_encoding':'row-major-rle-v1',
        'min_size_test':cfg.INPUT.MIN_SIZE_TEST,'max_size_test':cfg.INPUT.MAX_SIZE_TEST,
        'detections_per_image':cfg.TEST.DETECTIONS_PER_IMAGE,
        'class_mapping':{'0':'hold'} if hold_only else {'0':'hold','1':'volume'},
        'hold_only':hold_only,'runtime':{'torch':torch.__version__,
        'detectron2':detectron2.__version__,'python':sys.version,'platform':platform.platform()}}
    (output/'effective-config.yaml').write_text(cfg.dump(),encoding='utf-8')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));rows=[]
    transform=ResizeShortestEdge([cfg.INPUT.MIN_SIZE_TEST,cfg.INPUT.MIN_SIZE_TEST],cfg.INPUT.MAX_SIZE_TEST)
    for number,sample in enumerate(manifest['samples']):
        if sample.get('split')=='holdout' or sample.get('holdout'):
            raise ValueError('候选探测脚本不允许查看留出集')
        image_path=manifest_path.parent/sample['image'];image=decode_photo(image_path.read_bytes())
        height,width=image.shape[:2];started=time.monotonic()
        resized=transform.get_transform(image).apply_image(image)
        tensor=torch.as_tensor(np.ascontiguousarray(resized.transpose(2,0,1)).astype('float32'))
        with torch.inference_mode(): instances=model([{'image':tensor,'height':height,'width':width}])[0]['instances'].to('cpu')
        inference_seconds=time.monotonic()-started
        if hold_only:
            instances=instances[instances.pred_classes==0]
        folder=output/f'sample-{number+1}'
        objects,empty=export_instances(image,instances.pred_masks.numpy(),instances.pred_classes.numpy(),
                                      instances.scores.numpy(),folder,color_version,instances.pred_boxes.tensor.numpy())
        result={'objects':objects,'model_version':model_version,'processing_config':recipe,
            'input_fingerprint':hashlib.sha256(image_path.read_bytes()).hexdigest(),
            'empty_mask_predictions':empty,'width':width,'height':height}
        folder.mkdir(exist_ok=True)
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        row={'sample':sample['image'],'prediction':f'sample-{number+1}/result.json',
            'objects':len(objects),'inference_seconds':inference_seconds,'total_seconds':time.monotonic()-started,
            'load_seconds':load_seconds if number==0 else 0,'model_reused':number>0,
            'peak_process_memory_bytes':peak_memory_bytes()}
        rows.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        (output/'run-report.json').write_text(json.dumps({'recipe':recipe,'load_seconds':load_seconds,'runs':rows},indent=2),encoding='utf-8')
        del instances
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','config','checkpoint','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--threads',type=int,default=2);parser.add_argument('--threshold',type=float,default=.05)
    parser.add_argument('--color-version',choices=COLOR_VERSIONS,default='interior-v3')
    parser.add_argument('--hold-only',action='store_true')
    parser.add_argument('--min-size',type=int)
    parser.add_argument('--max-detections',type=int)
    args=parser.parse_args()
    run(args.manifest,args.config,args.checkpoint,args.output,threads=args.threads,threshold=args.threshold,
        color_version=args.color_version,hold_only=args.hold_only,
        min_size=args.min_size,max_detections=args.max_detections)


if __name__=='__main__':main()
