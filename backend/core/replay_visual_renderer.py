"""CPU-only, streaming replay tail. No service, model or account imports.

The manifest freezes the source coordinate system and the original event times.
Every wall pixel, contour and line is transformed by the same homography. The
only screen-space elements are the title and legend. This is a visual summary,
not a reconstruction of wall depth or an inferred body trajectory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

VISUAL_VERSION = "replay-visual-v2.1"
LIMB_COLORS = {
    "left_hand": (235, 196, 80), "right_hand": (193, 92, 237),
    "left_foot": (106, 179, 255), "right_foot": (87, 222, 143),
}
LIMB_NAMES = {"left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚"}


class VisualInputError(ValueError):
    """Insufficient or inconsistent evidence; retain the base replay."""


def visual_output_size(width: int, height: int, max_side: int = 1280) -> tuple[int, int]:
    if width < 2 or height < 2:
        raise VisualInputError("参考画面尺寸无效")
    scale = min(1., min(1280, max_side) / max(width, height))
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def _number(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _reference_person_region(result: dict, reference: dict, fps: float) -> dict | None:
    """Conservative occlusion hint from a nearby measured, aligned person box.

    This is not person segmentation. A missing/distant/unregistered observation
    produces no inferred region. Existing image pixels and contacts stay intact.
    """
    reference_frame = _number(reference.get("source_frame_id"))
    source_fps = _number((result.get("video") or {}).get("fps") or reference.get("source_fps"), fps)
    if reference_frame is None or source_fps <= 0:
        return None
    candidates = []
    for sample in result.get("pose_samples") or []:
        source_frame = _number(sample.get("source_frame_id"))
        if (source_frame is None or sample.get("observed") is not True
                or sample.get("wall_alignment") not in {"aligned", "reference"}
                or _number(sample.get("confidence"), 0.) < .5):
            continue
        delta = abs(source_frame - reference_frame) / source_fps
        box = sample.get("bbox_xywh") or []
        if delta > .3 or len(box) != 4 or any(_number(v) is None for v in box):
            continue
        x, y, bw, bh = map(float, box)
        if x < 0 or y < 0 or bw <= 0 or bh <= 0 or x + bw > 1.01 or y + bh > 1.01:
            continue
        matrix = sample.get("wall_reference_transform")
        if matrix is None and sample.get("wall_alignment") == "reference" and delta == 0:
            matrix = np.eye(3)
        try:
            matrix = np.asarray(matrix, np.float64)
            if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-9:
                continue
        except (TypeError, ValueError):
            continue
        video = result.get("video") or {}
        sw = _number(video.get("width"), reference["width"])
        sh = _number(video.get("height"), reference["height"])
        if sw <= 0 or sh <= 0:
            continue
        # Small tolerance covers pose-box imprecision and the <= 0.3 s gap.
        padding = .01 * min(sw, sh)
        left, top = max(0., x * sw - padding), max(0., y * sh - padding)
        right, bottom = min(sw, (x + bw) * sw + padding), min(sh, (y + bh) * sh + padding)
        quad = np.float32([[[left, top], [right, top], [right, bottom], [left, bottom]]])
        mapped = cv2.perspectiveTransform(quad, matrix)[0] / [reference["width"], reference["height"]]
        if not np.isfinite(mapped).all() or np.max(np.abs(mapped)) > 2:
            continue
        candidates.append((delta, int(source_frame), {
            "source_frame_id": int(source_frame), "reference_frame_id": int(reference_frame),
            "time_distance_seconds": round(delta, 6), "confidence": sample["confidence"],
            "polygon": mapped.tolist(), "method": "nearby_measured_aligned_person_bbox",
            "padding_short_side_fraction": .01,
        }))
    return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def build_visual_manifest(result: dict, reference_metadata: dict, *,
                          output_size: tuple[int, int] | None = None,
                          fps: float | None = None) -> dict:
    """Freeze existing normalized holds and accepted contacts, without inference.

    ``reference_metadata``: width, height, source_frame_id, source_sha256;
    optional quality=limited/insufficient, registration_valid, demonstration.
    Projected or occluded holds retain only neutral locating contours.
    """
    reference = dict(reference_metadata)
    sw, sh = int(reference.get("width", 0)), int(reference.get("height", 0))
    if reference.get("registration_valid") is False or reference.get("quality") == "insufficient":
        raise VisualInputError("参考画面无法可靠对齐，保留基础复盘")
    default_size = visual_output_size(sw, sh)
    width, height = map(int, output_size or default_size)
    if min(width, height) < 2 or max(width, height) > 1280 or width % 2 or height % 2:
        raise VisualInputError("线路回放须为偶数尺寸且长边不超过 1280")
    if abs(width / height - sw / sh) > max(2 / height, 2 * sw / (sh * height)):
        raise VisualInputError("线路回放画幅必须保持参考画面比例")
    fps = _number(fps if fps is not None else (result.get("video") or {}).get("fps"), 24.)
    if not 1 <= fps <= 60:
        raise VisualInputError("线路回放帧率无效")
    person_region = _reference_person_region(result, reference, fps)
    holds = []
    for raw in result.get("holds") or []:
        if raw.get("id") is None or raw.get("excluded") or raw.get("removed"):
            continue
        polygon = raw.get("polygon") or []
        valid_polygon = len(polygon) >= 3 and all(
            isinstance(p, (list, tuple)) and len(p) >= 2 and
            all(_number(v) is not None and 0 <= float(v) <= 1 for v in p[:2]) for p in polygon)
        texture_reliable = valid_polygon and raw.get("texture_reliable", True) and not raw.get("occluded", False)
        if not valid_polygon:
            box = raw.get("bbox") or []
            if len(box) != 4 or any(_number(v) is None for v in box):
                continue
            x, y, w, h = map(float, box)
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
                continue
            polygon = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        # Preserve native outlines; cap only hostile/unbounded manifest input.
        if len(polygon) > 2048:
            step = math.ceil(len(polygon) / 2048)
            polygon = polygon[::step]
        polygon = [[round(float(x), 7), round(float(y), 7)] for x, y, *_ in polygon]
        points = np.asarray(polygon, np.float32)
        if cv2.contourArea(points) < 1e-7:
            continue
        occlusion_fraction = 0.
        if person_region is not None:
            hull = cv2.convexHull(points)
            person_hull = cv2.convexHull(np.asarray(person_region["polygon"], np.float32))
            intersection, _ = cv2.intersectConvexConvex(hull, person_hull)
            occlusion_fraction = float(intersection) / max(1e-9, cv2.contourArea(hull))
        possible_occlusion = occlusion_fraction >= .20
        if possible_occlusion:
            texture_reliable = False
        raw_number = str(raw["id"])
        display_number = int(raw_number) if raw_number.isdigit() and 0 < int(raw_number) < 100000 else len(holds) + 1
        occupied_numbers = {hold["display_number"] for hold in holds}
        while display_number in occupied_numbers:
            display_number += 1
        holds.append({"id": raw["id"], "display_number": display_number, "polygon": polygon,
                      "texture_reliable": bool(texture_reliable),
                      "possible_person_occlusion": possible_occlusion,
                      "person_bbox_overlap_fraction": round(occlusion_fraction, 6),
                      "center": points.mean(axis=0).astype(float).tolist()})
    if not holds or len(holds) > 256:
        raise VisualInputError("缺少可用的岩点坐标")
    by_id = {str(h["id"]): h for h in holds}
    events = []
    attempt = result.get("attempt") or {}
    for raw in attempt.get("contacts") or []:
        limb, hold_id = str(raw.get("limb") or ""), str(raw.get("hold_id"))
        if limb not in LIMB_COLORS or hold_id not in by_id:
            continue
        if (raw.get("excluded") or raw.get("removed") or raw.get("reliable") is False
                or raw.get("status") in {"rejected", "removed", "uncertain", "invalid"}
                or _number(raw.get("confidence"), 1.) < .5):
            continue
        source_time = _number(raw.get("start_time_seconds"))
        source_frame = _number(raw.get("start_source_frame"))
        if source_time is None and source_frame is not None:
            source_fps = _number((result.get("video") or {}).get("fps") or reference.get("source_fps"), fps)
            source_time = source_frame / source_fps if source_fps > 0 else None
        if source_time is None or source_time < 0:
            continue
        events.append({"hold_id": by_id[hold_id]["id"], "limb": limb,
                       "source_time_seconds": source_time,
                       "source_frame_id": int(source_frame) if source_frame is not None else None,
                       "source_status": raw.get("status") or raw.get("source") or "accepted_contact"})
    events.sort(key=lambda e: (e["source_time_seconds"], list(LIMB_COLORS).index(e["limb"]), str(e["hold_id"])))
    if not events or len(events) > 2000:
        raise VisualInputError("没有可靠用点记录，保留基础复盘")
    groups = sorted(set(e["source_time_seconds"] for e in events))
    duration = 8. if len(groups) <= 18 else 10.
    frame_count = round(duration * fps)
    duration = frame_count / fps
    # Uniformly compress event groups, preserving simultaneous timestamps. The
    # map explicitly retains original time; it never edits the analysis result.
    times = {source: (1.1 if i == 0 else 2. + (duration - 4.) * i / max(1, len(groups) - 1))
             for i, source in enumerate(groups)}
    prior = {}
    seen = set()
    for event in events:
        event["tail_time_seconds"] = round(times[event["source_time_seconds"]], 6)
        key = str(event["hold_id"])
        event["first_use"] = key not in seen
        seen.add(key)
        previous = prior.get(event["limb"])
        # A single limb cannot have two distinct contacts at exactly one instant:
        # retain both highlights, but omit an invented order/connection.
        same_instant = sum(e["limb"] == event["limb"] and e["source_time_seconds"] == event["source_time_seconds"]
                           for e in events) > 1
        event["previous_hold_id"] = (previous["hold_id"] if previous and not same_instant
                                     and previous["source_time_seconds"] < event["source_time_seconds"]
                                     and previous["hold_id"] != event["hold_id"] else None)
        if same_instant:
            prior.pop(event["limb"], None)
        else:
            prior[event["limb"]] = event
    used = [by_id[str(e["hold_id"])] for e in events]
    margin = min(min(x, y, 1 - x, 1 - y) for h in used for x, y in h["polygon"])
    motion = min(1., max(0., margin - .015) / .075)
    if reference.get("quality") == "limited":
        motion *= .3
    manifest = {
        "schema_version": 1, "visual_version": VISUAL_VERSION,
        "width": width, "height": height, "fps": fps,
        "duration_seconds": duration, "frame_count": frame_count,
        "reference": reference, "holds": holds, "events": events,
        "reference_person_region": person_region,
        "camera": {"motion_scale": round(motion, 6), "freeze_at_seconds": duration - 1.},
        "timeline": [{"source_time_seconds": t, "tail_time_seconds": round(times[t], 6)} for t in groups],
        "title": "本次用点回顾",
        "input_versions": {key: result.get(key) for key in ("pipeline_version", "hold_review_version", "contact_review_version", "analysis_version")},
        "demonstration": bool(reference.get("demonstration")),
    }
    # Existing topped_out is a heuristic, so only an explicitly verified result
    # earns a completion claim in this presentation layer.
    if attempt.get("completion_verified") is True and attempt.get("topped_out") is True:
        manifest["title"] = "完成 · 线路回顾"
    manifest["input_digest"] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return manifest


def _smooth(value: float) -> float:
    value = max(0., min(1., value))
    return value * value * value * (value * (value * 6 - 15) + 10)


def visual_event_state(manifest: dict, seconds: float) -> dict:
    """Keep each limb's identity, including multiple limbs on the same hold."""
    active = [e for e in manifest["events"] if e["tail_time_seconds"] <= seconds]
    positions, used = {}, {}
    for event in active:
        positions[event["limb"]] = event
        used[str(event["hold_id"])] = event
    latest_time = max((e["tail_time_seconds"] for e in active), default=-100.)
    transitions = [e for e in active if e["tail_time_seconds"] == latest_time
                   and e.get("previous_hold_id") is not None
                   and seconds - e["tail_time_seconds"] < .85]
    groups = {}
    for limb, event in positions.items():
        groups.setdefault(str(event["hold_id"]), []).append(event)
    return {"active": active, "positions": positions, "used": used,
            "transitions": transitions, "hold_limb_groups": groups}


