"""Stream an evidence-bounded template over real footage, without inference.

The public wrapper runs this module in the shared cancellable resource worker.
Presentation time never changes source-time measurements. Transitions are extra
frames: they cannot replace the beginning or end of an action.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .replay_focus_renderer import VideoReader
from .replay_inplace_renderer import font, ease
from . import replay_resources

VERSION = "replay-template-v1"
WHITE = (247, 250, 251)
CYAN = (95, 226, 231)
LIMBS = {"left_hand": 9, "right_hand": 10, "left_foot": 15, "right_foot": 16}
RHYTHM_COLORS = {"hold": CYAN, "transition": WHITE, "unknown": (139, 157, 167)}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_plan(plan):
    if plan.get("version") != VERSION:
        raise ValueError("Unsupported template version")
    width, height, fps = (plan.get(k) for k in ("width", "height", "fps"))
    if (not all(isinstance(v, int) and not isinstance(v, bool) for v in (width, height, fps))
            or not (64 <= width <= 8192 and 64 <= height <= 8192 and fps == 30)):
        raise ValueError("Invalid source dimensions or frame rate")
    duration = plan.get("source_duration_seconds")
    if not _finite(duration) or not 0 < duration <= 1800:
        raise ValueError("Invalid source duration")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 1000:
        raise ValueError("Missing template shots")
    action_end, stage, total, frames = 0., 0, 0., 0
    for index, shot in enumerate(shots):
        kind = shot.get("kind")
        order = {"action": 0, "data": 1, "focus": 2}.get(kind, -1)
        if order < stage or order < 0:
            raise ValueError("Template chapters must be actions, data, then focus")
        stage = order
        start, end, rate, length = (shot.get(k) for k in (
            "source_start_seconds", "source_end_seconds", "playback_rate", "duration_seconds"))
        transition = shot.get("transition_seconds", 0.)
        if not all(_finite(v) for v in (start, end, rate, length, transition)):
            raise ValueError("Non-finite shot timing")
        if not (0 <= start <= end <= duration + 1e-5 and .2 <= rate <= 1
                and 0 < length <= 7200 and 0 <= transition <= .6):
            raise ValueError("Invalid shot timing")
        if index == 0 and transition:
            raise ValueError("First shot cannot dissolve from missing footage")
        if length + 1 / fps < (end - start) / rate:
            raise ValueError("Shot would truncate real movement")
        if kind == "action":
            if abs(start - action_end) > 1e-4:
                raise ValueError("First pass must cover every source interval in order")
            action_end = end
        for key in ("caption", "detail"):
            if not isinstance(shot.get(key, ""), str) or len(shot.get(key, "")) > 1200:
                raise ValueError("Invalid caption")
        steps = shot.get("caption_steps") or []
        previous = 0.
        for step in steps:
            a, b = step.get("start_seconds"), step.get("end_seconds")
            if not all(_finite(v) for v in (a, b)) or a < previous or not a < b <= length + 1e-4:
                raise ValueError("Invalid caption reading interval")
            previous = b
        frames += round(length * fps) + round(transition * fps)
        total += length + transition
    if abs(action_end - duration) > 1e-4:
        raise ValueError("The completion movement must remain complete")
    if not any(s["kind"] == "data" for s in shots):
        raise ValueError("Template requires basic data")
    if sum(s["kind"] == "focus" for s in shots) > 2:
        raise ValueError("At most two focused revisits")
    if total > 7200:
        raise ValueError("Template exceeds render budget")
    return frames


def output_size(width, height):
    scale = min(1., 1280 / max(width, height))
    # H.264 4:2:0 requires even dimensions; no crop or changed framing.
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def source_state(shot, local):
    start, end = shot["source_start_seconds"], shot["source_end_seconds"]
    at = min(end, start + max(0., local) * shot["playback_rate"])
    return at, start == end or at >= end


def rhythm_percentages(rhythm):
    kinds = ("hold", "transition", "unknown")
    values = [max(0., float(rhythm.get(key + "_seconds", 0))) for key in kinds]
    total = sum(values)
    if not total:
        return dict.fromkeys(kinds, 0)
    exact = [100 * value / total for value in values]
    rounded = [math.floor(value) for value in exact]
    for index in sorted(range(3), key=lambda i: exact[i] - rounded[i], reverse=True)[:100 - sum(rounded)]:
        rounded[index] += 1
    return dict(zip(kinds, rounded))


def wrap_text(value, face, width):
    """Measured Chinese/Latin wrapping, without throwing away model text."""
    lines = []
    for paragraph in str(value).splitlines():
        line = ""
        for char in paragraph:
            if line and face.getlength(line + char) > width:
                # Chinese punctuation must not become an orphan line.
                if char in "，。；：、！？,.!?;:）】》”’" and len(line) > 1:
                    carry = line[-1]
                    line = line[:-1]
                    lines.append(line)
                    line = carry + char
                    continue
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)
    return lines


@lru_cache(maxsize=16)
def _shade(size, side, top, bottom, reach):
    w, h = size
    x, y = np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)
    distance = x if side == "left" else w - 1 - x
    a = np.clip((reach - distance) / max(1, reach * .6), 0, 1)
    a = a * a * (3 - 2 * a)
    feather = max(18, w * .1)
    b = np.minimum(np.clip((y - top + feather) / feather, 0, 1),
                   np.clip((bottom + feather - y) / feather, 0, 1))
    return Image.fromarray(np.uint8(160 * b[:, None] * a[None, :]), "L")


class TemplateComposition:
    def __init__(self, plan, source):
        self.plan = plan
        self.video = VideoReader(source)
        self.size = output_size(plan["width"], plan["height"])
        self.scale = min(self.size[0] / 720, self.size[1] / 550)
        self.samples = plan.get("tracking_samples") or []
        self.last_raw = None

    def raw(self, at):
        frame = self.video.at(at)
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")

    def tracked_point(self, limb, at):
        joint = LIMBS.get(limb)
        if joint is None:
            return None
        before = [p for p in self.samples if p.get("time_seconds", -1) <= at]
        after = [p for p in self.samples if p.get("time_seconds", -1) >= at]
        if not before or not after:
            return None
        a, b = before[-1], after[0]
        gap = b["time_seconds"] - a["time_seconds"]
        if gap > .35:
            return None
        for sample in (a, b):
            xy, scores = sample.get("kpts_xy", []), sample.get("kpts_score", [])
            if (not sample.get("observed") or len(xy) <= joint or len(scores) <= joint
                    or scores[joint] < .5 or not all(0 < v < 1 for v in xy[joint])):
                return None
        weight = (at - a["time_seconds"]) / max(1e-8, gap)
        point = np.asarray(a["kpts_xy"][joint]) * (1 - weight) + np.asarray(b["kpts_xy"][joint]) * weight
        return point * np.asarray(self.size)

    def _anchor(self, shot, box_height, box_width):
        w, h = self.size
        margin = 30 * self.scale
        # Leave room for native mobile playback controls when a viewer pauses
        # on the data/teaching frame. The movie itself has no opaque panel.
        bottom_guard = max(100 * self.scale, h * .16)
        candidates = [(side, top) for top in (h * .12, h - bottom_guard - box_height)
                      for side in (shot.get("caption_side", "left"),
                                   "right" if shot.get("caption_side", "left") == "left" else "left")]
        samples = [p for p in self.samples if shot["source_start_seconds"] - .1 <= p.get("time_seconds", -1)
                   <= shot["source_end_seconds"] + .1 and p.get("observed")]
        def score(candidate):
            side, top = candidate
            left = margin if side == "left" else w - margin - box_width
            overlap = 0
            for sample in samples[::max(1, len(samples) // 16)]:
                for point, confidence in zip(sample.get("kpts_xy", []), sample.get("kpts_score", [])):
                    if confidence >= .4 and len(point) == 2:
                        x, y = point[0] * w, point[1] * h
                        if left - margin <= x <= left + box_width + margin and top - margin <= y <= top + box_height + margin:
                            overlap += 1
            return overlap
        side, top = min(candidates, key=score)
        return side, max(margin, top)

    def caption(self, image, shot, local):
        w, h = self.size
        length = shot["duration_seconds"]
        value, detail = shot.get("caption", ""), shot.get("detail", "")
        age, remaining = local, length - local
        for step in shot.get("caption_steps") or []:
            if step["start_seconds"] <= local < step["end_seconds"]:
                value, detail = step.get("caption", ""), step.get("detail", "")
                age, remaining = local - step["start_seconds"], step["end_seconds"] - local
                break
        alpha = ease(age / .18) * ease(remaining / .16)
        if shot["kind"] == "action":
            reading_time = max(4., len(value) / 5.5)
            alpha *= 1 - ease((local - reading_time) / .25)
        face = font(max(14, round(28 * self.scale)))
        small = font(max(12, round(23 * self.scale)))
        width = w * .68
        main = wrap_text(value, face, width)
        secondary = wrap_text(detail, small, width)
        # Long advice is shown as successive reading pages, never tiny type.
        pages = [main[i:i + 2] for i in range(0, len(main), 2)] or [[]]
        page = min(len(pages) - 1, int(max(0, age) / max(2.4, (age + remaining) / len(pages))))
        main = pages[page]
        line_height, small_height = face.size * 1.45, small.size * 1.5
        # Details are metadata for the viewer, not the full evidence report.
        secondary = secondary[:2]
        box_height = len(main) * line_height + len(secondary) * small_height + 10 * self.scale
        side, top = self._anchor(shot, box_height, width)
        margin = 30 * self.scale
        x = margin if side == "left" else w - margin - width
        layer = Image.new("RGBA", self.size, (3, 10, 13, 0))
        mask = _shade(self.size, side, round(top), round(top + box_height), round(width + margin * 2))
        layer.putalpha(mask.point(lambda v: round(v * alpha)))
        image = Image.alpha_composite(image, layer)
        glyphs = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(glyphs)
        y = top + 4 * self.scale * (1 - ease(age / .18))
        for line in main:
            draw.text((x, y), line, font=face, fill=(*WHITE, round(255 * alpha)), anchor="lt")
            y += line_height
        for line in secondary:
            draw.text((x, y + 7 * self.scale), line, font=small, fill=(*CYAN, round(240 * alpha)), anchor="lt")
            y += small_height
        return Image.alpha_composite(image, glyphs)

    def data_image(self, image, shot, local):
        """Small over-footage measurements; all four counts arrive together."""
        metrics = shot.get("metrics") or {}
        kind = metrics.get("data_kind")
        if kind not in {"counts", "rhythm"}:
            return self.caption(image, shot, local)
        w, h = self.size
        scale = self.scale
        face = font(max(14, round(28 * scale)))
        small = font(max(12, round(23 * scale)))
        number = font(max(16, round(34 * scale)), 500)
        alpha = ease(local / .18) * ease((shot["duration_seconds"] - local) / .16)
        width = w * .7
        rows = []
        bar = None
        if kind == "counts":
            timing = metrics.get("timing") or {}
            seconds = timing.get("value_seconds")
            title = str(timing.get("label") or "已观察时长")
            if _finite(seconds):
                title += f"约 {seconds:.1f} 秒"
            rows.extend((line, "title") for line in wrap_text(title, face, width))
            reviewed = all(item.get("status") == "reviewed" for item in metrics.get("limbs") or [])
            rows.append(("四肢用点 · 去重统计" if reviewed else "已识别用点 · 待复核", "small"))
            for item in metrics.get("limbs") or []:
                count = item.get("count")
                displayed = str(count) if isinstance(count, int) and count >= 0 else "未确认"
                rows.append((str(item.get("label") or ""), "count", displayed))
            ending = {"completed": "已确认完攀", "topped_out": "已确认完攀",
                      "fell": "用时计到脱落", "fall": "用时计到脱落", "fallen": "用时计到脱落",
                      "truncated": "片段已截断，未确认完攀"}.get(timing.get("outcome"), "离地与完攀边界尚未确认")
            caption = ending + "\n同一岩点重复使用只计一次"
            rows.extend((line, "small") for line in wrap_text(caption, small, width))
        else:
            rhythm = metrics.get("rhythm") or {}
            total = rhythm.get("duration_seconds", 0)
            rows.append(("整体攀爬节奏", "title"))
            bar = {**rhythm, "duration_seconds": total}
            rows.append(("", "bar"))
            percentages = rhythm_percentages(rhythm)
            for key, label in (("hold", "保持用点"), ("transition", "换点移动"), ("unknown", "观测不清")):
                value = rhythm.get(key + "_seconds", 0)
                percent = percentages[key]
                rows.append((f"{label}  {percent:.0f}% · 约 {value:.1f} 秒", "rhythm", key))
            longest = metrics.get("longest_hold")
            if longest and _finite(longest.get("duration_seconds")):
                label = f'{longest.get("label", "最长已识别停留")}约 {longest["duration_seconds"]:.1f} 秒'
            else:
                label = "最长停留暂无足够依据"
            rows.extend((line, "small") for line in wrap_text(label, small, width))
            reviewed = (self.plan.get("summary", {}).get("provenance") or {}).get("review_applied")
            rows.append(("原片时间 · 据核查记录" if reviewed else "原片时间 · 自动估计", "small"))
            if shot is self.plan["shots"][-1] and not any(s["kind"] == "focus" for s in self.plan["shots"]):
                rows.append(("本次暂无可靠修改建议", "small"))
        heights = {"title": 44 * scale, "count": 44 * scale, "bar": 36 * scale,
                   "rhythm": 38 * scale, "small": 34 * scale}
        box_height = sum(heights[row[1]] for row in rows)
        side, top = self._anchor(shot, box_height, width)
        margin = 30 * scale
        x = margin if side == "left" else w - margin - width
        shade = Image.new("RGBA", self.size, (3, 10, 13, 0))
        mask = _shade(self.size, side, round(top), round(top + box_height), round(width + margin * 2))
        shade.putalpha(mask.point(lambda v: round(v * alpha)))
        image = Image.alpha_composite(image, shade)
        overlay = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(overlay)
        y = top
        for row in rows:
            value, style = row[:2]
            if style == "count":
                draw.text((x, y), value, font=face, fill=(*WHITE, round(245 * alpha)), anchor="lt")
                draw.text((x + 105 * scale, y - 2 * scale), row[2], font=number,
                          fill=(*CYAN, round(255 * alpha)), anchor="lt")
                if row[2] != "未确认":
                    draw.text((x + 172 * scale, y + 4 * scale), "个点", font=small,
                              fill=(*WHITE, round(220 * alpha)), anchor="lt")
            elif style == "bar":
                segments = (bar or {}).get("segments") or []
                total = (bar or {}).get("duration_seconds", 0)
                start = (bar or {}).get("start_seconds", 0)
                shown = start + total * ease(local / .8)
                for segment in segments:
                    left = max(start, segment["start_seconds"])
                    right = min(shown, segment["end_seconds"])
                    if total <= 0 or right <= left:
                        continue
                    a = x + width * (left - start) / total
                    b = x + width * (right - start) / total
                    draw.rectangle((a, y + 9 * scale, b, y + 18 * scale),
                                   fill=(*RHYTHM_COLORS[segment["kind"]], round(220 * alpha)))
            else:
                offset = 0
                if style == "rhythm":
                    draw.rectangle((x, y + 8 * scale, x + 7 * scale, y + 15 * scale),
                                   fill=(*RHYTHM_COLORS[row[2]], round(230 * alpha)))
                    offset = 18 * scale
                draw.text((x + offset, y), value, font=face if style == "title" else small,
                          fill=(*WHITE, round((245 if style == "title" else 230) * alpha)), anchor="lt")
            y += heights[style]
        return Image.alpha_composite(image, overlay)

    def shot_image(self, shot, local):
        at, frozen = source_state(shot, local)
        image = self.raw(at)
        self.last_raw = image.copy()
        image = self.data_image(image, shot, local) if shot["kind"] == "data" else self.caption(image, shot, local)
        overlay = Image.new("RGBA", self.size)
        d = ImageDraw.Draw(overlay)
        w, h = self.size
        margin = round(30 * self.scale)
        if shot["kind"] in {"action", "focus"}:
            state = "定格" if frozen else f'{shot["playback_rate"]:g}× 慢放'
            label = f"原片 {at:.1f} 秒 · {state}"
            small = font(max(11, round(19 * self.scale)))
            d.text((margin, h - margin), label, font=small, fill=(*WHITE, 220), anchor="lb",
                   stroke_width=1, stroke_fill=(0, 0, 0, 130))
            # A source-time line shows the movement within this group, not playback time.
            span = shot["source_end_seconds"] - shot["source_start_seconds"]
            if span > 0:
                y = h - margin * .55
                d.line((margin, y, w - margin, y), fill=(*WHITE, 65), width=max(1, round(2 * self.scale)))
                d.line((margin, y, margin + (w - 2 * margin) * (at - shot["source_start_seconds"]) / span, y),
                       fill=(*CYAN, 190), width=max(1, round(2 * self.scale)))
            point = self.tracked_point(shot.get("focus_limb"), at)
            if point is not None:
                x, y = point
                radius = max(3, 6 * self.scale)
                strength = ease(local / .18) * ease((shot["duration_seconds"] - local) / .16)
                d.ellipse((x - radius, y - radius, x + radius, y + radius),
                          outline=(*CYAN, round(200 * strength)), width=max(1, round(2 * self.scale)))
        return Image.alpha_composite(image, overlay)

    def frames(self):
        fps = self.plan["fps"]
        for shot in self.plan["shots"]:
            count = round(shot["duration_seconds"] * fps)
            dissolve = round(shot.get("transition_seconds", 0.) * fps)
            if dissolve and self.last_raw is not None:
                previous, upcoming = self.last_raw.copy(), self.raw(shot["source_start_seconds"])
                for i in range(dissolve):
                    yield Image.blend(previous, upcoming, ease((i + 1) / dissolve))
            for frame in range(count):
                yield self.shot_image(shot, frame / fps)


def _ffmpeg():
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    from imageio_ffmpeg import get_ffmpeg_exe
    return get_ffmpeg_exe()


def _render(source, plan, output, metrics_path, *, composition_factory=None, validator=None):
    expected = (validator or validate_plan)(plan)
    output, metrics_path = Path(output), Path(metrics_path)
    partial = output.with_name(f".{output.name}.partial.mp4")
    if output.exists() or partial.exists():
        raise ValueError("Use a new private output path")
    cv2.setNumThreads(1)
    started = time.monotonic()
    composition = (composition_factory or TemplateComposition)(plan, source)
    if not _finite(composition.video.fps) or composition.video.fps <= 0 or composition.video.count <= 0:
        composition.video.close()
        raise ValueError("Source has no valid frame timeline")
    actual = composition.video.count / composition.video.fps
    if abs(actual - plan["source_duration_seconds"]) > max(.1, 2 / composition.video.fps):
        composition.video.close()
        raise ValueError("Source duration no longer matches evidence")
    width, height = composition.size
    command = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
               "-r", str(plan["fps"]), "-i", "pipe:0", "-an", "-c:v", "libx264", "-threads", "1",
               "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)]
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        count = 0
        for image in composition.frames():
            process.stdin.write(image.convert("RGB").tobytes())
            count += 1
        process.stdin.close()
        if process.wait(timeout=30) != 0 or count != expected:
            raise RuntimeError("Template encoder did not complete")
        cap = cv2.VideoCapture(str(partial))
        decoded = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame.shape[:2] != (height, width):
                    raise ValueError("Output framing changed")
                decoded += 1
        finally:
            cap.release()
        if decoded != expected:
            raise ValueError("Template video failed full decode")
        partial.replace(output)
        result = {"version": plan["version"], "width": width, "height": height, "fps": plan["fps"],
                  "frame_count": count, "duration_seconds": count / plan["fps"], "fully_decoded": True,
                  "source_video_used": True, "model_calls": 0, "audio": "none",
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        if process is not None:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        composition.video.close()
        partial.unlink(missing_ok=True)


def render_template_video(source_path, plan, output_path, *, cancelled=None, progress=None):
    """Atomic output; shared process-tree memory limits, cancellation and queue."""
    validate_plan(plan)
    source, output = Path(source_path), Path(output_path)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError("Use a new private output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="template-render-", dir=output.parent) as temporary:
        root = Path(temporary)
        manifest, staged, metrics = root / "plan.json", root / "video.mp4", root / "metrics.json"
        manifest.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        duration = sum(s["duration_seconds"] + s.get("transition_seconds", 0) for s in plan["shots"])
        result = replay_resources.run_visual_worker(source, manifest, staged, metrics,
            worker_module="core.replay_template_renderer", cancelled=cancelled, progress=progress,
            timeout_seconds=min(3600, max(120, duration * 5)))
        if cancelled and cancelled():
            raise InterruptedError("任务已取消")
        staged.replace(output)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "manifest", "output", "metrics"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    _render(args.reference, json.loads(args.manifest.read_text(encoding="utf-8")), args.output, args.metrics)


if __name__ == "__main__":
    main()
