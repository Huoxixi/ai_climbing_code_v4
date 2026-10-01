"""Render authorized existing replay samples without cloud calls or reanalysis.

Run from backend: python scripts/preview_fine_actions.py --output DIR
  --case NAME ACTIONS_JSON BASE_VIDEO [--case ...]
All outputs must be new. Existing files and source videos are never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.replay_action_naming import enrich_names, caption_entries
from core.replay_action_renderer import make_plan, render_actions, ActionComposition, validate


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append', nargs=3, metavar=('NAME', 'RESULT', 'BASE'), required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output directory')
    cases = [(name, Path(result), Path(base)) for name, result, base in args.case]
    if len({name for name, _, _ in cases}) != len(cases) or any(not re.fullmatch(r'[a-z0-9-]+', name) for name, _, _ in cases):
        raise ValueError('Case names must be unique lowercase identifiers')
    if any(not p.is_file() for _, result, base in cases for p in (result, base)):
        raise ValueError('A sample input is unavailable')
    args.output.mkdir(parents=True)
    records = []
    for name, input_result, source in cases:
        started = time.monotonic()
        before = sha256(source)
        old = json.loads(input_result.read_text(encoding='utf-8'))
        result = enrich_names(old)
        cap = cv2.VideoCapture(str(source))
        video = {'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                 'fps': cap.get(cv2.CAP_PROP_FPS), 'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
        cap.release()
        plan = make_plan(result, base_video=video)
        output = args.output / (name + '-fine-actions.mp4')
        metrics = render_actions(source, plan, output)
        cap = cv2.VideoCapture(str(output)); decoded = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            decoded += 1
        cap.release()
        assert decoded == validate(plan), (name, decoded, validate(plan))
        assert sha256(source) == before, 'Base video changed'
        rows = [{'group_id': new['id'], 'old_description': prior.get('description'), 'new_description': new.get('description'),
                 'events': [{'id': e['id'], 'limb': e['limb'], 'action': e['action'], 'name': e['display_name'],
                             'start_seconds': e['start_seconds'], 'end_seconds': e['end_seconds'],
                             'contact_fact_count': len(e['facts']), 'technique_tags': e['technique_tags'],
                             'status': e['event_status']} for e in new.get('events', [])]}
                for prior, new in zip(old['groups'], result['groups'])]
        composition = ActionComposition(plan, source)
        try:
            at = next((e['start_seconds'] + min(.2, (e['end_seconds']-e['start_seconds'])/2)
                       for g in result['groups'] for e in g['events'] if caption_entries(result['groups'], e['start_seconds']+.01)), 0)
            composition.commentary(composition.raw(at), at).save(args.output / (name + '-action.png'))
            last = composition.raw((video['frame_count']-1)/video['fps'])
            composition.summary_frame(last, plan['summary_seconds']-6.5).save(args.output / (name + '-data.png'))
            composition.summary_frame(last, plan['summary_seconds']-1).save(args.output / (name + '-rhythm.png'))
        finally:
            composition.video.close()
        for suffix, payload in [('actions', result), ('plan', plan), ('comparison', rows)]:
            (args.output / (name + '-' + suffix + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        records.append({'case': name, 'source_sha256': before, 'source_video': video, 'base_unchanged': True,
                        'decoded_frames': decoded, 'expected_frames': validate(plan), 'render_resources': metrics,
                        'wall_seconds_including_decode': round(time.monotonic()-started, 3),
                        'cloud_calls': 0, 'new_model_inference': False, 'validation': 'development_display_regression_only'})
        print(name + ': base preserved; decoded ' + str(decoded) + ' frames', flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
