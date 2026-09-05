"""Experimental local MobileSAM adapter, opt-in and never called by live APIs.

Model code and checkpoint must already exist locally. No downloads, external
inference, hard-coded sample annotations, or image-specific boxes are used.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from core.photo_route_processing import Candidate, Extraction, PhotoProcessingError, MAX_WORKING_EDGE


def inspection_points(parent: Candidate, candidates: list[Candidate], crop: tuple[int, int, int, int],
                      points_per_side: int = 20) -> np.ndarray:
    """Keep the same local grid, but only inspect the selected parent and children.

    Include nested candidates because the parent's visible mask excludes them.
    Do not restrict by saturation: a chalk-covered child may look gray.
    """
    left, top, right, bottom = crop
    region = parent.mask > 0
    px, py, pw, ph = parent.bounds
    for candidate in candidates:
        x, y, w, h = candidate.bounds
        if x >= px - 3 and y >= py - 3 and x + w <= px + pw + 3 and y + h <= py + ph + 3:
            region |= candidate.mask > 0
    points = []
    for y in (np.arange(points_per_side) + .5) / points_per_side:
        for x in (np.arange(points_per_side) + .5) / points_per_side:
            if region[min(bottom - 1, int(top + y * (bottom - top))),
                      min(right - 1, int(left + x * (right - left)))]:
                points.append((x, y))
    return np.asarray(points, dtype=np.float32).reshape(-1, 2)


def matches_route_color(region, color_mask, saturated_mask=None):
    area = np.count_nonzero(region)
    if not area or np.count_nonzero(region & color_mask) / area < .3:
        return False
    if saturated_mask is not None:
        colored_area = np.count_nonzero(region & saturated_mask)
        if colored_area and np.count_nonzero(region & color_mask & saturated_mask) / colored_area < .85:
            return False
    return True


def separate_proposals(proposals, color_mask: np.ndarray, saturated_mask: np.ndarray | None = None) -> list[Candidate]:
    """Remove detached unrelated regions, duplicates and nested-mask double paint.

    This geometric cleanup cannot prove that two touching same-color objects
    are distinct holds. The unresolved cases remain visible for review.
    """
    height, width = color_mask.shape
    minimum_area = max(150, width * height * .0006)
    parts = []
    for proposal in proposals:
        mask = proposal["segmentation"].astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < minimum_area or area > width * height * .35:
                continue
            region = labels == label
            if not matches_route_color(region, color_mask, saturated_mask):
                continue
            parts.append((region, float(proposal["predicted_iou"])))
    parts.sort(key=lambda item: item[1], reverse=True)
    accepted = []
    for region, quality in parts:
        if any(np.count_nonzero(region & other) / max(1, np.count_nonzero(region | other)) > .8 for other, _ in accepted):
            continue
        accepted.append((region, quality))
    candidates = []
    for region, _ in accepted:
        area = np.count_nonzero(region)
        visible = region.copy()
        for child, _ in accepted:
            child_area = np.count_nonzero(child)
            if .05 < child_area / area < .85 and np.count_nonzero(child & region) / child_area > .9:
                visible &= ~child
        count, labels, stats, _ = cv2.connectedComponentsWithStats(visible.astype(np.uint8))
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] < minimum_area:
                continue
            mask = labels == label
            if not matches_route_color(mask, color_mask, saturated_mask):
                continue
            bounds = tuple(int(v) for v in stats[label, :4])
            edge = bool(np.any(mask[0]) or np.any(mask[-1]) or np.any(mask[:, 0]) or np.any(mask[:, -1]))
            if any(np.count_nonzero(mask & (existing.mask > 0)) / np.count_nonzero(mask | (existing.mask > 0)) > .8 for existing in candidates):
                continue
            candidates.append(Candidate(mask.astype(np.uint8) * 255, bounds, edge))
    candidates.sort(key=lambda item: (item.bounds[1], item.bounds[0]))
    return candidates


def extract_with_mobilesam(image: np.ndarray, seed: tuple[float, float], *, checkpoint: Path,
                           cancelled: Callable[[], bool] = lambda: False,
                           timeout_seconds: float = 180, threads: int = 2,
                           prune_inspection: bool = False, batch_size: int = 8,
                           progress: Callable[[str, int], None] = lambda stage, percent: None) -> Extraction:
    started = time.monotonic()

    def check():
        if cancelled():
            raise PhotoProcessingError("识别已取消")
        if time.monotonic() - started >= timeout_seconds:
            raise PhotoProcessingError("识别超过三分钟，请缩小图片或重试")

    if batch_size not in (1, 2, 4, 8):
        raise PhotoProcessingError("本地推理批次必须为 1、2、4 或 8")
    if not checkpoint.is_file():
        raise PhotoProcessingError("本地分割模型不存在，需要先安装模型；不会自动下载或发送照片")
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in seed):
        raise PhotoProcessingError("请选择图片范围内的岩点")
    import torch
    from mobile_sam import SamAutomaticMaskGenerator, sam_model_registry

    torch.set_num_threads(threads)
    torch.manual_seed(0)
    check()
    height, width = image.shape[:2]
    scale = min(1, MAX_WORKING_EDGE / max(height, width))
    work = cv2.resize(image, (round(width * scale), round(height * scale))) if scale < 1 else image.copy()
    height, width = work.shape[:2]
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    x, y = min(width - 1, round(seed[0] * width)), min(height - 1, round(seed[1] * height))
    patch = hsv[max(0, y - 6):y + 7, max(0, x - 6):x + 7]
    pixels = patch[(patch[:, :, 1] >= 65) & (patch[:, :, 2] >= 35)]
    if len(pixels) < 8:
        raise PhotoProcessingError("请点击岩点颜色明显的区域")
    radians = pixels[:, 0].astype(float) * math.pi / 90
    hue = float(math.atan2(np.sin(radians).mean(), np.cos(radians).mean()) * 90 / math.pi) % 180
    distance = np.abs(hsv[:, :, 0].astype(float) - hue)
    distance = np.minimum(distance, 180 - distance)
    color_mask = (distance < 12) & (hsv[:, :, 1] > 75) & (hsv[:, :, 2] > 35)

    # Prompt only inside target-color regions. Use regular sampling plus a
    # distance-transform center per component to cover small isolated holds.
    points = []
    stride = max(20, round(max(width, height) / 32))
    for py in range(stride // 2, height, stride):
        for px in range(stride // 2, width, stride):
            if color_mask[py, px]:
                points.append((px / width, py / height))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(color_mask.astype(np.uint8))
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < max(80, width * height * .0002):
            continue
        component = (labels == label).astype(np.uint8)
        distances = cv2.distanceTransform(component, cv2.DIST_L2, 5)
        _, _, _, (px, py) = cv2.minMaxLoc(distances)
        points.append((px / width, py / height))
    points.append(seed)
    points = np.unique(np.array(points, dtype=np.float32), axis=0)
    check()

    class InterruptibleGenerator(SamAutomaticMaskGenerator):
        def _process_batch(self, *args, **kwargs):
            check()
            result = super()._process_batch(*args, **kwargs)
            check()
            return result

    model = sam_model_registry["vit_t"]()
    progress("载入本地分割模型", 25)
    # Only tensor weights are deserialized, and the device is explicitly CPU.
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.to(device="cpu").eval()
    generator = InterruptibleGenerator(model, points_per_side=None, point_grids=[points],
                                      points_per_batch=batch_size, pred_iou_thresh=.8,
                                      stability_score_thresh=.9, box_nms_thresh=.65,
                                      min_mask_region_area=60)
    progress("按采样颜色识别全图岩点", 35)
    with torch.inference_mode():
        proposals = generator.generate(cv2.cvtColor(work, cv2.COLOR_BGR2RGB))
    check()
    # Large colored objects can carry small chalk-covered holds. Inspect them
    # at a higher effective resolution instead of encoding a sample-specific
    # location or assuming that everything attached has saturated route color.
    coarse = separate_proposals(proposals, color_mask)
    regions = [c for c in coarse if np.count_nonzero(c.mask) > width * height * .03]
    regions.sort(key=lambda c: np.count_nonzero(c.mask), reverse=True)
    for region_index, parent in enumerate(regions[:3]):
        progress(f"局部放大精修 {region_index + 1}/{min(3, len(regions))}", 45 + region_index * 5)
        check()
        left, top, box_width, box_height = parent.bounds
        padding = max(24, round(min(box_width, box_height) * .35))
        l, t = max(0, left - padding), max(0, top - padding)
        r, b = min(width, left + box_width + padding), min(height, top + box_height + padding)
        if prune_inspection:
            local_points = inspection_points(parent, coarse, (l, t, r, b))
            if not len(local_points):
                continue
            point_settings = {"points_per_side": None, "point_grids": [local_points]}
        else:
            # Retain the v5 control experiment: pruning changes proposal NMS and
            # must not silently replace it before contour validation.
            point_settings = {"points_per_side": 20}
        crop_generator = InterruptibleGenerator(model, **point_settings, points_per_batch=batch_size,
                                                pred_iou_thresh=.8, stability_score_thresh=.9,
                                                box_nms_thresh=.65, min_mask_region_area=30)
        with torch.inference_mode():
            details = crop_generator.generate(cv2.cvtColor(work[t:b, l:r], cv2.COLOR_BGR2RGB))
        for detail in details:
            local_mask = detail["segmentation"]
            area = np.count_nonzero(local_mask)
            if not area:
                continue
            # Artificial crop edges must never create new partial holds.
            # The full-image proposals already represent objects crossing this
            # local inspection window; only fully contained details are useful.
            if (np.any(local_mask[:3]) or np.any(local_mask[-3:])
                    or np.any(local_mask[:, :3]) or np.any(local_mask[:, -3:])):
                continue
            global_mask = np.zeros((height, width), dtype=bool)
            global_mask[t:b, l:r] = local_mask
            # Gray/low-saturation candidates are only proposed if they are
            # inside an already selected object and retain its hue evidence.
            weak = (distance < 12) & (hsv[:, :, 1] >= 15) & (hsv[:, :, 2] > 35)
            if np.count_nonzero(global_mask & color_mask) / area < .3:
                if (area > np.count_nonzero(parent.mask) * .2
                        or np.count_nonzero(global_mask & (parent.mask > 0)) / area < .9
                        or np.count_nonzero(global_mask & weak) / area < .5):
                    continue
                color_mask |= global_mask & weak
            proposals.append({**detail, "segmentation": global_mask})
    check()
    saturated = (hsv[:, :, 1] > 75) & (hsv[:, :, 2] > 35)
    progress("去重并分离相邻对象", 62)
    candidates = separate_proposals(proposals, color_mask, saturated)
    return Extraction(work, candidates, hue, time.monotonic() - started,
                      ["实验性本地模型结果，需要检查重复、粘连和漏选", "没有推断起终点、线路完整性或不可见纹理"])
