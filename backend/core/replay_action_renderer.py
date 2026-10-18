"""Full-frame source rendering; one source interval, no editorial freeze/transition."""
import argparse
import json
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .replay_actions import EDGES, VERSION, number
from .replay_action_naming import enrich_names, caption_entries, LIMB_NAMES
from .replay_template_renderer import TemplateComposition, _render, _shade, wrap_text
from .replay_inplace_renderer import font, ease
from . import replay_resources

PRESENTATION_VERSION = "selectable-scene-and-diagram-round-head-v11"
SUMMARY_INTRO, SUMMARY_STEP, SUMMARY_HOLD = .6, .8, 3.


def summary_metrics(metrics, motion=None):
    return [m for m in metrics if m.get('key') not in ('route_total','route_used','route_usage') and (not motion or m.get('key') not in ('moving','relative_still'))]


def route_metrics(metrics):
    return [m for m in metrics if m.get('key') in ('route_total','route_used','route_usage')]


def chapter_seconds(count):
    return SUMMARY_INTRO + (count - 1) * SUMMARY_STEP + SUMMARY_HOLD if count else 0


def route_seconds(metrics):
    return chapter_seconds(len(route_metrics(metrics)))


def rhythm_start(metrics, motion=None):
    count = len(summary_metrics(metrics, motion))
    return route_seconds(metrics) + chapter_seconds(count)


def summary_seconds(metrics, motion=None):
    return rhythm_start(metrics, motion) + (6 if motion else 0)


def active_event(groups, at):
    events = sorted([dict(e, group_index=i) for i, g in enumerate(groups) for e in g.get("events", [])
                     if e.get("evidence_status") == "locally_verified"], key=lambda e: e["start_seconds"])
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        end = min(event["end_seconds"] + .55, events[i + 1]["start_seconds"] if i + 1 < len(events) else float('inf'))
        if event["start_seconds"] <= at < end:
            return event
    return None


def make_plan(result, *, scope="full", group_id=None, segment_id=None, speed=.75, summary=False, base_video=None, annotations=False, analysis_right=False,
              show_skeleton=False, show_human=True, show_diagram=None, background=None):
    result = enrich_names(result)
    if speed not in (.5, .75, 1):
        raise ValueError("Unsupported playback speed")
    duration = result["source_duration_seconds"]
    group = next((g for g in result["groups"] if g["id"] == group_id), None) if scope == "group" else None
    if scope not in {"full", "group"} or scope == "group" and group is None and segment_id is None:
        raise ValueError("Unknown action group")
    start, end = (group["start_seconds"], group["end_seconds"]) if group else (0., duration)
    if segment_id is not None:
        segment = next((s for s in result.get('commentary_segments',[]) if s['id']==segment_id and s.get('group_id')==group_id),None)
        if scope!='group' or segment is None:
            raise ValueError('Unknown commentary segment')
        start,end = segment['start_seconds'],segment['end_seconds']
        if not all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) for t in (start,end)) or not 0<=start<end<=duration:
            raise ValueError('Invalid commentary segment time')
    media = base_video or result["video"]
    fps = media["fps"]
    if base_video and (abs(fps - result["video"]["fps"]) > .01 or media["frame_count"] < result["video"]["frame_count"]):
        raise ValueError("Base replay must preserve the source timeline")
    # Quantize source boundaries once. Slow playback duplicates native frames
    # exactly; full playback includes every source frame including the last.
    first = max(0, math.floor(start * fps + 1e-6))
    stop = min(result["video"]["frame_count"], math.ceil(end * fps - 1e-6))
    # Analysis and end statistics are page content, never encoded in new videos.
    rail, annotations, summary = 0, False, False
    composition = show_diagram is not None or show_skeleton or not show_human
    diagram = analysis_right if show_diagram is None else show_diagram
    panes = int(show_human or show_skeleton) + int(diagram)
    if not panes:
        raise ValueError('Choose at least one picture')
    if show_skeleton and not show_human and (not background or background.get('status') != 'ready'):
        raise ValueError('Empty background is unavailable')
    return {"version": VERSION, "presentation_version": PRESENTATION_VERSION,
            "width": media["width"] * panes + rail, "height": media["height"], "base_width": media["width"] * panes,
            "composition":composition, "show_skeleton":show_skeleton, "show_human":show_human, "show_diagram":diagram, "background":background,
            "analysis_right":diagram, "source_video":result['video'], 'attempt':result.get('attempt') or {}, 'torso_trajectory':result.get('torso_trajectory'), 'center_of_mass_trajectory':result.get('center_of_mass_trajectory'),
            'skeleton_only': bool(result.get('skeleton_only')), 'trajectory_start_seconds': result.get('trajectory_start_seconds'),
            "preserve_base": base_video is not None, "annotations": annotations, "groups": result["groups"],
            "has_human_revision": any(e.get('event_status') == 'human_confirmed' for g in result['groups'] for e in g.get('events', [])),
            "fps": fps, "source_duration_seconds": duration,
            "source_media_duration_seconds": media["frame_count"] / fps, "source_start_frame": first, "source_stop_frame": stop,
            "speed": speed, "summary_seconds": summary_seconds(result["metrics"], result.get('motion_summary')) if scope == "full" and summary else 0,
            "caption": group["description"] if group and group["evidence_status"] == "locally_verified" else "",
            "tracking_samples": result["pose_samples"], "holds": result.get("holds", []), "metrics": result["metrics"], "motion_summary": result.get('motion_summary'),
            "scope": scope, "group_id": group_id if group else None, "shots": []}


