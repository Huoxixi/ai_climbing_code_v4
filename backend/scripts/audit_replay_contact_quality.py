"""Frozen real observations, manual diagnostic maps, shared L/F comparisons."""
import argparse
import copy
import json
from pathlib import Path
import time
import cv2
import numpy as np
from core.climb_replay import AliyunReplayAnalyzer
from core.replay_hold_fusion import align_to_reference, align_pose_record
from scripts.accept_replay_hold_editor import digest, measured_resources

def hold(name,box):
    x,y,w,h=box
    return {'id':name,'bbox':[x/720,y/1280,w/720,h/1280],
            'polygon':[[x/720,y/1280],[(x+w)/720,y/1280],[(x+w)/720,(y+h)/1280],[x/720,(y+h)/1280]]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    output=args.output.resolve()
    if not output.is_relative_to(project/'.tmp'): raise ValueError('Private .tmp output required')
    output.mkdir(exist_ok=False,parents=True)
    source=next(args.materials.glob('09_*.mp4'))
    initial_hash=digest(source)
    raw=json.loads((project/'.tmp/quality-s0-20261011/case-09/records.json').read_text(encoding='utf-8'))
    cap=cv2.VideoCapture(str(source))
    report={'source_sha256':initial_hash,'reference_kind':'manual_visible_anchor_only_not_event_ground_truth',
            'cases':[], 'policies_are_offline_only':True}
    map_report=json.loads((project/'.tmp/quality-h0-20261011/case-09/report.json').read_text(encoding='utf-8'))
    map_rows=json.loads((project/'.tmp/quality-h0-20261011/geometry-comparison.json').read_text(encoding='utf-8'))
    model_holds=next(row['selected'] for row in map_rows if row['case']==9 and row['geometry']=='bbox')
    model_holds=[{**h,'id':h['candidate_id']} for h in model_holds]
    cap.set(cv2.CAP_PROP_POS_FRAMES,map_report['diagnostics']['reference_frame']);ok,model_reference=cap.read()
    if not ok: raise RuntimeError('Model map reference decode failed')
    start=time.perf_counter()
    policies={'L1_F1_baseline':{},'L3_fingers_toes':{'contact_part':'wholebody'},
              'L4_short':{'duration':0},'F2_score_05':{'minimum_score':.5},
              'F3_no_offset':{'foot_offset':0},'F3_strict':{'margin':0,'foot_offset':0,'reject_ambiguous':True}}
    anchors=[(120,[hold('lower_yellow',[478,651,55,90])],{'left_hand':'lower_yellow'}),
             (264,[hold('left_hand_yellow',[358,466,43,34]),hold('right_hand_yellow',[445,466,48,45]),
                   hold('large_yellow_foot',[162,675,110,127])],
              {'left_hand':'left_hand_yellow','right_hand':'right_hand_yellow','left_foot':'large_yellow_foot'})]
    with measured_resources() as resources:
        for anchor,holds,visible in anchors:
            cap.set(cv2.CAP_PROP_POS_FRAMES,anchor); ok,reference=cap.read()
            if not ok: raise RuntimeError('Reference decode failed')
            records=[]
            model_records=[]
            for record in raw:
                frame=record['source_frame_id']
                if abs(frame-anchor)>21: continue
                cap.set(cv2.CAP_PROP_POS_FRAMES,frame); ok,image=cap.read()
                if not ok: raise RuntimeError('Source decode failed')
                matrix=np.eye(3) if frame==anchor else align_to_reference(image,reference)[0]
                records.append(align_pose_record(record,matrix,720,1280))
                model_matrix=align_to_reference(image,model_reference)[0]
                model_records.append(align_pose_record(record,model_matrix,720,1280))
            case={'anchor':anchor,'visible_positive_limbs':visible,'manual_map':holds,'variants':{}}
            model_trace=[]
            model_attempt=AliyunReplayAnalyzer._contacts(model_records,model_holds,10,source_fps=30,trace=model_trace)
            case['L0_preset_auto_map_not_user_confirmed_route']={'reference_frame':map_report['diagnostics']['reference_frame'],
                'holds':model_holds,'contacts':model_attempt['contacts'],
                'anchor_trace':[r for r in model_trace if r.get('source_frame')==anchor]}
            for name,policy in policies.items():
                trace=[]
                attempt=AliyunReplayAnalyzer._contacts(records,holds,10,source_fps=30,trace=trace,diagnostic_policy=policy)
                indices={r['frame_id']:r['source_frame_id'] for r in records}
                at_anchor={c['limb']:c['hold_id'] for c in attempt['contacts']
                           if indices[c['start_frame']]<=anchor<=indices[c['end_frame']]}
                rows=[r for r in trace if r.get('source_frame')==anchor]
                case['variants'][name]={'anchor_events':at_anchor,'anchor_trace':rows,'contacts':attempt['contacts'],
                    'visible_positive_misses':[limb for limb,target in visible.items() if at_anchor.get(limb)!=target]}
                (output/f'{anchor}-{name}-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
            # Correct one visible wrist only, without manufacturing a temporal sequence.
            if anchor==264:
                corrected=copy.deepcopy(records)
                next(r for r in corrected if r['source_frame_id']==anchor)['kpts_xy'][10]=[474/720,504/1280]
                for duration in (.4,0):
                    trace=[]
                    attempt=AliyunReplayAnalyzer._contacts(corrected,holds,10,source_fps=30,trace=trace,
                                                           diagnostic_policy={'duration':duration,'margin':0})
                    case[f'L2_single_visible_wrist_duration_{duration}']={'contacts':attempt['contacts'],
                        'anchor_trace':[r for r in trace if r.get('source_frame')==anchor]}
            for item in holds:
                polygon=np.rint(np.asarray(item['polygon'])*[720,1280]).astype(np.int32)
                cv2.polylines(reference,[polygon],True,(0,255,0),2)
            cv2.imwrite(str(output/f'anchor-{anchor}-manual-map.jpg'),reference)
            report['cases'].append(case)
    cap.release()
    report.update(seconds=round(time.perf_counter()-start,3),resources=resources,source_unchanged=digest(source)==initial_hash)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'seconds':report['seconds'],'source_unchanged':report['source_unchanged'],
        'cases':[{ 'anchor':c['anchor'],'misses':{k:v['visible_positive_misses'] for k,v in c['variants'].items()}}
                 for c in report['cases']]},ensure_ascii=False))

if __name__=='__main__': main()
