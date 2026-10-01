"""Quicker captions, unilateral shading and source-time rhythm in real footage."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .replay_inplace_full_renderer import FullComposition, hold_elapsed, validate_manifest as validate_full
from .replay_inplace_renderer import ease, WHITE, CYAN
from .replay_playback import playback_duration, playback_state, validate_playback
from .replay_rhythm import rhythm_data

VERSION = "replay-inplace-rhythm-v1"
COLORS = {"hold": CYAN, "transition": (243,246,246), "unknown": (137,156,166)}


@lru_cache(maxsize=20)
def shade_mask(size, side, top, bottom, reach):
    """Darkest at the selected edge; the opposite edge remains untouched."""
    width,height = size
    x = np.arange(width,dtype=np.float32)
    edge_distance = x if side == "left" else width-1-x
    # Broad readable region, then a continuous feather rather than a panel edge.
    falloff = np.clip((reach-edge_distance)/(reach*.52),0,1)
    horizontal = falloff*falloff*(3-2*falloff)
    y = np.arange(height,dtype=np.float32)
    vertical = np.minimum(np.clip((y-(top-105))/105,0,1),np.clip(((bottom+105)-y)/105,0,1))
    vertical = vertical*vertical*(3-2*vertical)
    return Image.fromarray(np.uint8(255*.55*vertical[:,None]*horizontal[None,:]),"L")


def shade_side(image, side, top, bottom, alpha=1., reach=610):
    if alpha <= 0:
        return image
    mask = shade_mask(image.size,side,round(top),round(bottom),reach).point(lambda v:round(v*alpha))
    overlay = Image.new("RGBA",image.size,(3,10,13,0))
    overlay.putalpha(mask)
    return Image.alpha_composite(image,overlay)


def validate_manifest(manifest):
    if manifest.get("visual_version") != VERSION:
        raise ValueError("Unsupported rhythm rendering version")
    # Existing local sample checks still own evidence and shot ordering.
    compatible = {**manifest,"visual_version":"replay-inplace-full-v1","shots":[]}
    for shot in manifest["shots"]:
        validate_playback(shot)
        required = playback_duration(shot)
        if required > shot["duration_seconds"]+1e-6:
            raise ValueError("Tempo would truncate the selected source interval")
        proxy = {k:v for k,v in shot.items() if k not in {"playback_sections","freeze_at","freeze_duration"}}
        span = shot["source_end_seconds"]-shot["source_start_seconds"]
        proxy["playback_rate"] = span/required if span else 1.
        compatible["shots"].append(proxy)
    validate_full(compatible)
    rhythm_data(manifest["summary"])
    longest = manifest["summary"]["longest_hold"]
    matches = [phase for phase in manifest["summary"]["phases"]
               if phase.get("kind") == "hold" and phase.get("status") in {"reviewed", "confirmed"}
               and abs(phase["start_seconds"]-longest["start_seconds"]) < 1e-5
               and abs(phase["end_seconds"]-longest["end_seconds"]) < 1e-5
               and phase.get("contacts") == longest.get("contacts")]
    if not matches:
        raise ValueError("Longest confirmed hold must agree with the source-time rhythm phases")


class RhythmComposition(FullComposition):
    def __init__(self, manifest, source):
        super().__init__(manifest,source)
        self.rhythm = rhythm_data(self.summary)

    def backdrop(self,shot,local):
        at,frozen,_rate = playback_state(shot,local)
        # No global dimming: lighting treatment belongs only to the caption side.
        return self.source_image(at,still=frozen),at,frozen

    def caption(self,image,entries,local,*,duration=None,side="left",alpha=None,reach=610):
        strength = ease(local/.18) if alpha is None else alpha
        if duration is not None:
            strength *= ease((duration-local)/.16)
        top = min(e[0][1] for e in entries)
        bottom = max(e[0][1]+e[2] for e in entries)
        image = shade_side(image,side,top,bottom,strength,reach)
        # Small settling motion ends in 180ms; counts still arrive as one group.
        offset = 5*(1-ease(local/.18))
        entries = [((xy[0],xy[1]+offset),value,size,weight) for xy,value,size,weight in entries]
        return self.words(image,entries,strength)

    def hold_view(self,image,shot,local,at,frozen):
        phase = self.summary["longest_hold"]
        elapsed = hold_elapsed(phase,at)
        shown = min(phase["duration_seconds"],np.floor((elapsed+1e-8)*4)/4)
        entries = [((394,637),"最长已确认停留",26,400),
                   ((394,678),f"约 {shown:.1f} 秒 · 用点未变",26,400)]
        image = self.caption(image,entries,local,duration=shot["duration_seconds"],side="right",reach=440)
        alpha = ease(local/.18)*ease((shot["duration_seconds"]-local)/.16)
        overlay = Image.new("RGBA",image.size)
        d = ImageDraw.Draw(overlay)
        d.line((394,721,572,721),fill=(*WHITE,round(65*alpha)),width=2)
        if elapsed>0:
            d.line((394,721,394+178*elapsed/phase["duration_seconds"],721),fill=(*CYAN,round(210*alpha)),width=2)
        return Image.alpha_composite(image,overlay)

    def move_view(self,image,shot,local,at,frozen):
        foot = ease(local/.18)*(1-ease((at-10.3)/.25))
        image = self.highlight(image,6,at,foot)
        if frozen and abs(at-10.7)<1e-6:
            image = self.highlight(image,6,at,.9,exclusion=(382,393,433,438))
        if at<10.95:
            image = self.marker(image,"left_foot",at,ease((at-10.3)/.2))
        elif at<12:
            strength = ease((at-10.95)/.12)*(1-ease((at-11.25)/.07))
            image = self.highlight(image,9,at,strength)
            image = self.marker(image,"right_hand",at,ease((at-11.38)/.12)*(1-ease((at-11.8)/.2)))
        # Match caption changes to the real gesture, not a fixed slide duration.
        if at<11.85:
            lines = ("左脚先抬高，","随后右手够向完攀点。")
            alpha = ease(local/.18)*(1-ease((at-11.73)/.12))
        else:
            lines = ("继续换脚、抬高身体，","再将左手并到完攀点。")
            alpha = ease((at-11.85)/.12)
        alpha *= ease((shot["duration_seconds"]-local)/.16)
        return self.caption(image,[((392,651),lines[0],28,400),((392,691),lines[1],28,400)],
                            local,side="right",alpha=alpha,reach=450)

    def rhythm_view(self,image,local):
        data = self.rhythm
        total = data["elapsed_seconds"]
        rows = [("hold","保持用点"),("transition","换点移动"),("unknown","观测不清")]
        entries = [((38,535),f"攀爬节奏 · 用时约 {total:.1f} 秒",28,400)]
        for index,(kind,label) in enumerate(rows):
            percent = data["display_percentages"][kind]
            seconds = data["totals"][kind]
            entries.append(((59,633+index*39),f"{label}  {percent:.1f}% · 约 {seconds:.1f} 秒",24,400))
        image = self.caption(image,entries,local,side="left",reach=625)
        alpha = ease(local/.18)
        overlay = Image.new("RGBA",image.size)
        d = ImageDraw.Draw(overlay)
        x,y,width,height = 38,592,510,12
        reveal = ease(local/.85)
        source_reveal = data["start_seconds"]+total*reveal
        for phase in data["segments"]:
            start,end = phase["start_seconds"],min(phase["end_seconds"],source_reveal)
            if end<=start:
                continue
            a = x+width*(start-data["start_seconds"])/total
            b = x+width*(end-data["start_seconds"])/total
            d.rectangle((a,y,b,y+height),fill=(*COLORS[phase["kind"]],round(230*alpha)))
        for index,(kind,_label) in enumerate(rows):
            d.rectangle((38,644+index*39,46,652+index*39),fill=(*COLORS[kind],round(235*alpha)))
        image = Image.alpha_composite(image,overlay)
        return self.words(image,[((38,612),"离地",17,400),((478,612),"双手到点",17,400)],alpha*.85)

    def shot_image(self,shot,local):
        image,at,frozen = self.backdrop(shot,local)
        kind = shot["kind"]
        if kind=="counts":
            if self.baseline_last is not None and local<.2:
                image = Image.blend(self.baseline_last,image,ease(local/.2))
            return self.caption(image,self.count_entries(),local,duration=shot["duration_seconds"],side="left")
        if kind=="summary":
            return self.rhythm_view(image,local)
        image = self.hold_view(image,shot,local,at,frozen) if kind=="hold" else self.move_view(image,shot,local,at,frozen)
        _,_,rate = playback_state(shot,local)
        label = "定格" if frozen else f"{rate:g}× 慢放"
        # A small playback tag does not darken the opposite side of the frame.
        return self.words(image,[((38,40),label,20,400)],.8)

    def frames(self):
        try:
            shots = self.manifest["shots"]
            previous = None
            index = 0
            for frame in range(self.manifest["frame_count"]):
                at = frame/self.manifest["fps"]
                if index+1<len(shots) and at+1e-8>=shots[index+1]["start_seconds"]:
                    previous = self.shot_image(shots[index],shots[index]["duration_seconds"]-1/30)
                    index += 1
                shot = shots[index]
                local = at-shot["start_seconds"]
                image = self.shot_image(shot,local)
                fade = shot.get("transition_seconds",.18)
                if previous is not None and 0<fade and local<fade:
                    image = Image.blend(previous,image,ease(local/fade))
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
        for frame in RhythmComposition(manifest,source).frames():
            writer.write(frame)
            count += 1
    finally:
        writer.release()
    if count!=manifest["frame_count"]:
        raise ValueError("Incomplete rhythm ending")
    partial.replace(output)
    data = {"visual_version":VERSION,"frame_count":count,"duration_seconds":count/30,
            "width":720,"height":880,"fps":30,"source_video_used":True,"model_calls":0,
            "elapsed_seconds":round(time.perf_counter()-started,3),"style_accepted_by_user":False,
            "full_frame_source":True,"unilateral_caption_shading":True,"global_dimming":False,
            "caption_transition_seconds":.18,"rhythm":rhythm_data(manifest["summary"])}
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
