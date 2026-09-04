"""Non-destructive local hold image background removal."""

from __future__ import annotations

import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

import cv2
import numpy as np


PROCESSING_VERSION = "cutout_v4"
PROCESSED_URL_PREFIX = "/images/processed"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class HoldImageProcessingError(ValueError):
    """Raised when an image cannot be cut out safely."""


def _decode_image(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        raise HoldImageProcessingError("上传图片为空")
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] not in {3, 4}:
        raise HoldImageProcessingError("无法解析图片，请上传 PNG、JPEG 或 WebP")
    if min(image.shape[:2]) < 16:
        raise HoldImageProcessingError("图片尺寸过小，无法可靠识别岩点")
    if image.shape[2] == 3:
        image = np.dstack([image, np.full(image.shape[:2], 255, dtype=np.uint8)])
    return image


def _encode_png(image: np.ndarray) -> bytes:
    success, buffer = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not success:
        raise HoldImageProcessingError("透明 PNG 编码失败")
    return buffer.tobytes()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_bytes(data)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def processed_filename_for(source_name: str | Path) -> str:
    return f"{Path(source_name).stem}_{PROCESSING_VERSION}.png"


def _border_pixels(bgr: np.ndarray) -> np.ndarray:
    height, width = bgr.shape[:2]
    thickness = max(2, int(round(min(height, width) * 0.025)))
    return np.concatenate(
        [
            bgr[:thickness, :, :].reshape(-1, 3),
            bgr[-thickness:, :, :].reshape(-1, 3),
            bgr[:, :thickness, :].reshape(-1, 3),
            bgr[:, -thickness:, :].reshape(-1, 3),
        ],
        axis=0,
    )


def _estimate_white_background(bgr: np.ndarray) -> np.ndarray:
    border = _border_pixels(bgr).astype(np.int16)
    minimum = border.min(axis=1)
    maximum = border.max(axis=1)
    low_chroma_bright = (minimum >= 178) & ((maximum - minimum) <= 52)
    candidates = border[low_chroma_bright]
    minimum_count = max(24, int(len(border) * 0.08))
    if len(candidates) < minimum_count:
        raise HoldImageProcessingError("未检测到可靠的白色或近白色背景")

    background = np.median(candidates, axis=0).astype(np.float32)
    if float(background.mean()) < 198 or float(background.max() - background.min()) > 35:
        raise HoldImageProcessingError("图片背景不是可可靠移除的白色背景")
    return background


def _largest_component(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros_like(mask, dtype=np.uint8)
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == largest_label, 255, 0).astype(np.uint8)


def _border_connected_mask(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    work = np.where(mask > 0, 255, 0).astype(np.uint8)
    flood_mask = np.zeros((height + 2, width + 2), dtype=np.uint8)
    connected = np.zeros_like(work)

    seeds = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    for x, y in seeds:
        if work[y, x] == 0:
            continue
        local_flood_mask = flood_mask.copy()
        cv2.floodFill(work, local_flood_mask, (x, y), 0)
        connected[local_flood_mask[1:-1, 1:-1] == 1] = 255
    return connected


def _strong_object_region(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Cast shadows can be very different from white in brightness, so color
    # distance alone is not a safe foreground signal. Saturated hold material
    # plus genuinely dark outline pixels gives a much tighter object seed.
    strong = ((saturation >= 36) | (gray <= 78)).astype(np.uint8) * 255
    kernel = np.ones((3, 3), dtype=np.uint8)
    strong = cv2.morphologyEx(strong, cv2.MORPH_OPEN, kernel, iterations=1)
    strong = cv2.morphologyEx(strong, cv2.MORPH_CLOSE, kernel, iterations=2)
    strong = _largest_component(strong)
    if not np.any(strong):
        raise HoldImageProcessingError("未识别到足够清晰的岩点主体")

    contours, _ = cv2.findContours(strong, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise HoldImageProcessingError("无法识别岩点主体轮廓")
    contour = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(strong)
    cv2.drawContours(filled, [contour], -1, 255, thickness=cv2.FILLED)
    return filled


def _grabcut_foreground(bgr: np.ndarray, background: np.ndarray, object_region: np.ndarray) -> np.ndarray:
    height, width = bgr.shape[:2]
    pixels = bgr.astype(np.float32)
    color_distance = np.linalg.norm(pixels - background.reshape(1, 1, 3), axis=2)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    probable_background = (color_distance <= 58) & (saturation <= 62) & (gray >= 158)
    definite_background = _border_connected_mask(probable_background.astype(np.uint8) * 255)

    mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)
    mask[definite_background > 0] = cv2.GC_BGD
    mask[object_region > 0] = cv2.GC_PR_FGD

    foreground_seed = cv2.erode(object_region, np.ones((5, 5), dtype=np.uint8), iterations=1)
    foreground_seed &= (((saturation >= 34) | (gray <= 170) | (color_distance >= 72)).astype(np.uint8) * 255)
    mask[foreground_seed > 0] = cv2.GC_FGD
    if not np.any(mask == cv2.GC_FGD):
        raise HoldImageProcessingError("岩点主体与背景差异不足，无法安全去除背景")

    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(bgr, mask, None, background_model, foreground_model, 4, cv2.GC_INIT_WITH_MASK)
    foreground = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
        255,
        0,
    ).astype(np.uint8)

    # Limit GrabCut to the immediate object region so photographed cast shadows
    # cannot become part of the cutout.
    support = cv2.dilate(object_region, np.ones((7, 7), dtype=np.uint8), iterations=1)
    foreground = cv2.bitwise_and(foreground, support)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8), iterations=1)
    return _largest_component(foreground)


