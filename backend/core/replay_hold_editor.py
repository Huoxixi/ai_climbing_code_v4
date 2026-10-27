"""Private, frame-bound hold editing. Previews never mutate replay results."""
from __future__ import annotations

import base64
import copy
import math
import threading
import time
import uuid
from collections import OrderedDict

import cv2
import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.replay_hold_fusion import align_to_reference, polygon_bbox, transform_polygon, box_iou
from core.replay_resources import high_resource_slot


class EditorFrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    frame_index: int | None = Field(default=None, ge=0)


class EditorPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_token: str = Field(min_length=32, max_length=32)
    mode: str = Field(pattern="^(manual|model|candidate|region)$")
    polygon: list[list[float]] | None = Field(default=None, min_length=3, max_length=512)
    region_xyxy: list[float] | None = Field(default=None, min_length=4, max_length=4)
    hold_id: int | None = Field(default=None, gt=0)
    request_id: str | None = Field(default=None, min_length=32, max_length=32)
    candidate_index: int | None = Field(default=None, ge=0)
    context_ratio: float = Field(default=.25, ge=0, le=1, allow_inf_nan=False)


class EditorCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=32, max_length=32)


class EditorCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=32, max_length=32)


_cache_lock = threading.RLock()
_frames = OrderedDict()
_proposals = OrderedDict()
_operations = OrderedDict()
TTL = 600
MAX_FRAME_BYTES = 64 * 1024 * 1024


def _put(cache, value, limit):
    with _cache_lock:
        now = time.monotonic()
        for key in list(cache):
            if now - cache[key]["created"] > TTL:
                del cache[key]
        key = uuid.uuid4().hex
        cache[key] = {**value, "created": now}
        while len(cache) > limit or (cache is _frames and
                sum(len(item["png"]) for item in cache.values()) > MAX_FRAME_BYTES and len(cache) > 1):
            cache.popitem(last=False)
        return key


def _get(cache, key, store, job_id, owner):
    with _cache_lock:
        item = cache.get(key)
        if not item or item["store"] != str(store.jobs.resolve()) or item["job_id"] != job_id or item["owner"] != owner:
            raise HTTPException(409, "预览已失效，请重新读取画面并核对轮廓。")
        if time.monotonic() - item["created"] > TTL:
            del cache[key]
            raise HTTPException(409, "预览已过期，请重新读取画面。")
        return copy.deepcopy(item)


def editor_context(store, job_id, owner):
    from core.replay_contracts import hold_review_input, holds_revision
    job = store.get(job_id, owner, private=True)
    if job.get("status") not in {"awaiting_hold_review", "succeeded"} or (job.get("deletion") or {}).get("state") == "queued":
        raise HTTPException(409, "当前任务不能编辑岩点，请等待本地识别完成。")
    if job.get("segment_reviews"):
        raise HTTPException(409, "请先撤销动作段复核，再修改岩点。")
    if job_id in store._active_hold_renders:
        raise HTTPException(409, "岩点复盘正在更新，请稍后再试。")
    if (job.get("media") or {}).get("source_video", {}).get("status") != "available":
        raise HTTPException(409, "原视频已不可用，已有复盘仍可观看。")
    source = store._media_path(job_id, job, "source_video")
    if not source.is_file():
        raise HTTPException(409, "原视频文件不存在。")
    result = copy.deepcopy(hold_review_input(job))
    return job, result, source, holds_revision(result)


