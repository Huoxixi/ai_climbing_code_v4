"""Local, source-video-led replay chapters; no inference or application imports.

Source time and presentation time stay separate. Saved poses locate a small
limb marker only; they never generate body pixels or new measured evidence.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

VERSION = "replay-focus-v1"
PAPER = (245, 243, 237)
INK = (29, 48, 48)
MUTED = (83, 103, 101)
TEAL = (16, 117, 117)
RULE = (207, 214, 207)
LIMBS = {"left_hand": ("左手", 9, (36, 159, 199)),
         "right_hand": ("右手", 10, (199, 91, 158)),
         "left_foot": ("左脚", 15, (212, 144, 42)),
         "right_foot": ("右脚", 16, (82, 151, 103))}


@lru_cache(maxsize=40)
def font(size, bold=False):
    names = ([os.environ.get("REPLAY_CJK_FONT_BOLD")] if bold else [os.environ.get("REPLAY_CJK_FONT")])
    names += (["C:/Windows/Fonts/msyhbd.ttc"] if bold else ["C:/Windows/Fonts/msyh.ttc"])
    names += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for name in names:
        if name and Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise ValueError("A Chinese font is required for the local sample")


def text(draw, xy, value, size=24, fill=INK, bold=False, anchor=None):
    draw.text(xy, str(value), font=font(size, bold), fill=fill, anchor=anchor,
              stroke_width=0)


def seconds(value):
    return "待确认" if value is None else f"约 {float(value):.1f} 秒"


def timing_display(timing):
    completed = timing.get("outcome") == "completed"
    fallen = timing.get("outcome") in {"fell", "fallen", "fall"}
    elapsed = timing.get("elapsed_seconds")
    terminal = (completed or fallen) and elapsed is not None
    duration = elapsed if elapsed is not None else timing.get("observed_duration_seconds")
    return completed, fallen, terminal, duration


def source_time(shot, local_seconds):
    """Freeze after the selected source end; never rewind or invent time."""
    start = float(shot.get("source_start_seconds", 0))
    end = float(shot.get("source_end_seconds", start))
    return min(end, start + max(0., local_seconds) * float(shot.get("playback_rate", 1)))


def validate_manifest(manifest):
    if manifest.get("visual_version") != VERSION:
        raise ValueError("Unsupported focus visual version")
    width, height = manifest.get("width"), manifest.get("height")
    if (width, height) != (720, 880):
        raise ValueError("This reviewed sample composition requires 720 x 880")
    fps = float(manifest.get("fps", 0))
    if not 1 <= fps <= 60:
        raise ValueError("Invalid frame rate")
    duration = float(manifest.get("duration_seconds", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid presentation duration")
    cursor = 0.
    for shot in manifest.get("shots", []):
        start, length = float(shot["start_seconds"]), float(shot["duration_seconds"])
        if not all(math.isfinite(v) for v in (start, length)) or abs(start - cursor) > 1e-5 or length <= 0:
            raise ValueError("Chapters must be positive, contiguous intervals")
        if abs(length * fps - round(length * fps)) > 1e-5:
            raise ValueError("Chapter durations must align with video frames")
        if shot["kind"] not in {"overview", "hold", "move", "counts", "summary"}:
            raise ValueError("Unsupported chapter kind")
        if shot["kind"] in {"overview", "hold", "move"}:
            a, b = float(shot["source_start_seconds"]), float(shot["source_end_seconds"])
            rate = float(shot.get("playback_rate", 1))
            if not all(math.isfinite(v) for v in (a, b, rate)) or a < 0 or b < a or rate <= 0:
                raise ValueError("Invalid source interval")
        cursor += length
    if not manifest.get("shots") or abs(cursor - duration) > 1e-5:
        raise ValueError("Invalid chapter duration")
    if round(cursor * fps) != int(manifest["frame_count"]):
        raise ValueError("Frame count does not match presentation time")


class VideoReader:
    """Sequential bounded-memory source decoding, including repeated frames."""
    def __init__(self, path):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise ValueError("Source video cannot be opened")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.index = -1
        self.frame = None

    def at(self, seconds_value):
        wanted = min(self.count - 1, max(0, round(seconds_value * self.fps)))
        if wanted < self.index or wanted > self.index + 12:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, wanted)
            self.index = wanted - 1
        while self.index < wanted:
            ok, frame = self.cap.read()
            if not ok:
                raise ValueError(f"Could not decode source frame {wanted}")
            self.index += 1
            self.frame = frame
        return self.frame

    def close(self):
        self.cap.release()


class Composition:
    def __init__(self, manifest, source):
        self.manifest = manifest
        self.summary = manifest["summary"]
        result = json.loads(Path(manifest["result_path"]).read_text(encoding="utf-8"))
        self.samples = sorted(result.get("pose_samples") or [], key=lambda p: p["time_seconds"])
        self.holds = {str(h["id"]): h for h in result.get("holds") or []}
        self.sw, self.sh = result["video"]["width"], result["video"]["height"]
        self.video = VideoReader(source)
        self.snapshot = None

    def measured_point(self, limb, at):
        joint = LIMBS[limb][1]
        before = [p for p in self.samples if p["time_seconds"] <= at]
        after = [p for p in self.samples if p["time_seconds"] >= at]
        if not before or not after:
            return None
        a, b = before[-1], after[0]
        if b["time_seconds"] - a["time_seconds"] > .35:
            return None
        for p in (a, b):
            if (not p.get("observed") or len(p.get("kpts_score", [])) <= joint
                    or p["kpts_score"][joint] < .35
                    or not all(v > 0 for v in p["kpts_xy"][joint])):
                return None
        weight = (at - a["time_seconds"]) / max(1e-8, b["time_seconds"] - a["time_seconds"])
        point = np.asarray(a["kpts_xy"][joint]) * (1 - weight) + np.asarray(b["kpts_xy"][joint]) * weight
        return point * [self.sw, self.sh]

    def polygon(self, hold_id, at):
        hold = self.holds.get(str(hold_id))
        if not hold or not self.samples:
            return None
        sample = min(self.samples, key=lambda p: abs(p["time_seconds"] - at))
        if abs(sample["time_seconds"] - at) > .3 or sample.get("wall_alignment") not in {"aligned", "reference"}:
            return None
        matrix = np.asarray(sample.get("wall_reference_transform"), np.float64)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            return None
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            return None
        points = np.asarray(hold["polygon"], np.float32) * [self.sw, self.sh]
        return cv2.perspectiveTransform(points.astype(np.float32)[None], inverse)[0]

    def chapter_header(self, canvas, shot, local):
        d = ImageDraw.Draw(canvas)
        text(d, (32, 20), shot["title"], 32, bold=True)
        text(d, (32, 66), shot.get("description", ""), 21, MUTED)
        x = 32
        for part in self.manifest["shots"]:
            length = 656 * part["duration_seconds"] / self.manifest["duration_seconds"]
            color = TEAL if part["id"] == shot["id"] else RULE
            d.rectangle((x, 103, x + length - 4, 106), fill=color)
            x += length

    def motion(self, shot, local):
        at = source_time(shot, local)
        frame = self.video.at(at)
        crop = shot.get("crop", [0, 140, self.sw, 600])
        cx, cy, cw, ch = map(int, crop)
        if cx < 0 or cy < 0 or cx + cw > self.sw or cy + ch > self.sh:
            raise ValueError("Chapter crop leaves the real source image")
        view = cv2.resize(frame[cy:cy+ch, cx:cx+cw], (672, 560), interpolation=cv2.INTER_AREA)
        canvas = Image.new("RGB", (720, 880), PAPER)
        canvas.paste(Image.fromarray(cv2.cvtColor(view, cv2.COLOR_BGR2RGB)), (24, 120))
        header = shot
        phase = self.summary.get("longest_hold") if shot["kind"] == "hold" else None
        entering_hold = bool(phase and at < phase["start_seconds"])
        if entering_hold:
            header = {**shot, "description": "先看进入保持前的动作"}
        self.chapter_header(canvas, header, local)
        d = ImageDraw.Draw(canvas)

        def mapped(point):
            return (24 + (point[0] - cx) * 672 / cw, 120 + (point[1] - cy) * 560 / ch)

        def mark_hold(hold_id, color):
            polygon = self.polygon(hold_id, at)
            if polygon is None:
                return
            points = [mapped(p) for p in polygon]
            if all(26 < x < 694 and 122 < y < 678 for x, y in points):
                d.line(points + points[:1], fill=(255, 255, 247), width=6, joint="curve")
                d.line(points + points[:1], fill=color, width=3, joint="curve")

        limb = shot.get("focus_limb")
        if limb:
            color = LIMBS[limb][2]
            mark_hold(shot.get("target_hold_id"), color)
            point = self.measured_point(limb, at)
            if point is not None:
                x, y = mapped(point)
                if 44 < x < 676 and 144 < y < 656:
                    d.ellipse((x-10, y-10, x+10, y+10), outline=(255, 255, 247), width=5)
                    d.ellipse((x-9, y-9, x+9, y+9), outline=color, width=3)
                    label_x = max(38, min(595, x + 20))
                    label_y = max(158, min(637, y - 24))
                    d.line((x+10, y, label_x, label_y+15), fill=(255, 255, 247), width=2)
                    d.rectangle((label_x-5, label_y-3, label_x+63, label_y+30), fill=INK)
                    text(d, (label_x, label_y), LIMBS[limb][0], 23, (255, 255, 247))
        # Actual frame content remains visible; the tag describes playback only.
        frozen = local * float(shot.get("playback_rate", 1)) >= shot["source_end_seconds"] - shot["source_start_seconds"]
        speed = "定格" if frozen else "原速" if shot.get("playback_rate", 1) == 1 else f'{shot["playback_rate"]:g}× 慢放'
        tag = f"{speed}  ·  原片 {at:04.1f}s"
        d.rectangle((36, 134, 328, 172), fill=INK)
        text(d, (46, 139), tag, 20, (255, 255, 247))
        if shot["kind"] == "overview":
            timing = self.summary["timing"]
            completed, fallen, terminal, elapsed = timing_display(timing)
            label = "离地 → 双手到达完攀点" if terminal and completed else "离地 → 脱落" if terminal and fallen else "已观察时长 · 起止待确认"
            text(d, (32, 706), label, 25)
            text(d, (32, 751), seconds(elapsed), 48, TEAL, True)
            text(d, (688, 843), "按原视频计时", 20, MUTED, anchor="ra")
        elif shot["kind"] == "hold":
            phase = self.summary.get("longest_hold")
            if not phase:
                raise ValueError("A hold chapter needs a reliable source phase")
            elapsed = max(0., min(phase["duration_seconds"], at - phase["start_seconds"]))
            text(d, (32, 701), "进入保持前 · 这段不计入停留" if entering_hold else "同一组岩点，身体仍可调整", 25)
            text(d, (32, 743), f"{elapsed:.1f}", 52, TEAL, True)
            text(d, (142, 772), f'/ {phase["duration_seconds"]:.1f} 秒', 25, MUTED)
            d.rectangle((300, 767, 686, 777), fill=RULE)
            d.rectangle((300, 767, 300 + 386*elapsed/max(.001, phase["duration_seconds"]), 777), fill=TEAL)
            text(d, (32, 831), "最长已确认停留 · 不把换点过程计入", 21, MUTED)
        else:
            text(d, (32, 706), shot.get("caption", "观察移动与落点"), 29, bold=True)
            text(d, (32, 754), shot.get("detail", ""), 24, MUTED)
            text(d, (32, 831), "只标当前肢体与目标岩点", 21, MUTED)
        return canvas

    def mini_hold(self, d, hold_id, box, color, amount=1.):
        hold = self.holds.get(str(hold_id))
        if not hold:
            return
        poly = np.asarray(hold["polygon"], float)
        a, b = poly.min(axis=0), poly.max(axis=0)
        x, y, w, h = box
        scale = min(w / max(1e-6, (b-a)[0]), h / max(1e-6, (b-a)[1])) * (.88+.12*amount)
        p = (poly - (a+b)/2) * scale + [x+w/2, y+h/2]
        fill = tuple(round(PAPER[i]*(1-amount) + (195, 225, 220)[i]*amount) for i in range(3))
        stroke = tuple(round(PAPER[i]*(1-amount) + color[i]*amount) for i in range(3))
        d.polygon([tuple(v) for v in p], fill=fill)
        d.line([tuple(v) for v in p]+[tuple(p[0])], fill=stroke, width=2, joint="curve")

    def counts(self, shot, local):
        canvas = Image.new("RGB", (720, 880), PAPER)
        self.chapter_header(canvas, shot, local)
        d = ImageDraw.Draw(canvas)
        for row, (limb, (name, _, color)) in enumerate(LIMBS.items()):
            y = 163 + row*145
            stat = self.summary["limbs"][limb]
            ids = stat["hold_ids"]
            text(d, (32, y+21), name, 28, bold=True)
            d.line((32, y+108, 688, y+108), fill=RULE, width=1)
            visible = max(0., min(1., (local - .35 - row*.62)/.8))
            for index, hid in enumerate(ids):
                amount = max(0., min(1., visible*max(1,len(ids))-index))
                if amount <= 0:
                    continue
                self.mini_hold(d, hid, (159+index*77, y+10, 52, 49), color, amount)
                text(d, (185+index*77, y+74), f"{hid}号", 19, MUTED, anchor="mm")
            shown = min(len(ids), math.floor(visible*len(ids)+1e-5))
            text(d, (650, y+35), shown, 44, color, True, anchor="mm")
            text(d, (650, y+83), "个点", 20, MUTED, anchor="mm")
        text(d, (32, 795), "重复使用同一点，只计一次", 25, bold=True)
        text(d, (32, 837), "线路岩点 · 本地视频核查估计", 21, MUTED)
        return canvas

    def final(self, shot):
        if self.snapshot is not None:
            return self.snapshot.copy()
        canvas = Image.new("RGB", (720, 880), PAPER)
        self.chapter_header(canvas, shot, 0)
        d = ImageDraw.Draw(canvas)
        end = self.summary["timing"].get("end_seconds") or self.video.count/self.video.fps-1/self.video.fps
        frame = self.video.at(end)
        thumb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        thumb = thumb.crop((300, 180, 700, 730)).resize((216, 297), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (32, 137))
        timing = self.summary["timing"]
        completed, fallen, terminal, elapsed = timing_display(timing)
        text(d, (285, 145), "攀爬用时" if terminal else "已观察时长", 24, MUTED)
        text(d, (285, 187), seconds(elapsed), 44, TEAL, True)
        text(d, (285, 265), "最长已确认停留", 24, MUTED)
        longest = self.summary.get("longest_hold")
        text(d, (285, 307), seconds(longest["duration_seconds"] if longest else None), 44, TEAL, True)
        text(d, (285, 394), "双手到达完攀点" if completed else "以脱落结束计时" if terminal else "未确认完攀", 23)
        d.line((32, 472, 688, 472), fill=RULE, width=1)
        for i, (limb, (name, _, color)) in enumerate(LIMBS.items()):
            x = 114 + i*164
            text(d, (x, 507), name, 24, MUTED, anchor="mm")
            text(d, (x, 558), self.summary["limbs"][limb]["count"], 45, color, True, anchor="mm")
            text(d, (x, 600), "个不同岩点", 20, MUTED, anchor="mm")
        text(d, (32, 659), "全程节奏", 25, bold=True)
        start = timing.get("start_seconds")
        end = timing.get("end_seconds")
        start = timing.get("observed_start_seconds", 0) if start is None else start
        end = timing.get("observed_end_seconds", start) if end is None else end
        for phase in self.summary["phases"]:
            color = {"hold": TEAL, "transition": (211, 183, 132), "unknown": (191, 196, 191)}[phase["kind"]]
            left = 32+656*(phase["start_seconds"]-start)/max(.001, end-start)
            right = 32+656*(phase["end_seconds"]-start)/max(.001, end-start)
            d.rectangle((left, 705, right, 737), fill=color)
        for x, title, color in [(32,"保持",TEAL),(210,"换点",(211,183,132)),(388,"观测缺口",(191,196,191))]:
            d.rectangle((x, 759, x+13, 772), fill=color)
            text(d, (x+23, 752), title, 21, MUTED)
        text(d, (32, 829), "按原片计时 · 自动记录经本地核查，待你确认", 20, MUTED)
        self.snapshot = canvas.copy()
        return canvas

    def frames(self):
        try:
            for shot in self.manifest["shots"]:
                count = round(shot["duration_seconds"] * self.manifest["fps"])
                for i in range(count):
                    local = i/self.manifest["fps"]
                    if shot["kind"] == "counts":
                        frame = self.counts(shot, local)
                    elif shot["kind"] == "summary":
                        frame = self.final(shot)
                    else:
                        frame = self.motion(shot, local)
                    yield cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)
        finally:
            self.video.close()


def render(source, manifest, output, metrics):
    validate_manifest(manifest)
    cv2.setNumThreads(1)
    output = Path(output)
    partial = output.with_name(f".{output.name}.partial.webm")
    if output.exists() or partial.exists():
        raise ValueError("Use a new temporary video output")
    started = time.perf_counter()
    writer = cv2.VideoWriter(str(partial), cv2.VideoWriter_fourcc(*"VP80"), manifest["fps"], (720,880))
    if not writer.isOpened():
        raise RuntimeError("VP8 encoder unavailable")
    composition = Composition(manifest, source)
    count = 0
    try:
        for frame in composition.frames():
            writer.write(frame)
            count += 1
        writer.release()
        if count != manifest["frame_count"]:
            raise ValueError("Wrong rendered frame count")
        cap = cv2.VideoCapture(str(partial))
        decoded = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[:2] != (880,720):
                raise ValueError("Wrong rendered dimensions")
            decoded += 1
        cap.release()
        if decoded != count:
            raise ValueError("Rendered video failed full decode")
        partial.replace(output)
        result = {"visual_version": VERSION, "width":720,"height":880,"fps":manifest["fps"],
                  "frame_count":count,"duration_seconds":count/manifest["fps"],
                  "elapsed_seconds":round(time.perf_counter()-started,3),"source_video_used":True,
                  "model_calls":0}
        Path(metrics).write_text(json.dumps(result, ensure_ascii=False, indent=2),encoding="utf-8")
    finally:
        writer.release()
        composition.video.close()
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference","manifest","output","metrics"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    render(args.reference, json.loads(args.manifest.read_text(encoding="utf-8")), args.output, args.metrics)


if __name__ == "__main__":
    main()
