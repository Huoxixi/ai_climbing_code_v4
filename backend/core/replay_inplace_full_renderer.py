"""Local full ending: one quiet count summary and uninterrupted real movement.

Source timestamps determine every measurement. Playback holds never add time.
No model calls, application writes, generated body pixels, or synthetic contacts.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .replay_inplace_renderer import InPlaceComposition, ease, WHITE, CYAN
from .replay_focus_renderer import VideoReader

VERSION = "replay-inplace-full-v1"
LIMBS = ("left_hand", "right_hand", "left_foot", "right_foot")


def source_state(shot, local_seconds):
    """Advance through all source frames, inserting only explicit holds."""
    start, end = shot["source_start_seconds"], shot["source_end_seconds"]
    rate = shot["playback_rate"]
    local = max(0., local_seconds)
    freeze = shot.get("freeze_at")
    if freeze is not None:
        begins = (freeze - start) / rate
        duration = shot["freeze_duration"]
        if begins <= local < begins + duration:
            return freeze, True
        if local >= begins + duration:
            local -= duration
    at = min(end, start + local * rate)
    return at, at >= end - 1e-8


def elapsed_at(timing, source_at):
    start, end = timing["start_seconds"], timing["end_seconds"]
    return max(0., min(source_at, end) - start)


def hold_elapsed(phase, source_at):
    return max(0., min(source_at, phase["end_seconds"]) - phase["start_seconds"])


def validate_manifest(manifest):
    if manifest.get("visual_version") != VERSION:
        raise ValueError("Unsupported full in-place version")
    if (manifest.get("width"), manifest.get("height"), manifest.get("fps")) != (720, 880, 30):
        raise ValueError("This local full treatment requires 720 x 880 at 30 fps")
    duration = manifest.get("duration_seconds", 0)
    last = manifest.get("last_source_seconds", -1)
    if not all(math.isfinite(v) for v in (duration, last)) or duration <= 0 or last <= 0:
        raise ValueError("Invalid duration or final source frame")
    if manifest.get("frame_count") != round(duration * 30):
        raise ValueError("Frame count does not match duration")
    shots = manifest.get("shots", [])
    if [s["kind"] for s in shots] != ["counts", "hold", "move", "summary"]:
        raise ValueError("A single simultaneous count view must precede the two action views and ending")
    cursor = 0.
    for shot in shots:
        values = [shot[k] for k in ("start_seconds", "duration_seconds", "source_start_seconds",
                                    "source_end_seconds", "playback_rate")]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Shot times must be finite")
        begins, length, start, end, rate = values
        if (abs(begins-cursor) > 1e-6 or length <= 0 or not 0 <= start <= end <= last+1e-6
                or rate <= 0 or abs(length*30-round(length*30)) > 1e-5):
            raise ValueError("Invalid or noncontiguous shot")
        extra = 0.
        if "freeze_at" in shot:
            extra = shot.get("freeze_duration", 0)
            if not math.isfinite(extra) or extra <= 0 or not start < shot["freeze_at"] < end:
                raise ValueError("Freeze must be inside the source motion")
        if (end-start)/rate + extra > length + 1e-6:
            raise ValueError("Shot would truncate its actual movement")
        if "events" in shot:
            raise ValueError("Sequential hold count events were removed from this treatment")
        cursor += length
    if abs(cursor-duration) > 1e-6:
        raise ValueError("Shots do not cover the full ending")
    if any(abs(shots[i][key]-last)>1e-6 for i in (0,3)
           for key in ("source_start_seconds", "source_end_seconds")):
        raise ValueError("Opening and ending freeze must use the actual final source frame")
    if abs(shots[2]["source_end_seconds"]-last)>1e-6:
        raise ValueError("Final motion must reach the last source frame before summary")
    summary = manifest["summary"]
    for limb in LIMBS:
        data = summary["limbs"][limb]
        if data["count"] != len(set(data["hold_ids"])):
            raise ValueError("Limb counts must be distinct hold counts")
    timing, phase = summary["timing"], summary["longest_hold"]
    if timing["outcome"] != "completed" or not 0 <= timing["start_seconds"] < timing["end_seconds"] <= last:
        raise ValueError("This reviewed local example needs a confirmed completion interval")
    if (phase["kind"] != "hold" or phase.get("status") not in {"reviewed", "confirmed"}
            or not shots[1]["source_start_seconds"] <= phase["start_seconds"] < phase["end_seconds"] <= shots[1]["source_end_seconds"]):
        raise ValueError("Longest hold must be supported and fully visible in the selected source interval")
    for limb in LIMBS:
        contact = phase.get("contacts", {}).get(limb)
        if contact is None or contact == "unknown" or contact not in summary["limbs"][limb]["hold_ids"]:
            raise ValueError("A confirmed hold requires four supported, known contacts")
    for item, key in ((timing, "elapsed_seconds"), (phase, "duration_seconds")):
        value = item.get(key)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value-(item["end_seconds"]-item["start_seconds"])) > 1e-5:
            raise ValueError("Displayed duration must agree with its source interval")
    if shots[2]["source_start_seconds"] >= timing["end_seconds"]:
        raise ValueError("Completion must be shown as motion, not an end-frame jump")


class FullComposition(InPlaceComposition):
    def __init__(self, manifest, source):
        super().__init__(manifest, source)
        self.baseline_last = None
        if manifest.get("baseline_path"):
            reader = VideoReader(manifest["baseline_path"])
            try:
                self.baseline_last = Image.fromarray(cv2.cvtColor(reader.at((reader.count-1)/reader.fps), cv2.COLOR_BGR2RGB)).convert("RGBA")
            finally:
                reader.close()

    def backdrop(self, shot, local):
        at, frozen = source_state(shot, local)
        image = self.source_image(at, still=frozen)
        # Real motion never switches to a final still until all source frames played.
        if frozen:
            dim = .08 if shot["kind"] in {"counts", "summary"} else .07
            image = Image.blend(image, Image.new("RGBA", image.size, (0,0,0,255)), dim)
        return image, at, frozen

    def count_entries(self):
        counts = [self.summary["limbs"][key]["count"] for key in LIMBS]
        # All four values have identical timing and modest weight.
        return [((38,650),"不同岩点 · 同点只计一次",24,400),
                ((38,694),f"左手 {counts[0]}    右手 {counts[1]}    左脚 {counts[2]}    右脚 {counts[3]}",28,400)]

    def hold_view(self, image, shot, local, at, frozen):
        phase = self.summary["longest_hold"]
        elapsed = hold_elapsed(phase, at)
        # Approximate quarter-second evidence does not warrant frame-precise text.
        shown = min(phase["duration_seconds"], math.floor((elapsed+1e-8)*4)/4)
        alpha = min(ease(local/.4), ease((shot["duration_seconds"]-local)/.35))
        image = self.words(image,[((432,650),"四肢用点保持不变，",28,400),
                                  ((432,690),"随后继续换点。",28,400)],alpha)
        image = self.words(image,[((38,82),"最长已确认停留",24,400),
                                  ((38,120),f"约 {shown:.1f} 秒",30,500)],alpha)
        # Small line measures only the source interval; it stops during the freeze.
        overlay = Image.new("RGBA",image.size)
        draw = ImageDraw.Draw(overlay)
        draw.line((38,164,198,164),fill=(*WHITE,round(75*alpha)),width=2)
        if elapsed > 0:
            draw.line((38,164,38+160*elapsed/phase["duration_seconds"],164),fill=(*CYAN,round(215*alpha)),width=2)
        return Image.alpha_composite(image,overlay)

    def move_view(self, image, shot, local, at, frozen):
        foot = ease(local/.25)*(1-ease((at-10.3)/.25))
        image = self.highlight(image,6,at,foot)
        if frozen and abs(at-10.7)<1e-6:
            image = self.highlight(image,6,at,.9,exclusion=(382,393,433,438))
        if at < 10.95:
            image = self.marker(image,"left_foot",at,ease((at-10.3)/.2))
        elif at < 12.0:
            strength = ease((at-10.95)/.12)*(1-ease((at-11.25)/.07))
            image = self.highlight(image,9,at,strength)
            image = self.marker(image,"right_hand",at,ease((at-11.38)/.12)*(1-ease((at-11.8)/.2)))
        alpha = ease(local/.35)
        if at < 11.85:
            lines = ("左脚先抬高，", "随后右手够向完攀点。")
            alpha *= 1-ease((at-11.65)/.2)
        else:
            lines = ("继续换脚、抬高身体，", "再将左手并到完攀点。")
            alpha *= ease((at-11.85)/.2)
        image = self.words(image,[((392,651),lines[0],28,400),((392,691),lines[1],28,400)],alpha)
        return image

    def shot_image(self, shot, local):
        image, at, frozen = self.backdrop(shot,local)
        kind = shot["kind"]
        if kind == "counts":
            if self.baseline_last is not None and local < .35:
                image = Image.blend(self.baseline_last,image,ease(local/.35))
            return self.words(image,self.count_entries(),min(ease(local/.4),ease((shot["duration_seconds"]-local)/.35)))
        if kind == "summary":
            elapsed = self.summary["timing"]["elapsed_seconds"]
            held = self.summary["longest_hold"]["duration_seconds"]
            return self.words(image,[((38,650),f"双手到达完攀点 · 用时约 {elapsed:.1f} 秒",28,400),
                                     ((38,694),f"最长已确认停留约 {held:.1f} 秒",28,400)],ease(local/.3))
        if kind == "hold":
            image = self.hold_view(image,shot,local,at,frozen)
        else:
            image = self.move_view(image,shot,local,at,frozen)
        tag = "定格" if frozen else "0.5× 慢放"
        return self.words(image,[((38,40),tag,20,400)],.8)

    def frames(self):
        try:
            shots = self.manifest["shots"]
            previous = None
            index = 0
            for frame in range(self.manifest["frame_count"]):
                at = frame / self.manifest["fps"]
                if index+1 < len(shots) and at+1e-8 >= shots[index+1]["start_seconds"]:
                    previous = self.shot_image(shots[index],shots[index]["duration_seconds"]-1/30)
                    index += 1
                shot = shots[index]
                local = at-shot["start_seconds"]
                image = self.shot_image(shot,local)
                if previous is not None and local < .3:
                    image = Image.blend(previous,image,ease(local/.3))
                yield cv2.cvtColor(np.asarray(image.convert("RGB")),cv2.COLOR_RGB2BGR)
        finally:
            self.video.close()


def render(source,manifest,output,metrics):
    validate_manifest(manifest)
    cv2.setNumThreads(1)
    output = Path(output)
    partial = output.with_name(f".{output.name}.partial.webm")
    if output.exists() or partial.exists():
        raise ValueError("Use a new private temporary output")
    started = time.perf_counter()
    writer = cv2.VideoWriter(str(partial),cv2.VideoWriter_fourcc(*"VP80"),30,(720,880))
    if not writer.isOpened():
        raise RuntimeError("VP8 encoder is unavailable")
    count = 0
    try:
        for frame in FullComposition(manifest,source).frames():
            writer.write(frame)
            count += 1
    finally:
        writer.release()
    if count != manifest["frame_count"]:
        raise ValueError("Incomplete full ending")
    partial.replace(output)
    data = {"visual_version":VERSION,"frame_count":count,"duration_seconds":count/30,
            "width":720,"height":880,"fps":30,"source_video_used":True,"model_calls":0,
            "elapsed_seconds":round(time.perf_counter()-started,3),"style_accepted_by_user":False,
            "font":"Noto Sans SC","full_frame_source":True,"sequential_counts":False,
            "completion_source_end_seconds":manifest["last_source_seconds"]}
    Path(metrics).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference","manifest","output","metrics"):
        parser.add_argument("--"+name,required=True,type=Path)
    args = parser.parse_args()
    render(args.reference,json.loads(args.manifest.read_text(encoding="utf-8")),args.output,args.metrics)


if __name__ == "__main__":
    main()
