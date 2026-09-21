"""Experimental, opt-in video replay analysis for climbing attempts.

This module is deliberately isolated from the photo-route recognition pipeline.
It owns a small file-backed job queue. Hold segmentation reuses the verified
local climbing-specific model, while pose estimation uses sampled still frames
through a mainland-accessible provider. Registration is controlled by
``ENABLE_CLIMB_REPLAY`` and is enabled by default for existing installations.

The model contract and contact heuristics are based on Jeremy Park's
Apache-2.0 ``vision-demos/rock_climbing`` reference implementation.  This first
slice returns reviewable structured evidence.  It does not make coaching,
difficulty, or injury-risk claims and it does not mutate a saved route.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import queue
import shutil
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field

from core.chunked_upload import ChunkUploadError, ChunkUploadStore
from core.photo_route_analysis import _climbing_model_masks, _colour_name
from core.photo_route_colors import CANDIDATE_COLOR_VERSION, classify_mask_color
from core.photo_route_inference_lock import serialized_inference


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_after(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


REPLAY_CONSENT_VERSION = "climb-replay-pose-frames-v1-2026-09-20"
REPLAY_CONSENT_PROVIDER = "阿里云视觉智能开放平台"
REPLAY_CONSENT_SERVICE = "BodyPosture"
REPLAY_CONSENT_DATA_TYPES = ["降帧后的单张视频画面", "画面中的人体姿态关键点"]
REPLAY_PIPELINE_VERSION = "climb-replay-v2.5-distilled-chinese-timeline"
REPLAY_POSE_API_VERSION = "2019-12-30"
DEFAULT_POSE_UNIT_PRICE_CNY = 0.0016
REPLAY_RETENTION_DELETE = "delete_after_processing"
REPLAY_RETENTION_KEEP = "keep_private_original"
ReplayRetentionMode = Literal["delete_after_processing", "keep_private_original"]
REPLAY_OVERLAY_FILENAME = "overlay.webm"
REPLAY_OVERLAY_MEDIA_KIND = "overlay_video"


class ReplayConfigurationError(RuntimeError):
    """Raised when the opt-in pose provider has no usable configuration."""


class ReplayCancelled(RuntimeError):
    """Raised between analysis stages after a user asks to cancel."""


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 200 * 1024 * 1024
    max_duration_seconds: float = 90.0
    max_width: int = 1920
    max_height: int = 1080
    max_frames: int = 2700


class ReplayUploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    route_id: str = Field(default="", max_length=64)
    route_color: str = Field(default="", max_length=40)
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool
    retention_mode: ReplayRetentionMode = REPLAY_RETENTION_DELETE


class ReplayRetryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float
    size_bytes: int


def probe_video(path: Path) -> VideoInfo:
    """Read enough metadata to reject unsafe or unsupported uploads."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("无法读取视频，请上传标准 MP4 文件")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
        raise ValueError("视频缺少有效的尺寸、帧率或时长信息")
    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=frame_count / fps,
        size_bytes=path.stat().st_size,
    )


def validate_video(info: VideoInfo, limits: VideoLimits) -> None:
    if info.size_bytes > limits.max_bytes:
        raise ValueError(f"视频不能超过 {limits.max_bytes // (1024 * 1024)} MB")
    if info.duration_seconds > limits.max_duration_seconds + 0.05:
        raise ValueError(f"试用阶段仅支持 {limits.max_duration_seconds:g} 秒以内的视频")
    allowed_long = max(limits.max_width, limits.max_height)
    allowed_short = min(limits.max_width, limits.max_height)
    if max(info.width, info.height) > allowed_long or min(info.width, info.height) > allowed_short:
        raise ValueError(f"试用阶段最高支持 {limits.max_width}×{limits.max_height}（支持横竖屏）")
    if info.frame_count > limits.max_frames:
        raise ValueError(f"试用阶段最多处理 {limits.max_frames} 帧")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


POSE_EDGES = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
)
LIMB_OVERLAY_NAMES = {
    "left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚",
}
_CJK_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)
_CJK_FONT_PATH = next((path for path in _CJK_FONT_CANDIDATES if path.is_file()), None)
_CJK_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def draw_cjk_labels(frame: np.ndarray, labels: list[dict]) -> None:
    """Draw all Chinese labels in one Pillow pass to keep video rendering fast."""
    if not labels:
        return
    if _CJK_FONT_PATH is None:
        for label in labels:
            _overlay_text(
                frame, str(label.get("fallback") or ""), tuple(label["origin"]),
                scale=max(.18, float(label.get("size") or 12) / 28),
                color=tuple(label.get("color") or (235, 239, 241)),
            )
        return
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    drawer = ImageDraw.Draw(image)
    for label in labels:
        size = max(8, int(label.get("size") or 12))
        font = _CJK_FONT_CACHE.get(size)
        if font is None:
            font = ImageFont.truetype(str(_CJK_FONT_PATH), size=size)
            _CJK_FONT_CACHE[size] = font
        bgr = tuple(int(value) for value in label.get("color") or (235, 239, 241))
        drawer.text(
            tuple(int(value) for value in label["origin"]),
            str(label.get("text") or ""), font=font,
            fill=(bgr[2], bgr[1], bgr[0]),
        )
    frame[:] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def build_pose_samples(records: list[dict], video_info: VideoInfo) -> list[dict]:
    """Preserve exact sampled-frame evidence without inventing interpolated poses."""
    samples = []
    for record in sorted(records, key=lambda item: int(item.get("frame_id", -1))):
        scores = [float(value or 0) for value in record.get("kpts_score") or []]
        usable_scores = [value for value in scores if value >= 0.15]
        source_frame = int(record.get("source_frame_id") or 0)
        samples.append({
            "sample_index": int(record.get("frame_id") or 0),
            "source_frame_id": source_frame,
            "time_seconds": round(source_frame / max(video_info.fps, 1e-9), 6),
            "observed": bool(usable_scores),
            "confidence": round(float(np.mean(usable_scores)), 6) if usable_scores else 0.0,
            "kpts_xy": record.get("kpts_xy") or [[0.0, 0.0] for _ in range(17)],
            "kpts_score": scores or [0.0] * 17,
            "bbox_xywh": record.get("bbox_xywh") or [0.0, 0.0, 0.0, 0.0],
        })
    return samples


def add_attempt_source_times(attempt: dict, pose_samples: list[dict], video_info: VideoInfo) -> dict:
    """Map sample-index events back to original frame numbers and playback time."""
    by_sample = {int(sample["sample_index"]): sample for sample in pose_samples}

    def sample_value(index: Any) -> dict | None:
        try:
            return by_sample.get(int(index))
        except (TypeError, ValueError):
            return None

    for contact in attempt.get("contacts") or []:
        start = sample_value(contact.get("start_frame"))
        end = sample_value(contact.get("end_frame"))
        if start:
            contact["start_source_frame"] = start["source_frame_id"]
            contact["start_time_seconds"] = start["time_seconds"]
        if end:
            contact["end_source_frame"] = end["source_frame_id"]
            contact["end_time_seconds"] = end["time_seconds"]
    for field in ("start", "completion"):
        sample = sample_value(attempt.get(f"{field}_frame"))
        if sample:
            attempt[f"{field}_source_frame"] = sample["source_frame_id"]
            attempt[f"{field}_time_seconds"] = sample["time_seconds"]
    if (attempt.get("start_time_seconds") is not None
            and attempt.get("completion_time_seconds") is not None):
        attempt["elapsed_seconds"] = round(
            attempt["completion_time_seconds"] - attempt["start_time_seconds"], 6,
        )
    for point in attempt.get("midline") or []:
        sample = sample_value(point.get("frame"))
        if sample:
            point["source_frame_id"] = sample["source_frame_id"]
            point["time_seconds"] = sample["time_seconds"]
    return attempt


def build_action_steps(contacts: list[dict]) -> list[dict]:
    """Return one chronological, auditable hand/foot-to-hold action ledger.

    The limb remains the primary label.  ``supplementary_name`` adds a conservative
    Chinese description derived only from confirmed contact relationships; technique
    names that require force direction or detailed pose evidence are deliberately not
    guessed here.
    """
    limb_order = {"left_hand": 0, "right_hand": 1, "left_foot": 2, "right_foot": 3}
    ordered = sorted(
        (
            contact for contact in contacts
            if contact.get("hold_id") is not None
            and contact.get("start_source_frame") is not None
        ),
        key=lambda contact: (
            int(contact.get("start_source_frame") or 0),
            limb_order.get(str(contact.get("limb") or ""), 9),
            int(contact.get("hold_id") or 0),
        ),
    )
    first_frame = min(
        (int(contact.get("start_source_frame") or 0) for contact in ordered),
        default=0,
    )
    steps = []
    previous_hold_by_limb: dict[str, int] = {}
    for index, contact in enumerate(ordered, start=1):
        limb = str(contact.get("limb") or "")
        hold_id = int(contact.get("hold_id") or 0)
        start_frame = int(contact.get("start_source_frame") or 0)
        end_frame = int(
            contact.get("end_source_frame")
            if contact.get("end_source_frame") is not None
            else contact.get("start_source_frame") or 0
        )
        source_hold_id = previous_hold_by_limb.get(limb)
        limb_kind = "hand" if limb.endswith("hand") else "foot" if limb.endswith("foot") else ""
        active_same_hold = next((
            prior for prior in reversed(steps)
            if prior["limb"] != limb
            and int(prior["hold_id"]) == hold_id
            and int(prior["start_source_frame"]) <= start_frame <= int(prior["end_source_frame"])
        ), None)

        if start_frame == first_frame:
            action_code, action_name = "START_CONTACT", "起步接触"
        elif active_same_hold:
            other_limb = str(active_same_hold.get("limb") or "")
            other_kind = "hand" if other_limb.endswith("hand") else "foot" if other_limb.endswith("foot") else ""
            if limb_kind == other_kind == "hand":
                action_code, action_name = "HAND_MATCH", "双手匹配"
            elif limb_kind == other_kind == "foot":
                action_code, action_name = "FOOT_MATCH", "双脚匹配"
            else:
                action_code, action_name = "HAND_FOOT_MATCH", "手脚同点"
        elif source_hold_id == hold_id:
            action_code, action_name = (
                ("HAND_READJUST", "原点调整") if limb_kind == "hand"
                else ("FOOT_READJUST", "原点调整")
            )
        elif source_hold_id is not None:
            action_code, action_name = (
                ("HAND_MOVE", "换点") if limb_kind == "hand"
                else ("FOOT_MOVE", "换点")
            )
        else:
            action_code, action_name = (
                ("HAND_CONTACT", "上点") if limb_kind == "hand"
                else ("FOOT_CONTACT", "上点")
            )

        if source_hold_id is not None and source_hold_id != hold_id and action_name == "换点":
            supplementary_name = f"{action_name} {source_hold_id}→{hold_id}"
        else:
            supplementary_name = f"{action_name} {hold_id}"

        step = {
            "step": index,
            "limb": limb,
            "hold_id": hold_id,
            "source_hold_id": source_hold_id,
            "start_source_frame": start_frame,
            "end_source_frame": end_frame,
            "start_time_seconds": contact.get("start_time_seconds"),
            "end_time_seconds": contact.get("end_time_seconds"),
            "action_code": action_code,
            "action_name": action_name,
            "supplementary_name": supplementary_name,
            "action_name_confidence": "confirmed_contact_relation",
            "action_name_version": "zh-action-v1",
        }
        steps.append(step)
        previous_hold_by_limb[limb] = hold_id
    return steps


def build_visible_action_markers(actions: list[dict], frame_index: int) -> dict[int, list[dict]]:
    """Group every reached action by hold, retaining repeated touches in order."""
    markers: dict[int, list[dict]] = defaultdict(list)
    for fallback_step, action in enumerate(actions, start=1):
        start = action.get("start_source_frame")
        hold_id = int(action.get("hold_id") or 0)
        if start is None or int(start) > frame_index or hold_id <= 0:
            continue
        markers[hold_id].append({
            "step": int(action.get("step") or fallback_step),
            "limb": str(action.get("limb") or ""),
        })
    return markers