def _soft_alpha(foreground: np.ndarray) -> np.ndarray:
    if not np.any(foreground):
        raise HoldImageProcessingError("去背景后没有保留下有效岩点主体")
    height, width = foreground.shape
    sigma = float(np.clip(max(height, width) * 0.0018, 0.9, 2.4))
    blurred = cv2.GaussianBlur(foreground.astype(np.float32) / 255.0, (0, 0), sigmaX=sigma, sigmaY=sigma)
    alpha = np.clip((blurred - 0.035) / 0.93, 0.0, 1.0)
    alpha[foreground >= 255] = np.maximum(alpha[foreground >= 255], 0.985)
    return np.rint(alpha * 255).astype(np.uint8)


def _decontaminate_white_edges(bgr: np.ndarray, alpha: np.ndarray, background: np.ndarray) -> np.ndarray:
    result = bgr.astype(np.float32)
    normalized_alpha = alpha.astype(np.float32) / 255.0
    edge = (alpha > 5) & (alpha < 250)
    if not np.any(edge):
        return bgr

    edge_alpha = np.clip(normalized_alpha[edge, None], 0.08, 1.0)
    estimated_foreground = (
        result[edge] - (1.0 - edge_alpha) * background.reshape(1, 3)
    ) / edge_alpha
    estimated_foreground = np.clip(estimated_foreground, 0, 255)
    blend = np.clip((1.0 - edge_alpha) * 0.72, 0.0, 0.72)
    result[edge] = result[edge] * (1.0 - blend) + estimated_foreground * blend
    result[alpha == 0] = 0
    return np.rint(result).astype(np.uint8)


