"""Non-destructive hold image processing utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


PROCESSING_VERSION = "cutout_v3"


def _read_image(path: Path) -> Optional[np.ndarray]:
    buffer = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)


def _write_image(path: Path, image: np.ndarray) -> bool:
    success, buffer = cv2.imencode(path.suffix or ".png", image)
    if not success:
        return False
    path.write_bytes(buffer.tobytes())
    return True


def _border_connected_mask(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    flood = np.zeros((height + 2, width + 2), dtype=np.uint8)
    connected = np.zeros_like(mask, dtype=np.uint8)
    work = mask.copy().astype(np.uint8)

    seeds = []
    for x_index in range(width):
        seeds.append((x_index, 0))
        seeds.append((x_index, height - 1))
    for y_index in range(height):
        seeds.append((0, y_index))
        seeds.append((width - 1, y_index))

    for seed in seeds:
        x_index, y_index = seed
        if work[y_index, x_index] == 0:
            continue
        fill_mask = flood.copy()
        cv2.floodFill(work, fill_mask, seed, 0)
        connected[fill_mask[1:-1, 1:-1] == 1] = 255
    return connected


def _grabcut_foreground_mask(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)

    rect_margin_x = max(6, int(width * 0.035))
    rect_margin_y = max(6, int(height * 0.035))
    mask[rect_margin_y : height - rect_margin_y, rect_margin_x : width - rect_margin_x] = cv2.GC_PR_FGD

    bgr = image[:, :, :3]
    alpha = image[:, :, 3]
    max_channel = bgr.max(axis=2)
    min_channel = bgr.min(axis=2)
    near_white = (max_channel >= 224) & ((max_channel - min_channel) <= 42) & (alpha > 0)
    border_background = _border_connected_mask(near_white.astype(np.uint8))
    mask[border_background > 0] = cv2.GC_BGD

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    dark_or_colored = ((gray < 218) | ((max_channel - min_channel) > 48)) & (alpha > 0)
    center_y0 = int(height * 0.12)
    center_y1 = int(height * 0.88)
    center_x0 = int(width * 0.12)
    center_x1 = int(width * 0.88)
    mask[center_y0:center_y1, center_x0:center_x1][dark_or_colored[center_y0:center_y1, center_x0:center_x1]] = cv2.GC_PR_FGD

    bg_model = np.zeros((1, 65), dtype=np.float64)
    fg_model = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(bgr, mask, None, bg_model, fg_model, 4, cv2.GC_INIT_WITH_MASK)

    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel, iterations=1)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel, iterations=2)
    return foreground


def _largest_foreground_region(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == largest_label, 255, 0).astype(np.uint8)


def _crop_to_foreground(image: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y_values, x_values = np.where(alpha > 0)
    if len(x_values) == 0 or len(y_values) == 0:
        return image, alpha

    height, width = alpha.shape
    x0, x1 = int(x_values.min()), int(x_values.max()) + 1
    y0, y1 = int(y_values.min()), int(y_values.max()) + 1
    pad = max(8, int(max(x1 - x0, y1 - y0) * 0.08))
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(width, x1 + pad)
    y1 = min(height, y1 + pad)
    cropped_image = image[y0:y1, x0:x1]
    cropped_alpha = alpha[y0:y1, x0:x1]
    extra_pad = max(8, int(max(cropped_image.shape[:2]) * 0.035))

    padded_shape = (
        cropped_image.shape[0] + extra_pad * 2,
        cropped_image.shape[1] + extra_pad * 2,
        cropped_image.shape[2],
    )
    padded_image = np.zeros(padded_shape, dtype=cropped_image.dtype)
    padded_alpha = np.zeros(padded_shape[:2], dtype=cropped_alpha.dtype)
    padded_image[extra_pad : extra_pad + cropped_image.shape[0], extra_pad : extra_pad + cropped_image.shape[1]] = cropped_image
    padded_alpha[extra_pad : extra_pad + cropped_alpha.shape[0], extra_pad : extra_pad + cropped_alpha.shape[1]] = cropped_alpha
    return padded_image, padded_alpha


def remove_border_white_background(source_path: Path, output_path: Path) -> Optional[Path]:
    image = _read_image(source_path)
    if image is None:
        return None
    if image.ndim != 3:
        return None
    if image.shape[2] == 3:
        alpha = np.full(image.shape[:2], 255, dtype=np.uint8)
        image = np.dstack([image, alpha])

    foreground = _largest_foreground_region(_grabcut_foreground_mask(image))
    output, alpha = _crop_to_foreground(image.copy(), foreground)
    output[:, :, 3] = alpha
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not _write_image(output_path, output):
        return None
    return output_path


def ensure_processed_hold_image(source_path: Path, output_dir: Path) -> Optional[Path]:
    output_path = output_dir / f"{source_path.stem}_{PROCESSING_VERSION}{source_path.suffix}"
    if output_path.exists() and output_path.stat().st_mtime >= source_path.stat().st_mtime:
        return output_path
    return remove_border_white_background(source_path, output_path)
