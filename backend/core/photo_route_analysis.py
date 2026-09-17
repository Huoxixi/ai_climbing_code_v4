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

from core.photo_route_inference_lock import serialized_inference

import cv2
import numpy as np

from core.photo_route_processing import PhotoProcessingError, decode_photo
from core.photo_route_colors import classify_mask_color, BASELINE_COLOR_VERSION, COLOR_VERSIONS
from core.photo_route_boundaries import refine_boundary, separate_mask_components


BOARD_WIDTH_MM = 4100
BOARD_HEIGHT_MM = 6200
GRID_COLUMNS = 20
GRID_ROWS = 30
HOLE_SPACING_MM = 200
MAX_WORKING_EDGE = 1920
PRODUCTION_CLIMBING_MIN_SIZE = 1200
PRODUCTION_CLIMBING_CANDIDATE_CAP = 300
PACKAGED_CLIMBING_MODEL_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "model_assets"
    / "climbing-mask-rcnn-r50-fpn-1200.yaml"
)
PRODUCTION_CLIMBING_MODEL_CHECKPOINT = Path(
    "/var/lib/ai-climbing/models/climbing/verified-model_final.pth"
)
AUTOMATIC_MASK_PARAMETERS = dict(points_per_side=24, points_per_batch=2,
    pred_iou_thresh=.84, stability_score_thresh=.9, box_nms_thresh=.7, min_mask_region_area=45)


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