def validate(plan):
    if plan.get("version") != VERSION or plan.get("speed") not in (.5, .75, 1):
        raise ValueError("Unsupported action render")
    fps = plan.get("fps")
    first, stop = plan.get("source_start_frame"), plan.get("source_stop_frame")
    if not number(fps) or not 0 < fps <= 120 or not isinstance(first, int) or not isinstance(stop, int) or not 0 <= first < stop:
        raise ValueError("Invalid source frames")
    if stop > math.ceil(plan["source_duration_seconds"] * fps + 1e-6):
        raise ValueError("Source range outside video")
    media_duration = plan.get("source_media_duration_seconds", plan["source_duration_seconds"])
    if not number(media_duration) or media_duration <= 0 or media_duration + max(.1, 2 / fps) < plan["source_duration_seconds"]:
        raise ValueError("Invalid source media duration")
    if not plan.get("preserve_base") and abs(media_duration - plan["source_duration_seconds"]) > max(.1, 2 / fps):
        raise ValueError("Source media duration differs without a base replay")
    presentation = plan.get('presentation_version')
    expected_summary = 0 if presentation == PRESENTATION_VERSION else summary_seconds(plan["metrics"], plan.get('motion_summary')) if presentation in ('base-replay-fine-action-captions-v5', 'base-replay-route-usage-summary-v4.1', 'base-replay-route-usage-summary-v4', 'base-replay-rhythm-summary-orb-v3') else summary_seconds(plan['metrics']) if presentation == 'base-replay-side-caption-sequential-summary-v2' else 4
    if presentation == PRESENTATION_VERSION and (plan.get('annotations') or plan['width'] != plan.get('base_width')):
        raise ValueError('New action videos keep only the base replay; analysis belongs on the page')
    if plan["summary_seconds"] not in (0, expected_summary) or plan["scope"] == "group" and plan["summary_seconds"]:
        raise ValueError("A group export cannot carry full-video data")
    return math.ceil((stop - first) / plan["speed"]) + round(plan["summary_seconds"] * fps)


def metric_text(metric):
    value = metric.get('display_value')
    if not value:
        value = ('约 ' if metric.get('approximate') else '') + (f'{metric["value"]:.1f}' if metric.get('approximate') else str(metric['value']))
    return value + (' ' + metric['unit'] if metric.get('unit') else '')


def metric_lines(metrics):
    lines = []
    for m in metrics:
        lines.append(f'{m["label"]} {metric_text(m)}')
    return lines


