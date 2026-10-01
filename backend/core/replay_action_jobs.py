"""Owner-scoped action result versions and local exports within existing jobs."""
from copy import deepcopy
from pathlib import Path
import queue
import threading
import uuid
import cv2
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .replay_actions import VERSION, ALGORITHM_VERSION, digest, organize, basic_metrics
from .replay_action_naming import catalogue, enrich_names
from .replay_action_review import revise_result, corrected_contact_evidence
from .replay_action_engine import ActionEngine
from .replay_action_renderer import make_plan, render_actions, PRESENTATION_VERSION
from .replay_motion_summary import prepare_motion_evidence, enrich_motion_summary
from .replay_route_usage import enrich_route_usage
from .replay_coaching_cost import estimate_ledger_cost

ACTIVE = {"queued", "running"}


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud_consent: bool = False
    consent_version: str | None = None
    budget_confirmed: bool = False


class ActionExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_version: str
    scope: Literal["full", "group"] = "full"
    group_id: str | None = None
    speed: Literal[0.5, 0.75, 1] = 0.75


class ActionRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    result_version: str
    group_id: str
    event_id: str | None = None
    limb: Literal["left_hand", "right_hand", "left_foot", "right_foot"]
    action: str = Field(max_length=32)
    start_seconds: float
    end_seconds: float
    source_hold_id: StrictInt | StrictStr | None = None
    target_hold_id: StrictInt | StrictStr | None = None
    contact_seconds: float | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    technique_codes: list[str] = Field(default_factory=list, max_length=8)


class ActionUndo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_version: str


