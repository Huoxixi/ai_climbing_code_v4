"""Offline auxiliary training. Torch is imported only for the ROI U-Net command."""
from pathlib import Path

import cv2
import numpy as np

from .data import audit_manifest, load_image, image_path, digest_json, digest_file, write_new, write_image_new
from .geometry import local_mask, object_from_mask, tiles
from .appearance import color_descriptor, mask_pixels, pair_features


def fit_logistic(features, targets, steps=800):
    x, y = np.asarray(features, dtype=float), np.asarray(targets, dtype=float)
    if x.ndim != 2 or len(x) < 4 or set(y) != {0., 1.} or not np.isfinite(x).all():
        raise ValueError('分类训练需要有限特征和足够的正负样本')
    mean, scale = x.mean(0), np.maximum(x.std(0), .01)
    x = (x-mean)/scale
    weights, bias = np.zeros(x.shape[1]), 0.
    balance = np.where(y == 1, .5/max(1, y.sum()), .5/max(1, (1-y).sum()))
    for _ in range(steps):
        p = 1/(1+np.exp(-np.clip(x@weights+bias, -40, 40)))
        error = (p-y)*balance
        weights -= .1*(x.T@error + .001*weights)
        bias -= .1*error.sum()
    return {'weights': weights.tolist(), 'bias': float(bias), 'mean': mean.tolist(), 'scale': scale.tolist()}


def training_samples(manifest_path):
    manifest, audit = audit_manifest(manifest_path)
    samples = [s for s in manifest['samples'] if s['split'] == 'train']
    if not samples:
        raise ValueError('没有训练集；不会使用验证集/留出集训练')
    for s in samples:
        if s.get('human_reviewed') is not True or s.get('provenance', {}).get('commercial_training_allowed') is not True:
            raise ValueError('训练样本缺少人工标注来源或许可确认')
    return samples, audit


def train_auxiliary(manifest_path, output):
    samples, audit = training_samples(manifest_path)
    root = Path(manifest_path).resolve().parent
    colors, features, labels = {}, [], []
    rng = np.random.default_rng(20260908)
    for sample in samples:
        image = load_image(image_path(root, sample['image']))
        objects = []
        for original in sample['objects']:
            (x, y), mask = local_mask(original, image.shape[:2])
            obj = {**original, **object_from_mask(mask, (x, y), original['kind'], 1.)}
            center, share, std = color_descriptor(mask_pixels(image, obj))
            obj.update(lab=center.tolist(), appearance_std=std.tolist())
            if obj['kind'] == 'hold' and original['color_group'] != '待确认' and share >= .5:
                colors.setdefault(original['color_group'], []).append(center)
            objects.append(obj)
        membership = {o['id']: set() for o in objects}
        for route in sample.get('routes', []):
            if route['decidable']:
                for oid in route['member_ids']:
                    membership[oid].add(route['id'])
        # Exclude unknown members from negative labels; do not invent line truth.
        holds = [o for o in objects if o['kind'] == 'hold' and membership[o['id']]]
        pairs = [(a, b) for i, a in enumerate(holds) for b in holds[:i]]
        if len(pairs) > 5000:
            pairs = [pairs[i] for i in rng.choice(len(pairs), 5000, replace=False)]
        for a, b in pairs:
            features.append(pair_features(a, b, sample['size']))
            labels.append(float(bool(membership[a['id']] & membership[b['id']])))
    evidence = {'training_manifest_sha256': audit['manifest_sha256'],
                'training_sample_ids': [s['id'] for s in samples],
                'training_image_sha256': [s['image_sha256'] for s in samples],
                'training_wall_ids': sorted({s['wall_id'] for s in samples})}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {'evidence': evidence, 'blockers': []}
    if len(colors) >= 2:
        palette = {'schema_version': 1, **evidence, 'anchors': {name: {
            'lab': np.median(values, axis=0).tolist(),
            'scale': np.maximum(np.std(values, axis=0), [12., 8., 8.]).tolist()}
            for name, values in colors.items()}}
        write_new(output/'palette.json', palette)
        result['palette_sha256'] = digest_file(output/'palette.json')
    else:
        result['blockers'].append('不足两种人工确认颜色，未生成色板')
    if len(features) >= 4 and set(labels) == {0., 1.}:
        relation = {'schema_version': 1, **evidence, **fit_logistic(features, labels),
                    'feature_version': 'pair-v1', 'pairs': len(labels)}
        write_new(output/'relation.json', relation)
        result['relation_sha256'] = digest_file(output/'relation.json')
    else:
        result['blockers'].append('缺少同线/异线真实成员对，未生成关系分类器')
    write_new(output/'training-report.json', result)
    return result