class ActionComposition(TemplateComposition):
    def __init__(self, plan, source):
        super().__init__(plan, source)
        self.base_size = (round(self.size[0] * plan.get("base_width", plan["width"]) / plan["width"]), self.size[1])
        self.analysis = None
        self.background = None
        if plan.get('show_skeleton') and not plan.get('show_human'):
            self.background = cv2.imdecode(np.fromfile(plan['background']['path'], dtype=np.uint8), cv2.IMREAD_COLOR)
            if self.background is None:
                raise ValueError('Empty background is unavailable')
        if plan.get('analysis_right') or plan.get('composition'):
            from .replay_analysis_view import AnalysisView
            self.analysis = AnalysisView({'video':plan['source_video'],'pose_samples':self.samples,
                'skeleton_only': plan.get('skeleton_only'), 'trajectory_start_seconds': plan.get('trajectory_start_seconds'),
                'holds':plan['holds'],'attempt':plan.get('attempt') or {},'center_of_mass_trajectory':plan.get('center_of_mass_trajectory')})

    def raw(self, at):
        frame = self.video.at(at)
        if self.analysis:
            if self.plan.get('composition'):
                frame = self.analysis.compose(frame,round(at*self.plan['fps']),self.size,
                    show_skeleton=self.plan['show_skeleton'],show_human=self.plan['show_human'],show_diagram=self.plan['show_diagram'],
                    background=self.background,reference_to_background=(self.plan.get('background') or {}).get('reference_to_background'))
            else:
                frame = self.analysis.frame(frame,round(at*self.plan['fps']),self.size)
            return Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).convert('RGBA')
        frame = cv2.resize(frame, self.base_size, interpolation=cv2.INTER_AREA)
        image = Image.new("RGBA", self.size, (13, 20, 24, 255))
        image.paste(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), (0, 0))
        return image

    def overlay(self, image, at):
        if self.plan.get("preserve_base") or self.analysis:
            return image
        w, h = self.base_size
        candidates = [s for s in self.samples if abs(s.get("time_seconds", -9) - at) <= .3]
        if not candidates:
            return image
        sample = min(candidates, key=lambda s: abs(s["time_seconds"] - at))
        layer = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(layer)
        if sample.get("observed"):
            xy, scores = sample.get("kpts_xy", []), sample.get("kpts_score", [])
            if len(xy) == 17 and len(scores) == 17:
                for a, b in EDGES:
                    if min(scores[a], scores[b]) >= .5:
                        points = [(xy[i][0] * w, xy[i][1] * h) for i in (a, b)]
                        draw.line(points, fill=(255, 255, 255, 175), width=max(1, round(w / 600)))
        if sample.get("wall_alignment") in {"aligned", "reference"}:
            try:
                inverse = np.linalg.inv(np.asarray(sample["wall_reference_transform"], float))
                source_size = [self.plan["width"], self.plan["height"]]
                for hold in self.plan["holds"]:
                    points = np.asarray(hold.get("polygon", []), np.float32)
                    if points.ndim != 2 or len(points) < 3:
                        continue
                    projected = cv2.perspectiveTransform((points * source_size).astype(np.float32)[None], inverse)[0]
                    projected *= np.asarray(self.size) / source_size
                    if np.isfinite(projected).all():
                        draw.line([tuple(p) for p in projected] + [tuple(projected[0])],
                                  fill=(255, 255, 255, 140), width=max(1, round(w / 720)))
            except (ValueError, KeyError, np.linalg.LinAlgError):
                pass
        return Image.alpha_composite(image, layer)

    def commentary(self, image, at):
        entries = caption_entries(self.plan.get("groups", []), at)
        if not entries or not self.plan.get("annotations"):
            return image
        event = entries[0]
        w, h = self.size
        left = self.base_size[0]
        rail = w - left
        scale = w / self.plan["width"]
        x, y = left + rail * .12, h * (.23 if len(entries) > 1 else .36)
        alpha = ease((at - event["start_seconds"]) / .15)
        layer = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(layer)
        small = font(max(11, round(15 * scale)), 500)
        title = font(max(20, round(38 * scale)), 700)
        body = font(max(16, round(27 * scale)), 550)
        ordinary = [wrap_text(entry['text'], body, rail * .76) for entry in entries]
        needed = 42*scale + sum((70+34*len(lines))*scale for lines in ordinary) + 60*scale
        compact = needed > h*.82
        if compact:
            ordinary = [wrap_text(LIMB_NAMES[entry['limb']]+' · '+entry['text'], body, rail*.76) for entry in entries]
            needed = 42*scale + sum((20+34*len(lines))*scale for lines in ordinary) + 60*scale
        y = max(h*.08, min(y, h-needed-h*.08))
        white, cyan, muted = (247, 250, 251, round(255*alpha)), (124, 222, 229, round(255*alpha)), (180, 200, 205, round(255*alpha))
        draw.text((x, y), f"动作 {event['group_index'] + 1:02d} / {len(self.plan['groups']):02d}", font=small, fill=cyan)
        cursor = y + 42 * scale
        for entry, lines in zip(entries, ordinary):
            if not compact:
                draw.text((x, cursor), LIMB_NAMES[entry["limb"]], font=title, fill=white)
                cursor += 50 * scale
            for line in lines:
                draw.text((x, cursor), line, font=body, fill=white)
                cursor += 34 * scale
            cursor += 20 * scale
        draw.line((x, cursor, x+36*scale, cursor), fill=cyan, width=1)
        draw.text((x, cursor+16*scale), f"{min(e['start_seconds'] for e in entries):.1f}–{max(e['end_seconds'] for e in entries):.1f} 秒", font=small, fill=muted)
        if self.plan.get('has_human_revision'):
            for i,line in enumerate(wrap_text('人工修订 · 基础动作图保留原分析', small, rail*.76)):
                draw.text((x,h*.9+i*20*scale),line,font=small,fill=muted)
        return Image.alpha_composite(image, layer)

    def summary_frame(self, last, local):
        # The actual completed base movie remains underneath the data, including
        # its route map and action sequence. No synthetic wall or replacement.
        w, h = self.base_size
        dark = last.crop((0, 0, w, h)).filter(ImageFilter.GaussianBlur(max(4, w / 60)))
        dark = Image.alpha_composite(dark, Image.new("RGBA", (w,h), (3,9,12,166)))
        image = Image.new("RGBA", self.size, (13,20,24,255))
        image.paste(dark, (0,0))
        layer = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(layer)
        motion = self.plan.get('motion_summary')
        metrics = summary_metrics(self.plan["metrics"], motion)
        route_end = route_seconds(self.plan['metrics'])
        showing_route = local < route_end
        if showing_route:
            metrics = route_metrics(self.plan['metrics'])
        row_time = local if showing_route else local-route_end
        scale = w / 720
        title = font(max(16, round(38*scale)), 700)
        label = font(max(11, round(23*scale)), 450)
        value = font(max(14, round(31*scale)), 650)
        if motion and local >= rhythm_start(self.plan['metrics'], motion):
            return self.rhythm_frame(image, motion, local-rhythm_start(self.plan['metrics'], motion))
        step = min(h*.067, 54*scale)
        height = 92*scale + max(0,len(metrics)-1)*step
        top = (h-height)/2 - h*.03
        draw.text((w/2,top), "线路岩点使用" if showing_route else "本次攀爬", font=title, fill=(247,250,251,255), anchor="mt")
        draw.line((w/2-16*scale,top+61*scale,w/2+16*scale,top+61*scale), fill=(124,222,229), width=max(1,round(2*scale)))
        for i, metric in enumerate(metrics):
            alpha = ease((row_time - SUMMARY_INTRO - i*SUMMARY_STEP)/.45)
            if alpha <= 0:
                continue
            y = top+92*scale+i*step+8*scale*(1-alpha)
            displayed = metric_text(metric)
            draw.text((w*.12,y), metric['label'], font=label, fill=(214,228,232,round(255*alpha)), anchor="lt")
            draw.text((w*.88,y), displayed, font=value, fill=(247,250,251,round(255*alpha)), anchor="rt")
        if showing_route:
            draw.text((w/2,top+92*scale+len(metrics)*step+12*scale),'按当前分析统计 · 同一岩点只计一次',font=font(max(10,round(16*scale)),450),fill=(180,200,205),anchor='mt')
        shown = Image.alpha_composite(image,layer)
        return Image.blend(last,shown,ease(local/.5))

    def rhythm_frame(self, image, motion, local):
        w,h = self.base_size
        scale=w/720
        layer=Image.new('RGBA',self.size)
        draw=ImageDraw.Draw(layer)
        title=font(max(16,round(38*scale)),700)
        label=font(max(11,round(23*scale)),450)
        value=font(max(14,round(31*scale)),650)
        small=font(max(10,round(16*scale)),450)
        top=h*.28
        draw.text((w/2,top),'整体攀爬节奏',font=title,fill=(247,250,251),anchor='mt')
        draw.line((w/2-16*scale,top+61*scale,w/2+16*scale,top+61*scale),fill=(124,222,229),width=max(1,round(2*scale)))
        left,right=w*.12,w*.88
        y=top+93*scale
        draw.text((left,y),'0 秒',font=small,fill=(180,200,205),anchor='lt')
        draw.text((right,y),f"{motion['duration_seconds']:.1f} 秒",font=small,fill=(180,200,205),anchor='rt')
        colors={'moving':(124,222,229),'relative_still':(231,200,141),'unknown':(99,117,125)}
        y+=30*scale
        for segment in motion['segments']:
            x1=left+(right-left)*segment['start_seconds']/motion['duration_seconds']
            x2=left+(right-left)*segment['end_seconds']/motion['duration_seconds']
            draw.rectangle((x1,y,x2,y+18*scale),fill=colors[segment['kind']])
            if segment['kind']=='unknown':
                for x in range(round(x1),round(x2),max(3,round(6*scale))):
                    draw.line((x,y,x,y+18*scale),fill=(62,79,87),width=1)
        for index,row in enumerate(motion['totals']):
            alpha=ease((local-.6-index*.8)/.45)
            yy=y+53*scale+index*54*scale
            draw.ellipse((left,yy+10*scale,left+8*scale,yy+18*scale),fill=colors[row['kind']]+(round(255*alpha),))
            draw.text((left+20*scale,yy),row['label'],font=label,fill=(214,228,232,round(255*alpha)),anchor='lt')
            draw.text((right,yy),f"{row['percent']:.1f}%  约 {row['seconds']:.1f} 秒",font=value,fill=(247,250,251,round(255*alpha)),anchor='rt')
        draw.text((w/2,y+228*scale),'按原片观测估算 · 未观测区间不计作停留',font=small,fill=(180,200,205),anchor='mt')
        return Image.alpha_composite(image,layer)

    def text(self, image, lines, alpha=1):
        w, h = self.size
        face = font(max(16, round(w / 29)))
        lines = [part for line in lines for part in wrap_text(line, face, w * .78)]
        top, height = h * .1, len(lines) * face.size * 1.5
        shade = Image.new("RGBA", self.size, (0, 0, 0, 0))
        shade.putalpha(_shade(self.size, "left", top - 16, top + height + 16, w * .9).point(lambda x: round(x * alpha)))
        image = Image.alpha_composite(image, shade)
        layer = Image.new("RGBA", self.size)
        draw = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            draw.text((w * .05, top + i * face.size * 1.5), line, font=face,
                      fill=(255, 255, 255, round(255 * alpha)), anchor="lt")
        return Image.alpha_composite(image, layer)

    def frames(self):
        plan, last = self.plan, None
        previous, shown = None, None
        for output_index in range(math.ceil((plan['source_stop_frame']-plan['source_start_frame'])/plan['speed'])):
            index = min(plan['source_stop_frame']-1, plan['source_start_frame']+math.floor(output_index*plan['speed']))
            at = index / plan["fps"]
            if index != previous:
                last = self.overlay(self.raw(at), at)
                shown = self.commentary(last, at)
                previous = index
            yield shown
        for i in range(round(plan["summary_seconds"] * plan["fps"])):
            yield self.summary_frame(last, i / plan["fps"])


def render_actions(source_path, plan, output_path, *, cancelled=None, progress=None):
    frames = validate(plan)
    source, output = Path(source_path), Path(output_path)
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError("Use a new output")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="action-render-", dir=output.parent) as temporary:
        root = Path(temporary)
        manifest, staged, metrics = root / "plan.json", root / "video.mp4", root / "metrics.json"
        manifest.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        result = replay_resources.run_visual_worker(source, manifest, staged, metrics,
            worker_module="core.replay_action_renderer", cancelled=cancelled, progress=progress,
            timeout_seconds=min(3600, max(120, frames / plan["fps"] * 6)))
        if cancelled and cancelled():
            raise InterruptedError()
        staged.replace(output)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in ("reference", "manifest", "output", "metrics"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    _render(args.reference, json.loads(args.manifest.read_text(encoding="utf-8")), args.output, args.metrics,
            composition_factory=ActionComposition, validator=validate)
