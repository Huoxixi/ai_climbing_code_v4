"""Local, click-conditioned photo route segmentation feasibility baseline.

This module deliberately has no network clients or persistent application state.
It produces reviewable candidates, not a claim that a climbing route is complete.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_WORKING_EDGE = 1920
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoProcessingError(ValueError):
    pass


@dataclass
class Candidate:
    mask: np.ndarray
    bounds: tuple[int, int, int, int]
    touches_border: bool


@dataclass
class Extraction:
    image: np.ndarray
    candidates: list[Candidate]
    seed_hue: float
    duration_seconds: float
    warnings: list[str]


def decode_photo(data: bytes) -> np.ndarray:
    """Check compressed size and header dimensions before decoding pixels."""
    if not data:
        raise PhotoProcessingError("上传图片为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoProcessingError("图片超过 20 MB，请缩小图片后重试")
    try:
        with Image.open(io.BytesIO(data)) as original:
            if original.format not in SUPPORTED_FORMATS:
                raise PhotoProcessingError("仅支持 JPEG、PNG、WebP，请转换图片格式")
            if original.width * original.height > MAX_PIXELS:
                raise PhotoProcessingError("图片超过 4000 万像素，请缩小图片后重试")
            if min(original.size) < 32:
                raise PhotoProcessingError("图片尺寸过小，请上传清晰的墙面照片")
            if getattr(original, "n_frames", 1) != 1:
                raise PhotoProcessingError("请上传静态图片，不支持动画")
            upright = ImageOps.exif_transpose(original)
            if upright.mode == "RGBA" or "transparency" in upright.info:
                rgba = upright.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                upright = Image.alpha_composite(background, rgba)
            return cv2.cvtColor(np.asarray(upright.convert("RGB")), cv2.COLOR_RGB2BGR)
    except PhotoProcessingError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoProcessingError("无法解析图片，请重新上传有效图片") from exc


def fill_enclosed(mask: np.ndarray) -> np.ndarray:
    """Fill fully enclosed chalk and bolt holes without using a convex hull."""
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    cv2.floodFill(flood, None, (0, 0), 255)
    return cv2.bitwise_or(padded, cv2.bitwise_not(flood))[1:-1, 1:-1]


def extract_candidates(
    image: np.ndarray,
    seed: tuple[float, float],
    *,
    hue_tolerance: float = 12,
    refine: bool = True,
    cancelled: Callable[[], bool] = lambda: False,
    timeout_seconds: float = 180,
) -> Extraction:
    """Return same-color connected objects; seed uses normalized upright coordinates.

    Touching same-color objects may remain merged. That limitation is reported
    rather than assigning an invented object split or climbing role.
    """
    started = time.monotonic()

    def checkpoint():
        if cancelled():
            raise PhotoProcessingError("识别已取消")
        if time.monotonic() - started >= timeout_seconds:
            raise PhotoProcessingError("识别超过三分钟，请缩小图片或重试")

    if not all(math.isfinite(v) and 0 <= v <= 1 for v in seed):
        raise PhotoProcessingError("请选择图片范围内的岩点")
    if not math.isfinite(hue_tolerance) or not 1 <= hue_tolerance <= 30:
        raise PhotoProcessingError("颜色容差必须在 1–30 之间")
    checkpoint()
    height, width = image.shape[:2]
    ratio = min(1.0, MAX_WORKING_EDGE / max(height, width))
    work = cv2.resize(image, (round(width * ratio), round(height * ratio))) if ratio < 1 else image.copy()
    height, width = work.shape[:2]
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    x, y = min(width - 1, round(seed[0] * width)), min(height - 1, round(seed[1] * height))
    patch = hsv[max(0, y - 6):y + 7, max(0, x - 6):x + 7]
    colored = patch[(patch[:, :, 1] >= 65) & (patch[:, :, 2] >= 35)]
    if len(colored) < 8:
        raise PhotoProcessingError("该位置颜色不明显，请点击岩点未被镁粉或反光覆盖的区域")
    # Circular mean respects red spanning both ends of OpenCV's hue interval.
    radians = colored[:, 0].astype(float) * math.pi / 90
    hue = float(math.atan2(np.sin(radians).mean(), np.cos(radians).mean()) * 90 / math.pi) % 180
    delta = np.abs(hsv[:, :, 0].astype(float) - hue)
    distance = np.minimum(delta, 180 - delta)
    strong = ((distance <= hue_tolerance) & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 35)).astype(np.uint8) * 255
    strong = cv2.morphologyEx(strong, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    strong = cv2.morphologyEx(strong, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(strong)
    minimum_area = max(80, round(height * width * 0.00025))
    results = []
    for label in range(1, count):
        checkpoint()
        left, top, box_width, box_height, area = [int(v) for v in stats[label]]
        if area < minimum_area or min(box_width, box_height) < 8:
            continue
        component = fill_enclosed(np.where(labels == label, 255, 0).astype(np.uint8))
        if refine:
            # Restrict GrabCut to a local neighborhood; other holds must not be
            # recruited simply because they have a similar foreground color.
            margin = max(10, round(min(box_width, box_height) * 0.18))
            l, t = max(0, left - margin), max(0, top - margin)
            r, b = min(width, left + box_width + margin), min(height, top + box_height + margin)
            local = component[t:b, l:r]
            gc = np.full(local.shape, cv2.GC_BGD, np.uint8)
            neighborhood = cv2.dilate(local, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin * 2 + 1, margin * 2 + 1)))
            gc[neighborhood > 0] = cv2.GC_PR_BGD
            gc[local > 0] = cv2.GC_PR_FGD
            inner = cv2.erode(local, np.ones((3, 3), np.uint8))
            gc[(inner > 0) & (strong[t:b, l:r] > 0)] = cv2.GC_FGD
            if np.any(gc == cv2.GC_FGD) and np.any(gc == cv2.GC_BGD):
                cv2.grabCut(work[t:b, l:r], gc, None, np.zeros((1, 65)), np.zeros((1, 65)), 3, cv2.GC_INIT_WITH_MASK)
                refined = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
                _, parts, _, _ = cv2.connectedComponentsWithStats(refined)
                # Retain only connected regions anchored to the source seed.
                anchored = np.unique(parts[local > 0])
                anchored = anchored[anchored != 0]
                refined = np.where(np.isin(parts, anchored), 255, 0).astype(np.uint8)
                component[:] = 0
                component[t:b, l:r] = fill_enclosed(refined)
        # Refinement may remove a color bridge. Keep the now disconnected
        # objects independently editable instead of retaining their shared box.
        piece_count, pieces, piece_stats, _ = cv2.connectedComponentsWithStats(component)
        for piece in range(1, piece_count):
            if piece_stats[piece, cv2.CC_STAT_AREA] < minimum_area:
                continue
            mask = np.where(pieces == piece, 255, 0).astype(np.uint8)
            bbox = tuple(int(v) for v in piece_stats[piece, :4])
            edge = bool(np.any(mask[0]) or np.any(mask[-1]) or np.any(mask[:, 0]) or np.any(mask[:, -1]))
            results.append(Candidate(mask, bbox, edge))
    checkpoint()
    results.sort(key=lambda candidate: (candidate.bounds[1], candidate.bounds[0]))
    warnings = ["颜色相同且接触的造型与岩点可能合并，需要检查并拆分", "未判断起终点、线路完整性或被遮挡内容"]
    if any(candidate.touches_border for candidate in results):
        warnings.append("部分候选到达图片边缘，请确认目标线路完整可见")
    if not results:
        warnings.append("没有找到可提取对象，请换一个位置点选或更换图片")
    return Extraction(work, results, hue, time.monotonic() - started, warnings)


def cutout(image: np.ndarray, candidate: Candidate) -> np.ndarray:
    x, y, width, height = candidate.bounds
    return np.dstack([image[y:y + height, x:x + width], candidate.mask[y:y + height, x:x + width]])
