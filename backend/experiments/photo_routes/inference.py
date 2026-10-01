"""ONNX Runtime CPU adapters and A/B/C pipelines with sequential model lifetimes."""
import gc
import time
from pathlib import Path

import cv2
import numpy as np

from .data import MAX_OBJECTS, KINDS, digest_file, load_image, read_json
from .geometry import tiles, merge_candidate, object_from_mask, local_mask
from .appearance import assign_colors, group_routes, quality_features, probability


class BudgetExceeded(RuntimeError):
    pass


def verify_artifact(root, spec):
    path = (Path(root) / spec['path']).resolve()
    if not path.is_file() or digest_file(path) != spec['sha256']:
        raise ValueError(f'模型或校准文件缺失/摘要不符: {spec["path"]}')
    if spec.get('commercial_use_allowed') is not True or not spec.get('license') or not spec.get('source'):
        raise ValueError('候选产物缺少来源、许可或商业使用确认')
    return path


def check_recipe(recipe, root):
    if recipe.get('schema_version') != 1 or recipe.get('scheme') not in ('A', 'B', 'C'):
        raise ValueError('未知实验方案')
    if recipe.get('precision') not in ('fp32', 'int8'):
        raise ValueError('必须明确 fp32 或 int8')
    if not 0 < recipe.get('score_threshold', .4) < 1:
        raise ValueError('检测阈值无效')
    if not 0 < recipe.get('route_threshold', .95) <= 1:
        raise ValueError('线路阈值无效')
    for key, default in (('color_threshold', .7), ('quality_threshold', .5)):
        if not isinstance(recipe.get(key, default), (int, float)) or not 0 <= recipe.get(key, default) <= 1:
            raise ValueError(f'{key} 无效')
    required = ['detector'] + (['segmenter'] if recipe['scheme'] in ('B', 'C') else [])
    for key in required:
        if key not in recipe:
            raise ValueError(f'缺少 {key}')
    for key in ('detector', 'segmenter', 'palette', 'relation', 'quality'):
        if recipe.get(key):
            verify_artifact(root, recipe[key])
    for key in ('relation', 'quality'):
        if recipe.get(key):
            value = read_json(Path(root)/recipe[key]['path'])
            dimension = 9 if key == 'relation' else 6
            if value.get('feature_version') != ('pair-v1' if key == 'relation' else 'quality-v1'):
                raise ValueError(f'{key} 特征版本不兼容')
            if not all(len(value.get(k, [])) == dimension for k in ('weights', 'mean', 'scale')):
                raise ValueError(f'{key} 特征维度不兼容')
            if not np.isfinite(np.r_[value['weights'], value['mean'], value['scale'], value.get('bias', np.nan)]).all() or min(value['scale']) <= 0:
                raise ValueError(f'{key} 存在非有限数值或无效缩放')
    if recipe.get('deepseek'):
        deepseek = recipe['deepseek']
        if (deepseek.get('provider') != 'DeepSeek' or not deepseek.get('model') or
                deepseek.get('prompt_version') != 'semantic-review-v1' or
                not isinstance(deepseek.get('allowed_colors'), list) or not deepseek['allowed_colors'] or
                any(not isinstance(color, str) or not color or color == '待确认' for color in deepseek['allowed_colors']) or
                not 1 <= deepseek.get('max_objects', 100) <= 300 or
                not 0 < deepseek.get('automatic_threshold', .95) <= 1):
            raise ValueError('DeepSeek 对照配置无效')
    detector = recipe['detector']
    if detector.get('class_mapping') != {'0': 'hold', '1': 'volume'}:
        raise ValueError('权重必须验证为两类 hold/volume；不能直接套用三类 Climbnet')
    expected = 'rtmdet-tiny' if recipe['scheme'] == 'B' else 'rtmdet-ins-tiny'
    if detector.get('architecture') != expected:
        raise ValueError(f'方案要求 {expected}')
    if detector.get('resize') != 'stretch-640' or detector.get('color_order') not in ('bgr', 'rgb'):
        raise ValueError('须显式声明与导出一致的 stretch-640 预处理和颜色顺序')
    if len(detector.get('mean', [])) != 3 or len(detector.get('std', [])) != 3 or any(x <= 0 for x in detector['std']):
        raise ValueError('必须提供导出模型的 mean/std')
    if not np.isfinite(detector['mean']+detector['std']).all():
        raise ValueError('mean/std 不能含非有限值')
    if recipe['scheme'] != 'B' and detector.get('mask_values') not in ('probability', 'binary'):
        raise ValueError('须声明掩膜为概率或二值')
    return recipe


