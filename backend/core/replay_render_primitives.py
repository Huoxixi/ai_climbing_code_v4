"""Shared replay drawing primitives; saved evidence and thresholds are unchanged."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


_CJK_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path(__file__).resolve().parents[1] / "vendor/NotoSansSC-VF.ttf",
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


def _overlay_text(frame: np.ndarray, text: str, origin: tuple[int, int], *,
                  scale: float, color: tuple[int, int, int] = (235, 239, 241),
                  thickness: int = 1) -> None:
    cv2.putText(
        frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
        color, thickness, cv2.LINE_AA,
    )
