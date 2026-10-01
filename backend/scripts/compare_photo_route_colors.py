"""Compare color rules on identical saved masks, without rerunning segmentation.

Manifest: samples[{result, assets, labels: {object-id: human color}}]. Labels
may be partial; unlabeled changes are always reported separately for review.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.photo_route_colors import COLOR_VERSIONS, classify_mask_color


def compare(path):
    path=Path(path);manifest=json.loads(path.read_text(encoding='utf-8'));rows=[]
    for index,sample in enumerate(manifest['samples']):
        result_path=path.parent/sample['result']
        result=json.loads(result_path.read_text(encoding='utf-8'))
        for obj in result['objects']:
            asset=path.parent/sample['assets']/obj['cutout']['filename']
            data=asset.read_bytes()
            if hashlib.sha256(data).hexdigest()!=obj['cutout']['sha256']:
                raise ValueError('固定轮廓素材摘要不符')
            rgba=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_UNCHANGED)
            if rgba is None or rgba.ndim!=3 or rgba.shape[2]!=4:
                raise ValueError('颜色实验需要保存的 RGBA 原始抠图')
            predictions={v:classify_mask_color(rgba[:,:,:3],rgba[:,:,3],version=v) for v in COLOR_VERSIONS}
            rows.append({'sample':index,'id':obj['id'],'expected':sample.get('labels',{}).get(obj['id']),
                         'saved_color':obj['color_group'],'predictions':predictions,
                         'asset_sha256':obj['cutout']['sha256']})
    metrics={}
    for version in COLOR_VERSIONS:
        confusion={};counts=Counter()
        for row in rows:
            truth=row['expected'];prediction=row['predictions'][version]
            if truth is None: continue
            confusion.setdefault(truth,Counter())[prediction]+=1
            counts['labeled']+=1
            counts['correct' if truth==prediction else 'pending' if prediction=='待确认' else 'wrong']+=1
        denominator=counts['labeled']
        metrics[version]={'counts':dict(counts),'confusion':{c:dict(v) for c,v in confusion.items()},
            **{key+'_rate':counts[key]/denominator if denominator else None for key in ['correct','pending','wrong']}}
    return {'formal_acceptance':False,'human_reviewed':manifest.get('human_reviewed',False),
            'scope':'fixed cached masks; partial color labels; no detection accuracy claim',
            'metrics':metrics,'rows':rows,
            'unlabeled_changes':[r for r in rows if r['expected'] is None and len(set(r['predictions'].values()))>1]}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=compare(args.manifest);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
