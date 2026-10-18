"""Bounded local-frame action checks. No profile, coaching or knowledge calls."""
import json
import os
import base64
import math
import cv2
import numpy as np

from .replay_actions import apply_local_review, aligned, LIMBS
from .replay_action_naming import catalogue, hold_key
from .replay_action_trajectory import analyze_event, prepare_tracks, chain_pair_reasons
from .replay_coaching_engine import (DashScopeProvider, _usage_counts,
                                     DEFAULT_MODEL, DEFAULT_BASE_URL, MAX_OUTPUT_TOKENS, analysis_frame_count)
from .replay_coaching_cost import estimate_coaching_cost

SYSTEM = """你只整理攀爬视频中的可见肢体事件，不评价、不建议，不推测受力、心理或完成原因。
左右始终是攀爬者自身左右。必须沿肩肘腕或髋膝踝逐帧确认连续性，不能依据画面横坐标。
输入窗口已由轨迹定位，前中后图是事实依据。姿态标签和触点仅为候选；交叉、侧身、遮挡或突跳时核查图像。
返回 JSON events，按发生顺序最多八个事件。每个事件字段：limb(left_hand/right_hand/left_foot/right_foot),
action(move_up/move/adjust/reach/lift/contact/release/readjust/attempt/wall_contact), frame_ids(至少三帧，前中后)。
direction(up/down/left/right/null)、facts、techniques。不能确认则 events=[]。不要写自由解释或建议。
伸手或抬脚与成功接触分开。facts每项包含kind(source_contact/target_contact/release/readjust/attempt/wall_contact)、
hold_id(输入岩点的准确ID，墙面为null)、frame_ids(至少两帧)、state(satisfied/not_satisfied/unknown)。
岩点位置和已有接触是候选，不能作为已确认事实；没有可定位岩点参考时不返回岩点ID。
target_contact须覆盖首次接触及保留接触；release须覆盖接触结束前后；readjust须看清同点重新抓握或踩放；
attempt须看清触点后未保留接触。遮挡或仅肢体位移不得证明接触、离点、抓握、受力。
techniques只用提供词典的code，每项含frame_ids、conditions(每个必要条件的三态)、conflict、occluded。
未拍全或深度关系不清时必要条件为unknown，不猜旗式、沉膝、脚跟脚尖或腾空。密采样是原片真实帧，不是插帧。
复核阶段每个事件另外返回 verified, chain_continuous, conflict, occluded 布尔字段。
复核时还独立返回facts及其state、techniques的各必要条件，direction_state；基础事件确认不代表接触或技术确认。
观察静止的手与正在移动的脚时，不可将脚的位移写成手的位移。同一事件须覆盖移动前、移动中、落点后三帧，
不能为填满窗口而把连续三帧机械编成一次换点；调整位置不能虚构离开或接触新的岩点。
清楚可见时应纠正候选错误，不可用中性说法掩盖看清的动作。"""
SYSTEM += """
骨架候选已去除相机移动，并区分墙面末端位移与相对肩／髋的主动移位。
身体整体升降或平移不能让四肢都变成伸手、抬脚；手在墙面基本静止而肩部移动时不能写伸手。
输入trajectory_observations若有遮挡、左右链交换、长度突变或短时噪声，应在原片连续帧中单独核对，不能照抄。
17个二维点只支持躯干、肩肘腕和髋膝踝的可见运动，不支持手指抓握、脚底踩实、受力或空间深度。
"""


def bounded_events(answer):
    if not isinstance(answer, dict) or not isinstance(answer.get('events'), list):
        raise ValueError('Action response must contain an event list')
    events = []
    for original in answer['events'][:8]:
        event = dict(original) if isinstance(original, dict) else {}
        for key in ('limb', 'action', 'direction'):
            if not isinstance(event.get(key), str):
                event[key] = None
        ids = event.get('frame_ids')
        event['frame_ids'] = ids[:64] if isinstance(ids, list) and all(isinstance(k, str) for k in ids) else []
        for key in ('facts', 'techniques'):
            values = event.get(key)
            event[key] = [v for v in values[:16] if isinstance(v, dict)] if isinstance(values, list) else []
        events.append(event)
    return {**answer, 'events': events}


