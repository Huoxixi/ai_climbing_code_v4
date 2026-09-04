"""Local background cleanup, separate from original photos and route cutouts.

The repaired wall is a derived visualization, not recovered hidden texture.
Callers must review removal masks; segmentation alone supplies no route labels.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math

import cv2
import numpy as np
from core.photo_route_processing import PhotoProcessingError


@dataclass
class WallCleanup:
    background: np.ndarray
    composite: np.ndarray
    repair_mask: np.ndarray
    display_repair_mask: np.ndarray


def prepare_repair_mask(image: np.ndarray, removal_mask: np.ndarray,
                        target_mask: np.ndarray, margin: int = 6,
                        preserve_mask: np.ndarray | None = None) -> np.ndarray:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise PhotoProcessingError('背景处理需要有效的三通道图片')
    for mask in (removal_mask, target_mask) + ((preserve_mask,) if preserve_mask is not None else ()):
        if mask.ndim != 2 or mask.shape != image.shape[:2]:
            raise PhotoProcessingError('背景选区与原图尺寸不一致，请重新生成选区')
        if mask.dtype not in (np.dtype('uint8'), np.dtype('bool')):
            raise PhotoProcessingError('背景选区必须为二值蒙版')
    if not np.any(target_mask):
        raise PhotoProcessingError('请先确认至少一个目标线路对象')
    if not isinstance(margin, int) or not 0 <= margin <= 40:
        raise PhotoProcessingError('背景修补边缘范围无效')
    mask = ((removal_mask > 0) | (target_mask > 0)).astype(np.uint8) * 255
    if margin:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin * 2 + 1, margin * 2 + 1))
        mask = cv2.dilate(mask, kernel)
    if preserve_mask is not None:
        mask[(preserve_mask > 0) & (target_mask == 0)] = 0
    if np.mean(mask > 0) > .85:
        raise PhotoProcessingError('选区覆盖了大部分画面，缺少可靠的墙面参考，请缩小修补范围')
    return mask


def composite_wall(image: np.ndarray, repair_mask: np.ndarray, target_mask: np.ndarray,
                   prediction: np.ndarray) -> WallCleanup:
    """Only repaired pixels may change; route pixels are copied from the photo."""
    if prediction.shape != image.shape or prediction.dtype != np.uint8:
        raise PhotoProcessingError('修补模型没有返回有效图片')
    repaired = repair_mask > 0
    protected = target_mask > 0
    background = image.copy()
    background[repaired] = prediction[repaired]
    composite = background.copy()
    composite[protected] = image[protected]
    return WallCleanup(background, composite, repair_mask.copy(),
                       (repaired & ~protected).astype(np.uint8) * 255)


def restore_wall(image: np.ndarray, removal_mask: np.ndarray, target_mask: np.ndarray, *,
                 method: str = 'opencv', checkpoint: Path | None = None,
                 margin: int = 6, working_edge: int = 768,
                 preserve_mask: np.ndarray | None = None) -> WallCleanup:
    repair_mask = prepare_repair_mask(image, removal_mask, target_mask, margin, preserve_mask)
    if not isinstance(working_edge, int) or not 256 <= working_edge <= 1024:
        raise PhotoProcessingError('背景修补工作尺寸必须在 256–1024 之间')
    height, width = image.shape[:2]
    ratio = min(1, working_edge / max(height, width))
    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    work = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    mask = (cv2.resize(repair_mask, size, interpolation=cv2.INTER_AREA) > 0).astype(np.uint8) * 255
    if method == 'opencv':
        prediction = cv2.inpaint(work, mask, 5, cv2.INPAINT_TELEA)
    elif method == 'lama':
        if checkpoint is None or not checkpoint.is_file():
            raise PhotoProcessingError('缺少本地背景修补模型；不会自动联网下载')
        import torch
        torch.set_num_threads(2)
        # Load only an explicitly installed trusted local TorchScript artifact.
        model = torch.jit.load(str(checkpoint), map_location='cpu').eval()
        ph = math.ceil(work.shape[0] / 8) * 8 - work.shape[0]
        pw = math.ceil(work.shape[1] / 8) * 8 - work.shape[1]
        rgb = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
        rgb = np.pad(rgb, ((0, ph), (0, pw), (0, 0)), mode='symmetric')
        padded_mask = np.pad(mask, ((0, ph), (0, pw)), mode='symmetric')
        pixels = torch.from_numpy(rgb.transpose(2, 0, 1).copy()).float()[None] / 255
        selection = torch.from_numpy(padded_mask.copy()).float()[None, None] / 255
        with torch.inference_mode():
            output = model(pixels, selection)
        result = output[0].permute(1, 2, 0).cpu().numpy()
        if not np.isfinite(result).all():
            raise PhotoProcessingError('背景修补模型输出异常，请重试')
        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        prediction = cv2.cvtColor(result[:work.shape[0], :work.shape[1]], cv2.COLOR_RGB2BGR)
    else:
        raise PhotoProcessingError('不支持的本地背景修补方式')
    prediction = cv2.resize(prediction, (width, height), interpolation=cv2.INTER_CUBIC)
    return composite_wall(image, repair_mask, target_mask, prediction)