def build_pose_render_timeline(pose_samples: list[dict], total_frames: int) -> dict[int, dict]:
    """Locally smooth adjacent measured samples without creating new pose evidence."""
    all_frames = sorted({
        int(sample.get("source_frame_id") or 0)
        for sample in pose_samples
        if 0 <= int(sample.get("source_frame_id") or 0) < total_frames
    })
    gaps = [right - left for left, right in zip(all_frames, all_frames[1:]) if right > left]
    nominal_gap = float(np.median(gaps)) if gaps else 1.0
    maximum_gap = max(1, round(nominal_gap * 1.75))
    observed = sorted(
        (
            sample for sample in pose_samples
            if sample.get("observed")
            and 0 <= int(sample.get("source_frame_id") or 0) < total_frames
        ),
        key=lambda sample: int(sample.get("source_frame_id") or 0),
    )
    timeline: dict[int, dict] = {}

    def measured(sample: dict, mode: str) -> dict:
        return {
            "source_frame_id": int(sample.get("source_frame_id") or 0),
            "kpts_xy": sample.get("kpts_xy") or [],
            "kpts_score": sample.get("kpts_score") or [],
            "render_mode": mode,
        }

    for sample in observed:
        timeline[int(sample.get("source_frame_id") or 0)] = measured(sample, "measured")

    for left, right in zip(observed, observed[1:]):
        left_frame = int(left.get("source_frame_id") or 0)
        right_frame = int(right.get("source_frame_id") or 0)
        gap = right_frame - left_frame
        if gap <= 1 or gap > maximum_gap:
            continue
        left_points, right_points = left.get("kpts_xy") or [], right.get("kpts_xy") or []
        left_scores, right_scores = left.get("kpts_score") or [], right.get("kpts_score") or []
        keypoint_count = min(len(left_points), len(right_points), len(left_scores), len(right_scores))
        for frame_index in range(left_frame + 1, right_frame):
            alpha = (frame_index - left_frame) / gap
            points, scores = [], []
            for keypoint in range(keypoint_count):
                left_score, right_score = (
                    float(left_scores[keypoint] or 0), float(right_scores[keypoint] or 0),
                )
                if left_score >= .15 and right_score >= .15:
                    points.append([
                        round(float(left_points[keypoint][0]) * (1 - alpha)
                              + float(right_points[keypoint][0]) * alpha, 6),
                        round(float(left_points[keypoint][1]) * (1 - alpha)
                              + float(right_points[keypoint][1]) * alpha, 6),
                    ])
                    scores.append(round(left_score * (1 - alpha) + right_score * alpha, 6))
                elif left_score >= .15:
                    points.append(list(left_points[keypoint]))
                    scores.append(round(left_score * max(0.0, 1 - alpha), 6))
                elif right_score >= .15:
                    points.append(list(right_points[keypoint]))
                    scores.append(round(right_score * max(0.0, alpha), 6))
                else:
                    points.append([0.0, 0.0])
                    scores.append(0.0)
            timeline[frame_index] = {
                "source_frame_id": frame_index,
                "kpts_xy": points,
                "kpts_score": scores,
                "render_mode": "interpolated",
                "left_sample_frame": left_frame,
                "right_sample_frame": right_frame,
            }

    if observed:
        first = observed[0]
        first_frame = int(first.get("source_frame_id") or 0)
        for frame_index in range(max(0, first_frame - maximum_gap), first_frame):
            timeline[frame_index] = measured(first, "edge_hold")
        last = observed[-1]
        last_frame = int(last.get("source_frame_id") or 0)
        for frame_index in range(last_frame + 1, min(total_frames, last_frame + maximum_gap + 1)):
            timeline[frame_index] = measured(last, "edge_hold")
    return timeline