def action_windows(organized):
    for group in organized["groups"]:
        last = min(group["end_seconds"], (organized["video"]["frame_count"] - 1) / organized["video"]["fps"])
        cursor = group["start_seconds"]
        # Displacement alone is not speed: a slow long reach must not expand the
        # cloud request count as if it were a rapid movement.
        rapid = max((analyze_event(organized, limb, cursor, last).get('measurements', {}).get('relative_speed_p95_body_units_per_second', 0)
                     for limb in LIMBS), default=0) > 1.4
        while cursor < last:
            end = min(last, cursor + (.8 if rapid else 2.))
            yield group, {**group, "start_seconds": cursor, "end_seconds": end, "sampling_rate": 30 if rapid else 12}
            cursor = end


def sample_action_frames(source, job, window, cancelled, rate=12):
    """Bounded native source sampling. No interpolation, secrets or annotations."""
    capture = cv2.VideoCapture(str(source))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        total = analysis_frame_count(job, fps, capture.get(cv2.CAP_PROP_FRAME_COUNT), "source_video")
        first = max(0, math.ceil(window["start_seconds"] * fps - 1e-6))
        last = min(total - 1, math.floor(window["end_seconds"] * fps + 1e-6))
        if last <= first:
            return [], {}
        indices = sorted({first, last, *range(first, last + 1, max(1, math.ceil(fps / min(rate, fps))))})
        if len(indices) > 32:
            indices = [indices[round(i * (len(indices) - 1) / 31)] for i in range(32)]
        frames = []
        for index in indices:
            if cancelled():
                raise InterruptedError()
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, pixels = capture.read()
            if not ok or pixels is None or round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1 != index:
                continue
            ratio = min(1., 768 / max(pixels.shape[:2]))
            if ratio < 1:
                pixels = cv2.resize(pixels, (max(1, round(pixels.shape[1] * ratio)), max(1, round(pixels.shape[0] * ratio))))
            ok, jpg = cv2.imencode('.jpg', pixels, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                frames.append({"frame_id": f"frame-{index}", "frame_index": index, "time_seconds": round(index / fps, 6),
                               "data_url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode('ascii')})
        gap = max((b["time_seconds"] - a["time_seconds"] for a, b in zip(frames, frames[1:])), default=None)
        return frames, {"source_fps": fps, "requested_rate": rate, "frame_count": len(frames), "max_gap_seconds": gap,
                        "native_only": True, "dense_source_frames": gap is not None and gap <= .05 and len(frames) == len(indices)}
    finally:
        capture.release()


def hold_references(frame, organized, bounds=(0., 0., 1., 1.)):
    samples = [s for s in organized.get("pose_samples", []) if abs(s.get("time_seconds", -999) - frame["time_seconds"]) <= .3]
    if not samples:
        return []
    sample = min(samples, key=lambda s: abs(s["time_seconds"] - frame["time_seconds"]))
    if sample.get("wall_alignment") not in {"aligned", "reference"}:
        return []
    try:
        matrix = np.linalg.inv(np.asarray(sample["wall_reference_transform"], float))
        w, h = organized["video"]["width"], organized["video"]["height"]
        low, size = np.asarray(bounds[:2]), np.asarray(bounds[2:]) - np.asarray(bounds[:2])
        refs = []
        for hold in organized.get("holds", []):
            polygon = np.asarray(hold.get("polygon", []), float)
            if hold_key(hold.get("id")) is None or polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3:
                continue
            points = np.c_[polygon * [w, h], np.ones(len(polygon))] @ matrix.T
            points = (points[:, :2] / points[:, 2:] / [w, h] - low) / size
            if np.isfinite(points).all() and np.any((points[:, 0] >= 0) & (points[:, 0] <= 1) & (points[:, 1] >= 0) & (points[:, 1] <= 1)):
                refs.append({"hold_id": hold_key(hold["id"]), "polygon_in_image": points.round(4).tolist(), "status": "candidate"})
        return refs
    except (KeyError, ValueError, np.linalg.LinAlgError):
        return []


def registered_limb_points(frame, organized):
    samples = [s for s in organized.get('pose_samples', []) if abs(s.get('time_seconds', -999)-frame['time_seconds']) <= .3]
    if not samples:
        return {}
    sample = min(samples, key=lambda s: abs(s['time_seconds']-frame['time_seconds']))
    mapped = aligned(sample, organized['video'])
    tracks = prepare_tracks(organized)
    index = next((i for i, r in enumerate(tracks) if abs(r['time'] - sample['time_seconds']) < 1e-6), None)
    def continuous(limb):
        if index is None:
            return False
        neighbors = [(tracks[index - 1], tracks[index])] if index > 0 else []
        if index + 1 < len(tracks):
            neighbors.append((tracks[index], tracks[index + 1]))
        return not any(any(reason in {'trajectory_jump', 'side_identity_conflict', 'chain_length_change'} for reason in chain_pair_reasons(a, b, limb)) for a, b in neighbors)
    return {limb: mapped[0][chain[-1]].tolist() for limb, (_, chain) in LIMBS.items() if mapped is not None and all(mapped[1][i] for i in chain) and continuous(limb)}


def motion_candidates(organized, start, end):
    output = {}
    tracks = prepare_tracks(organized)
    for limb in LIMBS:
        detail = analyze_event(organized, limb, start, end, tracks)
        if detail['status'] == 'observed':
            output[limb] = detail['measurements']['relative_extent_body_units']
        elif detail['status'] in {'stationary', 'body_carried'}:
            output[limb] = 0.
    return output


def cropped_frames(source, frames, organized, window):
    # Enlarge the whole climber, keeping anatomical chains in frame. One fixed
    # union crop per window avoids decorative camera motion or left/right flips.
    samples = [s for s in organized["pose_samples"] if window["start_seconds"] - .3 <= s.get("time_seconds", -1) <= window["end_seconds"] + .3]
    points = [p for s in samples for p, score in zip(s.get("kpts_xy", []), s.get("kpts_score", []))
              if score >= .35 and len(p) == 2 and 0 < p[0] < 1 and 0 < p[1] < 1]
    if len(points) < 10:
        return [dict(f, hold_regions=hold_references(f, organized)) for f in frames]
    points = np.asarray(points)
    low, high = np.maximum(0, points.min(axis=0) - .12), np.minimum(1, points.max(axis=0) + .12)
    capture = cv2.VideoCapture(str(source))
    output = []
    try:
        for frame in frames:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame["frame_index"])
            ok, pixels = capture.read()
            if not ok:
                return frames
            h, w = pixels.shape[:2]
            x, y = (low * [w, h]).astype(int); right, bottom = (high * [w, h]).astype(int)
            crop = pixels[y:bottom, x:right]
            if not crop.size:
                return frames
            ratio = min(2., 768 / max(crop.shape[:2]))
            crop = cv2.resize(crop, (round(crop.shape[1] * ratio), round(crop.shape[0] * ratio)))
            ok, jpg = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            output.append(dict(frame, data_url='data:image/jpeg;base64,' + base64.b64encode(jpg).decode('ascii'),
                               hold_regions=hold_references(frame, organized, (*low, *high))))
    finally:
        capture.release()
    return output


def track_conflicts(proposed, checked, organized, frames):
    by_id = {f["frame_id"]: f["time_seconds"] for f in frames}
    events = proposed.get("events", [])
    tracks = prepare_tracks(organized)
    for event, review in zip(events, checked.get("events", [])):
        if not isinstance(event, dict) or not isinstance(review, dict):
            continue
        times = [by_id[key] for key in review.get("frame_ids", event.get("frame_ids", [])) if isinstance(key, str) and key in by_id]
        if len(times) < 3:
            continue
        limb = review.get('limb', event.get('limb'))
        detail = analyze_event(organized, limb, min(times), max(times), tracks)
        if review.get("action", event.get("action")) in {"move", "move_up", "reach", "lift"} and detail['status'] in {'stationary', 'body_carried', 'conflict'}:
            review.update(conflict=True, verified=False, trajectory_conflict=detail)
    return checked


def resolve_checked_events(proposed, checked, organized, frames):
    """A blind local correction plus continuous matching track can fix a side.

    Preserve the original proposal in raw_attempts. A model correction alone,
    or a coordinate-side heuristic, is never enough for this derived change.
    """
    output = json.loads(json.dumps(proposed))
    by_id = {f["frame_id"]: f["time_seconds"] for f in frames}
    for event, review in zip(output.get("events", []), checked.get("events", [])):
        if not isinstance(event, dict) or not isinstance(review, dict):
            continue
        if not (review.get("verified") is True and review.get("conflict") is False and
                review.get("chain_continuous") is True and review.get("occluded") is False):
            continue
        if event.get("limb") == review.get("limb") and {event.get("action"), review.get("action")} <= {"move", "move_up"}:
            # The generic movement description is the common supported fact.
            event["action"] = review["action"] = "move" if event["action"] != review["action"] else event["action"]
        if event.get("limb") == review.get("limb"):
            continue
        ids = review.get("frame_ids", [])
        times = [by_id[key] for key in ids if isinstance(key, str) and key in by_id]
        if len(times) < 3:
            continue
        displacements = motion_candidates(organized, min(times), max(times))
        if displacements.get(review.get("limb"), 0) >= .18:
            event.update(limb=review["limb"], action=review.get("action"), frame_ids=ids,
                         facts=[], techniques=[], direction=None,
                         correction_basis="blind_local_review_and_continuous_track")
    return output


class ActionEngine:
    def __init__(self, provider=None):
        self.model = os.getenv("REPLAY_COACHING_MODEL", DEFAULT_MODEL)
        # Historical reader/tests only. The current entry uses owner-scoped vision settings.
        self.provider = provider

    @property
    def configured(self):
        return self.provider is not None

    def run(self, source, job, organized, *, cancelled, usage_callback, budget_cny=.2):
        reviews, ledger = {}, []
        def call(stage, frames, payload):
            if cancelled():
                raise InterruptedError()
            text = json.dumps(payload, ensure_ascii=False)
            bound = len(text) + len(SYSTEM) + len(frames) * 1800 + 512
            reserved = estimate_coaching_cost({"stage_usage": [{"model": self.model,
                "usage": {"prompt_tokens": bound, "completion_tokens": MAX_OUTPUT_TOKENS}}]}).get("amount_max")
            spent = 0
            for entry in ledger:
                if not entry.get("usage_complete"):
                    raise ValueError("Unknown cloud usage; no further requests")
                cost = estimate_coaching_cost({"stage_usage": [entry]}).get("amount_max")
                if cost is None:
                    raise ValueError("Unknown price")
                spent += cost
            if reserved is None or spent + reserved > budget_cny or len(ledger) >= 48:
                raise ValueError("Action review budget reached")
            event = {"request_id": f"action-request-{len(ledger) + 1}", "stage": stage,
                     "model": self.model, "status": "started", "usage": {}, "usage_complete": False}
            ledger.append(event)
            usage_callback(event.copy())
            content = [{"type": "text", "text": text}]
            for frame in frames:
                content.extend([{"type": "text", "text": json.dumps({k: frame[k] for k in ("frame_id", "time_seconds", "hold_regions") if k in frame})},
                                {"type": "image_url", "image_url": {"url": frame["data_url"]}}])
            def metered(response):
                event.update(status="responded", usage=_usage_counts(response))
                event["usage_complete"] = all(k in event["usage"] for k in ("prompt_tokens", "completion_tokens"))
                usage_callback(event.copy())
            kwargs = {"stage": stage, "model": self.model, "cancelled": cancelled,
                      "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]}
            if isinstance(self.provider, DashScopeProvider):
                kwargs["response_callback"] = metered
            response = self.provider(**kwargs)
            if event["status"] == "started":
                metered(response)
            if cancelled():
                raise InterruptedError()
            return bounded_events(response.get("content"))

        for group, window in action_windows(organized):
            # Each group is passed separately: _local_frames' old two-candidate
            # ceiling cannot leave other displayed groups unchecked.
            frames, sampling = sample_action_frames(source, job, window, cancelled, window["sampling_rate"])
            if len(frames) < 3:
                continue
            frames = cropped_frames(source, frames, organized, window)
            candidates = [{"start": a["time_seconds"], "end": b["time_seconds"],
                           "displacements": motion_candidates(organized, a["time_seconds"], b["time_seconds"])}
                          for a, b in zip(frames[::2], frames[2::2])]
            context = {"window": window, "sampling": sampling, "technique_vocabulary": catalogue()["techniques"],
                       "trajectory_observations": [{"limb": limb, **{k: detail.get(k) for k in ('status', 'summary', 'coverage', 'reasons', 'measurements')}}
                           for limb in LIMBS for detail in [analyze_event(organized, limb, window['start_seconds'], window['end_seconds'])]]}
            proposed = call("action_observe", frames, {**context, "motion_candidates": candidates})
            # Independent naming: the checker is deliberately not told the
            # observer's side, limb or action. This prevents answer echoing.
            checks = [{"frame_ids": e.get("frame_ids", [])} for e in proposed.get("events", []) if isinstance(e, dict)]
            checked = call("action_verify", frames, {**context, "event_windows": checks,
                "instruction": "独立识别各事件窗口中的肢体及动作，按输入顺序逐项返回，不遗漏；不要将静止手误判成移动脚。"})
            raw_attempts = [{"proposed": proposed, "checked": json.loads(json.dumps(checked))}]
            checked = track_conflicts(proposed, checked, organized, frames)
            proposed = resolve_checked_events(proposed, checked, organized, frames)
            safe_frames = [{**{k: f[k] for k in ("frame_id", "time_seconds", "hold_regions") if k in f},
                            'wall_limb_points': registered_limb_points(f, organized)} for f in frames]
            # Dense motion claims additionally require actual source sampling.
            if not sampling.get("dense_source_frames"):
                for answer in (proposed, checked):
                    for event in answer.get("events", []):
                        for tag in event.get("techniques", []) if isinstance(event.get('techniques'), list) else []:
                            if isinstance(tag, dict) and tag.get("code") in {"DYNO", "DOUBLE_DYNO", "DYNAMIC_REACH"}:
                                if not isinstance(tag.get('conditions'), dict):
                                    tag['conditions'] = {}
                                tag['conditions']["dense_source_frames"] = "unknown"
            verified = apply_local_review(group, proposed, checked, safe_frames, organized.get("holds", []))
            # A corrected second pass must be observed and checked anew locally;
            # it cannot be silently substituted as a verified first-pass event.
            if verified.get("coverage_status") != "complete" and checked.get("events"):
                # Recheck the conflicting event's own pictures, not all pictures
                # in the group. Otherwise a real movement earlier in the group
                # can be spuriously attached to a later event's frame IDs.
                retried = 0
                for index, event in enumerate(proposed.get("events", [])):
                    check = checked["events"][index] if index < len(checked["events"]) else {}
                    one = apply_local_review(group, {"events": [event]}, {"events": [check]}, safe_frames, organized.get("holds", []))
                    if one.get("evidence_status") == "locally_verified" or retried >= 2:
                        continue
                    keys = event.get("frame_ids", [])
                    local = [f for f in frames if f["frame_id"] in keys]
                    if len(local) < 3:
                        continue
                    retried += 1
                    a, b = local[0]["time_seconds"], local[-1]["time_seconds"]
                    response = call("action_recheck", local, {"event_windows": [{"frame_ids": keys}],
                        "motion_candidates": motion_candidates(organized, a, b),
                        "instruction": "仅看这一次移动的前中后三帧，独立返回一个事件及全部复核字段；不要将窗口外的移动附到这里。"})
                    raw_attempts.append({"event_index": index, "proposed": {"events": [event]},
                                         "checked": json.loads(json.dumps(response))})
                    response = track_conflicts({"events": [event]}, response, organized, local)
                    corrected = resolve_checked_events({"events": [event]}, response, organized, local)
                    if response.get("events"):
                        proposed["events"][index] = corrected["events"][0]
                        while len(checked["events"]) <= index:
                            checked["events"].append({})
                        checked["events"][index] = response["events"][0]
            # Rechecks cannot bypass native sampling requirements either.
            if not sampling.get('dense_source_frames'):
                for answer in (proposed, checked):
                    for event in answer['events']:
                        for tag in event.get('techniques', []) if isinstance(event.get('techniques'), list) else []:
                            if isinstance(tag, dict) and tag.get('code') in {'DYNO', 'DOUBLE_DYNO', 'DYNAMIC_REACH'} and isinstance(tag.get('conditions'), dict):
                                tag['conditions']['dense_source_frames'] = 'unknown'
            existing = reviews.setdefault(group["id"], {"proposed": {"events": []}, "checked": {"events": []}, "frames": [], "raw_attempts": [], "sampling": []})
            existing["proposed"]["events"].extend(proposed.get("events", []))
            existing["checked"]["events"].extend(checked.get("events", []))
            existing["frames"] = list({f["frame_id"]: f for f in [*existing["frames"], *safe_frames]}.values())
            existing["raw_attempts"].extend(raw_attempts)
            existing["sampling"].append(sampling)
        return reviews
