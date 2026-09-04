"""Deterministic, local-only analysis for photo-route V2.

The module deliberately keeps geometry deterministic: vision proposes objects and
hole centres, while the board transform is always computed from explicit points.
No network client or model downloader is used here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from core.photo_route_processing import PhotoProcessingError, decode_photo


BOARD_WIDTH_MM = 6200
BOARD_HEIGHT_MM = 4100
GRID_COLUMNS = 30
GRID_ROWS = 20
HOLE_SPACING_MM = 200
MAX_WORKING_EDGE = 1920


@dataclass(frozen=True)
class CaptureQuality:
    accepted: bool
    issues: list[str]
    metrics: dict[str, float | int]


def assess_capture_quality(image: np.ndarray) -> CaptureQuality:
    """Apply conservative gates before a board version is created."""
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise PhotoProcessingError("照片必须是有效的三通道图片")
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    clipped = float(np.mean((gray <= 5) | (gray >= 250)))
    ratio = width / max(height, 1)
    issues: list[str] = []
    if width < 800 or height < 520:
        issues.append("照片分辨率过低，请靠近并完整拍摄岩壁")
    # Portrait phone captures are valid when the full wall remains visible; ratio
    # is only used to reject extreme strips that cannot contain all boundaries.
    if not .45 <= ratio <= 2.4:
        issues.append("画面过窄，无法同时确认岩壁边界，请重新取景")
    if brightness < 32 or brightness > 228:
        issues.append("画面过暗或过亮，请改善照明后重拍")
    if sharpness < 22:
        issues.append("照片明显模糊，请保持镜头稳定后重拍")
    if clipped > .42:
        issues.append("大面积区域过曝或全黑，无法可靠识别")
    return CaptureQuality(not issues, issues, {
        "width": width, "height": height, "aspect_ratio": round(ratio, 5),
        "brightness": round(brightness, 3), "sharpness": round(sharpness, 3),
        "clipped_ratio": round(clipped, 6),
    })


def board_holes() -> list[dict]:
    def column(index: int) -> str:
        return chr(65 + index) if index < 26 else "A" + chr(65 + index - 26)
    return [{
        "id": f"{column(x)}{y + 1}",
        "x_mm": 200 + x * HOLE_SPACING_MM,
        "y_mm": 100 + y * HOLE_SPACING_MM,
    } for y in range(GRID_ROWS) for x in range(GRID_COLUMNS)]


def compute_homography(photo_points: list[list[float]], board_points: list[list[float]]) -> list[list[float]]:
    if len(photo_points) != len(board_points) or not 4 <= len(photo_points) <= 40:
        raise ValueError("标定点必须成对提供，数量为 4–40 个")
    src = np.asarray(photo_points, dtype=np.float64)
    dst = np.asarray(board_points, dtype=np.float64)
    if not np.isfinite(src).all() or not np.isfinite(dst).all():
        raise ValueError("标定点包含无效坐标")
    matrix, _ = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
    if matrix is None or abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError("标定点无法形成稳定映射")
    return matrix.tolist()


def map_point(matrix: list[list[float]], x: float, y: float) -> tuple[float, float]:
    value = np.asarray(matrix, dtype=np.float64) @ np.asarray([x, y, 1.0])
    if abs(value[2]) < 1e-9:
        raise ValueError("标定矩阵产生了无效坐标")
    return float(value[0] / value[2]), float(value[1] / value[2])


def nearest_hole(x_mm: float, y_mm: float) -> tuple[dict, float]:
    holes = board_holes()
    hole = min(holes, key=lambda item: (item["x_mm"] - x_mm) ** 2 + (item["y_mm"] - y_mm) ** 2)
    return hole, math.hypot(hole["x_mm"] - x_mm, hole["y_mm"] - y_mm)


def _write_asset(root: Path, data: bytes, suffix: str, width: int, height: int) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    filename = f"{digest}.{suffix}"
    target = root / "assets" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
    return {"filename": filename, "sha256": digest, "width": width, "height": height}


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise PhotoProcessingError("无法生成本地识别素材")
    return encoded.tobytes()


def _working_image(image: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    ratio = min(1.0, MAX_WORKING_EDGE / max(width, height))
    if ratio == 1:
        return image.copy(), 1.0
    return cv2.resize(image, (round(width * ratio), round(height * ratio)), interpolation=cv2.INTER_AREA), ratio


def _colour_name(lab: np.ndarray) -> str:
    # Convert a robust median Lab sample back to RGB and use stable buckets.
    rgb = cv2.cvtColor(np.uint8([[lab]]), cv2.COLOR_LAB2RGB)[0, 0]
    r, g, b = [int(v) for v in rgb]
    hsv = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)[0, 0]
    hue, saturation, value = [int(v) for v in hsv]
    if saturation < 38:
        return "黑色" if value < 70 else "白色" if value > 185 else "灰色"
    if hue < 8 or hue >= 172:
        return "红色"
    if hue < 20:
        return "橙色"
    if hue < 38:
        return "黄色"
    if hue < 85:
        return "绿色"
    if hue < 108:
        return "蓝色"
    if hue < 142:
        return "紫色"
    return "粉色"


def _candidate_masks(image: np.ndarray) -> list[np.ndarray]:
    """Generate full-scene colour candidates; MobileSAM may refine them later."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    # Coloured holds plus dark holds. The dark mask is conservative to avoid holes.
    foreground = (((saturation > 58) & (value > 34)) | ((value < 62) & (saturation > 22))).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel, iterations=2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
    area = image.shape[0] * image.shape[1]
    masks: list[np.ndarray] = []
    for index in range(1, count):
        x, y, width, height, size = [int(v) for v in stats[index]]
        if size < max(45, area * .000025) or size > area * .08:
            continue
        if width < 8 or height < 8:
            continue
        mask = (labels == index).astype(np.uint8) * 255
        # Reject line-like signs and tiny circular holes.
        extent = size / max(width * height, 1)
        if x <= 1 or y <= 1 or x + width >= image.shape[1] - 1 or y + height >= image.shape[0] - 1:
            continue
        if extent < .12 or (max(width, height) / max(min(width, height), 1) > 6):
            continue
        masks.append(mask)
    return masks


