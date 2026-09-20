"""Experimental, opt-in video replay analysis for climbing attempts.

This module is deliberately isolated from the photo-route recognition pipeline.
It owns a small file-backed job queue and sends the expensive segmentation and
pose work to VLM Run. Registration is controlled by
``ENABLE_CLIMB_REPLAY`` and is enabled by default for existing installations.

The model contract and contact heuristics are based on Jeremy Park's
Apache-2.0 ``vision-demos/rock_climbing`` reference implementation.  This first
slice returns reviewable structured evidence.  It does not make coaching,
difficulty, or injury-risk claims and it does not mutate a saved route.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import queue
import threading
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReplayConfigurationError(RuntimeError):
    """Raised when the opt-in service has no usable cloud configuration."""


class ReplayCancelled(RuntimeError):
    """Raised between analysis stages after a user asks to cancel."""


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 200 * 1024 * 1024
    max_duration_seconds: float = 90.0
    max_width: int = 1920
    max_height: int = 1080
    max_frames: int = 2700


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float
    size_bytes: int


def probe_video(path: Path) -> VideoInfo:
    """Read enough metadata to reject unsafe or unsupported uploads."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("无法读取视频，请上传标准 MP4 文件")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
        raise ValueError("视频缺少有效的尺寸、帧率或时长信息")
    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=frame_count / fps,
        size_bytes=path.stat().st_size,
    )


def validate_video(info: VideoInfo, limits: VideoLimits) -> None:
    if info.size_bytes > limits.max_bytes:
        raise ValueError(f"视频不能超过 {limits.max_bytes // (1024 * 1024)} MB")
    if info.duration_seconds > limits.max_duration_seconds + 0.05:
        raise ValueError(f"试用阶段仅支持 {limits.max_duration_seconds:g} 秒以内的视频")
    allowed_long = max(limits.max_width, limits.max_height)
    allowed_short = min(limits.max_width, limits.max_height)
    if max(info.width, info.height) > allowed_long or min(info.width, info.height) > allowed_short:
        raise ValueError(f"试用阶段最高支持 {limits.max_width}×{limits.max_height}（支持横竖屏）")
    if info.frame_count > limits.max_frames:
        raise ValueError(f"试用阶段最多处理 {limits.max_frames} 帧")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class ReplayAnalyzer(Protocol):
    def analyze(
        self,
        video: Path,
        *,
        route_color: str,
        video_info: VideoInfo,
        progress: Callable[[str, int], None],
        cancelled: Callable[[], bool],
    ) -> dict: ...


