"""Stage-only ROI diagnostic with oracle boxes, explicitly ineligible for acceptance."""
import time
from pathlib import Path

import numpy as np

from .data import audit_manifest, image_path, load_image, digest_file, write_new
from .geometry import local_mask, object_from_mask, overlap
from .inference import OnnxSegmenter


def probe_roi(manifest_path, model_path, output, limit=0):
    manifest, audit = audit_manifest(manifest_path)
    root = Path(manifest_path).resolve().parent
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    samples = [s for s in manifest['samples'] if s['split'] in ('train', 'diagnostic')]
    if limit:
        samples = samples[:limit]
    if not samples:
        raise ValueError('诊断只允许训练/诊断照片，不查看留出集')
    model = OnnxSegmenter(model_path, {})
    rows = []
    try:
        for sample in samples:
            start = time.monotonic()
            image = load_image(image_path(root, sample['image']))
            values = []
            for original in sample['objects']:
                origin, mask = local_mask(original, image.shape[:2])
                prompt = object_from_mask(mask, origin, original['kind'], 1.)
                refined = model.refine(image, prompt)
                values.append(overlap((origin, mask), local_mask(refined, image.shape[:2])) if refined else 0.)
            row = {'sample': sample['id'], 'objects': len(values), 'seconds': time.monotonic()-start,
                   'mean_oracle_box_mask_iou': float(np.mean(values)) if values else None,
                   'iou_ge_05': sum(v >= .5 for v in values)}
            rows.append(row)
            print(row, flush=True)
    finally:
        model.close()
    from scripts.run_climbing_instance_model import peak_memory_bytes
    report = {'schema_version': 1, 'purpose': 'oracle-box-stage-diagnostic',
              'ground_truth_boxes_provided': True, 'training_overlap': True, 'formal_acceptance_eligible': False,
              'model_sha256': digest_file(model_path), 'manifest_sha256': audit['manifest_sha256'],
              'peak_process_bytes': peak_memory_bytes(), 'scope': 'roi-stage-only-no-detector-no-api', 'runs': rows}
    write_new(output/'probe.json', report)
    return report