class ActionManager:
    def __init__(self, store, engine=None, renderer=None):
        self.store, self.engine, self.renderer = store, engine or ActionEngine(), renderer or render_actions
        self.queue = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.running = set()
        self.thread = None
        store.action_manager = self
        for path in store.jobs.glob("*/job.json"):
            with store._lock:
                try:
                    job = store._read(path.parent.name)
                    changes = {}
                    for key in ("action_task", "action_export"):
                        record = job.get(key)
                        if record and record.get("status") in ACTIVE:
                            changes[key] = dict(record, status="failed", error="服务重启，任务已停止，可重试。")
                    if changes:
                        store.update(job["id"], **changes)
                except (HTTPException, ValueError, OSError):
                    pass

    def source(self, job):
        if job.get("deletion") or self.store._deletion_path(job["id"]).exists():
            raise HTTPException(409, "记录正在删除")
        if job.get("status") != "succeeded" or not job.get("result"):
            raise HTTPException(409, "请先完成视频识别")
        history = [r for r in job.get("consent_history", []) if r.get("attempt") == job.get("attempt", 1)]
        if history and history[-1].get("event") == "withdrawn":
            raise HTTPException(409, "本次处理授权已撤回")
        path, _ = self.store.media_file(job["id"], job["owner"], "source_video")
        if not path.is_file():
            raise HTTPException(409, "原片缺失，只能播放已有旧视频")
        return path

    def fingerprint(self, job):
        source = self.source(job)
        stat = source.stat()
        result = {k: v for k, v in job["result"].items()
                  if k not in {"visual_replay", "visual_reference", "overlay", "visual_review_inputs"}}
        return digest({"version": VERSION, "algorithm": ALGORITHM_VERSION, "result": result, "video": job.get("video"),
                       "reviews": job.get("segment_reviews"), "source": [stat.st_size, stat.st_mtime_ns]})

    def presentation_source(self, job):
        for kind in ("reviewed_overlay_video", "overlay_video"):
            if (job.get("media", {}).get(kind) or {}).get("status") == "available":
                path, _ = self.store.media_file(job["id"], job["owner"], kind)
                capture = cv2.VideoCapture(str(path))
                video = {"width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                         "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                         "fps": capture.get(cv2.CAP_PROP_FPS),
                         "frame_count": int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}
                capture.release()
                if not all(video.values()):
                    raise ValueError("Base replay unavailable")
                return path, video
        return self.source(job), None

    def valid(self, job, record):
        try:
            return bool(record) and record.get("fingerprint") == self.fingerprint(job)
        except (HTTPException, OSError):
            return False

    def get(self, job_id, owner):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("action_result") or {}
            valid = self.valid(job, record)
            result = record.get("result") if valid else None
            presentation = enrich_names(result) if result else None
            presentation = enrich_motion_summary(presentation) if presentation and not presentation.get('motion_summary') else presentation
            if presentation and not presentation.get('route_usage'):
                presentation = enrich_route_usage(presentation, job['result'])
            public = {k: deepcopy(presentation[k]) for k in ("schema_version", "algorithm_version", "source_duration_seconds", "time_basis", "groups", "metrics", "motion_summary", "motion_analysis", "naming_version", "relations", "naming_validation") if k in presentation} if presentation else None
            if public is not None:
                public["holds"] = [{"id": h["id"]} for h in presentation.get("holds", []) if isinstance(h.get("id"), (str, int)) and not isinstance(h.get("id"), bool)]
            export = job.get("action_export") or {}
            media = job.get("action_export_media") or {}
            task = deepcopy(job.get("action_task") or {"status": "idle"})
            return {"task": task, "cost": estimate_ledger_cost(task.get("usage", [])),
                    "history_costs": [{"id": r["id"], "status": r["status"], "cost": estimate_ledger_cost(r.get("usage", []))}
                                      for r in job.get("action_history", []) if r.get("usage")],
                    "result": public, "result_version": record.get("id") if valid else None,
                    "presentation_version": record.get('presentation_version') if valid else None,
                    "stale": bool(record) and not valid, "media_ready": valid and bool(record.get("storage_name")) and record.get('presentation_version') == PRESENTATION_VERSION,
                    "export": deepcopy(export), "export_media": {k: media[k] for k in
                        ("id", "scope", "group_id", "speed", "result_version") if k in media} if self.valid(job, media) and media.get("result_version") == record.get("id") else None,
                    "revision_count": len(job.get("action_revisions", [])), "vocabulary": catalogue(),
                    "cloud_configured": self.engine.configured, "consent_version": VERSION, "budget_cny": .2}

    def revise(self, job_id, owner, payload=None, *, undo_version=None):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("action_result") or {}
            version = undo_version if undo_version is not None else payload.result_version
            if not self.valid(job, record) or record.get("id") != version:
                raise HTTPException(409, "动作结果已更新，请刷新后修正")
            if any((job.get(k) or {}).get("status") in ACTIVE for k in ("action_task", "action_export")):
                raise HTTPException(409, "请等待当前任务完成或先停止，再修正动作")
            history = deepcopy(job.get("action_revisions", []))
            if undo_version is not None:
                if not history:
                    raise HTTPException(409, "没有可撤销的动作修正")
                previous = history.pop()
                if previous["fingerprint"] != record["fingerprint"]:
                    raise HTTPException(409, "原分析已变化，不能撤销旧版修正")
                result = previous["result"]
            else:
                if len(history) >= 100:
                    raise HTTPException(409, "本版修正记录已达上限，请先导出或撤销已有修正")
                try:
                    result = revise_result(record["result"], payload.model_dump(), owner)
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from None
                history.append({"id": uuid.uuid4().hex, "fingerprint": record["fingerprint"], "result": deepcopy(record["result"]),
                                "created_at": datetime.now(timezone.utc).isoformat(), "actor": owner})
                source = corrected_contact_evidence(result, job["result"])
                result["metrics"] = basic_metrics(source, result.get("motion_intervals", []))
                result = enrich_motion_summary(result)
                result = enrich_route_usage(result, source)
                result["route_usage"]["basis"] = "automatic_and_action_review_contacts"
                for metric in result["metrics"]:
                    if metric.get("basis") in {"automatic_contacts", "automatic_route_and_contacts"}:
                        metric["basis"] = "automatic_and_action_review_contacts"
            updated = dict(record, id=uuid.uuid4().hex, result=result, request_key="manual-revision-" + uuid.uuid4().hex)
            # The unchanged base movie remains playable. Captions and exported
            # revisions use the new result; old files and tracks are preserved.
            audit = {"id": uuid.uuid4().hex, "kind": "undo" if undo_version is not None else "review",
                     "actor": owner, "created_at": datetime.now(timezone.utc).isoformat(),
                     "previous_result_version": record["id"], "result_version": updated["id"],
                     "fingerprint": record["fingerprint"], "previous_result": deepcopy(record["result"])}
            if payload is not None:
                audit["changes"] = payload.model_dump()
            self.store.update(job_id, action_result=updated, action_revisions=history,
                              action_revision_audit=[*job.get("action_revision_audit", []), audit])
            return self.get(job_id, owner)

    def enqueue(self, job_id, owner, key, payload):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            fingerprint = self.fingerprint(job)
            current = job.get(key) or {}
            payload = payload.model_dump()
            request_key = digest({"fingerprint": fingerprint, "payload": payload,
                                  "presentation": PRESENTATION_VERSION})
            if current.get("status") in ACTIVE:
                if current.get("request_key") == request_key:
                    return self.get(job_id, owner)
                raise HTTPException(409, "任务正在进行，请先停止")
            if key == "action_task":
                if payload["cloud_consent"]:
                    if payload["consent_version"] != VERSION or not payload["budget_confirmed"]:
                        raise HTTPException(400, "请确认动作核对的云端处理和费用")
                    if not self.engine.configured:
                        raise HTTPException(503, "尚未配置动作核对服务，可先整理本地片段")
                cached = job.get("action_result") or {}
                if self.valid(job, cached) and cached.get("request_key") == request_key:
                    return self.get(job_id, owner)
            else:
                record = job.get("action_result") or {}
                if not self.valid(job, record) or record.get("id") != payload["result_version"]:
                    raise HTTPException(409, "动作结果已更新，请刷新后导出")
                try:
                    make_plan(record["result"], scope=payload["scope"], group_id=payload["group_id"], speed=payload["speed"])
                except ValueError:
                    raise HTTPException(400, "导出动作范围无效") from None
                cached = job.get("action_export_media") or {}
                if self.valid(job, cached) and cached.get("request_key") == request_key:
                    return self.get(job_id, owner)
            if self.queue.full():
                raise HTTPException(429, "正在处理其他视频，请稍后重试")
            run_id = uuid.uuid4().hex
            if current:
                self.store.update(job_id, action_history=[*(job.get("action_history") or []), dict(current, kind=key)])
            self.store.update(job_id, **{key: {"id": run_id, "status": "queued", "progress": 0,
                "request_key": request_key, "fingerprint": fingerprint, "payload": payload, "usage": []}})
            self.queue.put_nowait((job_id, owner, key, run_id))
            if not self.thread:
                self.thread = threading.Thread(target=self._run, daemon=True, name="replay-actions")
                self.thread.start()
            return self.get(job_id, owner)

    def current(self, job_id, owner, key, run_id):
        job = self.store.get(job_id, owner, private=True)
        record = job.get(key) or {}
        if (self.stop.is_set() or record.get("id") != run_id or record.get("status") not in ACTIVE
                or not self.valid(job, record)):
            raise InterruptedError()
        return job, record

    def cancelled(self, *args):
        with self.store._lock:
            try:
                self.current(*args)
                return False
            except (HTTPException, InterruptedError, OSError):
                return True

    def cancel(self, job_id, owner, key):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get(key) or {}
            if record.get("status") in ACTIVE:
                self.store.update(job_id, **{key: dict(record, status="cancelled")})
            return self.get(job_id, owner)

    def invalidate(self, job_id):
        with self.store._lock:
            try:
                job = self.store._read(job_id)
                for key in ("action_task", "action_export"):
                    record = job.get(key) or {}
                    if record.get("status") in ACTIVE:
                        self.store.update(job_id, **{key: dict(record, status="cancelled")})
            except HTTPException:
                pass

    def execute(self, job_id, owner, key, run_id):
        target = None
        with self.condition:
            self.running.add(job_id)
        args = (job_id, owner, key, run_id)
        try:
            with self.store._lock:
                job, record = self.current(*args)
                source = self.source(job)
                snapshot = deepcopy(job)
                record.update(status="running", progress=5)
                self.store.update(job_id, **{key: record})
                source_hash = self.store._sha256(source)
            def usage(event):
                # Late billing belongs to its original attempt, even if cancelled.
                with self.store._lock:
                    latest = self.store.get(job_id, owner, private=True)
                    if latest.get("deletion"):
                        return
                    task = latest.get(key) or {}
                    if task.get("id") == run_id:
                        rows = [r for r in task.get("usage", []) if r["request_id"] != event["request_id"]]
                        task["usage"] = rows + [deepcopy(event)]
                        self.store.update(job_id, **{key: task})
                    else:
                        history = latest.get("action_history") or []
                        for previous in history:
                            if previous.get("id") == run_id:
                                previous["usage"] = [r for r in previous.get("usage", []) if r["request_id"] != event["request_id"]] + [deepcopy(event)]
                                self.store.update(job_id, action_history=history)
                                break
            if key == "action_task":
                snapshot['result'] = prepare_motion_evidence(snapshot['result'], source, cancelled=lambda: self.cancelled(*args))
                result = organize(snapshot)
                if record["payload"]["cloud_consent"]:
                    reviews = self.engine.run(source, snapshot, result,
                        cancelled=lambda: self.cancelled(*args), usage_callback=usage)
                    result = organize(snapshot, reviews)
                result = enrich_motion_summary(result)
                result = enrich_route_usage(result, snapshot['result'])
                render_source, base_video = self.presentation_source(snapshot)
                plan = make_plan(result, speed=1, summary=False, base_video=base_video, annotations=False)
            else:
                result = enrich_names(snapshot["action_result"]["result"])
                if not result.get('motion_summary'):
                    result = enrich_motion_summary(result)
                if not result.get('route_usage'):
                    result = enrich_route_usage(result, snapshot['result'])
                p = record["payload"]
                render_source, base_video = self.presentation_source(snapshot)
                plan = make_plan(result, scope=p["scope"], group_id=p["group_id"], speed=p["speed"], summary=False, annotations=False, base_video=base_video)
            target = self.store._path(job_id).parent / f"actions-{run_id}.mp4"
            base_hash = self.store._sha256(render_source)
            self.renderer(render_source, plan, target, cancelled=lambda: self.cancelled(*args))
            with self.store._lock:
                latest, record = self.current(*args)
                if self.store._sha256(source) != source_hash or self.store._sha256(render_source) != base_hash or not target.is_file():
                    raise InterruptedError()
                media = {"id": run_id, "storage_name": target.name, "fingerprint": record["fingerprint"], "presentation_version": PRESENTATION_VERSION,
                         "request_key": record["request_key"]}
                if key == "action_task":
                    media["result"] = result
                    output_key = "action_result"
                    self.store.update(job_id, action_revisions=[])
                else:
                    media.update(record["payload"])
                    output_key = "action_export_media"
                record.update(status="succeeded", progress=100)
                self.store.update(job_id, **{key: record, output_key: media})
                target = None
        except Exception as exc:
            with self.store._lock:
                try:
                    latest = self.store.get(job_id, owner, private=True)
                    task = latest.get(key) or {}
                    if not latest.get("deletion") and task.get("id") == run_id and task.get("status") in ACTIVE:
                        task.update(status="cancelled" if isinstance(exc, InterruptedError) else "failed",
                                    error="处理未完成，已有视频保留。可检查服务配置与预算后重试。")
                        self.store.update(job_id, **{key: task})
                except (HTTPException, OSError):
                    pass
        finally:
            if target is not None:
                target.unlink(missing_ok=True)
            with self.condition:
                self.running.discard(job_id)
                self.condition.notify_all()

    def media_file(self, job_id, owner, version, exported=False):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("action_export_media" if exported else "action_result") or {}
            if not self.valid(job, record) or record.get("id") != version:
                raise HTTPException(409, "视频版本已变化，请刷新")
            if exported and record.get("result_version") != (job.get("action_result") or {}).get("id"):
                raise HTTPException(409, "动作已修正，请重新导出")
            name = record.get("storage_name", "")
            if Path(name).name != name or not name.startswith("actions-"):
                raise HTTPException(404, "视频不可用")
            path = self.store._path(job_id).parent / name
            if not path.is_file():
                raise HTTPException(404, "视频不可用")
            return path

    def wait_idle(self, job_id, timeout=2):
        with self.condition:
            return self.condition.wait_for(lambda: job_id not in self.running, timeout)

    def _run(self):
        while not self.stop.is_set():
            try:
                args = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.execute(*args)
            finally:
                self.queue.task_done()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)