def _mobilesam_masks(image: np.ndarray, deadline: float,
                     cancelled: Callable[[], bool]) -> tuple[list[np.ndarray], str] | None:
    """Use an explicitly installed local MobileSAM; never download a model."""
    repo = Path(os.getenv("PHOTO_ROUTE_MOBILESAM_REPO", ""))
    checkpoint = Path(os.getenv("PHOTO_ROUTE_MOBILESAM_CHECKPOINT", ""))
    if not repo.is_dir() or not checkpoint.is_file():
        return None
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    sys.path.insert(0, str(repo.resolve()))
    import torch
    from mobile_sam import SamAutomaticMaskGenerator, sam_model_registry
    torch.set_num_threads(2); torch.manual_seed(0); cv2.setNumThreads(1)
    model = sam_model_registry["vit_t"]()
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    class LocalGenerator(SamAutomaticMaskGenerator):
        def _process_batch(self, *args, **kwargs):
            if cancelled(): raise InterruptedError("任务已取消")
            if time.monotonic() > deadline: raise TimeoutError("识别任务超过 180 秒")
            return super()._process_batch(*args, **kwargs)
    generator = LocalGenerator(model, points_per_side=24, points_per_batch=2,
                               pred_iou_thresh=.84, stability_score_thresh=.9,
                               box_nms_thresh=.7, min_mask_region_area=45)
    with torch.inference_mode(): proposals = generator.generate(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV); area = image.shape[0] * image.shape[1]
    masks = []
    for proposal in proposals:
        mask = proposal["segmentation"].astype(np.uint8) * 255
        x, y, width, height = cv2.boundingRect(mask); size = int(np.count_nonzero(mask))
        if not max(45, area * .000025) <= size <= area * .08 or min(width, height) < 8:
            continue
        if x <= 1 or y <= 1 or x + width >= image.shape[1]-1 or y + height >= image.shape[0]-1:
            continue
        pixels = hsv[mask > 0]
        if len(pixels) == 0 or (np.median(pixels[:, 1]) < 35 and np.median(pixels[:, 2]) > 70):
            continue
        masks.append(mask)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()[:12]
    return masks, f"mobilesam-vit-t-{digest}+local-rules-v2"


