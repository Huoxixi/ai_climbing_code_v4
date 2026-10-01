"""Offline common-joint comparison; extra slots never create foot detail."""
import argparse
import json
import math
from pathlib import Path
from .replay_action_naming import finite

COCO_TO_MP = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


def normalize(sample, layout='coco17', native_joint_count=None):
    xy, scores = sample.get('kpts_xy'), sample.get('kpts_score')
    expected = {'coco17': 17, 'mediapipe33': 33}.get(layout)
    if expected is None or not isinstance(xy, list) or not isinstance(scores, list) or len(xy) != expected or len(scores) != expected:
        raise ValueError('Declare the real keypoint layout and image-normalized coordinates')
    def point(index):
        row, score = xy[index], scores[index]
        if not isinstance(row, list) or len(row) != 2 or not all(finite(v) for v in row) or not finite(score) or score < .5 or not all(0 < v <= 1 for v in row):
            return None
        return row
    indices = range(17) if layout == 'coco17' else COCO_TO_MP
    common = [point(index) for index in indices] if sample.get('observed') is True else [None]*17
    details = {name: point(index) if sample.get('observed') is True else None
               for name, index in [('left_heel', 29), ('right_heel', 30), ('left_toe', 31), ('right_toe', 32)]} if layout == 'mediapipe33' and native_joint_count == 33 else {}
    return {'time_seconds': sample.get('time_seconds'), 'common17': common, 'foot_details': details}


def compare(primary, secondary=None):
    def samples(document):
        if document.get('coordinate_space') != 'image_normalized' or not document.get('source_sha256'):
            raise ValueError('Source hash and normalized coordinate declaration are required')
        return [normalize(row, document.get('layout'), document.get('native_joint_count')) for row in document.get('samples', [])]
    rows = samples(primary)
    coverage = {str(i): sum(r['common17'][i] is not None for r in rows)/len(rows) if rows else None for i in range(17)}
    output = {'schema_version': 'pose-common17-comparison-v1', 'primary_sample_count': len(rows), 'common_joint_coverage': coverage,
              'paired_sample_count': 0, 'mean_common_joint_distance': None, 'secondary_available': secondary is not None,
              'accuracy_established': False, 'technique_approval_granted': False,
              'primary_foot_detail_frames': sum(any(r['foot_details'].values()) for r in rows)}
    if secondary is None:
        return output
    if primary['source_sha256'] != secondary.get('source_sha256'):
        raise ValueError('Compare the same source video')
    other = samples(secondary)
    used, distances = set(), []
    for row in rows:
        candidates = [(i, r) for i, r in enumerate(other) if i not in used and finite(row['time_seconds']) and finite(r['time_seconds']) and abs(r['time_seconds']-row['time_seconds']) <= .05]
        if not candidates:
            continue
        i, matched = min(candidates, key=lambda pair: abs(pair[1]['time_seconds']-row['time_seconds']))
        used.add(i)
        output['paired_sample_count'] += 1
        distances.extend(math.dist(a, b) for a, b in zip(row['common17'], matched['common17']) if a is not None and b is not None)
    output.update(mean_common_joint_distance=sum(distances)/len(distances) if distances else None,
                  compared_joint_count=len(distances), secondary_foot_detail_frames=sum(any(r['foot_details'].values()) for r in other))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('primary', type=Path)
    parser.add_argument('--secondary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(json.loads(args.primary.read_text(encoding='utf-8')), json.loads(args.secondary.read_text(encoding='utf-8')) if args.secondary else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Offline comparison saved; no technique approval')