def action_router(manager):
    class PrivateRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()
            async def response(request):
                result = await handler(request)
                result.headers["Cache-Control"] = "private, no-store"
                return result
            return response
    router = APIRouter(route_class=PrivateRoute)
    def owner(request):
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    @router.get("/jobs/{job_id}/actions")
    def get(job_id: str, request: Request):
        return manager.get(job_id, owner(request))

    @router.post("/jobs/{job_id}/actions", status_code=202)
    def create(job_id: str, payload: ActionCreate, request: Request):
        return manager.enqueue(job_id, owner(request), "action_task", payload)

    @router.post("/jobs/{job_id}/actions/cancel")
    def cancel(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request), "action_task")

    @router.post("/jobs/{job_id}/actions/review")
    def review(job_id: str, payload: ActionRevision, request: Request):
        return manager.revise(job_id, owner(request), payload)

    @router.post("/jobs/{job_id}/actions/review/undo")
    def undo(job_id: str, payload: ActionUndo, request: Request):
        return manager.revise(job_id, owner(request), undo_version=payload.result_version)

    @router.post("/jobs/{job_id}/actions/export", status_code=202)
    def export(job_id: str, payload: ActionExport, request: Request):
        return manager.enqueue(job_id, owner(request), "action_export", payload)

    @router.post("/jobs/{job_id}/actions/export/cancel")
    def cancel_export(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request), "action_export")

    @router.get("/jobs/{job_id}/actions/media")
    def media(job_id: str, version: str, request: Request, exported: bool = False, download: bool = False):
        path = manager.media_file(job_id, owner(request), version, exported)
        return FileResponse(path, media_type="video/mp4", filename="climb-replay.mp4" if download else None,
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    return router