def _read_frame(path, *, index=None, seconds=None):
    cap = cv2.VideoCapture(str(path))
    try:
        if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
            cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        if index is not None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(422, "无法读取这帧画面，请选择附近一帧。")
        actual_index = max(0, round(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        actual_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        return frame, actual_index, actual_time
    finally:
        cap.release()


def validate_polygon(points, width, height):
    """Validate a single simple contour in original frame pixels, including concavity."""
    try:
        p = np.asarray(points, dtype=np.float64)
    except (TypeError, ValueError):
        raise HTTPException(422, "轮廓坐标无效，请重新描边。")
    if p.ndim != 2 or p.shape[1] != 2 or not 3 <= len(p) <= 512 or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise HTTPException(422, "轮廓须包含画面内的 3～512 个有效顶点。")
    if np.linalg.norm(p[0] - p[-1]) < 1e-9:
        p = p[:-1]
    if len(p) < 3 or len(np.unique(p, axis=0)) != len(p):
        raise HTTPException(422, "轮廓包含重复顶点，请修正后保存。")
    def cross(a, b, c):
        ab, ac = b - a, c - a
        return float(ab[0] * ac[1] - ab[1] * ac[0])
    def on(a, b, c):
        return abs(cross(a, b, c)) < 1e-12 and np.all(c >= np.minimum(a, b) - 1e-12) and np.all(c <= np.maximum(a, b) + 1e-12)
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        for j in range(i + 2, len(p)):
            if i == 0 and j == len(p) - 1:
                continue
            c, d = p[j], p[(j + 1) % len(p)]
            if (cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0) or any((on(a, b, c), on(a, b, d), on(c, d, a), on(c, d, b))):
                raise HTTPException(422, "轮廓边缘交叉，请移动顶点或重新描边。")
    pixels = (p * [width, height]).astype(np.float32)
    if abs(cv2.contourArea(pixels)) < 4 or min(np.ptp(pixels, axis=0)) < 2:
        raise HTTPException(422, "轮廓过小，请放大画面并沿岩点边缘描画。")
    return p.tolist()


def _binding(store, job, owner, revision):
    return {"store": str(store.jobs.resolve()), "job_id": job["id"], "owner": owner,
            "revision": revision, "checksum": job["media"]["source_video"].get("checksum_sha256"),
            "raw_checksum": (job.get("high_resolution_source") or {}).get("checksum_sha256")}


def cancel_editor_request(store, job_id, owner, request_id):
    job, _, _, revision = editor_context(store, job_id, owner)
    with _cache_lock:
        operation = _operations.get(request_id)
        if operation and (operation["store"] != str(store.jobs.resolve()) or operation["job_id"] != job_id or operation["owner"] != owner):
            raise HTTPException(404, "未找到本次局部识别。")
        if operation is None:
            operation = {**_binding(store, job, owner, revision), "event": threading.Event(), "created":time.monotonic()}
            _operations[request_id] = operation
        operation["event"].set()
        while len(_operations) > 128:
            _operations.popitem(last=False)
    return {"cancelled":True}


def _local_inference(store, job, owner, revision, request_id, image):
    from core.photo_route_analysis import _climbing_model_masks_batch
    request_id = request_id or uuid.uuid4().hex
    with _cache_lock:
        operation = _operations.get(request_id)
        if operation and (operation["store"] != str(store.jobs.resolve()) or operation["job_id"] != job["id"] or operation["owner"] != owner):
            raise HTTPException(409, "局部识别请求标识已失效，请重试。")
        if operation is None:
            operation = {**_binding(store, job, owner, revision), "event":threading.Event(), "created":time.monotonic()}
            _operations[request_id] = operation
        cancelled = operation["event"].is_set
    try:
        with high_resource_slot(cancelled=cancelled):
            # Input stays bounded by the existing model's 1200/2000 resize.
            # Reject new work when the host cannot safely load that model.
            from core.replay_resources import psutil
            if psutil is not None and psutil.virtual_memory().available < 2 * 1024 * 1024 * 1024:
                raise RuntimeError("当前可用内存不足，可先手绘轮廓，或关闭其他程序后再识别。")
            deadline = time.monotonic() + 90
            result = _climbing_model_masks_batch([image], deadline, cancelled, reuse_model=True, pack_masks=True)
            if time.monotonic() > deadline:
                raise TimeoutError("局部识别超过 90 秒")
        if cancelled():
            raise InterruptedError("Local editor inference cancelled")
        return result
    finally:
        with _cache_lock:
            _operations.pop(request_id, None)


def editor_frame(store, job_id, owner, request):
    job, result, source, revision = editor_context(store, job_id, owner)
    info = job["video"]
    count, fps = int(info["frame_count"]), float(info["fps"])
    index = request.frame_index if request.frame_index is not None else round(request.time_seconds * fps)
    if not 0 <= index < count:
        raise HTTPException(422, "画面超出视频片段，请重新选择。")
    # The prepared stream is CFR. Its decoded timestamp links into the untouched upload.
    frame, index, timestamp = _read_frame(source, index=index)
    timestamp = index / fps if not math.isfinite(timestamp) or (index > 0 and timestamp <= 0) else timestamp
    source_index, source_time = index, timestamp
    quality = "现有分析副本"
    high = job.get("high_resolution_source") or {}
    if high and high.get("storage_name"):
        path = source.parent / high["storage_name"]
        if path.name not in {"source" + suffix for suffix in (".mp4", ".m4v", ".mov", ".webm", ".3gp", ".3g2", ".mkv", ".video")}:
            raise HTTPException(422, "高清素材路径无效。")
        if path.is_file():
            raw, raw_index, raw_time = _read_frame(path, seconds=timestamp + float(high.get("trim_start_seconds") or 0))
            if abs(raw.shape[1] / raw.shape[0] - frame.shape[1] / frame.shape[0]) > .02:
                raise HTTPException(422, "高清帧方向与播放副本不一致，请使用参考帧核对。")
            offset = float(high.get("trim_start_seconds") or 0)
            if not math.isfinite(raw_time) or (raw_index > 0 and raw_time <= 0) or abs(raw_time - (timestamp + offset)) > .15:
                raise HTTPException(422, "高清帧时间无法准确对应，请选择附近画面。")
            frame, quality = raw, "保留的原始清晰度"
            source_index, source_time = raw_index, raw_time
            timestamp = raw_time - offset
    if frame.shape[0] * frame.shape[1] > 3840 * 2160:
        raise HTTPException(422, "单帧编辑暂支持最高 4K，请使用不超过 4K 的素材。")
    ref_index = int((result.get("hold_evidence") or {}).get("reference_frame") or 0)
    reference, _, _ = _read_frame(source, index=ref_index)
    if index == ref_index and abs(timestamp - index / fps) < .5 / fps:
        # At the same timestamp, the known normalize/resize chain supplies the
        # geometry; feature matching is unnecessary even on a low-texture wall.
        matrix = np.diag([reference.shape[1] / frame.shape[1], reference.shape[0] / frame.shape[0], 1.0])
    else:
        matrix, _ = align_to_reference(frame, reference)
    ok, png = cv2.imencode(".png", frame)
    if not ok:
        raise HTTPException(422, "画面编码失败，请换帧。")
    token = _put(_frames, {**_binding(store, job, owner, revision), "png": png.tobytes(),
        "frame_index": index, "time_seconds": timestamp, "matrix": matrix,
        "source_frame_index": source_index, "source_time_seconds": source_time,
        "width": frame.shape[1], "height": frame.shape[0],
        "reference_width": reference.shape[1], "reference_height": reference.shape[0]}, 8)
    contours = []
    candidates = []
    if matrix is not None:
        inverse = np.linalg.inv(matrix)
        for hold in result.get("holds") or []:
            if hold.get("polygon"):
                pixels = [[x * reference.shape[1], y * reference.shape[0]] for x, y in hold["polygon"]]
                contours.append({"id": hold["id"], "polygon": transform_polygon(pixels, inverse, frame.shape[1], frame.shape[0])})
        for candidate_index, hold in enumerate(result.get("hold_candidates") or []):
            if hold.get("polygon") and hold.get("contour_source") in {'climbing_model_native_mask','model_guided_mobilesam_mask'}:
                pixels = [[x * reference.shape[1], y * reference.shape[0]] for x, y in hold["polygon"]]
                mapped = transform_polygon(pixels, inverse, frame.shape[1], frame.shape[0])
                if all(0 <= x <= 1 and 0 <= y <= 1 for x, y in mapped):
                    candidates.append({"candidate_index":candidate_index, "polygon":mapped, "color_group":hold.get("color_group"), "score":hold.get("score")})
    return {"frame_token": token, "frame_index": index, "time_seconds": timestamp,
            "source_frame_index": source_index, "source_time_seconds": source_time,
            "frame_count": count, "fps": fps, "width": frame.shape[1], "height": frame.shape[0],
            "quality": quality, "aligned": matrix is not None, "holds_revision": revision,
            "image_data_url": "data:image/png;base64," + base64.b64encode(png).decode(), "holds": contours, "candidates":candidates}


def _check_binding(item, job, revision):
    if (item["revision"] != revision or item["checksum"] != job["media"]["source_video"].get("checksum_sha256")
            or item.get("raw_checksum") != (job.get("high_resolution_source") or {}).get("checksum_sha256")):
        raise HTTPException(409, "岩点或视频已更新，已保留编辑内容，请重新读取画面核对。")


def _make_proposal(store, job, owner, revision, frame, polygon, source, score=None, hold_id=None, metadata=None):
    polygon = validate_polygon(polygon, frame["width"], frame["height"])
    if frame["matrix"] is None:
        raise HTTPException(422, "这帧无法对齐墙面，编辑内容已保留；请回到参考帧或换一帧描画。")
    mapped = transform_polygon([[x * frame["width"], y * frame["height"]] for x, y in polygon],
                               frame["matrix"], frame["reference_width"], frame["reference_height"])
    # Reject out-of-wall contours, never silently clip a user's confirmed boundary.
    mapped = validate_polygon(mapped, frame["reference_width"], frame["reference_height"])
    value = {**_binding(store, job, owner, revision), "source_polygon": polygon,
             "reference_polygon": mapped, "bbox": polygon_bbox(mapped),
             "frame_index": frame["frame_index"], "time_seconds": frame["time_seconds"],
             "contour_source": source, "score": score, "hold_id": hold_id}
    value.update(metadata or {})
    value["geometry_evidence"] = {"source_size_wh": [frame["width"], frame["height"]],
        "reference_size_wh": [frame["reference_width"], frame["reference_height"]],
        "source_to_reference": np.asarray(frame["matrix"]).tolist(),
        "source_time_seconds": frame.get("source_time_seconds", frame["time_seconds"]),
        "source_frame_index":frame.get("source_frame_index", frame["frame_index"]),
        "prepared_time_seconds":frame["time_seconds"], "prepared_frame_index": frame["frame_index"],
        "orientation_auto":True, "mirrored":False}
    # Persist a small authoritative raster with its exact reference-space bounds.
    points = np.rint(np.asarray(mapped) * [frame["reference_width"], frame["reference_height"]]).astype(np.int32)
    x, y, w, h = cv2.boundingRect(points)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [points - [x, y]], 255)
    value["mask"] = {"encoding": "png-base64", "origin_xy": [x, y], "size_wh": [w, h],
        "reference_size_wh": [frame["reference_width"], frame["reference_height"]],
        "data": base64.b64encode(cv2.imencode(".png", mask)[1]).decode()}
    token = _put(_proposals, value, 64)
    return {key: copy.deepcopy(value[key]) for key in ("source_polygon", "reference_polygon", "bbox", "score", "contour_source", "hold_id")} | {"proposal_id": token}


def editor_preview(store, job_id, owner, request):
    job, result, _, revision = editor_context(store, job_id, owner)
    frame = _get(_frames, request.frame_token, store, job_id, owner)
    _check_binding(frame, job, revision)
    if request.hold_id is not None and not any(h["id"] == request.hold_id for h in result.get("holds") or []):
        raise HTTPException(409, "要修改的岩点已不存在，请刷新。")
    if request.mode == "manual":
        return {"candidates": [_make_proposal(store, job, owner, revision, frame, request.polygon,
                              "user_drawn_contour", hold_id=request.hold_id)]}
    if request.mode == 'region':
        from core.climb_replay import boxed_hold_polygon, existing_hold_mask
        polygon = validate_polygon(request.polygon, frame['width'], frame['height'])
        if frame['matrix'] is None:
            raise HTTPException(422, '这帧无法对齐墙面，请回参考帧识别。')
        image = cv2.imdecode(np.frombuffer(frame['png'],np.uint8),cv2.IMREAD_COLOR)
        w,h = frame['width'],frame['height']
        allowed = np.zeros((h,w),np.uint8)
        cv2.fillPoly(allowed,[np.rint(np.asarray(polygon)*[w,h]).astype(np.int32)],255)
        excluded = existing_hold_mask([hold for hold in result.get('holds') or [] if hold['id'] != request.hold_id],
            frame['matrix'],w,h,frame['reference_width'],frame['reference_height'])
        x,y,bw,bh = polygon_bbox(polygon)
        pixels = boxed_hold_polygon(image,[x,y,x+bw,y+bh],excluded,allowed)
        detected = [[px/w,py/h] for px,py in pixels]
        return {'candidates':[_make_proposal(store,job,owner,revision,frame,detected,
            'user_closed_region_local_colour',hold_id=request.hold_id)]}
    if request.mode == "candidate":
        candidates = result.get("hold_candidates") or []
        if request.candidate_index is None or request.candidate_index >= len(candidates):
            raise HTTPException(409, "候选已变化，请重新读取画面。")
        candidate = candidates[request.candidate_index]
        if candidate.get("contour_source") not in {'climbing_model_native_mask','model_guided_mobilesam_mask'} or not candidate.get("polygon") or frame["matrix"] is None:
            raise HTTPException(422, "这个候选不能直接补入，请选择清晰帧手绘。")
        inverse = np.linalg.inv(frame["matrix"])
        pixels = [[x * frame["reference_width"], y * frame["reference_height"]] for x, y in candidate["polygon"]]
        points = transform_polygon(pixels, inverse, frame["width"], frame["height"])
        return {"candidates":[_make_proposal(store, job, owner, revision, frame, points,
            candidate['contour_source'], candidate.get("score"), request.hold_id)]}
    values = request.region_xyxy
    if not values or not all(math.isfinite(v) and 0 <= v <= 1 for v in values) or values[2] <= values[0] or values[3] <= values[1]:
        raise HTTPException(422, "请框出局部识别范围。")
    w, h = frame["width"], frame["height"]
    x0, y0, x1, y1 = values
    if min((x1 - x0) * w, (y1 - y0) * h) < 4:
        raise HTTPException(422, "识别范围至少需要 4 个原帧像素，请稍微扩大范围。")
    dx, dy = (x1 - x0) * request.context_ratio, (y1 - y0) * request.context_ratio
    left, top = max(0, math.floor((x0 - dx) * w)), max(0, math.floor((y0 - dy) * h))
    right, bottom = min(w, math.ceil((x1 + dx) * w)), min(h, math.ceil((y1 + dy) * h))
    if (right - left) * (bottom - top) > 1920 * 1080:
        raise HTTPException(422, "局部范围过大，请放大后框住单个岩点及少量背景，或减少周围背景范围。")
    image = cv2.imdecode(np.frombuffer(frame["png"], np.uint8), cv2.IMREAD_COLOR)
    from core.climb_replay import native_mask_polygon
    outputs, model = _local_inference(store, job, owner, revision, request.request_id, image[top:bottom, left:right])
    candidates = []
    for mask, score in sorted(zip(*outputs[0]), key=lambda pair: -float(pair[1])):
        if mask.shape[1] != right - left:
            mask = np.unpackbits(mask, axis=1, count=right - left) * 255
        polygon = native_mask_polygon(mask, max_points=160)
        if len(polygon) < 3:
            continue
        points = [[(float(p[0][0]) + left) / w, (float(p[0][1]) + top) / h] for p in polygon]
        if box_iou(polygon_bbox(points), [x0, y0, x1 - x0, y1 - y0]) <= .01:
            continue
        try:
            item = _make_proposal(store, job, owner, revision, frame, points,
                "climbing_model_local_native_mask", score, request.hold_id,
                {"model_version":model, "crop_xyxy_pixels":[left, top, right, bottom]})
        except HTTPException as exc:
            if exc.status_code == 422:
                continue
            raise
        item["touches_crop"] = bool(np.any(mask[0]) or np.any(mask[-1]) or np.any(mask[:, 0]) or np.any(mask[:, -1]))
        candidates.append(item)
        if len(candidates) >= 12:
            break
    current, _, _, current_revision = editor_context(store, job_id, owner)
    _check_binding(frame, current, current_revision)
    return {"candidates": sorted(candidates, key=lambda item: -(item["score"] or 0))[:12], "model_version": model}


def editor_commit(store, job_id, owner, token):
    from core.climb_replay import utcnow
    proposal = _get(_proposals, token, store, job_id, owner)
    with store._lock:
        job, result, source, revision = editor_context(store, job_id, owner)
        _check_binding(proposal, job, revision)
        holds = result.get("holds") or []
        previous = next((h for h in holds if h["id"] == proposal["hold_id"]), None)
        if proposal["hold_id"] is not None and previous is None:
            raise HTTPException(409, "要修改的岩点已不存在。")
        if previous is None and any(box_iou(h["bbox"], proposal["bbox"]) > .7 for h in holds):
            raise HTTPException(409, "该位置已有岩点，请选择修改已有轮廓。")
        version = len(job.get("hold_review_history") or []) + 1
        hold = copy.deepcopy(previous or {})
        hold.update(id=previous["id"] if previous else max((h["id"] for h in holds), default=0) + 1,
            bbox=proposal["bbox"], polygon=proposal["reference_polygon"], mask=proposal.get("mask"),
            score=proposal["score"], user_confirmed=True, identity_source="user_confirmed_video_click",
            contour_source=proposal["contour_source"], source_frame=proposal["frame_index"],
            route_candidate=True, route_candidate_reason="user_confirmed", review_version=version)
        hold["contour_evidence"] = {"source_polygon": proposal["source_polygon"],
            **proposal.get("geometry_evidence", {}), "model_version": proposal.get("model_version"),
            "crop_xyxy_pixels": proposal.get("crop_xyxy_pixels")}
        result["holds"] = [hold if h["id"] == hold["id"] else h for h in holds] if previous else [*holds, hold]
        removed_candidates = [candidate for candidate in result.get("hold_candidates") or [] if box_iou(candidate["bbox"], hold["bbox"]) >= .7]
        result["hold_candidates"] = [candidate for candidate in result.get("hold_candidates") or [] if candidate not in removed_candidates]
        event = {"version": version, "operation": "edit_hold_contour" if previous else "add_hold_at_point",
                 "hold_id": hold["id"], "bbox": hold["bbox"], "time_seconds": proposal["time_seconds"],
                 "previous_hold": previous, "removed_candidates":removed_candidates,
                 "reviewed_at": utcnow(), "contour_source": proposal["contour_source"]}
        answer = store._save_hold_edits(job_id, job, result, source, event)
    with _cache_lock:
        _proposals.pop(token, None)
    return answer


def clear_editor_cache(store, job_id):
    with _cache_lock:
        for key in list(_operations):
            if _operations[key]["store"] == str(store.jobs.resolve()) and _operations[key]["job_id"] == job_id:
                _operations[key]["event"].set()
        for cache in (_frames, _proposals):
            for key in list(cache):
                if cache[key]["store"] == str(store.jobs.resolve()) and cache[key]["job_id"] == job_id:
                    del cache[key]
