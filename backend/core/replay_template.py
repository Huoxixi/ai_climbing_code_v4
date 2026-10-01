"""Owner-scoped template movies made from an existing report and source video.

Cloud work belongs exclusively to CoachingManager. This manager reuses that
report, plans locally, and commits a separate movie without replacing baseline.
"""
from __future__ import annotations

import copy
import hashlib
import json
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

from core.replay_coaching import CoachingCreate

TEMPLATE_VERSION = "replay-template-v1"
ACTIVE = {"queued", "waiting_report", "running"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _plan(job, report):
    from core.replay_template_plan import build_template_plan
    return build_template_plan(job, report)


def _render(source, plan, output, *, cancelled, progress):
    from core.replay_template_renderer import render_template_video
    return render_template_video(source, plan, output, cancelled=cancelled, progress=progress)


def plan_overview(plan):
    if not isinstance(plan, dict):
        return None
    shots = plan.get("shots") or []
    chapters = [{"kind": str(shot.get("kind") or "")[:32],
                 "title": str(shot.get("title") or shot.get("caption") or "")[:120],
                 "duration_seconds": shot.get("duration_seconds")}
                for shot in shots if isinstance(shot, dict)]
    duration = plan.get("duration_seconds")
    if duration is None:
        duration = sum(float(chapter.get("duration_seconds") or 0) for chapter in chapters)
    return {"duration_seconds": duration, "chapter_count": len(chapters), "chapters": chapters,
            "omitted_metrics": [{"metric": str(item.get("metric") or "")[:80],
                                 "reason": str(item.get("reason") or "")[:200]}
                                for item in plan.get("omitted_metrics") or [] if isinstance(item, dict)]}


class TemplateCancelled(Exception):
    pass


class TemplateVideoManager:
    def __init__(self, store, coaching_manager, *, planner=None, renderer=None):
        self.store, self.coaching = store, coaching_manager
        self.planner, self.renderer = planner or _plan, renderer or _render
        self._queue = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._thread = None
        self._running = set()
        self._condition = threading.Condition()
        self.store.template_manager = self
        # A restart never restarts paid analysis or silently resumes rendering.
        with self.store._lock:
            for path in self.store.jobs.glob("*/job.json"):
                try:
                    job = self.store._read(path.parent.name)
                    record = job.get("template_video") or {}
                    if record.get("status") in ACTIVE:
                        record.update(status="failed", error="服务重启，模板视频制作已停止，请重新制作。",
                                      message="原有视频仍保留", finished_at=_now())
                        self.store.update(job["id"], template_video=record)
                except (OSError, ValueError, HTTPException):
                    continue

    def _available(self, job):
        self.coaching._available(job)
        if job["id"] in getattr(self.store, "_active_hold_renders", set()):
            raise HTTPException(409, "岩点复盘正在更新，请稍后制作模板视频。")
        try:
            path, media = self.store.media_file(job["id"], job["owner"], "source_video")
        except (HTTPException, OSError):
            raise HTTPException(409, "模板视频需要仍可读取的原视频；不会使用照片或增强成片代替。") from None
        if not path.is_file() or not path.stat().st_size:
            raise HTTPException(409, "原视频已不可用，无法制作模板视频。")
        return path, media

    def _fingerprint(self, job):
        source, media = self._available(job)
        stat = source.stat()
        result = {key: value for key, value in (job.get("result") or {}).items()
                  if key not in {"visual_replay", "visual_reference", "overlay", "visual_review_inputs"}}
        return _digest({"attempt": job.get("attempt"), "video": job.get("video"), "result": result,
                        "route_id": job.get("route_id"), "route_version_id": job.get("route_version_id"),
                        "segment_reviews": job.get("segment_reviews") or {},
                        "source": {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                   "checksum_sha256": media.get("checksum_sha256")}})

    def _reason(self, job, record):
        if not record:
            return None
        if record.get("invalidated"):
            return record.get("stale_reason") or "依据已更新，请重新制作模板视频。"
        if record.get("template_version") != TEMPLATE_VERSION:
            return "模板已更新，请重新制作。"
        if record.get("analysis_version") != self._analysis_version():
            return "分析方法已更新，请重新制作模板视频。"
        if record.get("knowledge_fingerprint") != self.coaching._knowledge_version():
            return "知识依据已更新或撤回，请重新制作模板视频。"
        coaching = job.get("coaching") or {}
        if (coaching.get("consent") or {}).get("event") == "withdrawn":
            return "本次云端分析授权已撤回。"
        try:
            if record.get("evidence_fingerprint") != self._fingerprint(job):
                return "原视频或动作证据已更新，请重新制作。"
        except (HTTPException, OSError, ValueError):
            return "原视频或授权已不可用，模板视频已失效。"
        return None

    def _analysis_version(self):
        from core.replay_coaching import GENERATION_VERSION, PIPELINE_VERSION
        from core.replay_coaching_engine import ANALYSIS_VERSION
        return _digest({"generation": GENERATION_VERSION, "pipeline": PIPELINE_VERSION,
                        "analysis": ANALYSIS_VERSION, "model": self.coaching.engine.model})

    def _path(self, job_id, item):
        name = item.get("storage_name") or ""
        if not re.fullmatch(r"template-[a-f0-9]{32}\.mp4", name):
            raise HTTPException(404, "模板视频不存在")
        directory = self.store._path(job_id).parent.resolve()
        path = (directory / name).resolve()
        if path.parent != directory:
            raise HTTPException(404, "模板视频不存在")
        return path

    def get(self, job_id, owner):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("template_video") or {}
            media = record.get("media") or {}
            reason = self._reason(job, record)
            media_reason = self._reason(job, media) if media else None
            ready = False
            if media and not media_reason:
                try:
                    ready = self._path(job_id, media).is_file()
                except HTTPException:
                    pass
            return {"id": record.get("id"), "status": record.get("status", "none"),
                    "progress": record.get("progress", 0), "message": record.get("message", ""),
                    "error": record.get("error"), "stale": reason is not None,
                    "stale_reason": reason, "media_ready": ready,
                    "media_version": (media.get("id") or media.get("checksum_sha256")) if ready else None,
                    "media_plan": copy.deepcopy(media.get("plan_overview")) if ready else None,
                    "template_version": TEMPLATE_VERSION,
                    "plan": plan_overview(record.get("plan")) or media.get("plan_overview"),
                    "created_at": record.get("created_at"), "finished_at": record.get("finished_at")}

    def create(self, job_id, owner, payload: CoachingCreate):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            self._available(job)
            if self._stop.is_set():
                raise HTTPException(503, "模板视频服务正在停止，请稍后重试。")
            previous = job.get("template_video") or {}
            payload_fingerprint = _digest(payload.model_dump())
            if previous.get("status") in ACTIVE:
                if (previous.get("payload_fingerprint") == payload_fingerprint
                        and not self._reason(job, previous)):
                    return self.get(job_id, owner)
                raise HTTPException(409, "模板视频正在制作，请等待完成或先停止。")
            # CoachingManager owns consent, scope, budget and identical-request caching.
            # It alone can request cloud work; template planning/rendering are local.
            if self._queue.full() and previous.get("status") not in ACTIVE:
                raise HTTPException(429, "模板视频队列已满，请稍后重试。")
            previous_report_id = (job.get("coaching") or {}).get("id")
            coaching = self.coaching.create(job_id, owner, payload)
            job = self.store.get(job_id, owner, private=True)
            fingerprint = self._fingerprint(job)
            request_fingerprint = _digest({"template": TEMPLATE_VERSION, "evidence": fingerprint,
                                           "report_id": coaching["id"]})
            if (previous.get("request_fingerprint") == request_fingerprint and not self._reason(job, previous)
                    and previous.get("status") in ACTIVE | {"succeeded"}):
                return self.get(job_id, owner)
            if previous.get("status") in ACTIVE:
                raise HTTPException(409, "模板视频正在制作，请等待完成或先停止。")
            record = {"id": uuid.uuid4().hex, "status": "queued", "progress": 0,
                      "message": "等待网页 Agent 分析与模板制作", "error": None,
                      "created_at": _now(), "finished_at": None, "template_version": TEMPLATE_VERSION,
                      "report_id": coaching["id"], "request_fingerprint": request_fingerprint,
                      "owns_report": coaching["id"] != previous_report_id,
                      "analysis_version": self._analysis_version(),
                      "knowledge_fingerprint": self.coaching._knowledge_version(),
                      "payload_fingerprint": payload_fingerprint,
                      "evidence_fingerprint": fingerprint, "plan": None,
                      "media": copy.deepcopy(previous.get("media"))}
            self.store.update(job_id, template_video=record)
            self._queue.put_nowait((job_id, owner, record["id"]))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="replay-template-video", daemon=True)
                self._thread.start()
            return self.get(job_id, owner)

    def invalidate(self, job_id, *, media_kind=None, revoked=False, reason=None):
        if media_kind and media_kind != "source_video":
            return
        with self.store._lock:
            try:
                job = self.store._read(job_id)
            except HTTPException:
                return
            record = job.get("template_video")
            if not record:
                return
            message = reason or ("授权已撤回，模板视频已失效。" if revoked else "依据已更新，模板视频已失效。")
            record.update(invalidated=True, stale_reason=message)
            if record.get("status") in ACTIVE:
                record.update(status="cancelled", message="制作已停止", error=message, finished_at=_now())
            if record.get("media"):
                record["media"].update(invalidated=True, stale_reason=message)
            self.store.update(job_id, template_video=record)

    def cancel(self, job_id, owner):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("template_video") or {}
            if record.get("status") in ACTIVE:
                coaching = job.get("coaching") or {}
                owns_active_report = (record.get("owns_report") and coaching.get("id") == record.get("report_id")
                                      and coaching.get("status") in {"queued", "running"})
                shared_active_report = coaching.get("status") in {"queued", "running"} and not owns_active_report
                record.update(status="cancelled", message="已停止制作；已有视频仍保留。",
                              error=None, finished_at=_now())
                if shared_active_report:
                    record["message"] = "已停止视频制作；复用的独立 Agent 分析仍继续，可在报告中停止。"
                self.store.update(job_id, template_video=record)
                if owns_active_report:
                    self.coaching.cancel(job_id, owner)
            return self.get(job_id, owner)

    def report_cancelled(self, job_id):
        """A stopped shared analysis cancels only pending movies, not older media."""
        with self.store._lock:
            job = self.store._read(job_id)
            record = job.get("template_video") or {}
            if (record.get("status") in ACTIVE
                    and record.get("report_id") == (job.get("coaching") or {}).get("id")):
                record.update(status="cancelled", message="Agent 分析已停止，模板视频制作也已停止。",
                              error=None, finished_at=_now())
                self.store.update(job_id, template_video=record)

    def media_file(self, job_id, owner):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            media = (job.get("template_video") or {}).get("media") or {}
            if not media:
                raise HTTPException(404, "模板视频尚未生成")
            if self._reason(job, media):
                raise HTTPException(409, "模板视频依据已失效，请重新制作。")
            path = self._path(job_id, media)
            if not path.is_file():
                raise HTTPException(404, "模板视频已不可用")
            return path

    def _current(self, job_id, owner, run_id):
        job = self.store.get(job_id, owner, private=True)
        record = job.get("template_video") or {}
        if (self._stop.is_set() or record.get("id") != run_id or record.get("status") not in ACTIVE
                or self._reason(job, record)):
            raise TemplateCancelled()
        report = job.get("coaching") or {}
        if report.get("id") != record.get("report_id") or (report.get("consent") or {}).get("event") != "granted":
            raise TemplateCancelled()
        return job, record, report

    def _cancelled(self, job_id, owner, run_id):
        with self.store._lock:
            try:
                self._current(job_id, owner, run_id)
                return False
            except (HTTPException, OSError, ValueError, TemplateCancelled):
                return True

    def _execute(self, job_id, owner, run_id):
        target = None
        with self._condition:
            self._running.add(job_id)
        try:
            while True:
                with self.store._lock:
                    job, record, coaching = self._current(job_id, owner, run_id)
                    if coaching.get("status") == "succeeded":
                        if self.coaching._stale_reason(job, coaching):
                            raise TemplateCancelled()
                        break
                    if coaching.get("status") not in {"queued", "running"}:
                        raise RuntimeError("report_unavailable")
                    if record.get("status") != "waiting_report":
                        record.update(status="waiting_report", progress=5, message="等待现有 Agent 分析完成，不重复发送画面。")
                        self.store.update(job_id, template_video=record)
                self._stop.wait(.1)
            with self.store._lock:
                job, record, coaching = self._current(job_id, owner, run_id)
                source, _ = self._available(job)
                source_digest = self.store._sha256(source)
                inputs = {key: copy.deepcopy(job.get(key)) for key in
                          ("result", "video", "segment_reviews", "segment_review_history", "route_version_id")}
                report = copy.deepcopy(coaching["report"])
                record.update(status="running", progress=15, message="正在按模板组织本次动作与有效数据。")
                self.store.update(job_id, template_video=record)
            plan = self.planner(inputs, report)
            if not isinstance(plan, dict) or plan.get("version") != TEMPLATE_VERSION:
                raise ValueError("unsupported_plan")
            with self.store._lock:
                job, record, _ = self._current(job_id, owner, run_id)
                record.update(plan=plan, progress=20, message="正在制作模板复盘视频。")
                self.store.update(job_id, template_video=record)
                target = self.store._path(job_id).parent / f"template-{run_id}.mp4"

            def progress(message, value):
                with self.store._lock:
                    _, ongoing, _ = self._current(job_id, owner, run_id)
                    ongoing.update(progress=max(20, min(99, 20 + round(float(value) * .79))),
                                   message="正在制作模板复盘视频。")
                    self.store.update(job_id, template_video=ongoing)

            metrics = self.renderer(source, plan, target,
                                    cancelled=lambda: self._cancelled(job_id, owner, run_id), progress=progress)
            with self.store._lock:
                job, record, coaching = self._current(job_id, owner, run_id)
                if self.coaching._stale_reason(job, coaching) or self.store._sha256(source) != source_digest:
                    raise TemplateCancelled()
                if not target.is_file() or target.stat().st_size == 0:
                    raise RuntimeError("render_missing_output")
                old_media = record.get("media")
                record.update(status="succeeded", progress=100, message="模板复盘视频已生成。", error=None,
                              finished_at=_now(), metrics=metrics,
                              media={"id": run_id, "storage_name": target.name, "template_version": TEMPLATE_VERSION,
                                     "analysis_version": record["analysis_version"],
                                     "knowledge_fingerprint": record["knowledge_fingerprint"],
                                     "evidence_fingerprint": record["evidence_fingerprint"],
                                     "size_bytes": target.stat().st_size, "checksum_sha256": self.store._sha256(target),
                                     "content_type": "video/mp4", "plan_overview": plan_overview(plan)})
                self.store.update(job_id, template_video=record)
                if old_media:
                    try:
                        old_path = self._path(job_id, old_media)
                        if old_path != target:
                            old_path.unlink(missing_ok=True)
                    except (HTTPException, OSError):
                        pass
                target = None  # The committed movie is no longer worker-owned.
        except Exception as exc:
            with self.store._lock:
                try:
                    job = self.store.get(job_id, owner, private=True)
                    record = job.get("template_video") or {}
                    if (not job.get("deletion") and not self.store._deletion_path(job_id).exists()
                            and record.get("id") == run_id and record.get("status") in ACTIVE):
                        cancelled = isinstance(exc, (TemplateCancelled, InterruptedError))
                        record.update(status="cancelled" if cancelled else "failed", finished_at=_now(),
                                      message="原有复盘与已有模板视频仍保留。",
                                      error="依据已变化或制作已停止。" if cancelled else "模板视频未生成，请检查分析结果后重试。")
                        self.store.update(job_id, template_video=record)
                except (HTTPException, OSError):
                    pass
        finally:
            if target is not None:
                target.unlink(missing_ok=True)
            with self._condition:
                self._running.discard(job_id)
                self._condition.notify_all()

    def wait_idle(self, job_id, timeout=2):
        with self._condition:
            return self._condition.wait_for(lambda: job_id not in self._running, timeout=timeout)

    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self._execute(*item)
            finally:
                self._queue.task_done()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def template_router(manager):
    class PrivateRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def response(request):
                result = await handler(request)
                result.headers["Cache-Control"] = "private, no-store"
                result.headers["X-Content-Type-Options"] = "nosniff"
                return result
            return response

    router = APIRouter(route_class=PrivateRoute)

    def owner(request):
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    @router.post("/jobs/{job_id}/template-video", status_code=202)
    def create(job_id: str, payload: CoachingCreate, request: Request):
        return manager.create(job_id, owner(request), payload)

    @router.get("/jobs/{job_id}/template-video")
    def get(job_id: str, request: Request):
        return manager.get(job_id, owner(request))

    @router.post("/jobs/{job_id}/template-video/cancel")
    def cancel(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request))

    @router.get("/jobs/{job_id}/template-video/media")
    def media(job_id: str, request: Request, download: bool = False):
        path = manager.media_file(job_id, owner(request))
        return FileResponse(path, media_type="video/mp4", filename="模板复盘.mp4" if download else None,
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    return router
