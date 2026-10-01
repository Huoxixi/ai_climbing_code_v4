"""Optional, owner-scoped reports derived from an existing replay.

Reports live in the replay job, so the existing whole-job deletion also removes
personal snapshots. No image or provider response is written to a separate log.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.replay_coaching_engine import (CoachingEngine, CoachingCancelled,
                                        CoachingEngineError, analysis_frame_count)
from core.replay_coaching_cost import estimate_coaching_cost, estimate_ledger_cost, budget_policy
from core.replay_coaching_knowledge import ClaimRegistry


CONSENT_VERSION = "replay-coaching-evidence-v2-2026-09-27"
PIPELINE_VERSION = "replay-coaching-actions-v3"
GENERATION_VERSION = "replay-coaching-actions-verified-claim-2026-09-30"
ACTIVE = {"queued", "running"}
KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "docs" / "bouldering-knowledge"


class PersonalContext(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    height_cm: float | None = Field(None, gt=0, le=300)
    arm_span_cm: float | None = Field(None, gt=0, le=350)
    weight_kg: float | None = Field(None, gt=0, le=500)
    climbing_years: float | None = Field(None, ge=0, le=100)
    usual_grade: str | None = Field(None, max_length=60)


class AttemptContext(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    goal: str | None = Field(None, max_length=500)
    focus_start_seconds: float | None = Field(None, ge=0)
    focus_end_seconds: float | None = Field(None, gt=0)
    fatigue: str | None = Field(None, max_length=300)
    discomfort: str | None = Field(None, max_length=300)
    movement_limitations: str | None = Field(None, max_length=300)

    @model_validator(mode="after")
    def valid_interval(self):
        if (self.focus_start_seconds is None) != (self.focus_end_seconds is None):
            raise ValueError("关注片段需要同时填写起止时间")
        if self.focus_end_seconds is not None and self.focus_end_seconds <= self.focus_start_seconds:
            raise ValueError("片段结束时间必须晚于开始时间")
        return self


class CoachingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_version: str = Field(min_length=1, max_length=100)
    consent_granted: bool
    adult_confirmed: bool | None = None
    indoor_bouldering_confirmed: bool = False
    observation_only_accepted: bool = False
    budget_accepted: bool = False
    personal: PersonalContext = Field(default_factory=PersonalContext)
    context: AttemptContext = Field(default_factory=AttemptContext)


class CoachingFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: str = Field(min_length=1, max_length=64)
    item_id: str = Field(min_length=1, max_length=100)
    kind: Literal["helpful", "inaccurate", "not_applicable"]
    reason: Literal["body_part", "time", "knowledge", "conditions", "wording", "priority"] | None = None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _clean(model: BaseModel) -> dict:
    values = model.model_dump(exclude_none=True)
    return {key: value.strip() if isinstance(value, str) else value
            for key, value in values.items() if not isinstance(value, str) or value.strip()}


class CoachingManager:
    def __init__(self, store, engine=None, *, enabled: bool | None = None):
        self.store = store
        self.engine = engine if engine is not None else CoachingEngine()
        self.enabled = (os.getenv("ENABLE_REPLAY_COACHING", "true").lower() in {"1", "true", "yes"}
                        if enabled is None else enabled)
        self._queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread = None
        self.store.coaching_manager = self
        # Interrupted reports require an explicit retry; restarting never incurs a cloud charge.
        with store._lock:
            for path in store.jobs.glob("*/job.json"):
                try:
                    job = store._read(path.parent.name)
                    report = job.get("coaching") or {}
                    if report.get("status") in ACTIVE and not job.get("deletion"):
                        report.update(status="failed", error="服务重启，报告生成已停止，请重新生成。")
                        store.update(job["id"], coaching=report)
                except (OSError, ValueError, HTTPException):
                    continue

    def policy(self) -> dict:
        approved = len(ClaimRegistry(Path(getattr(self.engine, "knowledge_root", KNOWLEDGE_ROOT)),
                                     runtime_versions={"model": self.engine.model}).approved_claims())
        return {"version": CONSENT_VERSION, "enabled": self.enabled,
                "configured": bool(self.engine.configured), "provider": "阿里云百炼",
                "model": self.engine.model, "region": "cn-beijing",
                "data_types": ["已有无叠加分析副本的必要画面及局部截图；缺失时使用已有叠加画面", "复盘时间与定位信息", "建议筛选确需的本次目标、经验与感受；观察阶段不发送个人背景，体重不发送"],
                "purpose": "生成本次个性化攀岩复盘报告", "full_video_sent": False,
                "advice_available": approved > 0, "approved_claim_count": approved,
                "observation_only_notice": "当前没有通过主张审核与独立视频验收的知识，本次仅整理画面观察，不能生成技术建议。",
                "budget": budget_policy(),
                "knowledge_notice": "最多一项有条件的尝试；必要证据不足时只提供核对片段或说明缺失资料。第一版暂停个性化伤害风险判断。"}

    @staticmethod
    def _withdrawn(job: dict) -> bool:
        attempt = int(job.get("attempt") or 1)
        latest = next((entry for entry in reversed(job.get("consent_history") or [])
                       if int(entry.get("attempt") or 0) == attempt), None)
        return bool(latest and latest.get("event") == "withdrawn")

    def _available(self, job: dict) -> None:
        if job.get("deletion") or self.store._deletion_path(job["id"]).exists():
            raise HTTPException(409, "这次复盘正在删除，不能生成报告。")
        if job.get("status") != "succeeded" or not job.get("result"):
            raise HTTPException(409, "请先完成现有 AI 复盘。")
        if self._withdrawn(job):
            raise HTTPException(409, "本次复盘的第三方处理授权已撤回。")

    def _media(self, job: dict, kind: str | None = None):
        for candidate in ([kind] if kind else ["source_video", "reviewed_overlay_video", "overlay_video"]):
            try:
                path, item = self.store.media_file(job["id"], job["owner"], candidate)
                stat = path.stat()
                if stat.st_size:
                    return path, {"kind": candidate, "checksum_sha256": item.get("checksum_sha256"),
                                  "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                  "generated_at": item.get("generated_at"),
                                  "has_overlay": candidate != "source_video", "time_basis": "replay_seconds",
                                  "visual_replay": copy.deepcopy(item.get("visual_replay")),
                                  "revision": (job.get("result") or {}).get("hold_review_version", 0)}
            except (OSError, HTTPException):
                continue
        raise HTTPException(409, "复盘视频已删除或不可用，请先生成可播放的复盘视频。")

    def preflight(self, job_id: str, owner: str) -> dict:
        """Read-only checks; never decode via or call a cloud provider."""
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            self._available(job)
            path, media = self._media(job)
            duration = self._validate_media(job, path, media["kind"])
            return self.policy() | {"ready": True, "duration_seconds": duration, "media": media}

    def _validate_media(self, job: dict, path: Path, media_kind="overlay_video") -> float:
        duration = float((job.get("video") or (job.get("result") or {}).get("video") or {}).get("duration_seconds") or 0)
        if not math.isfinite(duration) or not 0 < duration <= 1800:
            raise HTTPException(409, "视频时长无效或超过本次分析范围。")
        # Dependency-injected test engines can provide their own synthetic reader.
        if isinstance(self.engine, CoachingEngine):
            import cv2
            cap = cv2.VideoCapture(str(path))
            try:
                ok, frame = cap.read()
                fps = cap.get(cv2.CAP_PROP_FPS)
                count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if (not cap.isOpened() or not ok or frame is None or not math.isfinite(fps)
                        or fps <= 0 or not math.isfinite(count) or count <= 0):
                    raise HTTPException(409, "本次视频无法读取，请检查可播放的分析副本。")
                try:
                    analysis_frame_count(job, fps, count, media_kind)
                except CoachingEngineError:
                    raise HTTPException(409, "视频分析区间与当前动作记录不一致，请先核对媒体版本。") from None
            finally:
                cap.release()
        return duration

    def _knowledge_version(self) -> str:
        root = Path(getattr(self.engine, "knowledge_root", KNOWLEDGE_ROOT))
        return ClaimRegistry(root, runtime_versions={"model": self.engine.model}).fingerprint

    def _evidence(self, job: dict, media: dict) -> dict:
        from core.replay_coaching_engine import ANALYSIS_VERSION
        public = self.store._public(job)
        # Render progress/style cannot change analysis evidence. A replacement
        # of the actual selected video still changes its media fingerprint.
        analysis = {key: value for key, value in (job.get("result") or {}).items()
                    if key not in {"visual_replay", "visual_reference"}}
        return {"pipeline": PIPELINE_VERSION, "analysis_version": ANALYSIS_VERSION, "model": self.engine.model,
                "attempt": job.get("attempt"), "route_id": job.get("route_id"),
                "route_version_id": job.get("route_version_id"), "video": job.get("video"),
                "result": analysis, "reviewed_segments": public.get("reviewed_segments", []),
                "segment_review_history": job.get("segment_review_history", []),
                "media": media, "knowledge": self._knowledge_version()}

    def _stale_reason(self, job: dict, record: dict) -> str | None:
        if (record.get("consent") or {}).get("event") == "withdrawn":
            return "这份报告的云端分析授权已撤回。"
        if self._withdrawn(job):
            return "本次复盘的第三方处理授权已撤回。"
        if record.get("generation_version") != GENERATION_VERSION:
            return "分析方法已更新，请重新生成报告。"
        try:
            _, media = self._media(job, (record.get("media") or {}).get("kind"))
            if _digest(self._evidence(job, media)) != record.get("evidence_fingerprint"):
                return "视频、动作修正或知识依据已更新，请重新生成报告。"
        except (HTTPException, OSError):
            return "这份报告对应的复盘视频已不可用。"
        return None

    def get(self, job_id: str, owner: str) -> dict:
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("coaching")
            if not record:
                return {"id": None, "status": "none", "stale": False, "stale_reason": None,
                        "report": None, "error": None, "feedback": []}
            reason = self._stale_reason(job, record)
            response = {key: copy.deepcopy(record.get(key)) for key in
                    ("id", "status", "report", "error", "error_code", "feedback", "created_at", "finished_at", "personal", "context", "generation_version", "usage_ledger")} | {
                        "stale": reason is not None, "stale_reason": reason, "prototype": True,
                        "legacy": record.get("generation_version") != GENERATION_VERSION}
            response["cost"] = estimate_ledger_cost(record["usage_ledger"]) if "usage_ledger" in record else estimate_coaching_cost((record.get("report") or {}).get("provenance") or {})
            response["previous_attempt_costs"] = [
                {"id": previous.get("id"), "status": previous.get("status"),
                 "cost": estimate_ledger_cost(previous["usage_ledger"]) if "usage_ledger" in previous
                 else estimate_coaching_cost((previous.get("report") or {}).get("provenance") or {})}
                for previous in job.get("coaching_history") or []]
            report = response.get("report")
            if isinstance(report, dict):
                provenance = report.setdefault("provenance", {})
                if "cost" not in provenance:
                    provenance["cost"] = estimate_coaching_cost(provenance)
            return response

    def create(self, job_id: str, owner: str, payload: CoachingCreate) -> dict:
        from core.climb_replay import utcnow
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            self._available(job)
            if not self.enabled or self._stop.is_set():
                raise HTTPException(503, "个性化复盘暂未开启。")
            if not payload.indoor_bouldering_confirmed:
                raise HTTPException(422, "本次仅支持室内抱石，请确认视频范围。")
            if not payload.consent_granted or payload.consent_version != CONSENT_VERSION:
                raise HTTPException(409, "请阅读本次个性化复盘的数据处理说明并选择同意。")
            if not self.engine.configured:
                raise HTTPException(503, "个性化复盘服务尚未配置，请联系服务管理员。")
            policy = self.policy()
            if not payload.budget_accepted:
                raise HTTPException(409, "请先阅读本次费用范围、预算限制及失败或重试可能产生费用的说明。")
            if not policy["advice_available"] and not payload.observation_only_accepted:
                raise HTTPException(409, "当前仅能整理画面观察，请明确选择观察模式后再生成。")
            path, media = self._media(job)
            duration = self._validate_media(job, path, media["kind"])
            if payload.context.focus_end_seconds is not None and payload.context.focus_end_seconds > duration:
                raise HTTPException(422, "关注片段超出了本次复盘视频的时长。")
            personal, context = _clean(payload.personal), _clean(payload.context)
            evidence_snapshot = self._evidence(job, media)
            evidence_fingerprint = _digest(evidence_snapshot)
            fingerprint = _digest({"generation": GENERATION_VERSION, "evidence": evidence_fingerprint, "personal": personal,
                                   "context": context, "consent": CONSENT_VERSION})
            previous = job.get("coaching") or {}
            if (previous.get("input_fingerprint") == fingerprint
                    and (previous.get("consent") or {}).get("event") == "granted"
                    and not self._stale_reason(job, previous)
                    and previous.get("status") in ACTIVE | {"succeeded"}):
                return self.get(job_id, owner)
            if previous.get("status") in ACTIVE:
                raise HTTPException(409, "已有报告正在生成，请等待完成或先停止。")
            if self._queue.full():
                raise HTTPException(429, "报告生成队列已满，请稍后重试。")
            record = {"id": uuid.uuid4().hex, "status": "queued", "created_at": utcnow(),
                      "finished_at": None, "error": None, "report": None, "feedback": [], "usage_ledger": [],
                      "budget": policy["budget"], "observation_only": not policy["advice_available"],
                      "personal": personal, "context": context, "media": media, "generation_version": GENERATION_VERSION,
                      "evidence_snapshot": copy.deepcopy(evidence_snapshot),
                      "evidence_fingerprint": evidence_fingerprint, "input_fingerprint": fingerprint,
                      "consent": {"version": CONSENT_VERSION, "granted_at": utcnow(),
                                  "provider": str(self.engine.provider), "model": self.engine.model,
                                  "adult_confirmed": payload.adult_confirmed, "indoor_bouldering_confirmed": True,
                                  "observation_only_accepted": payload.observation_only_accepted,
                                  "budget_accepted": True, "event": "granted"}}
            history = list(job.get("coaching_history") or [])
            if previous:
                history.append(previous)
            self.store.update(job_id, coaching=record, coaching_history=history)
            self._queue.put_nowait((job_id, owner, record["id"]))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="replay-coaching", daemon=True)
                self._thread.start()
            return self.get(job_id, owner)

    def invalidate(self, job_id: str, *, media_kind: str | None = None, revoked=False, cancel_only=False) -> None:
        """Called inside store mutations, including its scheduled media cleanup."""
        from core.climb_replay import utcnow
        with self.store._lock:
            if getattr(self.store, "template_manager", None):
                if cancel_only:
                    self.store.template_manager.report_cancelled(job_id)
                else:
                    self.store.template_manager.invalidate(job_id, media_kind=media_kind, revoked=revoked)
            job = self.store._read(job_id)
            record = job.get("coaching")
            if not record or (media_kind and (record.get("media") or {}).get("kind") != media_kind):
                return
            if record.get("status") in ACTIVE:
                record.update(status="cancelled", error="生成已停止，后续画面不会继续发送。", finished_at=utcnow())
            if revoked:
                record["consent"] = dict(record.get("consent") or {}, event="withdrawn", withdrawn_at=utcnow())
            self.store.update(job_id, coaching=record)

    def cancel(self, job_id: str, owner: str, *, revoke=False) -> dict:
        with self.store._lock:
            self.store.get(job_id, owner, private=True)
            self.invalidate(job_id, revoked=revoke, cancel_only=not revoke)
            return self.get(job_id, owner)

    def feedback(self, job_id: str, owner: str, payload: CoachingFeedback) -> dict:
        from core.climb_replay import utcnow
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            if job.get("deletion"):
                raise HTTPException(409, "这次复盘正在删除。")
            record = job.get("coaching") or {}
            report = record.get("report") or {}
            ids = {str(item.get("id")) for group in ("observations", "improvements", "risk_reminders")
                   for item in report.get(group, [])}
            if payload.report_id != record.get("id") or record.get("status") != "succeeded" or payload.item_id not in ids:
                raise HTTPException(409, "反馈对应的报告或条目已更新，请刷新后重试。")
            if self._stale_reason(job, record):
                raise HTTPException(409, "报告依据已更新，请先重新生成。")
            feedback = list(record.get("feedback") or [])
            if not any(item.get("item_id") == payload.item_id and item.get("kind") == payload.kind and item.get("reason") == payload.reason for item in feedback):
                feedback.append({"item_id": payload.item_id, "kind": payload.kind, "reason": payload.reason,
                                 "review_status": "pending_review" if payload.kind != "helpful" else "experience_only",
                                 "created_at": utcnow()})
            record["feedback"] = feedback
            self.store.update(job_id, coaching=record)
            return self.get(job_id, owner)

    def _current(self, job_id: str, owner: str, run_id: str) -> tuple[dict, dict]:
        job = self.store.get(job_id, owner, private=True)
        self._available(job)
        record = job.get("coaching") or {}
        if (record.get("id") != run_id or record.get("status") not in ACTIVE
                or (record.get("consent") or {}).get("event") != "granted" or self._stop.is_set()):
            raise CoachingCancelled()
        return job, record

    def _cancelled(self, job_id, owner, run_id) -> bool:
        with self.store._lock:
            try:
                job, record = self._current(job_id, owner, run_id)
                return self._stale_reason(job, record) is not None
            except (HTTPException, CoachingCancelled):
                return True

    def _record_usage(self, job_id: str, owner: str, run_id: str, event: dict) -> None:
        """Journal minimum usage even after cancellation; never revive deleted jobs."""
        from core.climb_replay import utcnow
        if not isinstance(event, dict):
            return
        request_id, stage, status = event.get("request_id"), event.get("stage"), event.get("status")
        if (not isinstance(request_id, str) or not 0 < len(request_id) <= 80
                or stage not in {"observe", "verify", "compose", "boundary"}
                or status not in {"started", "responded", "failed"}):
            return
        # Strict projection: no model content, request data, provider error or picture.
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        clean_usage = {key: value for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                       if isinstance((value := usage.get(key)), int) and not isinstance(value, bool) and value >= 0}
        model = event.get("model")
        clean = {"request_id": request_id, "stage": stage, "status": status,
                 "model": model[:100] if isinstance(model, str) else self.engine.model,
                 "region": "cn-beijing", "price_date": budget_policy().get("price_date", "2026-09-27"),
                 "usage": clean_usage, "usage_complete": event.get("usage_complete") is True,
                 "updated_at": utcnow()}
        with self.store._lock:
            try:
                job = self.store.get(job_id, owner, private=True)
                if job.get("deletion") or self.store._deletion_path(job_id).exists():
                    return
                current = job.get("coaching") or {}
                history = list(job.get("coaching_history") or [])
                record = current if current.get("id") == run_id else next((item for item in history if item.get("id") == run_id), None)
                if record is None:
                    return
                ledger = list(record.get("usage_ledger") or [])
                previous = next((item for item in ledger if item.get("request_id") == request_id), None)
                if previous is None:
                    ledger.append(clean)
                elif previous.get("usage_complete") is not True or clean["usage_complete"]:
                    previous.update(clean)
                record["usage_ledger"] = ledger
                self.store.update(job_id, coaching=current, coaching_history=history)
            except (HTTPException, OSError):
                return

    def _execute(self, job_id: str, owner: str, run_id: str) -> None:
        from core.climb_replay import utcnow
        try:
            with self.store._lock:
                job, record = self._current(job_id, owner, run_id)
                if self._stale_reason(job, record):
                    raise CoachingCancelled()
                path, media = self._media(job, record["media"]["kind"])
                record.update(status="running", started_at=utcnow())
                self.store.update(job_id, coaching=record)
                # A deliberate projection excludes usernames, filenames, storage paths and history.
                public = self.store._public(job)
                inputs = {key: copy.deepcopy(public.get(key)) for key in
                          ("result", "video", "reviewed_segments", "segment_review_history", "route_version_id")}
                inputs["media_manifest"] = copy.deepcopy(media)
            report = self.engine.generate(inputs, path, media["kind"], record["personal"], record["context"],
                                          lambda: self._cancelled(job_id, owner, run_id),
                                          usage_callback=lambda event: self._record_usage(job_id, owner, run_id, event))
            with self.store._lock:
                job, record = self._current(job_id, owner, run_id)
                if self._stale_reason(job, record):
                    raise CoachingCancelled()
                report.setdefault("provenance", {})["cost"] = estimate_ledger_cost(record.get("usage_ledger", []))
                record.update(status="succeeded", report=report, finished_at=utcnow())
                self.store.update(job_id, coaching=record)
        except Exception as exc:
            # Never persist provider exceptions (which can contain headers, prompts or pictures).
            with self.store._lock:
                try:
                    job = self.store.get(job_id, owner, private=True)
                    record = job.get("coaching") or {}
                    if (job.get("deletion") or self.store._deletion_path(job_id).exists()
                            or record.get("id") != run_id or record.get("status") not in ACTIVE):
                        return
                    cancelled = isinstance(exc, CoachingCancelled) or self._withdrawn(job)
                    code = getattr(exc, "code", "generation_failed")
                    messages = {"provider_timeout": "视觉请求超时，费用可能不完整；重试可能追加费用。",
                                "budget_exceeded": "本次预算已用尽，已停止后续请求。",
                                "budget_limit": "本次剩余预算不足，已停止后续请求。",
                                "usage_unknown": "上一步用量尚不明确，已停止后续付费请求。费用可能不完整。",
                                "media_changed": "媒体版本已变化，已停止后续请求，请核对后重新生成。",
                                "media_analysis_boundary_invalid": "视频分析区间与当前动作记录不一致，已停止生成，请先核对媒体版本。",
                                "knowledge_changed": "知识审核依据已变化，已停止后续请求，请重新核对。",
                                "budget_unavailable": "当前模型费用无法估算，已停止后续请求。",
                                "provider_invalid_response": "视觉服务返回内容无法用于报告；已知用量会保留，重试可能追加费用。"}
                    record.update(status="cancelled" if cancelled else "failed", finished_at=utcnow(),
                                  error_code=code if code in messages or code == "cancelled" else "generation_failed",
                                  error="依据发生变化或生成已停止，请检查后重新生成。" if cancelled else
                                  messages.get(code, "报告未生成，请检查视频与视觉服务配置后重试；已发送请求可能产生费用。"))
                    self.store.update(job_id, coaching=record)
                except (HTTPException, OSError):
                    pass

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


def coaching_router(manager: CoachingManager) -> APIRouter:
    from fastapi.routing import APIRoute

    class PrivateReportRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def private_response(request):
                response = await handler(request)
                response.headers["Cache-Control"] = "private, no-store"
                return response

            return private_response

    router = APIRouter(route_class=PrivateReportRoute)

    def owner(request: Request):
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "请先登录")
        return user.username

    @router.get("/coaching-policy")
    def policy(request: Request):
        owner(request)
        return manager.policy()

    @router.post("/jobs/{job_id}/coaching", status_code=202)
    def create(job_id: str, payload: CoachingCreate, request: Request):
        return manager.create(job_id, owner(request), payload)

    @router.get("/jobs/{job_id}/coaching/preflight")
    def preflight(job_id: str, request: Request):
        return manager.preflight(job_id, owner(request))

    @router.get("/jobs/{job_id}/coaching")
    def get(job_id: str, request: Request):
        return manager.get(job_id, owner(request))

    @router.post("/jobs/{job_id}/coaching/cancel")
    def cancel(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request))

    @router.post("/jobs/{job_id}/coaching/consent/withdraw")
    def withdraw(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request), revoke=True)

    @router.post("/jobs/{job_id}/coaching/feedback")
    def feedback(job_id: str, payload: CoachingFeedback, request: Request):
        return manager.feedback(job_id, owner(request), payload)

    return router
