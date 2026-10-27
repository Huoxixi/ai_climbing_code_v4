"""File-backed replay records and owner-scoped public snapshot caching.

The application initializes paths, locks and cache fields. Its public projection
and two policy hooks keep domain decisions outside this persistence boundary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import HTTPException


class ReplayJobRecords:
    """Read and update records using the owning store's lock and policies."""

    def _path(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise HTTPException(404, "未找到复盘任务")
        return self.jobs / job_id / "job.json"

    def _deletion_path(self, job_id: str) -> Path:
        if not job_id or not job_id.isalnum():
            raise HTTPException(404, "未找到删除任务")
        return self.deletions / f"{job_id}.json"

    def _read(self, job_id: str) -> dict:
        path = self._path(job_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(404, "未找到复盘任务")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def get(self, job_id: str, owner: str | None = None, *, private=False) -> dict:
        with self._lock:
            if not private:
                return self._cached_public(job_id, owner)
            job = self._read(job_id)
        if owner is not None and job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        return job if private else self._public(job)

    def _cached_public(self, job_id: str, owner: str | None) -> dict:
        """Called under the store lock; atomic replacements invalidate snapshots."""
        path = self._path(job_id)
        def fingerprint():
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino,
                    self._public_cache_context())
        try:
            version = fingerprint()
        except OSError:
            previous = self._public_cache.pop(job_id, None)
            if previous:
                self._public_cache_bytes -= len(previous[2])
            raise HTTPException(404, "未找到复盘任务")
        cached = self._public_cache.get(job_id)
        if cached and cached[0] == version:
            if owner is not None and cached[1] != owner:
                raise HTTPException(404, "未找到复盘任务")
            self._public_cache.move_to_end(job_id)
            return json.loads(cached[2])
        job = self._read(job_id)
        if owner is not None and job.get("owner") != owner:
            raise HTTPException(404, "未找到复盘任务")
        public = self._public(job)
        encoded = json.dumps(public, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        previous = self._public_cache.pop(job_id, None)
        if previous:
            self._public_cache_bytes -= len(previous[2])
        try:
            unchanged = fingerprint() == version
        except OSError:
            unchanged = False
        if unchanged and len(encoded) <= self._public_cache_limit:
            self._public_cache[job_id] = (version, job.get("owner"), encoded)
            self._public_cache_bytes += len(encoded)
            while (self._public_cache_bytes > self._public_cache_limit
                   or len(self._public_cache) > self._public_cache_entries):
                _, removed = self._public_cache.popitem(last=False)
                self._public_cache_bytes -= len(removed[2])
        return public

    def list(self, owner: str) -> list[dict]:
        found = []
        for path in self.jobs.glob("*/job.json"):
            try:
                job = self.get(path.parent.name, owner)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                continue
            if job.get("owner") == owner:
                found.append(job)
        return sorted(found, key=lambda item: item["created_at"], reverse=True)

    def update(self, job_id: str, **changes) -> dict:
        with self._lock:
            job = self._read(job_id)
            job.update(changes)
            self._commit_record(job_id, job)
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