def projected_bbox_scale_mm_per_px(matrix: list[list[float]], bbox: list[float] | tuple[float, float, float, float]) -> float:
    """Calculate photo-to-board scale at the object's position on the wall."""
    x, y, width, height = map(float, bbox)
    if width <= 0 or height <= 0:
        raise ValueError("对象边界尺寸必须大于零")
    top_left = map_point(matrix, x, y)
    top_right = map_point(matrix, x + width, y)
    bottom_right = map_point(matrix, x + width, y + height)
    bottom_left = map_point(matrix, x, y + height)
    distance = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])
    mapped_width = (distance(top_left, top_right) + distance(bottom_left, bottom_right)) / 2
    mapped_height = (distance(top_left, bottom_left) + distance(top_right, bottom_right)) / 2
    return math.sqrt((mapped_width / width) * (mapped_height / height))


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
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    # Coloured holds plus dark holds. The dark mask is conservative to avoid holes.
    # Label hue groups before morphology, so touching different colours cannot
    # become one connected component. This remains a coarse, unverified pass.
    hue = hsv[:, :, 0]
    groups = np.digitize(hue, [8, 20, 38, 85, 108, 142, 172])
    groups[groups == 7] = 0
    foreground = ((saturation > 58) & (value > 34)) | ((value < 62) & (saturation > 22))
    groups[value < 62] = 7
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    separated = np.zeros(image.shape[:2], np.int32)
    label_offset = 0
    all_stats = []
    for group in range(8):
        binary = (foreground & (groups == group)).astype(np.uint8) * 255
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        binary[foreground & (groups != group)] = 0
        count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
        separated[labels > 0] = labels[labels > 0] + label_offset
        all_stats.extend(stats[1:])
        label_offset += count - 1
    labels = separated
    area = image.shape[0] * image.shape[1]
    masks: list[np.ndarray] = []
    for index, stats in enumerate(all_stats, 1):
        x, y, width, height, size = [int(v) for v in stats]
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
                     cancelled: Callable[[], bool], progress=lambda stage,value:None) -> tuple[list[np.ndarray], str] | None:
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
    progress("载入本地分割模型",22)
    model = sam_model_registry["vit_t"]()
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    class LocalGenerator(SamAutomaticMaskGenerator):
        batches=0
        def _process_batch(self, *args, **kwargs):
            if cancelled(): raise InterruptedError("任务已取消")
            if time.monotonic() > deadline: raise TimeoutError("识别任务超过 180 秒")
            result=super()._process_batch(*args, **kwargs)
            self.batches+=1
            progress("全图轮廓识别",25+min(35,round(self.batches/288*35)))
            return result
    generator = LocalGenerator(model, **AUTOMATIC_MASK_PARAMETERS)
    with torch.inference_mode(): proposals = generator.generate(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    area = image.shape[0] * image.shape[1]
    masks = []
    for mask in (part for proposal in sorted(proposals, key=lambda p: p['predicted_iou'], reverse=True)
                 for part in separate_mask_components(proposal['segmentation'], max(45, area * .000025))):
        x, y, width, height = cv2.boundingRect(mask); size = int(np.count_nonzero(mask))
        if not max(45, area * .000025) <= size <= area * .08 or min(width, height) < 8:
            continue
        # Low saturation may be chalk or a neutral hold; retain for confirmation.
        def duplicate(other):
            overlap=np.count_nonzero((mask>0)&(other>0)); other_size=np.count_nonzero(other)
            return overlap/max(1,size+other_size-overlap)>.65 or (overlap/max(1,min(size,other_size))>.9 and min(size,other_size)/max(size,other_size)>.65)
        if any(duplicate(other) for other in masks): continue
        masks.append(mask)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()[:12]
    return masks, f"mobilesam-vit-t-{digest}+interior-colors-v3-boundaries"


def _climbing_model_masks(image: np.ndarray, deadline: float,
                          cancelled: Callable[[], bool], progress=lambda stage, value: None):
    """Return hold masks from the configured climbing-specific instance model."""
    config_value = os.getenv(
        "PHOTO_ROUTE_CLIMBING_MODEL_CONFIG", str(PACKAGED_CLIMBING_MODEL_CONFIG)
    )
    checkpoint_value = os.getenv(
        "PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT",
        str(PRODUCTION_CLIMBING_MODEL_CHECKPOINT),
    )
    config_path, checkpoint = Path(config_value), Path(checkpoint_value)
    if not config_path.is_file() or not checkpoint.is_file():
        raise PhotoProcessingError("岩点专项模型未配置，请检查本地配置和权重后重试")
    try:
        import torch
        from detectron2.config import get_cfg
        from detectron2.data.transforms import ResizeShortestEdge
        from detectron2.modeling import build_model
    except (ImportError, OSError) as exc:
        raise PhotoProcessingError("岩点专项模型运行环境不可用，请检查本地依赖") from exc
    if cancelled():
        raise InterruptedError("任务已取消")
    if time.monotonic() > deadline:
        raise TimeoutError("识别任务超过 180 秒")
    torch.set_num_threads(2)
    torch.manual_seed(0)
    cv2.setNumThreads(1)
    cfg = get_cfg()
    cfg.merge_from_file(str(config_path))
    cfg.MODEL.DEVICE = "cpu"
    cfg.MODEL.WEIGHTS = ""
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = .4
    # The local and production runtime intentionally have one accepted profile.
    # Force it after loading the model architecture so stale comparison configs
    # cannot silently select a lower inference size or candidate cap.
    _apply_production_climbing_profile(cfg)
    if cfg.MODEL.ROI_HEADS.NUM_CLASSES != 2 or not cfg.MODEL.MASK_ON:
        raise PhotoProcessingError("岩点专项模型配置与现有识别流程不兼容")
    cfg.freeze()
    progress("载入岩点专项模型", 25)
    model = build_model(cfg)
    weights = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(weights["model"], strict=True)
    del weights
    model.eval()
    transform = ResizeShortestEdge([cfg.INPUT.MIN_SIZE_TEST, cfg.INPUT.MIN_SIZE_TEST], cfg.INPUT.MAX_SIZE_TEST)
    resized = transform.get_transform(image).apply_image(image)
    tensor = torch.as_tensor(np.ascontiguousarray(resized.transpose(2, 0, 1)).astype("float32"))
    progress("识别岩点轮廓", 45)
    with torch.inference_mode():
        instances = model([{"image": tensor, "height": image.shape[0], "width": image.shape[1]}])[0]["instances"].to("cpu")
    if cancelled():
        raise InterruptedError("任务已取消")
    if time.monotonic() > deadline:
        raise TimeoutError("识别任务超过 180 秒")
    classes = instances.pred_classes.numpy()
    keep = classes == 0
    masks = [(mask.astype(np.uint8) * 255) for mask in instances.pred_masks.numpy()[keep]]
    scores = [float(value) for value in instances.scores.numpy()[keep]]
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()[:12]
    return masks, scores, (
        f"indoor-maskrcnn-{digest}"
        f"+min{PRODUCTION_CLIMBING_MIN_SIZE}-cap{PRODUCTION_CLIMBING_CANDIDATE_CAP}"
    )


def _apply_production_climbing_profile(cfg) -> None:
    """Lock every production caller to the accepted 1200 / 300 profile."""
    cfg.INPUT.MIN_SIZE_TEST = PRODUCTION_CLIMBING_MIN_SIZE
    cfg.INPUT.MAX_SIZE_TEST = max(PRODUCTION_CLIMBING_MIN_SIZE, int(cfg.INPUT.MAX_SIZE_TEST))
    cfg.TEST.DETECTIONS_PER_IMAGE = PRODUCTION_CLIMBING_CANDIDATE_CAP


def detect_photo_hole_grid(image: np.ndarray, source_ratio: float = 1.0) -> dict | None:
    """Fit the real 20×30 wall lattice from repeated dark hole evidence.

    A single dark blob is weak evidence on a textured climbing wall. The complete
    lattice is strong evidence: all 600 predicted intersections must improve
    together while the six affine parameters are adjusted. Holds may hide some
    holes without pulling the grid away from the remaining rows and columns.
    """
    if image is None or image.ndim != 3 or min(image.shape[:2]) < 320 or source_ratio <= 0:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    height, width = gray.shape
    dark_response = np.maximum(
        cv2.GaussianBlur(gray, (0, 0), 2.8) - cv2.GaussianBlur(gray, (0, 0), .55), 0,
    )
    # origin_x, origin_y, column_dx, column_dy, row_dx, row_dy
    params = np.asarray([
        .03 * width, .035 * height,
        .94 * width / (GRID_COLUMNS - 1), .04 * height / (GRID_COLUMNS - 1),
        -.09 * width / (GRID_ROWS - 1), .88 * height / (GRID_ROWS - 1),
    ], dtype=np.float64)

    def responses(candidate: np.ndarray) -> np.ndarray:
        values = []
        for row in range(GRID_ROWS):
            for column in range(GRID_COLUMNS):
                x, y = candidate[:2] + column * candidate[2:4] + row * candidate[4:6]
                px, py = int(round(x)), int(round(y))
                if 2 <= px < width - 2 and 2 <= py < height - 2:
                    values.append(min(55.0, float(dark_response[py-2:py+3, px-2:px+3].max())))
                else:
                    values.append(0.0)
        return np.asarray(values, dtype=np.float64)

    def score(candidate: np.ndarray) -> float:
        values = responses(candidate)
        ordered = np.sort(values)
        return float(values.sum() + .2 * ordered[100:400].sum())

    best_score = score(params)
    steps = np.asarray([20, 20, 2.5, 1.2, 1.2, 2.5], dtype=np.float64) * max(width / 810, height / 1440)
    for _ in range(14):
        improved = True
        while improved:
            improved = False
            for index in range(len(params)):
                for direction in (-1, 1):
                    candidate = params.copy()
                    candidate[index] += direction * steps[index]
                    candidate_score = score(candidate)
                    if candidate_score > best_score:
                        params, best_score, improved = candidate, candidate_score, True
        steps *= .65

    phase_scores = []
    for offset in (params[2:4] * .5, params[4:6] * .5, (params[2:4] + params[4:6]) * .5):
        shifted = params.copy()
        shifted[:2] += offset
        phase_scores.append(score(shifted))
    contrast = max(0.0, best_score / max(1.0, max(phase_scores)) - 1.0)
    values = responses(params)
    support_count = int(np.count_nonzero(values >= 8.0))
    confidence = min(.94, .45 + min(.34, contrast * 3.5) + min(.15, support_count / 1200))
    if contrast < .025 or support_count < 60:
        return None

    origin = params[:2] / source_ratio
    column_vector = params[2:4] / source_ratio
    row_vector = params[4:6] / source_ratio
    photo_points = np.float32([
        origin,
        origin + (GRID_COLUMNS - 1) * column_vector,
        origin + (GRID_ROWS - 1) * row_vector,
    ])
    board_points = np.float32([
        [200, BOARD_HEIGHT_MM - 300],
        [200 + (GRID_COLUMNS - 1) * HOLE_SPACING_MM, BOARD_HEIGHT_MM - 300],
        [200, 100],
    ])
    affine = cv2.getAffineTransform(photo_points, board_points)
    matrix = np.vstack([affine, [0.0, 0.0, 1.0]])
    return {
        "matrix": matrix.tolist(),
        "method": "detected-hole-grid-affine-v1",
        "status": "needs_review",
        "confidence": round(float(confidence), 4),
        "detected_hole_count": support_count,
        "photo_grid": {
            "origin": [round(float(value), 3) for value in origin],
            "column_vector": [round(float(value), 5) for value in column_vector],
            "row_vector": [round(float(value), 5) for value in row_vector],
            "columns": GRID_COLUMNS,
            "rows": GRID_ROWS,
            "center_column": GRID_COLUMNS // 2,
        },
    }


@serialized_inference
def analyze_board_photo(photo_path: Path, storage_root: Path, *,
                        cancelled: Callable[[], bool] | None = None,
                        deadline: float | None = None, seed: tuple[float, float] | None = None,
                        color_group: str | None = None, calibration: dict | None = None,
                        progress: Callable[[str, int], None] | None = None, coarse_only: bool = False,
                        require_mobilesam: bool = False, require_climbing_model: bool = False,
                        color_version: str = BASELINE_COLOR_VERSION, boundary_refinement: bool | None = None) -> dict:
    """Produce local object, colour, hole and initial anchor proposals."""
    cancelled = cancelled or (lambda: False)
    if color_version not in COLOR_VERSIONS:
        raise ValueError(f"未知分色版本：{color_version}")
    if coarse_only and (require_mobilesam or require_climbing_model):
        raise ValueError("粗略识别不能同时要求完整模型")
    if require_mobilesam and require_climbing_model:
        raise ValueError("一次识别只能选择一个轮廓模型")
    refine_edges = require_mobilesam if boundary_refinement is None else boundary_refinement
    if require_climbing_model:
        refine_edges = False
    deadline = deadline or time.monotonic() + 180
    progress = progress or (lambda stage, percent: None)
    progress("检查照片与工作尺寸", 12)
    image = decode_photo(photo_path.read_bytes())
    quality = assess_capture_quality(image)
    if not quality.accepted:
        raise PhotoProcessingError("；".join(quality.issues))
    original_height, original_width = image.shape[:2]
    work, ratio = _working_image(image)
    if require_mobilesam and max(work.shape[:2])>1280:
        ratio=1280/max(image.shape[:2])
        work=cv2.resize(image,(round(original_width*ratio),round(original_height*ratio)),interpolation=cv2.INTER_AREA)
    height, width = work.shape[:2]
    matrix = compute_homography(
        [[0, original_height], [original_width, original_height], [original_width, 0], [0, 0]],
        [[0, 0], [BOARD_WIDTH_MM, 0], [BOARD_WIDTH_MM, BOARD_HEIGHT_MM], [0, BOARD_HEIGHT_MM]],
    )
    detected_calibration = None
    if calibration and calibration.get("matrix"):
        matrix = calibration["matrix"]
    elif not require_climbing_model:
        detected_calibration = detect_photo_hole_grid(work, ratio)
        if detected_calibration:
            matrix = detected_calibration["matrix"]
    proposals = []
    candidate_scores = None
    progress("全图候选识别", 20)
    if require_climbing_model:
        work = image
        ratio = 1.0
        candidate_masks, candidate_scores, model_version = _climbing_model_masks(image, deadline, cancelled, progress)
    elif seed is not None:
        repo, checkpoint = mobilesam_paths()
        sys.path.insert(0, str(repo))
        from core.photo_route_mobilesam import extract_with_mobilesam
        extraction = extract_with_mobilesam(image, seed, checkpoint=checkpoint,
            cancelled=cancelled, timeout_seconds=max(.1, deadline-time.monotonic()),
            batch_size=2, prune_inspection=True, progress=progress)
        work = extraction.image
        candidate_masks = [item.mask for item in extraction.candidates]
        if not candidate_masks:
            raise PhotoProcessingError("该采样颜色未找到可靠对象，请换一个颜色清晰的位置重试；原版本已保留")
        model_version = "mobilesam-vit-t-" + hashlib.sha256(checkpoint.read_bytes()).hexdigest()[:12] + "+color-refine-v6"
    else:
        mobile = None if coarse_only else _mobilesam_masks(work, deadline, cancelled, progress)
        if mobile is None and require_mobilesam:
            raise PhotoProcessingError("全图识别需要本地 MobileSAM 模型，请检查模型配置后重试")
        candidate_masks, model_version = mobile if mobile is not None else (_candidate_masks(work), "local-rules-v3-no-mobilesam")
    ratio=work.shape[1]/original_width
    height,width=work.shape[:2]
    progress("原图边缘精修与内部分色" if refine_edges else "从轮廓内部取样分色", 65)
    for index, mask in enumerate(candidate_masks, 1):
        if cancelled():
            raise InterruptedError("任务已取消")
        if time.monotonic() > deadline:
            raise TimeoutError("识别任务超过 180 秒")
        source_ratio = ratio
        source_image = work
        offset_x = offset_y = 0
        if refine_edges:
            offset_x, offset_y, mask = refine_boundary(image, mask)
            source_image = image[offset_y:offset_y+mask.shape[0], offset_x:offset_x+mask.shape[1]]
            source_ratio = 1
            progress("原图边缘精修与内部分色",65+round(index/max(1,len(candidate_masks))*20))
        ys, xs = np.where(mask > 0)
        x, y, right, bottom = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
        crop_mask = mask[y:bottom, x:right]
        crop = source_image[y:bottom, x:right].copy()
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = crop_mask
        mask_ref = _write_asset(storage_root, _encode_png(crop_mask), "png", right - x, bottom - y)
        cutout_ref = _write_asset(storage_root, _encode_png(rgba), "png", right - x, bottom - y)
        colour = classify_mask_color(source_image,mask,version=color_version)
        source_cx, source_cy = (offset_x + (x + right) / 2) / source_ratio, (offset_y + (y + bottom) / 2) / source_ratio
        board_x, board_y = map_point(matrix, source_cx, source_cy)
        anchors = []
        if not require_climbing_model:
            hole, distance = nearest_hole(board_x, board_y)
            anchors = [{"hole_id": hole["id"], "x_mm": hole["x_mm"], "y_mm": hole["y_mm"],
                        "confidence": round(max(0.0, 1.0 - distance / 150.0), 4), "confirmed": False}]
        object_confidence = (candidate_scores[index - 1] if candidate_scores is not None else
            min(.96, .58 + (len(xs) / max((right - x) * (bottom - y), 1)) * .38))
        proposals.append({
            "id": f"object-{index:03d}",
            "kind": "hold" if require_climbing_model else
                ("volume" if len(xs) / source_ratio**2 > original_height * original_width * .012 else "hold"),
            "color_group": colour,
            "contour": [[round(float((px + x + offset_x) / source_ratio), 2), round(float((py + y + offset_y) / source_ratio), 2)]
                        for px, py in cv2.approxPolyDP(max(cv2.findContours(crop_mask, cv2.RETR_EXTERNAL,
                            cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea), .65 if refine_edges else 2.0, True)[:, 0]],
            "source_bbox_px": [round((x+offset_x) / source_ratio), round((y+offset_y) / source_ratio), round((right - x) / source_ratio), round((bottom - y) / source_ratio)],
            "cutout": cutout_ref,
            "mask": mask_ref,
            "center_x_mm": round(board_x, 3), "center_y_mm": round(board_y, 3),
            "rotation_deg": 0.0,
            "scale_mm_per_px": round(projected_bbox_scale_mm_per_px(matrix, [
                (x + offset_x) / source_ratio,
                (y + offset_y) / source_ratio,
                (right - x) / source_ratio,
                (bottom - y) / source_ratio,
            ]), 8),
            "confidence": round(object_confidence, 4),
            "review_status": "needs_review",
            "anchors": anchors,
        })
    detector = "climbing-mask-rcnn" if require_climbing_model else ("sam-proposals" if model_version.startswith("mobilesam") else "local-rules")
    processing_config = {"detector": detector,
        "segmentation_model": model_version.split('+',1)[0], "color_version": color_version,
        "boundary_version": "grabcut-band-v1" if refine_edges else "off",
        "working_size": [width, height], "max_seconds": 180,
        "min_size_test": PRODUCTION_CLIMBING_MIN_SIZE if require_climbing_model else None,
        "detections_per_image": PRODUCTION_CLIMBING_CANDIDATE_CAP if require_climbing_model else None,
        "automatic_mask_parameters": dict(AUTOMATIC_MASK_PARAMETERS) if seed is None and model_version.startswith('mobilesam') else None}
    if color_version != BASELINE_COLOR_VERSION or boundary_refinement is not None:
        model_version += f"+{color_version}+boundary-{'on' if refine_edges else 'off'}"
    return {
        "processing_config": processing_config,
        "quality": {"accepted": quality.accepted, "issues": quality.issues, "metrics": quality.metrics},
        "calibration": calibration or detected_calibration or {
            "matrix": matrix,
            "method": "board-boundary-provisional",
            "detected_hole_count": 0,
            "confidence": .35,
            "status": "needs_review",
        },
        "objects": proposals,
        "model_version": model_version,
        "input_fingerprint": hashlib.sha256(photo_path.read_bytes()).hexdigest(),
        "warnings": ([] if proposals else ["未自动识别到可靠岩点，请手动添加对象"]),
    }


def mobilesam_paths() -> tuple[Path, Path]:
    repo_value = os.getenv("PHOTO_ROUTE_MOBILESAM_REPO", "")
    checkpoint_value = os.getenv("PHOTO_ROUTE_MOBILESAM_CHECKPOINT", "")
    repo, checkpoint = Path(repo_value), Path(checkpoint_value)
    if not repo_value or not checkpoint_value or not (repo / "mobile_sam").is_dir() or not checkpoint.is_file():
        raise PhotoProcessingError("颜色精修需要配置本地 MobileSAM 模型；当前只有简化初识别，未执行精修")
    return repo.resolve(), checkpoint.resolve()


def fingerprint_payload(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