class OnnxDetector:
    def __init__(self, path, spec):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])
        self.spec = spec
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].shape != [1, 3, 640, 640] or inputs[0].type != 'tensor(float)':
            raise ValueError('检测 ONNX 必须是固定 [1,3,640,640] float 输入')
        self.input_name = inputs[0].name
        self.outputs = [o.name for o in self.session.get_outputs()]
        if not {'dets', 'labels'} <= set(self.outputs):
            raise ValueError('需要 MMDeploy dets/labels 输出')

    def predict(self, image, threshold, masks=True):
        height, width = image.shape[:2]
        image = cv2.resize(image, (640, 640), interpolation=cv2.INTER_LINEAR)
        if self.spec['color_order'] == 'rgb':
            image = image[:, :, ::-1]
        tensor = (image.astype(np.float32)-np.asarray(self.spec['mean'], np.float32))/np.asarray(self.spec['std'], np.float32)
        output = dict(zip(self.outputs, self.session.run(None, {self.input_name: np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])})))
        dets, labels = output['dets'], output['labels']
        if dets.ndim != 3 or dets.shape[0] != 1 or dets.shape[2] != 5 or labels.shape != dets.shape[:2]:
            raise ValueError('ONNX 输出不是 [1,N,5] dets 和 [1,N] labels')
        if masks and ('masks' not in output or output['masks'].shape[:2] != dets.shape[:2] or output['masks'].ndim != 4):
            raise ValueError('实例模型需要 [1,N,H,W] 输入坐标空间掩膜')
        for i, row in enumerate(dets[0]):
            if not np.isfinite(row).all():
                raise ValueError('检测结果存在非有限值')
            if row[4] < threshold:
                continue
            if not 0 <= row[4] <= 1 or int(labels[0, i]) not in (0, 1):
                raise ValueError('检测类别或置信度不合法')
            x1, y1, x2, y2 = row[:4] * [width/640, height/640, width/640, height/640]
            x1, y1 = max(0, int(np.floor(x1))), max(0, int(np.floor(y1)))
            x2, y2 = min(width, int(np.ceil(x2))), min(height, int(np.ceil(y2)))
            if x2 <= x1 or y2 <= y1:
                continue
            item = {'kind': KINDS[int(labels[0, i])], 'confidence': float(row[4]),
                    'source_bbox_px': [x1, y1, x2-x1, y2-y1],
                    'truncated': x1 <= 1 or y1 <= 1 or x2 >= width-1 or y2 >= height-1}
            if masks:
                raw = output['masks'][0, i]
                if not np.isfinite(raw).all() or raw.min() < 0 or raw.max() > 1:
                    raise ValueError('掩膜必须在 [0,1]')
                # Resize only the object's ROI, never a full-size mask per object.
                mh, mw = raw.shape
                left, top = max(0, int(x1*mw/width)), max(0, int(y1*mh/height))
                right, bottom = min(mw, max(left+1, int(np.ceil(x2*mw/width)))), min(mh, max(top+1, int(np.ceil(y2*mh/height))))
                patch = cv2.resize(raw[top:bottom, left:right].astype(np.float32), (x2-x1, y2-y1))
                stable = float((patch > .55).sum()/max(1, (patch > .45).sum()))
                if not (patch > .5).any():
                    continue
                item = object_from_mask(patch > .5, (x1, y1), item['kind'], item['confidence'],
                                        truncated=item['truncated'], stability=stable)
            yield item

    def close(self):
        self.session = None
        gc.collect()


def roi_input(image, box):
    x, y, w, h = box
    pad = max(4, int(max(w, h)*.15))
    left, top = max(0, x-pad), max(0, y-pad)
    right, bottom = min(image.shape[1], x+w+pad), min(image.shape[0], y+h+pad)
    crop = image[top:bottom, left:right]
    prompt = np.zeros(crop.shape[:2], np.float32)
    prompt[y-top:y+h-top, x-left:x+w-left] = 1
    rgb = cv2.resize(crop, (256, 256))[:, :, ::-1].astype(np.float32)/255.
    prompt = cv2.resize(prompt, (256, 256), interpolation=cv2.INTER_NEAREST)
    return np.concatenate([rgb.transpose(2, 0, 1), prompt[None]], 0)[None], (left, top, right-left, bottom-top)


class OnnxSegmenter:
    def __init__(self, path, spec):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].shape != [1, 4, 256, 256]:
            raise ValueError('局部分割器需要 [1,4,256,256] RGB+框提示输入')
        self.input_name = inputs[0].name

    def refine(self, image, obj):
        tensor, (x, y, w, h) = roi_input(image, obj['source_bbox_px'])
        raw = self.session.run(None, {self.input_name: tensor})[0]
        if raw.shape != (1, 1, 256, 256) or not np.isfinite(raw).all():
            raise ValueError('局部分割器输出须为 [1,1,256,256] 概率')
        if raw.min() < 0 or raw.max() > 1:
            raise ValueError('局部分割器输出不在 [0,1]')
        patch = cv2.resize(raw[0, 0], (w, h))
        if not (patch > .5).any():
            return None
        return object_from_mask(patch > .5, (x, y), obj['kind'], obj['confidence'],
                                stability=float((patch > .55).sum()/max(1, (patch > .45).sum())),
                                refined=True)

    def close(self):
        self.session = None
        gc.collect()


