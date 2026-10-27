"""Experimental, opt-in video replay analysis for climbing attempts.

This module is deliberately isolated from the photo-route recognition pipeline.
It owns a small file-backed job queue. Hold segmentation reuses the verified
local climbing-specific model, while pose estimation uses sampled still frames
through the default offline RTMW-L provider. Registration is controlled by
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
import logging
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
from collections import OrderedDict, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from core.chunked_upload import ChunkUploadError, ChunkUploadStore
from core.photo_route_analysis import _climbing_model_masks_batch
from core.photo_route_colors import ROUTE_COLOR_NAMES, lab_color_name
from core.replay_hold_colors import REPLAY_COLOUR_VERSION, observe_hold_colour, region_sample_distance, sample_clicked_hold
from core.replay_hold_evidence import material_observation, sample_compatible_group, colour_support, boundary_quality
from core.photo_route_inference_lock import serialized_inference
from core.replay_hold_fusion import align_pose_record, align_to_reference, box_iou, fuse_hold_detections, match_confirmed_route, polygon_bbox, select_sampled_route_holds, transform_polygon
from core.replay_segments import build_segments, compare_segments, effective_segments, measured_joint_angles
from core.replay_pose_display import TORSO_CENTER_STYLE, torso_center
from core.replay_torso_trajectory import torso_trajectory
from core.replay_sampling import FocusWindow
from core.replay_resources import high_resource_slot, run_visual_worker, serialized_heavy_stage
# Compatibility exports: callers keep their existing climb_replay imports.
from core.replay_contracts import (
    REPLAY_RETENTION_DELETE, REPLAY_RETENTION_KEEP, ReplayRetentionMode,
    ReplayConfigurationError, ReplayCancelled, VideoLimits, VideoInfo, ReplayAnalyzer,
    ReplayColorSample, ReplayUploadCreate, ReplayRetryCreate, ReplayHoldsConfirmation,
    ReplayComparisonCreate, ReplaySegmentReview, ReplayHoldPoint, parse_color_sample,
    hold_review_input, hold_geometry, holds_revision,
)
from core.replay_render_primitives import (
    draw_cjk_labels, build_pose_render_timeline, _overlay_text,
    _CJK_FONT_CANDIDATES, _CJK_FONT_PATH, _CJK_FONT_CACHE,
)

from core.replay_job_queue import ReplayJobQueue
from core.replay_job_records import ReplayJobRecords
from core.replay_test_videos import ReplayTestVideoCatalog
from core.replay_media import (
    REPLAY_VIDEO_MIME_TYPES, REPLAY_VIDEO_SUFFIXES,
    probe_video, validate_video_upload_type, validate_video,
)

from core.replay_hold_editor import (EditorFrameRequest, EditorPreviewRequest, EditorCommitRequest, EditorCancelRequest,
    editor_frame, editor_preview, editor_commit, cancel_editor_request, clear_editor_cache, _put, _proposals, _binding)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_after(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


REPLAY_CONSENT_VERSION = "climb-replay-local-rtmw-hold-editor-v2-2026-10-07"
REPLAY_CONSENT_PROVIDER = "本机 RTMW-L"
REPLAY_CONSENT_SERVICE = "RTMW-L 384×288"
REPLAY_CONSENT_DATA_TYPES = ["降帧后的单张视频画面", "画面中的人体姿态关键点"]
REPLAY_PIPELINE_VERSION = "climb-replay-v3-local-rtmw-20261006"
REPLAY_POSE_API_VERSION = "2019-12-30"
DEFAULT_POSE_UNIT_PRICE_CNY = 0.0016
REPLAY_OVERLAY_FILENAME = "overlay.webm"
REPLAY_OVERLAY_MEDIA_KIND = "overlay_video"
REPLAY_REVIEWED_OVERLAY_MEDIA_KIND = "reviewed_overlay_video"
REPLAY_REFERENCE_MEDIA_KIND = "wall_reference"
REPLAY_REFERENCE_FILENAME = "replay-reference.png"
REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE = 60.0
from core.replay_skeleton_mode import skeleton_draft, without_hold_data


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
    for long_edge, short_edge, crf in ((bounds.max_width, bounds.max_height, 20),):
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


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows readers and file scanners can briefly deny replacement. Keep
        # the previous receipt intact and retry only this atomic commit.
        for attempt in range(8):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.025 * (2 ** attempt), 0.2))
    finally:
        temp.unlink(missing_ok=True)


POSE_EDGES = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
)
LIMB_OVERLAY_NAMES = {
    "left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚",
}
def build_pose_samples(records: list[dict], video_info: VideoInfo) -> list[dict]:
    """Preserve exact sampled-frame evidence without inventing interpolated poses."""
    samples = []
    for record in sorted(records, key=lambda item: int(item.get("frame_id", -1))):
        scores = [float(value or 0) for value in record.get("kpts_score") or []]
        usable_scores = [value for value in scores if value >= 0.15]
        source_frame = int(record.get("source_frame_id") or 0)
        samples.append({
            **({"wholebody": copy.deepcopy(record["wholebody"])} if record.get("wholebody") else {}),
            **({"pose_evidence": copy.deepcopy(record["pose_evidence"])} if record.get("pose_evidence") else {}),
            **({"joint_observations": copy.deepcopy(record["joint_observations"])} if record.get("joint_observations") else {}),
            **({"image_observation_refinement": copy.deepcopy(record["image_observation_refinement"])} if record.get("image_observation_refinement") else {}),
            **({"temporal_display": copy.deepcopy(record["temporal_display"])} if record.get("temporal_display") else {}),
            **({"joint_eligibility": copy.deepcopy(record["joint_eligibility"])} if record.get("joint_eligibility") is not None else {}),
            **({"initial_wholebody_observation": copy.deepcopy(record["initial_wholebody_observation"]),
                "pose_revision": copy.deepcopy(record["pose_revision"])} if record.get("pose_revision") else {}),
            "sample_index": int(record.get("frame_id") or 0),
            "source_frame_id": source_frame,
            "time_seconds": round(source_frame / max(video_info.fps, 1e-9), 6),
            "wall_alignment": record.get("wall_alignment", "unknown"),
            "wall_alignment_diagnostics": record.get("wall_alignment_diagnostics") or {},
            "wall_reference_transform": record.get("wall_reference_transform"),
            "observed": bool(len(record['joint_eligibility'])==17
                and all(isinstance(v,bool) for v in record['joint_eligibility']) and any(record['joint_eligibility']))
                if record.get('joint_eligibility') is not None else bool(usable_scores),
            **({'confidence_basis':'not_calibrated',
                'mean_model_response':round(float(np.mean(scores)),6) if scores else None} if record.get('joint_eligibility') is not None else {}),
            "confidence": None if record.get('joint_eligibility') is not None else round(float(np.mean(usable_scores)), 6) if usable_scores else 0.0,
            "kpts_xy": record.get("kpts_xy") or [[0.0, 0.0] for _ in range(17)],
            "kpts_score": scores or [0.0] * 17,
            "bbox_xywh": record.get("bbox_xywh") or [0.0, 0.0, 0.0, 0.0],
            "joint_angles_2d": measured_joint_angles(
                record.get("kpts_xy") or [],
                [1. if eligible else 0. for eligible in record['joint_eligibility']]
                    if record.get('joint_eligibility') is not None and len(record['joint_eligibility'])==17
                    and all(isinstance(v,bool) for v in record['joint_eligibility'])
                    else [0.]*17 if record.get('joint_eligibility') is not None else scores,
                video_info.width, video_info.height),
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


def existing_hold_mask(holds, matrix, width, height, reference_width=None, reference_height=None):
    """Project existing contours into this frame; bounding boxes are legacy fallback only."""
    mask = np.zeros((height, width), np.uint8)
    inverse = np.linalg.inv(matrix)
    for hold in holds:
        polygon = hold.get('polygon') or []
        if len(polygon) < 3 and len(hold.get('bbox') or []) >= 4:
            x,y,w,h = hold['bbox'][:4]
            polygon = [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
        if len(polygon) < 3:
            continue
        points = np.asarray(polygon, np.float32) * [reference_width or width, reference_height or height]
        mapped = cv2.perspectiveTransform(points.reshape(-1,1,2), inverse).reshape(-1,2)
        if np.isfinite(mapped).all():
            cv2.fillPoly(mask, [np.rint(mapped).astype(np.int32)], 255)
    return mask


def clicked_hold_polygon(frame: np.ndarray, point_xy: list[float], excluded_mask=None) -> list[list[float]]:
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
    if excluded_mask is not None:
        if excluded_mask[y,x]:
            raise HTTPException(409, '所选位置已被已有岩点覆盖，请选择旁边尚未识别的区域。')
        binary[excluded_mask[top:bottom,left:right] > 0] = 0
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


def boxed_hold_polygon(frame: np.ndarray, region_xyxy: list[float], excluded_mask=None, allowed_mask=None) -> list[list[float]]:
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
    excluded = (excluded_mask[top:bottom,left:right] > 0) if excluded_mask is not None else np.zeros(inner.shape, bool)
    border_pixels = lab[~inner & ~excluded]
    if allowed_mask is not None:
        excluded = excluded | (allowed_mask[top:bottom,left:right] == 0)
    inner &= ~excluded
    if np.count_nonzero(inner) < 12:
        raise HTTPException(409, '选区已被已有岩点覆盖，请框选旁边尚未识别的区域。')
    if len(border_pixels) < 8:
        raise HTTPException(422, "框选范围太贴近画面边缘，请稍微扩大画面后重试。")
    background = np.median(border_pixels, axis=0)
    min_area = max(12, round(np.count_nonzero(inner) * .045))
    region_center = np.asarray([(inner_left + inner_right) / 2 - left,
                                (inner_top + inner_bottom) / 2 - top])
    region_radius = max(1, math.hypot(inner_width, inner_height) / 2)
    proposals = []
    for fy in (.18, .34, .5, .66, .82):
        for fx in (.18, .34, .5, .66, .82):
            px = min(lab.shape[1] - 1, int(inner_left - left + inner_width * fx))
            py = min(lab.shape[0] - 1, int(inner_top - top + inner_height * fy))
            if not inner[py,px]:
                continue
            seed = lab[max(0, py - 1):py + 2, max(0, px - 1):px + 2]
            target = np.median(seed.reshape(-1, 3), axis=0)
            distance = np.linalg.norm(lab.astype(np.float32) - target, axis=2)
            binary = (distance <= 26).astype(np.uint8)
            binary[excluded] = 0
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
        mask[excluded] = cv2.GC_BGD
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
    selected &= ~excluded
    contour = native_mask_polygon(selected.astype(np.uint8) * 255, max_points=160)
    if len(contour) < 3:
        raise HTTPException(422, "框内岩点轮廓不完整，请框紧一些或换帧。")
    return [[float(item[0][0] + left), float(item[0][1] + top)] for item in contour]


def _multi_frame_clicked_polygon(source: Path, video: VideoInfo, frame_index: int,
                                 reference_index: int, reference: np.ndarray,
                                 initial: list[list[float]],
                                 region_xyxy: list[float] | None = None, existing_holds=None) -> tuple[list[list[float]], int]:
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
                excluded = existing_hold_mask(existing_holds or [], to_reference, video.width, video.height)
                if region_xyxy is None:
                    polygon = clicked_hold_polygon(frame, click, excluded)
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
                    polygon = boxed_hold_polygon(frame, values, excluded)
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


def _replay_split_output_size(width: int, height: int) -> tuple[int, int]:
    pane_width, pane_height = _replay_output_size(width, height)
    return pane_width * 2, pane_height


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


def _contain_visual_tail(source: Path, target: Path, *, size: tuple[int, int], fps: float,
                         cancelled: Callable[[], bool] | None = None) -> None:
    """Fit the native wall animation on a split canvas without changing aspect."""
    capture = cv2.VideoCapture(str(source))
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"VP80"), fps, size)
    try:
        if not capture.isOpened() or not writer.isOpened():
            raise RuntimeError("无法适配线路回放画幅")
        while True:
            if cancelled and cancelled():
                raise ReplayCancelled()
            ok, frame = capture.read()
            if not ok:
                break
            scale = min(size[0] / frame.shape[1], size[1] / frame.shape[0])
            width, height = round(frame.shape[1] * scale), round(frame.shape[0] * scale)
            canvas = np.full((size[1], size[0], 3), (13, 16, 18), dtype=np.uint8)
            x, y = (size[0] - width) // 2, (size[1] - height) // 2
            canvas[y:y+height, x:x+width] = cv2.resize(frame, (width, height))
            writer.write(canvas)
    finally:
        capture.release()
        writer.release()


def _prepare_visual_tail(result: dict, reference: Path, directory: Path, *,
                         size: tuple[int, int], fps: float,
                         cancelled: Callable[[], bool] | None = None,
                         progress: Callable[[str, int], None] | None = None) -> tuple[Path | None, dict]:
    from core.replay_visual_renderer import build_visual_manifest
    visual = dict(result["visual_replay"])
    try:
        if not reference.is_file():
            raise ValueError("历史复盘缺少墙面参考画面，无法制作线路回放")
        # The worker keeps the original wall aspect and its 1280-side resource
        # limit. The split presentation canvas must not stretch that evidence.
        metadata = result["visual_reference"]
        native_size = _replay_output_size(metadata["width"], metadata["height"])
        manifest = build_visual_manifest(_visual_render_evidence(result), metadata, output_size=native_size, fps=fps)
        manifest_path, tail = directory / "manifest.json", directory / "tail.webm"
        native_tail = directory / "native-tail.webm" if native_size != size else tail
        _atomic_json(manifest_path, manifest)
        if progress:
            progress("正在制作线路回放", 0)
        metrics = run_visual_worker(reference, manifest_path, native_tail, directory / "metrics.json",
                                    cancelled=cancelled, progress=progress)
        if native_size != size:
            _contain_visual_tail(native_tail, tail, size=size, fps=fps, cancelled=cancelled)
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
    """Render the original and synchronized right-side analysis, without a tail."""
    info = probe_video(source)
    result["visual_replay"] = _visual_base_metadata(result,fps=info.fps,analysis_frames=info.frame_count)
    result["visual_replay"].update(status="disabled",can_retry=False,message="动作分析在右侧随视频同步显示")
    try:
        with high_resource_slot(cancelled=cancelled,progress=stage_progress):
            return _render_replay_overlay_video_body(source,target,result,progress=progress,cancelled=cancelled)
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
    # Keep the existing derivative geometry when rebuilding only its tail.
    size = (info.width, info.height)
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
    source: Path, target: Path, result: dict, *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    tail_path: Path | None = None,
    output_size: tuple[int, int] | None = None,
) -> dict:
    """Keep original pixels on the left and all analysis on the right."""
    from .replay_analysis_view import AnalysisView, LAYOUT
    cap = cv2.VideoCapture(str(source))
    width,height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps,total = float(cap.get(cv2.CAP_PROP_FPS)),int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not cap.isOpened() or min(width,height,fps,total)<=0:
        cap.release()
        raise RuntimeError("原视频信息不完整，无法生成复盘视频")
    output_width,output_height = output_size or _replay_split_output_size(width,height)
    snapshot = copy.deepcopy(result)
    snapshot['video'] = {**snapshot.get('video',{}),'width':width,'height':height,'fps':fps,
        'frame_count':total,'duration_seconds':total/fps}
    view = AnalysisView(snapshot)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary = target.with_name(f".{target.stem}-{uuid.uuid4().hex}.tmp.webm")
    writer = cv2.VideoWriter(str(temporary),cv2.VideoWriter_fourcc(*"VP80"),fps,(output_width,output_height))
    if not writer.isOpened():
        cap.release();writer.release();temporary.unlink(missing_ok=True)
        raise RuntimeError("当前环境无法编码 WebM 复盘视频")
    frame_index,tail_frames = 0,0
    try:
        while True:
            if cancelled and cancelled():
                raise ReplayCancelled()
            ok,frame = cap.read()
            if not ok:
                break
            canvas = view.frame(frame,frame_index,(output_width,output_height))
            writer.write(canvas)
            frame_index += 1
            if progress and (frame_index==total or frame_index%max(1,total//20)==0):
                progress(min(100,round(frame_index*100/total)))
        if frame_index!=total:
            raise RuntimeError("复盘视频未完整生成，请保留原视频后重试")
        # New analysis is visible throughout playback; no end summary is baked.
    except BaseException:
        cap.release();writer.release();temporary.unlink(missing_ok=True)
        raise
    cap.release();writer.release()
    try:
        _validate_visual_video(temporary,width=output_width,height=output_height,
            fps=fps,expected_frames=total,cancelled=cancelled)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary,target)
    pane=output_width//2
    scale=min(pane/width,output_height/height)
    w,h=max(1,round(width*scale)),max(1,round(height*scale))
    x,y=(pane-w)//2,(output_height-h)//2
    return {'schema_version':3,'container':'webm','codec':'vp8','frames_written':total,
        'analysis_frame_count':total,'analysis_duration_seconds':total/fps,'tail_frame_count':0,
        'total_duration_seconds':total/fps,'fps':round(fps,6),'width':output_width,'height':output_height,
        'pose_rendering':'local_linear_between_measured_samples','pose_evidence':'registered_saved_samples',
        'pose_rendered_frames':len(view.timeline),'center_of_mass':'projected-segment-mass-mean-v1','layout':LAYOUT,
        'video_rect':[x,y,w,h],'route_map_rect':[pane+x,y,w,h],'route_map_clip':[pane,0,output_width-pane,output_height],
        'hold_map':'source_scale_current_limb_holds','touch_markers':'none',
        'hold_highlighting':'current_contact_intervals_only','analysis_side':'right','original_side':'left',
        'torso_route':'progressive_registered_segments','action_labels':'page_statistics_no_baked_sequence',
        'hold_count':len(view.holds),'action_count':len((result.get('attempt') or {}).get('action_steps') or build_action_steps((result.get('attempt') or {}).get('contacts') or [])),
        'audio_included':False}


class ClimbReplayStore(ReplayJobRecords):
    """File-backed, owner-scoped jobs kept outside the photo-route database."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.jobs = self.root / "jobs"
        self.deletions = self.root / "deletions"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.deletions.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active_hold_renders: set[str] = set()
        # Only public snapshots are cached; private worker reads remain fresh.
        self._public_cache = OrderedDict()
        self._public_cache_bytes = 0
        self._public_cache_limit = 16 * 1024 * 1024
        self._public_cache_entries = 32
        self.recover_interrupted()

    def _public_cache_context(self):
        """Keep runtime projection flags in the legacy replacement namespace."""
        return replay_visual_enabled()

    def _commit_record(self, job_id: str, job: dict) -> None:
        """Keep the clock and atomic writer dynamic while the record lock is held."""
        job["updated_at"] = utcnow()
        _atomic_json(self._path(job_id), job)

    @staticmethod
    def _public(job: dict) -> dict:
        public = {key: value for key, value in job.items() if key not in {"input_path", "source_path", "saved_route_reference", "automatic_result", "coaching", "coaching_history", "template_video", "action_task", "action_result", "action_export", "action_export_media", "action_history", "action_revisions", "action_revision_audit", "action_result_history", "action_commentary_checkpoint", "worker_failure"}}
        hold_input = hold_review_input(job)
        public.pop("overlay_history", None)
        if hold_input:
            public["holds_revision"] = holds_revision(hold_input)
        public["holds_pending_local_analysis"] = bool(job.get("hold_edit_draft"))
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
        if job.get('skeleton_only'):
            public = without_hold_data(public)
        return public

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
                    "retention_mode": REPLAY_RETENTION_KEEP, "delete_at": None,
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
                "kind": "source_video", "status": "available", "retention_mode": REPLAY_RETENTION_KEEP,
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
        """Stage one confirmed candidate; defer all recomputation to global confirmation."""
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if job.get("status") not in {"succeeded", "awaiting_hold_review"}:
                raise HTTPException(409, "本地岩点识别完成后才能补入岩点")
            if job.get("segment_reviews"):
                raise HTTPException(409, "已有动作段人工复核，请先撤销复核再补入岩点")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "任务正在删除")
            result = copy.deepcopy(hold_review_input(job))
            candidates = result.get("hold_candidates") or []
            if candidate_index < 0 or candidate_index >= len(candidates):
                raise HTTPException(404, "未找到候选岩点")
            candidate = candidates[candidate_index]
            if (candidate.get("contour_source") not in {'climbing_model_native_mask','model_guided_mobilesam_mask'}
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
        return self._save_hold_edits(job_id, job, result, source, event)

    def _clicked_hold_proposal(self, job_id: str, owner: str, point: ReplayHoldPoint) -> tuple:
        """Build a read-only proposal; caller holds the store lock."""
        job = self._read(job_id)
        if job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        if (job.get("deletion") or {}).get("state") == "queued":
            raise HTTPException(409, "这条复盘正在删除，无法补入岩点。")
        if job.get("status") not in {"succeeded", "awaiting_hold_review"}:
            raise HTTPException(409, "本地岩点识别完成后才能补入岩点。")
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
        result = copy.deepcopy(hold_review_input(job))
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
        if frame_index == reference_index:
            matrix = np.eye(3)
        else:
            matrix, _ = align_to_reference(frame, reference)
        if matrix is None:
            raise HTTPException(422, "这帧画面无法对齐墙面，请换一帧再补点。")
        holds = result.get("holds") or []
        excluded = existing_hold_mask(holds, matrix, video.width, video.height)
        polygon = (boxed_hold_polygon(frame, point.region_xyxy, excluded)
                   if point.region_xyxy is not None else clicked_hold_polygon(frame, point.point_xy, excluded))
        mapped = transform_polygon(polygon, matrix, reference.shape[1], reference.shape[0])
        if len(mapped) < 3:
            raise HTTPException(422, "岩点轮廓无法映射到墙面，请换一帧再试。")
        mapped, frame_support = _multi_frame_clicked_polygon(
            source, video, frame_index, reference_index, reference, mapped, point.region_xyxy, holds)
        bbox = polygon_bbox(mapped)
        holds = result.get("holds") or []
        source_polygon = transform_polygon(
            [[x * video.width, y * video.height] for x, y in mapped],
            np.linalg.inv(matrix), video.width, video.height)
        return job, result, source, frame_index, source_polygon, mapped, bbox, frame_support

    def preview_hold_at_point(self, job_id: str, owner: str, point: ReplayHoldPoint) -> dict:
        with self._lock:
            job, result, _, frame_index, source_polygon, mapped, bbox, support = self._clicked_hold_proposal(
                job_id, owner, point)
            proposal_id = _put(_proposals, {**_binding(self, job, owner, holds_revision(result)),
                "source_polygon": source_polygon, "reference_polygon": mapped, "bbox": bbox,
                "frame_index": frame_index, "time_seconds": point.time_seconds, "hold_id": None,
                "contour_source": "user_box_local_multiframe" if support > 1 else "user_box_local_colour",
                "score": None}, 64)
            return {"frame_index": frame_index, "source_polygon": source_polygon,
                    "reference_polygon": mapped, "bbox": bbox, "supporting_frames": support,
                    "proposal_id": proposal_id}

    def add_hold_at_point(self, job_id: str, owner: str, point: ReplayHoldPoint) -> dict:
        """Save one traced hold to the draft without recomputing contacts or video."""
        if point.proposal_id:
            return editor_commit(self, job_id, owner, point.proposal_id)
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
        return self._save_hold_edits(job_id, job, result, source, event)

    def undo_clicked_hold(self, job_id: str, owner: str, review_version: int | None = None) -> dict:
        with self._lock:
            job = self._read(job_id)
            if job.get("owner") != owner:
                raise HTTPException(404, "未找到复盘任务")
            if job.get("status") not in {"succeeded", "awaiting_hold_review"} or (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘当前不能撤销补点。")
            if job.get("segment_reviews"):
                raise HTTPException(409, "已有动作段人工复核。请先撤销动作段复核，再修改岩点。")
            result = copy.deepcopy(hold_review_input(job))
            clicked = [hold for hold in result.get("holds") or []
                       if hold.get("identity_source") in {"user_confirmed_video_click", "user_confirmed_video_candidate"}
                       and (review_version is None or hold.get("review_version") == review_version)]
            if not clicked:
                raise HTTPException(409, "这次补点已撤销或不存在，请刷新补点记录。")
            hold = max(clicked, key=lambda item: int(item.get("review_version") or 0))
            source = self._media_path(job_id, job, "source_video")
            if (job.get("media") or {}).get("source_video", {}).get("status") != "available" or not source.is_file():
                raise HTTPException(409, "原视频已删除，无法重算撤销后的复盘。")
            previous = next((event.get("previous_hold") for event in reversed(job.get("hold_review_history") or [])
                             if event.get("version") == hold.get("review_version") and event.get("operation") == "edit_hold_contour"), None)
            result["holds"] = ([previous if item["id"] == hold["id"] else item for item in result["holds"]]
                               if previous else [item for item in result["holds"] if item["id"] != hold["id"]])
            original_edit = next((item for item in job.get("hold_review_history") or []
                                  if item.get("version") == hold.get("review_version")), {})
            for candidate in original_edit.get("removed_candidates") or []:
                if (candidate not in (result.get("hold_candidates") or []) and not any(
                        box_iou(candidate["bbox"], kept["bbox"]) >= .7 for kept in result["holds"])):
                    result.setdefault("hold_candidates", []).append(copy.deepcopy(candidate))
            event = {"version": len(job.get("hold_review_history") or []) + 1,
                     "operation": "undo_add_hold_at_point" if hold.get("identity_source") == "user_confirmed_video_click" else "undo_promote_candidate",
                     "hold_id": hold["id"],
                     "target_review_version": hold["review_version"],
                     "reviewed_at": utcnow()}
        return self._save_hold_edits(job_id, job, result, source, event)

    def undo_last_clicked_hold(self, job_id: str, owner: str) -> dict:
        return self.undo_clicked_hold(job_id, owner)

    def remove_hold(self, job_id: str, owner: str, hold_id: int) -> dict:
        with self._lock:
            job = self.get(job_id, owner, private=True)
            if job.get("status") not in {"succeeded", "awaiting_hold_review"} or job.get("segment_reviews"):
                raise HTTPException(409, "请先完成任务并撤销动作段复核，再修改岩点")
            result = copy.deepcopy(hold_review_input(job))
            hold = next((item for item in result.get("holds") or [] if item["id"] == hold_id), None)
            if hold is None:
                raise HTTPException(404, "未找到岩点")
            source = self._media_path(job_id, job, "source_video")
            if (job.get("media") or {}).get("source_video", {}).get("status") != "available" or not source.is_file():
                raise HTTPException(409, "原视频已删除，无法修改岩点")
            result["holds"] = [item for item in result["holds"] if item["id"] != hold_id]
            event = {"version": len(job.get("hold_review_history") or []) + 1,
                     "operation": "remove_hold", "hold_id": hold_id, "hold": hold,
                     "reviewed_at": utcnow()}
        return self._save_hold_edits(job_id, job, result, source, event)

    def confirm_all_holds(self, job_id: str, owner: str, revision: str) -> dict:
        with self._lock:
            job = self.get(job_id, owner, private=True)
            if job.get("status") not in {"awaiting_hold_review", "succeeded"} or job_id in self._active_hold_renders:
                raise HTTPException(409, "请先完成岩点修改，再确认全部岩点")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "任务正在删除")
            draft = hold_review_input(job)
            if not draft.get("holds"):
                raise HTTPException(422, "请至少确认一个线路岩点")
            if revision != holds_revision(draft):
                raise HTTPException(409, "岩点已更新，请重新检查并确认全部岩点")
            if not job.get("hold_edit_draft"):
                return self._public(self.update(job_id, holds_confirmation={
                    "revision": revision, "confirmed_at": utcnow(), "owner": owner}))
            if job.get("segment_reviews"):
                raise HTTPException(409, "请先撤销动作段复核，再确认岩点并本地分析")
            if (job.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
                raise HTTPException(409, "线路回放正在制作，请完成或取消后再确认岩点")
            source = self._media_path(job_id, job, "source_video")
            if not source.is_file() or job.get("media", {}).get("source_video", {}).get("status") != "available":
                raise HTTPException(409, "原视频已删除，无法本地重新分析")
            result = copy.deepcopy(job["result"])
            result.update(job["hold_edit_draft"])
            event = {"version": len(job.get("hold_review_history") or []) + 1,
                     "operation": "confirm_all_holds", "reviewed_at": utcnow(),
                     "confirmed_revision": revision}
            self._active_hold_renders.add(job_id)
            if job.get("cancel_requested"):
                self.update(job_id, cancel_requested=False)
        try:
            return self._compute_and_save_holds(job_id, job, result, source, event)
        finally:
            with self._lock:
                self._active_hold_renders.discard(job_id)

    def start_analysis(self, job_id: str, owner: str, consent: dict) -> dict:
        with self._lock:
            job = self.get(job_id, owner, private=True)
            if job.get("status") not in {"awaiting_hold_review", "succeeded", "failed", "cancelled"} or job_id in self._active_hold_renders:
                raise HTTPException(409, "任务正在处理，请稍后再试")
            if (job.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "任务正在删除")
            draft = skeleton_draft() if consent.get('skip_holds') else hold_review_input(job)
            revision = holds_revision(draft)
            if not draft.get("skeleton_only") and (not draft.get("holds") or (job.get("holds_confirmation") or {}).get("revision") != revision):
                raise HTTPException(409, "请先补点、删点并确认全部岩点，再开始本地分析")
            if (draft.get("visual_replay") or {}).get("status") in {"queued", "running"}:
                raise HTTPException(409, "线路回放正在制作，请稍后再试")
            source = self._media_path(job_id, job, "source_video")
            if not source.is_file() or job.get("media", {}).get("source_video", {}).get("status") != "available":
                raise HTTPException(409, "原视频已删除，无法重新分析")
            attempt = int(job.get("attempt") or 1) + bool(job.get("analysis_runs"))
            consent = {**consent, "attempt": attempt}
            # Freeze only the reviewed geometry. Pose requests must use this snapshot.
            snapshot = {key: copy.deepcopy(draft.get(key)) for key in
                        ("holds", "hold_candidates", "hold_evidence", "models", "route", "hold_review_version", "skeleton_only")}
            if job.get("result"):
                _atomic_json(self._path(job_id).parent / f"analysis-before-{uuid.uuid4().hex}.json", {
                    "result": job["result"], "automatic_result": job.get("automatic_result"),
                    "segment_reviews": job.get("segment_reviews"), "media": job.get("media"),
                    "saved_at": utcnow(), "attempt": job.get("attempt"),
                })
            media = copy.deepcopy(job.get("media") or {})
            media["source_video"]["delete_at"] = None
            return self._public(self.update(
                job_id, status="queued", stage="等待本地姿态分析", progress=0,
                attempt=attempt, hold_draft=snapshot, hold_edit_draft=None, skeleton_only=bool(draft.get("skeleton_only")),
                analysis_request={"revision": revision, "attempt": attempt, "requested_at": utcnow(), "provider": "local-rtmw",
                                  "sampling": consent.get('sampling') or {}},
                paid_analysis_request=None,
                consent_history=[*(job.get("consent_history") or []), consent],
                media=media, error=None, error_code=None, cancel_requested=False,
                started_at=None, finished_at=None))

    def start_paid_analysis(self, job_id: str, owner: str, consent: dict) -> dict:
        """Compatibility alias; new work always uses the local analysis gate."""
        return self.start_analysis(job_id, owner, consent)

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
            result = copy.deepcopy(hold_review_input(job))
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
            sample_group = ReplayAnalyzerBase._route_colour(str((result.get("route") or {}).get("color") or job.get("route_color") or ""))
            if sample_group not in ROUTE_COLOR_NAMES and sample.get("rgb"):
                sample_lab = cv2.cvtColor(np.uint8([[sample["rgb"]]]), cv2.COLOR_RGB2LAB)[0, 0]
                sample_group = lab_color_name(sample_lab, twelve_colors=True)
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
        return self._save_hold_edits(job_id, job, result, source, event)

    def _save_hold_edits(self, job_id: str, job: dict, result: dict,
                         source: Path, event: dict) -> dict:
        """Stage each edit atomically; global confirmation alone can analyze the batch."""
        with self._lock:
            current = self._read(job_id)
            if job_id in self._active_hold_renders:
                raise HTTPException(409, "岩点复盘正在更新，请稍后再试")
            if visual_input_version(current.get("result") or {}, current.get("segment_reviews")) != visual_input_version(job.get("result") or {}, job.get("segment_reviews")):
                raise HTTPException(409, "复盘内容已更新，请刷新后重试")
            if (current.get("deletion") or {}).get("state") == "queued":
                raise HTTPException(409, "这条复盘正在删除")
            if current.get("status") not in {"succeeded", "awaiting_hold_review"}:
                raise HTTPException(409, "当前任务不能修改岩点")
            if holds_revision(hold_review_input(current)) != holds_revision(hold_review_input(job)):
                raise HTTPException(409, "岩点已更新，请刷新后重试")
            if (current.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
                raise HTTPException(409, "线路回放正在制作，请完成或取消后再修改岩点")
            result["hold_review_version"] = int(event["version"])
            draft_key = "hold_draft" if current.get("status") == "awaiting_hold_review" else "hold_edit_draft"
            return self._public(self.update(
                job_id, **{draft_key: hold_geometry(result)}, holds_confirmation=None,
                paid_analysis_request=None, analysis_request=None,
                hold_review_history=[*(current.get("hold_review_history") or []), event]))

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
        contact_trace = []
        attempt = ReplayAnalyzerBase._contacts(records, result["holds"], sample_fps, source_fps=video.fps, trace=contact_trace)
        attempt['contact_evidence'] = {'version':1,'basis':'projected_joint_and_duration_not_physical_contact_proof','frames':contact_trace}
        add_attempt_source_times(attempt, samples, video)
        attempt["action_steps"] = build_action_steps(attempt.get("contacts") or [])
        result["attempt"] = attempt
        attempt["segments"] = build_segments(result)
        result["hold_review_version"] = version
        warning = "全部岩点修订已确认，已复用保存的骨架统一本地重算接触；未新增姿态请求。"
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
                        visual_input_version(job.get("result") or {}, job.get("segment_reviews")) or
                        holds_revision(hold_review_input(current)) != event["confirmed_revision"])

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
                               hold_edit_draft=None, paid_analysis_request=None, analysis_request=None,
                               holds_confirmation={"revision": holds_revision(result),
                                                   "confirmed_at": event["reviewed_at"], "owner": current["owner"]},
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

    def refresh_route_map(self, job_id: str, owner: str) -> dict:
        """Render saved evidence into a new file; never request or recompute poses."""
        with self._lock:
            job = self.get(job_id, owner, private=True)
            if (job.get("status") != "succeeded" or not job.get("result")
                    or job.get("deletion") or job_id in self._active_hold_renders
                    or (job["result"].get("visual_replay") or {}).get("status") in {"queued", "running"}
                    or any((job.get(key) or {}).get("status") in {"queued", "running"}
                           for key in ("action_task", "action_export"))):
                raise HTTPException(409, "请等待当前处理完成后，再本地更新岩点图")
            source = self._media_path(job_id, job, "source_video")
            if ((job.get("media", {}).get("source_video") or {}).get("status") != "available"
                    or not source.is_file()):
                raise HTTPException(409, "原片已不可用，无法重新生成岩点图；旧复盘仍保留")
            self._active_hold_renders.add(job_id)
            expected_revision = holds_revision(hold_review_input(job))
            result = copy.deepcopy(job["result"])
            target = self._path(job_id).parent / f"overlay-map-{uuid.uuid4().hex}.webm"

        def cancelled() -> bool:
            try:
                current = self.get(job_id, private=True)
            except HTTPException:
                return True
            return bool(current.get("cancel_requested") or current.get("deletion")
                        or current.get("status") != "succeeded"
                        or holds_revision(hold_review_input(current)) != expected_revision
                        or current.get("result") != job["result"])

        try:
            result["overlay"] = render_replay_overlay_video(source, target, result, cancelled=cancelled)
            with self._lock:
                if cancelled():
                    raise HTTPException(409, "复盘内容已更新，已保留上一版，请刷新后重试")
                current = self.get(job_id, owner, private=True)
                media = copy.deepcopy(current.get("media") or {})
                previous = media.get(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND)
                history = list(current.get("overlay_history") or [])
                if previous and previous.get("status") == "available":
                    history.append({"media": copy.deepcopy(previous),
                                    "overlay": copy.deepcopy(job["result"].get("overlay")),
                                    "visual_replay": copy.deepcopy(job["result"].get("visual_replay"))})
                media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND] = {
                    "kind": REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, "status": "available",
                    "storage_name": target.name, "retention_mode": REPLAY_RETENTION_KEEP,
                    "delete_at": None, "deleted_at": None, "size_bytes": target.stat().st_size,
                    "checksum_sha256": self._sha256(target), "content_type": "video/webm",
                    "filename": f"{Path(job.get('original_name') or 'climb-replay').stem}-当前四肢岩点复盘.webm",
                    "generated_at": utcnow(), "visual_replay": copy.deepcopy(result.get("visual_replay")),
                }
                return self._public(self.update(job_id, result=result, media=media, overlay_history=history))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            with self._lock:
                self._active_hold_renders.discard(job_id)

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
        high_resolution_source = {"storage_name": raw.name,
            "checksum_sha256": self._sha256(raw), "size_bytes": raw.stat().st_size,
            "trim_start_seconds": preparation.get("trim_start_seconds") or 0,
            "retention_mode": REPLAY_RETENTION_KEEP}
        high_resolution_source['video'] = asdict(probe_video(raw))
        high_resolution_source['time_mapping'] = 'prepared_timestamp_plus_trim_start; original_decode_timestamp'
        source.update(retention_mode=REPLAY_RETENTION_KEEP, delete_at=None)
        updated = self.update(job_id, input_path=str(target), source_path=None,
                              high_resolution_source=high_resolution_source,
                              video=asdict(info), media=media, preparation=preparation,
                              stage="视频已整理，准备分析", progress=12)
        return updated

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
            if not re.fullmatch(r"overlay-(?:review-[1-9][0-9]*|(?:visual|map)-[a-f0-9]{32})\.webm", expected_name):
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
        source.update(retention_mode=REPLAY_RETENTION_KEEP, delete_at=None)
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
            changes["high_resolution_source"] = None
            clear_editor_cache(self, job_id)
        return self._public(self.update(job_id, **changes))

    def cleanup_due_media(self) -> list[str]:
        deleted = []
        for path in self.jobs.glob("*/job.json"):
            try:
                with self._lock:
                    job = json.loads(path.read_text(encoding="utf-8"))
                # Historical deadlines do not authorize deleting retained originals.
                with self._lock:
                    job = self._read(job["id"])
                    overlay = (job.get("media") or {}).get(REPLAY_OVERLAY_MEDIA_KIND) or {}
                    if overlay.get("status") == "cleanup_pending":
                        self.discard_overlay(job["id"])
                    if job.get("status") in {"failed", "cancelled", "succeeded"} and job["id"] not in self._active_hold_renders:
                        (path.parent / ".preparing.mp4").unlink(missing_ok=True)
                        if (job.get("result") or {}).get("visual_replay", {}).get("status") not in {"queued", "running"}:
                            for temporary in path.parent.glob(".visual-*"):
                                if temporary.is_dir() and temporary.parent.resolve() == path.parent.resolve():
                                    shutil.rmtree(temporary)
                            current = ((job.get("media") or {}).get(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND) or {}).get("storage_name")
                            saved_overlays = {item.get("media", {}).get("storage_name")
                                              for item in job.get("overlay_history") or []}
                            for obsolete in path.parent.glob("overlay-visual-*.webm"):
                                if obsolete.name != current and obsolete.name not in saved_overlays:
                                    obsolete.unlink(missing_ok=True)
            except (OSError, TypeError, ValueError, json.JSONDecodeError, HTTPException):
                continue
        return deleted

    def request_delete(self, job_id: str, owner: str) -> dict:
        with self._lock:
            return self._request_delete_locked(job_id, owner)

    def _request_delete_locked(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        clear_editor_cache(self, job_id)
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
                    source.update(retention_mode=REPLAY_RETENTION_KEEP, delete_at=None)
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
        if job["status"] in {"queued", "awaiting_hold_review"}:
            changes.update(status="cancelled", progress=job["progress"],
                           error_code="cancelled_by_user", finished_at=utcnow())
        result = self._public(self.update(job_id, **changes))
        if job["status"] in {"queued", "awaiting_hold_review"}:
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
            paid_analysis_request=None, analysis_request=None,
            worker_failure=None,
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


class ClimbReplayManager(ReplayJobQueue):
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

    def _handle_worker_failure(self, action: str, job_id: str, exc: Exception) -> None:
        """Record safe failures using the legacy logger and clock namespace."""
        frames = []
        traceback = exc.__traceback__
        while traceback is not None:
            code = traceback.tb_frame.f_code
            frames.append({"file": Path(code.co_filename).name,
                           "function": code.co_name, "line": traceback.tb_lineno})
            traceback = traceback.tb_next
        diagnostic = {"exception_type": type(exc).__name__, "frames": frames[-8:]}
        identifier = getattr(exc, "name", None)
        if isinstance(identifier, str) and identifier.isidentifier():
            diagnostic["identifier"] = identifier
        # Exception text can contain provider credentials or private paths.
        logging.getLogger(__name__).error("Replay worker stopped: %s", json.dumps(diagnostic))
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
                        error_code="worker_failed", worker_failure=diagnostic, finished_at=utcnow(),
                    )
            except Exception:
                pass

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
        analysis_request = job.get("analysis_request") or {}
        draft = job.get("hold_draft") or {}
        analysis_authorized = bool(
            analysis_request.get("attempt") == int(job.get("attempt") or 1)
            and analysis_request.get("revision") == holds_revision(draft)
            and (draft.get('skeleton_only') or (
                (job.get("holds_confirmation") or {}).get("revision") == holds_revision(draft)
                and draft.get("holds"))))
        if analysis_request and not analysis_authorized:
            self.store.update(job_id, status="awaiting_hold_review", stage="请重新确认全部岩点",
                              paid_analysis_request=None, analysis_request=None, holds_confirmation=None)
            return
        if analysis_authorized and not active_consent(job):
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(
                job_id, status="failed", stage="缺少有效授权", progress=0,
                error="本次任务没有有效的本地分析授权，请重新启动分析",
                finished_at=utcnow(),
            )
            return
        self.store.update(job_id, status="running", stage="检查视频", progress=5,
                          started_at=utcnow(), error=None, error_code=None)
        attempt = int(job.get("attempt") or 1)
        run_started = False
        rerun_target = (self.store._path(job_id).parent / f"overlay-visual-{uuid.uuid4().hex}.webm"
                        if analysis_authorized and job.get("result") else None)

        def discard_attempt_overlay() -> None:
            if rerun_target is not None:
                rerun_target.unlink(missing_ok=True)
            else:
                self.store.discard_overlay(job_id)

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
            if not analysis_authorized and any(c.get('skip_holds') for c in job.get('consent_history', [])):
                self.store.update(job_id, status='awaiting_hold_review', hold_draft=skeleton_draft())
                self.store.start_analysis(job_id, job['owner'], {**job['consent_history'][-1], 'event': 'granted', 'skip_holds': True})
                job = self.store.get(job_id, private=True)
                analysis_authorized = True
            if not analysis_authorized:
                # Uploads and retries stop here, before SDK initialization or any pose request.
                draft = job.get("hold_draft")
                if not draft:
                    draft_args = {
                        "route_color": job["route_color"], "video_info": info,
                        "route_color_sample": job.get("route_color_sample"),
                        "saved_route_reference": job.get("saved_route_reference"),
                        "trim_start_seconds": float((job.get("preparation") or {}).get("trim_start_seconds") or 0),
                        "progress": progress, "cancelled": is_cancelled,
                    }
                    draft = self.analyzer.detect_holds(Path(job["input_path"]), **draft_args)
                if is_cancelled():
                    raise ReplayCancelled()
                self.store.update(job_id, status="awaiting_hold_review", stage="请补点、删点并确认全部岩点",
                                  progress=100, hold_draft=draft, holds_confirmation=None,
                                  paid_analysis_request=None, analysis_request=None, error=None, error_code=None)
                return
            if hasattr(self.analyzer, 'configure_sampling'):
                self.analyzer.configure_sampling((job.get('analysis_request') or {}).get('sampling'))
            if hasattr(self.analyzer, 'configure_cache'):
                from .replay_actions import digest
                self.analyzer.configure_cache(self.store._path(job_id).parent / '.pose-cache.json', {
                    'source_sha256':self.store._sha256(Path(job['input_path'])),
                    'video':job['video'], 'pose_model':self.analyzer.pose_model,
                    'pose_code_version':'raw-detector-per-box-pose-cache-v3',
                    'holds_sha256':digest((job.get('hold_draft') or {}).get('holds', []))})
            initial_analysis = self.analyzer.analysis_contract(info)
            self.store.start_analysis_run(job_id, attempt, initial_analysis)
            run_started = True
            analyze_args = {
                "route_color": job["route_color"], "video_info": info,
                "progress": progress, "cancelled": is_cancelled, "telemetry": telemetry,
                "confirmed_holds": job["hold_draft"],
            }
            if job.get("route_color_sample"):
                analyze_args["route_color_sample"] = job["route_color_sample"]
                if job["route_color_sample"].get("source") == "video":
                    analyze_args["trim_start_seconds"] = float(job.get("preparation", {}).get("trim_start_seconds") or 0)
            if job.get("saved_route_reference"):
                analyze_args["saved_route_reference"] = job["saved_route_reference"]
            if rerun_target is not None:
                analyze_args["overlay_target"] = rerun_target
            result = self.analyzer.analyze(Path(job["input_path"]), **analyze_args)
            if job.get('skeleton_only'):
                result = without_hold_data(result)
            if result.get('pose_samples') and result.get('video'):
                from .replay_actions import organize
                from .replay_action_features import enrich_action_features
                feature_started = time.perf_counter()
                organized = enrich_action_features(organize({**job, 'result':result}), {**job, 'result':result})
                result.update(action_evidence=organized['action_evidence'], action_groups=organized['groups'])
                if job.get('skeleton_only'):
                    result = without_hold_data(result)
                result['analysis']['timings_ms']['features'] = round((time.perf_counter()-feature_started)*1000)
                requested = (job.get('analysis_request') or {}).get('requested_at')
                if requested:
                    result['analysis']['timings_ms']['local_elapsed_from_start'] = round(
                        (datetime.now(timezone.utc)-datetime.fromisoformat(requested)).total_seconds()*1000)
                self.store.update_analysis_run(job_id, attempt, result['analysis'])
            if is_cancelled():
                raise ReplayCancelled()
            if rerun_target is not None and not rerun_target.is_file():
                raise RuntimeError("新的复盘视频未生成，已保留原版本")
            overlay_path = Path(job["input_path"]).with_name(REPLAY_OVERLAY_FILENAME)
            if rerun_target is None and overlay_path.is_file():
                self.store.register_overlay(job_id, result)
            self.store.finish_analysis_run(job_id, attempt, state="succeeded")
            self.store.schedule_source_cleanup(job_id, outcome="succeeded")
            media = copy.deepcopy(self.store.get(job_id, private=True).get("media") or {})
            if rerun_target is not None:
                media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND] = {
                    "kind": REPLAY_REVIEWED_OVERLAY_MEDIA_KIND, "status": "available",
                    "storage_name": rerun_target.name, "retention_mode": REPLAY_RETENTION_KEEP,
                    "delete_at": None, "deleted_at": None, "size_bytes": rerun_target.stat().st_size,
                    "checksum_sha256": self.store._sha256(rerun_target), "content_type": "video/webm",
                    "filename": "重新分析复盘.webm", "generated_at": utcnow(),
                    "visual_replay": copy.deepcopy(result.get("visual_replay")),
                }
                self.store._add_reference_media(media, result, rerun_target.parent)
            elif (media.get(REPLAY_REVIEWED_OVERLAY_MEDIA_KIND) or {}).get("status") == "available":
                media[REPLAY_REVIEWED_OVERLAY_MEDIA_KIND]["status"] = "superseded"
            self.store.update(job_id, status="succeeded", stage="分析完成", progress=100,
                              result=result, media=media, segment_reviews={},
                              paid_analysis_request=None, analysis_request=None, error_code=None, finished_at=utcnow())
        except (ReplayCancelled, InterruptedError):
            discard_attempt_overlay()
            if run_started:
                self.store.finish_analysis_run(
                    job_id, attempt, state="cancelled", error_code="cancelled_by_user",
                )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="succeeded" if rerun_target else "cancelled",
                              stage="重分析已取消，保留原复盘" if rerun_target else "已取消",
                              error=None, error_code="cancelled_by_user", finished_at=utcnow())
        except ReplayConfigurationError as exc:
            discard_attempt_overlay()
            if run_started:
                self.store.finish_analysis_run(
                    job_id, attempt, state="failed", error_code="pose_provider_unconfigured",
                )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(
                job_id, status="succeeded" if rerun_target else "failed",
                stage="本地骨架模型不可用，保留原复盘" if rerun_target else "本地骨架模型不可用", progress=0,
                error=str(exc)[:1000], error_code="pose_provider_unconfigured",
                finished_at=utcnow(),
            )
        except Exception as exc:  # the public job exposes a concise actionable error
            discard_attempt_overlay()
            code = "analysis_failed" if run_started else "media_processing_failed"
            if run_started:
                self.store.finish_analysis_run(
                    job_id, attempt, state="failed", error_code=code,
                )
            self.store.schedule_source_cleanup(job_id, outcome="failed")
            self.store.update(job_id, status="succeeded" if rerun_target else "failed",
                              stage="重分析失败，保留原复盘" if rerun_target else ("分析失败" if run_started else "视频无法处理"), progress=0,
                              error=str(exc)[:1000], error_code=code,
                              finished_at=utcnow())

    def close(self) -> None:
        if getattr(self.store, 'prepared_previews', None):
            self.store.prepared_previews.close()
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