def make_unet():
    import torch
    from torch import nn

    class ROIUNet(nn.Module):
        def __init__(self):
            super().__init__()
            def block(a, b):
                return nn.Sequential(nn.Conv2d(a, b, 3, padding=1), nn.ReLU(),
                                     nn.Conv2d(b, b, 3, padding=1), nn.ReLU())
            self.e1, self.e2, self.e3 = block(4, 16), block(16, 32), block(32, 64)
            self.d2, self.d1 = block(96, 32), block(48, 16)
            self.out = nn.Conv2d(16, 1, 1)

        def forward(self, x):
            a = self.e1(x)
            b = self.e2(nn.functional.max_pool2d(a, 2))
            c = self.e3(nn.functional.max_pool2d(b, 2))
            d = self.d2(torch.cat([nn.functional.interpolate(c, scale_factor=2, mode='nearest'), b], 1))
            return torch.sigmoid(self.out(self.d1(torch.cat([nn.functional.interpolate(d, scale_factor=2, mode='nearest'), a], 1))))
    return ROIUNet()


def train_quality(manifest_path, labels_path, output):
    """Quality labels refer to actual predictions on training walls only."""
    from .data import read_json
    from .appearance import quality_features
    samples, audit = training_samples(manifest_path)
    by_id = {s['id']: s for s in samples}
    labels = read_json(labels_path)
    if labels.get('manifest_sha256') != audit['manifest_sha256']:
        raise ValueError('质量标注不属于当前清单')
    features, targets = [], []
    for row in labels['items']:
        if row['sample_id'] not in by_id or row.get('human_reviewed') is not True or type(row.get('bad_boundary')) is not bool:
            raise ValueError('边界质量训练只能使用训练集上的人工好/坏标注')
        path = Path(labels_path).resolve().parent/row['prediction']
        if digest_file(path) != row['prediction_sha256']:
            raise ValueError('边界标注对应预测文件已变化')
        prediction = read_json(path)
        if prediction['image_sha256'] != by_id[row['sample_id']]['image_sha256']:
            raise ValueError('质量样本图片与预测不符')
        obj = next(o for o in prediction['objects'] if o['id'] == row['object_id'])
        features.append(quality_features(obj))
        targets.append(float(row['bad_boundary']))
    result = {'schema_version': 1, 'feature_version': 'quality-v1',
              'training_manifest_sha256': audit['manifest_sha256'],
              'training_wall_ids': sorted({s['wall_id'] for s in samples}),
              'training_image_sha256': [s['image_sha256'] for s in samples],
              **fit_logistic(features, targets)}
    write_new(output, result)
    return {'quality_sha256': digest_file(output), 'samples': len(targets)}


