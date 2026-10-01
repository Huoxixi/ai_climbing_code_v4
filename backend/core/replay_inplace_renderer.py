"""A local fifteen-second style study drawn directly over the source video.

No inference, synthetic body, scene reconstruction or application imports.
All displayed source times, count events and frame choices are auditable data.
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .replay_focus_renderer import Composition

VERSION = "replay-inplace-v1"
WHITE = (248, 250, 252)
CYAN = (94, 229, 240)


def ease(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


@lru_cache(maxsize=12)
def font(size, weight=400):
    candidates = [os.environ.get("REPLAY_NOTO_FONT"), "C:/Windows/Fonts/NotoSansSC-VF.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  str(Path(__file__).resolve().parents[1] / "vendor/NotoSansSC-VF.ttf")]
    for path in candidates:
        if path and Path(path).is_file():
            value = ImageFont.truetype(path, size)
            try:
                value.set_variation_by_axes([weight])
            except (OSError, AttributeError):
                pass
            return value
    raise ValueError("Noto Sans Chinese is required for this approved style")


def validate_manifest(manifest):
    if manifest.get("visual_version") != VERSION:
        raise ValueError("Unsupported inplace visual version")
    if (manifest.get("width"), manifest.get("height"), manifest.get("fps"),
        manifest.get("frame_count"), manifest.get("duration_seconds")) != (720,880,30,450,15):
        raise ValueError("This local style study is exactly fifteen seconds at 720 x 880 / 30 fps")
    move = manifest["motion"]
    values = [float(move[k]) for k in ("source_start", "source_end", "rate", "freeze_at", "freeze_duration")]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Source times must be finite")
    start, end, rate, freeze, duration = values
    if not (0 <= start < freeze < end and rate > 0 and duration > 0):
        raise ValueError("Invalid motion or freeze interval")
    if abs((end-start)/rate + duration - 7) > 1e-5:
        raise ValueError("Motion must occupy seven presentation seconds")
    if any(abs(a-b)>1e-5 for a,b in zip(values,(9.7,12.3,.5,10.7,1.8))):
        raise ValueError("This reviewed visibility study requires its approved source interval")
    counts = manifest["counts"]
    if counts.get("limb") != "left_hand":
        raise ValueError("This approved style study presents left-hand counts")
    events = counts["events"]
    ids = [event["hold_id"] for event in events]
    expected = manifest["summary"]["limbs"]["left_hand"]["hold_ids"]
    if ids != expected or len(ids) != len(set(ids)):
        raise ValueError("Count events must match reviewed, deduplicated left-hand evidence")
    event_times = [float(e["display_at"]) for e in events]
    if any(not math.isfinite(v) or not 7 <= v < 15 for v in event_times) or event_times != sorted(set(event_times)):
        raise ValueError("Count events must be strictly ordered inside the count chapter")
    switch, fade = float(counts["switch_at"]), float(counts["crossfade_seconds"])
    if not (7 < switch < switch + fade < 15):
        raise ValueError("Invalid real-frame transition")
    for event in events:
        if switch-.18 <= event["display_at"] < switch+fade or event["display_at"] < 7.3:
            raise ValueError("A count event cannot occur while its real frame is crossfading")
        frame = counts["late_frame"] if event["display_at"] < switch else counts["early_frame"]
        if event["hold_id"] not in frame["visible_holds"]:
            raise ValueError("A count event needs a reviewed visible hold")


def source_state(manifest, display_time):
    move = manifest["motion"]
    freeze_start = (move["freeze_at"] - move["source_start"])/move["rate"]
    freeze_end = freeze_start + move["freeze_duration"]
    if display_time < freeze_start:
        return move["source_start"] + display_time*move["rate"], False
    if display_time < freeze_end:
        return move["freeze_at"], True
    return min(move["source_end"], move["freeze_at"] + (display_time-freeze_end)*move["rate"]), False


def count_state(manifest, display_time):
    active = [e for e in manifest["counts"]["events"] if display_time + 1e-8 >= e["display_at"]]
    return len(active), active[-1] if active else None


class InPlaceComposition(Composition):
    def __init__(self, manifest, source):
        super().__init__(manifest, source)
        self.stills = {}

    def source_image(self, at, *, still=False):
        if still and at in self.stills:
            return self.stills[at].copy()
        image = Image.fromarray(cv2.cvtColor(self.video.at(at), cv2.COLOR_BGR2RGB)).convert("RGBA")
        if still:
            self.stills[at] = image.copy()
        return image

    def words(self, image, entries, alpha=1.):
        if alpha <= 0:
            return image
        # Shadow follows the glyphs; it never creates a banner or opaque panel.
        glyphs = Image.new("L", image.size)
        draw = ImageDraw.Draw(glyphs)
        for xy, value, size, weight in entries:
            draw.text(xy, value, font=font(size, weight), fill=255, anchor="lt")
        shadow = glyphs.filter(ImageFilter.GaussianBlur(4))
        shadow = shadow.point(lambda v: round(v*.88*alpha))
        image = Image.alpha_composite(image, Image.merge("RGBA", (Image.new("L", image.size, 0),)*3 + (shadow,)))
        overlay = Image.new("RGBA", image.size)
        d = ImageDraw.Draw(overlay)
        for xy, value, size, weight in entries:
            d.text(xy, value, font=font(size, weight), fill=(*WHITE, round(255*alpha)),
                   stroke_width=1, stroke_fill=(12, 24, 29, round(58*alpha)), anchor="lt")
        return Image.alpha_composite(image, overlay)

    def highlight(self, image, hold_id, source_at, strength=1., *, previous=False, exclusion=None):
        if strength <= 0:
            return image
        polygon = self.polygon(hold_id, source_at)
        if polygon is None:
            return image
        points = [tuple(map(float, p)) for p in polygon]
        overlay = Image.new("RGBA", image.size)
        d = ImageDraw.Draw(overlay)
        d.polygon(points, fill=(*CYAN, round((13 if previous else 70)*strength)))
        d.line(points+[points[0]], fill=(*CYAN, round((65 if previous else 235)*strength)),
               width=1 if previous else 2, joint="curve")
        if exclusion:
            # Conservative reviewed occlusion; do not outline its artificial boundary.
            d.rectangle(exclusion, fill=(0,0,0,0))
        return Image.alpha_composite(image, overlay)

    def marker(self, image, limb, at, alpha):
        point = self.measured_point(limb, at)
        if point is None or alpha <= 0:
            return image
        x,y = map(float, point)
        overlay = Image.new("RGBA", image.size)
        d = ImageDraw.Draw(overlay)
        d.ellipse((x-6,y-6,x+6,y+6), outline=(*WHITE,round(210*alpha)), width=2)
        return Image.alpha_composite(image,overlay)

    def motion_image(self, t):
        at, frozen = source_state(self.manifest, t)
        image = self.source_image(at, still=frozen)
        if frozen:
            amount = .10 * min(ease((t-2)/.2), ease((3.8-t)/.2))
            image = Image.blend(image, Image.new("RGBA", image.size, (0,0,0,255)), amount)
        # Fade the entire target before contact so no fill is painted on a shoe/hand.
        foot_strength = ease(t/.25) * (1-ease((at-10.30)/.25))
        image = self.highlight(image, 6, at, foot_strength)
        if frozen:
            image = self.highlight(image, 6, at, .9, exclusion=(382,393,433,438))
        if at < 10.95:
            image = self.marker(image,"left_foot",at,ease((at-10.3)/.2))
        else:
            strength = ease((at-10.95)/.12)*(1-ease((at-11.25)/.07))
            image = self.highlight(image,9,at,strength)
            image = self.marker(image,"right_hand",at,ease((at-11.38)/.12))
        alpha = min(ease(t/.3), ease((7-t)/.35))
        image = self.words(image, [((392,651),"左脚先抬高，",28,400),
                                  ((392,691),"随后右手够向完攀点。",28,400)],alpha)
        tag = "定格" if frozen else "0.5× 慢放"
        return self.words(image,[((38,40),tag,20,400)],.8)

    def counts_image(self,t):
        counts = self.manifest["counts"]
        late, early = counts["late_frame"], counts["early_frame"]
        switch, fade = counts["switch_at"], counts["crossfade_seconds"]
        amount = ease((t-switch)/fade)
        frame = late if t < switch else early
        image = self.source_image(frame["source_at"],still=True)
        if switch <= t < switch+fade:
            image = Image.blend(self.source_image(late["source_at"],still=True),image,amount)
        if t < 7.3:
            image = Image.blend(self.source_image(self.manifest["motion"]["source_end"],still=True),
                                image,ease((t-7)/.3))
        image = Image.blend(image,Image.new("RGBA",image.size,(0,0,0,255)),.12)
        count, current = count_state(self.manifest,t)
        if current is not None:
            transition_alpha = 1.
            if switch-.18 < t < switch:
                transition_alpha = 1-ease((t-(switch-.18))/.18)
            elif switch <= t < switch+fade:
                transition_alpha = 0.
            for event in counts["events"]:
                if event["display_at"] > t or event["hold_id"] not in frame["visible_holds"]:
                    continue
                newest = event is current
                # Same event boundary drives both the visible point and integer count.
                strength = (.35+.65*ease((t-event["display_at"])/.16)) if newest else 1.
                image = self.highlight(image,event["hold_id"],frame["source_at"],strength*transition_alpha,
                                       previous=not newest)
            image = self.words(image,[((38,68),"左手",28,400),((114,63),str(count),34,500),
                                      ((150,68),"个不同岩点",28,400),
                                      ((38,112),"同一点只计一次",28,400)])
        return image

    def frames(self):
        try:
            for index in range(450):
                at = index/30
                image = self.motion_image(at) if at < 7 else self.counts_image(at)
                yield cv2.cvtColor(np.asarray(image.convert("RGB")),cv2.COLOR_RGB2BGR)
        finally:
            self.video.close()


def render(source,manifest,output,metrics):
    validate_manifest(manifest)
    cv2.setNumThreads(1)
    output=Path(output)
    partial=output.with_name(f".{output.name}.partial.webm")
    if output.exists() or partial.exists():
        raise ValueError("Use a new private temporary output")
    started=time.perf_counter()
    writer=cv2.VideoWriter(str(partial),cv2.VideoWriter_fourcc(*"VP80"),30,(720,880))
    if not writer.isOpened():
        raise RuntimeError("VP8 encoder is unavailable")
    count=0
    try:
        for frame in InPlaceComposition(manifest,source).frames():
            writer.write(frame);count+=1
    finally:
        writer.release()
    if count!=450:
        raise ValueError("Incomplete style preview")
    partial.replace(output)
    data={"visual_version":VERSION,"frame_count":count,"duration_seconds":15,
          "width":720,"height":880,"fps":30,"source_video_used":True,"model_calls":0,
          "elapsed_seconds":round(time.perf_counter()-started,3),"style_accepted_by_user":False,
          "font":"Noto Sans SC","font_weights":[400,500],"freeze_display_interval":[2,3.8],
          "freeze_source_seconds":10.7,"full_frame_source":True}
    Path(metrics).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("reference","manifest","output","metrics"):
        p.add_argument("--"+name,required=True,type=Path)
    args=p.parse_args()
    render(args.reference,json.loads(args.manifest.read_text(encoding="utf-8")),args.output,args.metrics)


if __name__=="__main__":
    main()
