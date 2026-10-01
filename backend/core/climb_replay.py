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
import bisect
import copy
import io
import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core.chunked_upload import ChunkUploadError, ChunkUploadStore
from core.photo_route_analysis import _climbing_model_masks_batch
from core.photo_route_colors import TWELVE_COLOR_VERSION, classify_mask_color, lab_color_name, mask_sample_distance
from core.photo_route_inference_lock import serialized_inference
from core.replay_hold_fusion import align_pose_record, align_to_reference, box_iou, fuse_hold_detections, match_confirmed_route, polygon_bbox, select_sampled_route_holds, transform_polygon
from core.replay_segments import build_segments, compare_segments, effective_segments, measured_joint_angles
from core.replay_resources import high_resource_slot, run_visual_worker, serialized_heavy_stage


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_after(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


REPLAY_CONSENT_VERSION = "climb-replay-pose-frames-v1-2026-09-20"
REPLAY_CONSENT_PROVIDER = "阿里云视觉智能开放平台"
REPLAY_CONSENT_SERVICE = "BodyPosture"
REPLAY_CONSENT_DATA_TYPES = ["降帧后的单张视频画面", "画面中的人体姿态关键点"]
REPLAY_PIPELINE_VERSION = "climb-replay-v2.6-reviewed-segments"
REPLAY_POSE_API_VERSION = "2019-12-30"
DEFAULT_POSE_UNIT_PRICE_CNY = 0.0016
REPLAY_RETENTION_DELETE = "delete_after_processing"
REPLAY_RETENTION_KEEP = "keep_private_original"
ReplayRetentionMode = Literal["delete_after_processing", "keep_private_original"]
REPLAY_OVERLAY_FILENAME = "overlay.webm"
REPLAY_OVERLAY_MEDIA_KIND = "overlay_video"
REPLAY_REVIEWED_OVERLAY_MEDIA_KIND = "reviewed_overlay_video"
REPLAY_REFERENCE_MEDIA_KIND = "wall_reference"
REPLAY_REFERENCE_FILENAME = "replay-reference.png"
REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE = 34.0
REPLAY_VIDEO_MIME_TYPES = frozenset({
    "video/mp4", "video/quicktime", "video/x-m4v", "video/webm",
    "video/3gpp", "video/3gpp2", "video/x-matroska",
})
REPLAY_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm", ".3gp", ".3g2", ".mkv"})


class ReplayConfigurationError(RuntimeError):
    """Raised when the opt-in pose provider has no usable configuration."""


class ReplayCancelled(RuntimeError):
    """Raised between analysis stages after a user asks to cancel."""


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 200 * 1024 * 1024
    max_input_bytes: int = 500 * 1024 * 1024
    max_duration_seconds: float = 90.0
    max_width: int = 1920
    max_height: int = 1080
    max_frames: int = 2700


class ReplayColorSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["palette", "video"]
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    rgb: list[int] = Field(min_length=3, max_length=3)
    time_seconds: float | None = Field(default=None, ge=0)
    point_xy: list[float] | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("rgb")
    @classmethod
    def validate_rgb(cls, value: list[int]) -> list[int]:
        if any(channel < 0 or channel > 255 for channel in value):
            raise ValueError("RGB 数值必须在 0 到 255 之间")
        return value

    @field_validator("point_xy")
    @classmethod
    def validate_point(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (not all(math.isfinite(item) and 0 <= item <= 1 for item in value)):
            raise ValueError("岩点坐标必须位于画面内")
        return value

    @model_validator(mode="after")
    def validate_video_point(self):
        if self.source == "video" and self.point_xy is not None and self.time_seconds is None:
            raise ValueError("视频岩点样本需要对应的画面时间")
        return self


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
    trim_start_seconds: float = Field(default=0, ge=0)
    trim_end_seconds: float | None = Field(default=None, gt=0)
    route_color_sample: ReplayColorSample | None = None


class ReplayRetryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool


class ReplayComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_job_id: str = Field(min_length=1, max_length=64)
    second_job_id: str = Field(min_length=1, max_length=64)
    same_climber_confirmed: bool = False


class ReplaySegmentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limb: Literal["left_hand", "right_hand", "left_foot", "right_foot"]
    source_route_hold_id: str = Field(min_length=1, max_length=100)
    target_route_hold_id: str = Field(min_length=1, max_length=100)
    start_time_seconds: float = Field(ge=0)
    end_time_seconds: float = Field(gt=0)
    technique_label: Literal["高抬脚", "锁臂", "旗式", "脚上方重心转移", "动态点", "跳跃", "主动摆荡换点", "抓点后制摆", "开门摆动"] | None = None


class ReplayHoldPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point_xy: list[float] = Field(min_length=2, max_length=2)
    time_seconds: float = Field(ge=0)
    region_xyxy: list[float] | None = Field(default=None, min_length=4, max_length=4)

    @field_validator("point_xy")
    @classmethod
    def validate_point(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(item) and 0 <= item <= 1 for item in value):
            raise ValueError("补点位置必须位于视频画面内")
        return value

    @field_validator("region_xyxy")
    @classmethod
    def validate_region(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        x0, y0, x1, y1 = value
        if (not all(math.isfinite(item) and 0 <= item <= 1 for item in value)
                or x1 - x0 < .012 or y1 - y0 < .012
                or x1 - x0 > .35 or y1 - y0 > .35):
            raise ValueError("请框出画面中单个岩点的大概范围")
        return value


def parse_color_sample(value: str | dict | ReplayColorSample | None) -> dict | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, ReplayColorSample):
            sample = value
        else:
            payload = json.loads(value) if isinstance(value, str) else value
            sample = ReplayColorSample.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise ValueError("视频取色样本无效，请重新取色") from exc
    return sample.model_dump()


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
    orientation_auto = getattr(cv2, "CAP_PROP_ORIENTATION_AUTO", None)
    if cap.isOpened() and orientation_auto is not None:
        cap.set(orientation_auto, 1)
    try:
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        if ok and frame is not None:
            height, width = frame.shape[:2]
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        else:
            width = height = frame_count = 0
            fps = 0.0
    finally:
        cap.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
        from imageio_ffmpeg import get_ffmpeg_exe
        try:
            result = subprocess.run(
                [get_ffmpeg_exe(), "-hide_banner", "-i", str(path), "-t", "0", "-f", "null", "-"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15,
            )
            duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
            video_match = re.search(
                r"Video:.*?(\d{2,5})x(\d{2,5}).*?(\d+(?:\.\d+)?) fps", result.stderr,
            )
            if not duration_match or not video_match:
                raise ValueError("missing video stream metadata")
            hours, minutes, seconds = duration_match.groups()
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            width, height = int(video_match.group(1)), int(video_match.group(2))
            rotation = re.search(r"rotation of\s+(-?\d+(?:\.\d+)?) degrees", result.stderr)
            if rotation and abs(float(rotation.group(1))) % 180 > 45:
                width, height = height, width
            fps = float(video_match.group(3))
            frame_count = max(1, int(round(duration * fps)))
        except (OSError, RuntimeError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            raise ValueError("服务器无法读取这个视频，可能是文件损坏或编码暂不支持；可更换视频重试，仍失败请联系管理员") from exc
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


def validate_video_upload_type(filename: str, content_type: str) -> bool:
    """Accept common mobile containers without trusting MIME metadata alone."""
    suffix = Path(filename or "").suffix.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in REPLAY_VIDEO_MIME_TYPES and suffix not in REPLAY_VIDEO_SUFFIXES:
        raise ValueError("支持 MP4、MOV、M4V、WebM、3GP 和 MKV 视频")
    return suffix == ".mp4" and mime in {"", "application/octet-stream", "video/mp4"}


@serialized_heavy_stage
def convert_video_to_mp4(
    source: Path,
    target: Path,
    *,
    limits: VideoLimits | None = None,
    start_seconds: float = 0,
    end_seconds: float | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """Produce a silent, upright, browser-readable H.264 analysis copy."""
    from imageio_ffmpeg import get_ffmpeg_exe

    info = probe_video(source)
    bounds = limits or VideoLimits()
    if not math.isfinite(start_seconds) or start_seconds < 0 or start_seconds >= info.duration_seconds:
        raise ValueError("视频片段起点无效或超出视频时长")
    finish = min(info.duration_seconds, end_seconds if end_seconds is not None else start_seconds + bounds.max_duration_seconds)
    if not math.isfinite(finish) or finish <= start_seconds or finish > info.duration_seconds + .05:
        raise ValueError("视频片段终点无效或超出视频时长")
    duration = finish - start_seconds
    output_fps = min(info.fps, 30.0, bounds.max_frames / duration)
    if output_fps < 1:
        raise ValueError("当前视频片段过长，无法在试用上限内处理")

    def dimensions(max_long: int, max_short: int) -> tuple[int, int]:
        scale = min(1.0, max_long / max(info.width, info.height), max_short / min(info.width, info.height))
        return (max(2, int(info.width * scale) // 2 * 2),
                max(2, int(info.height * scale) // 2 * 2))

    try:
        ffmpeg = get_ffmpeg_exe()
    except (OSError, RuntimeError) as exc:
        raise ValueError("服务器视频转换组件不可用，请联系管理员检查媒体处理组件") from exc
    for long_edge, short_edge, crf in ((bounds.max_width, bounds.max_height, 26), (1280, 720, 30), (960, 540, 34)):
        width, height = dimensions(long_edge, short_edge)
        target.unlink(missing_ok=True)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-i", str(source), "-ss", str(start_seconds), "-t", str(duration),
                   "-map", "0:v:0", "-an", "-vf", f"fps={output_fps:.5f},scale={width}:{height}",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf),
                   "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ValueError("服务器无法启动视频转换组件，请联系管理员检查媒体处理组件") from exc
        try:
            while process.poll() is None:
                if cancelled():
                    process.terminate()
                    raise ReplayCancelled()
                try:
                    process.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise ValueError("服务器未能完成视频转换，可能是编码暂不支持、文件损坏或服务器资源不足；可更换视频重试，仍失败请联系管理员")
        if target.stat().st_size <= bounds.max_bytes:
            return
    target.unlink(missing_ok=True)
    raise ValueError(f"视频压缩后仍超过 {bounds.max_bytes // (1024 * 1024)} MB，当前服务器无法处理")


def prepare_video_upload(
    source: Path,
    *,
    filename: str,
    content_type: str,
    limits: VideoLimits,
    output: Path,
    trim_start_seconds: float = 0,
    trim_end_seconds: float | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[Path, VideoInfo]:
    """Validate uploaded bytes and normalize mobile media for analysis."""
    validate_video_upload_type(filename, content_type)
    original_info = probe_video(source)
    if original_info.size_bytes > limits.max_input_bytes:
        raise ValueError(f"视频不能超过 {limits.max_input_bytes // (1024 * 1024)} MB")
    trim_start_seconds = float(trim_start_seconds)
    if not math.isfinite(trim_start_seconds) or trim_start_seconds < 0:
        raise ValueError("视频片段起点无效")
    if trim_end_seconds is not None:
        trim_end_seconds = float(trim_end_seconds)
        if not math.isfinite(trim_end_seconds):
            raise ValueError("视频片段终点无效")
        if trim_end_seconds <= trim_start_seconds:
            raise ValueError("视频片段终点必须晚于起点")
        if trim_end_seconds - trim_start_seconds > limits.max_duration_seconds + 0.05:
            raise ValueError(f"视频片段不能超过 {limits.max_duration_seconds:g} 秒")
    elif original_info.duration_seconds > trim_start_seconds + limits.max_duration_seconds:
        trim_end_seconds = trim_start_seconds + limits.max_duration_seconds
    if trim_end_seconds is not None and trim_end_seconds > original_info.duration_seconds + 0.05:
        raise ValueError("视频片段终点超出视频时长")
    try:
        convert_video_to_mp4(
            source, output, limits=limits,
            start_seconds=trim_start_seconds, end_seconds=trim_end_seconds,
            cancelled=cancelled,
        )
        converted_info = probe_video(output)
        validate_video(converted_info, limits)
        return output, converted_info
    except Exception:
        output.unlink(missing_ok=True)
        raise


def validate_video(info: VideoInfo, limits: VideoLimits, *, max_bytes: int | None = None) -> None:
    byte_limit = limits.max_bytes if max_bytes is None else max_bytes
    if info.size_bytes > byte_limit:
        raise ValueError(f"视频不能超过 {byte_limit // (1024 * 1024)} MB")
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
            "wall_alignment": record.get("wall_alignment", "unknown"),
            "wall_alignment_diagnostics": record.get("wall_alignment_diagnostics") or {},
            "wall_reference_transform": record.get("wall_reference_transform"),
            "observed": bool(usable_scores),
            "confidence": round(float(np.mean(usable_scores)), 6) if usable_scores else 0.0,
            "kpts_xy": record.get("kpts_xy") or [[0.0, 0.0] for _ in range(17)],
            "kpts_score": scores or [0.0] * 17,
            "bbox_xywh": record.get("bbox_xywh") or [0.0, 0.0, 0.0, 0.0],
            "joint_angles_2d": measured_joint_angles(
                record.get("kpts_xy") or [], scores, video_info.width, video_info.height),
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
        stable = sample_value(contact.get("stable_frame"))
        if start:
            contact["start_source_frame"] = start["source_frame_id"]
            contact["start_time_seconds"] = start["time_seconds"]
        if end:
            contact["end_source_frame"] = end["source_frame_id"]
            contact["end_time_seconds"] = end["time_seconds"]
        if stable:
            contact["stable_source_frame"] = stable["source_frame_id"]
            contact["stable_time_seconds"] = stable["time_seconds"]
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
            "stable_source_frame": contact.get("stable_source_frame"),
            "stable_time_seconds": contact.get("stable_time_seconds"),
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


def clicked_hold_polygon(frame: np.ndarray, point_xy: list[float]) -> list[list[float]]:
    """Trace a local colour component around a user click; never invent a box."""
    height, width = frame.shape[:2]
    x = min(width - 1, int(point_xy[0] * width))
    y = min(height - 1, int(point_xy[1] * height))
    radius = max(24, round(min(width, height) * .09))
    left, top = max(0, x - radius), max(0, y - radius)
    right, bottom = min(width, x + radius + 1), min(height, y + radius + 1)
    lab = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2LAB)
    local_x, local_y = x - left, y - top
    seed = lab[max(0, local_y - 2):local_y + 3,
               max(0, local_x - 2):local_x + 3]
    target = np.median(seed.reshape(-1, 3), axis=0)
    distance = np.linalg.norm(lab.astype(np.float32) - target, axis=2)
    binary = (distance <= 26).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    label = int(labels[local_y, local_x])
    if label == 0 or label >= count:
        raise HTTPException(422, "点击位置没有清晰的岩点轮廓，请换一帧并点击岩点中间。")
    area = int(stats[label, cv2.CC_STAT_AREA])
    if area < 12 or area > binary.size * .32:
        raise HTTPException(422, "点击处的颜色区域无法确定为单个岩点，请换一帧或点击岩点中间。")
    component = np.where(labels == label, 255, 0).astype(np.uint8)
    contour = native_mask_polygon(component, max_points=160)
    if len(contour) < 3:
        raise HTTPException(422, "点击位置没有可用的岩点轮廓，请换一帧再试。")
    polygon = [[float(point[0][0] + left), float(point[0][1] + top)] for point in contour]
    box = polygon_bbox([[px / width, py / height] for px, py in polygon])
    if box[2] > .2 or box[3] > .2:
        raise HTTPException(422, "点击处的范围过大，可能点到了墙面；请点击岩点中间。")
    return polygon


def boxed_hold_polygon(frame: np.ndarray, region_xyxy: list[float]) -> list[list[float]]:
    """Find the most hold-like colour component inside a rough user rectangle."""
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = region_xyxy
    inner_left, inner_top = int(x0 * width), int(y0 * height)
    inner_right = min(width, max(inner_left + 1, math.ceil(x1 * width)))
    inner_bottom = min(height, max(inner_top + 1, math.ceil(y1 * height)))
    inner_width, inner_height = inner_right - inner_left, inner_bottom - inner_top
    padding = max(5, round(max(inner_width, inner_height) * .12))
    left, top = max(0, inner_left - padding), max(0, inner_top - padding)
    right, bottom = min(width, inner_right + padding), min(height, inner_bottom + padding)
    lab = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2LAB)
    inner = np.zeros(lab.shape[:2], dtype=bool)
    inner[inner_top - top:inner_bottom - top, inner_left - left:inner_right - left] = True
    border_pixels = lab[~inner]
    if len(border_pixels) < 8:
        raise HTTPException(422, "框选范围太贴近画面边缘，请稍微扩大画面后重试。")
    background = np.median(border_pixels, axis=0)
    min_area = max(12, round(inner_width * inner_height * .045))
    region_center = np.asarray([(inner_left + inner_right) / 2 - left,
                                (inner_top + inner_bottom) / 2 - top])
    region_radius = max(1, math.hypot(inner_width, inner_height) / 2)
    proposals = []
    for fy in (.18, .34, .5, .66, .82):
        for fx in (.18, .34, .5, .66, .82):
            px = min(lab.shape[1] - 1, int(inner_left - left + inner_width * fx))
            py = min(lab.shape[0] - 1, int(inner_top - top + inner_height * fy))
            seed = lab[max(0, py - 1):py + 2, max(0, px - 1):px + 2]
            target = np.median(seed.reshape(-1, 3), axis=0)
            distance = np.linalg.norm(lab.astype(np.float32) - target, axis=2)
            binary = (distance <= 26).astype(np.uint8)
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
            label = int(labels[py, px])
            if label <= 0 or label >= count:
                continue
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_area or area > binary.size * .65:
                continue
            component = labels == label
            inside_count = int(np.count_nonzero(component & inner))
            if inside_count < .65 * area:
                continue
            bx, by, bw, bh = (int(value) for value in stats[label, :4])
            if bw > width * .25 or bh > height * .25:
                continue
            touches_crop = bx == 0 or by == 0 or bx + bw >= lab.shape[1] or by + bh >= lab.shape[0]
            contrast = float(np.linalg.norm(target - background))
            centrality = max(0.0, 1 - float(np.linalg.norm(centroids[label] - region_center)) / region_radius)
            coverage = min(1.0, inside_count / max(1, inner_width * inner_height))
            score = min(contrast, 100) * .08 + coverage * 9 + centrality * 3
            score -= 10 if touches_crop else 0
            proposals.append((score, area, component))
    if not proposals:
        raise HTTPException(422, "框内没有找到可靠的岩点轮廓，请框紧单个岩点或换到无遮挡的画面。")
    selected = max(proposals, key=lambda item: (item[0], item[1]))[2]
    # The colour seed may cover only a bright ridge of a shaded hold. Use the
    # selected component as sure foreground and the user's box as a local mask.
    if np.count_nonzero(selected) >= 12:
        mask = np.where(inner, cv2.GC_PR_FGD, cv2.GC_BGD).astype(np.uint8)
        wall_distance = np.linalg.norm(lab.astype(np.float32) - background, axis=2)
        mask[inner & (wall_distance < 14)] = cv2.GC_PR_BGD
        sure = cv2.erode(selected.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        mask[sure] = cv2.GC_FGD
        if np.count_nonzero(sure) >= 5:
            try:
                cv2.grabCut(frame[top:bottom, left:right], mask, None,
                            np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                            4, cv2.GC_INIT_WITH_MASK)
                expanded = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)) & inner
                count, labels, stats, _ = cv2.connectedComponentsWithStats(expanded.astype(np.uint8), 8)
                matching = [(int(np.count_nonzero((labels == index) & selected)), index)
                            for index in range(1, count)]
                if matching:
                    overlap, label = max(matching)
                    area = int(stats[label, cv2.CC_STAT_AREA])
                    if overlap >= max(4, np.count_nonzero(selected) * .35) \
                            and np.count_nonzero(selected) <= area <= inner_width * inner_height * .90:
                        selected = labels == label
            except cv2.error:
                pass
    contour = native_mask_polygon(selected.astype(np.uint8) * 255, max_points=160)
    if len(contour) < 3:
        raise HTTPException(422, "框内岩点轮廓不完整，请框紧一些或换帧。")
    return [[float(item[0][0] + left), float(item[0][1] + top)] for item in contour]


def _multi_frame_clicked_polygon(source: Path, video: VideoInfo, frame_index: int,
                                 reference_index: int, reference: np.ndarray,
                                 initial: list[list[float]],
                                 region_xyxy: list[float] | None = None) -> tuple[list[list[float]], int]:
    """Prefer a contour observed consistently in nearby unobstructed frames."""
    initial_box = polygon_bbox(initial)
    center = np.asarray([[[video.width * (initial_box[0] + initial_box[2] / 2),
                           video.height * (initial_box[1] + initial_box[3] / 2)]]], np.float32)
    proposals = [(frame_index, initial, initial_box)]
    offsets = {max(1, round(video.fps * seconds)) for seconds in (.4, .8, 1.2)}
    capture = cv2.VideoCapture(str(source))
    try:
        for offset in sorted({signed * delta for delta in offsets for signed in (-1, 1)}):
            candidate_index = frame_index + offset
            if candidate_index < 0 or candidate_index >= video.frame_count:
                continue
            capture.set(cv2.CAP_PROP_POS_FRAMES, candidate_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            to_reference = np.eye(3) if candidate_index == reference_index else align_to_reference(frame, reference)[0]
            if to_reference is None:
                continue
            try:
                to_candidate = np.linalg.inv(to_reference)
            except np.linalg.LinAlgError:
                continue
            pixel = cv2.perspectiveTransform(center, to_candidate).reshape(2)
            if not np.isfinite(pixel).all():
                continue
            click = [float(pixel[0] / video.width), float(pixel[1] / video.height)]
            if not all(0 <= value <= 1 for value in click):
                continue
            try:
                if region_xyxy is None:
                    polygon = clicked_hold_polygon(frame, click)
                else:
                    expansion = .15
                    bx, by, bw, bh = initial_box
                    x0, y0 = video.width * (bx - bw * expansion), video.height * (by - bh * expansion)
                    x1, y1 = video.width * (bx + bw * (1 + expansion)), video.height * (by + bh * (1 + expansion))
                    corners = np.asarray([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]], np.float32)
                    projected = cv2.perspectiveTransform(corners, to_candidate).reshape(4, 2)
                    if not np.isfinite(projected).all():
                        continue
                    values = [float(np.clip(projected[:, 0].min() / video.width, 0, 1)),
                              float(np.clip(projected[:, 1].min() / video.height, 0, 1)),
                              float(np.clip(projected[:, 0].max() / video.width, 0, 1)),
                              float(np.clip(projected[:, 1].max() / video.height, 0, 1))]
                    polygon = boxed_hold_polygon(frame, values)
            except HTTPException:
                continue
            mapped = transform_polygon(polygon, to_reference, video.width, video.height)
            if len(mapped) < 3:
                continue
            box = polygon_bbox(mapped)
            if box_iou(box, initial_box) >= .28:
                proposals.append((candidate_index, mapped, box))
    finally:
        capture.release()
    if len(proposals) < 3:
        return initial, 1
    ranked = []
    for index, (_, polygon, box) in enumerate(proposals):
        overlaps = [box_iou(box, other[2]) for other_index, other in enumerate(proposals)
                    if other_index != index]
        support = sum(value >= .55 for value in overlaps)
        ranked.append((support, sum(overlaps), -len(polygon), index))
    support, _, _, selected_index = max(ranked)
    if support < 2:
        return initial, 1
    return proposals[selected_index][1], support + 1


def _registered_hold_polygons(source: cv2.VideoCapture, reference: np.ndarray,
                              holds: list[dict], fps: float, total: int,
                              reference_index: int) -> dict[int, list[list[list[float]]]]:
    """Project fixed wall contours back into sampled source frames."""
    interval = max(1, round(fps / 5))
    indices = sorted({*range(0, total, interval), total - 1, reference_index})
    height, width = reference.shape[:2]
    reference_polygons = []
    for hold in holds:
        polygon = hold.get("polygon") or []
        if len(polygon) < 3:
            x, y, w, h = hold["bbox"]
            polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        reference_polygons.append(np.asarray(polygon, np.float32) * [width, height])
    registered = {}
    for index in indices:
        source.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = source.read()
        if not ok or frame is None:
            continue
        if index == reference_index or np.mean(cv2.absdiff(frame, reference)) < 3:
            matrix = np.eye(3)
        else:
            to_reference, _ = align_to_reference(frame, reference)
            if to_reference is None:
                continue
            try:
                matrix = np.linalg.inv(to_reference)
            except np.linalg.LinAlgError:
                continue
        projected = []
        for polygon in reference_polygons:
            pixels = cv2.perspectiveTransform(polygon.reshape(-1, 1, 2), matrix).reshape(-1, 2)
            if not np.isfinite(pixels).all():
                break
            projected.append((pixels / [width, height]).tolist())
        if len(projected) == len(holds):
            registered[index] = projected
    source.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return registered


def _interpolated_hold_polygons(registered: dict[int, list[list[list[float]]]],
                                frame_index: int, fps: float) -> list[list[list[float]]] | None:
    anchors = sorted(registered)
    if not anchors:
        return None
    position = bisect.bisect_left(anchors, frame_index)
    if position < len(anchors) and anchors[position] == frame_index:
        return registered[frame_index]
    before = anchors[position - 1] if position else None
    after = anchors[position] if position < len(anchors) else None
    if before is not None and after is not None and after - before <= max(2, round(fps)):
        ratio = (frame_index - before) / (after - before)
        return [(np.asarray(left) * (1 - ratio) + np.asarray(right) * ratio).tolist()
                for left, right in zip(registered[before], registered[after])]
    nearest = min((item for item in (before, after) if item is not None),
                  key=lambda item: abs(item - frame_index))
    if abs(nearest - frame_index) <= max(1, round(fps / 5)):
        return registered[nearest]
    return None


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


def _replay_output_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1280 / max(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def replay_visual_enabled() -> bool:
    return os.getenv("CLIMB_REPLAY_VISUAL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def visual_input_version(result: dict, segment_reviews: dict | None = None) -> str:
    """Hash only frozen evidence; changing presentation never reruns inference."""
    evidence = {
        "reference": result.get("visual_reference"),
        "holds": result.get("holds") or [],
        "contacts": (result.get("attempt") or {}).get("contacts") or [],
        "hold_review_version": result.get("hold_review_version"),
        "segment_reviews": segment_reviews if segment_reviews is not None else result.get("visual_review_inputs") or {},
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def freeze_replay_reference(source: Path, result: dict) -> Path:
    """Persist the exact wall image used by normalized hold coordinates."""
    reference_path = source.parent / REPLAY_REFERENCE_FILENAME
    index = max(0, int((result.get("hold_evidence") or {}).get("reference_frame") or 0))
    cap = cv2.VideoCapture(str(source))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ValueError("无法读取与岩点坐标对应的墙面参考画面")
    finally:
        cap.release()
    temporary = reference_path.with_name(f".reference-{uuid.uuid4().hex}.png")
    try:
        # imencode/tofile also supports Unicode job directories on Windows.
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise ValueError("墙面参考画面保存失败")
        encoded.tofile(str(temporary))
        os.replace(temporary, reference_path)
    finally:
        temporary.unlink(missing_ok=True)
    result["visual_reference"] = {
        "schema_version": 1, "storage_name": REPLAY_REFERENCE_FILENAME,
        "source_frame_id": index, "width": frame.shape[1], "height": frame.shape[0],
        "source_sha256": ClimbReplayStore._sha256(source),
        "checksum_sha256": ClimbReplayStore._sha256(reference_path),
        "reference_sha256": ClimbReplayStore._sha256(reference_path),
        "coordinate_version": "normalized_reference_v1",
        "reference_transform": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "registration_valid": True,
    }
    return reference_path


def _visual_base_metadata(result: dict, *, fps: float, analysis_frames: int) -> dict:
    from core.replay_visual_renderer import VISUAL_VERSION
    duration = analysis_frames / fps
    return {
        "schema_version": 1, "status": "unavailable", "visual_version": VISUAL_VERSION,
        "input_version": visual_input_version(result),
        "analysis_frame_count": analysis_frames, "analysis_end_frame": analysis_frames,
        "analysis_duration_seconds": duration, "tail_start_seconds": duration,
        "start_seconds": duration, "tail_duration_seconds": 0,
        "total_duration_seconds": duration, "can_retry": False,
        "failure_reason": None, "message": "",
    }


def _validate_visual_video(path: Path, *, width: int, height: int, fps: float,
                           expected_frames: int, cancelled: Callable[[], bool] | None = None) -> None:
    """Decode the complete short tail before any final body encoding starts."""
    cap = cv2.VideoCapture(str(path))
    count = 0
    try:
        if not cap.isOpened() or abs(float(cap.get(cv2.CAP_PROP_FPS)) - fps) > .02:
            raise ValueError("线路回放的帧率不匹配")
        while True:
            if cancelled and cancelled():
                raise ReplayCancelled()
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (height, width):
                raise ValueError("线路回放的画幅不匹配")
            count += 1
    finally:
        cap.release()
    if count != expected_frames or count <= 0:
        raise ValueError("线路回放未完整生成")


def _prepare_visual_tail(result: dict, reference: Path, directory: Path, *,
                         size: tuple[int, int], fps: float,
                         cancelled: Callable[[], bool] | None = None,
                         progress: Callable[[str, int], None] | None = None) -> tuple[Path | None, dict]:
    from core.replay_visual_renderer import build_visual_manifest
    visual = dict(result["visual_replay"])
    try:
        if not reference.is_file():
            raise ValueError("历史复盘缺少墙面参考画面，无法制作线路回放")
        manifest = build_visual_manifest(_visual_render_evidence(result), result["visual_reference"], output_size=size, fps=fps)
        manifest_path, tail = directory / "manifest.json", directory / "tail.webm"
        _atomic_json(manifest_path, manifest)
        if progress:
            progress("正在制作线路回放", 0)
        metrics = run_visual_worker(reference, manifest_path, tail, directory / "metrics.json",
                                    cancelled=cancelled, progress=progress)
        _validate_visual_video(tail, width=size[0], height=size[1], fps=fps,
                               expected_frames=int(manifest["frame_count"]), cancelled=cancelled)
        visual.update(status="ready", can_retry=True, failure_reason=None, message="线路回放已生成",
                      tail_duration_seconds=int(manifest["frame_count"]) / fps,
                      tail_frame_count=int(manifest["frame_count"]),
                      total_duration_seconds=visual["analysis_duration_seconds"] + int(manifest["frame_count"]) / fps,
                      event_time_mapping=manifest.get("events") or [],
                      visual_parameters={key: manifest.get(key) for key in
                                         ("camera", "timeline", "width", "height", "fps", "duration_seconds")},
                      resource_metrics=metrics)
        return tail, visual
    except (ReplayCancelled, InterruptedError):
        raise ReplayCancelled()
    except Exception as exc:
        visual.update(status="failed", can_retry=reference.is_file(),
                      failure_reason=getattr(exc, "code", "visual_render_failed"),
                      resource_metrics=getattr(exc, "metrics", {}) or {},
                      message="线路回放暂未生成，可重试" if reference.is_file()
                      else "历史复盘的素材已不足，无法制作线路回放")
        return None, visual


def _visual_render_evidence(result: dict) -> dict:
    """Apply reviewed contact boundaries to presentation, preserving automatic evidence."""
    reviews = result.get("visual_review_inputs") or {}
    if not reviews:
        return result
    render_result = copy.deepcopy(result)
    contacts = render_result.get("attempt", {}).get("contacts") or []
    segments = {item["id"]: item for item in render_result.get("attempt", {}).get("segments") or []}
    hold_ids = {str(item.get("saved_object_id")): item["id"] for item in result.get("holds") or []
                if item.get("saved_object_id") is not None}
    fps = float((result.get("video") or {}).get("fps") or 1)
    for segment_id, review in reviews.items():
        original = segments.get(segment_id) or {}
        left, right = original.get("start_time_seconds", 0), original.get("end_time_seconds", 0)
        contacts = [item for item in contacts if not (
            item.get("limb") == original.get("limb") and
            left <= float(item.get("stable_time_seconds") if item.get("stable_time_seconds") is not None
                          else item.get("start_time_seconds") or 0) <= right)]
        for position, boundary in (("source", "start"), ("target", "end")):
            hold_id = hold_ids.get(str(review.get(f"{position}_route_hold_id")))
            if hold_id is None:
                raise ValueError("人工复核岩点没有可靠的墙面位置，暂不能制作线路回放")
            second = float(review[f"{boundary}_time_seconds"])
            contacts.append({"hold_id": hold_id, "limb": review["limb"],
                             "start_time_seconds": second, "end_time_seconds": second,
                             "start_source_frame": round(second * fps),
                             "end_source_frame": round(second * fps), "source": "user_confirmed"})
    render_result["attempt"]["contacts"] = contacts
    return render_result


def _append_visual_tail(writer: cv2.VideoWriter, tail_path: Path | None,
                        last_analysis_frame: np.ndarray, *, fps: float,
                        cancelled: Callable[[], bool] | None = None) -> int:
    if tail_path is None:
        return 0
    tail = cv2.VideoCapture(str(tail_path))
    written = 0
    try:
        while True:
            if cancelled and cancelled():
                raise ReplayCancelled()
            ok, frame = tail.read()
            if not ok:
                break
            if written < .8 * fps:
                position = min(1., written / max(1., .8 * fps - 1))
                alpha = position * position * (3 - 2 * position)
                frame = cv2.addWeighted(last_analysis_frame, 1 - alpha, frame, alpha, 0)
            writer.write(frame)
            written += 1
    finally:
        tail.release()
    return written


def render_replay_overlay_video(
    source: Path, target: Path, result: dict, *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    stage_progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Validate a short tail first, then encode the analysis body only once."""
    info = probe_video(source)
    if not replay_visual_enabled():
        result["visual_replay"] = _visual_base_metadata(result, fps=info.fps, analysis_frames=info.frame_count)
        result["visual_replay"].update(status="disabled", can_retry=False,
                                       message="线路回放尚未启用")
        try:
            with high_resource_slot(cancelled=cancelled, progress=stage_progress):
                return _render_replay_overlay_video_body(source, target, result,
                    progress=progress, cancelled=cancelled)
        except InterruptedError:
            raise ReplayCancelled()
    size = _replay_output_size(info.width, info.height)
    result["visual_replay"] = _visual_base_metadata(result, fps=info.fps, analysis_frames=info.frame_count)
    target.parent.mkdir(parents=True, exist_ok=True)
    reference_available = False
    try:
        reference = freeze_replay_reference(source, result)
        reference_available = True
        result["visual_replay"]["input_version"] = visual_input_version(result)
    except Exception:
        reference = source.parent / REPLAY_REFERENCE_FILENAME
        result["visual_replay"].update(status="unavailable", failure_reason="reference_unavailable",
                                        message="缺少可靠的墙面参考画面，已保留基础复盘")
    with tempfile.TemporaryDirectory(prefix=".visual-", dir=target.parent) as temporary:
        tail = None
        if reference_available:
            tail, result["visual_replay"] = _prepare_visual_tail(
                result, reference, Path(temporary), size=size, fps=info.fps,
                cancelled=cancelled, progress=stage_progress)
        try:
            with high_resource_slot(cancelled=cancelled, progress=stage_progress):
                return _render_replay_overlay_video_body(
                    source, target, result, progress=progress, cancelled=cancelled,
                    tail_path=tail, output_size=size)
        except InterruptedError:
            raise ReplayCancelled()


def render_replay_visual_from_overlay(source: Path, target: Path, result: dict, *,
                                      cancelled: Callable[[], bool] | None = None,
                                      progress: Callable[[str, int], None] | None = None) -> dict:
    """Historical retry reuses only the real body, never treating an old tail as evidence."""
    info = probe_video(source)
    analysis_frames = int((result.get("visual_replay") or {}).get("analysis_frame_count") or
                          (result.get("video") or {}).get("frame_count") or 0)
    if analysis_frames <= 0 or analysis_frames > info.frame_count:
        raise ValueError("历史复盘没有可靠的分析区间，无法重新制作线路回放")
    result["visual_replay"] = _visual_base_metadata(result, fps=info.fps, analysis_frames=analysis_frames)
    size = _replay_output_size(info.width, info.height)
    with tempfile.TemporaryDirectory(prefix=".visual-", dir=target.parent) as directory:
        temporary = Path(directory)
        tail, result["visual_replay"] = _prepare_visual_tail(
            result, source.parent / REPLAY_REFERENCE_FILENAME, temporary,
            size=size, fps=info.fps, cancelled=cancelled, progress=progress)
        if tail is None:
            return {}
        assembled = temporary / "assembled.webm"
        with high_resource_slot(cancelled=cancelled, progress=progress):
            cap = cv2.VideoCapture(str(source))
            writer = cv2.VideoWriter(str(assembled), cv2.VideoWriter_fourcc(*"VP80"), info.fps, size)
            try:
                if not cap.isOpened() or not writer.isOpened():
                    raise ValueError("无法重新读取或编码历史复盘")
                for index in range(analysis_frames):
                    if cancelled and cancelled():
                        raise ReplayCancelled()
                    ok, frame = cap.read()
                    if not ok:
                        raise ValueError("历史复盘的分析画面不完整")
                    frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                    writer.write(frame)
                tail_frames = _append_visual_tail(writer, tail, frame, fps=info.fps, cancelled=cancelled)
            finally:
                cap.release()
                writer.release()
            expected = analysis_frames + int(result["visual_replay"]["tail_frame_count"])
            if analysis_frames + tail_frames != expected:
                raise ValueError("线路回放未完整生成")
            _validate_visual_video(assembled, width=size[0], height=size[1], fps=info.fps,
                                   expected_frames=expected, cancelled=cancelled)
            os.replace(assembled, target)
        return {**(result.get("overlay") or {}), "frames_written": expected,
                "analysis_frame_count": analysis_frames, "tail_frame_count": tail_frames,
                "analysis_duration_seconds": analysis_frames / info.fps,
                "total_duration_seconds": expected / info.fps,
                "width": size[0], "height": size[1], "fps": info.fps}


def _render_replay_overlay_video_body(
    source: Path,
    target: Path,
    result: dict,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    tail_path: Path | None = None,
    output_size: tuple[int, int] | None = None,
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
    output_width, output_height = output_size or (width + width % 2, height + height % 2)
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
    reference_index = max(0, min(total - 1, int((result.get("hold_evidence") or {}).get("reference_frame") or 0)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, reference_index)
    reference_ok, reference = cap.read()
    if not reference_ok or reference is None:
        cap.release()
        writer.release()
        temporary.unlink(missing_ok=True)
        raise RuntimeError("无法读取墙面参考帧")
    registered_holds = _registered_hold_polygons(cap, reference, holds, fps, total, reference_index)
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
        "青色": "青色线路", "青": "青色线路", "cyan": "青色线路", "teal": "青色线路",
        "棕色": "棕色线路", "棕": "棕色线路", "brown": "棕色线路",
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
    line_width = max(1, round(min(output_width, output_height) / 420))
    tail_frames = 0
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
            frame_polygons = _interpolated_hold_polygons(registered_holds, frame_index, fps)
            for hold_index, hold in enumerate(holds):
                if frame_polygons is None:
                    break
                hold_id = int(hold.get("id") or 0)
                polygon = _scaled_hold_polygon(
                    {"polygon": frame_polygons[hold_index], "bbox": hold.get("bbox")}, x=video_x, y=video_y,
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
        if frame_index == total:
            tail_frames = _append_visual_tail(writer, tail_path, canvas, fps=fps, cancelled=cancelled)
            if tail_path is not None and tail_frames != int((result.get("visual_replay") or {}).get("tail_frame_count") or 0):
                raise RuntimeError("线路回放帧数发生变化，请重新生成")
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
    try:
        _validate_visual_video(temporary, width=output_width, height=output_height,
                               fps=fps, expected_frames=frame_index + tail_frames, cancelled=cancelled)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, target)
    return {
        "schema_version": 3,
        "container": "webm",
        "codec": "vp8",
        "frames_written": frame_index + tail_frames,
        "analysis_frame_count": frame_index,
        "analysis_duration_seconds": frame_index / fps,
        "tail_frame_count": tail_frames,
        "total_duration_seconds": (frame_index + tail_frames) / fps,
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
        route_color_sample: dict | None = None,
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
        self._active_hold_renders: set[str] = set()
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
        public = {key: value for key, value in job.items() if key not in {"input_path", "source_path", "saved_route_reference", "automatic_result", "coaching", "coaching_history", "template_video", "action_task", "action_result", "action_export", "action_export_media", "action_history", "action_revisions", "action_revision_audit"}}
        if job.get("result"):
            public["reviewed_segments"] = effective_segments(job)
            public["result"] = copy.deepcopy(job["result"])
            visual = public["result"].get("visual_replay")
            if visual:
                from core.replay_visual_renderer import VISUAL_VERSION
                outdated = (
                        visual.get("visual_version") != VISUAL_VERSION or
                        visual.get("input_version") != visual_input_version(job["result"], job.get("segment_reviews")))
                if outdated and float(visual.get("tail_duration_seconds") or 0) > 0:
                    visual["stale"] = True
                    if visual.get("status") == "ready":
                        visual.update(status="stale", message="复核内容或视觉版本已更新，请重新制作线路回放")
                media = job.get("media") or {}
                source_available = (media.get("source_video") or {}).get("status") == "available"
                reference_available = (media.get(REPLAY_REFERENCE_MEDIA_KIND) or {}).get("status") == "available"
                overlay_available = any((media.get(kind) or {}).get("status") == "available" for kind in
                                        (REPLAY_OVERLAY_MEDIA_KIND, REPLAY_REVIEWED_OVERLAY_MEDIA_KIND))
                visual["can_retry"] = replay_visual_enabled() and job.get("status") == "succeeded" and (source_available or (reference_available and overlay_available))
        return public

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
        route_color_sample: dict | None = None,
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
            "route_color_sample": route_color_sample,
            "original_name": original_name,
            "input_path": str(target),
            "media": {
                "source_video": {
                    "kind": "source_video", "status": "available",
                    "retention_mode": retention_mode, "delete_at": None,
                    "deleted_at": None, "size_bytes": info.size_bytes,
                    "checksum_sha256": checksum,
                    "content_type": "video/mp4",
                    "filename": f"{Path(original_name).stem or 'climb-replay'}.mp4",
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

    def create_pending(
        self, *, owner: str, route_id: str | None, route_color: str,
        source: Path, original_name: str, content_type: str, consent: dict,
        retention_mode: ReplayRetentionMode, trim_start_seconds: float = 0,
        trim_end_seconds: float | None = None, route_color_sample: dict | None = None,
        saved_route_reference: dict | None = None,
    ) -> dict:
        """Persist the upload and respond before any expensive video processing."""
        job_id, now = uuid.uuid4().hex, utcnow()
        directory = self.jobs / job_id
        directory.mkdir(parents=True, exist_ok=False)
        suffix = Path(original_name).suffix.lower()
        if suffix not in REPLAY_VIDEO_SUFFIXES:
            suffix = ".video"
        target = directory / f"source{suffix}"
        os.replace(source, target)
        size = target.stat().st_size
        job = {
            "id": job_id, "owner": owner, "route_id": route_id,
            "route_color": route_color, "original_name": original_name,
            "route_color_sample": route_color_sample,
            "saved_route_reference": saved_route_reference,
            "route_hold_ids": ([str(item["object_id"]) for item in saved_route_reference["members"]]
                               if saved_route_reference else []),
            "route_version_id": (hashlib.sha256(json.dumps({
                "board_id": saved_route_reference["board_id"],
                "member_ids": sorted(str(item["object_id"]) for item in saved_route_reference["members"]),
            }, sort_keys=True).encode("utf-8")).hexdigest()
                if saved_route_reference else None),
            "source_path": str(target), "input_path": None,
            "preparation": {"status": "queued", "trim_start_seconds": trim_start_seconds,
                            "trim_end_seconds": trim_end_seconds, "content_type": content_type},
            "media": {"source_video": {
                "kind": "source_video", "status": "available", "retention_mode": retention_mode,
                "delete_at": None, "deleted_at": None, "size_bytes": size,
                "checksum_sha256": self._sha256(target),
                "content_type": content_type or "application/octet-stream", "filename": original_name,
            }},
            "deletion": None, "video": None, "status": "queued", "stage": "等待整理视频",
            "progress": 0, "error": None, "error_code": None, "cancel_requested": False,
            "attempt": 1, "consent_history": [consent], "analysis_runs": [], "result": None,
            "created_at": now, "updated_at": now, "started_at": None, "finished_at": None,
        }
        _atomic_json(self._path(job_id), job)
        return self._public(job)

    def review_segment(self, job_id: str, owner: str, segment_id: str,
                       review: ReplaySegmentReview | None) -> dict:
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if job.get("status") != "succeeded":
                raise HTTPException(409, "分析完成后才能复核动作段")
            segments = (job.get("result") or {}).get("attempt", {}).get("segments") or []
            if not any(item.get("id") == segment_id for item in segments):
                raise HTTPException(404, "未找到动作段")
            media = job.get("media") or {}
            if review is not None and not any((media.get(kind) or {}).get("status") == "available"
                                              for kind in ("source_video", REPLAY_OVERLAY_MEDIA_KIND)):
                raise HTTPException(409, "视频已删除，无法复核动作时间")
            if review is not None:
                allowed = set(job.get("route_hold_ids") or [])
                if review.source_route_hold_id not in allowed or review.target_route_hold_id not in allowed:
                    raise HTTPException(422, "请选择这条已保存线路中的岩点")
                if review.source_route_hold_id == review.target_route_hold_id:
                    raise HTTPException(422, "起点和终点不能相同")
                duration = float((job.get("video") or {}).get("duration_seconds") or 0)
                if (not math.isfinite(review.start_time_seconds) or not math.isfinite(review.end_time_seconds)
                        or review.end_time_seconds <= review.start_time_seconds
                        or review.end_time_seconds > duration + .05):
                    raise HTTPException(422, "请在视频范围内标记有效的起止时间")
            reviews = dict(job.get("segment_reviews") or {})
            history = list(job.get("segment_review_history") or [])
            version = len(history) + 1
            if review is None:
                reviews.pop(segment_id, None)
                event = {"segment_id": segment_id, "version": version, "operation": "revert",
                         "reviewed_at": utcnow()}
            else:
                event = {**review.model_dump(), "segment_id": segment_id, "version": version,
                         "operation": "set", "reviewed_at": utcnow()}
                reviews[segment_id] = event
            history.append(event)
            job.update(segment_reviews=reviews, segment_review_history=history, updated_at=utcnow())
            result = copy.deepcopy(job.get("result") or {})
            result["visual_review_inputs"] = reviews
            if result.get("visual_replay"):
                result["visual_replay"].update(status="stale", stale=True, previous_status="stale",
                    message="复核内容已更新，请重新制作线路回放", failure_reason="input_changed")
            job["result"] = result
            _atomic_json(self._path(job_id), job)
            if getattr(self, "template_manager", None):
                self.template_manager.invalidate(job_id, reason="动作复核已更新，请重新制作模板视频。")
            return self._public(job)

    def promote_hold_candidate(self, job_id: str, owner: str, candidate_index: int) -> dict:
        """Confirm one repeated native-mask candidate and recompute from stored poses only."""
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if job.get("status") != "succeeded":
                raise HTTPException(409, "分析完成后才能补入岩点")
            if job.get("segment_reviews"):
                raise HTTPException(409, "已有动作段人工复核，请先撤销复核再补入岩点")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "任务正在删除")
            result = copy.deepcopy(job.get("result") or {})
            candidates = result.get("hold_candidates") or []
            if candidate_index < 0 or candidate_index >= len(candidates):
                raise HTTPException(404, "未找到候选岩点")
            candidate = candidates[candidate_index]
            if (candidate.get("contour_source") != "climbing_model_native_mask"
                    or int(candidate.get("appearances") or 0) < 2
                    or len(candidate.get("polygon") or []) < 3):
                raise HTTPException(422, "这个候选缺少稳定的模型轮廓，不能直接补入")
            source_item = (job.get("media") or {}).get("source_video") or {}
            if source_item.get("status") != "available":
                raise HTTPException(409, "原视频已删除，无法重算接触和叠加视频")
            source = self._media_path(job_id, job, "source_video")
            if not source.is_file():
                raise HTTPException(409, "原视频文件不存在")
            holds = result.get("holds") or []
            if any(box_iou(candidate["bbox"], hold["bbox"]) > .45 for hold in holds):
                raise HTTPException(409, "该岩点已在线路中")
            version = len(job.get("hold_review_history") or []) + 1
            hold = copy.deepcopy(candidate)
            hold["id"] = max((int(item.get("id") or 0) for item in holds), default=0) + 1
            hold["identity_source"] = "user_confirmed_video_candidate"
            hold["route_candidate"] = True
            hold["route_candidate_reason"] = "user_confirmed"
            hold["review_version"] = version
            result["holds"] = [*holds, hold]
            result["hold_candidates"] = [item for index, item in enumerate(candidates)
                                         if index != candidate_index and box_iou(item["bbox"], hold["bbox"]) < .45]
            event = {"version": version, "candidate_index": candidate_index, "hold_id": hold["id"],
                     "bbox": hold["bbox"], "color_group": hold.get("color_group"),
                     "reviewed_at": utcnow(), "operation": "promote_candidate"}
        return self._save_recomputed_holds(job_id, job, result, source, event)

    def _clicked_hold_proposal(self, job_id: str, owner: str, point: ReplayHoldPoint) -> tuple:
        """Build a read-only proposal; caller holds the store lock."""
        job = self._read(job_id)
        if job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        if (job.get("deletion") or {}).get("state") == "queued":
            raise HTTPException(409, "这条复盘正在删除，无法补入岩点。")
        if job.get("status") != "succeeded":
            raise HTTPException(409, "分析完成后才能补入岩点。")
        if job.get("segment_reviews"):
            raise HTTPException(409, "已有动作段人工复核。请先撤销动作段复核，再补入岩点。")
        source_item = (job.get("media") or {}).get("source_video") or {}
        if source_item.get("status") != "available":
            raise HTTPException(409, "原视频已删除，无法补入岩点。")
        source = self._media_path(job_id, job, "source_video")
        if not source.is_file():
            raise HTTPException(409, "原视频文件不存在，无法补入岩点。")
        video = VideoInfo(**job["video"])
        if point.time_seconds > video.duration_seconds + .1:
            raise HTTPException(422, "所选画面超出视频时长，请重新选择。")
        result = copy.deepcopy(job.get("result") or {})
        reference_index = int((result.get("hold_evidence") or {}).get("reference_frame") or 0)
        frame_index = min(video.frame_count - 1, round(point.time_seconds * video.fps))
        capture = cv2.VideoCapture(str(source))
        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            capture.set(cv2.CAP_PROP_POS_FRAMES, reference_index)
            reference_ok, reference = capture.read()
        finally:
            capture.release()
        if not ok or frame is None or not reference_ok or reference is None:
            raise HTTPException(422, "无法读取所选画面，请换一帧再试。")
        polygon = (boxed_hold_polygon(frame, point.region_xyxy)
                   if point.region_xyxy is not None else clicked_hold_polygon(frame, point.point_xy))
        if frame_index == reference_index:
            matrix = np.eye(3)
        else:
            matrix, _ = align_to_reference(frame, reference)
        if matrix is None:
            raise HTTPException(422, "这帧画面无法对齐墙面，请换一帧再补点。")
        mapped = transform_polygon(polygon, matrix, reference.shape[1], reference.shape[0])
        if len(mapped) < 3:
            raise HTTPException(422, "岩点轮廓无法映射到墙面，请换一帧再试。")
        mapped, frame_support = _multi_frame_clicked_polygon(
            source, video, frame_index, reference_index, reference, mapped, point.region_xyxy)
        bbox = polygon_bbox(mapped)
        holds = result.get("holds") or []
        if any(box_iou(bbox, hold["bbox"]) > .3 for hold in holds):
            raise HTTPException(409, "这个位置已有岩点，无需重复补入。")
        source_polygon = transform_polygon(
            [[x * video.width, y * video.height] for x, y in mapped],
            np.linalg.inv(matrix), video.width, video.height)
        return job, result, source, frame_index, source_polygon, mapped, bbox, frame_support

    def preview_hold_at_point(self, job_id: str, owner: str, point: ReplayHoldPoint) -> dict:
        with self._lock:
            _, _, _, frame_index, source_polygon, mapped, bbox, support = self._clicked_hold_proposal(
                job_id, owner, point)
            return {"frame_index": frame_index, "source_polygon": source_polygon,
                    "reference_polygon": mapped, "bbox": bbox, "supporting_frames": support}

    def add_hold_at_point(self, job_id: str, owner: str, point: ReplayHoldPoint) -> dict:
        """Trace a clicked hold in the source frame and recompute from stored poses."""
        with self._lock:
            job, result, source, frame_index, _, mapped, bbox, support = self._clicked_hold_proposal(
                job_id, owner, point)
            holds = result.get("holds") or []
            version = len(job.get("hold_review_history") or []) + 1
            hold = {"id": max((int(item.get("id") or 0) for item in holds), default=0) + 1,
                    "bbox": bbox, "polygon": mapped, "score": 1.0,
                    "route_candidate": True, "route_candidate_reason": "user_confirmed",
                    "identity_source": "user_confirmed_video_click",
                    "contour_source": (
                        "user_box_local_multiframe" if support > 1 else "user_box_local_colour"
                    ) if point.region_xyxy is not None else (
                        "user_click_local_multiframe" if support > 1 else "user_click_local_colour"
                    ),
                    "supporting_frames": support,
                    "source_frame": frame_index, "review_version": version}
            result["holds"] = [*holds, hold]
            result["hold_candidates"] = [candidate for candidate in result.get("hold_candidates") or []
                                         if box_iou(candidate["bbox"], bbox) < .3]
            event = {"version": version, "operation": "add_hold_at_point",
                     "hold_id": hold["id"], "bbox": bbox, "point_xy": point.point_xy,
                     "region_xyxy": point.region_xyxy,
                     "time_seconds": point.time_seconds, "reviewed_at": utcnow()}
        return self._save_recomputed_holds(job_id, job, result, source, event)

    def undo_clicked_hold(self, job_id: str, owner: str, review_version: int | None = None) -> dict:
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if job.get("status") != "succeeded" or (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘当前不能撤销补点。")
            if job.get("segment_reviews"):
                raise HTTPException(409, "已有动作段人工复核。请先撤销动作段复核，再修改岩点。")
            result = copy.deepcopy(job.get("result") or {})
            clicked = [hold for hold in result.get("holds") or []
                       if hold.get("identity_source") in {"user_confirmed_video_click", "user_confirmed_video_candidate"}
                       and (review_version is None or hold.get("review_version") == review_version)]
            if not clicked:
                raise HTTPException(409, "这次补点已撤销或不存在，请刷新补点记录。")
            hold = max(clicked, key=lambda item: int(item.get("review_version") or 0))
            source = self._media_path(job_id, job, "source_video")
            if (job.get("media") or {}).get("source_video", {}).get("status") != "available" or not source.is_file():
                raise HTTPException(409, "原视频已删除，无法重算撤销后的复盘。")
            result["holds"] = [item for item in result["holds"] if item["id"] != hold["id"]]
            event = {"version": len(job.get("hold_review_history") or []) + 1,
                     "operation": "undo_add_hold_at_point" if hold.get("identity_source") == "user_confirmed_video_click" else "undo_promote_candidate",
                     "hold_id": hold["id"],
                     "target_review_version": hold["review_version"],
                     "reviewed_at": utcnow()}
        return self._save_recomputed_holds(job_id, job, result, source, event)

    def undo_last_clicked_hold(self, job_id: str, owner: str) -> dict:
        return self.undo_clicked_hold(job_id, owner)

    def refine_sampled_holds(self, job_id: str, owner: str) -> dict:
        """Clean an existing sampled-colour job without any new pose-provider calls."""
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘正在删除，无法清理岩点。请选择其他记录。")
            if job.get("status") != "succeeded":
                raise HTTPException(409, "这条复盘尚未完成，完成后才能清理岩点。")
            history = job.get("hold_review_history") or []
            result = copy.deepcopy(job.get("result") or {})
            if (history and history[0].get("operation") == "refine_sampled_route"
                    and (result.get("hold_refinement") or {}).get("method") == "local_sampled_colour_geometry"):
                return self._public(job)
            if job.get("segment_reviews"):
                raise HTTPException(409, "已有动作段人工复核。请先撤销动作段复核，再清理岩点。")
            if history:
                raise HTTPException(409, "已有人工补入的岩点，不能自动覆盖。请查看当前修订结果。")
            sample = (result.get("route") or {}).get("color_sample") or {}
            if (result.get("hold_evidence") or {}).get("selection") != "color_candidates_need_review":
                raise HTTPException(409, "这条复盘已经是精简结果，无需重复清理。")
            source_item = (job.get("media") or {}).get("source_video") or {}
            if source_item.get("status") != "available":
                raise HTTPException(409, "原视频已删除，无法重算接触和叠加视频")
            source = self._media_path(job_id, job, "source_video")
            if not source.is_file():
                raise HTTPException(409, "原视频文件不存在")
            if sample.get("rgb"):
                sample_lab = cv2.cvtColor(np.uint8([[sample["rgb"]]]), cv2.COLOR_RGB2LAB)[0, 0]
                sample_group = lab_color_name(sample_lab, twelve_colors=True)
            else:
                sample_group = AliyunReplayAnalyzer._route_colour(str((result.get("route") or {}).get("color") or job.get("route_color") or ""))
            original_holds = result.get("holds") or []
            all_holds = [*original_holds, *(result.get("hold_candidates") or [])]
            selected, candidates, evidence = select_sampled_route_holds(
                all_holds, sample_group=sample_group,
                minimum_appearances=2 if (result.get("hold_evidence") or {}).get("frames_aligned", 0) >= 2 else 1,
            )
            if not selected:
                raise HTTPException(409, "清理后没有可信岩点，已保留原结果")
            selected.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2), hold["bbox"][0]))
            for index, hold in enumerate(selected, 1):
                hold["id"] = index
            for candidate in candidates:
                candidate.pop("id", None)
            result["holds"] = selected
            result["hold_candidates"] = candidates
            result["hold_evidence"].update(selection="minimal_colour_geometry_needs_review",
                                           sampled_selection=evidence)
            result["hold_refinement"] = {"before": len(original_holds), "after": len(selected),
                                         "demoted": len(original_holds) - sum(
                                             any(box_iou(old["bbox"], kept["bbox"]) >= .7 for kept in selected)
                                             for old in original_holds),
                                         "method": "local_sampled_colour_geometry"}
            event = {"version": 1, "operation": "refine_sampled_route",
                     "before": len(original_holds), "after": len(selected),
                     "reviewed_at": utcnow()}
        return self._save_recomputed_holds(job_id, job, result, source, event)

    def _save_recomputed_holds(self, job_id: str, job: dict, result: dict,
                               source: Path, event: dict) -> dict:
        """Reserve briefly, render without the store lock, then compare and commit."""
        with self._lock:
            current = self._read(job_id)
            if job_id in self._active_hold_renders:
                raise HTTPException(409, "岩点复盘正在更新，请稍后再试")
            if visual_input_version(current.get("result") or {}, current.get("segment_reviews")) != visual_input_version(job.get("result") or {}, job.get("segment_reviews")):
                raise HTTPException(409, "复盘内容已更新，请刷新后重试")
            if (current.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘正在删除")
            if (current.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
                raise HTTPException(409, "线路回放正在制作，请完成或取消后再修改岩点")
            if current.get("cancel_requested"):
                self.update(job_id, cancel_requested=False)
            self._active_hold_renders.add(job_id)
        try:
            return self._compute_and_save_holds(job_id, job, result, source, event)
        finally:
            with self._lock:
                self._active_hold_renders.discard(job_id)

    def _compute_and_save_holds(self, job_id: str, job: dict, result: dict,
                               source: Path, event: dict) -> dict:
        version = int(event["version"])
        video = VideoInfo(**job["video"])
        reference_index = int((result.get("hold_evidence") or {}).get("reference_frame") or 0)
        samples = result.get("pose_samples") or []
        if not samples:
            raise HTTPException(409, "缺少已保存的姿态采样，不能安全重算")
        cap = cv2.VideoCapture(str(source))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, reference_index)
            ok, reference = cap.read()
            if not ok or reference is None:
                raise HTTPException(409, "无法读取墙面参考帧")
            records = []
            for sample in samples:
                source_frame = int(sample.get("source_frame_id") or 0)
                record = {
                    "frame_id": int(sample.get("sample_index") or 0),
                    "source_frame_id": source_frame,
                    "kpts_xy": sample.get("kpts_xy") or [[0.0, 0.0] for _ in range(17)],
                    "kpts_score": sample.get("kpts_score") or [0.0] * 17,
                }
                if not sample.get("observed") or sample.get("wall_alignment") == "failed":
                    records.append(align_pose_record(record, None, video.width, video.height))
                    continue
                if source_frame == reference_index:
                    matrix = np.eye(3)
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                    read_ok, frame = cap.read()
                    matrix = align_to_reference(frame, reference)[0] if read_ok and frame is not None else None
                records.append(align_pose_record(record, matrix, video.width, video.height))
        finally:
            cap.release()
        sample_fps = float((result.get("analysis") or {}).get("sampling", {}).get("effective_fps") or 1)
        attempt = AliyunReplayAnalyzer._contacts(records, result["holds"], sample_fps)
        add_attempt_source_times(attempt, samples, video)
        attempt["action_steps"] = build_action_steps(attempt.get("contacts") or [])
        result["attempt"] = attempt
        attempt["segments"] = build_segments(result)
        result["hold_review_version"] = version
        warning = ("取色线路已按颜色族、轮廓大小和多帧证据清理自动岩点；其他候选仍可人工补入。"
                   if event["operation"] == "refine_sampled_route" else
                   "人工补入的模型候选岩点已参与接触重算；接触仍需结合原视频复核。")
        result["warnings"] = [*(result.get("warnings") or []), warning]
        target = self._path(job_id).parent / f"overlay-review-{version}.webm"

        def cancelled() -> bool:
            try:
                current = self.get(job_id, private=True)
            except HTTPException:
                return True
            return bool(current.get("cancel_requested") or
                        (current.get("deletion") or {}).get("state") == "queued" or
                        visual_input_version(current.get("result") or {}, current.get("segment_reviews")) !=
                        visual_input_version(job.get("result") or {}, job.get("segment_reviews")))

        try:
            options = {"cancelled": cancelled} if replay_visual_enabled() else {}
            result["overlay"] = render_replay_overlay_video(source, target, result, **options)
            with self._lock:
                current = self._read(job_id)
                if cancelled():
                    raise HTTPException(409, "复盘内容已更新或制作已取消，已保留原版本")
                media = dict(current.get("media") or {})
                media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND] = {
                    "kind": REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, "status": "available",
                    "storage_name": target.name, "retention_mode": REPLAY_RETENTION_KEEP,
                    "delete_at": None, "deleted_at": None, "size_bytes": target.stat().st_size,
                    "checksum_sha256": self._sha256(target), "content_type": "video/webm",
                    "filename": f"{Path(job.get('original_name') or 'climb-replay').stem}-岩点修订复盘.webm",
                    "generated_at": utcnow(),
                    "visual_replay": copy.deepcopy(result.get("visual_replay")),
                }
                self._add_reference_media(media, result, source.parent)
                current.update(result=result, media=media,
                               automatic_result=current.get("automatic_result") or current.get("result"),
                               hold_review_history=[*(current.get("hold_review_history") or []), event],
                               updated_at=utcnow())
                _atomic_json(self._path(job_id), current)
                if getattr(self, "template_manager", None):
                    self.template_manager.invalidate(job_id, reason="岩点与接触证据已更新，请重新制作模板视频。")
                return self._public(current)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def finish_preparation(self, job_id: str, path: Path, info: VideoInfo) -> dict:
        job = self.get(job_id, private=True)
        directory = self._path(job_id).parent
        target = directory / "input.mp4"
        os.replace(path, target)
        media = dict(job["media"])
        source = dict(media["source_video"])
        source.update(size_bytes=info.size_bytes, checksum_sha256=self._sha256(target),
                      content_type="video/mp4",
                      filename=f"{Path(job['original_name']).stem or 'climb-replay'}.mp4")
        media["source_video"] = source
        preparation = dict(job["preparation"])
        preparation["status"] = "completed"
        raw = Path(job["source_path"])
        updated = self.update(job_id, input_path=str(target), source_path=None,
                              video=asdict(info), media=media, preparation=preparation,
                              stage="视频已整理，准备分析", progress=12)
        try:
            raw.unlink(missing_ok=True)
        except OSError:
            # A later cleanup pass removes the redundant upload after a sharing lock clears.
            pass
        return updated

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
            raw_path = job.get("source_path") or job.get("input_path")
            if not raw_path:
                raise HTTPException(404, "原视频已删除")
            path = Path(raw_path).resolve()
            expected_name = path.name
            if expected_name != "input.mp4" and expected_name not in {
                    f"source{suffix}" for suffix in (*REPLAY_VIDEO_SUFFIXES, ".video")}:
                raise RuntimeError("媒体文件名未通过安全校验")
        elif media_kind == REPLAY_OVERLAY_MEDIA_KIND:
            path = (directory / REPLAY_OVERLAY_FILENAME).resolve()
            expected_name = REPLAY_OVERLAY_FILENAME
        elif media_kind == REPLAY_REVIEWED_OVERLAY_MEDIA_KIND:
            expected_name = str(((job.get("media") or {}).get(media_kind) or {}).get("storage_name") or "")
            if not re.fullmatch(r"overlay-(?:review-[1-9][0-9]*|visual-[a-f0-9]{32})\.webm", expected_name):
                raise RuntimeError("修订视频文件名未通过安全校验")
            path = (directory / expected_name).resolve()
        elif media_kind == REPLAY_REFERENCE_MEDIA_KIND:
            expected_name = REPLAY_REFERENCE_FILENAME
            path = (directory / expected_name).resolve()
        else:
            raise HTTPException(404, "未找到可访问的媒体")
        if (directory.parent != self.jobs.resolve() or path.parent != directory
                or path.name != expected_name):
            raise RuntimeError("媒体路径未通过安全校验")
        return path

    @staticmethod
    def _add_reference_media(media: dict, result: dict, directory: Path) -> None:
        path = directory / REPLAY_REFERENCE_FILENAME
        reference = result.get("visual_reference")
        if not reference or not path.is_file():
            return
        source = media.get("source_video") or {}
        media[REPLAY_REFERENCE_MEDIA_KIND] = {
            "kind": REPLAY_REFERENCE_MEDIA_KIND, "status": "available",
            "retention_mode": source.get("retention_mode", REPLAY_RETENTION_DELETE),
            "delete_at": source.get("delete_at"), "deleted_at": None,
            "size_bytes": path.stat().st_size, "checksum_sha256": reference["checksum_sha256"],
            "content_type": "image/png", "filename": "线路回放参考画面.png",
            "generated_at": utcnow(),
        }

    def register_overlay(self, job_id: str, result: dict | None = None) -> dict:
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
            "visual_replay": copy.deepcopy((result or job.get("result") or {}).get("visual_replay")),
        }
        self._add_reference_media(media, result or job.get("result") or {}, path.parent)
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
        if REPLAY_REFERENCE_MEDIA_KIND in media:
            media[REPLAY_REFERENCE_MEDIA_KIND] = {**media[REPLAY_REFERENCE_MEDIA_KIND], "delete_at": source["delete_at"]}
        return self._public(self.update(job_id, media=media))

    def delete_media(self, job_id: str, owner: str | None, media_kind: str) -> dict:
        actions = getattr(self, "action_manager", None)
        if actions and media_kind == "source_video":
            with self._lock:
                self.get(job_id, owner, private=True)
                actions.invalidate(job_id)
            if not actions.wait_idle(job_id, timeout=2):
                raise HTTPException(409, "正在停止复盘并释放原片，请稍后再删除。")
        template = getattr(self, "template_manager", None)
        if template and media_kind == "source_video":
            with self._lock:
                self.get(job_id, owner, private=True)
                template.invalidate(job_id, media_kind=media_kind)
            # Release the store lock before waiting: the renderer needs it to
            # observe cancellation and close its source reader on Windows.
            if not template.wait_idle(job_id, timeout=2):
                raise HTTPException(409, "模板视频已停止制作，正在释放原视频，请稍后再删除。")
        with self._lock:
            return self._delete_media_locked(job_id, owner, media_kind)

    def _delete_media_locked(self, job_id: str, owner: str | None, media_kind: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job_id in self._active_hold_renders or job.get("status") in {"queued", "running"} or (job.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
            raise HTTPException(409, "分析进行中，请先取消任务再删除媒体")
        media = dict(job.get("media") or {})
        item = dict(media.get(media_kind) or {})
        if not item or item.get("status") == "deleted":
            raise HTTPException(404, "媒体已删除或不存在")
        if getattr(self, "coaching_manager", None):
            self.coaching_manager.invalidate(job_id, media_kind=media_kind)
        path = self._media_path(job_id, job, media_kind)
        path.unlink(missing_ok=True)
        if media_kind == "source_video":
            directory = self._path(job_id).parent
            for suffix in (*REPLAY_VIDEO_SUFFIXES, ".video"):
                (directory / f"source{suffix}").unlink(missing_ok=True)
            (directory / REPLAY_REFERENCE_FILENAME).unlink(missing_ok=True)
            if REPLAY_REFERENCE_MEDIA_KIND in media:
                media[REPLAY_REFERENCE_MEDIA_KIND] = {**media[REPLAY_REFERENCE_MEDIA_KIND],
                    "status": "deleted", "deleted_at": utcnow(), "delete_at": None}
        item.update(status="deleted", deleted_at=utcnow(), delete_at=None)
        media[media_kind] = item
        changes = {"media": media}
        if media_kind == "source_video":
            changes["input_path"] = None
            changes["source_path"] = None
        return self._public(self.update(job_id, **changes))

    def cleanup_due_media(self) -> list[str]:
        deleted = []
        now = datetime.now(timezone.utc)
        for path in self.jobs.glob("*/job.json"):
            try:
                with self._lock:
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
                with self._lock:
                    job = self._read(job["id"])
                    overlay = (job.get("media") or {}).get(REPLAY_OVERLAY_MEDIA_KIND) or {}
                    if overlay.get("status") == "cleanup_pending":
                        self.discard_overlay(job["id"])
                    if (job.get("preparation") or {}).get("status") == "completed":
                        for suffix in (*REPLAY_VIDEO_SUFFIXES, ".video"):
                            (path.parent / f"source{suffix}").unlink(missing_ok=True)
                    if job.get("status") in {"failed", "cancelled", "succeeded"} and job["id"] not in self._active_hold_renders:
                        (path.parent / ".preparing.mp4").unlink(missing_ok=True)
                        if (job.get("result") or {}).get("visual_replay", {}).get("status") not in {"queued", "running"}:
                            for temporary in path.parent.glob(".visual-*"):
                                if temporary.is_dir() and temporary.parent.resolve() == path.parent.resolve():
                                    shutil.rmtree(temporary)
                            current = ((job.get("media") or {}).get(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND) or {}).get("storage_name")
                            for obsolete in path.parent.glob("overlay-visual-*.webm"):
                                if obsolete.name != current:
                                    obsolete.unlink(missing_ok=True)
            except (OSError, TypeError, ValueError, json.JSONDecodeError, HTTPException):
                continue
        return deleted

    def request_delete(self, job_id: str, owner: str) -> dict:
        with self._lock:
            return self._request_delete_locked(job_id, owner)

    def _request_delete_locked(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if getattr(self, "coaching_manager", None):
            self.coaching_manager.invalidate(job_id)
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
        with self._lock:
            return self._get_deletion_locked(job_id, owner)

    def _get_deletion_locked(self, job_id: str, owner: str) -> dict:
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
        actions = getattr(self, "action_manager", None)
        if actions:
            actions.invalidate(job_id)
            if not actions.wait_idle(job_id, timeout=2):
                receipt = json.loads(self._deletion_path(job_id).read_text(encoding="utf-8"))
                return {key: value for key, value in receipt.items() if key != "owner"}
        # Share the report commit lock: late cloud results must not recreate a deleted job.
        template = getattr(self, "template_manager", None)
        if template and not template.wait_idle(job_id, timeout=2):
            # Leave deletion queued until the cancelled local renderer releases its files.
            receipt = json.loads(self._deletion_path(job_id).read_text(encoding="utf-8"))
            return {key: value for key, value in receipt.items() if key != "owner"}
        with self._lock:
            return self._process_delete_locked(job_id)

    def _process_delete_locked(self, job_id: str) -> dict:
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
        with self._lock:
            self._fail_deletion_locked(job_id)

    def _fail_deletion_locked(self, job_id: str) -> None:
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
            visual = (item.get("result") or {}).get("visual_replay") or {}
            if visual.get("status") in {"queued", "running"}:
                visual.update(status="failed", failure_reason="service_restarted",
                              message="服务重启后线路回放已停止，原复盘仍可播放")
                item.update(cancel_requested=False, stage="分析完成", updated_at=utcnow())
                _atomic_json(path, item)
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
                (path.parent / ".preparing.mp4").unlink(missing_ok=True)

    def cancel(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job_id in self._active_hold_renders:
            return self._public(self.update(job_id, cancel_requested=True, stage="正在停止更新复盘"))
        if (job.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
            return self._public(self.update(job_id, cancel_requested=True, stage="正在停止制作线路回放"))
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

    def request_visual_retry(self, job_id: str, owner: str) -> dict:
        with self._lock:
            job = self.get(job_id, owner, private=True)
            if not replay_visual_enabled():
                raise HTTPException(409, "线路回放尚未启用，请保留基础复盘")
            if job_id in self._active_hold_renders:
                raise HTTPException(409, "岩点复盘正在更新，请稍后再试")
            if job.get("status") != "succeeded" or not job.get("result"):
                raise HTTPException(409, "基础复盘完成后才能制作线路回放")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘正在删除")
            result = copy.deepcopy(job["result"])
            visual = dict((self._public(job).get("result") or {}).get("visual_replay") or {})
            if visual.get("status") in {"queued", "running"}:
                return self._public(job)
            media = job.get("media") or {}
            source_available = (media.get("source_video") or {}).get("status") == "available"
            reference_available = ((media.get(REPLAY_REFERENCE_MEDIA_KIND) or {}).get("status") == "available"
                                   and (self._path(job_id).parent / REPLAY_REFERENCE_FILENAME).is_file())
            overlay_available = any((media.get(kind) or {}).get("status") == "available" for kind in
                                    (REPLAY_OVERLAY_MEDIA_KIND, REPLAY_REVIEWED_OVERLAY_MEDIA_KIND))
            if not source_available and not (reference_available and overlay_available):
                visual.update(status="unavailable", can_retry=False, failure_reason="materials_unavailable",
                              message="历史复盘的素材已不足，无法重新制作线路回放")
                result["visual_replay"] = visual
                return self._public(self.update(job_id, result=result))
            result["visual_review_inputs"] = job.get("segment_reviews") or {}
            visual.update(status="queued", previous_status=visual.get("status"), can_retry=True,
                          stale=bool(visual.get("stale") or visual.get("status") == "stale"),
                          message="等待制作线路回放", failure_reason=None)
            result["visual_replay"] = visual
            return self._public(self.update(job_id, result=result, cancel_requested=False,
                                            stage="等待制作线路回放"))

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
        with self._lock:
            return self._withdraw_consent_locked(job_id, owner)

    def _withdraw_consent_locked(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if getattr(self, "action_manager", None):
            self.action_manager.invalidate(job_id)
        if getattr(self, "coaching_manager", None):
            self.coaching_manager.invalidate(job_id, revoked=True)
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
        self.video_limits = VideoLimits()
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=8)
        self._queued: set[tuple[str, str]] = set()
        self._queue_lock = threading.Lock()
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

    def enqueue_visual(self, job_id: str) -> None:
        self._enqueue("visual", job_id)

    def _enqueue(self, action: str, job_id: str) -> None:
        item = (action, job_id)
        with self._queue_lock:
            if item not in self._queued:
                self._queued.add(item)
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    # Durable job records remain the bounded recovery source.
                    self._queued.discard(item)

    def ensure_capacity(self) -> None:
        pending = 0
        for path in self.store.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") in {"queued", "running"} or (item.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
                pending += 1
        if pending >= 8:
            raise HTTPException(429, "复盘处理队列已满，请稍后再试")

    def _refill_queue(self) -> None:
        candidates = [("delete", job_id) for job_id in self.store.pending_deletions()]
        candidates.extend(("analysis", job_id) for job_id in self.store.queued())
        for path in self.store.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (item.get("result") or {}).get("visual_replay", {}).get("status") == "queued":
                candidates.append(("visual", item["id"]))
        for action, job_id in candidates:
            if self._queue.full():
                break
            self._enqueue(action, job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            with self._queue_lock:
                self._queued.discard(item)
            action, job_id = item
            try:
                if action == "delete":
                    self.store.process_delete(job_id)
                elif action == "visual":
                    self._execute_visual(job_id)
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
                self._refill_queue()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self._cleanup_interval_seconds):
            try:
                self.store.cleanup_due_media()
            except Exception:
                # One malformed legacy record must not stop future cleanup passes.
                continue

    def _execute_visual(self, job_id: str) -> None:
        """A separate local-only retry leaves the successful analysis and media intact."""
        job = self.store.get(job_id, private=True)
        if job.get("status") != "succeeded" or (job.get("result") or {}).get("visual_replay", {}).get("status") != "queued":
            return
        result = copy.deepcopy(job["result"])
        previous = dict(result["visual_replay"])
        expected_version = visual_input_version(result, job.get("segment_reviews"))
        target = self.store._path(job_id).parent / f"overlay-visual-{uuid.uuid4().hex}.webm"

        def cancelled() -> bool:
            try:
                current = self.store.get(job_id, private=True)
            except HTTPException:
                return True
            return bool(current.get("cancel_requested") or self._stop.is_set() or
                        (current.get("deletion") or {}).get("state") == "queued" or
                        visual_input_version(current.get("result") or {}, current.get("segment_reviews")) != expected_version)

        def progress(stage: str, value: int) -> None:
            with self.store._lock:
                if cancelled():
                    raise ReplayCancelled()
                current = self.store.get(job_id, private=True)
                ongoing = copy.deepcopy(current["result"])
                ongoing["visual_replay"].update(status="running", message=stage, progress=max(0, min(99, value)))
                self.store.update(job_id, result=ongoing, stage=stage)

        try:
            progress("正在制作线路回放", 0)
            media = job.get("media") or {}
            if (media.get("source_video") or {}).get("status") == "available":
                source = self.store._media_path(job_id, job, "source_video")
                overlay = render_replay_overlay_video(source, target, result,
                    cancelled=cancelled, stage_progress=progress,
                    progress=lambda value: progress("正在生成可播放的完整复盘", value))
            else:
                kind = next((kind for kind in (REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, REPLAY_OVERLAY_MEDIA_KIND)
                             if (media.get(kind) or {}).get("status") == "available"), None)
                if kind is None:
                    raise ValueError("没有仍可读取的复盘素材")
                source = self.store._media_path(job_id, job, kind)
                overlay = render_replay_visual_from_overlay(source, target, result,
                                                            cancelled=cancelled, progress=progress)
            if result["visual_replay"].get("status") != "ready":
                raise ValueError(result["visual_replay"].get("message") or "线路回放暂未生成")
            if cancelled():
                raise ReplayCancelled()
            with self.store._lock:
                current = self.store.get(job_id, private=True)
                if cancelled():
                    raise ReplayCancelled()
                media = dict(current.get("media") or {})
                old_item = media.get(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND) or {}
                old_path = (self.store._media_path(job_id, current, REPLAY_REVIEWED_OVERLAY_MEDIA_KIND)
                            if old_item.get("status") == "available" else None)
                media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND] = {
                    "kind": REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, "status": "available", "storage_name": target.name,
                    "retention_mode": REPLAY_RETENTION_KEEP, "delete_at": None, "deleted_at": None,
                    "size_bytes": target.stat().st_size, "checksum_sha256": self.store._sha256(target),
                    "content_type": "video/webm", "filename": "线路回放复盘.webm", "generated_at": utcnow(),
                    "visual_replay": copy.deepcopy(result.get("visual_replay")),
                }
                self.store._add_reference_media(media, result, target.parent)
                result["overlay"] = overlay
                result["visual_replay"].update(stale=False, progress=100,
                    input_version=visual_input_version(result, current.get("segment_reviews")))
                self.store.update(job_id, result=result, media=media, cancel_requested=False, stage="分析完成")
                if old_path is not None and old_path != target:
                    try:
                        old_path.unlink(missing_ok=True)
                    except OSError:
                        pass  # A later cleanup pass reclaims obsolete media.
        except Exception as exc:
            target.unlink(missing_ok=True)
            with self.store._lock:
                try:
                    current = self.store.get(job_id, private=True)
                except HTTPException:
                    return
                if visual_input_version(current.get("result") or {}, current.get("segment_reviews")) != expected_version:
                    return
                fallback = copy.deepcopy(current["result"])
                generated_visual = result.get("visual_replay") or {}
                previous.update(status="failed", can_retry=True,
                    failure_reason="cancelled" if isinstance(exc, (ReplayCancelled, InterruptedError))
                    else generated_visual.get("failure_reason") or "visual_render_failed",
                    message="已停止制作，原复盘仍可播放" if isinstance(exc, (ReplayCancelled, InterruptedError))
                    else "线路回放暂未生成，可重试；原复盘仍可播放")
                fallback["visual_replay"] = previous
                self.store.update(job_id, result=fallback, cancel_requested=False, stage="分析完成")

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
        attempt = int(job.get("attempt") or 1)
        run_started = False

        def is_cancelled() -> bool:
            return self._stop.is_set() or bool(self.store.get(job_id, private=True).get("cancel_requested"))

        def progress(stage: str, value: int) -> None:
            if is_cancelled():
                raise ReplayCancelled()
            self.store.update(job_id, status="running", stage=stage,
                              progress=max(5, min(95, int(value))))

        def telemetry(analysis: dict) -> None:
            self.store.update_analysis_run(job_id, attempt, analysis)

        try:
            if (job.get("preparation") or {}).get("status") != "completed" and job.get("preparation"):
                raw = Path(job["source_path"])
                prepared = raw.with_name(".preparing.mp4")
                progress("正在整理视频格式、方向和片段", 8)
                try:
                    _, info = prepare_video_upload(
                        raw, filename=job["original_name"],
                        content_type=job["preparation"].get("content_type", ""),
                        limits=self.video_limits, output=prepared,
                        trim_start_seconds=job["preparation"].get("trim_start_seconds", 0),
                        trim_end_seconds=job["preparation"].get("trim_end_seconds"),
                        cancelled=is_cancelled,
                    )
                    if is_cancelled():
                        raise ReplayCancelled()
                    job = self.store.finish_preparation(job_id, prepared, info)
                finally:
                    prepared.unlink(missing_ok=True)
            info = VideoInfo(**job["video"])
            initial_analysis = self.analyzer.analysis_contract(info)
            self.store.start_analysis_run(job_id, attempt, initial_analysis)
            run_started = True
            analyze_args = {
                "route_color": job["route_color"], "video_info": info,
                "progress": progress, "cancelled": is_cancelled, "telemetry": telemetry,
            }
            if job.get("route_color_sample"):
                analyze_args["route_color_sample"] = job["route_color_sample"]
                if job["route_color_sample"].get("source") == "video":
                    analyze_args["trim_start_seconds"] = float(job.get("preparation", {}).get("trim_start_seconds") or 0)
            if job.get("saved_route_reference"):
                analyze_args["saved_route_reference"] = job["saved_route_reference"]
            result = self.analyzer.analyze(Path(job["input_path"]), **analyze_args)
            if is_cancelled():
                raise ReplayCancelled()
            overlay_path = Path(job["input_path"]).with_name(REPLAY_OVERLAY_FILENAME)
            if overlay_path.is_file():
                self.store.register_overlay(job_id, result)
            self.store.finish_analysis_run(job_id, attempt, state="succeeded")
            self.store.schedule_source_cleanup(job_id, outcome="succeeded")
            self.store.update(job_id, status="succeeded", stage="分析完成", progress=100,
                              result=result, error_code=None, finished_at=utcnow())
        except (ReplayCancelled, InterruptedError):
            self.store.discard_overlay(job_id)
            if run_started:
                self.store.finish_analysis_run(
                    job_id, attempt, state="cancelled", error_code="cancelled_by_user",
                )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="cancelled", stage="已取消",
                              error=None, error_code="cancelled_by_user", finished_at=utcnow())
        except ReplayConfigurationError as exc:
            self.store.discard_overlay(job_id)
            if run_started:
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
            code = "analysis_failed" if run_started else "media_processing_failed"
            if run_started:
                self.store.finish_analysis_run(
                    job_id, attempt, state="failed", error_code=code,
                )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="failed", stage="分析失败" if run_started else "视频无法处理", progress=0,
                              error=str(exc)[:1000], error_code=code,
                              finished_at=utcnow())

    def close(self) -> None:
        if getattr(self.store, "action_manager", None):
            self.store.action_manager.close()
        if getattr(self.store, "template_manager", None):
            self.store.template_manager.close()
        if getattr(self.store, "coaching_manager", None):
            self.store.coaching_manager.close()
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2)
        self._cleanup_thread.join(timeout=2)


COLOR_PROMPTS = {
    "红色": "red", "红": "red", "蓝色": "blue", "蓝": "blue",
    "绿色": "green", "绿": "green", "黄色": "yellow", "黄": "yellow",
    "橙色": "orange", "橙": "orange", "紫色": "purple", "紫": "purple",
    "粉色": "pink", "粉": "pink", "白色": "white", "白": "white",
    "黑色": "black", "黑": "black", "灰色": "gray", "灰": "gray",
    "青色": "cyan", "青": "cyan", "棕色": "brown", "棕": "brown",
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
                "hold_color": TWELVE_COLOR_VERSION,
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
    def _hold_frames(video: Path, info: VideoInfo, sample: dict | None) -> list[tuple[int, np.ndarray]]:
        total = info.frame_count
        indices = {int(round(value)) for value in np.linspace(total * .08, total * .92, 4)}
        if sample and sample.get("source") == "video" and sample.get("point_xy") is not None:
            trim = float(sample.get("trim_start_seconds") or 0)
            sample_index = round((float(sample.get("time_seconds") or 0) - trim) * info.fps)
            if not 0 <= sample_index < total:
                raise ValueError("取样时间不在保留的视频片段内，请重新选择岩点")
            indices.add(sample_index)
        cap = cv2.VideoCapture(str(video))
        frames = []
        try:
            for index in sorted(indices):
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append((index, frame))
        finally:
            cap.release()
        return frames

    @classmethod
    @serialized_inference
    def _video_holds(cls, *, frames: list[tuple[int, np.ndarray]], route_color: str,
                     route_color_sample: dict | None, saved_route_reference: dict | None,
                     deadline: float, progress: Callable[[str, int], None],
                     cancelled: Callable[[], bool]) -> tuple[list[dict], list[dict], dict, dict | None, str]:
        if not frames:
            raise RuntimeError("没有从视频中读取到有效画面")
        images = [frame for _, frame in frames]
        sharpness = [cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
                     for frame in images]
        reference_index = int(np.argmax(sharpness))
        requested_frame = route_color_sample.get("prepared_frame_index") if route_color_sample else None
        if requested_frame is not None:
            reference_index = next((index for index, item in enumerate(frames)
                                    if item[0] == requested_frame), reference_index)
        reference = images[reference_index]
        height, width = reference.shape[:2]
        transformations: list[np.ndarray | None] = []
        registrations = []
        for index, frame in enumerate(images):
            if index == reference_index:
                transformations.append(np.eye(3))
                registrations.append({"frame": frames[index][0], "status": "reference"})
                continue
            matrix, evidence = align_to_reference(frame, reference)
            transformations.append(matrix)
            registrations.append({"frame": frames[index][0],
                                  "status": "aligned" if matrix is not None else "rejected", **evidence})
        corners = np.float32([[[0, 0]], [[width, 0]], [[width, height]], [[0, height]]])
        motion_px = max((float(np.median(np.linalg.norm(
            cv2.perspectiveTransform(corners, matrix) - corners, axis=2)))
            for matrix in transformations if matrix is not None), default=0.0)
        outputs, model_version = _climbing_model_masks_batch(
            images, deadline, cancelled,
            lambda stage, value: progress(stage, 16 + round(max(0, value - 20) * .37)),
            pack_masks=True,
        )

        def restore_mask(encoded: np.ndarray, frame: np.ndarray) -> np.ndarray:
            if encoded.shape[1] == frame.shape[1]:
                return encoded
            return np.unpackbits(encoded, axis=1, count=frame.shape[1]).astype(np.uint8) * 255

        actual_sample = dict(route_color_sample) if route_color_sample else None
        sampled_bbox = None
        if actual_sample and actual_sample.get("source") == "video" and actual_sample.get("point_xy") is not None:
            requested = actual_sample.get("prepared_frame_index")
            sample_frame_index = next((index for index, item in enumerate(frames)
                if item[0] == requested), None)
            if sample_frame_index is None:
                raise ValueError("无法读取取样时刻的画面，请重新选择岩点")
            frame = images[sample_frame_index]
            px = min(frame.shape[1] - 1, int(actual_sample["point_xy"][0] * frame.shape[1]))
            py = min(frame.shape[0] - 1, int(actual_sample["point_xy"][1] * frame.shape[0]))
            masks, _ = outputs[sample_frame_index]
            matches = []
            for encoded in masks:
                mask = restore_mask(encoded, frame)
                if mask[py, px] > 0:
                    matches.append(mask)
            if not matches:
                raise ValueError("所点位置未落在识别出的岩点内，请选择清晰且未被遮挡的岩点")
            mask = min(matches, key=lambda item: int(np.count_nonzero(item)))
            sample_polygon = native_mask_polygon(mask)
            if len(sample_polygon) >= 3 and transformations[sample_frame_index] is not None:
                sampled_bbox = polygon_bbox(transform_polygon(
                    [[float(point[0][0]), float(point[0][1])] for point in sample_polygon],
                    transformations[sample_frame_index], width, height))
            interior = cv2.erode(mask, np.ones((5, 5), np.uint8))
            pixels = frame[interior > 0]
            if len(pixels) < 10:
                pixels = frame[mask > 0]
            rgb = np.median(pixels[:, ::-1], axis=0).astype(int).tolist()
            actual_sample.update(rgb=rgb, hex="#{:02x}{:02x}{:02x}".format(*rgb),
                                 evidence="segmented_hold_interior", frame_index=frames[sample_frame_index][0])
        detections: list[list[dict]] = []
        target = cls._route_colour(route_color)
        for frame_index, ((source_index, frame), (masks, scores), matrix) in enumerate(
                zip(frames, outputs, transformations)):
            if matrix is None:
                continue
            frame_holds = []
            for encoded, score in zip(masks, scores):
                if cancelled():
                    raise ReplayCancelled()
                mask = restore_mask(encoded, frame)
                polygon = native_mask_polygon(mask)
                if len(polygon) < 3:
                    continue
                source_polygon = [[float(point[0][0]), float(point[0][1])] for point in polygon]
                mapped = transform_polygon(source_polygon, matrix, width, height)
                bbox = polygon_bbox(mapped)
                if bbox[2] <= 0 or bbox[3] <= 0:
                    continue
                colour = classify_mask_color(frame, mask, version=TWELVE_COLOR_VERSION)
                if colour == "待确认":
                    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)[mask > 0]
                    if len(lab):
                        colour = lab_color_name(np.median(lab, axis=0).astype(np.uint8), twelve_colors=True)
                distance = mask_sample_distance(frame, mask, actual_sample["rgb"]) if actual_sample else None
                candidate = distance <= REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE if distance is not None else colour == target
                frame_holds.append({
                    "bbox": bbox, "polygon": mapped, "score": round(float(score), 4),
                    "color_group": colour, "color_source": actual_sample["source"] if actual_sample else "preset",
                    "color_distance": round(distance, 4) if distance is not None else None,
                    "route_candidate": candidate, "route_candidate_reason": "color_sample" if actual_sample else "preset_color",
                    "identity_source": "multi_frame_geometry", "contour_source": "climbing_model_native_mask",
                    "contour_points": len(mapped), "source_frame": source_index,
                })
            detections.append(frame_holds)
        all_holds = fuse_hold_detections(detections, color_distance_limit=REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE)
        if sampled_bbox is not None:
            for hold in all_holds:
                if cls._iou(hold["bbox"], sampled_bbox) > .5:
                    hold["identity_source"] = "user_sampled_hold"
                    hold["route_candidate"] = True
                    hold["route_candidate_reason"] = "user_sampled_hold"
                    break
        projected = []
        route_registration = None
        if saved_route_reference:
            try:
                image = cv2.imdecode(np.fromfile(saved_route_reference["asset_path"], np.uint8), cv2.IMREAD_COLOR)
            except OSError:
                image = None
            if image is not None:
                matrix, route_registration = align_to_reference(image, reference)
                if matrix is not None:
                    for member in saved_route_reference["members"]:
                        polygon = transform_polygon(member["contour"], matrix, width, height)
                        if len(polygon) >= 3:
                            projected.append({"object_id": member["object_id"], "bbox": polygon_bbox(polygon),
                                              "polygon": polygon})
            else:
                route_registration = {"reason": "saved_photo_unavailable"}
        strong_registration = bool(route_registration and
            route_registration.get("inliers", 0) >= 25 and
            route_registration.get("median_error_px", float("inf")) <= 3)
        confirmed, remaining = match_confirmed_route(
            all_holds, projected, include_projected_unmatched=strong_registration)
        if confirmed:
            holds = confirmed
            candidates = remaining
            selection = "confirmed_saved_route"
            sampled_selection = None
        else:
            minimum_appearances = 2 if sum(item is not None for item in transformations) >= 2 else 1
            if actual_sample and actual_sample.get("rgb"):
                sample_rgb = np.uint8([[actual_sample["rgb"]]])
                sample_lab = cv2.cvtColor(sample_rgb, cv2.COLOR_RGB2LAB)[0, 0]
                sample_group = lab_color_name(sample_lab, twelve_colors=True)
                holds, candidates, sampled_selection = select_sampled_route_holds(
                    all_holds, sample_group=sample_group,
                    minimum_appearances=minimum_appearances,
                )
                selection = "sampled_colour_geometry_needs_review"
            else:
                holds, candidates, sampled_selection = select_sampled_route_holds(
                    all_holds, sample_group=target,
                    minimum_appearances=minimum_appearances,
                )
                selection = "minimal_colour_geometry_needs_review"
            candidates.extend(item for item in remaining if item.get("appearances") == 0)
        holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2), hold["bbox"][0]))
        for index, hold in enumerate(holds, 1):
            hold["id"] = index
        diagnostics = {"selection": selection, "reference_frame": frames[reference_index][0],
                       "frames_decoded": len(frames), "frames_aligned": sum(item is not None for item in transformations),
                       "registrations": registrations, "saved_route_registration": route_registration,
                       "camera_motion_px": round(motion_px, 2),
                       "confirmed_members_matched": sum(item.get("appearances", 0) > 0 for item in confirmed),
                       "confirmed_members_projected": sum(item.get("appearances", 0) == 0 for item in candidates),
                       "all_candidates": len(all_holds), "sampled_selection": sampled_selection}
        return holds, candidates, diagnostics, actual_sample, f"{model_version}+multiframe-aligned-v1"

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
        stable_at = {key: None for key in limbs}
        contacts: list[dict] = []
        holding: dict[int, dict[str, int]] = {}
        midline = []

        def close(key: str, frame: int) -> None:
            if current[key] is not None and confirmed[key]:
                contacts.append({"limb": key, "hold_id": current[key], "start_frame": since[key],
                                 "end_frame": max(since[key], frame - 1),
                                 "stable_frame": stable_at[key]})
            current[key], run[key], confirmed[key], stable_at[key] = None, 0, False, None

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
                    if confirmed[key] and stable_at[key] is None:
                        stable_at[key] = frame
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
        top = min(holds, key=lambda hold: hold["bbox"][1] + hold["bbox"][3] / 2)["id"] if holds else None
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
                route_color_sample: dict | None = None,
                saved_route_reference: dict | None = None,
                trim_start_seconds: float = 0,
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
                "wall_alignment": "unavailable",
                "track_id": 0, "kpts_xy": [[0.0, 0.0] for _ in range(17)],
                "kpts_score": [0.0] * 17, "bbox_xywh": [0.0, 0.0, 0.0, 0.0],
            }

        publish()
        try:
            # Fail before local inference so a missing provider configuration
            # cannot spend local CPU or send any image data.
            self._client()

            stage_started = time.perf_counter()
            progress("选取清晰视频帧", 10)
            prepared_sample = dict(route_color_sample) if route_color_sample else None
            if prepared_sample and prepared_sample.get("source") == "video" and prepared_sample.get("point_xy") is not None:
                prepared_sample["trim_start_seconds"] = trim_start_seconds
                prepared_sample["prepared_frame_index"] = round(
                    (float(prepared_sample["time_seconds"]) - prepared_sample["trim_start_seconds"]) * video_info.fps)
            hold_frames = self._hold_frames(video, video_info, prepared_sample)
            if not hold_frames:
                timings["background"] = max(0, round((time.perf_counter() - stage_started) * 1000))
                publish()
                raise RuntimeError("没有从视频中读取到有效画面")
            timings["background"] = max(0, round((time.perf_counter() - stage_started) * 1000))
            publish()

            stage_started = time.perf_counter()
            progress("逐帧识别并对齐岩点", 16)
            holds, hold_candidates, hold_diagnostics, actual_sample, hold_version = self._video_holds(
                frames=hold_frames, route_color=route_color, route_color_sample=prepared_sample,
                saved_route_reference=saved_route_reference,
                deadline=time.monotonic() + 240, progress=progress, cancelled=cancelled,
            )
            timings["hold_inference"] = max(0, round((time.perf_counter() - stage_started) * 1000))
            analysis["models"]["holds"]["version"] = hold_version
            publish()
            if cancelled():
                raise ReplayCancelled()
            if not holds:
                raise RuntimeError(f"没有找到“{route_color}”线路候选岩点，请尝试从画面点选样本岩点")

            sample_fps, positions = self._sampling_positions(video_info)
            stage_started = time.perf_counter()
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                raise RuntimeError("无法重新读取视频进行姿态识别")
            records = []
            contact_records = []
            hold_reference = next(frame for index, frame in hold_frames
                                  if index == hold_diagnostics["reference_frame"])
            pose_alignment_failed = 0
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
                        missing = empty_pose(sample_index, int(source_index))
                        records.append(missing)
                        contact_records.append(missing)
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
                        matrix, alignment = align_to_reference(frame, hold_reference)
                        record["wall_alignment"] = "aligned" if matrix is not None else "failed"
                        record["wall_alignment_diagnostics"] = alignment
                        record["wall_reference_transform"] = matrix.tolist() if matrix is not None else None
                        records.append(record)
                        if matrix is None:
                            pose_alignment_failed += 1
                        contact_records.append(align_pose_record(
                            record, matrix, hold_reference.shape[1], hold_reference.shape[0]))
                    else:
                        usage["responses_without_pose"] += 1
                        missing = empty_pose(sample_index, int(source_index))
                        records.append(missing)
                        contact_records.append(missing)
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
            attempt = self._contacts(contact_records, holds, sample_fps)
            pose_samples = build_pose_samples(records, video_info)
            add_attempt_source_times(attempt, pose_samples, video_info)
            attempt["action_steps"] = build_action_steps(attempt.get("contacts") or [])
            timings["contact"] = max(0, round((time.perf_counter() - stage_started) * 1000))

            stage_started = time.perf_counter()
            progress("生成可导出的叠加视频", 86)
            result = {
                "schema_version": 2,
                "segment_schema_version": 1,
                "status": "prototype_needs_review",
                "route": {"color": route_color, "color_sample": actual_sample},
                "models": {"holds": hold_version, "pose": self.pose_model},
                "video": asdict(video_info),
                "track_id": track_id,
                "frames_with_pose": detected_pose_frames,
                "holds": holds,
                "hold_candidates": hold_candidates,
                "hold_evidence": hold_diagnostics,
                "pose_samples": pose_samples,
                "attempt": attempt,
                "analysis": analysis,
                "warnings": [
                    "当前为技术验证结果，手脚接触需要用户复核。",
                    "岩点由服务器本地专项模型识别，并直接保留模型原生掩膜轮廓；姿态仅对降帧画面调用阿里云人体姿态关键点服务。",
                    "导出视频在相邻实测姿态帧之间做本地线性平滑；分析证据仍以实测抽样帧为准。",
                    "导出的叠加视频保留原画面，但当前不包含原视频音轨。",
                    "岩点接触使用本地专项模型原生实例分割轮廓与短时停留判断，接触边界仍需用户复核。",
                    f"{pose_alignment_failed} 帧姿态未能可靠对齐墙面参考，已从接触判断中排除。",
                    (f"{hold_diagnostics['confirmed_members_projected']} 个已确认岩点仅通过照片对齐投影定位，"
                     "未在抽样帧中被模型重新检测到，已放在其他候选且不参与接触判断。") if hold_diagnostics.get("confirmed_members_projected") else
                    "已确认线路岩点优先采用照片与视频的几何对应，颜色仅参与候选筛选。",
                    ("检测到机位变化；接触计算已对齐姿态帧，但导出视频中的固定岩点框仅供参考。"
                     if hold_diagnostics.get("camera_motion_px", 0) > .02 * min(video_info.width, video_info.height)
                     else "固定岩点图采用多帧配准融合，单帧漏检不会直接决定岩点身份。"),
                    "开始时间根据首个手脚同时稳定接触估算，尚未使用地面分割。",
                ],
            }
            attempt["segments"] = build_segments(result)
            result["overlay"] = render_replay_overlay_video(
                video, video.with_name(REPLAY_OVERLAY_FILENAME), result,
                progress=lambda value: progress(
                    "生成可导出的叠加视频", 86 + round(10 * value / 100),
                ),
                cancelled=cancelled,
                stage_progress=lambda stage, value: progress(stage, 86 + round(10 * value / 100)),
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
    route_reference_lookup: Callable[[str, str], dict | None] | None = None,
    limits: VideoLimits | None = None,
    test_video_path: Path | None = None,
    test_video_source_url: str | None = None,
    test_video_cases: list[dict[str, Any]] | None = None,
    coaching_manager=None,
    template_manager=None,
) -> APIRouter:
    limits = limits or VideoLimits()
    manager.video_limits = limits
    router = APIRouter(prefix="/api/climb-replay", tags=["climb-replay"])
    from core.replay_coaching import CoachingManager, coaching_router
    coaching = coaching_manager or getattr(store, "coaching_manager", None) or CoachingManager(store)
    router.include_router(coaching_router(coaching))
    from core.replay_template import TemplateVideoManager, template_router
    template = template_manager or getattr(store, "template_manager", None) or TemplateVideoManager(store, coaching)
    router.include_router(template_router(template))
    from core.replay_action_jobs import ActionManager, action_router
    actions = getattr(store, "action_manager", None) or ActionManager(store)
    router.include_router(action_router(actions))
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

    def route_reference(username: str, route_id: str) -> dict | None:
        return route_reference_lookup(route_id, username) if route_id and route_reference_lookup else None

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
        trim_start_seconds: float = Form(default=0),
        trim_end_seconds: float | None = Form(default=None),
        route_color_sample: str = Form(default=""),
    ):
        username = owner(request)
        route_id, route_color = resolve_route(username, route_id, route_color)
        consent = consent_grant(consent_version, consent_granted, attempt=1)
        retention = retention_choice(retention_mode)
        try:
            color_sample = parse_color_sample(route_color_sample)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            validate_video_upload_type(video.filename or "", video.content_type or "")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        upload = store.root / f".upload-{uuid.uuid4().hex}.tmp"
        size, digest = 0, hashlib.sha256()
        try:
            with upload.open("wb") as target:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > limits.max_input_bytes:
                        raise HTTPException(413, f"视频不能超过 {limits.max_input_bytes // (1024 * 1024)} MB")
                    digest.update(chunk)
                    target.write(chunk)
            if not size:
                raise HTTPException(422, "视频内容为空")
            with store._lock:
                manager.ensure_capacity()
                job = store.create_pending(
                    owner=username, route_id=route_id or None, route_color=route_color,
                    source=upload, original_name=video.filename or f"{digest.hexdigest()}.mp4",
                    content_type=video.content_type or "application/octet-stream",
                    consent=consent, retention_mode=retention,
                    trim_start_seconds=trim_start_seconds, trim_end_seconds=trim_end_seconds,
                    route_color_sample=color_sample,
                    saved_route_reference=route_reference(username, route_id),
                )
                manager.enqueue(job["id"])
            return job
        finally:
            upload.unlink(missing_ok=True)

    @router.post("/uploads")
    def create_upload(payload: ReplayUploadCreate, request: Request):
        username = owner(request)
        route_id, route_color = resolve_route(username, payload.route_id, payload.route_color)
        consent = consent_grant(payload.consent_version, payload.consent_granted, attempt=1)
        try:
            validate_video_upload_type(payload.filename, payload.content_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            return replay_uploads.create(username, total_size=payload.size_bytes, max_size=limits.max_input_bytes, metadata={
                "filename": payload.filename, "content_type": payload.content_type,
                "route_id": route_id, "route_color": route_color,
                "consent": consent, "retention_mode": payload.retention_mode,
                "trim_start_seconds": payload.trim_start_seconds,
                "trim_end_seconds": payload.trim_end_seconds,
                "route_color_sample": parse_color_sample(payload.route_color_sample),
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
        manager.ensure_capacity()
        try:
            meta, part = replay_uploads.finish(upload_id, username)
            details = meta["metadata"]
            route_id, route_color = resolve_route(username, details.get("route_id", ""), details.get("route_color", ""))
            with store._lock:
                manager.ensure_capacity()
                job = store.create_pending(
                    owner=username, route_id=route_id or None, route_color=route_color,
                    source=part, original_name=details["filename"],
                    content_type=details.get("content_type", "application/octet-stream"),
                    consent=details["consent"],
                    retention_mode=retention_choice(details.get("retention_mode", REPLAY_RETENTION_DELETE)),
                    trim_start_seconds=float(details.get("trim_start_seconds", 0) or 0),
                    trim_end_seconds=(float(details["trim_end_seconds"])
                                      if details.get("trim_end_seconds") is not None else None),
                    route_color_sample=parse_color_sample(details.get("route_color_sample")),
                    saved_route_reference=route_reference(username, route_id),
                )
                manager.enqueue(job["id"])
            return job
        except ChunkUploadError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            replay_uploads.discard(upload_id)

    @router.get("/jobs")
    def list_jobs(request: Request):
        return store.list(owner(request))

    @router.post("/comparisons")
    def compare_replay_jobs(payload: ReplayComparisonCreate, request: Request):
        username = owner(request)
        if payload.first_job_id == payload.second_job_id:
            raise HTTPException(422, "请选择同一线路的两次不同攀爬")
        first = store.get(payload.first_job_id, username, private=True)
        second = store.get(payload.second_job_id, username, private=True)
        if first.get("status") != "succeeded" or second.get("status") != "succeeded":
            raise HTTPException(409, "两段视频都完成分析后才能比较")
        try:
            return compare_segments(first, second, same_climber_confirmed=payload.same_climber_confirmed)
        except ValueError as exc:
            messages = {
                "route_mismatch": "只能比较同一条已保存线路的两次攀爬",
                "route_version_mismatch": "线路版本不同，暂不能自动比较",
                "same_climber_unconfirmed": "请先确认两段视频是同一位攀爬者",
            }
            raise HTTPException(422, messages.get(str(exc), "两段视频暂不能比较")) from exc

    @router.put("/jobs/{job_id}/segments/{segment_id}/review")
    def review_replay_segment(job_id: str, segment_id: str, payload: ReplaySegmentReview, request: Request):
        return store.review_segment(job_id, owner(request), segment_id, payload)

    @router.post("/jobs/{job_id}/segments/{segment_id}/review/revert")
    def revert_replay_segment(job_id: str, segment_id: str, request: Request):
        return store.review_segment(job_id, owner(request), segment_id, None)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        return store.get(job_id, owner(request))

    @router.post("/jobs/{job_id}/holds/candidates/{candidate_index}/promote")
    def promote_hold_candidate(job_id: str, candidate_index: int, request: Request):
        return store.promote_hold_candidate(job_id, owner(request), candidate_index)

    @router.post("/jobs/{job_id}/holds/point")
    def add_hold_at_point(job_id: str, point: ReplayHoldPoint, request: Request):
        return store.add_hold_at_point(job_id, owner(request), point)

    @router.post("/jobs/{job_id}/holds/point/preview")
    def preview_hold_at_point(job_id: str, point: ReplayHoldPoint, request: Request):
        return store.preview_hold_at_point(job_id, owner(request), point)

    @router.post("/jobs/{job_id}/holds/point/undo")
    def undo_last_clicked_hold(job_id: str, request: Request):
        return store.undo_last_clicked_hold(job_id, owner(request))

    @router.post("/jobs/{job_id}/holds/point/{review_version}/undo")
    def undo_clicked_hold(job_id: str, review_version: int, request: Request):
        return store.undo_clicked_hold(job_id, owner(request), review_version)

    @router.post("/jobs/{job_id}/holds/refine-sampled-route")
    def refine_sampled_route_holds(job_id: str, request: Request):
        return store.refine_sampled_holds(job_id, owner(request))

    def media_response(job_id: str, request: Request, media_kind: str,
                       *, download: bool) -> FileResponse:
        if download and media_kind in {REPLAY_OVERLAY_MEDIA_KIND, REPLAY_REVIEWED_OVERLAY_MEDIA_KIND}:
            job = store.get(job_id, owner(request))
            visual = (job.get("result") or {}).get("visual_replay") or {}
            if visual.get("stale") or visual.get("status") == "stale":
                raise HTTPException(409, "复核内容已更新，请重新制作线路回放后下载")
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

    @router.get("/jobs/{job_id}/media/reviewed-overlay-video")
    def get_reviewed_overlay_video(job_id: str, request: Request, download: bool = False):
        return media_response(job_id, request, REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, download=download)

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
        with store._lock:
            manager.ensure_capacity()
            job = store.get(job_id, username, private=True)
            consent = consent_grant(
                payload.consent_version, payload.consent_granted,
                attempt=int(job.get("attempt") or 1) + 1,
            )
            result = store.retry(job_id, username, consent)
            manager.enqueue(job_id)
        return result

    @router.post("/jobs/{job_id}/visual-replay/retry", status_code=202)
    def retry_visual_replay(job_id: str, request: Request):
        username = owner(request)
        with store._lock:
            current = store.get(job_id, username, private=True)
            if (current.get("result") or {}).get("visual_replay", {}).get("status") not in {"queued", "running"}:
                manager.ensure_capacity()
            result = store.request_visual_retry(job_id, username)
            if (result.get("result") or {}).get("visual_replay", {}).get("status") == "queued":
                manager.enqueue_visual(job_id)
        return result

    @router.post("/jobs/{job_id}/consent/withdraw")
    def withdraw_job_consent(job_id: str, request: Request):
        return store.withdraw_consent(job_id, owner(request))

    return router