def _draw_overlay_label(frame: np.ndarray, text: str, origin: tuple[int, int],
                        *, background: tuple[int, int, int]) -> None:
    scale = max(0.42, min(frame.shape[:2]) / 900)
    thickness = max(1, round(scale * 2))
    (width, height), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness,
    )
    x, y = origin
    cv2.rectangle(
        frame, (x, max(0, y - height - 8)),
        (min(frame.shape[1] - 1, x + width + 10), min(frame.shape[0] - 1, y + baseline + 4)),
        background, -1,
    )
    cv2.putText(
        frame, text, (x + 5, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
        (255, 255, 255), thickness, cv2.LINE_AA,
    )


REPLAY_LIMB_COLORS = {
    "left_hand": (235, 196, 80),
    "right_hand": (193, 92, 237),
    "left_foot": (106, 179, 255),
    "right_foot": (87, 222, 143),
}


def _overlay_text(frame: np.ndarray, text: str, origin: tuple[int, int], *,
                  scale: float, color: tuple[int, int, int] = (235, 239, 241),
                  thickness: int = 1) -> None:
    cv2.putText(
        frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
        color, thickness, cv2.LINE_AA,
    )


def _scaled_hold_box(hold: dict, *, x: int, y: int, width: int, height: int,
                     minimum: int = 3) -> tuple[int, int, int, int]:
    bx, by, box_width, box_height = hold.get("bbox") or [0, 0, 0, 0]
    x0 = round(x + float(bx) * width)
    y0 = round(y + float(by) * height)
    x1 = round(x + (float(bx) + float(box_width)) * width)
    y1 = round(y + (float(by) + float(box_height)) * height)
    if x1 - x0 < minimum:
        x1 = x0 + minimum
    if y1 - y0 < minimum:
        y1 = y0 + minimum
    return x0, y0, x1, y1


def _scaled_hold_polygon(hold: dict, *, x: int, y: int, width: int,
                         height: int, minimum: int = 3) -> np.ndarray:
    polygon = hold.get("polygon") or []
    if isinstance(polygon, list) and len(polygon) >= 3:
        points = np.asarray([
            [round(x + float(point[0]) * width), round(y + float(point[1]) * height)]
            for point in polygon if isinstance(point, (list, tuple)) and len(point) >= 2
        ], dtype=np.int32)
        if len(points) >= 3:
            return points.reshape((-1, 1, 2))
    x0, y0, x1, y1 = _scaled_hold_box(
        hold, x=x, y=y, width=width, height=height, minimum=minimum,
    )
    return np.asarray(
        [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32,
    ).reshape((-1, 1, 2))


def native_mask_polygon(mask: np.ndarray, *, max_points: int = 1024) -> np.ndarray:
    """Keep the climbing model's native mask edge with only a safety-size cap.

    The former replay path applied a perimeter-relative approximation to every
    hold. On small or irregular holds that removed exactly the corners and
    notches users need to recognise. CHAIN_APPROX_SIMPLE is lossless for
    straight pixel runs; an additional approximation is used only when a very
    complex mask would exceed the JSON/rendering safety cap.
    """
    max_points = max(3, int(max_points))
    binary = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.empty((0, 1, 2), dtype=np.int32)
    contour = max(contours, key=cv2.contourArea)
    if len(contour) <= max_points:
        return contour.astype(np.int32, copy=False)

    # Find the smallest tolerance that meets the cap, preserving as much of
    # the model boundary as the payload limit allows.
    low, high = 0.0, max(1.0, cv2.arcLength(contour, True))
    reduced = contour
    for _ in range(14):
        epsilon = (low + high) / 2
        candidate = cv2.approxPolyDP(contour, epsilon, True)
        if len(candidate) > max_points:
            low = epsilon
        else:
            high = epsilon
            reduced = candidate
    return reduced.astype(np.int32, copy=False)


def fit_aspect_rect(source_width: int, source_height: int, *, x: int, y: int,
                    width: int, height: int) -> tuple[int, int, int, int]:
    """Fit source coordinates into a destination without changing geometry."""
    scale = min(
        max(1, width) / max(1, source_width),
        max(1, height) / max(1, source_height),
    )
    fitted_width = max(1, round(source_width * scale))
    fitted_height = max(1, round(source_height * scale))
    return (
        x + (width - fitted_width) // 2,
        y + (height - fitted_height) // 2,
        fitted_width,
        fitted_height,
    )


def fit_hold_map_rect(holds: list[dict], source_width: int, source_height: int, *,
                      x: int, y: int, width: int, height: int,
                      padding: float = .10) -> tuple[int, int, int, int]:
    """Uniformly zoom the source coordinate plane around the detected route."""
    boxes = [
        hold.get("bbox") for hold in holds
        if isinstance(hold.get("bbox"), (list, tuple)) and len(hold["bbox"]) >= 4
    ]
    if not boxes:
        return fit_aspect_rect(
            source_width, source_height, x=x, y=y, width=width, height=height,
        )
    left = min(float(box[0]) for box in boxes)
    top = min(float(box[1]) for box in boxes)
    right = max(float(box[0]) + float(box[2]) for box in boxes)
    bottom = max(float(box[1]) + float(box[3]) for box in boxes)
    route_width = max(.02, right - left)
    route_height = max(.02, bottom - top)
    left = max(0.0, left - route_width * padding)
    right = min(1.0, right + route_width * padding)
    top = max(0.0, top - route_height * padding)
    bottom = min(1.0, bottom + route_height * padding)

    crop_width = max(1.0, (right - left) * source_width)
    crop_height = max(1.0, (bottom - top) * source_height)
    scale = min(max(1, width) / crop_width, max(1, height) / crop_height)
    mapped_width = max(1, round(source_width * scale))
    mapped_height = max(1, round(source_height * scale))
    crop_render_width = crop_width * scale
    crop_render_height = crop_height * scale
    return (
        round(x + (width - crop_render_width) / 2 - left * mapped_width),
        round(y + (height - crop_render_height) / 2 - top * mapped_height),
        mapped_width,
        mapped_height,
    )


def render_replay_overlay_video(
    source: Path,
    target: Path,
    result: dict,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Render a calm split view with a fixed wall map and measured pose samples."""
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError("无法读取原视频生成叠加视频")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if width <= 0 or height <= 0 or fps <= 0 or total <= 0:
        cap.release()
        raise RuntimeError("原视频信息不完整，无法生成叠加视频")
    output_width, output_height = width + width % 2, height + height % 2
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.tmp.webm")
    writer = cv2.VideoWriter(
        str(temporary), cv2.VideoWriter_fourcc(*"VP80"), fps,
        (output_width, output_height),
    )
    if not writer.isOpened():
        cap.release()
        temporary.unlink(missing_ok=True)
        raise RuntimeError("当前环境无法编码 WebM 叠加视频")

    holds = result.get("holds") or []
    pose_samples = result.get("pose_samples") or []
    pose_timeline = build_pose_render_timeline(pose_samples, total)
    contacts = result.get("attempt", {}).get("contacts") or []
    actions = result.get("attempt", {}).get("action_steps") or build_action_steps(contacts)
    ordered_contacts = sorted(
        contacts,
        key=lambda item: (
            int(item.get("start_source_frame") or 0),
            int(item.get("hold_id") or 0),
        ),
    )
    first_use: dict[int, int] = {}
    for contact in ordered_contacts:
        hold_id = int(contact.get("hold_id") or 0)
        start = contact.get("start_source_frame")
        if hold_id > 0 and start is not None:
            first_use[hold_id] = min(first_use.get(hold_id, total), int(start))

    panel_ratio = 0.36
    timeline_columns = min(
        max(1, len(actions)),
        max(5, min(10, output_width // 110)),
    ) if actions else 1
    timeline_rows = max(1, math.ceil(len(actions) / timeline_columns))
    action_strip_height = max(
        54,
        round(output_height * min(.28, .075 + .065 * timeline_rows)),
    ) if actions else max(42, round(output_height * .10))
    content_height = max(2, output_height - action_strip_height)
    video_pane_width = max(2, round(output_width * (1 - panel_ratio)))
    video_scale = min(video_pane_width / width, content_height / height)
    display_width = max(1, round(width * video_scale))
    display_height = max(1, round(height * video_scale))
    video_x = max(0, (video_pane_width - display_width) // 2)
    video_y = max(0, (content_height - display_height) // 2)

    panel_padding = max(6, round(min(output_width, output_height) * .018))
    panel_x = video_pane_width + panel_padding
    panel_width = max(1, output_width - panel_x - panel_padding)
    title_height = max(18, round(content_height * .085))
    footer_height = max(26, round(content_height * .15))
    map_y = title_height
    map_height = max(1, content_height - title_height - footer_height)
    route_map_x, route_map_y, route_map_width, route_map_height = fit_hold_map_rect(
        holds, width, height,
        x=panel_x, y=map_y, width=panel_width, height=map_height,
    )
    base_text_scale = max(.24, min(.62, min(output_width, output_height) / 1050))
    route_color = str((result.get("route") or {}).get("color") or "ROUTE")
    route_color_label = {
        "红色": "红色线路", "红": "红色线路", "red": "红色线路",
        "蓝色": "蓝色线路", "蓝": "蓝色线路", "blue": "蓝色线路",
        "绿色": "绿色线路", "绿": "绿色线路", "green": "绿色线路",
        "黄色": "黄色线路", "黄": "黄色线路", "yellow": "黄色线路",
        "橙色": "橙色线路", "橙": "橙色线路", "orange": "橙色线路",
        "紫色": "紫色线路", "紫": "紫色线路", "purple": "紫色线路",
        "粉色": "粉色线路", "粉": "粉色线路", "pink": "粉色线路",
        "白色": "白色线路", "白": "白色线路", "white": "白色线路",
        "黑色": "黑色线路", "黑": "黑色线路", "black": "黑色线路",
        "灰色": "灰色线路", "灰": "灰色线路", "gray": "灰色线路",
    }.get(route_color.strip().lower(), f"{route_color}线路" if route_color else "所选线路")
    timeline_padding = max(4, panel_padding // 2)
    timeline_title_height = max(16, round(action_strip_height * .19))
    timeline_gap = max(4, round(min(output_width, output_height) * .008))
    timeline_card_width = max(
        12,
        (output_width - timeline_padding * 2 - timeline_gap * (timeline_columns - 1))
        // timeline_columns,
    )
    timeline_card_height = max(
        10,
        (action_strip_height - timeline_title_height - timeline_padding * 2
         - timeline_gap * (timeline_rows - 1)) // timeline_rows,
    )

    def point_on_video(point: list[float]) -> tuple[int, int]:
        return (
            round(video_x + float(point[0]) * display_width),
            round(video_y + float(point[1]) * display_height),
        )

    def hold_center_on_map(hold: dict) -> tuple[int, int]:
        bx, by, box_width, box_height = hold.get("bbox") or [0, 0, 0, 0]
        return (
            round(route_map_x + (float(bx) + float(box_width) / 2) * route_map_width),
            round(route_map_y + (float(by) + float(box_height) / 2) * route_map_height),
        )

    frame_index = 0
    line_width = max(1, round(min(width, height) / 420))
    try:
        while True:
            if cancelled and cancelled():
                raise ReplayCancelled()
            ok, frame = cap.read()
            if not ok:
                break
            canvas = np.full((output_height, output_width, 3), (13, 16, 18), dtype=np.uint8)
            cjk_labels: list[dict] = []
            resized = cv2.resize(
                frame, (display_width, display_height),
                interpolation=cv2.INTER_AREA if video_scale < 1 else cv2.INTER_LINEAR,
            )
            canvas[video_y:video_y + display_height, video_x:video_x + display_width] = resized

            active = []
            active_by_hold: dict[int, str] = {}
            for contact in contacts:
                start = contact.get("start_source_frame")
                end = contact.get("end_source_frame")
                if start is None or end is None or not int(start) <= frame_index <= int(end):
                    continue
                limb = str(contact.get("limb") or "")
                hold_id = int(contact.get("hold_id") or 0)
                if hold_id > 0:
                    active.append((limb, hold_id))
                    active_by_hold[hold_id] = limb

            used_ids = {
                hold_id for hold_id, start_frame in first_use.items()
                if start_frame <= frame_index
            }
            visible_markers = build_visible_action_markers(actions, frame_index)

            # The video pane stays quiet: true fixed contours, no repeated hold labels.
            shape_layer = canvas.copy()
            shape_outlines: list[tuple[np.ndarray, tuple[int, int, int], int]] = []
            for hold in holds:
                hold_id = int(hold.get("id") or 0)
                polygon = _scaled_hold_polygon(
                    hold, x=video_x, y=video_y,
                    width=display_width, height=display_height,
                    minimum=max(2, line_width + 1),
                )
                color = (82, 111, 94)
                thickness = line_width
                if hold_id in used_ids:
                    color, thickness = (92, 196, 115), line_width + 1
                if hold_id in active_by_hold:
                    color = REPLAY_LIMB_COLORS.get(active_by_hold[hold_id], (96, 231, 151))
                    thickness = line_width + 2
                if hold_id in used_ids or hold_id in active_by_hold:
                    cv2.fillPoly(shape_layer, [polygon], color, cv2.LINE_AA)
                shape_outlines.append((polygon, color, thickness))
            canvas = cv2.addWeighted(shape_layer, .20, canvas, .80, 0)
            for polygon, color, thickness in shape_outlines:
                cv2.polylines(canvas, [polygon], True, color, thickness, cv2.LINE_AA)

            sample = pose_timeline.get(frame_index)
            if sample:
                points = sample.get("kpts_xy") or []
                scores = sample.get("kpts_score") or []
                for start, end in POSE_EDGES:
                    if (start >= len(points) or end >= len(points)
                            or start >= len(scores) or end >= len(scores)
                            or float(scores[start] or 0) < 0.15 or float(scores[end] or 0) < 0.15):
                        continue
                    start_point = point_on_video(points[start])
                    end_point = point_on_video(points[end])
                    cv2.line(canvas, start_point, end_point, (232, 222, 144), line_width + 1, cv2.LINE_AA)
                for point, score in zip(points, scores):
                    if float(score or 0) >= 0.15:
                        cv2.circle(
                            canvas, point_on_video(point),
                            line_width + 2, (245, 232, 151), -1, cv2.LINE_AA,
                        )

            # A fixed-coordinate route map carries identifiers and history.
            cv2.line(
                canvas, (video_pane_width, 0), (video_pane_width, content_height),
                (43, 49, 52), max(1, line_width), cv2.LINE_AA,
            )
            cjk_labels.extend([
                {
                    "text": "线路动作图", "fallback": "",
                    "origin": (panel_x, max(2, round(title_height * .08))),
                    "size": max(10, round(base_text_scale * 25)),
                    "color": (235, 239, 241),
                },
                {
                    "text": route_color_label, "fallback": "",
                    "origin": (panel_x, max(15, round(title_height * .48))),
                    "size": max(8, round(base_text_scale * 18)),
                    "color": (126, 211, 147),
                },
            ])

            visible_sequence = [
                int(action.get("hold_id") or 0) for action in actions
                if action.get("start_source_frame") is not None
                and int(action.get("start_source_frame") or 0) <= frame_index
                and int(action.get("hold_id") or 0) > 0
            ]
            hold_lookup = {int(hold.get("id") or 0): hold for hold in holds}
            for previous, current in zip(visible_sequence, visible_sequence[1:]):
                if previous in hold_lookup and current in hold_lookup:
                    cv2.line(
                        canvas, hold_center_on_map(hold_lookup[previous]),
                        hold_center_on_map(hold_lookup[current]),
                        (55, 119, 72), max(1, line_width), cv2.LINE_AA,
                    )

            for hold in holds:
                hold_id = int(hold.get("id") or 0)
                polygon = _scaled_hold_polygon(
                    hold, x=route_map_x, y=route_map_y,
                    width=route_map_width, height=route_map_height,
                    minimum=max(5, line_width * 3),
                )
                x0, y0, x1, y1 = _scaled_hold_box(
                    hold, x=route_map_x, y=route_map_y,
                    width=route_map_width, height=route_map_height,
                    minimum=max(5, line_width * 3),
                )
                color = (75, 82, 85)
                fill = False
                thickness = max(1, line_width)
                if hold_id in used_ids:
                    color, fill = (79, 176, 103), True
                if hold_id in active_by_hold:
                    color = REPLAY_LIMB_COLORS.get(active_by_hold[hold_id], (96, 231, 151))
                    fill = True
                if fill:
                    cv2.fillPoly(canvas, [polygon], color, cv2.LINE_AA)
                cv2.polylines(canvas, [polygon], True, color, thickness, cv2.LINE_AA)
                markers = visible_markers.get(hold_id) or []
                if markers:
                    badge_height = max(11, round(min(output_width, output_height) * .017))
                    badge_gap = max(2, badge_height // 6)
                    badge_width = max(22, round(badge_height * 1.75))
                    total_badge_height = len(markers) * badge_height + (len(markers) - 1) * badge_gap
                    badge_y = round((y0 + y1 - total_badge_height) / 2)
                    badge_y = max(map_y, min(content_height - footer_height - total_badge_height, badge_y))
                    badge_x = x1 + max(3, panel_padding // 3)
                    if badge_x + badge_width > output_width - panel_padding:
                        badge_x = x0 - badge_width - max(3, panel_padding // 3)
                    badge_x = max(video_pane_width + 2, badge_x)
                    for marker_index, marker in enumerate(markers):
                        marker_y = badge_y + marker_index * (badge_height + badge_gap)
                        limb = str(marker.get("limb") or "")
                        marker_color = REPLAY_LIMB_COLORS.get(limb, (126, 211, 147))
                        cv2.rectangle(
                            canvas, (badge_x, marker_y),
                            (badge_x + badge_width, marker_y + badge_height),
                            marker_color, -1, cv2.LINE_AA,
                        )
                        sequence_text = f"{int(marker.get('step') or 0):02d}"
                        sequence_scale = max(.2, badge_height / 34)
                        (sequence_width, sequence_height), _ = cv2.getTextSize(
                            sequence_text, cv2.FONT_HERSHEY_SIMPLEX, sequence_scale, 1,
                        )
                        _overlay_text(
                            canvas, sequence_text,
                            (
                                badge_x + max(1, (badge_width - sequence_width) // 2),
                                marker_y + max(sequence_height + 1, (badge_height + sequence_height) // 2),
                            ),
                            scale=sequence_scale, color=(18, 22, 24),
                        )

            footer_y = content_height - footer_height + max(12, panel_padding)
            cjk_labels.append({
                "text": f"已触及 {len(used_ids)}／{len(holds)}", "fallback": "",
                "origin": (panel_x, max(0, footer_y - max(9, round(base_text_scale * 17)))),
                "size": max(9, round(base_text_scale * 20)),
                "color": (126, 211, 147),
            })
            pose_label = (
                "实测姿态" if sample and sample.get("render_mode") == "measured"
                else "平滑姿态" if sample else "暂无姿态"
            )
            cjk_labels.append({
                "text": pose_label, "fallback": "",
                "origin": (max(5, video_x + panel_padding), max(3, video_y + panel_padding // 2)),
                "size": max(8, round(base_text_scale * 17)),
                "color": (224, 229, 231) if sample and sample.get("render_mode") == "measured"
                else (157, 164, 168),
            })

            # Chronological action ledger: every hand/foot contact keeps one stable slot.
            timeline_y = content_height
            cv2.line(
                canvas, (0, timeline_y), (output_width, timeline_y),
                (43, 49, 52), max(1, line_width), cv2.LINE_AA,
            )
            cjk_labels.append({
                "text": "动作顺序", "fallback": "",
                "origin": (timeline_padding, timeline_y + 3),
                "size": max(10, round(base_text_scale * 22)),
                "color": (235, 239, 241),
            })
            if actions:
                cards_y = timeline_y + timeline_title_height + timeline_padding
                node_radius = max(8, min(14, timeline_card_height // 4))
                for row in range(timeline_rows):
                    row_start = row * timeline_columns
                    row_count = min(timeline_columns, len(actions) - row_start)
                    if row_count <= 1:
                        continue
                    first_center = (
                        timeline_padding + timeline_card_width // 2,
                        cards_y + row * (timeline_card_height + timeline_gap) + node_radius + 2,
                    )
                    last_center = (
                        timeline_padding + (row_count - 1) * (timeline_card_width + timeline_gap)
                        + timeline_card_width // 2,
                        first_center[1],
                    )
                    cv2.line(
                        canvas, first_center, last_center,
                        (53, 59, 62), max(1, line_width), cv2.LINE_AA,
                    )
                for action_index, action in enumerate(actions):
                    row, column = divmod(action_index, timeline_columns)
                    x0 = timeline_padding + column * (timeline_card_width + timeline_gap)
                    y0 = cards_y + row * (timeline_card_height + timeline_gap)
                    center_x = x0 + timeline_card_width // 2
                    center_y = y0 + node_radius + 2
                    limb = str(action.get("limb") or "")
                    start_frame = int(action.get("start_source_frame") or 0)
                    end_frame = int(action.get("end_source_frame") or start_frame)
                    is_current = start_frame <= frame_index <= end_frame
                    is_completed = start_frame <= frame_index
                    limb_color = REPLAY_LIMB_COLORS.get(limb, (126, 211, 147))
                    if is_current:
                        fill_color, border_color, text_color = limb_color, (238, 241, 242), (16, 20, 22)
                    elif is_completed:
                        fill_color, border_color, text_color = limb_color, limb_color, (16, 20, 22)
                    else:
                        fill_color, border_color, text_color = (24, 28, 30), (67, 74, 77), (128, 137, 141)
                    cv2.circle(canvas, (center_x, center_y), node_radius, fill_color, -1, cv2.LINE_AA)
                    cv2.circle(
                        canvas, (center_x, center_y), node_radius,
                        border_color, max(1, line_width + (1 if is_current else 0)), cv2.LINE_AA,
                    )
                    step_text = f"{int(action.get('step') or action_index + 1):02d}"
                    step_scale = max(.20, node_radius / 30)
                    (step_width, step_height), _ = cv2.getTextSize(
                        step_text, cv2.FONT_HERSHEY_SIMPLEX, step_scale, 1,
                    )
                    _overlay_text(
                        canvas, step_text,
                        (
                            center_x - step_width // 2,
                            center_y + step_height // 2,
                        ),
                        scale=step_scale, color=text_color,
                    )
                    limb_name = LIMB_OVERLAY_NAMES.get(limb, "手脚")
                    limb_size = max(9, min(13, timeline_card_height // 4))
                    text_width = len(limb_name) * limb_size
                    cjk_labels.append({
                        "text": limb_name, "fallback": "",
                        "origin": (
                            center_x - text_width // 2,
                            center_y + node_radius + max(3, timeline_card_height // 14),
                        ),
                        "size": limb_size,
                        "color": limb_color if is_completed else (128, 137, 141),
                    })
                    supplementary_name = str(action.get("supplementary_name") or "")
                    if supplementary_name:
                        supplementary_size = max(7, min(10, timeline_card_height // 6))
                        supplementary_width = len(supplementary_name) * supplementary_size
                        cjk_labels.append({
                            "text": supplementary_name, "fallback": "",
                            "origin": (
                                center_x - supplementary_width // 2,
                                center_y + node_radius
                                + max(3, timeline_card_height // 14)
                                + limb_size + 2,
                            ),
                            "size": supplementary_size,
                            "color": (190, 197, 200) if is_completed else (105, 113, 117),
                        })
            else:
                cjk_labels.append({
                    "text": "暂无确认的手脚接触",
                    "fallback": "",
                    "origin": (
                        timeline_padding,
                        min(output_height - 14, timeline_y + timeline_title_height + 2),
                    ),
                    "size": max(9, round(base_text_scale * 20)),
                    "color": (153, 162, 166),
                })
            draw_cjk_labels(canvas, cjk_labels)
            writer.write(canvas)
            frame_index += 1
            if progress and (frame_index == total or frame_index % max(1, total // 20) == 0):
                progress(min(100, round(frame_index * 100 / total)))
    except BaseException:
        cap.release()
        writer.release()
        temporary.unlink(missing_ok=True)
        raise
    cap.release()
    writer.release()
    if (frame_index != total or not temporary.is_file()
            or temporary.stat().st_size <= 0):
        temporary.unlink(missing_ok=True)
        raise RuntimeError("叠加视频未完整生成，请保留原视频后重试")
    os.replace(temporary, target)
    return {
        "schema_version": 3,
        "container": "webm",
        "codec": "vp8",
        "frames_written": frame_index,
        "fps": round(fps, 6),
        "width": output_width,
        "height": output_height,
        "pose_rendering": "local_linear_between_measured_samples",
        "pose_evidence": "cloud_samples_with_local_visual_smoothing",
        "pose_rendered_frames": len(pose_timeline),
        "layout": "split_route_map_actions_v7",
        "hold_map": "route_bounds_zoom_with_touch_markers",
        "touch_markers": "persistent_sequence_per_contact",
        "action_labels": "sequence_limb_and_chinese_supplement_v1",
        "hold_count": len(holds),
        "action_count": len(actions),
        "audio_included": False,
    }


class ReplayAnalyzer(Protocol):
    def analysis_contract(self, video_info: VideoInfo) -> dict: ...

    def analyze(
        self,
        video: Path,
        *,
        route_color: str,
        video_info: VideoInfo,
        progress: Callable[[str, int], None],
        cancelled: Callable[[], bool],
        telemetry: Callable[[dict], None],
    ) -> dict: ...


class ClimbReplayStore:
    """File-backed, owner-scoped jobs kept outside the photo-route database."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.jobs = self.root / "jobs"
        self.deletions = self.root / "deletions"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.deletions.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.recover_interrupted()

    def _path(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise HTTPException(404, "未找到复盘任务")
        return self.jobs / job_id / "job.json"

    def _deletion_path(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise HTTPException(404, "未找到删除任务")
        return self.deletions / f"{job_id}.json"

    def _read(self, job_id: str) -> dict:
        path = self._path(job_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, "未找到复盘任务")

    @staticmethod
    def _public(job: dict) -> dict:
        return {key: value for key, value in job.items() if key != "input_path"}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def create(
        self,
        *,
        owner: str,
        route_id: str | None,
        route_color: str,
        source: Path,
        original_name: str,
        info: VideoInfo,
        consent: dict,
        retention_mode: ReplayRetentionMode,
    ) -> dict:
        job_id, now = uuid.uuid4().hex, utcnow()
        directory = self.jobs / job_id
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / "input.mp4"
        os.replace(source, target)
        checksum = self._sha256(target)
        job = {
            "id": job_id,
            "owner": owner,
            "route_id": route_id,
            "route_color": route_color,
            "original_name": original_name,
            "input_path": str(target),
            "media": {
                "source_video": {
                    "kind": "source_video", "status": "available",
                    "retention_mode": retention_mode, "delete_at": None,
                    "deleted_at": None, "size_bytes": info.size_bytes,
                    "checksum_sha256": checksum,
                    "content_type": "video/mp4", "filename": original_name,
                },
            },
            "deletion": None,
            "video": asdict(info),
            "status": "queued",
            "stage": "等待分析",
            "progress": 0,
            "error": None,
            "error_code": None,
            "cancel_requested": False,
            "attempt": 1,
            "consent_history": [consent],
            "analysis_runs": [],
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        _atomic_json(self._path(job_id), job)
        return self._public(job)

    def get(self, job_id: str, owner: str | None = None, *, private=False) -> dict:
        with self._lock:
            job = self._read(job_id)
        if owner is not None and job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        return job if private else self._public(job)

    def list(self, owner: str) -> list[dict]:
        found = []
        for path in self.jobs.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if job.get("owner") == owner:
                found.append(self._public(job))
        return sorted(found, key=lambda item: item["created_at"], reverse=True)

    def update(self, job_id: str, **changes) -> dict:
        with self._lock:
            job = self._read(job_id)
            job.update(changes)
            job["updated_at"] = utcnow()
            _atomic_json(self._path(job_id), job)
        return job

    def _media_path(self, job_id: str, job: dict, media_kind: str) -> Path:
        directory = self._path(job_id).parent.resolve()
        if media_kind == "source_video":
            raw_path = job.get("input_path")
            if not raw_path:
                raise HTTPException(404, "原视频已删除")
            path = Path(raw_path).resolve()
            expected_name = "input.mp4"
        elif media_kind == REPLAY_OVERLAY_MEDIA_KIND:
            path = (directory / REPLAY_OVERLAY_FILENAME).resolve()
            expected_name = REPLAY_OVERLAY_FILENAME
        else:
            raise HTTPException(404, "未找到可访问的媒体")
        if (directory.parent != self.jobs.resolve() or path.parent != directory
                or path.name != expected_name):
            raise RuntimeError("媒体路径未通过安全校验")
        return path

    def register_overlay(self, job_id: str) -> dict:
        job = self.get(job_id, private=True)
        path = self._media_path(job_id, job, REPLAY_OVERLAY_MEDIA_KIND)
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError("叠加视频文件不存在")
        media = dict(job.get("media") or {})
        media[REPLAY_OVERLAY_MEDIA_KIND] = {
            "kind": REPLAY_OVERLAY_MEDIA_KIND,
            "status": "available",
            "retention_mode": REPLAY_RETENTION_KEEP,
            "delete_at": None,
            "deleted_at": None,
            "size_bytes": path.stat().st_size,
            "checksum_sha256": self._sha256(path),
            "content_type": "video/webm",
            "filename": f"{Path(job.get('original_name') or 'climb-replay').stem}-复盘叠加.webm",
            "generated_at": utcnow(),
        }
        return self._public(self.update(job_id, media=media))

    def discard_overlay(self, job_id: str) -> dict:
        """Remove a partial or uncommitted overlay after cancellation/failure."""
        job = self.get(job_id, private=True)
        path = self._media_path(job_id, job, REPLAY_OVERLAY_MEDIA_KIND)
        media = dict(job.get("media") or {})
        item = dict(media.get(REPLAY_OVERLAY_MEDIA_KIND) or {})
        last_error: OSError | None = None
        for retry_delay in (0.0, 0.05, 0.15):
            if retry_delay:
                time.sleep(retry_delay)
            try:
                path.unlink(missing_ok=True)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
        if item or last_error is not None:
            item.update(
                kind=REPLAY_OVERLAY_MEDIA_KIND,
                status="cleanup_pending" if last_error is not None else "discarded",
                deleted_at=None if last_error is not None else utcnow(),
                delete_at=utcnow() if last_error is not None else None,
            )
            media[REPLAY_OVERLAY_MEDIA_KIND] = item
            return self._public(self.update(job_id, media=media))
        return self._public(job)

    def media_file(self, job_id: str, owner: str, media_kind: str) -> tuple[Path, dict]:
        job = self.get(job_id, owner, private=True)
        item = dict((job.get("media") or {}).get(media_kind) or {})
        if item.get("status") != "available":
            raise HTTPException(404, "媒体已删除或不存在")
        path = self._media_path(job_id, job, media_kind)
        if not path.is_file():
            raise HTTPException(404, "媒体文件不存在")
        return path, item

    def schedule_source_cleanup(self, job_id: str, *, outcome: str) -> dict:
        job = self.get(job_id, private=True)
        media = dict(job.get("media") or {})
        source = dict(media.get("source_video") or {})
        if source.get("status") != "available":
            return self._public(job)
        if source.get("retention_mode") == REPLAY_RETENTION_KEEP:
            source["delete_at"] = None
        else:
            source["delete_at"] = utc_after(24 if outcome == "succeeded" else 72)
        media["source_video"] = source
        return self._public(self.update(job_id, media=media))

    def delete_media(self, job_id: str, owner: str | None, media_kind: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job.get("status") in {"queued", "running"}:
            raise HTTPException(409, "分析进行中，请先取消任务再删除媒体")
        media = dict(job.get("media") or {})
        item = dict(media.get(media_kind) or {})
        if not item or item.get("status") == "deleted":
            raise HTTPException(404, "媒体已删除或不存在")
        path = self._media_path(job_id, job, media_kind)
        path.unlink(missing_ok=True)
        item.update(status="deleted", deleted_at=utcnow(), delete_at=None)
        media[media_kind] = item
        changes = {"media": media}
        if media_kind == "source_video":
            changes["input_path"] = None
        return self._public(self.update(job_id, **changes))

    def cleanup_due_media(self) -> list[str]:
        deleted = []
        now = datetime.now(timezone.utc)
        for path in self.jobs.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                source = (job.get("media") or {}).get("source_video") or {}
                due = source.get("delete_at")
                if source.get("status") == "available" and due:
                    when = datetime.fromisoformat(due)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    if when <= now:
                        self.delete_media(job["id"], None, "source_video")
                        deleted.append(job["id"])
                overlay = (job.get("media") or {}).get(REPLAY_OVERLAY_MEDIA_KIND) or {}
                if overlay.get("status") == "cleanup_pending":
                    self.discard_overlay(job["id"])
            except (OSError, TypeError, ValueError, json.JSONDecodeError, HTTPException):
                continue
        return deleted

    def request_delete(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        receipt_path = self._deletion_path(job_id)
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise HTTPException(409, "删除回执损坏，请联系管理员")
            if receipt.get("owner") != owner:
                raise HTTPException(404, "未找到删除任务")
            if receipt.get("state") == "failed":
                receipt.update(
                    state="queued", requested_at=utcnow(), completed_at=None, error=None,
                )
                _atomic_json(receipt_path, receipt)
                deletion = {key: value for key, value in receipt.items() if key != "owner"}
                self.update(
                    job_id, deletion=deletion, cancel_requested=True,
                    stage="正在重新删除整次记录",
                )
                return deletion
            return {key: value for key, value in receipt.items() if key != "owner"}
        now = utcnow()
        receipt = {
            "job_id": job_id, "owner": owner, "state": "queued",
            "requested_at": now, "completed_at": None, "error": None,
        }
        _atomic_json(receipt_path, receipt)
        deletion = {key: value for key, value in receipt.items() if key != "owner"}
        changes = {
            "deletion": deletion, "cancel_requested": True,
            "stage": "正在停止任务并删除整次记录",
        }
        if job.get("status") == "queued":
            changes.update(status="cancelled", error_code="delete_requested", finished_at=now)
        self.update(job_id, **changes)
        return deletion

    def get_deletion(self, job_id: str, owner: str) -> dict:
        try:
            receipt = json.loads(self._deletion_path(job_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, "未找到删除任务")
        if receipt.get("owner") != owner:
            raise HTTPException(404, "未找到删除任务")
        return {key: value for key, value in receipt.items() if key != "owner"}

    def pending_deletions(self) -> list[str]:
        pending = []
        for path in self.deletions.glob("*.json"):
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if receipt.get("state") == "queued" and receipt.get("job_id"):
                pending.append(receipt["job_id"])
        return pending

    def process_delete(self, job_id: str) -> dict:
        receipt_path = self._deletion_path(job_id)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, "未找到删除任务")
        if receipt.get("state") == "completed":
            return {key: value for key, value in receipt.items() if key != "owner"}
        directory = self._path(job_id).parent.resolve()
        jobs_root = self.jobs.resolve()
        if directory.parent != jobs_root or directory.name != job_id:
            raise RuntimeError("删除范围未通过安全校验")
        last_error: OSError | None = None
        for retry_delay in (0.0, 0.05, 0.15):
            if retry_delay:
                time.sleep(retry_delay)
            try:
                if directory.exists():
                    shutil.rmtree(directory)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
        if last_error is None:
            receipt.update(state="completed", completed_at=utcnow(), error=None)
        else:
            receipt.update(state="failed", error="删除未完成，请稍后重试")
        _atomic_json(receipt_path, receipt)
        return {key: value for key, value in receipt.items() if key != "owner"}

    def fail_deletion(self, job_id: str) -> None:
        """Leave a retryable, path-free receipt if the delete worker fails unexpectedly."""
        receipt_path = self._deletion_path(job_id)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, HTTPException):
            return
        if receipt.get("state") != "completed":
            receipt.update(state="failed", error="删除未完成，请稍后重试")
            _atomic_json(receipt_path, receipt)

    def queued(self) -> list[str]:
        jobs = []
        for path in self.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") == "queued":
                jobs.append(item)
        return [item["id"] for item in sorted(jobs, key=lambda item: item["created_at"])]

    def recover_interrupted(self) -> None:
        for path in self.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") == "running":
                attempt = int(item.get("attempt") or 1)
                runs = list(item.get("analysis_runs") or [])
                for run in reversed(runs):
                    if int(run.get("attempt") or 0) == attempt and run.get("state") == "running":
                        run.update(
                            state="failed", error_code="service_restarted", finished_at=utcnow(),
                        )
                        break
                media = dict(item.get("media") or {})
                source = dict(media.get("source_video") or {})
                if (source.get("status") == "available"
                        and source.get("retention_mode") != REPLAY_RETENTION_KEEP):
                    source["delete_at"] = utc_after(72)
                    media["source_video"] = source
                item.update(
                    status="failed",
                    stage="服务重启后已停止",
                    error="服务在视频分析期间重启，请重试",
                    error_code="service_restarted",
                    analysis_runs=runs,
                    media=media,
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                _atomic_json(path, item)

    def cancel(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return self._public(job)
        changes = {"cancel_requested": True, "stage": "正在取消"}
        if job["status"] == "queued":
            changes.update(status="cancelled", progress=job["progress"],
                           error_code="cancelled_by_user", finished_at=utcnow())
        result = self._public(self.update(job_id, **changes))
        if job["status"] == "queued":
            result = self.schedule_source_cleanup(job_id, outcome="failed")
        return result

    def retry(self, job_id: str, owner: str, consent: dict) -> dict:
        job = self.get(job_id, owner, private=True)
        if job["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "只有失败或已取消的任务可以重试")
        if (job.get("deletion") or {}).get("state") == "queued":
            raise HTTPException(409, "整次记录正在删除，不能重新分析")
        media = dict(job.get("media") or {})
        source = dict(media.get("source_video") or {})
        try:
            source_path = self._media_path(job_id, job, "source_video")
        except HTTPException as exc:
            raise HTTPException(409, "原视频已删除，不能重新分析") from exc
        if source.get("status") != "available" or not source_path.is_file():
            raise HTTPException(409, "原视频已删除，不能重新分析")
        source["delete_at"] = None
        media["source_video"] = source
        overlay = dict(media.get(REPLAY_OVERLAY_MEDIA_KIND) or {})
        if overlay.get("status") == "available":
            overlay_path = self._media_path(job_id, job, REPLAY_OVERLAY_MEDIA_KIND)
            overlay_path.unlink(missing_ok=True)
            overlay.update(status="superseded", deleted_at=utcnow(), delete_at=None)
            media[REPLAY_OVERLAY_MEDIA_KIND] = overlay
        history = list(job.get("consent_history") or [])
        history.append(consent)
        return self._public(self.update(
            job_id,
            status="queued",
            stage="等待重试",
            progress=0,
            error=None,
            cancel_requested=False,
            result=None,
            attempt=int(job.get("attempt") or 1) + 1,
            consent_history=history,
            media=media,
            error_code=None,
            started_at=None,
            finished_at=None,
        ))

    def start_analysis_run(self, job_id: str, attempt: int, analysis: dict) -> dict:
        with self._lock:
            job = self._read(job_id)
            runs = list(job.get("analysis_runs") or [])
            run = {
                "attempt": attempt, "state": "running", "started_at": utcnow(),
                "finished_at": None, "error_code": None, "analysis": analysis,
            }
            runs.append(run)
            job["analysis_runs"] = runs
            job["updated_at"] = utcnow()
            _atomic_json(self._path(job_id), job)
        return run

    def update_analysis_run(self, job_id: str, attempt: int, analysis: dict) -> dict:
        with self._lock:
            job = self._read(job_id)
            runs = list(job.get("analysis_runs") or [])
            for run in reversed(runs):
                if int(run.get("attempt") or 0) == attempt:
                    run["analysis"] = analysis
                    break
            else:
                raise RuntimeError("当前分析批次不存在")
            job["analysis_runs"] = runs
            job["updated_at"] = utcnow()
            _atomic_json(self._path(job_id), job)
        return run

    def finish_analysis_run(self, job_id: str, attempt: int, *, state: str,
                            error_code: str | None = None) -> dict:
        with self._lock:
            job = self._read(job_id)
            runs = list(job.get("analysis_runs") or [])
            for run in reversed(runs):
                if int(run.get("attempt") or 0) == attempt:
                    run.update(state=state, error_code=error_code, finished_at=utcnow())
                    break
            else:
                raise RuntimeError("当前分析批次不存在")
            job["analysis_runs"] = runs
            job["updated_at"] = utcnow()
            _atomic_json(self._path(job_id), job)
        return run

    def withdraw_consent(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        attempt = int(job.get("attempt") or 1)
        history = list(job.get("consent_history") or [])
        latest = next((event for event in reversed(history)
                       if int(event.get("attempt") or 0) == attempt), None)
        if not latest or latest.get("event") != "granted":
            return self._public(job)
        if job["status"] == "queued":
            outcome = "任务已取消，未开始发送抽样画面"
            changes = {"status": "cancelled", "stage": "授权已撤回", "progress": job["progress"],
                       "cancel_requested": True, "finished_at": utcnow()}
        elif job["status"] == "running":
            outcome = "已请求停止，下一帧起不再发送抽样画面"
            changes = {"cancel_requested": True, "stage": "正在停止第三方处理"}
        else:
            outcome = "本次处理已结束，已记录撤回且不会据此再次调用"
            changes = {}
        history.append({
            "event": "withdrawn", "attempt": attempt,
            "version": latest.get("version"), "withdrawn_at": utcnow(),
            "outcome": outcome,
        })
        changes["consent_history"] = history
        return self._public(self.update(job_id, **changes))


def active_consent(job: dict) -> bool:
    """Return whether the current analysis attempt has an unwithdrawn grant."""
    attempt = int(job.get("attempt") or 1)
    latest = next((event for event in reversed(job.get("consent_history") or [])
                   if int(event.get("attempt") or 0) == attempt), None)
    return bool(latest and latest.get("event") == "granted"
                and latest.get("version") == REPLAY_CONSENT_VERSION)


class ClimbReplayManager:
    """One-at-a-time worker so video analysis cannot overlap itself."""

    def __init__(self, store: ClimbReplayStore, analyzer: ReplayAnalyzer,
                 *, cleanup_interval_seconds: float = 300):
        self.store, self.analyzer = store, analyzer
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._queued: set[tuple[str, str]] = set()
        self._stop = threading.Event()
        self._cleanup_interval_seconds = max(1.0, cleanup_interval_seconds)
        self.store.cleanup_due_media()
        self._thread = threading.Thread(target=self._run, name="climb-replay-worker", daemon=True)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, name="climb-replay-cleanup", daemon=True,
        )
        self._thread.start()
        self._cleanup_thread.start()
        for job_id in store.pending_deletions():
            self.enqueue_delete(job_id)
        for job_id in store.queued():
            self.enqueue(job_id)

    def enqueue(self, job_id: str) -> None:
        self._enqueue("analysis", job_id)

    def enqueue_delete(self, job_id: str) -> None:
        self._enqueue("delete", job_id)

    def _enqueue(self, action: str, job_id: str) -> None:
        item = (action, job_id)
        if item not in self._queued:
            self._queued.add(item)
            self._queue.put(item)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            self._queued.discard(item)
            action, job_id = item
            try:
                if action == "delete":
                    self.store.process_delete(job_id)
                else:
                    self._execute(job_id)
            except Exception:
                if action == "delete":
                    self.store.fail_deletion(job_id)
                else:
                    try:
                        job = self.store.get(job_id, private=True)
                        if job.get("status") in {"queued", "running"}:
                            self.store.schedule_source_cleanup(job_id, outcome="failed")
                            self.store.update(
                                job_id, status="failed", stage="分析失败", progress=0,
                                error="分析任务意外停止，请稍后重试",
                                error_code="worker_failed", finished_at=utcnow(),
                            )
                    except Exception:
                        pass
            finally:
                self._queue.task_done()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self._cleanup_interval_seconds):
            try:
                self.store.cleanup_due_media()
            except Exception:
                # One malformed legacy record must not stop future cleanup passes.
                continue

    def _execute(self, job_id: str) -> None:
        job = self.store.get(job_id, private=True)
        if job["status"] != "queued" or job.get("cancel_requested"):
            return
        if not active_consent(job):
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(
                job_id, status="failed", stage="缺少有效授权", progress=0,
                error="本次任务没有有效的抽样画面第三方处理授权，请重新确认后重试",
                finished_at=utcnow(),
            )
            return
        self.store.update(job_id, status="running", stage="检查视频", progress=5,
                          started_at=utcnow(), error=None, error_code=None)
        info = VideoInfo(**job["video"])
        attempt = int(job.get("attempt") or 1)
        initial_analysis = self.analyzer.analysis_contract(info)
        self.store.start_analysis_run(job_id, attempt, initial_analysis)

        def is_cancelled() -> bool:
            return bool(self.store.get(job_id, private=True).get("cancel_requested"))

        def progress(stage: str, value: int) -> None:
            if is_cancelled():
                raise ReplayCancelled()
            self.store.update(job_id, status="running", stage=stage,
                              progress=max(5, min(95, int(value))))

        def telemetry(analysis: dict) -> None:
            self.store.update_analysis_run(job_id, attempt, analysis)

        try:
            result = self.analyzer.analyze(
                Path(job["input_path"]), route_color=job["route_color"], video_info=info,
                progress=progress, cancelled=is_cancelled, telemetry=telemetry,
            )
            if is_cancelled():
                raise ReplayCancelled()
            overlay_path = Path(job["input_path"]).with_name(REPLAY_OVERLAY_FILENAME)
            if overlay_path.is_file():
                self.store.register_overlay(job_id)
            self.store.finish_analysis_run(job_id, attempt, state="succeeded")
            self.store.schedule_source_cleanup(job_id, outcome="succeeded")
            self.store.update(job_id, status="succeeded", stage="分析完成", progress=100,
                              result=result, error_code=None, finished_at=utcnow())
        except ReplayCancelled:
            self.store.discard_overlay(job_id)
            self.store.finish_analysis_run(
                job_id, attempt, state="cancelled", error_code="cancelled_by_user",
            )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="cancelled", stage="已取消",
                              error=None, error_code="cancelled_by_user", finished_at=utcnow())
        except ReplayConfigurationError as exc:
            self.store.discard_overlay(job_id)
            self.store.finish_analysis_run(
                job_id, attempt, state="failed", error_code="pose_provider_unconfigured",
            )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(
                job_id, status="failed", stage="姿态服务未配置", progress=0,
                error=str(exc)[:1000], error_code="pose_provider_unconfigured",
                finished_at=utcnow(),
            )
        except Exception as exc:  # the public job exposes a concise actionable error
            self.store.discard_overlay(job_id)
            self.store.finish_analysis_run(
                job_id, attempt, state="failed", error_code="analysis_failed",
            )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="failed", stage="分析失败", progress=0,
                              error=str(exc)[:1000], error_code="analysis_failed",
                              finished_at=utcnow())

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=2)
        self._cleanup_thread.join(timeout=2)


COLOR_PROMPTS = {
    "红色": "red", "红": "red", "蓝色": "blue", "蓝": "blue",
    "绿色": "green", "绿": "green", "黄色": "yellow", "黄": "yellow",
    "橙色": "orange", "橙": "orange", "紫色": "purple", "紫": "purple",
    "粉色": "pink", "粉": "pink", "白色": "white", "白": "white",
    "黑色": "black", "黑": "black", "灰色": "gray", "灰": "gray",
}


class AliyunReplayAnalyzer:
    """Local hold detection plus Alibaba Cloud body-keypoint estimation."""

    hold_model = "local-climbing-mask-rcnn"
    pose_model = "aliyun-viapi-bodyposture-2019-12-30"
    _coco_parts = {
        0: "nose", 1: "left_eye", 2: "right_eye", 3: "left_ear", 4: "right_ear",
        5: "left_shoulder", 6: "right_shoulder", 7: "left_elbow", 8: "right_elbow",
        9: "left_wrist", 10: "right_wrist", 11: "left_hip", 12: "right_hip",
        13: "left_knee", 14: "right_knee", 15: "left_ankle", 16: "right_ankle",
    }

    def __init__(self, access_key_id: str | None = None, access_key_secret: str | None = None,
                 *, pose_fps: float | None = None, client: Any | None = None):
        self.access_key_id = (access_key_id if access_key_id is not None
                              else os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID"))
        self.access_key_secret = (access_key_secret if access_key_secret is not None
                                  else os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET"))
        self.region_id = os.getenv("ALIBABA_CLOUD_REGION_ID", "cn-shanghai")
        self.endpoint = os.getenv("ALIYUN_VIAPI_ENDPOINT", "facebody.cn-shanghai.aliyuncs.com")
        configured_fps = pose_fps if pose_fps is not None else os.getenv("CLIMB_REPLAY_POSE_FPS", "4")
        try:
            self.pose_fps = max(1.0, min(10.0, float(configured_fps)))
        except (TypeError, ValueError):
            self.pose_fps = 4.0
        try:
            self.pose_qps = max(1.0, min(5.0, float(os.getenv("CLIMB_REPLAY_POSE_QPS", "4"))))
        except (TypeError, ValueError):
            self.pose_qps = 4.0
        try:
            self.pose_unit_price_cny = max(
                0.0, float(os.getenv("CLIMB_REPLAY_POSE_UNIT_PRICE_CNY", str(DEFAULT_POSE_UNIT_PRICE_CNY))),
            )
        except (TypeError, ValueError):
            self.pose_unit_price_cny = DEFAULT_POSE_UNIT_PRICE_CNY
        self._sdk_client = client
        self._client_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _sampling_positions(self, video_info: VideoInfo) -> tuple[float, np.ndarray]:
        sample_fps = min(self.pose_fps, video_info.fps)
        positions = np.unique(np.clip(
            np.rint(np.arange(0, video_info.duration_seconds, 1 / sample_fps) * video_info.fps).astype(int),
            0, video_info.frame_count - 1,
        ))
        return sample_fps, positions

    def analysis_contract(self, video_info: VideoInfo) -> dict:
        sample_fps, positions = self._sampling_positions(video_info)
        return {
            "contract_version": 1,
            "pipeline_version": REPLAY_PIPELINE_VERSION,
            "provider": {
                "name": "aliyun-viapi", "service": REPLAY_CONSENT_SERVICE,
                "region": self.region_id, "api_version": REPLAY_POSE_API_VERSION,
            },
            "models": {
                "holds": {"name": self.hold_model, "version": "pending"},
                "pose": {"name": self.pose_model, "version": REPLAY_POSE_API_VERSION},
            },
            "algorithms": {
                "hold_color": CANDIDATE_COLOR_VERSION,
                "contact": "mask-contour-dwell-0.4s-v2",
            },
            "sampling": {
                "source_fps": round(video_info.fps, 6),
                "requested_fps": round(self.pose_fps, 6),
                "effective_fps": round(sample_fps, 6),
                "planned_frames": len(positions),
                "qps_limit": round(self.pose_qps, 6),
                "jpeg_max_edge": 1280, "jpeg_quality": 82,
                "max_frame_bytes": 3 * 1024 * 1024,
            },
            "usage": {
                "planned_requests": len(positions), "actual_requests": 0,
                "successful_requests": 0, "failed_requests": 0,
                "successful_pose_frames": 0, "responses_without_pose": 0,
                "decode_failed_frames": 0, "unprocessed_frames": len(positions),
                "request_image_bytes": 0,
            },
            "cost": {
                "currency": "CNY", "unit_price": self.pose_unit_price_cny,
                "billable_requests_estimate": 0, "estimated_amount": 0.0,
                "basis": "按成功返回的应用层请求和配置单价估算，实际费用以阿里云账单为准",
            },
            "timings_ms": {
                "total": 0, "background": 0, "hold_inference": 0,
                "pose": 0, "contact": 0, "overlay": 0, "report": 0,
            },
        }

    def _client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        if not self.access_key_id or not self.access_key_secret:
            raise ReplayConfigurationError(
                "尚未配置阿里云 AccessKey ID 和 AccessKey Secret，视频画面未发送到云端"
            )
        with self._client_lock:
            if self._sdk_client is not None:
                return self._sdk_client
            try:
                from alibabacloud_facebody20191230.client import Client
                from alibabacloud_tea_openapi import models as open_api_models
            except ImportError as exc:
                raise ReplayConfigurationError(
                    "阿里云人体姿态 SDK 未安装，请先安装后端依赖"
                ) from exc
            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
                region_id=self.region_id,
            )
            config.endpoint = self.endpoint
            try:
                self._sdk_client = Client(config)
            except Exception as exc:
                raise ReplayConfigurationError(
                    "阿里云人体姿态服务初始化失败，请检查密钥和地域配置"
                ) from exc
            return self._sdk_client

    def _request_pose(self, jpeg: bytes) -> dict:
        client = self._client()
        try:
            from alibabacloud_facebody20191230 import models as facebody_models
            from alibabacloud_tea_util import models as util_models
            request = facebody_models.BodyPostureAdvanceRequest(
                image_urlobject=io.BytesIO(jpeg),
            )
            with self._request_lock:
                delay = (1.0 / self.pose_qps) - (time.monotonic() - self._last_request_at)
                if delay > 0:
                    time.sleep(delay)
                response = client.body_posture_advance(
                    request, util_models.RuntimeOptions(),
                )
                self._last_request_at = time.monotonic()
            body = getattr(response, "body", response)
            payload = body.to_map() if hasattr(body, "to_map") else body
            if not isinstance(payload, dict):
                raise ValueError("unexpected response body")
            return payload
        except ReplayConfigurationError:
            raise
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc)
            concise = message[:240] if message else "请稍后重试"
            raise RuntimeError(
                f"阿里云人体姿态识别请求失败：{concise}"
            ) from exc

    @staticmethod
    def _as_list(value: Any) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    @classmethod
    def _pose_candidates(cls, payload: dict) -> list[dict]:
        data = payload.get("Data") or payload.get("data") or {}
        candidates = []
        for output in cls._as_list(data.get("Outputs") or data.get("outputs")):
            if not isinstance(output, dict):
                continue
            for result in cls._as_list(output.get("Results") or output.get("results")):
                if not isinstance(result, dict):
                    continue
                parts = {}
                for body in cls._as_list(result.get("Bodies") or result.get("bodies")):
                    if not isinstance(body, dict):
                        continue
                    label = str(body.get("Label") or body.get("label") or "").lower()
                    positions = cls._as_list(body.get("Positions") or body.get("positions"))
                    raw_points = None
                    for position in positions:
                        if isinstance(position, dict):
                            raw_points = position.get("Points") or position.get("points")
                            if raw_points is not None:
                                break
                    if not isinstance(raw_points, (list, tuple)) or len(raw_points) < 2:
                        continue
                    try:
                        x, y = float(raw_points[0]), float(raw_points[1])
                        confidence = float(body.get("Confident") or body.get("confident") or 0)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(x) and math.isfinite(y) and math.isfinite(confidence):
                        parts[label] = ([min(1.0, max(0.0, x)), min(1.0, max(0.0, y))],
                                        min(1.0, max(0.0, confidence)))
                valid = [point for point, score in parts.values() if score > .2]
                if len(valid) < 4:
                    continue
                xs, ys = [point[0] for point in valid], [point[1] for point in valid]
                bbox = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
                candidates.append({
                    "parts": parts,
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    "confidence": float(np.mean([score for _, score in parts.values()])),
                })
        return candidates

    @staticmethod
    def _sample_frames(video: Path, count: int = 8) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(video))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        indices = np.linspace(total * 0.05, total * 0.95, num=min(count, total)).astype(int)
        frames = []
        try:
            for index in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
                ok, frame = cap.read()
                if ok:
                    frames.append(frame)
        finally:
            cap.release()
        return frames

    @staticmethod
    def _jpeg(frame: np.ndarray) -> tuple[bytes, int, int]:
        height, width = frame.shape[:2]
        ratio = min(1.0, 1280 / max(height, width))
        if ratio < 1:
            frame = cv2.resize(frame, (round(width * ratio), round(height * ratio)),
                               interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            raise RuntimeError("无法编码视频抽样帧")
        encoded_height, encoded_width = frame.shape[:2]
        return buf.tobytes(), encoded_width, encoded_height

    @staticmethod
    def _route_colour(value: str) -> str:
        aliases = {english: chinese for chinese, english in COLOR_PROMPTS.items() if len(chinese) > 1}
        return aliases.get(value.strip().lower(), value.strip())

    @classmethod
    @serialized_inference
    def _local_holds(cls, *, background: np.ndarray, route_color: str, deadline: float,
                     progress: Callable[[str, int], None], cancelled: Callable[[], bool]) -> tuple[list[dict], str]:
        masks, scores, model_version = _climbing_model_masks(
            background, deadline, cancelled,
            lambda stage, value: progress(stage, 16 + round(max(0, value - 20) * .42)),
        )
        height, width = background.shape[:2]
        target = cls._route_colour(route_color)
        lab = cv2.cvtColor(background, cv2.COLOR_BGR2LAB)
        holds = []
        for mask, score in zip(masks, scores):
            if cancelled():
                raise ReplayCancelled()
            colour = classify_mask_color(background, mask, version=CANDIDATE_COLOR_VERSION)
            if colour == "待确认":
                pixels = lab[mask > 0]
                if len(pixels):
                    colour = _colour_name(np.median(pixels, axis=0).astype(np.uint8))
            if colour != target:
                continue
            polygon = native_mask_polygon(mask)
            if len(polygon) < 3:
                continue
            x, y, box_width, box_height = cv2.boundingRect(polygon)
            holds.append({
                "bbox": [round(x / width, 6), round(y / height, 6),
                         round(box_width / width, 6), round(box_height / height, 6)],
                "polygon": [
                    [round(float(point[0][0]) / width, 6),
                     round(float(point[0][1]) / height, 6)]
                    for point in polygon
                ],
                "score": round(float(score), 4), "appearances": 1,
                "contour_source": "climbing_model_native_mask",
                "contour_points": len(polygon),
            })
        holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2),
                                     hold["bbox"][0] + hold["bbox"][2] / 2))
        for index, hold in enumerate(holds, start=1):
            hold["id"] = index
        return holds, f"{model_version}+native-mask-contour-v1"

    def _pose_frame(self, frame: np.ndarray, *, frame_id: int, source_frame_id: int,
                    before_request: Callable[[int], None] | None = None) -> dict | None:
        jpeg, _, _ = self._jpeg(frame)
        if len(jpeg) > 3 * 1024 * 1024:
            raise RuntimeError("视频抽样帧超过阿里云 3 MB 限制，请降低视频分辨率")
        if before_request is not None:
            before_request(len(jpeg))
        candidates = self._pose_candidates(self._request_pose(jpeg))
        if not candidates:
            return None
        person = max(candidates, key=lambda item: (item["area"], item["confidence"]))
        parts = person["parts"]
        points, scores = [], []
        for index in range(17):
            point, score = parts.get(self._coco_parts[index], ([0.0, 0.0], 0.0))
            points.append([round(point[0], 6), round(point[1], 6)] if score > 0 else [0.0, 0.0])
            scores.append(round(score, 6))
        return {
            "frame_id": frame_id, "source_frame_id": source_frame_id, "track_id": 0,
            "kpts_xy": points, "kpts_score": scores,
            "bbox_xywh": [round(float(value), 6) for value in person["bbox"]],
        }

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax, ay, aw, ah = a; bx, by, bw, bh = b
        x0, y0 = max(ax, bx), max(ay, by)
        x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        union = aw * ah + bw * bh - overlap
        return overlap / union if union > 1e-9 else 0.0

    @classmethod
    def _consensus_holds(cls, detections: list[list[dict]]) -> list[dict]:
        clusters: list[dict] = []
        for frame_index, items in enumerate(detections):
            for item in items:
                box = [float(value) for value in item["bbox_xywh"]]
                match = None
                best = 0.30
                for cluster in clusters:
                    score = cls._iou(box, np.mean(cluster["boxes"], axis=0).tolist())
                    if score > best:
                        match, best = cluster, score
                if match is None:
                    match = {"boxes": [], "scores": [], "frames": set()}
                    clusters.append(match)
                match["boxes"].append(box)
                match["scores"].append(float(item.get("score") or 0))
                match["frames"].add(frame_index)
        minimum = max(1, math.ceil(max(1, len(detections)) * 0.25))
        holds = []
        for cluster in clusters:
            if len(cluster["frames"]) < minimum:
                continue
            box = np.median(np.asarray(cluster["boxes"], dtype=float), axis=0).tolist()
            holds.append({"bbox": [round(float(v), 6) for v in box],
                          "score": round(float(np.mean(cluster["scores"])), 4),
                          "appearances": len(cluster["frames"])})
        holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2),
                                     hold["bbox"][0] + hold["bbox"][2] / 2))
        for index, hold in enumerate(holds, start=1):
            hold["id"] = index
        return holds

    @staticmethod
    def _choose_track(items: list[dict]) -> tuple[Any, list[dict]]:
        by_track: dict[Any, list[dict]] = defaultdict(list)
        for item in items:
            by_track[item.get("track_id")].append(item)
        if not by_track:
            raise RuntimeError("视频中没有识别到攀爬者")
        track = max(by_track, key=lambda key: (len(by_track[key]),
            np.mean([record.get("bbox_xywh", [0, 0, 0, 0])[2] *
                     record.get("bbox_xywh", [0, 0, 0, 0])[3] for record in by_track[key]])))
        return track, by_track[track]

    @staticmethod
    def _inside(point: tuple[float, float], hold: dict, margin: float) -> bool:
        x, y = point
        polygon = hold.get("polygon") or []
        if isinstance(polygon, list) and len(polygon) >= 3:
            contour = np.asarray(polygon, dtype=np.float32).reshape((-1, 1, 2))
            return cv2.pointPolygonTest(contour, (float(x), float(y)), True) >= -margin
        bx, by, bw, bh = hold["bbox"]
        return bx - margin <= x <= bx + bw + margin and by - margin <= y <= by + bh + margin

    @classmethod
    def _contacts(cls, records: list[dict], holds: list[dict], fps: float) -> dict:
        limbs = {"left_hand": 9, "right_hand": 10, "left_foot": 15, "right_foot": 16}
        dwell = max(1, round(0.4 * fps))
        records = sorted(records, key=lambda item: int(item.get("frame_id", -1)))
        current = {key: None for key in limbs}
        since = {key: 0 for key in limbs}
        run = {key: 0 for key in limbs}
        confirmed = {key: False for key in limbs}
        contacts: list[dict] = []
        holding: dict[int, dict[str, int]] = {}
        midline = []

        def close(key: str, frame: int) -> None:
            if current[key] is not None and confirmed[key]:
                contacts.append({"limb": key, "hold_id": current[key], "start_frame": since[key],
                                 "end_frame": max(since[key], frame - 1)})
            current[key], run[key], confirmed[key] = None, 0, False

        for item in records:
            frame = int(item.get("frame_id", -1))
            points = item.get("kpts_xy") or []
            scores = item.get("kpts_score") or []
            torso = [points[i] for i in (5, 6, 11, 12) if i < len(points) and points[i] != [0, 0]]
            if torso:
                midline.append({"frame": frame, "x": round(float(np.mean([p[0] for p in torso])), 5),
                                "y": round(float(np.mean([p[1] for p in torso])), 5)})
            active = {}
            for key, index in limbs.items():
                if index >= len(points) or points[index] == [0, 0] or (
                    index < len(scores) and scores[index] is not None and float(scores[index]) < 0.15
                ):
                    close(key, frame); continue
                x, y = map(float, points[index])
                if "foot" in key:
                    y += 0.02
                choices = [hold for hold in holds if cls._inside((x, y), hold, 0.02)]
                chosen = min(choices, key=lambda hold: abs(x - hold["bbox"][0] - hold["bbox"][2] / 2)
                             + abs(y - hold["bbox"][1] - hold["bbox"][3] / 2)) if choices else None
                hold_id = chosen["id"] if chosen else None
                if hold_id != current[key]:
                    close(key, frame)
                    current[key], since[key] = hold_id, frame
                if hold_id is not None:
                    run[key] += 1
                    confirmed[key] = confirmed[key] or run[key] >= dwell
                    if confirmed[key]:
                        active[key] = hold_id
            holding[frame] = active
        last_frame = int(records[-1].get("frame_id", 0)) + 1 if records else 0
        for key in limbs:
            close(key, last_frame)

        first_use: dict[int, int] = {}
        for contact in contacts:
            first_use[contact["hold_id"]] = min(first_use.get(contact["hold_id"], 10**9), contact["start_frame"])
        sequence = [hold for hold, _ in sorted(first_use.items(), key=lambda pair: pair[1])]
        start = next((frame for frame, active in sorted(holding.items())
                      if any(k.endswith("hand") for k in active) and any(k.endswith("foot") for k in active)), None)
        top = holds[-1]["id"] if holds else None
        completion = next((frame for frame, active in sorted(holding.items())
                           if active.get("left_hand") == top and active.get("right_hand") == top), None)
        end = completion if completion is not None else (max(holding) if holding else None)
        window_frames = max(1, (end - start + 1)) if start is not None and end is not None else 1
        per_limb = {}
        for key in limbs:
            relevant = [c for c in contacts if c["limb"] == key]
            clip_start = start if start is not None else 0
            clip_end = end if end is not None else max(0, last_frame - 1)
            count = sum(max(0, min(c["end_frame"], clip_end) -
                            max(c["start_frame"], clip_start) + 1) for c in relevant)
            per_limb[key] = {"contact_seconds": round(count / fps, 3),
                             "coverage_of_attempt": round(count / window_frames, 4),
                             "holds": list(dict.fromkeys(c["hold_id"] for c in relevant))}
        return {
            "start_frame": start,
            "completion_frame": completion,
            "topped_out": completion is not None,
            "elapsed_seconds": round((completion - start) / fps, 3)
                if start is not None and completion is not None else None,
            "sequence": sequence,
            "contacts": contacts,
            "per_limb": per_limb,
            "midline": midline,
        }

    def analyze(self, video: Path, *, route_color: str, video_info: VideoInfo,
                progress: Callable[[str, int], None], cancelled: Callable[[], bool],
                telemetry: Callable[[dict], None]) -> dict:
        started = time.perf_counter()
        analysis = self.analysis_contract(video_info)
        usage = analysis["usage"]
        timings = analysis["timings_ms"]
        processed_frames = 0

        def snapshot() -> dict:
            timings["total"] = max(0, round((time.perf_counter() - started) * 1000))
            usage["unprocessed_frames"] = max(0, usage["planned_requests"] - processed_frames)
            analysis["cost"]["billable_requests_estimate"] = usage["successful_requests"]
            analysis["cost"]["estimated_amount"] = round(
                usage["successful_requests"] * analysis["cost"]["unit_price"], 6,
            )
            return json.loads(json.dumps(analysis, ensure_ascii=False))

        def publish() -> None:
            telemetry(snapshot())

        def empty_pose(sample_index: int, source_index: int) -> dict:
            return {
                "frame_id": sample_index, "source_frame_id": int(source_index),
                "track_id": 0, "kpts_xy": [[0.0, 0.0] for _ in range(17)],
                "kpts_score": [0.0] * 17, "bbox_xywh": [0.0, 0.0, 0.0, 0.0],
            }

        publish()
        try:
            # Fail before local inference so a missing provider configuration
            # cannot spend local CPU or send any image data.
            self._client()

            stage_started = time.perf_counter()
            progress("生成无人物墙面参考", 10)
            background_frames = self._sample_frames(video, count=9)
            if not background_frames:
                timings["background"] = max(0, round((time.perf_counter() - stage_started) * 1000))
                publish()
                raise RuntimeError("没有从视频中读取到有效画面")
            background = np.median(np.stack(background_frames), axis=0).astype(np.uint8)
            timings["background"] = max(0, round((time.perf_counter() - stage_started) * 1000))
            publish()

            stage_started = time.perf_counter()
            progress("使用本地专项模型识别线路岩点", 16)
            holds, hold_version = self._local_holds(
                background=background, route_color=route_color,
                deadline=time.monotonic() + 240, progress=progress, cancelled=cancelled,
            )
            timings["hold_inference"] = max(0, round((time.perf_counter() - stage_started) * 1000))
            analysis["models"]["holds"]["version"] = hold_version
            publish()
            if cancelled():
                raise ReplayCancelled()
            if not holds:
                raise RuntimeError(f"没有稳定识别到“{route_color}”线路岩点，请检查颜色和机位")

            sample_fps, positions = self._sampling_positions(video_info)
            stage_started = time.perf_counter()
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                raise RuntimeError("无法重新读取视频进行姿态识别")
            records = []
            detected_pose_frames = 0
            try:
                progress("抽帧识别攀爬者姿态", 55)
                for sample_index, source_index in enumerate(positions):
                    if cancelled():
                        raise ReplayCancelled()
                    processed_frames = sample_index + 1
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(source_index))
                    ok, frame = cap.read()
                    if not ok:
                        usage["decode_failed_frames"] += 1
                        records.append(empty_pose(sample_index, int(source_index)))
                        publish()
                        continue

                    request_state = {"made": False}

                    def before_request(size_bytes: int) -> None:
                        request_state["made"] = True
                        usage["actual_requests"] += 1
                        usage["request_image_bytes"] += size_bytes

                    try:
                        record = self._pose_frame(
                            frame, frame_id=sample_index, source_frame_id=int(source_index),
                            before_request=before_request,
                        )
                    except Exception:
                        if request_state["made"]:
                            usage["failed_requests"] += 1
                        publish()
                        raise
                    if request_state["made"]:
                        usage["successful_requests"] += 1
                    if record:
                        detected_pose_frames += 1
                        usage["successful_pose_frames"] += 1
                        records.append(record)
                    else:
                        usage["responses_without_pose"] += 1
                        records.append(empty_pose(sample_index, int(source_index)))
                    publish()
                    progress("抽帧识别攀爬者姿态", 55 + round(25 * processed_frames / len(positions)))
            finally:
                cap.release()
                timings["pose"] = max(0, round((time.perf_counter() - stage_started) * 1000))
                publish()

            if not detected_pose_frames:
                raise RuntimeError("视频中没有识别到攀爬者，请检查机位和光线")
            track_id, records = self._choose_track(records)

            stage_started = time.perf_counter()
            progress("计算手脚与岩点接触", 82)
            attempt = self._contacts(records, holds, sample_fps)
            pose_samples = build_pose_samples(records, video_info)
            add_attempt_source_times(attempt, pose_samples, video_info)
            attempt["action_steps"] = build_action_steps(attempt.get("contacts") or [])
            timings["contact"] = max(0, round((time.perf_counter() - stage_started) * 1000))

            stage_started = time.perf_counter()
            progress("生成可导出的叠加视频", 86)
            result = {
                "schema_version": 2,
                "status": "prototype_needs_review",
                "route": {"color": route_color},
                "models": {"holds": hold_version, "pose": self.pose_model},
                "video": asdict(video_info),
                "track_id": track_id,
                "frames_with_pose": detected_pose_frames,
                "holds": holds,
                "pose_samples": pose_samples,
                "attempt": attempt,
                "analysis": analysis,
                "warnings": [
                    "当前为技术验证结果，手脚接触需要用户复核。",
                    "岩点由服务器本地专项模型识别，并直接保留模型原生掩膜轮廓；姿态仅对降帧画面调用阿里云人体姿态关键点服务。",
                    "导出视频在相邻实测姿态帧之间做本地线性平滑；分析证据仍以实测抽样帧为准。",
                    "导出的叠加视频保留原画面，但当前不包含原视频音轨。",
                    "岩点接触使用本地专项模型原生实例分割轮廓与短时停留判断，接触边界仍需用户复核。",
                    "开始时间根据首个手脚同时稳定接触估算，尚未使用地面分割。",
                ],
            }
            result["overlay"] = render_replay_overlay_video(
                video, video.with_name(REPLAY_OVERLAY_FILENAME), result,
                progress=lambda value: progress(
                    "生成可导出的叠加视频", 86 + round(10 * value / 100),
                ),
                cancelled=cancelled,
            )
            timings["overlay"] = max(0, round((time.perf_counter() - stage_started) * 1000))

            stage_started = time.perf_counter()
            progress("整理复盘报告", 97)
            timings["report"] = max(0, round((time.perf_counter() - stage_started) * 1000))
            publish()
            return result
        finally:
            publish()


