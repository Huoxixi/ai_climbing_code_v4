"""Replay request schemas and shared data contracts, independent of job services.

The legacy core.climb_replay imports remain available for existing callers.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .replay_sampling import FocusWindow


REPLAY_RETENTION_DELETE = "delete_after_processing"


REPLAY_RETENTION_KEEP = "keep_private_original"


ReplayRetentionMode = Literal["delete_after_processing", "keep_private_original"]


class ReplayConfigurationError(RuntimeError):
    """Raised when the opt-in pose provider has no usable configuration."""


class ReplayCancelled(RuntimeError):
    """Raised between analysis stages after a user asks to cancel."""


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 200 * 1024 * 1024
    max_input_bytes: int = 500 * 1024 * 1024
    max_duration_seconds: float = 90.0
    max_width: int = 1280
    max_height: int = 720
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
    skip_holds: bool = False
    route_id: str = Field(default="", max_length=64)
    route_color: str = Field(default="", max_length=40)
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool
    retention_mode: ReplayRetentionMode = REPLAY_RETENTION_KEEP
    trim_start_seconds: float = Field(default=0, ge=0)
    trim_end_seconds: float | None = Field(default=None, gt=0)
    route_color_sample: ReplayColorSample | None = None


class ReplayRetryCreate(BaseModel):
    skip_holds: bool = False
    model_config = ConfigDict(extra="forbid")
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool
    pose_fps: Literal[4, 10, 15, 20] | None = None
    focus_windows: list[FocusWindow] = Field(default_factory=list, max_length=20)


class ReplayHoldsConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=64)


def hold_review_input(job: dict) -> dict:
    return job.get("hold_edit_draft") or job.get("result") or job.get("hold_draft") or {}


def hold_geometry(result: dict) -> dict:
    return {key: copy.deepcopy(result[key]) for key in
            ("holds", "hold_candidates", "hold_evidence", "models", "route", "hold_review_version", "hold_refinement")
            if key in result}


def holds_revision(result: dict) -> str:
    """Bind global confirmation to the exact holds and wall reference reviewed."""
    payload = {"holds": result.get("holds") or [],
               "reference_frame": (result.get("hold_evidence") or {}).get("reference_frame"),
               "version": result.get("hold_review_version") or 0}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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
    proposal_id: str | None = Field(default=None, min_length=32, max_length=32)

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


class ReplayAnalyzer(Protocol):
    def analysis_contract(self, video_info: VideoInfo) -> dict: ...

    def detect_holds(self, video: Path, *, route_color: str, video_info: VideoInfo,
                     route_color_sample: dict | None, saved_route_reference: dict | None,
                     trim_start_seconds: float, progress: Callable[[str, int], None],
                     cancelled: Callable[[], bool]) -> dict: ...

    def analyze(
        self,
        video: Path,
        *,
        route_color: str,
        route_color_sample: dict | None = None,
        confirmed_holds: dict | None = None,
        video_info: VideoInfo,
        progress: Callable[[str, int], None],
        cancelled: Callable[[], bool],
        telemetry: Callable[[dict], None],
    ) -> dict: ...
