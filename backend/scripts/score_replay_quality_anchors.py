"""Score frozen coarse visible anchors; never treat them as full event truth."""
import argparse
import json
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    if not args.output.resolve().is_relative_to(project/'.tmp'):
        raise ValueError('Private .tmp output required')
    frozen=json.loads((project/'backend/experiments/frozen-quality-20261011.json').read_text('utf-8'))
    results=[]
    limbs={'left_hand':9,'right_hand':10,'left_foot':15,'right_foot':16}
    for case in ('02','09'):
        folder=args.input/f'case-{case}'
        report=json.loads((folder/'report.json').read_text('utf-8'))
        if report['source_sha256'] != frozen['sources'][case]:
            raise ValueError('Source variant differs from the frozen reference')
        rows={row['source_frame_id']:row for row in json.loads((folder/'records.json').read_text('utf-8'))}
        size=[report['video']['width'],report['video']['height']]
        for reference in (r for r in frozen['references'] if r['case']==case):
            record=rows.get(reference['source_frame']) or {}
            xy=np.asarray(record.get('kpts_xy') or [],float)
            scores=np.asarray(record.get('kpts_score') or [],float)
            def point(joint):
                flags=record.get('joint_eligibility')
                eligible=(len(flags)==17 and all(isinstance(v,bool) for v in flags) and flags[joint] and scores.shape==(17,) and scores[joint]>0) if flags is not None else scores.shape==(17,) and .5<=scores[joint]<=1
                if xy.shape!=(17,2) or scores.shape!=(17,) or not np.isfinite(xy[joint]).all() or not eligible:
                    return None
                return xy[joint]*size
            def inside(value,box):
                return None if value is None else bool(box[0]<=value[0]<=box[2] and box[1]<=value[1]<=box[3])
            checks={}
            if reference['kind']=='identity':
                torso=[point(j) for j in (5,6,11,12)]
                center=None if any(p is None for p in torso) else np.mean(torso,axis=0)
                checks['target_torso_region']=inside(center,reference['expected_torso_region_xyxy'])
            elif reference['kind']=='coarse_body_parts':
                checks={str(j):inside(point(j),reference['wrist_region_xyxy' if j<11 else 'ankle_region_xyxy']) for j in (9,10,15,16)}
            else:
                for limb,hold in reference['positives'].items():
                    x,y,w,h=reference['hold_boxes_xywh'][hold]
                    checks[limb+'_visible_positive']=inside(point(limbs[limb]),[x,y,x+w,y+h])
                for limb,hold in reference.get('negatives',{}).items():
                    x,y,w,h=reference['hold_boxes_xywh'][hold]
                    value=inside(point(limbs[limb]),[x,y,x+w,y+h])
                    checks[limb+'_avoids_wrong_hold']=None if value is None else not value
            results.append({'case':case,'source_frame':reference['source_frame'],'checks':checks})
    values=[v for r in results for v in r['checks'].values()]
    output={'reference_version':frozen['version'],'scope':'coarse visible anchor agreement; no PCK or event precision/recall',
            'agreed':sum(v is True for v in values),'disagreed':sum(v is False for v in values),
            'unknown':sum(v is None for v in values),'rows':results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='rows'}))


if __name__=='__main__':
    main()