def camera_matrix(manifest: dict, seconds: float) -> np.ndarray:
    """Small, coverage-safe perspective; stationary for the entire last second."""
    w, h = manifest["width"], manifest["height"]
    amount = manifest["camera"]["motion_scale"]
    t = _smooth(seconds / manifest["camera"]["freeze_at_seconds"])
    zoom = 1. + amount * (.09 - .06 * t)
    dx, dy = amount * .009 * w * (2 * t - 1), amount * .003 * h * (1 - t)
    skew = amount * .004 * min(w, h) * (1 - t)
    source = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    target = (source - [(w - 1) / 2, (h - 1) / 2]) * zoom + [(w - 1) / 2 + dx, (h - 1) / 2 + dy]
    target += np.array([[skew, -skew], [-skew, skew], [skew, -skew], [-skew, skew]])
    return cv2.getPerspectiveTransform(source, target.astype(np.float32))


def _font(size: int):
    paths = (os.environ.get("REPLAY_FONT_PATH"), "C:/Windows/Fonts/msyh.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
             str(Path(__file__).resolve().parents[1] / "vendor/NotoSansSC-VF.ttf"),
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in paths:
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size), "CJK" if any(s in path.lower() for s in ("msyh", "cjk", "wqy", "notosanssc")) else "latin"
            except OSError:
                pass
    return ImageFont.load_default(), "latin"