def train_roi(manifest_path, output, epochs=20):
    import torch
    from .inference import roi_input
    samples, audit = training_samples(manifest_path)
    if not 1 <= epochs <= 200:
        raise ValueError('epochs 必须在 1 到 200 之间')
    root, output = Path(manifest_path).resolve().parent, Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(20260908)
    torch.set_num_threads(2)
    model = make_unet()
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    history = []
    rng = np.random.default_rng(20260908)
    for epoch in range(epochs):
        model.train()
        loss_sum, count = 0., 0
        for sample in samples:
            image = load_image(image_path(root, sample['image']))
            for obj in sample['objects']:
                (x, y), mask = local_mask(obj, image.shape[:2])
                h, w = mask.shape
                # Expand the detector prompt randomly, preserving all true foreground.
                padding = int(rng.uniform(0, .1)*max(w, h))
                bx, by = max(0, x-padding), max(0, y-padding)
                bw, bh = min(image.shape[1], x+w+padding)-bx, min(image.shape[0], y+h+padding)-by
                tensor, (left, top, rw, rh) = roi_input(image, [bx, by, bw, bh])
                truth = np.zeros((rh, rw), np.float32)
                truth[y-top:y-top+h, x-left:x-left+w] = mask
                truth = cv2.resize(truth, (256, 256), interpolation=cv2.INTER_NEAREST)[None, None]
                prediction = model(torch.from_numpy(tensor))
                target = torch.from_numpy(truth)
                bce = torch.nn.functional.binary_cross_entropy(prediction, target)
                dice = 1-(2*(prediction*target).sum()+1)/(prediction.sum()+target.sum()+1)
                loss = bce+dice
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                loss_sum += float(loss.detach())
                count += 1
        if not count:
            raise ValueError('没有可训练掩膜')
        history.append({'epoch': epoch+1, 'loss': loss_sum/count})
        print(history[-1], flush=True)
    model.eval()
    checkpoint = output/'roi-unet.pt'
    torch.save(model.state_dict(), checkpoint)
    torch.onnx.export(model, torch.zeros(1, 4, 256, 256), str(output/'roi-unet.onnx'),
                      input_names=['image_prompt'], output_names=['probability'],
                      opset_version=17, dynamo=False)
    report = {'training_manifest_sha256': audit['manifest_sha256'],
              'training_sample_ids': [s['id'] for s in samples], 'history': history,
              'training_wall_ids': sorted({s['wall_id'] for s in samples}),
              'training_image_sha256': [s['image_sha256'] for s in samples],
              'model_sha256': digest_file(output/'roi-unet.onnx'), 'formal_quality_passed': False}
    write_new(output/'training-report.json', report)
    return report


def export_coco(manifest_path, output):
    """Creates tile JPGs + COCO masks; retains source-level split assignments."""
    manifest, audit = audit_manifest(manifest_path)
    root, output = Path(manifest_path).resolve().parent, Path(output)
    output.mkdir(parents=True, exist_ok=False)
    reports = {}
    for split in ('train', 'validation'):
        images, annotations = [], []
        for sample in manifest['samples']:
            if sample['split'] != split:
                continue
            if sample.get('human_reviewed') is not True or sample.get('provenance', {}).get('commercial_training_allowed') is not True:
                raise ValueError('COCO 导出需要人工标注来源及训练许可')
            image = load_image(image_path(root, sample['image']))
            from itertools import chain
            # The overview teaches complete large volumes; tiles teach small holds.
            windows = chain([(0, 0, image.shape[1], image.shape[0])], tiles(image.shape[1], image.shape[0])) if max(image.shape[:2]) > 640 else tiles(image.shape[1], image.shape[0])
            for x, y, w, h in windows:
                iid = len(images)+1
                name = f'{split}-{iid:06d}.jpg'
                write_image_new(output/name, image[y:y+h, x:x+w])
                images.append({'id': iid, 'file_name': name, 'width': w, 'height': h,
                               'source_id': sample['source_id'], 'wall_id': sample['wall_id']})
                for obj in sample['objects']:
                    (ox, oy), mask = local_mask(obj, image.shape[:2])
                    left, top = max(x, ox), max(y, oy)
                    right, bottom = min(x+w, ox+mask.shape[1]), min(y+h, oy+mask.shape[0])
                    if right <= left or bottom <= top:
                        continue
                    cropped = np.zeros((h, w), np.uint8)
                    cropped[top-y:bottom-y, left-x:right-x] = mask[top-oy:bottom-oy, left-ox:right-ox]
                    if cropped.sum() < 4:
                        continue
                    # COCO's uncompressed RLE is column-major, unlike our row-major RLE.
                    flat = cropped.ravel(order='F')
                    changes = np.flatnonzero(np.diff(flat))+1
                    counts = np.diff(np.r_[0, changes, len(flat)]).astype(int).tolist()
                    if flat[0]:
                        counts.insert(0, 0)
                    bx, by, bw, bh = cv2.boundingRect(cropped)
                    annotations.append({'id': len(annotations)+1, 'image_id': iid,
                        'category_id': 1 if obj['kind'] == 'hold' else 2, 'bbox': [bx, by, bw, bh],
                        'area': int(cropped.sum()), 'iscrowd': 0,
                        'segmentation': {'size': [h, w], 'counts': counts}})
        value = {'images': images, 'annotations': annotations,
                 'categories': [{'id': 1, 'name': 'hold'}, {'id': 2, 'name': 'volume'}]}
        write_new(output/f'{split}.json', value)
        reports[split] = {'images': len(images), 'objects': len(annotations)}
    write_new(output/'provenance.json', {'manifest_sha256': audit['manifest_sha256'], 'splits': reports,
              'training_image_sha256': [s['image_sha256'] for s in manifest['samples'] if s['split'] == 'train'],
              'training_wall_ids': sorted({s['wall_id'] for s in manifest['samples'] if s['split'] == 'train'})})
    return reports


