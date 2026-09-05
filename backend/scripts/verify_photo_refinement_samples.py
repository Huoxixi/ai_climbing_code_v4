"""Compare the V2 refinement job with existing, explicitly supplied evidence.

Run from backend with --evidence-root and --output. Uses temporary persistence;
never reads application databases. Agreement is regression evidence, not accuracy.
"""
import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.photo_route_analysis import analyze_board_photo
from core.photo_route_v2 import ColorRefinement, PhotoRouteJobManager, PhotoRouteV2Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(1); cv2.setRNGSeed(0)
    samples = Path(__file__).resolve().parents[2]/'frontend/src/assets/boulder-samples'
    summaries = []
    for number, color, folder in [(1,'黄色','yellow-sam-v6-final'), (2,'蓝色','blue-sam-v6-final')]:
        evidence = args.evidence_root/folder/'run-01/evidence'
        expected = json.loads((evidence/'report.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(prefix='photo-refinement-') as temporary:
            store = PhotoRouteV2Store(Path(temporary))
            photo = samples/f'boulder-{number}.jpg'
            original, _ = store.create_upload('test', photo.name, photo.read_bytes())
            with patch('core.photo_route_analysis._mobilesam_masks', return_value=None):
                coarse = analyze_board_photo(photo, store.root)
            store.set_analysis_result(original['id'], coarse)
            source = store.get_board(original['id'], 'test')
            queued = store.create_color_refinement(source['id'], 'test', ColorRefinement(
                expected_version=source['version'], color_group=color, seed=expected['seed']))
            started = time.monotonic()
            manager = SimpleNamespace(store=store, timeout_seconds=180)
            PhotoRouteJobManager._recognize(manager, queued['job'], threading.Event(), started)
            result = store.get_board(queued['board']['id'], 'test')
            assert store.get_board(source['id'], 'test') == source
            objects = [item for item in result['objects'] if item['color_group']==color]
            matches = 0
            overlay = cv2.imdecode(np.frombuffer(photo.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            for index, item in enumerate(objects):
                mask = cv2.imdecode(np.frombuffer(store.asset_path(item['mask']['filename']).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
                x,y,w,h = item['source_bbox_px']
                full = np.zeros(overlay.shape[:2], np.uint8); full[y:y+h,x:x+w] = mask
                if index < len(expected['objects']):
                    reference = cv2.imdecode(np.frombuffer((evidence/f"{expected['objects'][index]['id']}-mask.png").read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
                    matches += int(np.array_equal(full, reference))
                cv2.drawContours(overlay, cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, (30,30,240), 2)
            cv2.imencode('.jpg', overlay)[1].tofile(str(args.output/f'sample-{number}-refined.jpg'))
            summary = {'sample':number, 'color':color, 'coarse_candidates':sum(item['color_group']==color for item in coarse['objects']),
                'refined_candidates':len(objects), 'previous_candidates':len(expected['objects']),
                'pixel_identical_masks':matches, 'refinement_seconds':round(time.monotonic()-started,2),
                'other_colors_preserved':len(result['objects'])-len(objects)==sum(item['color_group']!=color for item in source['objects']),
                'model_version':result['model_version'], 'accuracy_claim':False}
            summaries.append(summary); print(json.dumps(summary,ensure_ascii=False), flush=True)
    (args.output/'comparison.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(item['pixel_identical_masks']==item['refined_candidates']==item['previous_candidates'] and item['other_colors_preserved'] for item in summaries)


if __name__ == '__main__': main()
