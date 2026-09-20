"""Small file-backed chunk upload sessions for proxy-safe large uploads."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class ChunkUploadError(ValueError):
    pass


class ChunkUploadStore:
    def __init__(self, root: Path, *, chunk_size: int = 8 * 1024 * 1024):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.chunk_size = chunk_size
        self._lock = threading.RLock()

    def _paths(self, upload_id: str) -> tuple[Path, Path]:
        if len(upload_id) != 32 or any(char not in "0123456789abcdef" for char in upload_id):
            raise ChunkUploadError("上传会话不存在")
        return self.root / f"{upload_id}.json", self.root / f"{upload_id}.part"

    def _read(self, upload_id: str, owner: str) -> tuple[dict[str, Any], Path, Path]:
        meta_path, part_path = self._paths(upload_id)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChunkUploadError("上传会话不存在或已过期") from exc
        if meta.get("owner") != owner:
            raise ChunkUploadError("上传会话不存在或已过期")
        return meta, meta_path, part_path

    @staticmethod
    def _write(meta_path: Path, meta: dict[str, Any]) -> None:
        temp = meta_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, meta_path)

    def create(self, owner: str, *, total_size: int, max_size: int, metadata: dict[str, Any]) -> dict[str, Any]:
        if total_size <= 0:
            raise ChunkUploadError("文件内容为空")
        if total_size > max_size:
            raise ChunkUploadError(f"文件不能超过 {max_size // (1024 * 1024)}MB")
        upload_id = uuid.uuid4().hex
        meta_path, part_path = self._paths(upload_id)
        meta = {
            "id": upload_id,
            "owner": owner,
            "total_size": total_size,
            "received": 0,
            "created_at": time.time(),
            "metadata": metadata,
        }
        with self._lock:
            part_path.touch(exist_ok=False)
            self._write(meta_path, meta)
        return {"id": upload_id, "offset": 0, "chunk_size": self.chunk_size}

    def append(self, upload_id: str, owner: str, *, offset: int, data: bytes) -> dict[str, Any]:
        if not data or len(data) > self.chunk_size:
            raise ChunkUploadError("上传分片大小无效")
        with self._lock:
            meta, meta_path, part_path = self._read(upload_id, owner)
            if offset != meta["received"]:
                raise ChunkUploadError(f"上传位置不一致，应从 {meta['received']} 字节继续")
            if offset + len(data) > meta["total_size"]:
                raise ChunkUploadError("上传内容超过声明的文件大小")
            with part_path.open("ab") as stream:
                stream.write(data)
            meta["received"] += len(data)
            self._write(meta_path, meta)
            return {"id": upload_id, "offset": meta["received"], "complete": meta["received"] == meta["total_size"]}

    def finish(self, upload_id: str, owner: str) -> tuple[dict[str, Any], Path]:
        with self._lock:
            meta, _meta_path, part_path = self._read(upload_id, owner)
            if meta["received"] != meta["total_size"] or not part_path.is_file():
                raise ChunkUploadError("文件尚未上传完成")
            return meta, part_path

    def discard(self, upload_id: str) -> None:
        try:
            meta_path, part_path = self._paths(upload_id)
        except ChunkUploadError:
            return
        with self._lock:
            meta_path.unlink(missing_ok=True)
            part_path.unlink(missing_ok=True)