class ReplayAnalyzerBase:
    """Shared local hold, contact, sampled evidence and replay rendering pipeline."""

    hold_model = "local-climbing-mask-rcnn"
    pose_model = "unconfigured"
    _coco_parts = {
        0: "nose", 1: "left_eye", 2: "right_eye", 3: "left_ear", 4: "right_ear",
        5: "left_shoulder", 6: "right_shoulder", 7: "left_elbow", 8: "right_elbow",
        9: "left_wrist", 10: "right_wrist", 11: "left_hip", 12: "right_hip",
        13: "left_knee", 14: "right_knee", 15: "left_ankle", 16: "right_ankle",
    }

    def _prepare_pose_run(self, confirmed_holds: dict) -> None:
        raise NotImplementedError

    def _pose_frame(self, frame, **kwargs):
        raise NotImplementedError

    def _sampling_positions(self, video_info: VideoInfo) -> tuple[float, np.ndarray]:
        sample_fps = min(self.pose_fps, video_info.fps)
        positions = np.unique(np.clip(
            np.rint(np.arange(0, video_info.duration_seconds, 1 / sample_fps) * video_info.fps).astype(int),
            0, video_info.frame_count - 1,
        ))
        return sample_fps, positions

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
    def _hold_frames(video: Path, info: VideoInfo, sample: dict | None,
                     cancelled: Callable[[], bool] | None = None) -> list[tuple[int, np.ndarray]]:
        total = info.frame_count
        cancelled = cancelled or (lambda: False)
        sample_index = None
        profile = os.getenv("CLIMB_REPLAY_HOLD_FRAME_PROFILE", "4")
        frame_budget = int(profile) if profile in {"6", "8"} else 4
        indices = {min(total - 1, int(round(value))) for value in np.linspace(
            total * (.02 if frame_budget > 4 else .08), total * (.98 if frame_budget > 4 else .92), frame_budget)}
        if profile == "seconds":
            # Offline coverage experiment; default remains four frames.
            indices.update(min(total-1,round(second*info.fps))
                           for second in range(math.ceil(info.duration_seconds)))
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
                if cancelled():
                    raise InterruptedError("选帧已取消")
                # Experimental profiles seek a clearer neighbor; default four-frame
                # behavior stays frozen until the ten-video comparison is reviewed.
                if frame_budget > 4 and index != sample_index:
                    options = []
                    for offset in (-round(info.fps * .12), 0, round(info.fps * .12)):
                        if cancelled():
                            raise InterruptedError("选帧已取消")
                        candidate_index = max(0, min(total - 1, index + offset))
                        cap.set(cv2.CAP_PROP_POS_FRAMES, candidate_index)
                        candidate_ok, candidate = cap.read()
                        if candidate_ok:
                            small = cv2.resize(candidate, (max(1, candidate.shape[1] // 4), max(1, candidate.shape[0] // 4)))
                            sharp = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
                            options.append((sharp, candidate_index, candidate))
                    if options:
                        _, selected_index, selected = max(options, key=lambda item: item[0])
                        if not any(existing == selected_index for existing, _ in frames):
                            frames.append((selected_index, selected))
                        continue
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
                     cancelled: Callable[[], bool],
                     trace: list[dict] | None = None,
                     reference_source_frame: int | None = None,
                     source_video: Path | None = None) -> tuple[list[dict], list[dict], dict, dict | None, str]:
        if not frames:
            raise RuntimeError("没有从视频中读取到有效画面")
        images = [frame for _, frame in frames]
        sharpness = [cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
                     for frame in images]
        reference_index = int(np.argmax(sharpness))
        if reference_source_frame is not None:
            reference_index = next((index for index,item in enumerate(frames)
                                    if item[0]==reference_source_frame),-1)
            if reference_index < 0:
                raise ValueError("Frozen reference frame is missing from experiment")
        requested_frame = route_color_sample.get("prepared_frame_index") if route_color_sample else None
        if requested_frame is not None:
            reference_index = next((index for index, item in enumerate(frames)
                                    if item[0] == requested_frame), reference_index)
        reference = images[reference_index]
        from core.replay_hold_fusion import image_content_bounds
        content_bounds = image_content_bounds(reference)
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
        native_metadata=[]
        outputs, model_version = _climbing_model_masks_batch(
            images, deadline, cancelled,
            lambda stage, value: progress(stage, 16 + round(max(0, value - 20) * .37)),
            pack_masks=True,
            reuse_model=True,
            include_volumes=True, native_metadata=native_metadata,
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
            mask, rgb, sample_region = sample_clicked_hold(
                frame, [restore_mask(encoded, frame) for encoded in masks], (px, py))
            sample_polygon = native_mask_polygon(mask)
            if len(sample_polygon) >= 3 and transformations[sample_frame_index] is not None:
                sampled_bbox = polygon_bbox(transform_polygon(
                    [[float(point[0][0]), float(point[0][1])] for point in sample_polygon],
                    transformations[sample_frame_index], width, height))
            actual_sample.update(rgb=rgb, hex="#{:02x}{:02x}{:02x}".format(*rgb),
                                 evidence="segmented_hold_interior", frame_index=frames[sample_frame_index][0],
                                 colour_region=sample_region)
        detections: list[list[dict]] = []
        target = cls._route_colour(route_color)
        if target not in ROUTE_COLOR_NAMES and actual_sample and actual_sample.get('rgb'):
            target = lab_color_name(cv2.cvtColor(np.uint8([[actual_sample['rgb']]]),
                                               cv2.COLOR_RGB2LAB)[0, 0], twelve_colors=True)
        for frame_index, ((source_index, frame), (masks, scores), matrix) in enumerate(
                zip(frames, outputs, transformations)):
            if matrix is None:
                if trace is not None:
                    trace.append({"stage": "registration", "source_frame": source_index,
                                  "status": "rejected", "reason": registrations[frame_index].get("reason"),
                                  "model_candidates": len(masks)})
                detections.append([])
                continue
            frame_holds = []
            for mask_index, (encoded, score) in enumerate(zip(masks, scores)):
                observation_id = f"frame-{source_index}-mask-{mask_index}"
                if cancelled():
                    raise ReplayCancelled()
                mask = restore_mask(encoded, frame)
                polygon = native_mask_polygon(mask)
                if len(polygon) < 3:
                    if trace is not None:
                        trace.append({"observation_id": observation_id, "stage": "contour",
                                      "status": "rejected", "reason": "invalid_native_contour"})
                    continue
                source_polygon = [[float(point[0][0]), float(point[0][1])] for point in polygon]
                mapped = transform_polygon(source_polygon, matrix, width, height)
                bbox = polygon_bbox(mapped)
                if bbox[2] <= 0 or bbox[3] <= 0:
                    if trace is not None:
                        trace.append({"observation_id": observation_id, "stage": "mapping",
                                      "status": "rejected", "reason": "degenerate_mapped_contour"})
                    continue
                colour, interior, colour_evidence = observe_hold_colour(frame, mask)
                distance = region_sample_distance(frame, interior, actual_sample["rgb"]) if actual_sample else None
                material=material_observation(colour_evidence,actual_sample['rgb'] if actual_sample else None)
                colour=sample_compatible_group(colour,material,target)
                support=colour_support(frame,interior,actual_sample['rgb'],colour,target,distance,
                    colour_evidence=colour_evidence) if actual_sample else None
                candidate = (distance is not None and np.isfinite(distance) and
                             distance <= REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE and colour == target
                             if actual_sample else colour == target)
                if support:candidate=support['qualified']
                frame_holds.append({
                    "bbox": bbox, "polygon": mapped, "score": round(float(score), 4),
                    "color_group": colour, "color_source": actual_sample["source"] if actual_sample else "preset",
                    "color_evidence": colour_evidence,
                    "material_observation": material,
                    "new_body_resolution":bool(colour_evidence.get('body_resolution')),
                    "boundary_quality": boundary_quality(frame,mask),
                    "colour_support":support,
                    "native_class":native_metadata[frame_index]['classes'][mask_index] if frame_index<len(native_metadata) else 0,
                    "color_distance": round(distance, 4) if distance is not None else None,
                    "route_candidate": candidate, "route_candidate_reason": "color_sample" if actual_sample else "preset_color",
                    "identity_source": "multi_frame_geometry", "contour_source": "climbing_model_native_mask",
                    "contour_complete": all(0 < point[0] < frame.shape[1] - 1 and
                                            0 < point[1] < frame.shape[0] - 1 for point in source_polygon),
                    "contour_points": len(mapped), "source_frame": source_index,
                    "observation_id": observation_id,
                })
                if trace is not None:
                    trace.append({"stage": "mapping", "status": "retained", **frame_holds[-1]})
            detections.append(frame_holds)
        all_holds = fuse_hold_detections(detections, color_distance_limit=REPLAY_COLOR_SAMPLE_MAX_LAB_DISTANCE,
                                         sample_group=target, evidence_policy='material_boundary')
        if trace is not None:
            trace.extend({"stage": "fusion", "status": "retained", **hold} for hold in all_holds)
        if sampled_bbox is not None:
            for hold in all_holds:
                if cls._iou(hold["bbox"], sampled_bbox) > .5:
                    hold["identity_source"] = "user_sampled_hold"
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
                sample_group = target
                holds, candidates, sampled_selection = select_sampled_route_holds(
                    all_holds, sample_group=sample_group,
                    minimum_appearances=minimum_appearances,
                    trace=trace,
                    content_bounds=content_bounds,
                )
                selection = "sampled_colour_geometry_needs_review"
            else:
                holds, candidates, sampled_selection = select_sampled_route_holds(
                    all_holds, sample_group=target,
                    minimum_appearances=minimum_appearances,
                    trace=trace,
                    content_bounds=content_bounds,
                )
                selection = "minimal_colour_geometry_needs_review"
            candidates.extend(item for item in remaining if item.get("appearances") == 0)
        recovery=None
        if not confirmed and actual_sample and actual_sample.get('rgb'):
            from core.replay_hold_recovery import recover_hold_candidates
            added,extra_rejected,recovery=recover_hold_candidates(frames=frames,matrices=transformations,
                reference_frame=frames[reference_index][0],detections=detections,native_outputs=outputs,
                all_holds=all_holds,existing=holds,sample_group=target,sample_rgb=actual_sample['rgb'],
                model_fn=_climbing_model_masks_batch,polygon_fn=native_mask_polygon,
                deadline=deadline,cancelled=cancelled,progress=progress,trace=trace)
            holds.extend(added);candidates.extend(extra_rejected)
        expansion = None
        if not confirmed:
            from core.replay_hold_expansion import expand_native_evidence, EXPANSION_VERSION
            from core.replay_hold_resampling import resample_weak_candidates, refine_weak_candidates, refine_native_fragments
            expansion = {'version': EXPANSION_VERSION, 'accepted_contours_preserved': True}
            sample_rgb = actual_sample.get('rgb') if actual_sample else None
            try:
                additions, detail = expand_native_evidence(frames=frames, outputs=outputs,
                    detections=detections, existing=holds, sample_group=target,
                    sample_rgb=sample_rgb, trace=trace)
                holds.extend(additions)
                expansion.update(detail)
            except (ReplayCancelled, InterruptedError):
                raise
            except (RuntimeError, ValueError, OSError, ImportError, TimeoutError) as exc:
                expansion.update(status='native_expansion_unavailable', reason=type(exc).__name__, added=0)
            try:
                extra_frames, extra_outputs, extra_detections, resampling = resample_weak_candidates(
                    source_video=source_video, frames=frames, outputs=outputs, detections=detections,
                    existing=holds, sample_group=target, sample_rgb=sample_rgb,
                    reference_frame=frames[reference_index][0], model_fn=_climbing_model_masks_batch,
                    polygon_fn=native_mask_polygon, alignment_fn=align_to_reference,
                    deadline=deadline, cancelled=cancelled, progress=progress)
                expansion['resampling'] = resampling
                if extra_frames:
                    additions, detail = expand_native_evidence(frames=frames+extra_frames,
                        outputs=outputs+extra_outputs, detections=detections+extra_detections,
                        existing=holds, sample_group=target, sample_rgb=sample_rgb, trace=trace)
                    holds.extend(additions)
                    expansion['resampling_added'] = detail['added']
                    expansion['added'] = expansion.get('added', 0)+detail['added']
                    additions, refinement = refine_weak_candidates(frames=extra_frames,
                        outputs=extra_outputs, detections=extra_detections, existing=holds,
                        sample_group=target, sample_rgb=sample_rgb, reference=reference,
                        alignment_fn=align_to_reference, polygon_fn=native_mask_polygon,
                        deadline=deadline, cancelled=cancelled, progress=progress, trace=trace)
                    holds.extend(additions)
                    expansion['weak_refinement'] = refinement
                    expansion['added'] += len(additions)
            except (ReplayCancelled, InterruptedError):
                raise
            except (RuntimeError, ValueError, OSError, ImportError, TimeoutError) as exc:
                expansion['resampling'] = {'reason':'additional_observation_unavailable',
                    'error_type':type(exc).__name__, 'accepted_contours_preserved':True}
            try:
                budget=max(0,8-(expansion.get('weak_refinement') or {}).get('prompts',0))
                additions, refinement = refine_native_fragments(frames=frames, outputs=outputs,
                    detections=detections, existing=holds, sample_group=target,
                    sample_rgb=sample_rgb, reference_frame=frames[reference_index][0],
                    alignment_fn=align_to_reference, polygon_fn=native_mask_polygon,
                    deadline=deadline, cancelled=cancelled, progress=progress,
                    trace=trace, prompt_budget=budget)
                holds.extend(additions)
                expansion['native_fragment_refinement']=refinement
                expansion['added']=expansion.get('added',0)+len(additions)
            except (ReplayCancelled, InterruptedError):
                raise
            except (RuntimeError, ValueError, OSError, ImportError, TimeoutError) as exc:
                expansion['native_fragment_refinement']={'status':'unavailable',
                    'error_type':type(exc).__name__, 'accepted_contours_preserved':True}
        holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2), hold["bbox"][0]))
        for index, hold in enumerate(holds, 1):
            hold["id"] = index
        diagnostics = {"selection": selection, "reference_frame": frames[reference_index][0],
                       "frame_profile": os.getenv("CLIMB_REPLAY_HOLD_FRAME_PROFILE", "4"),
                       "raw_model_candidates_by_frame": [len(item[0]) for item in outputs],
                       "aligned_candidates_by_frame": [len(item) for item in detections],
                       "sampled_source_frames": [item[0] for item in frames],
                       "frames_decoded": len(frames), "frames_aligned": sum(item is not None for item in transformations),
                       "registrations": registrations, "saved_route_registration": route_registration,
                       "camera_motion_px": round(motion_px, 2),
                       "confirmed_members_matched": sum(item.get("appearances", 0) > 0 for item in confirmed),
                       "confirmed_members_projected": sum(item.get("appearances", 0) == 0 for item in candidates),
                       "all_candidates": len(all_holds), "sampled_selection": sampled_selection,
                       "hold_colour_version": REPLAY_COLOUR_VERSION,
                       "model_guided_recovery":recovery, "native_route_expansion":expansion}
        version = f"{model_version}+multiframe-aligned-v1+{REPLAY_COLOUR_VERSION}"
        if expansion is not None:version += '+'+expansion['version']
        return holds, candidates, diagnostics, actual_sample, version

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
    def _contacts(cls, records: list[dict], holds: list[dict], fps: float, *, source_fps: float | None = None,
                  trace: list | None = None, diagnostic_policy: dict | None = None) -> dict:
        # Offline one-variable comparisons share the production event/time engine.
        # These policies are deliberately absent from user settings and defaults.
        policy = diagnostic_policy or {}
        margin = float(policy.get('margin', .02))
        foot_offset = float(policy.get('foot_offset', .02))
        minimum_score = float(policy.get('minimum_score', .5))
        duration = float(policy.get('duration', .4))
        limbs = {"left_hand": 9, "right_hand": 10, "left_foot": 15, "right_foot": 16}
        dwell = max(1, round(duration * fps))
        records = sorted(records, key=lambda item: int(item.get("frame_id", -1)))
        current = {key: None for key in limbs}
        since = {key: 0 for key in limbs}
        run = {key: 0 for key in limbs}
        confirmed = {key: False for key in limbs}
        stable_at = {key: None for key in limbs}
        contacts: list[dict] = []
        holding: dict[int, dict[str, int]] = {}
        midline = []
        times = {int(r.get('frame_id', -1)): float(r.get('source_frame_id', 0)) / source_fps
                 for r in records} if source_fps else {}
        previous_time = None

        def close(key: str, frame: int) -> None:
            if current[key] is not None and confirmed[key]:
                contacts.append({"limb": key, "hold_id": current[key], "start_frame": since[key],
                                 "end_frame": max(since[key], frame - 1),
                                 "stable_frame": stable_at[key]})
            current[key], run[key], confirmed[key], stable_at[key] = None, 0, False, None

        for item in records:
            frame = int(item.get("frame_id", -1))
            if source_fps and previous_time is not None and not 0 < times[frame] - previous_time <= .6:
                for key in limbs:
                    close(key, frame)
            if source_fps:
                previous_time = times[frame]
            points = item.get("kpts_xy") or []
            scores = item.get("kpts_score") or []
            torso = [points[i] for i in (5, 6, 11, 12) if i < len(points) and points[i] != [0, 0]]
            if torso:
                midline.append({"frame": frame, "x": round(float(np.mean([p[0] for p in torso])), 5),
                                "y": round(float(np.mean([p[1] for p in torso])), 5)})
            active = {}
            for key, index in limbs.items():
                reason = None
                observed = item.get('observed', (item.get('pose_evidence') or {}).get('observed', True))
                if item.get('contact_registration_reason'):
                    reason = item['contact_registration_reason']
                elif (observed is False or item.get('interpolated') or item.get('render_mode') in {'interpolated','edge_hold'}
                        or item.get('observation_kind') in {'display_interpolation','image_supported_temporal_inference'}
                        or (item.get('pose_evidence') or {}).get('observation_kind') in {'display_interpolation','image_supported_temporal_inference'}):
                    reason = 'not_model_observation'
                elif index >= len(points) or len(points[index] or []) != 2:
                    reason = 'missing_joint'
                elif index >= len(scores) or scores[index] is None:
                    reason = 'missing_score'
                else:
                    try:
                        xy = tuple(map(float, points[index]))
                        score = float(scores[index])
                        if not all(math.isfinite(v) for v in (*xy, score)):
                            reason = 'nonfinite_joint_or_score'
                        elif not all(0 < v < 1 for v in xy):
                            reason = 'outside_image'
                        elif score < minimum_score or score > 1:
                            reason = 'weak_joint'
                    except (TypeError, ValueError):
                        reason = 'invalid_joint_or_score'
                if reason:
                    if trace is not None:
                        trace.append({'frame':frame,'source_frame':item.get('source_frame_id'),
                                      'limb':key,'state':'unknown','reason':reason})
                    close(key, frame); continue
                x, y = map(float, points[index])
                if "foot" in key:
                    y += foot_offset
                parts = [(x, y)]
                if policy.get('contact_part') == 'wholebody':
                    indices = {'left_hand':[95,99,103,107,111], 'right_hand':[116,120,124,128,132],
                               'left_foot':[17,18], 'right_foot':[20,21]}[key]
                    whole = item.get('wholebody') or {}
                    wp, ws = whole.get('kpts_xy') or [], whole.get('kpts_score') or []
                    parts = [tuple(map(float,wp[j])) for j in indices if j < len(wp) and j < len(ws)
                             and len(wp[j] or []) == 2 and ws[j] is not None
                             and all(math.isfinite(float(v)) for v in (*wp[j],ws[j]))
                             and float(ws[j]) >= minimum_score and all(0 <= float(v) <= 1 for v in wp[j])]
                choices = [hold for hold in holds if any(cls._inside(part, hold, margin) for part in parts)]
                if policy.get('reject_ambiguous') and len(choices) > 1:
                    if trace is not None:
                        trace.append({'frame':frame,'source_frame':item.get('source_frame_id'),'limb':key,
                                      'state':'unknown','reason':'competing_holds','candidate_ids':[h['id'] for h in choices]})
                    close(key,frame); continue
                chosen = min(choices, key=lambda hold: abs(x - hold["bbox"][0] - hold["bbox"][2] / 2)
                             + abs(y - hold["bbox"][1] - hold["bbox"][3] / 2)) if choices else None
                hold_id = chosen["id"] if chosen else None
                if hold_id != current[key]:
                    close(key, frame)
                    current[key], since[key] = hold_id, frame
                if hold_id is not None:
                    run[key] += 1
                    enough = times[frame] - times[since[key]] >= duration - 1e-8 if source_fps else run[key] >= dwell
                    confirmed[key] = confirmed[key] or enough
                    if confirmed[key] and stable_at[key] is None:
                        stable_at[key] = frame
                    if confirmed[key]:
                        active[key] = hold_id
                if trace is not None:
                    trace.append({'frame':frame,'source_frame':item.get('source_frame_id'),'limb':key,
                                  'state':'contact_candidate_confirmed' if confirmed[key] else 'near' if choices else 'no_support',
                                  'reason':None if confirmed[key] else 'duration_gate' if choices else 'outside_holds',
                                  'candidate_ids':[h['id'] for h in choices], 'chosen_id':hold_id,
                                  'point_xy':[x,y], 'score':scores[index], 'parts_xy':parts})
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
                           if top is not None and active.get("left_hand") == top and active.get("right_hand") == top), None)
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
        if source_fps and times:
            window_seconds = max(1 / source_fps, times.get(end, 0) - times.get(start, 0)) if start is not None and end is not None else 0
            for key in limbs:
                seconds = sum(max(0, times.get(min(c['end_frame'], clip_end), 0) - times.get(max(c['start_frame'], clip_start), 0))
                              for c in contacts if c['limb'] == key)
                per_limb[key].update(contact_seconds=round(seconds, 3),
                    coverage_of_attempt=round(min(1, seconds / window_seconds), 4) if window_seconds else None)
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

    def detect_holds(self, video: Path, *, route_color: str, video_info: VideoInfo,
                     route_color_sample: dict | None = None,
                     saved_route_reference: dict | None = None,
                     trim_start_seconds: float = 0,
                     progress: Callable[[str, int], None], cancelled: Callable[[], bool]) -> dict:
        """Local-only preparation; deliberately independent of pose credentials and SDK."""
        progress("选取清晰视频帧", 10)
        prepared_sample = dict(route_color_sample) if route_color_sample else None
        if prepared_sample and prepared_sample.get("source") == "video" and prepared_sample.get("point_xy") is not None:
            prepared_sample["trim_start_seconds"] = trim_start_seconds
            prepared_sample["prepared_frame_index"] = round(
                (float(prepared_sample["time_seconds"]) - trim_start_seconds) * video_info.fps)
        frames = self._hold_frames(video, video_info, prepared_sample, cancelled=cancelled)
        if not frames:
            raise RuntimeError("没有从视频中读取到有效画面")
        progress("本地识别并对齐岩点", 16)
        holds, candidates, evidence, sample, version = self._video_holds(
            frames=frames, route_color=route_color, route_color_sample=prepared_sample,
            saved_route_reference=saved_route_reference, deadline=time.monotonic() + 240,
            progress=progress, cancelled=cancelled, source_video=video)
        if cancelled():
            raise ReplayCancelled()
        # Even a zero-hold draft can be repaired manually before global confirmation.
        return {"schema_version": 2, "video": asdict(video_info),
                "route": {"color": route_color, "color_sample": sample},
                "models": {"holds": version}, "holds": holds,
                "hold_candidates": candidates, "hold_evidence": evidence}

    def analyze(self, video: Path, *, route_color: str, video_info: VideoInfo,
                confirmed_holds: dict | None = None,
                overlay_target: Path | None = None,
                route_color_sample: dict | None = None,
                saved_route_reference: dict | None = None,
                trim_start_seconds: float = 0,
                progress: Callable[[str, int], None], cancelled: Callable[[], bool],
                telemetry: Callable[[dict], None]) -> dict:
        if not confirmed_holds or (not confirmed_holds.get("holds") and not confirmed_holds.get("skeleton_only")):
            raise RuntimeError("请先确认全部岩点，再启动姿态分析")
        started = time.perf_counter()
        analysis = self.analysis_contract(video_info)
        usage = analysis["usage"]
        timings = analysis["timings_ms"]
        processed_frames = 0

        def snapshot() -> dict:
            timings["total"] = max(0, round((time.perf_counter() - started) * 1000))
            if hasattr(self, 'runtime_metadata'):
                analysis['runtime'] = self.runtime_metadata()
                timings.update(analysis['runtime'].get('timings_ms', {}))
            usage["unprocessed_frames"] = max(0, usage["planned_requests"] - processed_frames)
            analysis["cost"]["billable_requests_estimate"] = (0 if analysis["provider"].get("execution") == "local" else usage["successful_requests"])
            analysis["cost"]["estimated_amount"] = round(
                usage["successful_requests"] * analysis["cost"]["unit_price"], 6,
            )
            return json.loads(json.dumps(analysis, ensure_ascii=False))

        def publish() -> None:
            telemetry(snapshot())

        def empty_pose(sample_index: int, source_index: int, reason=None) -> dict:
            return {
                "frame_id": sample_index, "source_frame_id": int(source_index),
                "wall_alignment": "unavailable",
                "track_id": 0, "kpts_xy": [[0.0, 0.0] for _ in range(17)],
                "kpts_score": [0.0] * 17, "bbox_xywh": [0.0, 0.0, 0.0, 0.0],
                "pose_evidence": {'provider':analysis['provider']['name'], 'observed':False,
                    'reason':reason or getattr(self, 'last_pose_failure', None) or 'no_pose_returned'},
            }

        publish()
        try:
            self._prepare_pose_run(confirmed_holds)
            holds = copy.deepcopy(confirmed_holds["holds"])
            hold_candidates = copy.deepcopy(confirmed_holds.get("hold_candidates") or [])
            hold_diagnostics = copy.deepcopy(confirmed_holds.get("hold_evidence") or {})
            actual_sample = (confirmed_holds.get("route") or {}).get("color_sample")
            hold_version = (confirmed_holds.get("models") or {}).get("holds")
            analysis["models"]["holds"]["version"] = hold_version
            publish()
            if cancelled():
                raise ReplayCancelled()

            sample_fps, positions = self._sampling_positions(video_info)
            stage_started = time.perf_counter()
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                raise RuntimeError("无法重新读取视频进行姿态识别")
            records = []
            contact_records = []
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(hold_diagnostics.get("reference_frame") or 0))
            reference_ok, hold_reference = cap.read()
            if not reference_ok:
                cap.release()
                raise RuntimeError("无法读取已确认岩点的墙面参考帧")
            pose_alignment_failed = 0
            detected_pose_frames = 0
            try:
                if hasattr(self, '_prepare_clip_observations'):
                    self._prepare_clip_observations(video, video_info, positions, hold_reference,
                                                    progress=progress, cancelled=cancelled)
                    publish()
                progress("抽帧识别攀爬者姿态", 55)
                for sample_index, source_index in enumerate(positions):
                    if cancelled():
                        raise ReplayCancelled()
                    processed_frames = sample_index + 1
                    cursor = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    if 0 <= int(source_index) - cursor <= 90:
                        for _ in range(int(source_index) - cursor):
                            if not cap.grab():
                                break
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(source_index))
                    ok, frame = cap.read()
                    if not ok:
                        usage["decode_failed_frames"] += 1
                        missing = empty_pose(sample_index, int(source_index), 'decode_failed')
                        records.append(missing)
                        contact_records.append(missing)
                        publish()
                        continue

                    request_state = {"made": False}
                    person_alignment = None
                    if hasattr(self, 'set_person_reference_transform'):
                        registration_started = time.perf_counter()
                        person_alignment = (self._person_alignment(int(source_index))
                                            if hasattr(self, '_person_alignment') else None)
                        if person_alignment is None:
                            person_alignment = align_to_reference(frame, hold_reference)
                        timings['registration'] = timings.get('registration', 0) + round(
                            (time.perf_counter()-registration_started)*1000)
                        self.set_person_reference_transform(person_alignment[0],
                            [hold_reference.shape[1], hold_reference.shape[0]],
                            [frame.shape[1], frame.shape[0]])
                    if analysis["provider"].get("execution") == "local":
                        usage["local_inferences"] += 1

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
                        if analysis["provider"].get("execution") == "local":
                            usage["failed_local_inferences"] += 1
                        publish()
                        raise
                    if analysis["provider"].get("execution") == "local":
                        if getattr(self, 'last_pose_cache_hit', False):
                            usage['cached_pose_frames'] = usage.get('cached_pose_frames', 0) + 1
                            usage['local_inferences'] -= 1
                        else:
                            usage["successful_local_inferences"] += 1
                        analysis["runtime"] = self.runtime_metadata()
                    if request_state["made"]:
                        usage["successful_requests"] += 1
                    if record:
                        detected_pose_frames += 1
                        usage["successful_pose_frames"] += 1
                        if person_alignment is not None:
                            matrix, alignment = person_alignment
                        else:
                            registration_started = time.perf_counter()
                            matrix, alignment = align_to_reference(frame, hold_reference)
                            timings['registration'] = timings.get('registration', 0) + round(
                                (time.perf_counter()-registration_started)*1000)
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
                if hasattr(self, 'flush_pose_cache'):
                    self.flush_pose_cache()
                timings["pose"] = max(0, round((time.perf_counter() - stage_started) * 1000))
                publish()

            if not detected_pose_frames:
                raise RuntimeError("视频中没有识别到攀爬者，请检查机位和光线")
            track_id, records = self._choose_track(records)

            stage_started = time.perf_counter()
            progress("整理骨架数据" if confirmed_holds.get("skeleton_only") else "计算手脚与岩点接触", 82)
            contact_trace = []
            attempt = {} if confirmed_holds.get('skeleton_only') else self._contacts(contact_records, holds, sample_fps, source_fps=video_info.fps, trace=contact_trace)
            if not confirmed_holds.get('skeleton_only'):
                attempt['contact_evidence'] = {'version':1,'basis':'projected_joint_and_duration_not_physical_contact_proof','frames':contact_trace}
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
                "hold_review_version": confirmed_holds.get("hold_review_version", 0),
                "pose_samples": pose_samples,
                "attempt": attempt,
                "analysis": analysis,
                "warnings": [
                    "当前为技术验证结果，手脚接触需要用户复核。",
                    self.pose_processing_notice,
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
            if confirmed_holds.get('skeleton_only'):
                result = without_hold_data(result)
                result['warnings'] = [self.pose_processing_notice]
            result["torso_trajectory"] = torso_trajectory(result)
            result["overlay"] = render_replay_overlay_video(
                video, overlay_target or video.with_name(REPLAY_OVERLAY_FILENAME), result,
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



class AliyunReplayAnalyzer(ReplayAnalyzerBase):
    """Historical adapter only; never selected by the application factory."""
    pose_model = "aliyun-viapi-bodyposture-2019-12-30"
    pose_processing_notice = "历史阿里云姿态：抽样画面由阿里云人体姿态服务分析。"

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

    def analysis_contract(self, video_info: VideoInfo) -> dict:
        sample_fps, positions = self._sampling_positions(video_info)
        return {
            "contract_version": 1,
            "pipeline_version": REPLAY_PIPELINE_VERSION,
            "provider": {
                "name": "aliyun-viapi", "service": "BodyPosture",
                "region": self.region_id, "api_version": REPLAY_POSE_API_VERSION,
            },
            "models": {
                "holds": {"name": self.hold_model, "version": "pending"},
                "pose": {"name": self.pose_model, "version": REPLAY_POSE_API_VERSION},
            },
            "algorithms": {
                "hold_color": REPLAY_COLOUR_VERSION,
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

    def _prepare_pose_run(self, confirmed_holds: dict) -> None:
        self._client()


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
    test_video_catalog = ReplayTestVideoCatalog(
        test_video_cases, test_video_path, test_video_source_url)

    available_test_videos = test_video_catalog.available_test_videos

    public_test_video = test_video_catalog.public_test_video

    def owner(request: Request) -> str:
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    def consent_policy() -> dict:
        region = "local"
        return {
            "version": REPLAY_CONSENT_VERSION,
            "provider": REPLAY_CONSENT_PROVIDER,
            "service": REPLAY_CONSENT_SERVICE,
            "region": region,
            "data_types": list(REPLAY_CONSENT_DATA_TYPES),
            "execution": "local", "requires_paid_consent": False, "uploads_frames": False,
            "keeps_high_resolution": True,
            "model": "rtmw-l-384x288-cocktail14-20231122",
            "purpose": "生成本次攀岩复盘所需的人体姿态关键点",
            "full_video_sent": False,
        }

    def consent_grant(version: str, granted: bool, *, attempt: int) -> dict:
        policy = consent_policy()
        if not granted:
            raise HTTPException(422, "请先明确同意本次本地视频分析")
        if version != policy["version"]:
            raise HTTPException(409, "数据处理告知已更新，请阅读最新说明并重新同意")
        return {
            "event": "granted", "attempt": attempt, "version": policy["version"],
            "provider": policy["provider"], "service": policy["service"],
            "region": policy["region"], "data_types": policy["data_types"],
            "purpose": policy["purpose"], "full_video_sent": policy["full_video_sent"],
            "execution": "local", "uploads_frames": False,
            "granted_at": utcnow(),
        }

    def retention_choice(value: str) -> ReplayRetentionMode:
        if value not in {REPLAY_RETENTION_DELETE, REPLAY_RETENTION_KEEP}:
            raise HTTPException(422, "请选择有效的视频保留方式")
        return REPLAY_RETENTION_KEEP

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

    from core.replay_preview import preview_router
    router.include_router(preview_router(store, owner, limits))

    @router.post('/prepared-videos/{key}/start', status_code=202)
    def start_prepared_video(key: str, payload: ReplayUploadCreate, request: Request):
        username = owner(request)
        route_id, route_color = (None, '') if payload.skip_holds else resolve_route(username, payload.route_id, payload.route_color)
        consent = consent_grant(payload.consent_version, payload.consent_granted, attempt=1)
        consent.update(event='local_processing_granted', skip_holds=payload.skip_holds)
        color_sample = parse_color_sample(payload.route_color_sample)
        with store._lock:
            manager.ensure_capacity()
            prepared = store.prepared_previews.take(key, username)
            try:
                info = prepared['info']
                if payload.trim_start_seconds != 0 or (payload.trim_end_seconds is not None and abs(payload.trim_end_seconds-info.duration_seconds) > .1):
                    raise HTTPException(409, '视频范围已变化，请重新导入后取色。')
                root = Path(prepared['work'].name)
                job = store.create_pending(owner=username, route_id=route_id, route_color=route_color,
                    source=root/'source.mp4', original_name=prepared['filename'], content_type=prepared['content_type'],
                    consent=consent, retention_mode=retention_choice(payload.retention_mode),
                    trim_start_seconds=0, trim_end_seconds=info.duration_seconds,
                    route_color_sample=color_sample, saved_route_reference=route_reference(username, route_id))
                job = store.finish_preparation(job['id'], root/'preview.mp4', info)
                manager.enqueue(job['id'])
                return job
            finally:
                prepared['work'].cleanup()

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

    test_video_response = test_video_catalog.test_video_response

    comparison_video_response = test_video_catalog.comparison_video_response

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
    def create_job(
        request: Request,
        video: UploadFile = File(...),
        route_id: str = Form(default=""),
        route_color: str = Form(default=""),
        consent_version: str = Form(default=""),
        consent_granted: bool = Form(default=False),
        retention_mode: str = Form(default=REPLAY_RETENTION_KEEP),
        trim_start_seconds: float = Form(default=0),
        trim_end_seconds: float | None = Form(default=None),
        route_color_sample: str = Form(default=""),
        skip_holds: bool = Form(default=False),
    ):
        username = owner(request)
        route_id, route_color = (None, "") if skip_holds else resolve_route(username, route_id, route_color)
        consent = consent_grant(consent_version, consent_granted, attempt=1)
        consent["event"] = "local_processing_granted"
        consent["skip_holds"] = skip_holds
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
                while chunk := video.file.read(1024 * 1024):
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
        route_id, route_color = (None, "") if payload.skip_holds else resolve_route(username, payload.route_id, payload.route_color)
        consent = consent_grant(payload.consent_version, payload.consent_granted, attempt=1)
        consent["event"] = "local_processing_granted"
        consent["skip_holds"] = payload.skip_holds
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
            data = await request.body()
            return await run_in_threadpool(replay_uploads.append, upload_id, owner(request), offset=offset, data=data)
        except ChunkUploadError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/uploads/{upload_id}/complete", status_code=202)
    def complete_upload(upload_id: str, request: Request):
        username = owner(request)
        manager.ensure_capacity()
        try:
            meta, part = replay_uploads.finish(upload_id, username)
            details = meta["metadata"]
            route_id, route_color = (None, "") if details["consent"].get("skip_holds") else resolve_route(username, details.get("route_id", ""), details.get("route_color", ""))
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

    @router.post("/jobs/{job_id}/holds/editor/frame")
    def read_editor_frame(job_id: str, payload: EditorFrameRequest, request: Request):
        return editor_frame(store, job_id, owner(request), payload)

    @router.post("/jobs/{job_id}/holds/editor/preview")
    def preview_editor_contour(job_id: str, payload: EditorPreviewRequest, request: Request):
        try:
            return editor_preview(store, job_id, owner(request), payload)
        except (TimeoutError, InterruptedError) as exc:
            raise HTTPException(422, "局部识别未完成，描边内容已保留；可继续手绘或重试。") from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(422, "本地专项模型暂不可用，可先手绘轮廓并保存。") from exc

    @router.post("/jobs/{job_id}/holds/editor/cancel")
    def cancel_editor_inference(job_id: str, payload: EditorCancelRequest, request: Request):
        return cancel_editor_request(store, job_id, owner(request), payload.request_id)

    @router.post("/jobs/{job_id}/holds/editor/confirm")
    def confirm_editor_contour(job_id: str, payload: EditorCommitRequest, request: Request):
        return editor_commit(store, job_id, owner(request), payload.proposal_id)

    @router.delete("/jobs/{job_id}/holds/{hold_id}")
    def remove_replay_hold(job_id: str, hold_id: int, request: Request):
        return store.remove_hold(job_id, owner(request), hold_id)

    @router.post("/jobs/{job_id}/holds/confirm-all")
    def confirm_replay_holds(job_id: str, payload: ReplayHoldsConfirmation, request: Request):
        return store.confirm_all_holds(job_id, owner(request), payload.revision)

    @router.post("/jobs/{job_id}/route-map/refresh")
    def refresh_route_map(job_id: str, request: Request):
        return store.refresh_route_map(job_id, owner(request))

    @router.post("/jobs/{job_id}/analysis/start", status_code=202)
    def start_replay_analysis(job_id: str, payload: ReplayRetryCreate, request: Request):
        username = owner(request)
        with store._lock:
            manager.ensure_capacity()
            consent = consent_grant(payload.consent_version, payload.consent_granted, attempt=1)
            consent['skip_holds'] = payload.skip_holds
            consent['sampling'] = {'pose_fps': payload.pose_fps,
                                   'focus_windows': [row.model_dump() for row in payload.focus_windows]}
            from core.replay_sampling import native_plan
            selected = store.get(job_id, username, private=True)
            if selected.get('video'):
                try:
                    native_plan(VideoInfo(**selected['video']), payload.pose_fps or 10, payload.focus_windows)
                except ValueError:
                    raise HTTPException(422, '重点采样片段须位于当前视频时间范围内') from None
            result = store.start_analysis(job_id, username, consent)
            manager.enqueue(job_id)
        return result

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

    @router.get('/jobs/{job_id}/media/original-video')
    def get_original_video(job_id: str, request: Request):
        job = store.get(job_id, owner(request), private=True)
        prepared, item = store.media_file(job_id, owner(request), 'source_video')
        high = job.get('high_resolution_source') or {}
        name = high.get('storage_name')
        if not name:
            raise HTTPException(404, '这条历史记录没有保留上传原片，现有播放副本仍可使用。')
        if name not in {f'source{suffix}' for suffix in (*REPLAY_VIDEO_SUFFIXES, '.video')}:
            raise HTTPException(404, '原片不可用')
        path = prepared.parent / name
        if not path.is_file() or path.resolve().parent != prepared.resolve().parent:
            raise HTTPException(404, '原片不可用')
        return FileResponse(path, filename=job['original_name'],
            headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})

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
