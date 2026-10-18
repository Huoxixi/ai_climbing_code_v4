"""Recheck isolated real-video pose captures; never reads private job storage."""
import importlib.util
import json
from pathlib import Path
from core.climb_replay import probe_video, align_to_reference
import cv2
from core.replay_action_segmentation import displacement_bouts


def run(project, previous_package, output):
    spec = importlib.util.spec_from_file_location('core.replay_action_segmentation_previous',
        previous_package / 'backend/core/replay_action_segmentation.py')
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    captures = project / '.tmp/tracking-repair-20261008'
    full = json.loads((captures / 'full-v010-verified/full-result.json').read_text('utf-8'))
    cases = [('v010', full)]
    for name in ('1', '10'):
        video = captures / f'additional/case-{name}-720.mp4'
        info = probe_video(video)
        samples = json.loads((captures / f'additional/case-{name}-verified/pose-samples.json').read_text('utf-8'))
        capture = cv2.VideoCapture(str(video))
        ok, reference = capture.read()
        if not ok:
            raise RuntimeError('Cannot decode reference')
        try:
            for sample in samples:
                capture.set(cv2.CAP_PROP_POS_FRAMES, sample['source_frame_id'])
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError('Cannot decode observed source frame')
                matrix, diagnostics = align_to_reference(frame, reference)
                sample.update(wall_alignment='aligned' if matrix is not None else 'unknown',
                    wall_reference_transform=matrix.tolist() if matrix is not None else None,
                    wall_alignment_diagnostics=diagnostics)
        finally:
            capture.release()
        (output.parent / f'registered-case-{name}.json').write_text(json.dumps({'video':{'width':info.width,'height':info.height,
            'fps':info.fps,'duration_seconds':info.duration_seconds,'frame_count':info.frame_count},'pose_samples':samples},allow_nan=False),'utf-8')
        cases.append((f'case-{name}', {'video': {'width':info.width,'height':info.height,
            'fps':info.fps,'duration_seconds':info.duration_seconds,'frame_count':info.frame_count},
            'pose_samples':samples}))
    rows = []
    for name,result in cases:
        def windows(fn):
            return [{**row,'limbs':sorted(row['limbs'])} for row in fn(result)]
        old, new = windows(previous.displacement_bouts), windows(displacement_bouts)
        rows.append({'case':name,'duration_seconds':result['video']['duration_seconds'],
            'pose_count':len(result['pose_samples']), 'previous':old,'current':new,
            'manual_boundary_reference':None,
            'scope':'Cached native model poses from real videos. Constructed holds; no professional accuracy claim.'})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
    print(json.dumps([{'case':r['case'],'old_count':len(r['previous']),'new_count':len(r['current']),
        'new_windows':[(w['start'],w['end'],w['settled']) for w in r['current']]} for r in rows],ensure_ascii=False))


if __name__=='__main__':
    import sys
    run(*(Path(arg) for arg in sys.argv[1:]))
