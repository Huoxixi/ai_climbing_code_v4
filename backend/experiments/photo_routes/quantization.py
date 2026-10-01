"""Static QDQ INT8 calibration using training images only; never claim parity."""
import copy
from pathlib import Path

import cv2
import numpy as np

from .data import read_json, write_new, load_image, image_path, digest_file
from .geometry import tiles, local_mask
from .inference import check_recipe, roi_input, verify_artifact
from .training import training_samples


def quantize_recipe(manifest_path, recipe_path, output):
    import onnxruntime as ort
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static
    samples, audit = training_samples(manifest_path)
    recipe_path, output = Path(recipe_path).resolve(), Path(output).resolve()
    recipe = check_recipe(read_json(recipe_path), recipe_path.parent)
    if recipe['precision'] != 'fp32':
        raise ValueError('量化输入必须为 FP32 recipe')
    root = Path(manifest_path).resolve().parent
    output.mkdir(parents=True, exist_ok=False)
    result = copy.deepcopy(recipe)
    result['precision'] = 'int8'
    for key in ('detector', 'segmenter', 'palette', 'relation', 'quality'):
        if not recipe.get(key):
            continue
        spec = recipe[key]
        path = verify_artifact(recipe_path.parent, spec)
        if key not in ('detector', 'segmenter'):
            result[key]['path'] = str(path)
            continue
        session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        input_name = session.get_inputs()[0].name
        del session

        class Reader(CalibrationDataReader):
            def __init__(self):
                self.items = self.generate()

            def generate(self):
                count = 0
                for sample in samples:
                    image = load_image(image_path(root, sample['image']))
                    if key == 'detector':
                        for x, y, w, h in tiles(image.shape[1], image.shape[0]):
                            crop = cv2.resize(image[y:y+h, x:x+w], (640, 640)).astype(np.float32)
                            if spec['color_order'] == 'rgb':
                                crop = crop[:, :, ::-1]
                            tensor = (crop-np.asarray(spec['mean'], np.float32))/np.asarray(spec['std'], np.float32)
                            yield {input_name: np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])}
                            count += 1
                            if count >= 128:
                                return
                    else:
                        for obj in sample['objects']:
                            (x, y), mask = local_mask(obj, image.shape[:2])
                            tensor, _ = roi_input(image, [x, y, mask.shape[1], mask.shape[0]])
                            yield {input_name: tensor}
                            count += 1
                            if count >= 128:
                                return

            def get_next(self):
                return next(self.items, None)

        destination = output/f'{key}-int8.onnx'
        quantize_static(str(path), str(destination), Reader(), quant_format=QuantFormat.QDQ,
                        activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                        op_types_to_quantize=['Conv', 'MatMul'], per_channel=True)
        result[key].update(path=destination.name, sha256=digest_file(destination), quantized_from=spec['sha256'])
    write_new(output/'recipe-int8.json', result)
    report = {'calibration_manifest_sha256': audit['manifest_sha256'],
              'calibration_split': 'train', 'quality_parity_verified': False,
              'next': '同验证集运行 FP32/INT8，再 compare-int8；最大允许下降 1 个百分点'}
    write_new(output/'quantization-report.json', report)
    return report