def _screen_labels(manifest: dict) -> tuple[np.ndarray, np.ndarray]:
    w, h = manifest["width"], manifest["height"]
    short = min(w, h)
    image = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(image)
    title_font, language = _font(max(16, round(short * .048)))
    small_font, _ = _font(max(11, round(short * .029)))
    pad = max(12, round(short * .045))
    title = manifest["title"] if language == "CJK" else "YOUR ROUTE REPLAY"
    kicker = "线路回放" if language == "CJK" else "ROUTE REPLAY"
    draw.text((pad, pad), kicker, font=small_font, fill=(230, 211, 166, 235))
    draw.text((pad, pad + short * .041), title, font=title_font, fill=(247, 246, 241, 255))
    text = ("箭头：换点顺序 · 标签：最近用点" if language == "CJK" else "Arrows: move order / Labels: last recorded holds")
    if manifest.get("demonstration"):
        text = "视觉样片 · 演示顺序，非真实攀爬记录" if language == "CJK" else "VISUAL DEMO - illustrative contact order"
    draw.text((pad, h - pad - short * .035), text, font=small_font, fill=(225, 226, 224, 235))
    x, y = pad, h - pad - short * .087
    present_limbs = {e["limb"] for e in manifest["events"]}
    for limb, bgr in LIMB_COLORS.items():
        if limb not in present_limbs:
            continue
        r = max(2, round(short * .004))
        draw.ellipse((x, y + 5, x + r * 2, y + 5 + r * 2), fill=(*bgr[::-1], 255))
        label = LIMB_NAMES[limb] if language == "CJK" else {"left_hand": "LH", "right_hand": "RH", "left_foot": "LF", "right_foot": "RF"}[limb]
        draw.text((x + r * 4, y), label, font=small_font, fill=(229, 233, 231, 255))
        x += short * .16
    missing = [LIMB_NAMES[limb] for limb in LIMB_COLORS if limb not in present_limbs]
    if missing:
        if present_limbs <= {"left_hand", "right_hand"}:
            coverage = "本段缺少脚部用点记录" if language == "CJK" else "No foot contacts recorded in this segment"
        else:
            coverage = "本段未记录：" + "、".join(missing) if language == "CJK" else "Some limb contacts were not recorded"
        draw.text((pad, h - pad - short * .142), coverage, font=small_font, fill=(239, 210, 159, 255))
    rgba = np.asarray(image)
    return rgba[:, :, :3][:, :, ::-1].copy(), rgba[:, :, 3:4].astype(np.float32) / 255


