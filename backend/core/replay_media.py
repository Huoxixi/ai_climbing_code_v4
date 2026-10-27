"""Video metadata and upload bounds, independent of replay jobs and services."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import cv2

from core.replay_contracts import VideoInfo, VideoLimits


REPLAY_VIDEO_MIME_TYPES = frozenset({
    "video/mp4", "video/quicktime", "video/x-m4v", "video/webm",
    "video/3gpp", "video/3gpp2", "video/x-matroska", "video/x-msvideo", "video/avi",
    "video/mpeg", "video/mp2t", "video/x-ms-wmv", "video/x-ms-asf", "video/x-flv",
    "video/ogg", "application/mxf",
})


REPLAY_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".webm", ".3gp", ".3g2", ".mkv",
    ".avi", ".mpg", ".mpeg", ".mpe", ".ts", ".mts", ".m2ts", ".m2t", ".wmv", ".asf",
    ".flv", ".f4v", ".vob", ".ogv", ".ogg", ".mxf", ".divx"})


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
    if not mime.startswith('video/') and mime not in REPLAY_VIDEO_MIME_TYPES and suffix not in REPLAY_VIDEO_SUFFIXES:
        raise ValueError("请选择常见视频文件，如 MP4、MOV、MKV、AVI、WebM、MTS、MPEG 或 WMV。")
    return suffix == ".mp4" and mime in {"", "application/octet-stream", "video/mp4"}


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
