"""Offline evaluation; defaults to the climbing instance model and interior-v4 colors."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.photo_route_analysis import analyze_board_photo, fingerprint_payload
from core.photo_route_colors import CANDIDATE_COLOR_VERSION, COLOR_VERSIONS, classify_mask_color
from core.photo_route_evaluation import evaluate_objects, summarize, mask_for_object
from core.photo_route_processing import decode_photo


MAX_P95_SECONDS = 180
MAX_SINGLE_SECONDS = 300
MIN_BOUNDARY_F1 = .75


class PeakProcessMemory:
    """Sample this evaluator process RSS while one image is processed."""
    def __init__(self, interval=.02):
        self.interval = interval
        self.peak_bytes = 0
        self.measurement_complete = True
        self._stop = threading.Event()
        self._thread = None

    def _sample_once(self):
        try:
            import psutil
            current = psutil.Process(os.getpid()).memory_info().rss
        except ImportError:
            current = self._native_high_water_bytes()
        self.peak_bytes = max(self.peak_bytes, current)

    @staticmethod
    def _native_high_water_bytes():
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                            ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                            ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                            ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            process = kernel32.GetCurrentProcess()
            if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                raise OSError('无法读取进程内存')
            return int(counters.PeakWorkingSetSize)
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == 'darwin' else peak * 1024)

    def _sample(self):
        try:
            while not self._stop.is_set():
                try:
                    self._sample_once()
                except Exception:
                    self.measurement_complete = False
                self._stop.wait(self.interval)
        except Exception:
            self.measurement_complete = False

    def __enter__(self):
        try:
            self._sample_once()
        except Exception:
            self.measurement_complete = False
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join(timeout=1)


def _data_path(root, relative, label):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'{label}不存在或越过清单目录')
    return path


def validate_manifest(manifest, root):
    """Reject scene/source/hash leakage before running inference, including crops."""
    if not isinstance(manifest.get('samples'), list):
        raise ValueError('清单缺少 samples')
    seen = {}
    blockers = []
    for sample in manifest['samples']:
        split = sample.get('split', 'holdout' if sample.get('holdout') else 'validation')
        if split not in ('train', 'validation', 'holdout'):
            raise ValueError('未知数据集合')
        if 'holdout' in sample and bool(sample['holdout']) != (split == 'holdout'):
            raise ValueError('split 与 holdout 标记冲突')
        image_path = _data_path(root, sample['image'], '照片')
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if sample.get('image_sha256') and sample['image_sha256'] != digest:
            raise ValueError('照片摘要与清单不符')
        for key in [('sha256', digest), ('source', sample.get('source_id')), ('scene', sample.get('scene_id'))]:
            if key[1] is None: continue
            if key in seen and seen[key] != split:
                raise ValueError('同一照片、裁片或场景跨越训练/验证/留出集合')
            seen[key] = split
        sample['_split'] = split
        sample['_sha256'] = digest
        if sample.get('image_sha256') != digest:
            blockers.append(f"{sample['image']}: 缺少已锁定的照片摘要")
        if not (sample.get('human_reviewed') is True and sample.get('complete') is True
                and sample.get('scene_id') and sample.get('source_id')):
            blockers.append(f"{sample['image']}: 缺少完整人工复核、场景或来源标记")
        if sample.get('annotations_available') is False or sample.get('evaluation_exclusion'):
            blockers.append(f"{sample['image']}: 正式清单不能跳过标注或排除照片")
        for obj in sample['objects']:
            if obj.get('kind') not in ('hold', 'volume'):
                raise ValueError('标注类别必须明确映射为 hold 或 volume')
            conditions = obj.get('conditions', [])
            if not isinstance(conditions, list) or any(value not in ('low_saturation', 'shadow', 'chalk') for value in conditions):
                raise ValueError('conditions 仅允许 low_saturation、shadow、chalk')
            if not obj.get('color_group'):
                raise ValueError('每个实例都必须标注颜色，无法确定时填写待确认')
    counted = [s for s in manifest['samples'] if s['_split'] in ('validation', 'holdout')]
    holdouts = [s for s in counted if s['_split'] == 'holdout']
    validations = [s for s in counted if s['_split'] == 'validation']
    if not 5 <= len(counted) <= 10:
        blockers.append(f'完整评测照片须为 5–10 张，当前 {len(counted)} 张')
    if len({s['_sha256'] for s in counted}) != len(counted):
        blockers.append('评测清单包含重复照片')
    if len(validations) < 3:
        blockers.append(f'验证照片至少 3 张，当前 {len(validations)} 张')
    if len(holdouts) < 2:
        blockers.append(f'独立留出照片至少 2 张，当前 {len(holdouts)} 张')
    if len({s.get('scene_id') for s in holdouts if s.get('scene_id')}) < 2:
        blockers.append('独立留出集须覆盖至少 2 个场景')
    if any(s.get('model_training_overlap') is not False for s in holdouts):
        blockers.append('留出照片尚未逐张排除模型训练重合')
    if any(s.get('algorithm_tuning_overlap') is not False for s in holdouts):
        blockers.append('留出照片尚未逐张排除算法或阈值调参重合')
    return {'eligible': not blockers, 'blockers': blockers,
            'validation_images': len(validations), 'holdout_images': len(holdouts),
            'unique_images': len({s['_sha256'] for s in counted}),
            'holdout_scenes': len({s.get('scene_id') for s in holdouts if s.get('scene_id')})}


def evaluate(manifest_path: Path, *, mode='climbing', color_version=CANDIDATE_COLOR_VERSION,
             boundary_refinement=True, split='validation', tolerance=2, locked_config=None,
             max_peak_memory_bytes=None) -> dict:
    if mode not in ('climbing', 'mobilesam', 'coarse', 'saved') or color_version not in COLOR_VERSIONS:
        raise ValueError('未知评测配置')
    if split not in ('validation', 'holdout') or not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError('评测集合或边界容差无效')
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    code_root = Path(__file__).resolve().parents[1]
    source_hashes = {name: hashlib.sha256((code_root / name).read_bytes()).hexdigest()
        for name in ('core/photo_route_analysis.py', 'core/photo_route_colors.py',
                     'core/photo_route_boundaries.py', 'core/photo_route_evaluation.py',
                     'core/photo_route_instance_masks.py',
                     'scripts/evaluate_photo_route_v2.py')}
    checkpoint_variable = ('PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT' if mode == 'climbing'
                           else 'PHOTO_ROUTE_MOBILESAM_CHECKPOINT')
    checkpoint = Path(os.getenv(checkpoint_variable, ''))
    model_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest() if mode in ('climbing', 'mobilesam') and checkpoint.is_file() else None
    climbing_config = Path(os.getenv('PHOTO_ROUTE_CLIMBING_MODEL_CONFIG', ''))
    climbing_config_digest = (hashlib.sha256(climbing_config.read_bytes()).hexdigest()
                              if mode == 'climbing' and climbing_config.is_file() else None)
    effective_boundary_refinement = False if mode == 'climbing' else boundary_refinement
    if max_peak_memory_bytes is not None and (type(max_peak_memory_bytes) is not int or max_peak_memory_bytes <= 0):
        raise ValueError('内存上限必须为正整数字节')
    config = {'mode': mode, 'color_version': color_version,
              'boundary_refinement': 'preserved-from-saved-masks' if mode=='saved' else effective_boundary_refinement,
              'boundary_tolerance_px': tolerance, 'matching': 'maximum-cardinality-iou-0.5-v2-kind-aware',
              'source_sha256': source_hashes, 'checkpoint_sha256': model_digest,
              'climbing_config_sha256': climbing_config_digest,
              'runtime': {'python': sys.version, 'opencv': cv2.__version__, 'numpy': np.__version__},
              'quality_gates': {'object_precision': .9, 'object_recall': .9, 'color_accuracy': .9,
                                'boundary_f1': MIN_BOUNDARY_F1, 'severe_contour_failures': 0,
                                'p95_seconds': MAX_P95_SECONDS, 'max_seconds': MAX_SINGLE_SECONDS,
                                'max_peak_memory_bytes': max_peak_memory_bytes},
              'saved_model_version': manifest.get('saved_model_version') if mode == 'saved' else None}
    if split == 'holdout' and locked_config != config:
        raise ValueError('留出评测需要与验证时完全一致的锁定配置')
    dataset_audit = validate_manifest(manifest, manifest_path.parent)
    samples = [s for s in manifest['samples'] if s['_split'] == split and s.get('annotations_available', True)
               and not s.get('evaluation_exclusion')]
    if not samples: raise ValueError('所选集合没有照片')
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        for number, sample in enumerate(samples):
            image_path = _data_path(manifest_path.parent, sample['image'], '照片')
            image = decode_photo(image_path.read_bytes())
            started = time.monotonic()
            with PeakProcessMemory() as memory:
                if mode == 'saved':
                    prediction_path = _data_path(manifest_path.parent, sample['prediction'], '预测结果')
                    result = json.loads(prediction_path.read_text(encoding='utf-8'))
                    if result.get('input_fingerprint') != sample['_sha256']:
                        raise ValueError('预测结果不属于当前原图')
                    if not result.get('model_version'):
                        raise ValueError('预测结果缺少模型版本')
                    if manifest.get('saved_model_version') != result['model_version']:
                        raise ValueError('保存的模型版本与评测清单不一致')
                    for obj in result['objects']:
                        obj['color_group'] = classify_mask_color(
                            image, mask_for_object(obj, image.shape[:2]), version=color_version)
                else:
                    result = analyze_board_photo(image_path, Path(directory) / str(number),
                        require_mobilesam=mode == 'mobilesam', coarse_only=mode == 'coarse',
                        require_climbing_model=mode == 'climbing', color_version=color_version,
                        boundary_refinement=effective_boundary_refinement)
            row = evaluate_objects(sample['objects'], result['objects'], image.shape[:2], tolerance)
            row.update({'image': sample['image'], 'split': split, 'image_sha256': sample['_sha256'],
                        'model_version': result['model_version'], 'processing_config': result.get('processing_config'),
                        'resolution': [image.shape[1], image.shape[0]], 'seconds': time.monotonic()-started,
                        'peak_process_bytes': memory.peak_bytes,
                        'memory_measurement_complete': memory.measurement_complete,
                        'memory_scope': 'evaluator-process-rss-or-os-high-water',
                        'memory_sampling_interval_ms': int(memory.interval * 1000),
                        'timing_scope': 'saved-contours-recolor-and-metrics' if mode == 'saved' else 'inference-and-metrics'})
            rows.append(row)
    report = summarize(rows)
    seconds = [row['seconds'] for row in rows]
    memory_values = [row['peak_process_bytes'] for row in rows]
    performance = {
        'p95_seconds': float(np.percentile(seconds, 95)),
        'max_seconds': max(seconds),
        'peak_process_bytes': max(memory_values),
        'memory_limit_bytes': max_peak_memory_bytes,
        'memory_measurement_complete': all(row['memory_measurement_complete'] and row['peak_process_bytes'] > 0
                                           for row in rows),
        'scope': 'per-image inference, color classification, metrics, and evaluator process RSS/HWM',
    }
    reviewed = all(s.get('human_reviewed') is True and s.get('complete') is True
                   for s in manifest['samples'] if s['_split'] in ('validation', 'holdout'))
    report.update({'schema_version': 2, 'config': config, 'config_sha256': fingerprint_payload(config),
                   'split': split, 'human_reviewed': reviewed,
                   'formal_dataset_eligible': dataset_audit['eligible'], 'dataset_audit': dataset_audit,
                   'performance': performance,
                   'per_image': rows, 'passed': False,
                   'unannotated_samples_skipped': sum(s['_split'] == split and not s.get('annotations_available', True) for s in manifest['samples']),
                   'excluded_samples': [{'image':s['image'],'reason':s['evaluation_exclusion']} for s in manifest['samples'] if s.get('evaluation_exclusion')],
                   'limitations': ['本报告只验收识别链路；保存、重开、服务重启和目标服务并发仍须单独通过。']})
    blockers = list(dataset_audit['blockers'])
    gates = {
        'holdout_split': split == 'holdout',
        'object_precision': (report['object_precision'] or 0) >= .9,
        'object_recall': (report['object_recall'] or 0) >= .9,
        'color_accuracy': (report['color_accuracy'] or 0) >= .9,
        'boundary_f1': (report['boundary_f1'] or 0) >= MIN_BOUNDARY_F1,
        'severe_contour_failures': report['severe_contour_failures'] == 0,
        'p95_seconds': performance['p95_seconds'] <= MAX_P95_SECONDS,
        'max_seconds': performance['max_seconds'] <= MAX_SINGLE_SECONDS,
        'memory_measured': performance['memory_measurement_complete'],
        'memory_budget_configured': max_peak_memory_bytes is not None,
        'peak_memory': (max_peak_memory_bytes is not None
                        and performance['peak_process_bytes'] <= max_peak_memory_bytes),
    }
    labels = {'holdout_split': '报告不是独立留出集', 'object_precision': '实例精确率低于 90%',
              'object_recall': '实例召回率低于 90%', 'color_accuracy': '颜色准确率低于 90%',
              'boundary_f1': '边界 F1 低于 0.75', 'severe_contour_failures': '存在严重轮廓错误',
              'p95_seconds': 'P95 算法耗时超过 180 秒', 'max_seconds': '单张算法耗时超过 300 秒',
              'memory_measured': '识别进程内存测量不完整',
              'memory_budget_configured': '未配置目标环境内存上限', 'peak_memory': '峰值内存超过目标上限'}
    blockers.extend(labels[key] for key, passed in gates.items() if not passed)
    report['quality_gates'] = gates
    report['gate_blockers'] = list(dict.fromkeys(blockers))
    report['absolute_metric_gates_met'] = all(gates.values())
    report['validation_ready_to_lock'] = bool(dataset_audit['eligible']
        and all(value for key, value in gates.items() if key != 'holdout_split'))
    report['full_plan_passed'] = False
    report['passed'] = bool(dataset_audit['eligible'] and report['absolute_metric_gates_met'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=['climbing', 'mobilesam', 'coarse', 'saved'], default='climbing')
    parser.add_argument('--color-version', choices=COLOR_VERSIONS, default=CANDIDATE_COLOR_VERSION)
    parser.add_argument('--no-boundary-refinement', action='store_true')
    parser.add_argument('--split', choices=['validation', 'holdout'], default='validation')
    parser.add_argument('--boundary-tolerance', type=int, default=2)
    parser.add_argument('--max-peak-memory-mb', type=int, help='目标运行环境允许的识别进程峰值内存')
    parser.add_argument('--locked-config', type=Path, help='验证报告或其中导出的 config JSON')
    parser.add_argument('--write-lock', type=Path, help='验证后新建配置锁文件；已有文件不会覆盖')
    parser.add_argument('--audit-only', action='store_true', help='只检查数据隔离和标注完整性，不运行模型')
    args = parser.parse_args()
    if args.audit_only:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        audit = validate_manifest(manifest, args.manifest.resolve().parent)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        raise SystemExit(0 if audit['eligible'] else 2)
    locked = None
    if args.locked_config:
        locked = json.loads(args.locked_config.read_text(encoding='utf-8'))
        locked = locked.get('config', locked)
    report = evaluate(args.manifest, mode=args.mode, color_version=args.color_version,
        boundary_refinement=not args.no_boundary_refinement, split=args.split, tolerance=args.boundary_tolerance,
        locked_config=locked,
        max_peak_memory_bytes=args.max_peak_memory_mb * 1024 * 1024 if args.max_peak_memory_mb else None)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(text + '\n')
    if args.write_lock:
        if args.split != 'validation':
            raise ValueError('只能从验证集报告写出配置锁')
        if not report['validation_ready_to_lock']:
            raise ValueError('验证集质量、边界、耗时或内存门禁未通过，不能锁定配置')
        args.write_lock.parent.mkdir(parents=True, exist_ok=True)
        with args.write_lock.open('x', encoding='utf-8') as stream:
            json.dump(report['config'], stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    print(text)
    raise SystemExit(0 if report['passed'] else 2)


if __name__ == '__main__': main()