def run_pipeline(image_path, recipe, root, *, detector_factory=OnnxDetector,
                 segmenter_factory=OnnxSegmenter, reviewer_factory=None, check=lambda: None):
    """Factories permit tests; the CLI always uses verified real ONNX artifacts."""
    start = time.monotonic()
    image = load_image(image_path)
    shape = image.shape[:2]
    objects, model, stages = [], None, {}

    def guard():
        check()
        if time.monotonic()-start > 120:
            raise BudgetExceeded('超过 120 秒，结果未完成')

    scheme = recipe['scheme']
    try:
        model = detector_factory(Path(root)/recipe['detector']['path'], recipe['detector'])
        windows = [(0, 0, shape[1], shape[0])]
        if recipe.get('slicing', True) and max(shape) > 640:
            from itertools import chain
            windows = chain(windows, tiles(shape[1], shape[0]))
        for index, (x, y, w, h) in enumerate(windows):
            guard()
            for obj in model.predict(image[y:y+h, x:x+w], recipe.get('score_threshold', .4), masks=scheme != 'B'):
                guard()
                obj['source_bbox_px'][0] += x
                obj['source_bbox_px'][1] += y
                obj['source'] = 'overview' if index == 0 else 'tile'
                if 'mask_rle' in obj:
                    obj['mask_rle']['origin'][0] += x
                    obj['mask_rle']['origin'][1] += y
                    obj['contour'] = [[a+x, b+y] for a, b in obj['contour']]
                merge_candidate(objects, obj, shape)
                if len(objects) > MAX_OBJECTS:
                    raise BudgetExceeded('候选超过 300 个，请分区拍摄；未静默截断')
        stages['detection_seconds'] = time.monotonic()-start
    finally:
        if model:
            model.close()
        model = None
    quality = read_json(Path(root)/recipe['quality']['path']) if recipe.get('quality') else None
    to_refine = []
    if scheme == 'B':
        to_refine = list(range(len(objects)))
    elif scheme == 'C':
        for i, obj in enumerate(objects):
            bad = (float(probability(quality, quality_features(obj))) if quality else
                   float(obj.get('truncated') or obj.get('conflict') or obj.get('stability', 0) < .9))
            if bad >= recipe.get('quality_threshold', .5):
                to_refine.append(i)
                obj['needs_review'] = True
        to_refine.sort(key=lambda i: objects[i]['confidence'])
        to_refine = to_refine[:60]
    if to_refine:
        try:
            guard()
            model = segmenter_factory(Path(root)/recipe['segmenter']['path'], recipe['segmenter'])
            for i in to_refine:
                guard()
                previous = objects[i]
                refined = model.refine(image, previous)
                if refined is None:
                    previous['needs_review'] = True
                    continue
                # Reject a refinement escaping its detector box substantially.
                rx, ry, rw, rh = refined['source_bbox_px']
                px, py, pw, ph = previous['source_bbox_px']
                bounded = rx >= px-.2*pw and ry >= py-.2*ph and rx+rw <= px+1.2*pw and ry+rh <= py+1.2*ph
                if not bounded or refined.get('stability', 0) < .9:
                    previous['needs_review'] = True
                    continue
                objects[i] = {**refined, 'needs_review': bool(previous.get('conflict')),
                              'source': previous['source']}
        finally:
            if model:
                model.close()
            model = None
    # B must not masquerade detector boxes as segmentation masks.
    missing = sum('mask_rle' not in o for o in objects)
    objects = [o for o in objects if 'mask_rle' in o]
    merged = []
    for obj in objects:
        merge_candidate(merged, obj, shape)
    objects = merged
    for i, obj in enumerate(objects):
        obj['id'] = f'object-{i+1:03d}'
    guard()
    palette = read_json(Path(root)/recipe['palette']['path']) if recipe.get('palette') else None
    assign_colors(image, objects, palette, recipe.get('color_mode', 'lab'), recipe.get('color_threshold', .7))
    relation = read_json(Path(root)/recipe['relation']['path']) if recipe.get('relation') else None
    routes = group_routes(objects, (shape[1], shape[0]), relation, recipe.get('route_threshold', .95))
    deepseek_evidence = None
    if recipe.get('deepseek'):
        guard()
        if reviewer_factory is None:
            from .deepseek import DeepSeekReviewer
            reviewer_factory = DeepSeekReviewer
        reviewer = reviewer_factory(recipe['deepseek'])
        try:
            reviewed = reviewer.review(image, objects, routes)
        finally:
            reviewer.close()
        objects, routes = reviewed['objects'], reviewed['routes']
        deepseek_evidence = reviewed['evidence']
        stages['deepseek_seconds'] = deepseek_evidence['seconds']
    guard()
    if missing:
        for route in routes:
            route['review_status'] = 'needs_review'
            route['reasons'].append('存在未成功分割的候选对象')
    return {'schema_version': 1, 'status': 'incomplete' if missing else 'completed',
            'objects': objects, 'route_candidates': routes, 'unsegmented_candidates': missing,
            'size': [shape[1], shape[0]], 'seconds': time.monotonic()-start, 'stages': stages,
            'deepseek': deepseek_evidence,
            'warnings': ([] if quality or scheme != 'C' else ['边界判断器未训练，当前为规则对照'])}
