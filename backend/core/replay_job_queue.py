"""Bounded replay admission, durable refill and single-worker dispatch.

The application initializes queue/lock/thread fields and owns job execution and
safe failure policy. This module does not initialize services or resource slots.
"""
from __future__ import annotations

import json
import queue

from fastapi import HTTPException


class ReplayJobQueue:
    """Schedule jobs using the owning manager's existing queue and stop signal."""

    def enqueue(self, job_id: str) -> None:
        self._enqueue("analysis", job_id)

    def enqueue_delete(self, job_id: str) -> None:
        self._enqueue("delete", job_id)

    def enqueue_visual(self, job_id: str) -> None:
        self._enqueue("visual", job_id)

    def _enqueue(self, action: str, job_id: str) -> None:
        item = (action, job_id)
        with self._queue_lock:
            if item not in self._queued:
                self._queued.add(item)
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    # Durable job records remain the bounded recovery source.
                    self._queued.discard(item)

    def ensure_capacity(self) -> None:
        pending = 0
        for path in self.store.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("status") in {"queued", "running"} or (item.get("result") or {}).get("visual_replay", {}).get("status") in {"queued", "running"}:
                pending += 1
        if pending >= 8:
            raise HTTPException(429, "复盘处理队列已满，请稍后再试")

    def _refill_queue(self) -> None:
        candidates = [("delete", job_id) for job_id in self.store.pending_deletions()]
        candidates.extend(("analysis", job_id) for job_id in self.store.queued())
        for path in self.store.jobs.glob("*/job.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (item.get("result") or {}).get("visual_replay", {}).get("status") == "queued":
                candidates.append(("visual", item["id"]))
        for action, job_id in candidates:
            if self._queue.full():
                break
            self._enqueue(action, job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            with self._queue_lock:
                self._queued.discard(item)
            action, job_id = item
            try:
                if action == "delete":
                    self.store.process_delete(job_id)
                elif action == "visual":
                    self._execute_visual(job_id)
                else:
                    self._execute(job_id)
            except Exception as exc:
                self._handle_worker_failure(action, job_id, exc)
            finally:
                self._queue.task_done()
                self._refill_queue()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self._cleanup_interval_seconds):
            try:
                self.store.cleanup_due_media()
            except Exception:
                # One malformed legacy record must not stop future cleanup passes.
                continue
