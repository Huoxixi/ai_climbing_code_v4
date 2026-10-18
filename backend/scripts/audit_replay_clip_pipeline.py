"""Run the actual default analyzer, encode replay and export in a private folder."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2

from core.climb_replay import probe_video
from core.replay_pose_clip import LocalClipReplayAnalyzer
from core.replay_export import build_bundle


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--cache-from',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    if not args.output.resolve().is_relative_to(project/'.tmp'):raise ValueError('Private output required')
    args.output.mkdir(parents=True,exist_ok=False)
    sha=digest(args.video)
    saved=json.loads((args.cache_from/'raw-cache.json').read_text('utf-8'))
    if saved['binding'].get('source_sha256')!=sha:raise ValueError('Native source cache mismatch')
    info=probe_video(args.video)
    analyzer=LocalClipReplayAnalyzer(device='cpu')
    analyzer.configure_cache(args.output/'raw-cache.json',{'source_sha256':sha})
    analyzer._pose_cache=saved['frames']
    def progress(stage,value):
        if progress.previous!=(stage,value):
            print(stage,value,flush=True)
            progress.previous=stage,value
    progress.previous=None
    result=analyzer.analyze(args.video,route_color='',video_info=info,
        confirmed_holds={'holds':[],'hold_candidates':[],'skeleton_only':True,
            'hold_evidence':{'reference_frame':0},'models':{'holds':'not_requested'}},
        overlay_target=args.output/'replay.webm',progress=progress,cancelled=lambda:False,telemetry=lambda *_:None)
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    from core.replay_analysis_view import visual_evidence
    (args.output/'display.json').write_text(json.dumps(visual_evidence(result),indent=2,allow_nan=False),'utf-8')
    # Export data and the generated replay. The input remains read-only at its
    # source location; this diagnostic does not copy or upload the original.
    with build_bundle(result,mapping={'basis':'source_video','source_fps':info.fps},
                      video_path=args.output/'replay.webm') as bundle:
        with (args.output/'export.zip').open('wb') as output:shutil.copyfileobj(bundle,output)
    encoded=probe_video(args.output/'replay.webm')
    reader=cv2.VideoCapture(str(args.output/'replay.webm'))
    decoded=0
    while reader.grab():decoded+=1
    reader.release()
    checks={'source_sha256':sha,'source_unchanged':sha==digest(args.video),
            'target':result['track_id'],'source_sample_count':len(result['pose_samples']),
            'all_source_sample_ids_present':len(result['pose_samples'])==result['analysis']['usage']['planned_frames'],
            'encoded_frames':encoded.frame_count,'decoded_frames':decoded,'source_frames':info.frame_count,
            'source_duration_seconds':info.duration_seconds,'encoded_duration_seconds':encoded.duration_seconds,
            'paid_requests':result['analysis']['usage']['actual_requests'],
            'scope':'full local execution and export integrity; anatomical quality not certified'}
    (args.output/'checks.json').write_text(json.dumps(checks,indent=2),'utf-8')
    print(json.dumps(checks),flush=True)


if __name__=='__main__':main()