def _detect_grid_points(image: np.ndarray) -> list[list[float]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    min_dist = max(8, round(min(image.shape[:2]) / 60))
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.3, minDist=min_dist,
                               param1=90, param2=18, minRadius=2, maxRadius=max(4, min_dist // 2))
    if circles is None:
        return []
    return [[round(float(x), 2), round(float(y), 2)] for x, y, _ in circles[0][:1000]]


def analyze_board_photo(photo_path: Path, storage_root: Path, *,
                        cancelled: Callable[[], bool] | None = None,
                        deadline: float | None = None) -> dict:
    """Produce local object, colour, hole and initial anchor proposals."""
    cancelled = cancelled or (lambda: False)
    deadline = deadline or time.monotonic() + 180
    image = decode_photo(photo_path.read_bytes())
    quality = assess_capture_quality(image)
    if not quality.accepted:
        raise PhotoProcessingError("；".join(quality.issues))
    original_height, original_width = image.shape[:2]
    work, ratio = _working_image(image)
    height, width = work.shape[:2]
    matrix = compute_homography(
        [[0, original_height], [original_width, original_height], [original_width, 0], [0, 0]],
        [[0, 0], [BOARD_WIDTH_MM, 0], [BOARD_WIDTH_MM, BOARD_HEIGHT_MM], [0, BOARD_HEIGHT_MM]],
    )
    proposals = []
    lab = cv2.cvtColor(work, cv2.COLOR_BGR2LAB)
    mobile = _mobilesam_masks(work, deadline, cancelled)
    candidate_masks, model_version = mobile if mobile is not None else (_candidate_masks(work), "local-rules-v2-no-mobilesam")
    for index, mask in enumerate(candidate_masks, 1):
        if cancelled():
            raise InterruptedError("任务已取消")
        if time.monotonic() > deadline:
            raise TimeoutError("识别任务超过 180 秒")
        ys, xs = np.where(mask > 0)
        x, y, right, bottom = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
        crop_mask = mask[y:bottom, x:right]
        crop = work[y:bottom, x:right].copy()
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = crop_mask
        mask_ref = _write_asset(storage_root, _encode_png(crop_mask), "png", right - x, bottom - y)
        cutout_ref = _write_asset(storage_root, _encode_png(rgba), "png", right - x, bottom - y)
        median_lab = np.median(lab[mask > 0], axis=0).astype(np.uint8)
        colour = _colour_name(median_lab)
        source_cx, source_cy = (x + right) / (2 * ratio), (y + bottom) / (2 * ratio)
        board_x, board_y = map_point(matrix, source_cx, source_cy)
        hole, distance = nearest_hole(board_x, board_y)
        anchor_confidence = max(0.0, 1.0 - distance / 150.0)
        object_confidence = min(.96, .58 + (len(xs) / max((right - x) * (bottom - y), 1)) * .38)
        proposals.append({
            "id": f"object-{index:03d}",
            "kind": "volume" if len(xs) > work.shape[0] * work.shape[1] * .012 else "hold",
            "color_group": colour,
            "contour": [[round(float((px + x) / ratio), 2), round(float((py + y) / ratio), 2)]
                        for px, py in cv2.approxPolyDP(max(cv2.findContours(crop_mask, cv2.RETR_EXTERNAL,
                            cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea), 2.0, True)[:, 0]],
            "source_bbox_px": [round(x / ratio), round(y / ratio), round((right - x) / ratio), round((bottom - y) / ratio)],
            "cutout": cutout_ref,
            "mask": mask_ref,
            "center_x_mm": round(board_x, 3), "center_y_mm": round(board_y, 3),
            "rotation_deg": 0.0,
            "scale_mm_per_px": round((BOARD_WIDTH_MM / width) * ratio, 8),
            "confidence": round(object_confidence, 4),
            "review_status": "confirmed" if mobile is not None and object_confidence >= .9 else "needs_review",
            "anchors": [{"hole_id": hole["id"], "x_mm": hole["x_mm"], "y_mm": hole["y_mm"],
                         "confidence": round(anchor_confidence, 4),
                         "confirmed": anchor_confidence >= .86}],
        })
    grid_points = _detect_grid_points(work)
    return {
        "quality": {"accepted": quality.accepted, "issues": quality.issues, "metrics": quality.metrics},
        "calibration": {
            "matrix": matrix,
            "method": "visible-hole-hybrid" if len(grid_points) >= 20 else "board-boundary-provisional",
            "detected_hole_count": len(grid_points),
            "confidence": round(min(.94, .45 + len(grid_points) / 160), 4),
            "status": "confirmed" if len(grid_points) >= 80 else "needs_review",
        },
        "objects": proposals,
        "model_version": model_version,
        "input_fingerprint": hashlib.sha256(photo_path.read_bytes()).hexdigest(),
        "warnings": ([] if proposals else ["未自动识别到可靠岩点，请手动添加对象"]),
    }


def fingerprint_payload(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
