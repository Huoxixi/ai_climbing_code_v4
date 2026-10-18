"""Export explicitly authored AI visual labels; never promote them to truth."""
import argparse,csv,hashlib,json,shutil
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tasks',type=Path,required=True)
    parser.add_argument('--decisions',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();project=Path(__file__).resolve().parents[2]
    root=(project/'.tmp').resolve()
    if not all(p.resolve().is_relative_to(root) for p in (args.tasks,args.decisions,args.output)):
        raise ValueError('Private development reference paths required')
    if args.output.resolve()==args.tasks.parent.resolve() or args.tasks.resolve().is_relative_to(args.output.resolve()):
        raise ValueError('AI drafts must not overwrite the original blank reference set')
    blank=json.loads(args.tasks.read_text('utf8'));decisions=json.loads(args.decisions.read_text('utf8'))
    assert decisions['independent_human_review'] is False
    data=json.loads(json.dumps(blank));dest=args.output;dest.mkdir(parents=True,exist_ok=True)
    table={};expected={(t['case'],t['source_frame_id']) for t in blank['tasks']}
    for case,entry in decisions['cases'].items():
        for frame,left,right in entry['rows']:
            key=(case,frame)
            if key in table:raise ValueError('Duplicate explicit visual decision')
            table[key]=(entry,[left,right])
    if set(table)!=expected:raise ValueError('Every declared source frame requires an explicit decision')
    counts=Counter();rows=[];image_hashes=[]
    for task in data['tasks']:
        entry,points=table[(task['case'],task['source_frame_id'])]
        path=args.tasks.parent/task['image']
        image=Image.open(path).convert('RGB')
        if list(image.size)!=task['size_wh']:raise ValueError('Original image dimensions changed')
        image_hashes.append({'case':task['case'],'frame':task['source_frame_id'],
            'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_sha256':task['source_sha256']})
        task.update(annotation_status='ai_initial_wrist_only_requires_review',reviewer=decisions['annotator'],reviewed_by=None,
            annotation_provenance={'method':'multimodal_direct_original_image_review','prior_failure_context_known':True,
                'pipeline_pose_coordinates_used_as_labels':False,'independent_human_review':False,
                'reference_status':'AI_initial_development_only','source_frame_id':task['source_frame_id']})
        for index,side in enumerate(('left','right')):
            point=points[index];override=entry.get('overrides',{}).get(f'{task["source_frame_id"]}:{side}',{})
            visibility=override.get('visibility','visible' if point is not None else 'occluded')
            radius=override.get('radius_px',entry['radius_px'][index]) if point is not None else None
            if point is not None:
                if visibility!='visible' or radius is None or not (0<=point[0]<image.width and 0<=point[1]<image.height):
                    raise ValueError('Inconsistent visible source-pixel wrist label')
            elif visibility=='visible':raise ValueError('Visible point without location')
            label={'xy_px':point,'visibility':visibility,'localization_status':'visual_approximation' if point else override.get('reason','occluded_no_position_inferred'),
                'visual_radius_px':radius,'radius_semantics':'annotator_judgement_not_calibrated_interval',
                'side_status':'anatomical_side_visually_assigned_AI_not_independently_verified',
                'label_source':'AI_direct_visual_annotation','human_reviewed':False,
                'allowed_use':'development_diagnostic_pending_review',
                'independent_evaluation_eligible':False,'note':entry['notes'][index]}
            task['joints'][side+'_wrist']=label
            counts[visibility]+=1
            rows.append({'case':task['case'],'source_frame_id':task['source_frame_id'],'time_seconds':task['time_seconds'],
                'side':side,'x_px':point[0] if point else '', 'y_px':point[1] if point else '',
                'visibility':visibility,'visual_radius_px':radius if radius is not None else '',
                'allowed_use':label['allowed_use'],'label_source':label['label_source'],
                'human_reviewed':False,'independent_evaluation_eligible':False,
                'source_sha256':task['source_sha256'],'note':label['note']})
        hand_box=entry.get('right_visible_hand_boxes',{}).get(str(task['source_frame_id']))
        if hand_box:
            task['hand_regions']['right'].update(visible_hand_box_xyxy_px=hand_box,
                visibility='partially_visible',side_verified=None,
                note='AI框出的可见手部，仅为手部图像证据；不是腕点、分割轮廓或接触真值。')
            counts['visible_hand_boxes_wrist_occluded']+=1
        # Independent review copy; blank tasks and PNGs remain unchanged.
        shutil.copy2(path,dest/task['image'])
    data['definition']={**data['definition'],'reference_status':'AI_initial_wrist_only_not_independent_truth',
        'scope':'Original development clips; AI visual initial labels explicitly requested by user; not human truth or independent holdout'}
    data['ai_label_metadata']={k:v for k,v in decisions.items() if k!='cases'}
    encoded=json.dumps(data,ensure_ascii=False,indent=2)
    (dest/'annotation-tasks.json').write_text(encoded,'utf8')
    with (dest/'wrist-labels.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    receipt={'frames_reviewed':len(data['tasks']),'wrist_status_entries':len(rows),**counts,
        'human_reviewed_frames':0,'independent_evaluation_eligible':False,
        'case_counts':{case:dict(Counter(row['visibility'] for row in rows if row['case']==case)) for case in sorted(decisions['cases'])},
        'blank_tasks_sha256':hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
        'decisions_sha256':hashlib.sha256(args.decisions.read_bytes()).hexdigest(),
        'source_images':image_hashes,'annotation_sha256':hashlib.sha256(encoded.encode('utf8')).hexdigest()}
    (dest/'label-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='source_images'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