def create_climb_replay_router(
    store: ClimbReplayStore,
    manager: ClimbReplayManager,
    *,
    route_lookup: Callable[[str, str], dict] | None = None,
    limits: VideoLimits | None = None,
    test_video_path: Path | None = None,
    test_video_source_url: str | None = None,
    test_video_cases: list[dict[str, Any]] | None = None,
) -> APIRouter:
    limits = limits or VideoLimits()
    router = APIRouter(prefix="/api/climb-replay", tags=["climb-replay"])
    replay_uploads = ChunkUploadStore(store.root / ".chunk-uploads")
    configured_test_videos: list[dict[str, Any]] = []
    for index, item in enumerate(test_video_cases or []):
        path_value = item.get("path")
        case_id = str(item.get("id") or f"case-{index + 1}").strip()
        if not path_value or not case_id or not all(
                char.isalnum() or char in {"-", "_"} for char in case_id):
            continue
        configured_test_videos.append({
            "id": case_id,
            "label": str(item.get("label") or f"本地案例 {index + 1}").strip(),
            "description": str(item.get("description") or "本地验收素材").strip(),
            "path": Path(path_value).resolve(),
            "comparison_path": (Path(item["comparison_path"]).resolve()
                                if item.get("comparison_path") else None),
            "comparison_route_color": str(item.get("comparison_route_color") or "").strip(),
            "comparison_action_count": int(item.get("comparison_action_count") or 0),
            "source_url": item.get("source_url"),
        })
    if not configured_test_videos and test_video_path:
        configured_test_videos.append({
            "id": "case-1",
            "label": "本地案例 1",
            "description": "本地验收素材",
            "path": Path(test_video_path).resolve(),
            "comparison_path": None,
            "comparison_route_color": "",
            "comparison_action_count": 0,
            "source_url": test_video_source_url,
        })

    def available_test_videos() -> list[dict[str, Any]]:
        return [item for item in configured_test_videos
                if item["path"].is_file() and item["path"].suffix.lower() == ".mp4"]

    def public_test_video(item: dict[str, Any]) -> dict[str, Any]:
        path = item["path"]
        return {
            "id": item["id"],
            "label": item["label"],
            "description": item["description"],
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "comparison_available": bool(
                item.get("comparison_path")
                and item["comparison_path"].is_file()
                and item["comparison_path"].suffix.lower() == ".webm"
            ),
            "comparison_route_color": item.get("comparison_route_color") or None,
            "comparison_action_count": item.get("comparison_action_count") or None,
            "source_url": item.get("source_url"),
            "usage": "local_acceptance_only",
        }

    def owner(request: Request) -> str:
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    def consent_policy() -> dict:
        region = str(getattr(manager.analyzer, "region_id", "cn-shanghai"))
        return {
            "version": REPLAY_CONSENT_VERSION,
            "provider": REPLAY_CONSENT_PROVIDER,
            "service": REPLAY_CONSENT_SERVICE,
            "region": region,
            "data_types": list(REPLAY_CONSENT_DATA_TYPES),
            "purpose": "生成本次攀岩复盘所需的人体姿态关键点",
            "full_video_sent": False,
        }

    def consent_grant(version: str, granted: bool, *, attempt: int) -> dict:
        policy = consent_policy()
        if not granted:
            raise HTTPException(422, "请先明确同意本次抽样画面第三方处理")
        if version != policy["version"]:
            raise HTTPException(409, "数据处理告知已更新，请阅读最新说明并重新同意")
        return {
            "event": "granted", "attempt": attempt, "version": policy["version"],
            "provider": policy["provider"], "service": policy["service"],
            "region": policy["region"], "data_types": policy["data_types"],
            "purpose": policy["purpose"], "full_video_sent": policy["full_video_sent"],
            "granted_at": utcnow(),
        }

    def retention_choice(value: str) -> ReplayRetentionMode:
        if value not in {REPLAY_RETENTION_DELETE, REPLAY_RETENTION_KEEP}:
            raise HTTPException(422, "请选择有效的视频保留方式")
        return value  # type: ignore[return-value]

    def resolve_route(username: str, route_id: str, route_color: str) -> tuple[str, str]:
        route_id = route_id.strip()
        if route_id:
            if route_lookup is None:
                raise HTTPException(503, "线路库尚未连接到复盘服务")
            route = route_lookup(route_id, username)
            route_color = str(route.get("color_group") or route_color).strip()
        route_color = route_color.strip()
        if not route_color or len(route_color) > 40:
            raise HTTPException(422, "请选择需要分析的线路颜色")
        return route_id, route_color

    @router.get("/consent-policy")
    def get_consent_policy(request: Request):
        owner(request)
        return consent_policy()

    @router.get("/test-video-info")
    def get_test_video_info(request: Request):
        owner(request)
        items = available_test_videos()
        available = bool(items)
        first = items[0] if items else None
        return {
            "available": available,
            "filename": first["path"].name if first else None,
            "size_bytes": first["path"].stat().st_size if first else None,
            "source_url": first.get("source_url") if first else None,
            "usage": "local_acceptance_only" if available else None,
        }

    @router.get("/test-videos")
    def list_test_videos(request: Request):
        owner(request)
        return {"items": [public_test_video(item) for item in available_test_videos()]}

    def test_video_response(item: dict[str, Any]) -> FileResponse:
        return FileResponse(
            item["path"],
            media_type="video/mp4",
            filename=item["path"].name,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def comparison_video_response(item: dict[str, Any], *, download: bool) -> FileResponse:
        path = item.get("comparison_path")
        if not path or not path.is_file() or path.suffix.lower() != ".webm":
            raise HTTPException(404, "最新对照版视频不存在")
        return FileResponse(
            path,
            media_type="video/webm",
            filename=path.name if download else None,
            content_disposition_type="attachment" if download else "inline",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/test-videos/{case_id}")
    def get_test_video_case(case_id: str, request: Request):
        owner(request)
        item = next((candidate for candidate in available_test_videos()
                     if candidate["id"] == case_id), None)
        if item is None:
            raise HTTPException(404, "本机测试视频不存在")
        return test_video_response(item)

    @router.get("/test-videos/{case_id}/comparison")
    def get_test_video_comparison(case_id: str, request: Request, download: bool = False):
        owner(request)
        item = next((candidate for candidate in available_test_videos()
                     if candidate["id"] == case_id), None)
        if item is None:
            raise HTTPException(404, "本机测试视频不存在")
        return comparison_video_response(item, download=download)

    @router.get("/test-video")
    def get_test_video(request: Request):
        owner(request)
        items = available_test_videos()
        if not items:
            raise HTTPException(404, "本机测试视频尚未配置")
        return test_video_response(items[0])

    @router.post("/jobs", status_code=202)
    async def create_job(
        request: Request,
        video: UploadFile = File(...),
        route_id: str = Form(default=""),
        route_color: str = Form(default=""),
        consent_version: str = Form(default=""),
        consent_granted: bool = Form(default=False),
        retention_mode: str = Form(default=REPLAY_RETENTION_DELETE),
    ):
        username = owner(request)
        route_id, route_color = resolve_route(username, route_id, route_color)
        consent = consent_grant(consent_version, consent_granted, attempt=1)
        retention = retention_choice(retention_mode)
        if (video.content_type or "").lower() != "video/mp4":
            raise HTTPException(422, "技术验证阶段仅支持 MP4 视频")

        upload = store.root / f".upload-{uuid.uuid4().hex}.tmp"
        size, digest = 0, hashlib.sha256()
        try:
            with upload.open("wb") as target:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > limits.max_bytes:
                        raise HTTPException(413, f"视频不能超过 {limits.max_bytes // (1024 * 1024)} MB")
                    digest.update(chunk)
                    target.write(chunk)
            if not size:
                raise HTTPException(422, "视频内容为空")
            try:
                info = probe_video(upload)
                validate_video(info, limits)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            job = store.create(owner=username, route_id=route_id or None, route_color=route_color,
                               source=upload, original_name=video.filename or f"{digest.hexdigest()}.mp4",
                               info=info, consent=consent, retention_mode=retention)
            manager.enqueue(job["id"])
            return job
        finally:
            upload.unlink(missing_ok=True)

    @router.post("/uploads")
    def create_upload(payload: ReplayUploadCreate, request: Request):
        username = owner(request)
        route_id, route_color = resolve_route(username, payload.route_id, payload.route_color)
        consent = consent_grant(payload.consent_version, payload.consent_granted, attempt=1)
        if payload.content_type.lower() != "video/mp4":
            raise HTTPException(422, "技术验证阶段仅支持 MP4 视频")
        try:
            return replay_uploads.create(username, total_size=payload.size_bytes, max_size=limits.max_bytes, metadata={
                "filename": payload.filename, "content_type": "video/mp4",
                "route_id": route_id, "route_color": route_color,
                "consent": consent, "retention_mode": payload.retention_mode,
            })
        except ChunkUploadError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.put("/uploads/{upload_id}")
    async def append_upload(upload_id: str, request: Request):
        try:
            offset = int(request.headers.get("x-upload-offset", "-1"))
        except ValueError as exc:
            raise HTTPException(422, "上传位置无效") from exc
        try:
            return replay_uploads.append(upload_id, owner(request), offset=offset, data=await request.body())
        except ChunkUploadError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/uploads/{upload_id}/complete", status_code=202)
    def complete_upload(upload_id: str, request: Request):
        username = owner(request)
        try:
            meta, part = replay_uploads.finish(upload_id, username)
            details = meta["metadata"]
            route_id, route_color = resolve_route(username, details.get("route_id", ""), details.get("route_color", ""))
            try:
                info = probe_video(part)
                validate_video(info, limits)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            job = store.create(owner=username, route_id=route_id or None, route_color=route_color,
                               source=part, original_name=details["filename"], info=info,
                               consent=details["consent"],
                               retention_mode=retention_choice(
                                   details.get("retention_mode", REPLAY_RETENTION_DELETE),
                               ))
            manager.enqueue(job["id"])
            return job
        except ChunkUploadError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            replay_uploads.discard(upload_id)

    @router.get("/jobs")
    def list_jobs(request: Request):
        return store.list(owner(request))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        return store.get(job_id, owner(request))

    def media_response(job_id: str, request: Request, media_kind: str,
                       *, download: bool) -> FileResponse:
        path, item = store.media_file(job_id, owner(request), media_kind)
        options = {
            "media_type": item.get("content_type") or "application/octet-stream",
            "headers": {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        }
        if download:
            options["filename"] = item.get("filename") or path.name
        return FileResponse(path, **options)

    @router.get("/jobs/{job_id}/media/source-video")
    def get_source_video(job_id: str, request: Request, download: bool = False):
        return media_response(job_id, request, "source_video", download=download)

    @router.get("/jobs/{job_id}/media/overlay-video")
    def get_overlay_video(job_id: str, request: Request, download: bool = False):
        return media_response(job_id, request, REPLAY_OVERLAY_MEDIA_KIND, download=download)

    @router.delete("/jobs/{job_id}/media/source-video")
    def delete_source_video(job_id: str, request: Request):
        return store.delete_media(job_id, owner(request), "source_video")

    @router.delete("/jobs/{job_id}/media/overlay-video")
    def delete_overlay_video(job_id: str, request: Request):
        return store.delete_media(job_id, owner(request), REPLAY_OVERLAY_MEDIA_KIND)

    @router.delete("/jobs/{job_id}", status_code=202)
    def delete_job(job_id: str, request: Request):
        receipt = store.request_delete(job_id, owner(request))
        if receipt.get("state") == "queued":
            manager.enqueue_delete(job_id)
        return receipt

    @router.get("/deletions/{job_id}")
    def get_deletion(job_id: str, request: Request):
        return store.get_deletion(job_id, owner(request))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request):
        return store.cancel(job_id, owner(request))

    @router.post("/jobs/{job_id}/retry")
    def retry_job(job_id: str, payload: ReplayRetryCreate, request: Request):
        username = owner(request)
        job = store.get(job_id, username, private=True)
        consent = consent_grant(
            payload.consent_version, payload.consent_granted,
            attempt=int(job.get("attempt") or 1) + 1,
        )
        result = store.retry(job_id, username, consent)
        manager.enqueue(job_id)
        return result

    @router.post("/jobs/{job_id}/consent/withdraw")
    def withdraw_job_consent(job_id: str, request: Request):
        return store.withdraw_consent(job_id, owner(request))

    return router