def train_detector(coco_root, base_config, initial_checkpoint, output, epochs=100):
    """Use official MMDetection config in a separate supported training environment."""
    from mmengine.config import Config
    from mmengine.runner import Runner
    from mmdet.utils import register_all_modules
    from .data import read_json
    coco_root, output = Path(coco_root).resolve(), Path(output).resolve()
    if not Path(initial_checkpoint).is_file() or not Path(base_config).is_file() or not 1 <= epochs <= 300:
        raise ValueError('需本地官方配置、初始权重，以及 1–300 epochs')
    provenance = read_json(coco_root/'provenance.json')
    if not provenance['splits']['train']['images']:
        raise ValueError('没有 COCO 训练照片')
    register_all_modules()
    cfg = Config.fromfile(str(base_config))
    if cfg.model.get('type') != 'RTMDet':
        raise ValueError('仅接受官方 RTMDet/RTMDet-Ins 配置')
    output.mkdir(parents=True, exist_ok=False)
    cfg.model.bbox_head.num_classes = 2
    cfg.model.backbone.init_cfg = None
    cfg.load_from = str(Path(initial_checkpoint).resolve())
    cfg.work_dir = str(output)
    with_mask = 'Ins' in cfg.model.bbox_head.type
    common = [dict(type='LoadImageFromFile'), dict(type='LoadAnnotations', with_bbox=True,
              with_mask=with_mask, poly2mask=True), dict(type='Resize', scale=(640, 640), keep_ratio=False)]
    train_pipeline = [*common, dict(type='RandomFlip', prob=.5), dict(type='PackDetInputs')]
    val_pipeline = [*common, dict(type='PackDetInputs')]
    metainfo = dict(classes=('hold', 'volume'))
    def loader(split, pipeline, training):
        return dict(batch_size=2 if training else 1, num_workers=0, persistent_workers=False,
            sampler=dict(type='DefaultSampler', shuffle=training),
            dataset=dict(type='CocoDataset', data_root=str(coco_root), ann_file=f'{split}.json',
                         data_prefix=dict(img=''), metainfo=metainfo, test_mode=not training,
                         pipeline=pipeline, filter_cfg=None))
    cfg.train_dataloader = loader('train', train_pipeline, True)
    cfg.train_cfg = dict(type='EpochBasedTrainLoop', max_epochs=epochs, val_interval=5)
    if provenance['splits']['validation']['images']:
        cfg.val_dataloader = loader('validation', val_pipeline, False)
        cfg.val_cfg = dict(type='ValLoop')
        cfg.val_evaluator = dict(type='CocoMetric', ann_file=str(coco_root/'validation.json'),
                                metric=['bbox', 'segm'] if with_mask else ['bbox'])
    else:
        cfg.val_dataloader = cfg.val_cfg = cfg.val_evaluator = None
    cfg.test_dataloader = cfg.test_cfg = cfg.test_evaluator = None
    cfg.custom_hooks = []  # No inherited pipeline switch to another dataset recipe.
    cfg.param_scheduler = [dict(type='CosineAnnealingLR', by_epoch=True, T_max=epochs, eta_min=1e-6)]
    cfg.optim_wrapper = dict(type='OptimWrapper', optimizer=dict(type='AdamW', lr=.0002, weight_decay=.05))
    cfg.default_hooks.checkpoint = dict(type='CheckpointHook', interval=5, max_keep_ckpts=2)
    cfg.randomness = dict(seed=20260908, deterministic=True)
    cfg.dump(str(output/'training-config.py'))
    write_new(output/'training-provenance.json', {**provenance,
        'base_config_sha256': digest_file(base_config), 'initial_checkpoint_sha256': digest_file(initial_checkpoint),
        'architecture': 'rtmdet-ins-tiny' if with_mask else 'rtmdet-tiny', 'formal_quality_passed': False})
    Runner.from_cfg(cfg).train()
    return {'work_dir': str(output), 'formal_quality_passed': False}
