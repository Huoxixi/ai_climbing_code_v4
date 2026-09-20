"""Dataset contracts and immutable evidence; never infer human ground truth."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

MAX_PIXELS = 12_000_000
MAX_OBJECTS = 300
KINDS = ('hold', 'volume')


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def source_digest():
    root = Path(__file__).parent
    files = {p.name: digest_file(p) for p in sorted(root.glob('*.py'))}
    for name in ('photo_route_instance_masks.py', 'photo_route_evaluation.py', 'photo_route_colors.py'):
        files[name] = digest_file(root.parents[1] / 'core' / name)
    return digest_json(files)


def image_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'图片不存在或越过数据目录: {relative}')
    return path


def image_size(path):
    with Image.open(path) as im:
        if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('仅支持静态 JPEG、PNG、WebP')
        if min(im.size) < 32 or im.width * im.height > MAX_PIXELS:
            raise ValueError('照片须为 32 像素以上且不超过 1200 万像素')
        if Path(path).stat().st_size > 20 * 1024 * 1024:
            raise ValueError('照片超过 20 MB')
        # Coordinates and masks always refer to the EXIF-upright image.
        return im.size[::-1] if im.getexif().get(274) in (5, 6, 7, 8) else im.size


def load_image(path):
    import cv2
    import numpy as np
    image_size(path)  # Check before decoding a potentially huge image.
    with Image.open(path) as im:
        upright = ImageOps.exif_transpose(im)
        if upright.mode == 'RGBA' or 'transparency' in upright.info:
            rgba = upright.convert('RGBA')
            background = Image.new('RGBA', rgba.size, 'white')
            upright = Image.alpha_composite(background, rgba)
        return cv2.cvtColor(np.asarray(upright.convert('RGB')), cv2.COLOR_RGB2BGR)


def write_image_new(path, image):
    """OpenCV's filename writer does not support every Windows Unicode path."""
    import cv2
    ok, encoded = cv2.imencode(Path(path).suffix, image)
    if not ok:
        raise OSError('图片编码失败')
    with Path(path).open('xb') as stream:
        stream.write(encoded.tobytes())


def audit_manifest(path):
    """Strict new contract; existing legacy manifests are not rewritten."""
    manifest = read_json(path)
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('samples'), list):
        raise ValueError('需要 schema_version=1 的离线对照清单')
    root = Path(path).resolve().parent
    ids, seen, errors, splits, walls = set(), {}, [], Counter(), set()
    digests = {}
    for sample in manifest['samples']:
        sid = sample['id']
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError('照片 ID 必须非空且唯一')
        ids.add(sid)
        split = sample['split']
        if split not in ('train', 'validation', 'holdout', 'diagnostic'):
            raise ValueError('未知数据集合')
        photo = image_path(root, sample['image'])
        width, height = image_size(photo)
        digest = digest_file(photo)
        digests[sid] = digest
        if sample.get('image_sha256') != digest:
            raise ValueError(f'{sid}: 图片 SHA256 缺失或不一致')
        for key in ('wall_id', 'scene_id', 'source_id'):
            if not sample.get(key):
                raise ValueError(f'{sid}: 缺少 {key}')
        for key, value in [('image', digest)] + [(k, sample[k]) for k in ('wall_id', 'scene_id', 'source_id')]:
            if (key, value) in seen and seen[key, value] != split:
                raise ValueError(f'{sid}: 同一图片、墙面、场景或来源跨集合')
            seen[key, value] = split
        if list(sample.get('size', [])) != [width, height]:
            raise ValueError(f'{sid}: size 必须是 EXIF 校正后的 [宽,高]')
        objects = sample.get('objects', [])
        if len(objects) > MAX_OBJECTS:
            raise ValueError(f'{sid}: 对象超过 300，请拆分照片')
        object_ids = [o['id'] for o in objects]
        if len(set(object_ids)) != len(object_ids) or any(not isinstance(i, str) or not i for i in object_ids):
            raise ValueError('对象 ID 必须非空且唯一')
        for obj in objects:
            if obj.get('kind') not in KINDS or not ('mask_rle' in obj or 'contour' in obj):
                raise ValueError(f'{sid}: 对象必须有类别及可见掩膜')
            from .geometry import local_mask
            local_mask(obj, (height, width))
            if not obj.get('color_group'):
                raise ValueError(f'{sid}: 必须标注颜色，无法确定时填写待确认')
        route_ids = set()
        for route in sample.get('routes', []):
            if not route.get('id') or route['id'] in route_ids:
                raise ValueError(f'{sid}: 线路 ID 缺失或重复')
            route_ids.add(route['id'])
            members = route.get('member_ids', [])
            if not members or len(set(members)) != len(members) or not set(members) <= set(object_ids):
                raise ValueError(f'{sid}: 线路成员为空、重复或不存在')
            if type(route.get('decidable')) is not bool:
                raise ValueError(f'{sid}: 线路须预先标明 decidable')
            if not route['decidable'] and not route.get('reason'):
                raise ValueError(f'{sid}: 不可判定线路须说明原因')
        if split != 'diagnostic':
            splits[split] += 1
            walls.add(sample['wall_id'])
            if not (sample.get('human_reviewed') is True and sample.get('complete') is True
                    and sample.get('route_truth_confirmed_by') and sample.get('routes')
                    and sample.get('ambiguity_labeled_before_predictions') is True):
                errors.append(f'{sid}: 缺少完整人工轮廓/线路确认或事先歧义标注')
            provenance = sample.get('provenance', {})
            if provenance.get('commercial_training_allowed') is not True or not provenance.get('source') or not provenance.get('license'):
                errors.append(f'{sid}: 数据来源及商业训练许可未确认')
        if split == 'holdout' and sample.get('model_training_overlap') is not False:
            errors.append(f'{sid}: 尚未排除模型训练重合')
    if len(set(digests.values())) != len(digests):
        raise ValueError('重复照片不能重复计入数据量')
    for split, count in (('train', 120), ('validation', 40), ('holdout', 40)):
        if splits[split] < count:
            errors.append(f'{split}: {splits[split]}/{count} 张')
    if len(walls) < 10:
        errors.append(f'独立墙面: {len(walls)}/10')
    holdout_walls = {s['wall_id'] for s in manifest['samples'] if s['split'] == 'holdout'}
    if len(holdout_walls) < 3:
        errors.append(f'留出墙面: {len(holdout_walls)}/3')
    return manifest, {'eligible': not errors, 'blockers': errors, 'counts': dict(splits),
                      'walls': len(walls), 'holdout_walls': len(holdout_walls),
                      'manifest_sha256': digest_json(manifest), 'image_sha256': digests}