class ClimbReplayStore:
    """File-backed, owner-scoped jobs kept outside the photo-route database."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.jobs = self.root / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.recover_interrupted()

    def _path(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise HTTPException(404, "未找到复盘任务")
        return self.jobs / job_id / "job.json"

    def _read(self, job_id: str) -> dict:
        path = self._path(job_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, "未找到复盘任务")

    @staticmethod
    def _public(job: dict) -> dict:
        return {key: value for key, value in job.items() if key != "input_path"}

    def create(
        self,
        *,
        owner: str,
        route_id: str | None,
        route_color: str,
        source: Path,
        original_name: str,
        info: VideoInfo,
    ) -> dict:
        job_id, now = uuid.uuid4().hex, utcnow()
        directory = self.jobs / job_id
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / "input.mp4"
        os.replace(source, target)
        job = {
            "id": job_id,
            "owner": owner,
            "route_id": route_id,
            "route_color": route_color,
            "original_name": original_name,
            "input_path": str(target),
            "video": asdict(info),
            "status": "queued",
            "stage": "等待分析",
            "progress": 0,
            "error": None,
            "cancel_requested": False,
            "attempt": 1,
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        _atomic_json(self._path(job_id), job)
        return self._public(job)

    def get(self, job_id: str, owner: str | None = None, *, private=False) -> dict:
        with self._lock:
            job = self._read(job_id)
        if owner is not None and job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        return job if private else self._public(job)

    def list(self, owner: str) -> list[dict]:
        found = []
        for path in self.jobs.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if job.get("owner") == owner:
                found.append(self._public(job))
        return sorted(found, key=lambda item: item["created_at"], reverse=True)

    def update(self, job_id: str, **changes) -> dict:
        with self._lock:
            job = self._read(job_id)
            job.update(changes)
            job["updated_at"] = utcnow()
            _atomic_json(self._path(job_id), job)
        return job

    def queued(self) -> list[str]:
        jobs = []
        for path in self.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") == "queued":
                jobs.append(item)
        return [item["id"] for item in sorted(jobs, key=lambda item: item["created_at"])]

    def recover_interrupted(self) -> None:
        for path in self.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") == "running":
                item.update(
                    status="failed",
                    stage="服务重启后已停止",
                    error="服务在视频分析期间重启，请重试",
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                _atomic_json(path, item)

    def cancel(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return self._public(job)
        changes = {"cancel_requested": True, "stage": "正在取消"}
        if job["status"] == "queued":
            changes.update(status="cancelled", progress=job["progress"], finished_at=utcnow())
        return self._public(self.update(job_id, **changes))

    def retry(self, job_id: str, owner: str) -> dict:
        job = self.get(job_id, owner, private=True)
        if job["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "只有失败或已取消的任务可以重试")
        return self._public(self.update(
            job_id,
            status="queued",
            stage="等待重试",
            progress=0,
            error=None,
            cancel_requested=False,
            result=None,
            attempt=int(job.get("attempt") or 1) + 1,
            started_at=None,
            finished_at=None,
        ))


class ClimbReplayManager:
    """One-at-a-time worker so video analysis cannot overlap itself."""

    def __init__(self, store: ClimbReplayStore, analyzer: ReplayAnalyzer):
        self.store, self.analyzer = store, analyzer
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._queued: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="climb-replay-worker", daemon=True)
        self._thread.start()
        for job_id in store.queued():
            self.enqueue(job_id)

    def enqueue(self, job_id: str) -> None:
        if job_id not in self._queued:
            self._queued.add(job_id)
            self._queue.put(job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            self._queued.discard(job_id)
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        job = self.store.get(job_id, private=True)
        if job["status"] != "queued" or job.get("cancel_requested"):
            return
        self.store.update(job_id, status="running", stage="检查视频", progress=5,
                          started_at=utcnow(), error=None)

        def is_cancelled() -> bool:
            return bool(self.store.get(job_id, private=True).get("cancel_requested"))

        def progress(stage: str, value: int) -> None:
            if is_cancelled():
                raise ReplayCancelled()
            self.store.update(job_id, status="running", stage=stage,
                              progress=max(5, min(95, int(value))))

        try:
            info = VideoInfo(**job["video"])
            result = self.analyzer.analyze(
                Path(job["input_path"]), route_color=job["route_color"], video_info=info,
                progress=progress, cancelled=is_cancelled,
            )
            if is_cancelled():
                raise ReplayCancelled()
            self.store.update(job_id, status="succeeded", stage="分析完成", progress=100,
                              result=result, finished_at=utcnow())
        except ReplayCancelled:
            self.store.update(job_id, status="cancelled", stage="已取消",
                              error=None, finished_at=utcnow())
        except Exception as exc:  # the public job exposes a concise actionable error
            self.store.update(job_id, status="failed", stage="分析失败", progress=0,
                              error=str(exc)[:1000], finished_at=utcnow())

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=2)


COLOR_PROMPTS = {
    "红色": "red", "红": "red", "蓝色": "blue", "蓝": "blue",
    "绿色": "green", "绿": "green", "黄色": "yellow", "黄": "yellow",
    "橙色": "orange", "橙": "orange", "紫色": "purple", "紫": "purple",
    "粉色": "pink", "粉": "pink", "白色": "white", "白": "white",
    "黑色": "black", "黑": "black", "灰色": "gray", "灰": "gray",
}


class VlmRunReplayAnalyzer:
    """Small, testable VLM Run adapter for the phase-one evidence contract."""

    hold_model = "facebook/sam3.1"
    pose_model = "usyd-community/vitpose-plus-large"

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None):
        self.api_key = api_key or os.getenv("VLMRUN_API_KEY")
        self.base_url = base_url or os.getenv("VLMRUN_BASE_URL", "https://gateway.vlm.run/v1/openai")

    def _client(self):
        if not self.api_key:
            raise ReplayConfigurationError("尚未配置 VLMRUN_API_KEY，视频未发送到云端")
        from openai import OpenAI
        return OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=1800.0, max_retries=1)

    @staticmethod
    def _sample_frames(video: Path, count: int = 8) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(video))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        indices = np.linspace(total * 0.05, total * 0.95, num=min(count, total)).astype(int)
        frames = []
        try:
            for index in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
                ok, frame = cap.read()
                if ok:
                    frames.append(frame)
        finally:
            cap.release()
        return frames

    @staticmethod
    def _jpeg(frame: np.ndarray) -> str:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise RuntimeError("无法编码视频抽样帧")
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def _segment_frame(self, client, frame: np.ndarray, prompt: str) -> tuple[list[dict], dict | None]:
        response = client.chat.completions.create(
            model=self.hold_model,
            messages=[{"role": "user", "content": [{"type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{self._jpeg(frame)}"}}]}],
            response_format={"type": "json_object"},
            extra_body={"method": "segment", "method_params": {"prompt": prompt, "mask_format": "png"}},
        )
        payload = json.loads(response.choices[0].message.content)
        content = payload.get("content") or {}
        if content.get("object") not in {"img.segment.masks", "vid.segment.masks"}:
            raise RuntimeError("岩点分割服务返回了无法识别的结果")
        items = [item for item in content.get("items") or []
                 if float(item.get("score") or 0) >= 0.4 and len(item.get("bbox_xywh") or []) == 4]
        usage = response.usage.model_dump() if response.usage else None
        return items, usage

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax, ay, aw, ah = a; bx, by, bw, bh = b
        x0, y0 = max(ax, bx), max(ay, by)
        x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        union = aw * ah + bw * bh - overlap
        return overlap / union if union > 1e-9 else 0.0

    @classmethod
    def _consensus_holds(cls, detections: list[list[dict]]) -> list[dict]:
        clusters: list[dict] = []
        for frame_index, items in enumerate(detections):
            for item in items:
                box = [float(value) for value in item["bbox_xywh"]]
                match = None
                best = 0.30
                for cluster in clusters:
                    score = cls._iou(box, np.mean(cluster["boxes"], axis=0).tolist())
                    if score > best:
                        match, best = cluster, score
                if match is None:
                    match = {"boxes": [], "scores": [], "frames": set()}
                    clusters.append(match)
                match["boxes"].append(box)
                match["scores"].append(float(item.get("score") or 0))
                match["frames"].add(frame_index)
        minimum = max(1, math.ceil(max(1, len(detections)) * 0.25))
        holds = []
        for cluster in clusters:
            if len(cluster["frames"]) < minimum:
                continue
            box = np.median(np.asarray(cluster["boxes"], dtype=float), axis=0).tolist()
            holds.append({"bbox": [round(float(v), 6) for v in box],
                          "score": round(float(np.mean(cluster["scores"])), 4),
                          "appearances": len(cluster["frames"])})
        holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2),
                                     hold["bbox"][0] + hold["bbox"][2] / 2))
        for index, hold in enumerate(holds, start=1):
            hold["id"] = index
        return holds

    @staticmethod
    def _choose_track(items: list[dict]) -> tuple[Any, list[dict]]:
        by_track: dict[Any, list[dict]] = defaultdict(list)
        for item in items:
            by_track[item.get("track_id")].append(item)
        if not by_track:
            raise RuntimeError("视频中没有识别到攀爬者")
        track = max(by_track, key=lambda key: (len(by_track[key]),
            np.mean([record.get("bbox_xywh", [0, 0, 0, 0])[2] *
                     record.get("bbox_xywh", [0, 0, 0, 0])[3] for record in by_track[key]])))
        return track, by_track[track]

    @staticmethod
    def _inside(point: tuple[float, float], hold: dict, margin: float) -> bool:
        x, y = point; bx, by, bw, bh = hold["bbox"]
        return bx - margin <= x <= bx + bw + margin and by - margin <= y <= by + bh + margin

    @classmethod
    def _contacts(cls, records: list[dict], holds: list[dict], fps: float) -> dict:
        limbs = {"left_hand": 9, "right_hand": 10, "left_foot": 15, "right_foot": 16}
        dwell = max(1, round(0.4 * fps))
        records = sorted(records, key=lambda item: int(item.get("frame_id", -1)))
        current = {key: None for key in limbs}
        since = {key: 0 for key in limbs}
        run = {key: 0 for key in limbs}
        confirmed = {key: False for key in limbs}
        contacts: list[dict] = []
        holding: dict[int, dict[str, int]] = {}
        midline = []

        def close(key: str, frame: int) -> None:
            if current[key] is not None and confirmed[key]:
                contacts.append({"limb": key, "hold_id": current[key], "start_frame": since[key],
                                 "end_frame": max(since[key], frame - 1)})
            current[key], run[key], confirmed[key] = None, 0, False

        for item in records:
            frame = int(item.get("frame_id", -1))
            points = item.get("kpts_xy") or []
            scores = item.get("kpts_score") or []
            torso = [points[i] for i in (5, 6, 11, 12) if i < len(points) and points[i] != [0, 0]]
            if torso:
                midline.append({"frame": frame, "x": round(float(np.mean([p[0] for p in torso])), 5),
                                "y": round(float(np.mean([p[1] for p in torso])), 5)})
            active = {}
            for key, index in limbs.items():
                if index >= len(points) or points[index] == [0, 0] or (
                    index < len(scores) and scores[index] is not None and float(scores[index]) < 0.15
                ):
                    close(key, frame); continue
                x, y = map(float, points[index])
                if "foot" in key:
                    y += 0.02
                choices = [hold for hold in holds if cls._inside((x, y), hold, 0.02)]
                chosen = min(choices, key=lambda hold: abs(x - hold["bbox"][0] - hold["bbox"][2] / 2)
                             + abs(y - hold["bbox"][1] - hold["bbox"][3] / 2)) if choices else None
                hold_id = chosen["id"] if chosen else None
                if hold_id != current[key]:
                    close(key, frame)
                    current[key], since[key] = hold_id, frame
                if hold_id is not None:
                    run[key] += 1
                    confirmed[key] = confirmed[key] or run[key] >= dwell
                    if confirmed[key]:
                        active[key] = hold_id
            holding[frame] = active
        last_frame = int(records[-1].get("frame_id", 0)) + 1 if records else 0
        for key in limbs:
            close(key, last_frame)

        first_use: dict[int, int] = {}
        for contact in contacts:
            first_use[contact["hold_id"]] = min(first_use.get(contact["hold_id"], 10**9), contact["start_frame"])
        sequence = [hold for hold, _ in sorted(first_use.items(), key=lambda pair: pair[1])]
        start = next((frame for frame, active in sorted(holding.items())
                      if any(k.endswith("hand") for k in active) and any(k.endswith("foot") for k in active)), None)
        top = holds[-1]["id"] if holds else None
        completion = next((frame for frame, active in sorted(holding.items())
                           if active.get("left_hand") == top and active.get("right_hand") == top), None)
        end = completion if completion is not None else (max(holding) if holding else None)
        window_frames = max(1, (end - start + 1)) if start is not None and end is not None else 1
        per_limb = {}
        for key in limbs:
            relevant = [c for c in contacts if c["limb"] == key]
            clip_start = start if start is not None else 0
            clip_end = end if end is not None else max(0, last_frame - 1)
            count = sum(max(0, min(c["end_frame"], clip_end) -
                            max(c["start_frame"], clip_start) + 1) for c in relevant)
            per_limb[key] = {"contact_seconds": round(count / fps, 3),
                             "coverage_of_attempt": round(count / window_frames, 4),
                             "holds": list(dict.fromkeys(c["hold_id"] for c in relevant))}
        return {
            "start_frame": start,
            "completion_frame": completion,
            "topped_out": completion is not None,
            "elapsed_seconds": round((completion - start) / fps, 3)
                if start is not None and completion is not None else None,
            "sequence": sequence,
            "contacts": contacts,
            "per_limb": per_limb,
            "midline": midline,
        }

    def analyze(self, video: Path, *, route_color: str, video_info: VideoInfo,
                progress: Callable[[str, int], None], cancelled: Callable[[], bool]) -> dict:
        client = self._client()
        prompt_color = COLOR_PROMPTS.get(route_color.strip(), route_color.strip())
        prompt = f"{prompt_color} climbing hold"
        progress("抽取岩点画面", 12)
        frames = self._sample_frames(video)
        if not frames:
            raise RuntimeError("没有从视频中读取到有效画面")
        progress("识别线路岩点", 20)
        with ThreadPoolExecutor(max_workers=min(4, len(frames))) as pool:
            segmented = list(pool.map(lambda frame: self._segment_frame(client, frame, prompt), frames))
        if cancelled():
            raise ReplayCancelled()
        holds = self._consensus_holds([items for items, _ in segmented])
        if not holds:
            raise RuntimeError(f"没有稳定识别到“{route_color}”线路岩点，请检查颜色和机位")
        progress("识别攀爬者姿态", 55)
        video_b64 = base64.b64encode(video.read_bytes()).decode("ascii")
        response = client.chat.completions.create(
            model=self.pose_model,
            messages=[{"role": "user", "content": [{"type": "video_url",
                "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}}]}],
            response_format={"type": "json_object"},
            extra_body={"method": "pose", "video_fps": video_info.fps,
                        "video_max_frames": video_info.frame_count, "precision": 4},
        )
        del video_b64
        payload = json.loads(response.choices[0].message.content)
        content = payload.get("content") or {}
        if content.get("object") != "vid.pose.kpts":
            raise RuntimeError("姿态服务返回了无法识别的结果")
        track_id, records = self._choose_track(content.get("items") or [])
        progress("计算手脚与岩点接触", 82)
        attempt = self._contacts(records, holds, video_info.fps)
        progress("整理复盘报告", 94)
        usages = [usage for _, usage in segmented if usage]
        if response.usage:
            usages.append(response.usage.model_dump())
        return {
            "schema_version": 1,
            "status": "prototype_needs_review",
            "route": {"color": route_color, "prompt": prompt},
            "models": {"holds": self.hold_model, "pose": self.pose_model},
            "video": asdict(video_info),
            "track_id": track_id,
            "frames_with_pose": len(records),
            "holds": holds,
            "attempt": attempt,
            "usage": usages,
            "warnings": [
                "当前为技术验证结果，手脚接触需要用户复核。",
                "本阶段使用岩点外接框计算接触，下一阶段将接入像素级掩膜。",
                "开始时间根据首个手脚同时稳定接触估算，尚未使用地面分割。",
            ],
        }


def create_climb_replay_router(
    store: ClimbReplayStore,
    manager: ClimbReplayManager,
    *,
    route_lookup: Callable[[str, str], dict] | None = None,
    limits: VideoLimits | None = None,
) -> APIRouter:
    limits = limits or VideoLimits()
    router = APIRouter(prefix="/api/climb-replay", tags=["climb-replay"])

    def owner(request: Request) -> str:
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    @router.post("/jobs", status_code=202)
    async def create_job(
        request: Request,
        video: UploadFile = File(...),
        route_id: str = Form(default=""),
        route_color: str = Form(default=""),
    ):
        username = owner(request)
        route_id = route_id.strip()
        if route_id:
            if route_lookup is None:
                raise HTTPException(503, "线路库尚未连接到复盘服务")
            route = route_lookup(route_id, username)
            route_color = str(route.get("color_group") or route_color).strip()
        route_color = route_color.strip()
        if not route_color or len(route_color) > 40:
            raise HTTPException(422, "请选择需要分析的线路颜色")
        if (video.content_type or "").lower() != "video/mp4":
            raise HTTPException(422, "技术验证阶段仅支持 MP4 视频")

        upload = store.root / f".upload-{uuid.uuid4().hex}.tmp"
        size, digest = 0, hashlib.sha256()
        try:
            with upload.open("wb") as target:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > limits.max_bytes:
                        raise HTTPException(413, f"视频不能超过 {limits.max_bytes // (1024 * 1024)} MB")
                    digest.update(chunk)
                    target.write(chunk)
            if not size:
                raise HTTPException(422, "视频内容为空")
            try:
                info = probe_video(upload)
                validate_video(info, limits)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            job = store.create(owner=username, route_id=route_id or None, route_color=route_color,
                               source=upload, original_name=video.filename or f"{digest.hexdigest()}.mp4",
                               info=info)
            manager.enqueue(job["id"])
            return job
        finally:
            upload.unlink(missing_ok=True)

    @router.get("/jobs")
    def list_jobs(request: Request):
        return store.list(owner(request))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        return store.get(job_id, owner(request))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request):
        return store.cancel(job_id, owner(request))

    @router.post("/jobs/{job_id}/retry")
    def retry_job(job_id: str, request: Request):
        result = store.retry(job_id, owner(request))
        manager.enqueue(job_id)
        return result

    return router