def _crop_with_padding(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    y_values, x_values = np.where(alpha > 3)
    if len(x_values) == 0 or len(y_values) == 0:
        raise HoldImageProcessingError("透明化结果为空")

    height, width = alpha.shape
    x0, x1 = int(x_values.min()), int(x_values.max()) + 1
    y0, y1 = int(y_values.min()), int(y_values.max()) + 1
    object_width = x1 - x0
    object_height = y1 - y0
    padding = max(8, int(round(max(object_width, object_height) * 0.08)))

    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(width, x1 + padding)
    y1 = min(height, y1 + padding)
    cropped_bgr = image[y0:y1, x0:x1]
    cropped_alpha = alpha[y0:y1, x0:x1]

    missing_left = max(0, padding - int(x_values.min()))
    missing_top = max(0, padding - int(y_values.min()))
    missing_right = max(0, padding - (width - int(x_values.max()) - 1))
    missing_bottom = max(0, padding - (height - int(y_values.max()) - 1))
    if any((missing_left, missing_top, missing_right, missing_bottom)):
        cropped_bgr = cv2.copyMakeBorder(
            cropped_bgr,
            missing_top,
            missing_bottom,
            missing_left,
            missing_right,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
        cropped_alpha = cv2.copyMakeBorder(
            cropped_alpha,
            missing_top,
            missing_bottom,
            missing_left,
            missing_right,
            cv2.BORDER_CONSTANT,
            value=0,
        )
    return np.dstack([cropped_bgr, cropped_alpha])


def _validate_cutout(alpha: np.ndarray, source_shape: tuple[int, ...]) -> None:
    foreground_area = int(np.count_nonzero(alpha > 16))
    source_area = int(source_shape[0] * source_shape[1])
    ratio = foreground_area / max(1, source_area)
    if ratio < 0.008:
        raise HoldImageProcessingError("识别到的岩点主体过小，已停止处理以避免损坏")
    if ratio > 0.92:
        raise HoldImageProcessingError("背景去除范围异常，已停止处理以避免损坏")
    if not np.any((alpha > 0) & (alpha < 255)):
        raise HoldImageProcessingError("无法生成平滑的透明边缘")


def process_hold_image_bytes(image_bytes: bytes) -> bytes:
    image = _decode_image(image_bytes)
    bgr = image[:, :, :3]
    source_alpha = image[:, :, 3]

    # Preserve meaningful user-provided transparency without re-segmenting it.
    transparent_ratio = float(np.mean(source_alpha < 250))
    if transparent_ratio >= 0.002:
        bgr = bgr.copy()
        bgr[source_alpha == 0] = 0
        output = _crop_with_padding(bgr, source_alpha)
        return _encode_png(output)

    background = _estimate_white_background(bgr)
    object_region = _strong_object_region(bgr)
    foreground = _grabcut_foreground(bgr, background, object_region)
    alpha = _soft_alpha(foreground)
    _validate_cutout(alpha, image.shape)
    clean_bgr = _decontaminate_white_edges(bgr, alpha, background)
    output = _crop_with_padding(clean_bgr, alpha)
    return _encode_png(output)


def remove_border_white_background(source_path: Path, output_path: Path) -> Optional[Path]:
    try:
        png_bytes = process_hold_image_bytes(source_path.read_bytes())
        png_path = output_path.with_suffix(".png")
        write_bytes_atomic(png_path, png_bytes)
        return png_path
    except (OSError, HoldImageProcessingError):
        return None


def ensure_processed_hold_image(source_path: Path, output_dir: Path) -> Optional[Path]:
    output_path = output_dir / processed_filename_for(source_path.name)
    try:
        if output_path.exists() and output_path.stat().st_mtime >= source_path.stat().st_mtime:
            return output_path
    except OSError:
        pass
    return remove_border_white_background(source_path, output_path)


def resolve_local_hold_image_url(
    image_url: str,
    source_dir: Path,
    output_dir: Path,
    url_prefix: str = PROCESSED_URL_PREFIX,
) -> str:
    if image_url.startswith(f"{url_prefix}/"):
        processed_name = PurePosixPath(image_url).name
        version_suffix = f"_{PROCESSING_VERSION}"
        processed_stem = Path(processed_name).stem
        if not processed_stem.endswith(version_suffix):
            return image_url
        source_stem = processed_stem[: -len(version_suffix)]
        if not source_dir.is_dir():
            return image_url
        source_path = next(
            (
                candidate
                for candidate in source_dir.iterdir()
                if candidate.is_file()
                and candidate.stem == source_stem
                and candidate.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            ),
            None,
        )
        if source_path is None:
            return image_url
        processed_path = ensure_processed_hold_image(source_path, output_dir)
        if processed_path is None:
            return f"/images/{source_path.name}"
        return f"{url_prefix.rstrip('/')}/{processed_path.name}"

    if not image_url.startswith("/images/"):
        return image_url
    source_name = PurePosixPath(image_url).name
    source_path = source_dir / source_name
    if source_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES or not source_path.is_file():
        return image_url
    processed_path = ensure_processed_hold_image(source_path, output_dir)
    if processed_path is None:
        return image_url
    return f"{url_prefix.rstrip('/')}/{processed_path.name}"


def resolve_local_holds_mapping(
    mapping: Dict[str, Dict[str, Any]],
    source_dir: Path,
    output_dir: Path,
) -> Dict[str, Dict[str, Any]]:
    return {
        hold_type: {
            variant: resolve_local_hold_image_url(str(image_url), source_dir, output_dir)
            for variant, image_url in variants.items()
        }
        for hold_type, variants in mapping.items()
    }
