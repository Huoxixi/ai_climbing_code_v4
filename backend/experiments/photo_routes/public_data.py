"""Import public VIA annotations, retaining their limitations and source licence."""
import io
import shutil
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path

from .data import read_json, write_new, image_size, digest_file
from .geometry import local_mask

SOURCE = 'https://www.kaggle.com/datasets/tomasslama/indoor-climbing-gym-hold-segmentation'
COMMIT = '27ba65fcc2982e6d01e7556f1882df72e5fb1f46'


def fetch_image(group, filename, destination):
    if Path(filename).name != filename or group not in ('bh', 'bh-phone', 'sm'):
        raise ValueError('未知公开图片路径')
    endpoint = 'https://www.kaggle.com/api/v1/datasets/download/tomasslama/indoor-climbing-gym-hold-segmentation/'
    url = endpoint + urllib.parse.quote(group+'/'+filename, safe='')
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(20*1024*1024+1)
    if len(data) > 20*1024*1024:
        raise ValueError('下载响应超过 20 MB，未下载整个数据集')
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [m for m in archive.infolist() if Path(m.filename).name == filename]
            if len(members) != 1 or members[0].file_size > 20*1024*1024:
                raise ValueError('单图片压缩包内容不符')
            data = archive.read(members[0])
    with Path(destination).open('xb') as stream:
        stream.write(data)
    image_size(destination)


def import_indoor(source_root, output, download=False, training_pilot=False, image_cache=None):
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    samples, skipped, counts = [], [], {}
    for group in ('bh', 'bh-phone', 'sm'):
        annotation = source_root/f'{group}-annotation.json'
        if not annotation.is_file():
            skipped.append({'group': group, 'reason': '缺少本地公开 VIA 标注文件'})
            continue
        records = read_json(annotation)['_via_img_metadata'].values()
        for record in records:
            regions = record.get('regions', [])
            manual = [r for r in regions if r.get('region_attributes', {}).get('label_type') == 'handlabeled']
            if not manual:
                continue
            filename = record['filename']
            if Path(filename).name != filename:
                raise ValueError('标注中的图片路径不是文件名')
            counts[group] = counts.get(group, 0)+1
            target = output/f'{group}-{filename}'
            try:
                local = source_root/group/filename
                if not local.is_file() and image_cache:
                    local = Path(image_cache)/f'{group}-{filename}'
                if local.is_file():
                    with local.open('rb') as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                elif download:
                    fetch_image(group, filename, target)
                else:
                    raise ValueError('图片尚未下载')
                width, height = image_size(target)
                objects, routes = [], {}
                for region in manual:
                    attributes = region['region_attributes']
                    kind = attributes.get('hold_type')
                    if kind not in ('hold', 'volume'):
                        raise ValueError(f'未映射类别: {kind}')
                    points = region['shape_attributes']
                    if points.get('name') != 'polygon' or len(points['all_points_x']) != len(points['all_points_y']):
                        raise ValueError('不是有效多边形标注')
                    obj = {'id': f'object-{len(objects)+1:03d}', 'kind': kind, 'color_group': '待确认',
                           'contour': list(map(list, zip(points['all_points_x'], points['all_points_y'])))}
                    local_mask(obj, (height, width))
                    objects.append(obj)
                    route = attributes.get('route_id')
                    if route not in (None, ''):
                        routes.setdefault(str(route), []).append(obj['id'])
                if len(objects) > 300:
                    raise ValueError(f'{len(objects)} 个对象超过本期 300 上限，需人工分区')
                samples.append({'id': f'{group}-{Path(filename).stem}', 'image': target.name,
                    'image_sha256': digest_file(target), 'size': [width, height],
                    'split': 'train' if training_pilot else 'diagnostic',
                    # Conservatively group all views from one gym: no invented wall IDs.
                    'wall_id': 'upstream-bh-unknown-wall' if group.startswith('bh') else 'upstream-sm-unknown-wall',
                    'scene_id': 'upstream-bh' if group.startswith('bh') else 'upstream-sm',
                    'source_id': f'indoor-{group}-{filename}', 'human_reviewed': True,
                    'complete': False, 'annotation_origin': 'upstream-handlabeled-not-locally-verified',
                    'route_truth_confirmed_by': 'upstream VIA route_id' if routes else None,
                    'ambiguity_labeled_before_predictions': False, 'model_training_overlap': True,
                    'provenance': {'source': SOURCE, 'license': 'CC-BY-SA-4.0 (dataset metadata)',
                                   'commercial_training_allowed': True,
                                   'annotation_sha256': digest_file(annotation), 'upstream_commit': COMMIT},
                    'objects': objects, 'routes': [{'id': rid, 'member_ids': members, 'decidable': True,
                        'annotation_origin': 'upstream-route-id-not-local-acceptance'} for rid, members in routes.items()]})
                print({'imported': samples[-1]['id'], 'objects': len(objects), 'routes': len(routes)}, flush=True)
            except (ValueError, OSError) as exc:
                # Remove only the copy created inside this new import package;
                # the upstream public dataset remains unchanged.
                target.unlink(missing_ok=True)
                skipped.append({'image': f'{group}/{filename}', 'reason': str(exc)})
    manifest = {'schema_version': 1, 'purpose': 'public-training-pilot' if training_pilot else 'public-diagnostic',
                'samples': samples}
    write_new(output/'manifest.json', manifest)
    report = {'available_annotation_images': counts, 'imported': len(samples),
              'route_annotated_images': sum(bool(s['routes']) for s in samples), 'skipped': skipped,
              'source': SOURCE, 'license': 'CC-BY-SA-4.0', 'formal_acceptance_eligible': False,
              'limitations': ['无人工颜色标签', '无事先歧义标注', '墙面身份未核实',
                              '专项公开模型可能已见过这些照片', '不能替代 200 张/10 面墙独立验收集']}
    write_new(output/'import-report.json', report)
    return report