def _limb_badge(text: str, color: tuple[int, int, int], font) -> tuple[np.ndarray, np.ndarray]:
    bbox = font.getbbox(text)
    w, h = bbox[2] - bbox[0] + 20, bbox[3] - bbox[1] + 14
    image = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=6, fill=(13, 20, 19, 235), outline=(*color[::-1], 235), width=1)
    draw.rounded_rectangle((2, 3, 5, h - 4), radius=1, fill=(*color[::-1], 255))
    draw.text((11 - bbox[0], 7 - bbox[1]), text, font=font, fill=(249, 250, 247, 255))
    rgba = np.asarray(image)
    return rgba[:, :, :3][:, :, ::-1].copy(), rgba[:, :, 3:4].astype(np.float32) / 255


def iter_visual_frames(reference_path: Path | str, manifest: dict) -> Iterator[np.ndarray]:
    """Yield a frame then discard it. Fixed masks are small hold-local patches."""
    cv2.setNumThreads(1)
    if manifest.get("visual_version") != VISUAL_VERSION:
        raise VisualInputError("线路回放版本不匹配")
    data = np.fromfile(str(reference_path), np.uint8)
    source = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if source is None:
        raise VisualInputError("参考墙面图片不可用")
    metadata = manifest["reference"]
    if source.shape[1] != metadata["width"] or source.shape[0] != metadata["height"]:
        raise VisualInputError("参考墙面图片尺寸已改变")
    reference_digest = metadata.get("reference_sha256") or metadata.get("checksum_sha256")
    if reference_digest and hashlib.sha256(data.tobytes()).hexdigest() != reference_digest:
        raise VisualInputError("参考墙面图片版本已改变")
    w, h = manifest["width"], manifest["height"]
    source = cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    base = cv2.addWeighted(source, .60, cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), .40, 0)
    yy, xx = np.ogrid[-1:1:complex(h), -1:1:complex(w)]
    vignette = np.clip(.65 - .18 * (xx * xx + yy * yy), .34, .65).astype(np.float32)
    base = (base * vignette[:, :, None]).astype(np.uint8)
    short = min(w, h)
    line_width = max(1, round(short / 400))
    patches = {}
    visual_numbers = {str(hold["id"]): hold.get("display_number", index + 1)
                      for index, hold in enumerate(manifest["holds"])}
    for hold in manifest["holds"]:
        polygon = np.round(np.asarray(hold["polygon"]) * [w - 1, h - 1]).astype(np.int32)
        x, y, bw, bh = cv2.boundingRect(polygon)
        padding = max(4, round(short * .012))
        x0, y0, x1, y1 = max(0, x - padding), max(0, y - padding), min(w, x + bw + padding), min(h, y + bh + padding)
        local = polygon - [x0, y0]
        mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(mask, [local], 255, cv2.LINE_AA)
        edge = np.zeros_like(mask)
        cv2.polylines(edge, [local], True, 255, line_width + 1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(edge, (0, 0), max(1., short * .006)).astype(np.float32) / 255
        patches[str(hold["id"])] = (hold, (x0, y0, x1, y1), polygon, mask.astype(np.float32)[:, :, None] / 255, glow[:, :, None])
    labels, labels_alpha = _screen_labels(manifest)
    badge_font, badge_language = _font(max(11, round(short * .032)))
    badge_cache = {}
    # Static title/footer readability gradient; no expensive per-frame blur.
    screen_shade = np.ones((h, 1, 1), np.float32)
    band = max(1, round(short * .19))
    screen_shade[:band, 0, 0] = np.linspace(.45, 1., band)
    screen_shade[-band:, 0, 0] = np.linspace(1., .38, band)
    events = manifest["events"]
    freeze = manifest["camera"]["freeze_at_seconds"]
    frozen_frame = None
    for frame_index in range(manifest["frame_count"]):
        if frame_index / manifest["fps"] >= freeze and frozen_frame is not None:
            yield frozen_frame.copy()
            continue
        seconds = min(frame_index / manifest["fps"], freeze)
        canvas = base.copy()
        state = visual_event_state(manifest, seconds)
        # Only the current move is visible. Old lines do not accumulate into
        # an unreadable web, and simultaneous moves remain simultaneous.
        for event in state["transitions"]:
            previous_id = event["previous_hold_id"]
            previous, current = patches[str(previous_id)][0], patches[str(event["hold_id"])][0]
            a = np.asarray(previous["center"]) * [w - 1, h - 1]
            b = np.asarray(current["center"]) * [w - 1, h - 1]
            age = seconds - event["tail_time_seconds"]
            fraction = _smooth(age / .28)
            end = a + fraction * (b - a)
            opacity = 1 - _smooth((age - .5) / .35)
            color = tuple(round(c * .88 * opacity) for c in LIMB_COLORS[event["limb"]])
            cv2.arrowedLine(canvas, tuple(a.astype(int)), tuple(end.astype(int)), color, line_width + 1, cv2.LINE_AA, tipLength=.065)
        for key, event in state["used"].items():
            hold, (x0, y0, x1, y1), polygon, mask, glow = patches[key]
            age = seconds - event["tail_time_seconds"]
            reveal = _smooth(age / .30)
            pulse = (math.sin(math.pi * min(1., age / .72)) ** 2 if age < .72 and event["first_use"] else 0.)
            roi = canvas[y0:y1, x0:x1]
            color = np.array(LIMB_COLORS[event["limb"]], np.float32)
            if hold["texture_reliable"]:
                alpha = mask * (.83 + .10 * pulse) * reveal
                roi[:] = np.clip(roi * (1 - alpha) + source[y0:y1, x0:x1] * alpha, 0, 255).astype(np.uint8)
                glow_alpha = glow * (.24 + .65 * pulse) * reveal
                roi[:] = np.clip(roi * (1 - glow_alpha) + color * glow_alpha, 0, 255).astype(np.uint8)
                outline = tuple(int(v) for v in color * (.65 + .35 * pulse) * reveal)
            else:
                outline = (155, 164, 166)
            cv2.polylines(canvas, [polygon], True, outline, line_width, cv2.LINE_AA)
        for event in state["transitions"]:
            for hold_id in (event["previous_hold_id"], event["hold_id"]):
                point = np.asarray(patches[str(hold_id)][0]["center"]) * [w - 1, h - 1]
                cv2.circle(canvas, tuple(point.astype(int)), max(3, round(short * .007)),
                           LIMB_COLORS[event["limb"]], line_width + 1, cv2.LINE_AA)
        matrix = camera_matrix(manifest, seconds)
        transformed = cv2.warpPerspective(canvas, matrix, (w, h),
                                           flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        transition = _smooth(seconds / .8)
        # Start with the real frame; the final compositor can dissolve its last
        # analysis frame into these first 0.8 seconds without a second encode.
        if transition < 1:
            original = cv2.warpPerspective(source, camera_matrix(manifest, seconds), (w, h))
            transformed = cv2.addWeighted(original, 1 - transition, transformed, transition, 0)
        # Text and readability shading occupy only two narrow bands. Avoid
        # allocating/converting an entire floating-point wall for empty alpha.
        for top, bottom in ((0, band), (h - band, h)):
            roi = transformed[top:bottom]
            roi[:] = (roi * (1 - (1 - screen_shade[top:bottom]) * transition)).astype(np.uint8)
            alpha = labels_alpha[top:bottom] * transition
            roi[:] = (roi * (1 - alpha) + labels[top:bottom] * alpha).astype(np.uint8)
        occupied = []
        for hold_id, limb_events in state["hold_limb_groups"].items():
            polygon = patches[hold_id][2].astype(np.float32).reshape(-1, 1, 2)
            mapped = cv2.perspectiveTransform(polygon, matrix).reshape(-1, 2)
            tag_y = int(mapped[:, 1].mean()) - int(len(limb_events) * short * .029)
            for event in sorted(limb_events, key=lambda e: list(LIMB_COLORS).index(e["limb"])):
                limb = event["limb"]
                name = LIMB_NAMES[limb] if badge_language == "CJK" else {"left_hand": "LH", "right_hand": "RH", "left_foot": "LF", "right_foot": "RF"}[limb]
                target_id = str(visual_numbers[str(event["hold_id"])])
                moving = event in state["transitions"]
                detail = f"{visual_numbers[str(event['previous_hold_id'])]}→{target_id}" if moving else target_id
                text = f"{name} · {detail}"
                cache_key = (text, limb)
                if cache_key not in badge_cache:
                    badge_cache[cache_key] = _limb_badge(text, LIMB_COLORS[limb], badge_font)
                badge, badge_alpha = badge_cache[cache_key]
                bh, bw = badge.shape[:2]
                right_side = int(mapped[:, 0].max()) + 9
                left_side = int(mapped[:, 0].min()) - bw - 9
                candidates = []
                for candidate_x in (right_side, left_side, 6, w - bw - 6):
                    for shift in (0, 1, -1, 2, -2, 3, -3):
                        cx = max(4, min(w - bw - 4, candidate_x))
                        cy = max(round(short * .15), min(h - round(short * .20) - bh, tag_y + shift * (bh + 5)))
                        overlap = sum(max(0, min(cx + bw, ox + ow) - max(cx, ox)) *
                                      max(0, min(cy + bh, oy + oh) - max(cy, oy)) for ox, oy, ow, oh in occupied)
                        distance = abs(cx + bw / 2 - mapped[:, 0].mean()) + abs(cy + bh / 2 - mapped[:, 1].mean())
                        candidates.append((overlap * 10000 + distance, cx, cy))
                _, left, top = min(candidates)
                # A short leader ends on the actual transformed rock contour;
                # it keeps a moved badge clearly attached to its own hold.
                middle = np.array([left + bw / 2, top + bh / 2])
                anchor = mapped[np.argmin(np.sum((mapped - middle) ** 2, axis=1))]
                edge = (int(np.clip(anchor[0], left, left + bw)), int(np.clip(anchor[1], top, top + bh)))
                anchor_xy = tuple(anchor.astype(int))
                leader_color = tuple(round(c * .78) for c in LIMB_COLORS[limb])
                cv2.line(transformed, anchor_xy, edge, leader_color, max(1, line_width), cv2.LINE_AA)
                cv2.circle(transformed, anchor_xy, max(2, round(short * .004)), LIMB_COLORS[limb], -1, cv2.LINE_AA)
                roi = transformed[top:top + bh, left:left + bw]
                if roi.shape[:2] == badge.shape[:2]:
                    roi[:] = (roi * (1 - badge_alpha) + badge * badge_alpha).astype(np.uint8)
                    occupied.append((left, top, bw, bh))
                tag_y = top + bh + 5
        if seconds >= freeze:
            frozen_frame = transformed.copy()
        yield transformed


def validate_visual_video(path: Path | str, manifest: dict) -> None:
    """Decode every frame before the caller is allowed to use this tail."""
    cap = cv2.VideoCapture(str(path))
    count = 0
    try:
        if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS) - manifest["fps"]) > .1:
            raise RuntimeError("线路回放视频无法播放或帧率不匹配")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (manifest["height"], manifest["width"]):
                raise RuntimeError("线路回放视频画幅不匹配")
            count += 1
    finally:
        cap.release()
    if count != manifest["frame_count"]:
        raise RuntimeError("线路回放视频不完整")


