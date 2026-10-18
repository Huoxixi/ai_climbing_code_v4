"""Owner-scoped action result versions and local exports within existing jobs."""
from copy import deepcopy
from pathlib import Path
import queue
import threading
import time
import uuid
import io
import zipfile
import cv2
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .replay_actions import VERSION, ALGORITHM_VERSION, digest, organize, basic_metrics
from .replay_action_naming import catalogue, enrich_names
from .replay_action_review import revise_result, corrected_contact_evidence
from .replay_action_engine import ActionEngine
from .replay_action_renderer import make_plan, render_actions, validate as validate_action_plan, PRESENTATION_VERSION
from .replay_motion_summary import prepare_motion_evidence, enrich_motion_summary
from .replay_torso_trajectory import enrich_torso_trajectory
from .replay_torso_trajectory import center_of_mass_trajectory
from .replay_important_actions import enrich_important_actions
from .replay_route_usage import enrich_route_usage
from .replay_coaching_cost import estimate_ledger_cost
from .replay_action_features import enrich_action_features
from .replay_commentary import VisionCommentaryEngine, ledger_cost, VERSION as COMMENTARY_VERSION
from .replay_vision_settings import load_settings, public_settings, configuration_fingerprint
from .replay_vision_provider import VisionAPIError
from .replay_analysis_view import visual_evidence
from .replay_event_validation import validate_event_sequence, require_event_sequence
from .replay_full_analysis import validate_input as validate_analysis_input
from .replay_full_analysis import input_mode
from .climb_replay import _atomic_json
import json

ACTIVE = {"queued", "running"}


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud_consent: bool = False
    consent_version: str | None = None
    budget_confirmed: bool = False
    reuse_saved_commentary: bool = False
    retry_saved_response: bool = False
    replace_legacy_return: bool = False
    budget_cny: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)


class ActionExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_version: str
    scope: Literal["full", "group"] = "full"
    group_id: str | None = None
    segment_id: str | None = None
    speed: Literal[0.5, 0.75, 1] = 0.75
    show_skeleton: bool = False
    show_human: bool = True
    show_diagram: bool = True
    include_data: bool = False


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


class TrajectoryStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ActionManager:
    def __init__(self, store, engine=None, renderer=None):
        self.store, self.engine, self.renderer = store, engine or ActionEngine(), renderer or render_actions
        self.injected_engine = engine is not None
        self.queue = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.running = set()
        self.presentation_cache = {}
        self.legacy_vision_returns = {}
        self._background_runs = set()
        self.thread = None
        store.action_manager = self

    def background_binding(self, job):
        from .replay_background import VERSION
        path = self.source(job)
        stat = path.stat()
        return digest({'version': VERSION, 'source': [stat.st_size, stat.st_mtime_ns],
                       'video': job['result'].get('video'),
                       'reference': (job['result'].get('hold_evidence') or {}).get('reference_frame')})

    def background_status(self, job):
        from .replay_background import REASONS
        try:
            binding = self.background_binding(job)
        except (HTTPException, OSError, ValueError):
            return {'status': 'unavailable', 'reason': 'source_missing', 'message': REASONS['source_missing']}
        saved = job.get('replay_background') or {}
        if saved.get('binding') != binding:
            return {'status': 'not_started', 'message': REASONS['not_started']}
        if saved.get('status') == 'running' and (job['id'], binding) not in self._background_runs:
            return {'status': 'not_started', 'message': REASONS['not_started']}
        if saved.get('status') == 'ready' and not (self.store._path(job['id']).parent / saved['storage_name']).is_file():
            return {'status': 'not_started', 'message': REASONS['not_started']}
        return {k: deepcopy(saved[k]) for k in ('status', 'reason', 'message', 'version', 'binding',
            'reference_to_background', 'source_frame_id', 'width', 'height') if k in saved}

    def prepare_background(self, job_id, owner):
        from .replay_background import REASONS
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            source = self.source(job)
            binding = self.background_binding(job)
            if self.background_status(job)['status'] != 'not_started':
                return self.background_status(job)
            self._background_runs.add((job_id, binding))
            self.store.update(job_id, replay_background={'binding': binding, 'status': 'running', 'message': REASONS['running']})
            threading.Thread(target=self._prepare_background, args=(job_id, owner, binding, source, deepcopy(job['result'])),
                             daemon=True, name='replay-background').start()
            return self.background_status(self.store.get(job_id, owner, private=True))

    def _prepare_background(self, job_id, owner, binding, source, result):
        from .replay_background import prepare_background, unavailable
        from .replay_resources import high_resource_slot
        target = self.store._path(job_id).parent / ('empty-scene-' + uuid.uuid4().hex + '.png')
        last_check = 0.
        source_stat = None
        def cancelled(force=False):
            nonlocal last_check
            try:
                if self.stop.is_set() or self.store._deletion_path(job_id).exists():
                    return True
                stat = source.stat()
                if (stat.st_size, stat.st_mtime_ns) != source_stat:
                    return True
                now = time.monotonic()
                if not force and now - last_check < .5:
                    return False
                with self.store._lock:
                    job = self.store.get(job_id, owner, private=True)
                    invalid = self.background_binding(job) != binding or (job.get('replay_background') or {}).get('binding') != binding
                    last_check = now
                    return invalid
            except (HTTPException, OSError, ValueError):
                return True
        try:
            stat = source.stat()
            source_stat = (stat.st_size, stat.st_mtime_ns)
            with high_resource_slot(cancelled=cancelled):
                checksum = self.store._sha256(source)
                status = prepare_background(source, target, result, cancelled=cancelled)
                if cancelled(force=True) or checksum != self.store._sha256(source):
                    raise InterruptedError()
            with self.store._lock:
                if cancelled(force=True):
                    raise InterruptedError()
                self.store.update(job_id, replay_background={**status, 'binding': binding,
                    **({'storage_name': target.name} if status['status'] == 'ready' else {})})
                if status['status'] == 'ready':
                    target = None
        except Exception:
            with self.store._lock:
                if not cancelled(force=True):
                    self.store.update(job_id, replay_background={**unavailable('unverified'), 'binding': binding})
        finally:
            if target is not None:
                target.unlink(missing_ok=True)
            self._background_runs.discard((job_id, binding))

    def background_file(self, job_id, owner, version):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            status = self.background_status(job)
            if status.get('status') != 'ready' or status.get('binding') != version:
                raise HTTPException(409, '无人背景不可用，请刷新记录。')
            return self.store._path(job_id).parent / job['replay_background']['storage_name']

    def export_plan(self, job, result, payload):
        options = {k: payload.get(k, default) for k, default in
                   (('show_skeleton', False), ('show_human', True), ('show_diagram', True))}
        background = None
        if options['show_skeleton'] and not options['show_human']:
            background = self.background_status(job)
            if background.get('status') != 'ready' or background.get('binding') != payload.get('background_version'):
                raise ValueError(background.get('message') or '无人背景已变化，请刷新后导出。')
            background['path'] = str(self.background_file(job['id'], job['owner'], background['binding']))
        return make_plan(result, scope=payload['scope'], group_id=payload.get('group_id'),
            segment_id=payload.get('segment_id'), speed=payload['speed'], summary=False, annotations=False,
            **options, background=background)
        for path in store.jobs.glob("*/job.json"):
            with store._lock:
                try:
                    job = store._read(path.parent.name)
                    legacy = self.legacy_vision_checkpoint(job)
                    if legacy:
                        identity = (job['owner'],self.store._sha256(self.source(job)))
                        self.legacy_vision_returns[identity] = legacy
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

    def fingerprint(self, job, algorithm=ALGORITHM_VERSION):
        source = self.source(job)
        stat = source.stat()
        result = {k: v for k, v in job["result"].items()
                  if k not in {"visual_replay", "visual_reference", "overlay", "visual_review_inputs", "center_of_mass_trajectory"}}
        base = next((job.get("media", {}).get(kind) for kind in ("reviewed_overlay_video", "overlay_video")
                     if job.get("media", {}).get(kind, {}).get("status") == "available"), {})
        return digest({"version": VERSION, "algorithm": algorithm, "result": result, "video": job.get("video"),
                       "base_replay": base.get("checksum_sha256"),
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

    def commentary_checkpoint(self, job):
        checkpoint = job.get('action_commentary_checkpoint') or {}
        if (self.valid(job, checkpoint)
                and checkpoint.get('review_digest') == digest(job.get('action_revisions') or [])):
            return checkpoint
        return {}

    def vision_cache_path(self, job):
        evidence = {k:v for k,v in job['result'].items()
                    if k not in {'visual_replay','visual_reference','overlay','visual_review_inputs','center_of_mass_trajectory'}}
        binding = digest({'video_sha256':self.store._sha256(self.source(job)),
            'analysis_version':[ALGORITHM_VERSION,COMMENTARY_VERSION], 'evidence':evidence,
            'reviews':job.get('action_revisions') or []})
        return self.store.root / 'vision-responses' / digest(job['owner']) / (binding + '.json')

    def legacy_vision_checkpoint(self, job):
        raw = job.get('action_commentary_checkpoint') or {}
        if not raw.get('responses'):
            return {}
        algorithms = {(record.get('result') or {}).get('algorithm_version')
            for record in [job.get('action_result') or {}, *job.get('action_result_history', [])]}
        algorithms.add('source-axis-time-window-local-naming-v8')
        algorithms.add('whole-body-settled-event-timeline-v10')
        for algorithm in algorithms - {None, ALGORITHM_VERSION}:
            try:
                if raw.get('fingerprint') == self.fingerprint(job, algorithm):
                    return {'responses':deepcopy(raw['responses']), 'legacy_saved_return':True,
                            'vision_status':'legacy_return_saved'}
            except (HTTPException, OSError):
                pass
        return {}

    def vision_checkpoint(self, job):
        checkpoint = self.commentary_checkpoint(job)
        try:
            path = self.vision_cache_path(job)
            shared = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            if shared.get('responses') or shared.get('vision_status') == 'succeeded':
                if (shared.get('responses') and shared.get('vision_status')!='succeeded'
                        and not any(r.get('_analysis_version') for r in shared.get('responses',{}).values())
                        and not (shared.get('input',{}).get('commentary_policy') or {}).get('important_only')):
                    # A partially paid old limb-description request cannot be
                    # reshaped into new important-event batches and sent again.
                    return {**shared, 'legacy_saved_return':True, 'vision_status':'legacy_return_saved'}
                return shared
        except (HTTPException, OSError, ValueError):
            pass
        legacy = self.legacy_vision_checkpoint(job)
        if legacy:
            return legacy
        try:
            identity = (job['owner'],self.store._sha256(self.source(job)))
            if identity in self.legacy_vision_returns:
                return self.legacy_vision_returns[identity]
        except (HTTPException, OSError):
            pass
        return checkpoint

    def get(self, job_id, owner):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("action_result") or {}
            valid = self.valid(job, record)
            result = record.get("result") if valid else None
            # Existing analyses must retain their timeline and recap even when
            # no separately prepared action movie was transferred to this host.
            # This is a read-only view: no rendering, cloud calls or job writes.
            if result is None and job.get("status") == "succeeded" and job.get("result"):
                try:
                    # Legacy poses may predate saved wall transforms. Recover
                    # them locally for this read-only view, exactly as preparing
                    # actions does, and reuse the view without writing job data.
                    source = None
                    try:
                        source = self.source(job)
                    except HTTPException:
                        pass
                    stat = source.stat() if source else None
                    cache_key = digest({'job': job_id, 'algorithm': ALGORITHM_VERSION,
                        'result': job['result'], 'video': job.get('video'),
                        'previous_actions': record,
                        'source': [stat.st_size, stat.st_mtime_ns] if stat else None})
                    result = self.presentation_cache.get(cache_key)
                    if result is None:
                        snapshot = deepcopy(job)
                        if source:
                            snapshot['result'] = prepare_motion_evidence(snapshot['result'], source)
                        result = enrich_motion_summary(organize(snapshot))
                        previous = record.get('result') or {}
                        if (source and previous.get('algorithm_version')
                                and record.get('fingerprint') == self.fingerprint(job, previous['algorithm_version'])):
                            # Preserve reviewed labels only when the underlying
                            # evidence is unchanged and their original full time
                            # window fits one new displacement group. Never copy
                            # an old event into two groups or rewrite its times.
                            for old_group in previous.get('groups', []):
                                for event in old_group.get('events', []):
                                    if event.get('motion_origin') == 'pose_trajectory':
                                        continue
                                    target = next((g for g in result['groups']
                                        if g['start_seconds'] <= event.get('start_seconds', -1)
                                        and event.get('end_seconds', float('inf')) <= g['end_seconds']), None)
                                    if target is not None:
                                        target['events'].append(deepcopy(event))
                            corrected = corrected_contact_evidence(previous, snapshot['result'])
                            result['metrics'] = basic_metrics(corrected, result['motion_intervals'])
                            result = enrich_route_usage(enrich_motion_summary(result), corrected)
                        if len(self.presentation_cache) >= 8:
                            self.presentation_cache.pop(next(iter(self.presentation_cache)))
                        self.presentation_cache[cache_key] = result
                except (ValueError, KeyError, TypeError, OSError):
                    result = None
            presentation = enrich_names(result) if result else None
            if presentation and not presentation.get('action_evidence'):
                presentation = enrich_action_features(presentation, job)
            presentation = enrich_motion_summary(presentation) if presentation and not presentation.get('motion_summary') else presentation
            if presentation:
                # Reuse the saved evidence and current contact corrections even
                # for historical results; do not rewrite the stored record.
                evidence = deepcopy(presentation)
                evidence['skeleton_only'] = bool(job.get('skeleton_only') or job['result'].get('skeleton_only'))
                evidence['trajectory_start_seconds'] = job.get('trajectory_start_seconds')
                presentation['skeleton_only'] = evidence['skeleton_only']
                presentation['trajectory_start_seconds'] = evidence['trajectory_start_seconds']
                evidence['attempt'] = corrected_contact_evidence(presentation, job['result']).get('attempt') or {}
                presentation['torso_trajectory'] = enrich_torso_trajectory(evidence)['torso_trajectory']
            if presentation and not presentation.get('route_usage'):
                presentation = enrich_route_usage(presentation, job['result'])
            if presentation:
                if not presentation.get('ai_analysis'):
                    presentation = enrich_important_actions(presentation)
                presentation['event_validation'] = validate_event_sequence(presentation)
                presentation['center_of_mass_trajectory'] = center_of_mass_trajectory(evidence)
            public = {k: deepcopy(presentation[k]) for k in ("schema_version", "algorithm_version", "segmentation_basis", "source_duration_seconds", "time_basis", "groups", "metrics", "route_usage", "motion_summary", "torso_trajectory", "motion_analysis", "naming_version", "relations", "naming_validation", "action_evidence", "priority_focus", "commentary_disclaimer", "commentary_version", "commentary_model", "commentary_status") if k in presentation} if presentation else None
            if public is not None:
                public['event_validation'] = presentation['event_validation']
                public['commentary_policy'] = presentation['commentary_policy']
                public['center_of_mass_trajectory'] = presentation['center_of_mass_trajectory']
                public["holds"] = [{"id": h["id"]} for h in presentation.get("holds", []) if isinstance(h.get("id"), (str, int)) and not isinstance(h.get("id"), bool)]
                public['commentary_segments'] = deepcopy(presentation.get('commentary_segments') or [])
                public['ai_analysis'] = deepcopy(presentation.get('ai_analysis'))
                public['replay_visualization'] = visual_evidence({**presentation,'attempt':evidence.get('attempt') or {}})
                if presentation.get('skeleton_only') or evidence.get('skeleton_only'):
                    from .replay_skeleton_mode import without_hold_data
                    public = without_hold_data(public)
            export = job.get("action_export") or {}
            media = job.get("action_export_media") or {}
            task = deepcopy(job.get("action_task") or {"status": "idle"})
            config = public_settings(load_settings(self.store.root.parent, owner))
            mode = 'frames'
            if config['configured']:
                try:
                    mode = input_mode(config,self.source(job))
                except (HTTPException,OSError):
                    pass
            cost = lambda rows: ledger_cost(rows) if any(r.get('stage') == 'action_commentary' for r in rows) else estimate_ledger_cost(rows)
            checkpoint = self.vision_checkpoint(job)
            if checkpoint.get('legacy_saved_return') and task.get('status') == 'failed':
                task['error'] = '旧视觉返回已保留，原评语的时间结构未通过校验。已禁止再次发送视觉请求；可免费重新整理本地动作。'
            return {"task": task, "background": self.background_status(job), "cost": cost(task.get("usage", [])),
                    "saved_commentary_available": bool(self.commentary_checkpoint(job).get('result')),
                    "saved_response_count": len(checkpoint.get('responses', {})),
                    "vision_status": checkpoint.get('vision_status', 'partial' if checkpoint.get('responses') else 'not_started'),
                    "legacy_saved_vision_return":bool(checkpoint.get('legacy_saved_return')),
                    "vision_request_count":len(checkpoint.get('usage', [])) or len(checkpoint.get('responses', {})),
                    "vision_cost":ledger_cost(checkpoint['usage']) if checkpoint.get('usage') else None,
                    "local_commentary_retry_available":checkpoint.get('vision_status') == 'succeeded' and bool(checkpoint.get('input')),
                    "history_costs": [{"id": r["id"], "status": r["status"], "cost": cost(r.get("usage", []))}
                                      for r in job.get("action_history", []) if r.get("usage")],
                    "result": public, "result_version": record.get("id") if valid else None,
                    "presentation_version": record.get('presentation_version') if valid else None,
                    "stale": bool(record) and not valid, "media_ready": valid and bool(record.get("storage_name")) and record.get('presentation_version') == PRESENTATION_VERSION,
                    "export": deepcopy(export), "export_media": {k: media[k] for k in
                        ("id", "scope", "group_id", "segment_id", "speed", "result_version", "show_skeleton", "show_human", "show_diagram", "include_data") if k in media} if self.valid(job, media) and media.get("result_version") == record.get("id") else None,
                    "revision_count": len(job.get("action_revisions", [])), "vocabulary": catalogue(),
                    "cloud_configured": self.engine.configured if self.injected_engine else config['ready'],
                    "analysis_input_mode": mode,
                    "vision_configured": config['configured'], "pricing_configured": config['pricing_configured'],
                    "cost_control_enabled": config.get('cost_control_enabled', False),
                    "consent_version": VERSION if self.injected_engine else COMMENTARY_VERSION,
                    "budget_cny": config['budget_cny'] if config.get('cost_control_enabled', False) or self.injected_engine else None}

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
                result['priority_focus'] = None
                for field in ('commentary_version', 'commentary_model'):
                    result.pop(field, None)
                result = enrich_action_features(result, {**job, 'result':source})
                if 'route_usage' in result:
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
            if key == 'action_export':
                from .replay_export import PACKAGE_VERSION
                pictures = any(payload[k] for k in ('show_skeleton', 'show_human', 'show_diagram'))
                if not pictures and not payload['include_data']:
                    raise HTTPException(400, '请至少选择一项导出内容。')
                payload['background_version'] = self.background_status(job).get('binding') if payload['show_skeleton'] and not payload['show_human'] else None
                payload['package_version'] = PACKAGE_VERSION
            if key == 'action_task' and payload['retry_saved_response']:
                checkpoint = self.vision_checkpoint(job)
                if payload['cloud_consent'] or checkpoint.get('vision_status') != 'succeeded' or not checkpoint.get('input'):
                    raise HTTPException(409, '没有已完成的视觉返回可供本地重试。')
            if key == 'action_task' and payload['reuse_saved_commentary']:
                if payload['cloud_consent'] or not self.commentary_checkpoint(job).get('result'):
                    raise HTTPException(409, '没有可复用的完整评语，请刷新记录。')
            if key == 'action_task' and payload['cloud_consent'] and not self.injected_engine:
                if payload['consent_version'] != COMMENTARY_VERSION or not payload['budget_confirmed']:
                    raise HTTPException(400, '请单独确认发送动作证据与本次评语费用。')
                presentation = self.get(job_id, owner).get('result') or {}
                try:
                    validate_analysis_input(presentation)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from None
                # Successful vision is immutable. Even the paid endpoint resumes
                # local processing when returns for this evidence already exist.
                checkpoint = self.vision_checkpoint(job)
                if checkpoint.get('legacy_saved_return') and not payload.get('replace_legacy_return'):
                    raise HTTPException(409, '旧视觉返回已保留，已禁止再次发送这条视频。旧评语不能套用到新的动作时间段；可免费重新整理本地动作。')
                if checkpoint.get('vision_status') == 'succeeded' and checkpoint.get('input'):
                    payload['cloud_consent'] = False
                    payload['retry_saved_response'] = True
            if key == 'action_task' and payload['cloud_consent'] and not self.injected_engine:
                if payload['consent_version'] != COMMENTARY_VERSION or not payload['budget_confirmed']:
                    raise HTTPException(400, '请单独确认发送动作证据与本次评语费用。')
                config = load_settings(self.store.root.parent, owner)
                if not public_settings(config)['ready']:
                    raise HTTPException(503, '请先完成视觉服务配置；已启用费用估算时需填写计费参数，或关闭费用估算。')
                payload['configuration'] = configuration_fingerprint(config)
                payload['budget_cny'] = payload.get('budget_cny') or config['budget_cny']
            request_key = digest({"fingerprint": fingerprint, "payload": payload,
                                  "presentation": PRESENTATION_VERSION})
            if current.get("status") in ACTIVE:
                if current.get("request_key") == request_key:
                    return self.get(job_id, owner)
                raise HTTPException(409, "任务正在进行，请先停止")
            if key == "action_task":
                if payload["cloud_consent"]:
                    if payload["consent_version"] != (VERSION if self.injected_engine else COMMENTARY_VERSION) or not payload["budget_confirmed"]:
                        raise HTTPException(400, "请确认动作核对的云端处理和费用")
                    if self.injected_engine and not self.engine.configured:
                        raise HTTPException(503, "尚未配置动作核对服务，可先整理本地片段")
                cached = job.get("action_result") or {}
                if self.valid(job, cached) and cached.get("request_key") == request_key:
                    return self.get(job_id, owner)
            else:
                record = job.get("action_result") or {}
                if not self.valid(job, record) or record.get("id") != payload["result_version"]:
                    raise HTTPException(409, "动作结果已更新，请刷新后导出")
                try:
                    # Data-only requests validate the interval without rendering it.
                    self.export_plan(job, record['result'], payload if pictures else {**payload, 'show_human': True})
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from None
                cached = job.get("action_export_media") or {}
                if self.valid(job, cached) and cached.get("request_key") == request_key:
                    return self.get(job_id, owner)
                if not pictures:
                    run_id = uuid.uuid4().hex
                    self.store.update(job_id, action_export={'id': run_id, 'status': 'succeeded', 'progress': 100,
                        'request_key': request_key, 'fingerprint': fingerprint, 'payload': payload},
                        action_export_media={'id': run_id, 'fingerprint': fingerprint, 'request_key': request_key, **payload})
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
        stage = "preparation"
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
                checkpoint = self.vision_checkpoint(snapshot)
                previous_checkpoint = None
                if record['payload'].get('replace_legacy_return'):
                    if not record['payload']['cloud_consent'] or not checkpoint.get('legacy_saved_return'):
                        raise ValueError('新分析需单独确认发送资料与费用。')
                    previous_checkpoint, checkpoint = checkpoint, {}
                local_retry = record['payload'].get('retry_saved_response')
                if not local_retry:
                    snapshot['result'] = prepare_motion_evidence(snapshot['result'], source, cancelled=lambda: self.cancelled(*args))
                previous_result = snapshot.get('action_result') or {}
                result = (deepcopy(previous_result['result']) if snapshot.get('action_revisions') and self.valid(snapshot, previous_result)
                          else organize(snapshot))
                result['trajectory_start_seconds'] = snapshot.get('trajectory_start_seconds')
                if local_retry:
                    stage = 'commentary'
                    config = {'model':checkpoint.get('model')}
                    result = VisionCommentaryEngine(config).recover(deepcopy(checkpoint['input']),
                        checkpoint['responses'].values(), cancelled=lambda:self.cancelled(*args))
                if record['payload'].get('reuse_saved_commentary'):
                    saved_commentary = self.commentary_checkpoint(snapshot)
                    if not saved_commentary.get('result'):
                        raise ValueError('保存的评语依据已变化')
                    result = deepcopy(saved_commentary['result'])
                elif not local_retry:
                    for field in ('priority_focus','commentary_version','commentary_model','commentary_status'):
                        result.pop(field,None)
                    result = enrich_action_features(result, snapshot)
                    result['center_of_mass_trajectory'] = center_of_mass_trajectory(result)
                # Commentary belongs to page data and does not need a video encoder.
                if record["payload"]["cloud_consent"]:
                    import os
                    if os.getenv('LOCAL_REPLAY_SIMPLE') == '1':
                        raise ValueError('本地版仅生成复盘视频。')
                    stage = "commentary"
                    if self.injected_engine:
                        reviews = self.engine.run(source, snapshot, result,
                            cancelled=lambda: self.cancelled(*args), usage_callback=usage)
                        result = enrich_action_features(organize(snapshot, reviews), snapshot)
                    else:
                        validate_analysis_input(result)
                        config = load_settings(self.store.root.parent, owner)
                        if configuration_fingerprint(config) != record['payload']['configuration']:
                            raise ValueError('视觉服务配置已改变，请重新授权。')
                        config['budget_cny'] = record['payload']['budget_cny']
                        previous = [row for task in snapshot.get('action_history', [])
                            if task.get('fingerprint') == record['fingerprint']
                            for row in task.get('usage', []) if row.get('stage') == 'action_commentary']
                        # Content hash + analysis/evidence version is shared by
                        # duplicate uploads for this owner. Never use file mtime.
                        cache_path = self.vision_cache_path(job)
                        shared = deepcopy(checkpoint)
                        if previous_checkpoint:
                            shared['previous_checkpoint'] = deepcopy(previous_checkpoint)
                        shared['input'] = deepcopy(result)
                        shared.setdefault('model', config['model'])
                        shared.setdefault('responses', {})
                        def persist_vision():
                            _atomic_json(cache_path, shared)
                        def vision_usage(event):
                            with self.store._lock:
                                shared['usage'] = [r for r in shared.get('usage', []) if r['request_id'] != event['request_id']] + [deepcopy(event)]
                                persist_vision()
                            usage(event)
                        def save_response(cache_key, response):
                            with self.store._lock:
                                latest = self.store.get(job_id, owner, private=True)
                                if latest.get('deletion'):
                                    return
                                # A late response still belongs to this evidence;
                                # never replace a checkpoint from a newer attempt.
                                shared['responses'].setdefault(cache_key, deepcopy(response))
                                bill = response.get('_billing')
                                if bill:
                                    shared['usage'] = [r for r in shared.get('usage',[]) if r['request_id'] != bill['request_id']] + [deepcopy(bill)]
                                shared['vision_status'] = 'succeeded' if response.get('_vision_complete') else 'partial'
                                persist_vision()
                                if (latest.get(key) or {}).get('id') != run_id:
                                    return
                                saved = deepcopy(self.commentary_checkpoint(latest))
                                saved.update(fingerprint=record['fingerprint'],
                                    review_digest=digest(snapshot.get('action_revisions') or []))
                                saved.setdefault('responses', {})[cache_key] = response
                                self.store.update(job_id, action_commentary_checkpoint=saved)
                        def complete_vision():
                            with self.store._lock:
                                shared['vision_status'] = 'succeeded'
                                persist_vision()
                        result = VisionCommentaryEngine(config).run(source, snapshot, result,
                            cancelled=lambda: self.cancelled(*args), usage_callback=vision_usage,
                            previous_usage=checkpoint.get('usage', []) or previous,
                            previous_responses=checkpoint.get('responses', {}), response_callback=save_response,
                            vision_complete_callback=complete_vision)
                        with self.store._lock:
                            latest, _ = self.current(*args)
                            saved = deepcopy(self.commentary_checkpoint(latest))
                            saved.update(fingerprint=record['fingerprint'],
                                review_digest=digest(snapshot.get('action_revisions') or []), result=deepcopy(result))
                            self.store.update(job_id, action_commentary_checkpoint=saved)
                result['trajectory_start_seconds'] = snapshot.get('trajectory_start_seconds')
                result = enrich_motion_summary(result)
                result = enrich_route_usage(result, snapshot['result'])
                if local_retry:
                    with self.store._lock:
                        self.store.update(job_id, action_commentary_checkpoint={
                            'fingerprint':record['fingerprint'], 'review_digest':digest(snapshot.get('action_revisions') or []),
                            'result':deepcopy(result)})
                if not self.injected_engine:
                    with self.store._lock:
                        latest, record = self.current(*args)
                        if self.store._sha256(source) != source_hash:
                            raise InterruptedError()
                        saved = {'id':run_id,'fingerprint':record['fingerprint'],
                            'request_key':record['request_key'],'result':result,'presentation_version':PRESENTATION_VERSION}
                        old = latest.get('action_result')
                        if old:
                            self.store.update(job_id, action_result_history=[*latest.get('action_result_history',[]),old])
                        record.update(status='succeeded',progress=100)
                        self.store.update(job_id, action_task=record,action_result=saved)
                    return
                render_source, base_video = source, None
                plan = make_plan(result, speed=1, summary=False, annotations=False, analysis_right=True)
            else:
                result = enrich_names(snapshot["action_result"]["result"])
                result['trajectory_start_seconds'] = snapshot.get('trajectory_start_seconds')
                result['attempt'] = corrected_contact_evidence(result,snapshot['result']).get('attempt') or {}
                result = enrich_torso_trajectory(result)
                if not result.get('motion_summary'):
                    result = enrich_motion_summary(result)
                if not result.get('route_usage'):
                    result = enrich_route_usage(result, snapshot['result'])
                p = record["payload"]
                render_source, base_video = source, None
                plan = self.export_plan(snapshot, result, p)
            target = self.store._path(job_id).parent / f"actions-{run_id}.mp4"
            base_hash = self.store._sha256(render_source)
            stage = "rendering"
            self.renderer(render_source, plan, target, cancelled=lambda: self.cancelled(*args))
            with self.store._lock:
                latest, record = self.current(*args)
                if self.store._sha256(source) != source_hash or self.store._sha256(render_source) != base_hash or not target.is_file():
                    raise InterruptedError()
                media = {"id": run_id, "storage_name": target.name, "fingerprint": record["fingerprint"], "presentation_version": PRESENTATION_VERSION,
                         "request_key": record["request_key"]}
                if key == "action_task":
                    old = latest.get('action_result')
                    if old:
                        self.store.update(job_id, action_result_history=[*latest.get('action_result_history', []), old])
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
                        error = "处理未完成，已有视频保留。可检查服务配置与预算后重试。"
                        if stage == "rendering":
                            returned = any(r.get("stage") == "action_commentary" and r.get("status") == "succeeded" for r in task.get("usage", []))
                            error = ("模型已返回，但动作视频生成失败。已有视频保留，请重试。" if returned
                                     else "动作视频生成失败，已有视频保留，请重试。")
                            if self.commentary_checkpoint(latest).get('result'):
                                error = '模型已返回，评语已保存。点击“恢复已保存评语”可在本地恢复到动作列表，不再调用 AI。'
                        elif stage == 'commentary':
                            saved = self.vision_checkpoint(latest)
                            error = ('AI 返回已保存，但分析内容未能恢复。点击“恢复分析”不会再次收费。'
                                if saved.get('vision_status') == 'succeeded' else
                                'AI 分析未完成，已有复盘已保留。')
                            if isinstance(exc, (VisionAPIError, ValueError)) and not isinstance(exc, json.JSONDecodeError):
                                error = str(exc)
                        task['failed_stage'] = ('commentary' if self.vision_checkpoint(latest).get('vision_status') == 'succeeded'
                            else 'vision') if stage == 'commentary' else stage
                        task.update(status="cancelled" if isinstance(exc, InterruptedError) else "failed", error=error)
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

    def export_package(self, job_id, owner, version, exported=False, data_only=False, export_id=None):
        """Build an offline bundle containing the replay and its evidence contract."""
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            record = job.get("action_result") or {}
            if not self.valid(job, record) or record.get("id") != version:
                raise HTTPException(409, "动作结果已更新，请刷新后导出")
            media = job.get("action_export_media") or {}
            if exported and export_id is not None and media.get('id') != export_id:
                raise HTTPException(409, '导出组合已变化，请重新导出。')
            if exported and (not self.valid(job, media) or media.get("result_version") != version):
                raise HTTPException(409, "导出视频版本已变化，请重新生成")
            video_name = media.get("storage_name") if exported else record.get("storage_name")
            video_path = self.store._path(job_id).parent / (video_name or "")
            if not data_only and (not isinstance(video_name, str) or Path(video_name).name != video_name or not video_path.is_file()):
                raise HTTPException(404, "复盘视频不可用")
            result = record.get("result") or {}
            from .replay_action_renderer import make_plan
            plan = self.export_plan(job, result, media) if exported and not data_only else (
                make_plan(result, speed=1, analysis_right=True) if not data_only else None)
            mapping = ({'scope':plan['scope'], 'speed':plan['speed'],
                'source_start_seconds':plan['source_start_frame']/plan['fps'],
                'source_stop_seconds':plan['source_stop_frame']/plan['fps'],
                'show_skeleton':plan['show_skeleton'], 'show_human':plan['show_human'], 'show_diagram':plan['show_diagram'],
                'formula':'analysis_time_seconds = source_start_seconds + replay_time_seconds * speed'}
                if plan else None)
            result = deepcopy(result)
            result['trajectory_start_seconds'] = job.get('trajectory_start_seconds')
            result['center_of_mass_trajectory'] = center_of_mass_trajectory(result)
        from .replay_export import build_bundle
        return build_bundle(result, mapping=mapping, video_path=None if data_only else video_path,
                            source_path=None, vision=None)

    def set_trajectory_start(self, job_id, owner, payload):
        with self.store._lock:
            job = self.store.get(job_id, owner, private=True)
            self.source(job)
            if not (job.get('skeleton_only') or job['result'].get('skeleton_only')):
                raise HTTPException(409, '有岩点的复盘沿用岩点起点')
            if any((job.get(key) or {}).get('status') in ACTIVE for key in ('action_task', 'action_export')):
                raise HTTPException(409, '请等待当前处理完成后再调整起点')
            duration = (job['result'].get('video') or {}).get('duration_seconds', 0)
            start = payload.start_seconds
            if start is not None and start >= duration:
                raise HTTPException(422, '请选择视频结束之前的起点')
            changes = {'trajectory_start_seconds': start, 'action_export_media': None}
            record = job.get('action_result') or {}
            if self.valid(job, record):
                updated = deepcopy(record)
                updated['id'] = uuid.uuid4().hex
                updated['result']['trajectory_start_seconds'] = start
                updated['result']['skeleton_only'] = True
                updated['result'] = enrich_torso_trajectory(updated['result'])
                changes['action_result'] = updated
                changes['action_result_history'] = [*job.get('action_result_history', []), record]
            self.store.update(job_id, **changes)
        return self.get(job_id, owner)

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

    @router.post('/jobs/{job_id}/actions/background', status_code=202)
    def prepare_background(job_id: str, request: Request):
        return manager.prepare_background(job_id, owner(request))

    @router.get('/jobs/{job_id}/actions/background')
    def background(job_id: str, version: str, request: Request):
        return FileResponse(manager.background_file(job_id, owner(request), version), media_type='image/png',
                            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.post("/jobs/{job_id}/actions", status_code=202)
    def create(job_id: str, payload: ActionCreate, request: Request):
        return manager.enqueue(job_id, owner(request), "action_task", payload)

    @router.post("/jobs/{job_id}/actions/cancel")
    def cancel(job_id: str, request: Request):
        return manager.cancel(job_id, owner(request), "action_task")

    @router.put('/jobs/{job_id}/actions/trajectory-start')
    def trajectory_start(job_id: str, payload: TrajectoryStart, request: Request):
        return manager.set_trajectory_start(job_id, owner(request), payload)

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

    @router.get("/jobs/{job_id}/actions/package")
    def package(job_id: str, version: str, request: Request, exported: bool = False, data_only: bool = False, export_id: str | None = None):
        stream = manager.export_package(job_id, owner(request), version, exported, data_only, export_id)
        def chunks():
            try:
                while chunk := stream.read(1024 * 1024):
                    yield chunk
            finally:
                stream.close()
        return StreamingResponse(chunks(), media_type="application/zip",
            headers={"Content-Disposition":"attachment; filename=climb-replay-package.zip",
                     "Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"})
    return router
