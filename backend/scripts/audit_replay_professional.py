"""Read-only source inventory, trial-label templates and controlled native-FPS experiments.

Uses a new isolated output directory; never opens replay databases or calls APIs.
Pose-only comparisons do not validate contact accuracy or the full three-minute target.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import cv2
from core.climb_replay import probe_video, prepare_video_upload, VideoLimits, build_pose_samples
from core.replay_sampling import native_plan
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer
from core.replay_action_features import TECHNIQUE_PROTOCOL
from core.replay_action_naming import NAMING_VERSION
from core.replay_actions import motion_intervals
from core.replay_actions import organize
from core.replay_action_features import enrich_action_features


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')


def inventory(materials, output):
    rows=[]
    for index,path in enumerate(sorted(materials.glob('*.mp4')),1):
        info=probe_video(path)
        rows.append({'attempt_id':f'dev-{index:02d}', 'filename':path.name, 'source_sha256':sha(path),
            'video':asdict(info), 'duration_seconds':info.duration_seconds, 'split':'development', 'real_video':True,
            'participant_group':None,'route_group':None,'original_video_group':None,
            'annotation_status':'pending_user_trial','events':[], 'references':[], 'predictions':[],
            'sampling_plans':{str(fps):native_plan(info,fps)[2] for fps in (4,10,15,20)}})
    write(output/'inventory.json',{'schema_version':1,'attempts':rows,'professional_accuracy':'not_evaluated'})
    write(output/'trial-labels.json',{'schema_version':1,'naming_version':NAMING_VERSION,
        'protocol_frozen':False,'independent_blind_review':False,'disagreements_resolved':False,
        'reviewers':[], 'trial_reviewer':None,'attempts':rows,'technique_protocol':TECHNIQUE_PROTOCOL,
        'event_template':{'id':None,'limbs':[],'type':None,'start_seconds':None,'end_seconds':None,
            'source_hold_id':None,'target_hold_id':None,'technique_codes':[], 'evidence_frame_ids':[],
            'decision':'unknown','occluded':None,'reviewer':None,'disagreement':None},
        'allowed_decisions':['confirmed','rejected','unknown','disputed'],
        'allowed_event_types':['reach','lift','return','same_hold_adjustment','body_move','visible_contact_change'],
        'warning':'开发试标不计为独立专业验收；分组未知时不得划分留出集。'})
    return rows


def pose_comparison(path, output, seconds):
    original=sha(path)
    prepared,info=prepare_video_upload(path,filename=path.name,content_type='video/mp4',limits=VideoLimits(),
        output=output/'analysis-720.mp4',trim_end_seconds=min(seconds,probe_video(path).duration_seconds))
    analyzer=LocalRTMWReplayAnalyzer()
    load=time.perf_counter(); analyzer._load_models(); load_seconds=time.perf_counter()-load
    results=[]
    for fps in (4,10,15,20):
        analyzer.configure_sampling({'pose_fps':fps}); analyzer._prepare_pose_run({'holds':[]})
        _,positions,plan=native_plan(info,fps)
        capture=cv2.VideoCapture(str(prepared)); records=[]; started=time.perf_counter()
        try:
            cursor=0
            for index,frame_id in enumerate(positions):
                while cursor<int(frame_id):
                    capture.grab();cursor+=1
                ok,frame=capture.read();cursor+=1
                if not ok: raise RuntimeError('Native-frame decode failed')
                record=analyzer._pose_frame(frame,frame_id=index,source_frame_id=int(frame_id))
                records.append(record or {'frame_id':index,'source_frame_id':int(frame_id),
                    'kpts_xy':[[0,0]]*17,'kpts_score':[0]*17,'bbox_xywh':[0,0,0,0]})
        finally: capture.release()
        elapsed=time.perf_counter()-started
        samples=build_pose_samples(records,info)
        # The comparison has no reviewed wall reference; do not invent registered features.
        result={'fps':fps,'sampling':plan,'elapsed_seconds':round(elapsed,3),
            'observed_frames':sum(bool(s.get('observed')) for s in samples),
            'sample_count':len(samples),'runtime':analyzer.runtime_metadata(),
            'pose_accuracy':'unscored_no_reference_labels','wall_registration':'not_run',
            'pose_samples':samples}
        write(output/f'pose-{fps}fps.json',result)
        results.append({k:v for k,v in result.items() if k!='pose_samples'})
        print(f'{fps} FPS: {len(samples)} samples, {elapsed:.2f}s',flush=True)
    write(output/'comparison.json',{'source_sha256':original,'source_unchanged':sha(path)==original,
        'prepared_video':asdict(info),'load_seconds':round(load_seconds,3),'conditions':results,
        'scope':'pose-only; no holds, registration, features or rendering; no labeled accuracy score',
        'three_minute_full_pipeline_target':'not_evaluated'})


def full_local_profile(path, output, seconds):
    """Engineering profile with declared synthetic holds, never expert ground truth."""
    from scripts.accept_replay_hold_editor import measured_resources
    original=sha(path)
    prepared,info=prepare_video_upload(path,filename=path.name,content_type='video/mp4',limits=VideoLimits(),
        output=output/'analysis-720.mp4',trim_end_seconds=min(seconds,probe_video(path).duration_seconds))
    # Fixed wall regions exercise contacts and the existing composition only.
    # They are deliberately not presented as genuine, user-confirmed holds.
    holds=[{'id':index+1,'bbox':[x,y,.07,.045], 'route_candidate':True}
        for index,(x,y) in enumerate(((.25,.8),(.55,.7),(.3,.55),(.6,.4),(.4,.25)))]
    draft={'holds':holds,'hold_candidates':[],'hold_evidence':{'reference_frame':0},
        'models':{'holds':'constructed-engineering-regions'},'route':{'color':'黄色'},'hold_review_version':0}
    analyzer=LocalRTMWReplayAnalyzer(pose_fps=10)
    stages=[]; begun=time.perf_counter()
    def progress(stage,value):
        if not stages or stages[-1]['stage']!=stage:
            stages.append({'stage':stage,'elapsed_seconds':round(time.perf_counter()-begun,3)})
            print(f'{stage} ({value}%)',flush=True)
    with measured_resources() as resources:
        result=analyzer.analyze(prepared,route_color='黄色',video_info=info,confirmed_holds=draft,
            progress=progress,cancelled=lambda:False,telemetry=lambda data:None)
        feature_start=time.perf_counter()
        organized=enrich_action_features(organize({'result':result}),{'result':result})
        result['analysis']['timings_ms']['features']=round((time.perf_counter()-feature_start)*1000)
    elapsed=time.perf_counter()-begun
    write(output/'full-result.json',result)
    write(output/'full-actions.json',organized)
    write(output/'full-profile.json',{'source_sha256':original,'source_unchanged':sha(path)==original,
        'video':asdict(info),'elapsed_seconds':round(elapsed,3),'timings_ms':result['analysis']['timings_ms'],
        'pose_sample_count':len(result.get('pose_samples',[])),
        'observed_pose_sample_count':sum(bool(s.get('observed')) for s in result.get('pose_samples',[])),
        'runtime':analyzer.runtime_metadata(),'resources':resources,'stages':stages,
        'scope':'real video, actual RTMW, registration, features and composition; synthetic wall regions',
        'accuracy':'unscored; no user or independent hold/action labels',
        'under_three_minutes_this_engineering_case':elapsed<=180,
        'three_minute_product_acceptance':'pending_user_confirmed_holds_and_representative_cases'})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pose-case',type=int)
    parser.add_argument('--full-case',type=int)
    parser.add_argument('--seconds',type=float,default=3)
    args=parser.parse_args()
    if not args.materials.is_dir() or not 0<args.seconds<=90:
        parser.error('Existing materials and 0 < seconds <= 90 required')
    args.output.mkdir(parents=True,exist_ok=False)
    rows=inventory(args.materials,args.output)
    print(f'Inventoried {len(rows)} real videos. User labels remain empty.',flush=True)
    if args.pose_case:
        path=sorted(args.materials.glob('*.mp4'))[args.pose_case-1]
        pose_comparison(path,args.output,args.seconds)
    if args.full_case:
        path=sorted(args.materials.glob('*.mp4'))[args.full_case-1]
        full_local_profile(path,args.output,args.seconds)


if __name__=='__main__': main()