def render_visual_tail(reference_path: Path | str, manifest: dict, output_path: Path | str, *,
                       cancelled: Callable[[], bool] | None = None,
                       progress: Callable[[int], None] | None = None) -> dict:
    start = time.monotonic()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = visual_partial_path(path)
    if temporary.exists():
        raise VisualInputError("线路回放临时输出已存在")
    writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*"VP80"), manifest["fps"],
                             (manifest["width"], manifest["height"]))
    try:
        if not writer.isOpened():
            raise RuntimeError("当前环境无法编码线路回放")
        for index, frame in enumerate(iter_visual_frames(reference_path, manifest)):
            if cancelled and cancelled():
                raise RuntimeError("线路回放已取消")
            writer.write(frame)
            if progress and index % max(1, round(manifest["fps"])) == 0:
                progress(round(index / manifest["frame_count"] * 95))
        writer.release()
        validate_visual_video(temporary, manifest)
        if cancelled and cancelled():
            raise RuntimeError("线路回放已取消")
        os.replace(temporary, path)
    finally:
        writer.release()
        temporary.unlink(missing_ok=True)
    if progress:
        progress(100)
    return {key: manifest[key] for key in ("visual_version", "input_digest", "width", "height", "fps", "frame_count", "duration_seconds")} | {
        "elapsed_seconds": round(time.monotonic() - start, 3), "size_bytes": path.stat().st_size,
        "codec": "VP8", "streamed": True, "new_model_calls": 0,
    }


def visual_partial_path(output_path: Path | str) -> Path:
    """Deterministic worker-owned path, so a supervisor can clean after SIGKILL."""
    path = Path(output_path)
    return path.with_name(f".{path.name}.partial.webm")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metrics", type=Path)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    metrics = render_visual_tail(args.reference, manifest, args.output)
    if args.metrics:
        args.metrics.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
