"""SQLite persistence, background jobs and HTTP contracts for photo-route V2."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.photo_route_analysis import (BOARD_HEIGHT_MM, BOARD_WIDTH_MM, analyze_board_photo,
                                       assess_capture_quality, board_holes, compute_homography,
                                       fingerprint_payload, map_point, nearest_hole, mobilesam_paths)
from core.photo_route_processing import PhotoProcessingError, decode_photo
from core.photo_wall_processing import restore_wall


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ColorRefinement(BaseModel):
    expected_version: int = Field(ge=1)
    color_group: str = Field(min_length=1, max_length=40)
    seed: tuple[float, float]

    @model_validator(mode="after")
    def valid_seed(self):
        if not all(np.isfinite(value) and 0 <= value <= 1 for value in self.seed):
            raise ValueError("请在照片内选择颜色清晰的岩点")
        return self


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CalibrationUpdate(Contract):
    photo_points: list[tuple[float, float]] = Field(min_length=4, max_length=40)
    board_hole_ids: list[str] = Field(min_length=4, max_length=40)

    @model_validator(mode="after")
    def paired(self):
        if len(self.photo_points) != len(self.board_hole_ids):
            raise ValueError("照片点和孔位必须一一对应")
        if len(set(self.board_hole_ids)) != len(self.board_hole_ids):
            raise ValueError("同一孔位不能重复参与标定")
        return self


class AnchorInput(Contract):
    hole_id: str = Field(pattern=r"^(?:[A-Z]|A[A-D])(?:[1-9]|1[0-9]|20)$")
    confidence: float = Field(ge=0, le=1, default=1)
    confirmed: bool = True


class ObjectPatch(Contract):
    expected_version: int = Field(ge=1)
    kind: Literal["hold", "volume"] | None = None
    color_group: str | None = Field(default=None, min_length=1, max_length=40)
    contour: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=2000)
    center_x_mm: float | None = Field(default=None, ge=0, le=BOARD_WIDTH_MM)
    center_y_mm: float | None = Field(default=None, ge=0, le=BOARD_HEIGHT_MM)
    rotation_deg: float | None = Field(default=None, ge=-360, le=360)
    scale_mm_per_px: float | None = Field(default=None, gt=0, le=100)
    review_status: Literal["needs_review", "confirmed", "rejected"] | None = None
    anchors: list[AnchorInput] | None = Field(default=None, max_length=12)


class ObjectCreate(Contract):
    expected_version: int = Field(ge=1)
    kind: Literal["hold", "volume"] = "hold"
    color_group: str = Field(min_length=1, max_length=40)
    contour: list[tuple[float, float]] = Field(min_length=3, max_length=2000)


class MergeObjects(Contract):
    expected_version: int = Field(ge=1)
    object_ids: list[str] = Field(min_length=2, max_length=20)


class SplitObject(Contract):
    expected_version: int = Field(ge=1)
    contours: list[list[tuple[float, float]]] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def valid_contours(self):
        if any(len(contour) < 3 or len(contour) > 2000 for contour in self.contours):
            raise ValueError("每个拆分轮廓至少需要 3 个点")
        return self


class ColorRouteCreate(Contract):
    board_version_id: str
    color_group: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=120)


class RouteMemberInput(Contract):
    object_id: str
    roles: list[Literal["start", "end"]] = Field(default_factory=list, max_length=2)
    tags: list[Literal["动态", "静态", "匹配", "交叉", "换手", "休息", "核心动作", "安全提醒"]] = Field(default_factory=list)
    note: str = Field(default="", max_length=2000)


class RouteUpdate(Contract):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    difficulty: str = Field(default="", max_length=40)
    setter: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=4000)
    members: list[RouteMemberInput] = Field(min_length=1, max_length=600)


class CleanupRequest(Contract):
    removal_polygons: list[list[tuple[float, float]]] = Field(default_factory=list, max_length=200)
    preserve_polygons: list[list[tuple[float, float]]] = Field(default_factory=list, max_length=200)
    method: Literal["opencv", "lama"] = "opencv"


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS board_versions(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_key TEXT NOT NULL, board_version_no INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL,
 status TEXT NOT NULL, original_asset TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 quality_json TEXT NOT NULL, calibration_json TEXT, model_version TEXT, input_fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
 UNIQUE(owner, board_key, board_version_no));
CREATE INDEX IF NOT EXISTS idx_boards_owner ON board_versions(owner, updated_at DESC);
CREATE TABLE IF NOT EXISTS board_objects(
 id TEXT PRIMARY KEY, board_version_id TEXT NOT NULL REFERENCES board_versions(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, color_group TEXT NOT NULL, contour_json TEXT NOT NULL, bbox_json TEXT NOT NULL,
 cutout_asset TEXT, mask_asset TEXT, center_x_mm REAL NOT NULL, center_y_mm REAL NOT NULL,
 rotation_deg REAL NOT NULL DEFAULT 0, scale_mm_per_px REAL NOT NULL, confidence REAL NOT NULL,
 review_status TEXT NOT NULL, object_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_objects_board_color ON board_objects(board_version_id, color_group);
CREATE TABLE IF NOT EXISTS object_anchors(
 id TEXT PRIMARY KEY, object_id TEXT NOT NULL REFERENCES board_objects(id) ON DELETE CASCADE,
 hole_id TEXT NOT NULL, x_mm REAL NOT NULL, y_mm REAL NOT NULL, confidence REAL NOT NULL,
 confirmed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(object_id, hole_id));
CREATE TABLE IF NOT EXISTS processing_jobs(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_version_id TEXT REFERENCES board_versions(id) ON DELETE CASCADE,
 route_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
 error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, attempt INTEGER NOT NULL DEFAULT 1,
 model_version TEXT, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS routes(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_version_id TEXT NOT NULL REFERENCES board_versions(id),
 name TEXT NOT NULL, color_group TEXT NOT NULL, difficulty TEXT NOT NULL DEFAULT '', setter TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT);
CREATE INDEX IF NOT EXISTS idx_routes_library ON routes(owner, board_version_id, color_group, status, updated_at DESC);
CREATE TABLE IF NOT EXISTS route_members(
 route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
 object_id TEXT NOT NULL REFERENCES board_objects(id), roles_json TEXT NOT NULL DEFAULT '[]',
 tags_json TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '', ordinal INTEGER NOT NULL,
 PRIMARY KEY(route_id, object_id));
CREATE TABLE IF NOT EXISTS route_revisions(
 id TEXT PRIMARY KEY, route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(route_id, version));
CREATE TABLE IF NOT EXISTS background_variants(
 id TEXT PRIMARY KEY, route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
 route_version INTEGER NOT NULL, original_fingerprint TEXT NOT NULL, member_fingerprint TEXT NOT NULL,
 removal_mask_asset TEXT NOT NULL, preserve_mask_asset TEXT, background_asset TEXT NOT NULL,
 composite_asset TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class PhotoRouteV2Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.assets = self.root / "assets"
        self.db_path = self.root / "photo_routes_v2.sqlite3"
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)", (utcnow(),))
            columns = {row[1] for row in db.execute("PRAGMA table_info(board_versions)")}
            if "board_version_no" not in columns:
                db.execute("ALTER TABLE board_versions ADD COLUMN board_version_no INTEGER NOT NULL DEFAULT 1")
            table_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='board_versions'").fetchone()[0]
            if "UNIQUE(owner, board_key, version)" in table_sql:
                self._rebuild_board_versions_v3(db)
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(3, ?)", (utcnow(),))
        self.recover_interrupted_jobs()
        self.import_legacy_drafts()

    def _rebuild_board_versions_v3(self, db: sqlite3.Connection):
        """Replace the short-lived V2 preview constraint without losing rows."""
        db.execute("PRAGMA foreign_keys=OFF"); db.execute("PRAGMA legacy_alter_table=ON")
        db.executescript("""
        ALTER TABLE board_versions RENAME TO board_versions_v2_preview;
        CREATE TABLE board_versions(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_key TEXT NOT NULL,
          board_version_no INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL,
          status TEXT NOT NULL, original_asset TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
          quality_json TEXT NOT NULL, calibration_json TEXT, model_version TEXT, input_fingerprint TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
          UNIQUE(owner, board_key, board_version_no));
        INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,
          quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at)
        SELECT id,owner,board_key,board_version_no,version,status,original_asset,width,height,
          quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at
        FROM board_versions_v2_preview;
        DROP TABLE board_versions_v2_preview;
        CREATE INDEX IF NOT EXISTS idx_boards_owner ON board_versions(owner, updated_at DESC);
        """)
        db.execute("PRAGMA legacy_alter_table=OFF"); db.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _load(value: str | None, default=None):
        return json.loads(value) if value else default

    def save_asset(self, data: bytes, suffix: str, width: int, height: int) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        suffix = suffix.lower().lstrip(".")
        if suffix == "jpeg": suffix = "jpg"
        filename = f"{digest}.{suffix}"
        target = self.assets / filename
        with self._lock:
            if not target.exists():
                temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                temp.write_bytes(data)
                os.replace(temp, target)
        return {"filename": filename, "sha256": digest, "width": width, "height": height}

    def asset_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or not filename.split(".")[0].isalnum():
            raise HTTPException(404, "素材不存在")
        path = (self.assets / filename).resolve()
        if not path.is_relative_to(self.assets) or not path.is_file():
            raise HTTPException(404, "素材不存在")
        if hashlib.sha256(path.read_bytes()).hexdigest() != filename.split(".")[0]:
            raise HTTPException(422, "素材指纹校验失败")
        return path

    def create_upload(self, owner: str, filename: str, data: bytes) -> tuple[dict, dict]:
        try:
            image = decode_photo(data)
        except PhotoProcessingError as exc:
            raise HTTPException(422, str(exc)) from exc
        quality = assess_capture_quality(image)
        if not quality.accepted:
            raise HTTPException(422, {"message": "照片未通过上传检查", "issues": quality.issues,
                                      "metrics": quality.metrics})
        suffix = (Path(filename).suffix or ".jpg").lower().lstrip(".")
        if suffix not in {"jpg", "jpeg", "png", "webp"}: suffix = "jpg"
        asset = self.save_asset(data, suffix, image.shape[1], image.shape[0])
        board_id, job_id, now = uuid.uuid4().hex, uuid.uuid4().hex, utcnow()
        board_key = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                       (board_id, owner, board_key, 1, 1, "processing", self._json(asset), image.shape[1], image.shape[0],
                        self._json({"accepted": True, "issues": [], "metrics": quality.metrics}), None, None,
                        asset["sha256"], now, now))
            db.execute("INSERT INTO processing_jobs(id,owner,board_version_id,kind,status,stage,progress,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (job_id, owner, board_id, "recognition", "queued", "等待识别", 0, "{}", now, now))
        return self.get_board(board_id, owner), self.get_job(job_id, owner)

    def _row_board(self, db: sqlite3.Connection, row: sqlite3.Row, include_objects=True) -> dict:
        result = dict(row)
        result["original_asset"] = self._load(result["original_asset"])
        result["quality"] = self._load(result.pop("quality_json"), {})
        result["calibration"] = self._load(result.pop("calibration_json"), None)
        # Include the last recognition job so an interrupted upload can resume.
        job = db.execute("SELECT id,kind,status,stage,progress,error,board_version_id,route_id FROM processing_jobs WHERE board_version_id=? AND kind='recognition' ORDER BY created_at DESC LIMIT 1", (row["id"],)).fetchone()
        result["latest_job"] = dict(job) if job else None
        if include_objects:
            objects = db.execute("SELECT * FROM board_objects WHERE board_version_id=? AND review_status!='rejected' ORDER BY created_at,id", (row["id"],)).fetchall()
            result["objects"] = [self._row_object(db, item) for item in objects]
        return result

    def _row_object(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict:
        result = dict(row)
        for source, target, default in (("contour_json", "contour", []), ("bbox_json", "source_bbox_px", []),
                                        ("cutout_asset", "cutout", None), ("mask_asset", "mask", None)):
            result[target] = self._load(result.pop(source), default)
        result["anchors"] = [dict(item) | {"confirmed": bool(item["confirmed"])} for item in
                             db.execute("SELECT id,hole_id,x_mm,y_mm,confidence,confirmed FROM object_anchors WHERE object_id=? ORDER BY hole_id", (row["id"],))]
        return result

    def list_boards(self, owner: str, include_archived=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM board_versions WHERE owner=? AND (? OR archived_at IS NULL) ORDER BY updated_at DESC",
                              (owner, int(include_archived))).fetchall()
            return [self._row_board(db, row, False) for row in rows]

    def get_board(self, board_id: str, owner: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM board_versions WHERE id=? AND owner=?", (board_id, owner)).fetchone()
            if not row: raise HTTPException(404, "未找到岩板版本")
            return self._row_board(db, row)

    def set_analysis_result(self, board_id: str, result: dict) -> None:
        now = utcnow()
        with self.transaction() as db:
            board = db.execute("SELECT status,quality_json FROM board_versions WHERE id=?", (board_id,)).fetchone()
            if not board or board["status"] != "processing": return
            quality = json.loads(board['quality_json'])
            if 'processing_config' in result:
                quality['processing_config'] = result['processing_config']
            db.execute("UPDATE board_versions SET status=?,calibration_json=?,model_version=?,quality_json=?,updated_at=? WHERE id=?",
                       ("review", self._json(result["calibration"]), result["model_version"], self._json(quality), now, board_id))
            for item in result["objects"]:
                object_id = f"{board_id[:8]}-{item['id']}"
                db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?)",
                    (object_id, board_id, item["kind"], item["color_group"], self._json(item["contour"]),
                     self._json(item["source_bbox_px"]), self._json(item["cutout"]), self._json(item["mask"]),
                     item["center_x_mm"], item["center_y_mm"], item["rotation_deg"], item["scale_mm_per_px"],
                     item["confidence"], item["review_status"], 1, now, now))
                for anchor in item["anchors"]:
                    db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, object_id, anchor["hole_id"], anchor["x_mm"], anchor["y_mm"],
                                anchor["confidence"], int(anchor["confirmed"]), now))

    def create_color_refinement(self, board_id: str, owner: str, payload: ColorRefinement):
        source = self.get_board(board_id, owner)
        try: mobilesam_paths()
        except PhotoProcessingError as exc: raise HTTPException(503, str(exc)) from exc
        new_id, job_id, now = uuid.uuid4().hex, uuid.uuid4().hex, utcnow()
        with self.transaction() as db:
            current = db.execute("SELECT version,status FROM board_versions WHERE id=? AND owner=?", (board_id, owner)).fetchone()
            if current["version"] != payload.expected_version: raise HTTPException(409, "岩板版本已变化，请重新打开后精修")
            if current["status"] not in {"review", "ready"}: raise HTTPException(409, "请等待初识别完成后再精修")
            if not any(item["color_group"] == payload.color_group for item in source["objects"]):
                raise HTTPException(422, "请先选择当前岩板中的颜色")
            number = db.execute("SELECT COALESCE(MAX(board_version_no),0)+1 FROM board_versions WHERE owner=? AND board_key=?", (owner, source["board_key"])).fetchone()[0]
            db.execute("INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (new_id, owner, source["board_key"], number, 1, "processing", self._json(source["original_asset"]), source["width"], source["height"], self._json(source["quality"]), self._json(source["calibration"]), None, source["input_fingerprint"], now, now))
            # Snapshot other colours so later edits to the original never alter
            # the queued refinement. No existing objects or routes are replaced.
            job_payload = {"seed": payload.seed, "color_group": payload.color_group,
                "calibration": source["calibration"], "preserved_objects": [item for item in source["objects"] if item["color_group"] != payload.color_group]}
            db.execute("INSERT INTO processing_jobs(id,owner,board_version_id,kind,status,stage,progress,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (job_id, owner, new_id, "recognition", "queued", "等待按颜色精修", 0, self._json(job_payload), now, now))
        return {"board": self.get_board(new_id, owner), "job": self.get_job(job_id, owner)}

    def create_job(self, owner: str, kind: str, *, board_id: str | None = None,
                   route_id: str | None = None, payload: dict | None = None) -> dict:
        job_id, now = uuid.uuid4().hex, utcnow()
        with self.transaction() as db:
            db.execute("INSERT INTO processing_jobs(id,owner,board_version_id,route_id,kind,status,stage,progress,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (job_id, owner, board_id, route_id, kind, "queued", "等待处理", 0,
                        self._json(payload or {}), now, now))
        return self.get_job(job_id, owner)

    def get_job(self, job_id: str, owner: str | None = None) -> dict:
        with self.connect() as db:
            sql, params = "SELECT * FROM processing_jobs WHERE id=?", [job_id]
            if owner is not None: sql += " AND owner=?"; params.append(owner)
            row = db.execute(sql, params).fetchone()
            if not row: raise HTTPException(404, "未找到处理任务")
            result = dict(row); result["payload"] = self._load(result.pop("payload_json"), {})
            result["cancel_requested"] = bool(result["cancel_requested"])
            return result

    def queued_jobs(self) -> list[str]:
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM processing_jobs WHERE status='queued' ORDER BY created_at")]

    def mark_job(self, job_id: str, status: str, stage: str, progress: int, error: str | None = None):
        now = utcnow()
        with self.transaction() as db:
            extra = ",started_at=COALESCE(started_at,?)" if status == "running" else ",finished_at=?" if status in {"succeeded", "failed", "cancelled"} else ""
            params: list[Any] = [status, stage, progress, error, now]
            if extra: params.append(now)
            params.append(job_id)
            db.execute(f"UPDATE processing_jobs SET status=?,stage=?,progress=?,error=?,updated_at=?{extra} WHERE id=?", params)

    def cancel_job(self, job_id: str, owner: str) -> dict:
        self.get_job(job_id, owner)
        with self.transaction() as db:
            db.execute("UPDATE processing_jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,stage='正在取消',updated_at=? WHERE id=?",
                       (utcnow(), job_id))
        return self.get_job(job_id, owner)

    def retry_job(self, job_id: str, owner: str) -> dict:
        old = self.get_job(job_id, owner)
        if old["status"] not in {"failed", "cancelled"}: raise HTTPException(409, "只有失败或已取消任务可以重试")
        with self.transaction() as db:
            if old["kind"] == "recognition":
                db.execute("DELETE FROM object_anchors WHERE object_id IN (SELECT id FROM board_objects WHERE board_version_id=?)", (old["board_version_id"],))
                db.execute("DELETE FROM board_objects WHERE board_version_id=?", (old["board_version_id"],))
                db.execute("UPDATE board_versions SET status='processing',updated_at=? WHERE id=?", (utcnow(), old["board_version_id"]))
            db.execute("UPDATE processing_jobs SET status='queued',stage='等待重试',progress=0,error=NULL,cancel_requested=0,attempt=attempt+1,started_at=NULL,finished_at=NULL,updated_at=? WHERE id=?",
                       (utcnow(), job_id))
        return self.get_job(job_id, owner)

    def recover_interrupted_jobs(self):
        with self.transaction() as db:
            db.execute("UPDATE processing_jobs SET status='failed',stage='服务重启后已停止',error='本机服务在任务执行期间重启，请重试',finished_at=?,updated_at=? WHERE status='running'", (utcnow(), utcnow()))

    def update_calibration(self, board_id: str, owner: str, payload: CalibrationUpdate):
        board = self.get_board(board_id, owner)
        lookup = {item["id"]: item for item in board_holes()}
        try: targets = [[lookup[item]["x_mm"], lookup[item]["y_mm"]] for item in payload.board_hole_ids]
        except KeyError as exc: raise HTTPException(422, f"未知孔位：{exc.args[0]}") from exc
        matrix = compute_homography([list(p) for p in payload.photo_points], targets)
        with self.transaction() as db:
            objects = db.execute("SELECT id,bbox_json FROM board_objects WHERE board_version_id=?", (board_id,)).fetchall()
            for obj in objects:
                x, y, width, height = self._load(obj["bbox_json"])
                bx, by = map_point(matrix, x + width / 2, y + height / 2)
                db.execute("UPDATE board_objects SET center_x_mm=?,center_y_mm=?,review_status='needs_review',object_version=object_version+1,updated_at=? WHERE id=?",
                           (max(0, min(BOARD_WIDTH_MM, bx)), max(0, min(BOARD_HEIGHT_MM, by)), utcnow(), obj["id"]))
            calibration = {"matrix": matrix, "method": "user-confirmed-hybrid", "status": "confirmed",
                           "photo_points": payload.photo_points, "board_hole_ids": payload.board_hole_ids,
                           "confidence": 1.0}
            db.execute("UPDATE board_versions SET calibration_json=?,status='review',version=version+1,updated_at=? WHERE id=?",
                       (self._json(calibration), utcnow(), board_id))
        return self.get_board(board_id, owner)

    def patch_object(self, board_id: str, object_id: str, owner: str, payload: ObjectPatch):
        self.get_board(board_id, owner)
        values = payload.model_dump(exclude_none=True, exclude={"expected_version", "anchors"})
        with self.transaction() as db:
            row = db.execute("SELECT * FROM board_objects WHERE id=? AND board_version_id=?", (object_id, board_id)).fetchone()
            if not row: raise HTTPException(404, "未找到对象")
            if row["object_version"] != payload.expected_version: raise HTTPException(409, "对象已有新版本")
            columns, params = [], []
            for key, value in values.items():
                column = "contour_json" if key == "contour" else key
                columns.append(f"{column}=?"); params.append(self._json(value) if key == "contour" else value)
            if columns:
                db.execute(f"UPDATE board_objects SET {','.join(columns)},object_version=object_version+1,updated_at=? WHERE id=?",
                           (*params, utcnow(), object_id))
            if payload.anchors is not None:
                lookup = {item["id"]: item for item in board_holes()}
                db.execute("DELETE FROM object_anchors WHERE object_id=?", (object_id,))
                for anchor in payload.anchors:
                    hole = lookup[anchor.hole_id]
                    db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, object_id, hole["id"], hole["x_mm"], hole["y_mm"],
                                anchor.confidence, int(anchor.confirmed), utcnow()))
            db.execute("UPDATE board_versions SET version=version+1,updated_at=? WHERE id=?", (utcnow(), board_id))
        return self.get_board(board_id, owner)

    def add_object(self, board_id: str, owner: str, payload: ObjectCreate):
        board = self.get_board(board_id, owner)
        if board["version"] != payload.expected_version: raise HTTPException(409, "岩板已有新版本")
        x, y, right, bottom, cutout, mask = self._render_contour_assets(board, payload.contour)
        matrix = (board.get("calibration") or {}).get("matrix")
        if not matrix: raise HTTPException(422, "请先完成岩板标定")
        cx, cy = map_point(matrix, (x + right) / 2, (y + bottom) / 2)
        hole, distance = nearest_hole(cx, cy); now, object_id = utcnow(), uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (object_id, board_id, payload.kind, payload.color_group, self._json(payload.contour),
                        self._json([x, y, right-x, bottom-y]), self._json(cutout), self._json(mask), cx, cy, 0, 1, .5,
                        "needs_review", 1, now, now))
            db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, object_id,
                       hole["id"], hole["x_mm"], hole["y_mm"], max(0, 1-distance/150), 0, now))
            db.execute("UPDATE board_versions SET version=version+1,updated_at=? WHERE id=?", (now, board_id))
        return self.get_board(board_id, owner)

    def _render_contour_assets(self, board: dict, contour: list[tuple[float, float]] | list[list[float]]):
        try: image = decode_photo(self.asset_path(board["original_asset"]["filename"]).read_bytes())
        except PhotoProcessingError as exc: raise HTTPException(422, "无法读取岩板原图") from exc
        points = np.asarray(contour, np.int32)
        x, y, width, height = cv2.boundingRect(points)
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > image.shape[1] or y + height > image.shape[0]:
            raise HTTPException(422, "轮廓超出原图范围")
        full_mask = np.zeros(image.shape[:2], np.uint8); cv2.fillPoly(full_mask, [points], 255)
        crop_mask = full_mask[y:y+height, x:x+width]
        rgba = cv2.cvtColor(image[y:y+height, x:x+width], cv2.COLOR_BGR2BGRA); rgba[:, :, 3] = crop_mask
        def save(array):
            ok, encoded = cv2.imencode(".png", array)
            if not ok: raise HTTPException(422, "无法生成轮廓素材")
            return self.save_asset(encoded.tobytes(), "png", width, height)
        return x, y, x + width, y + height, save(rgba), save(crop_mask)

    def split_object(self, board_id: str, object_id: str, owner: str, payload: SplitObject):
        board = self.get_board(board_id, owner)
        original = next((item for item in board["objects"] if item["id"] == object_id), None)
        if not original: raise HTTPException(404, "未找到对象")
        if original["object_version"] != payload.expected_version: raise HTTPException(409, "对象已有新版本")
        prepared = [self._render_contour_assets(board, contour) for contour in payload.contours]
        matrix = (board.get("calibration") or {}).get("matrix")
        if not matrix: raise HTTPException(422, "请先完成岩板标定")
        now = utcnow()
        with self.transaction() as db:
            db.execute("UPDATE board_objects SET review_status='rejected',object_version=object_version+1,updated_at=? WHERE id=?", (now, object_id))
            for contour, (x, y, right, bottom, cutout, mask) in zip(payload.contours, prepared):
                cx, cy = map_point(matrix, (x + right) / 2, (y + bottom) / 2)
                hole, distance = nearest_hole(cx, cy); new_id = uuid.uuid4().hex
                db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (new_id, board_id,
                           original["kind"], original["color_group"], self._json(contour), self._json([x,y,right-x,bottom-y]),
                           self._json(cutout), self._json(mask), cx, cy, original["rotation_deg"], original["scale_mm_per_px"],
                           min(original["confidence"], .7), "needs_review", 1, now, now))
                db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, new_id, hole["id"],
                           hole["x_mm"], hole["y_mm"], max(0, 1-distance/150), 0, now))
            db.execute("UPDATE board_versions SET version=version+1,updated_at=? WHERE id=?", (now, board_id))
        return self.get_board(board_id, owner)

    def merge_objects(self, board_id: str, owner: str, payload: MergeObjects):
        board = self.get_board(board_id, owner)
        if board["version"] != payload.expected_version: raise HTTPException(409, "岩板已有新版本")
        selected = [item for item in board["objects"] if item["id"] in set(payload.object_ids)]
        if len(selected) != len(set(payload.object_ids)): raise HTTPException(422, "合并对象不属于该岩板")
        colors = {item["color_group"] for item in selected}
        if len(colors) != 1: raise HTTPException(422, "请先统一颜色再合并轮廓")
        points = np.concatenate([np.asarray(item["contour"], np.float32) for item in selected])
        hull = cv2.convexHull(points).reshape(-1, 2).tolist()
        x, y, right, bottom, cutout, mask = self._render_contour_assets(board, hull)
        matrix = (board.get("calibration") or {}).get("matrix")
        if not matrix: raise HTTPException(422, "请先完成岩板标定")
        cx, cy = map_point(matrix, (x + right) / 2, (y + bottom) / 2); now, new_id = utcnow(), uuid.uuid4().hex
        anchors = {anchor["hole_id"]: anchor for item in selected for anchor in item["anchors"]}
        with self.transaction() as db:
            db.executemany("UPDATE board_objects SET review_status='rejected',object_version=object_version+1,updated_at=? WHERE id=?",
                           [(now, item["id"]) for item in selected])
            db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (new_id, board_id,
                       selected[0]["kind"], selected[0]["color_group"], self._json(hull), self._json([x,y,right-x,bottom-y]),
                       self._json(cutout), self._json(mask), cx, cy, 0, selected[0]["scale_mm_per_px"],
                       min(item["confidence"] for item in selected), "needs_review", 1, now, now))
            for anchor in anchors.values():
                db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, new_id,
                           anchor["hole_id"], anchor["x_mm"], anchor["y_mm"], anchor["confidence"], 0, now))
            db.execute("UPDATE board_versions SET version=version+1,updated_at=? WHERE id=?", (now, board_id))
        return self.get_board(board_id, owner)

    def reject_object(self, board_id: str, object_id: str, owner: str, expected_version: int):
        return self.patch_object(board_id, object_id, owner, ObjectPatch(expected_version=expected_version, review_status="rejected"))

    def _row_route(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict:
        result = dict(row)
        members = db.execute("SELECT * FROM route_members WHERE route_id=? ORDER BY ordinal", (row["id"],)).fetchall()
        result["members"] = [{**dict(item), "roles": self._load(item["roles_json"], []),
                              "tags": self._load(item["tags_json"], [])} for item in members]
        for member in result["members"]: member.pop("roles_json"); member.pop("tags_json")
        return result

    def create_route_from_color(self, owner: str, payload: ColorRouteCreate):
        board = self.get_board(payload.board_version_id, owner)
        objects = [item for item in board["objects"] if item["color_group"] == payload.color_group]
        if not objects: raise HTTPException(422, "该颜色没有可用对象")
        route_id, now = uuid.uuid4().hex, utcnow()
        with self.transaction() as db:
            db.execute("INSERT INTO routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                       (route_id, owner, board["id"], payload.name or f"{payload.color_group}线路", payload.color_group,
                        "", "", "", "draft", 1, now, now))
            for ordinal, obj in enumerate(objects):
                db.execute("INSERT INTO route_members VALUES(?,?,?,?,?,?)", (route_id, obj["id"], "[]", "[]", "", ordinal))
        return self.get_route(route_id, owner)

    def get_route(self, route_id: str, owner: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM routes WHERE id=? AND owner=?", (route_id, owner)).fetchone()
            if not row: raise HTTPException(404, "未找到线路")
            return self._row_route(db, row)

    def list_routes(self, owner: str, *, board_id: str | None = None, color: str | None = None,
                    status: str | None = None, search: str | None = None, archived=False):
        clauses, params = ["owner=?", "(? OR archived_at IS NULL)"], [owner, int(archived)]
        for column, value in (("board_version_id", board_id), ("color_group", color), ("status", status)):
            if value: clauses.append(f"{column}=?"); params.append(value)
        if search: clauses.append("(name LIKE ? OR setter LIKE ? OR notes LIKE ?)"); params.extend([f"%{search}%"]*3)
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM routes WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC", params).fetchall()
            return [self._row_route(db, row) for row in rows]

    def update_route(self, route_id: str, owner: str, payload: RouteUpdate):
        route = self.get_route(route_id, owner)
        if route["status"] == "completed": raise HTTPException(409, "已完成线路不可覆盖，请从历史版本创建新版本")
        if route["version"] != payload.expected_version: raise HTTPException(409, "线路已有新版本")
        board = self.get_board(route["board_version_id"], owner)
        object_map = {item["id"]: item for item in board["objects"]}
        if len({m.object_id for m in payload.members}) != len(payload.members): raise HTTPException(422, "线路对象不能重复")
        for member in payload.members:
            obj = object_map.get(member.object_id)
            if not obj: raise HTTPException(422, "线路包含不属于该岩板的对象")
            if obj["color_group"] != route["color_group"]: raise HTTPException(422, "当前版本不允许加入异色岩点")
        with self.transaction() as db:
            db.execute("UPDATE routes SET name=?,difficulty=?,setter=?,notes=?,version=version+1,updated_at=? WHERE id=?",
                       (payload.name, payload.difficulty, payload.setter, payload.notes, utcnow(), route_id))
            db.execute("DELETE FROM route_members WHERE route_id=?", (route_id,))
            for index, member in enumerate(payload.members):
                db.execute("INSERT INTO route_members VALUES(?,?,?,?,?,?)", (route_id, member.object_id,
                           self._json(member.roles), self._json(member.tags), member.note, index))
            db.execute("DELETE FROM background_variants WHERE route_id=?", (route_id,))
        return self.get_route(route_id, owner)

    def _snapshot(self, route: dict) -> dict:
        return {key: route[key] for key in ("id", "board_version_id", "name", "color_group", "difficulty",
                                            "setter", "notes", "status", "version", "members")}

    def complete_route(self, route_id: str, owner: str):
        route = self.get_route(route_id, owner)
        if not route["name"].strip() or not route["setter"].strip(): raise HTTPException(422, "请填写线路名称和定线者")
        roles = [role for item in route["members"] for role in item["roles"]]
        if "start" not in roles or "end" not in roles: raise HTTPException(422, "线路至少需要一个起点和一个终点")
        board = self.get_board(route["board_version_id"], owner)
        objects = {item["id"]: item for item in board["objects"]}
        for member in route["members"]:
            anchors = objects[member["object_id"]]["anchors"]
            if not anchors or not all(anchor["confirmed"] for anchor in anchors):
                raise HTTPException(422, "所有线路对象都必须确认孔位关系")
        with self.transaction() as db:
            now = utcnow()
            db.execute("UPDATE routes SET status='completed',updated_at=? WHERE id=?", (now, route_id))
            completed = {**route, "status": "completed", "updated_at": now}
            db.execute("INSERT OR REPLACE INTO route_revisions VALUES(?,?,?,?,?)",
                       (uuid.uuid4().hex, route_id, completed["version"], self._json(self._snapshot(completed)), now))
        return self.get_route(route_id, owner)

    def latest_background(self, route_id: str, owner: str):
        route = self.get_route(route_id, owner)
        with self.connect() as db:
            row = db.execute("SELECT * FROM background_variants WHERE route_id=? AND route_version=? ORDER BY created_at DESC LIMIT 1",
                             (route_id, route["version"])).fetchone()
        if not row: raise HTTPException(404, "当前线路版本还没有有效净化结果")
        result = dict(row)
        for field in ("removal_mask_asset", "preserve_mask_asset", "background_asset", "composite_asset"):
            result[field] = self._load(result[field])
        return result

    def revisions(self, route_id: str, owner: str):
        self.get_route(route_id, owner)
        with self.connect() as db:
            return [{**dict(row), "snapshot": self._load(row["snapshot_json"])} for row in
                    db.execute("SELECT * FROM route_revisions WHERE route_id=? ORDER BY version DESC", (route_id,))]

    def restore_revision(self, route_id: str, revision: int, owner: str):
        self.get_route(route_id, owner)
        with self.connect() as db:
            row = db.execute("SELECT snapshot_json FROM route_revisions WHERE route_id=? AND version=?", (route_id, revision)).fetchone()
        if not row: raise HTTPException(404, "未找到线路历史版本")
        snapshot = self._load(row[0]); new_id, now = uuid.uuid4().hex, utcnow()
        with self.transaction() as db:
            db.execute("INSERT INTO routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                       (new_id, owner, snapshot["board_version_id"], snapshot["name"] + "（历史副本）", snapshot["color_group"],
                        snapshot["difficulty"], snapshot["setter"], snapshot["notes"], "draft", 1, now, now))
            for index, member in enumerate(snapshot["members"]):
                db.execute("INSERT INTO route_members VALUES(?,?,?,?,?,?)", (new_id, member["object_id"],
                           self._json(member["roles"]), self._json(member["tags"]), member["note"], index))
        return self.get_route(new_id, owner)

    def archive_route(self, route_id: str, owner: str, archived: bool):
        self.get_route(route_id, owner)
        with self.transaction() as db:
            db.execute("UPDATE routes SET archived_at=?,updated_at=? WHERE id=?", (utcnow() if archived else None, utcnow(), route_id))
        return self.get_route(route_id, owner)

    def new_board_version(self, board_id: str, owner: str):
        board = self.get_board(board_id, owner); now, new_id = utcnow(), uuid.uuid4().hex
        with self.transaction() as db:
            next_number = db.execute("SELECT COALESCE(MAX(board_version_no),0)+1 FROM board_versions WHERE owner=? AND board_key=?",
                                     (owner, board["board_key"])).fetchone()[0]
            db.execute("INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                       (new_id, owner, board["board_key"], next_number, 1, "review",
                        self._json(board["original_asset"]), board["width"], board["height"],
                        self._json(board["quality"]), self._json(board["calibration"]), board["model_version"],
                        board["input_fingerprint"], now, now))
            for item in board["objects"]:
                clone_id = uuid.uuid4().hex
                db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (clone_id, new_id,
                           item["kind"], item["color_group"], self._json(item["contour"]), self._json(item["source_bbox_px"]),
                           self._json(item["cutout"]) if item["cutout"] else None, self._json(item["mask"]) if item["mask"] else None,
                           item["center_x_mm"], item["center_y_mm"], item["rotation_deg"], item["scale_mm_per_px"],
                           item["confidence"], item["review_status"], 1, now, now))
                for anchor in item["anchors"]:
                    db.execute("INSERT INTO object_anchors VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, clone_id,
                               anchor["hole_id"], anchor["x_mm"], anchor["y_mm"], anchor["confidence"], int(anchor["confirmed"]), now))
        return self.get_board(new_id, owner)

    def import_legacy_drafts(self):
        legacy = self.root / "drafts.json"
        if not legacy.exists(): return
        backup = self.root / "drafts.v1.readonly.json"
        if not backup.exists(): shutil.copy2(legacy, backup); os.chmod(backup, 0o444)
        try: drafts = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return
        with self.connect() as db:
            if db.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone(): return
        for draft in drafts:
            try: self._import_legacy_one(draft)
            except (KeyError, TypeError, ValueError, sqlite3.Error): continue
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(2,?)", (utcnow(),))

    def _import_legacy_one(self, draft: dict):
        board_id, now = f"legacy-board-{draft['id']}", draft.get("updated_at") or utcnow()
        source = draft["source"]; original = source["original"]
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM board_versions WHERE id=?", (board_id,)).fetchone(): return
            db.execute("INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)", (board_id, draft["owner"],
                       f"legacy-{draft['extraction_id']}", 1, 1, "review", self._json(original), original["width"], original["height"],
                       self._json({"accepted": True, "issues": ["由旧草稿迁入，需人工复核"], "metrics": {}}), None,
                       "legacy-import-v1", original["sha256"], draft.get("created_at", now), now))
            object_ids = []
            for old in draft["objects"]:
                object_id = f"{board_id}-{old['id']}"; object_ids.append(object_id)
                x, y, width, height = old["source_bbox_px"]
                contour = [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]
                db.execute("INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (object_id, board_id,
                           old["kind"], draft.get("color") or "未分组", self._json(contour), self._json(old["source_bbox_px"]),
                           self._json(old["cutout"]), self._json(old["mask"]), old["center_x_mm"], old["center_y_mm"],
                           old["rotation_deg"], old["scale_mm_per_px"], .5,
                           "needs_review" if old["contour_status"] == "needs_correction" else "confirmed", 1, now, now))
            route_id = f"legacy-route-{draft['id']}"
            db.execute("INSERT INTO routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)", (route_id, draft["owner"], board_id,
                       draft.get("name", ""), draft.get("color", "未分组"), draft.get("original_grade", ""), "",
                       draft.get("notes", ""), "draft", max(1, draft.get("version", 1)), draft.get("created_at", now), now))
            for index, (old, object_id) in enumerate(zip(draft["objects"], object_ids)):
                db.execute("INSERT INTO route_members VALUES(?,?,?,?,?,?)", (route_id, object_id,
                           self._json(old.get("roles", [])), "[]", "", index))


class PhotoRouteJobManager:
    """Single-concurrency local queue with cancellation and late-result protection."""
    def __init__(self, store: PhotoRouteV2Store, timeout_seconds: int = 180):
        self.store, self.timeout_seconds = store, timeout_seconds
        self._queue: queue.Queue[str] = queue.Queue()
        self._queued: set[str] = set()
        self._stop = threading.Event()
        self._active_cancel: dict[str, threading.Event] = {}
        self._thread = threading.Thread(target=self._run, name="photo-route-worker", daemon=True)
        self._thread.start()
        for job_id in store.queued_jobs(): self.enqueue(job_id)

    def enqueue(self, job_id: str):
        if job_id not in self._queued:
            self._queued.add(job_id); self._queue.put(job_id)

    def cancel(self, job_id: str):
        event = self._active_cancel.get(job_id)
        if event: event.set()

    def close(self):
        self._stop.set(); self._queue.put(""); self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            job_id = self._queue.get()
            if not job_id: continue
            self._queued.discard(job_id)
            try: job = self.store.get_job(job_id)
            except HTTPException: continue
            if job["status"] != "queued": continue
            cancel = threading.Event(); self._active_cancel[job_id] = cancel
            started = time.monotonic()
            try:
                self.store.mark_job(job_id, "running", "本地模型识别中", 10)
                failure: list[BaseException] = []
                def execute():
                    try:
                        if job["kind"] == "recognition": self._recognize(job, cancel, started)
                        elif job["kind"] == "cleanup": self._cleanup(job, cancel, started)
                        else: raise ValueError("未知任务类型")
                    except BaseException as exc: failure.append(exc)
                worker = threading.Thread(target=execute, name=f"photo-route-job-{job_id[:8]}", daemon=True)
                worker.start(); worker.join(self.timeout_seconds)
                if worker.is_alive(): cancel.set(); raise TimeoutError("本地处理任务超过 180 秒，迟到结果已丢弃")
                if failure: raise failure[0]
                latest = self.store.get_job(job_id)
                if cancel.is_set() or latest["cancel_requested"]:
                    self.store.mark_job(job_id, "cancelled", "已取消", latest["progress"])
                else: self.store.mark_job(job_id, "succeeded", "已完成", 100)
            except (Exception, KeyboardInterrupt) as exc:
                latest = self.store.get_job(job_id)
                if cancel.is_set() or latest["cancel_requested"]: self.store.mark_job(job_id, "cancelled", "已取消", latest["progress"])
                else:
                    if job["kind"] == "recognition" and job.get("board_version_id"):
                        with self.store.transaction() as db:
                            db.execute("UPDATE board_versions SET status='failed',updated_at=? WHERE id=?", (utcnow(), job["board_version_id"]))
                    self.store.mark_job(job_id, "failed", "处理失败", latest["progress"], str(exc)[:1000])
            finally: self._active_cancel.pop(job_id, None)

    def _recognize(self, job: dict, cancel: threading.Event, started: float):
        board = self.store.get_board(job["board_version_id"], job["owner"])
        path = self.store.asset_path(board["original_asset"]["filename"])
        result = analyze_board_photo(path, self.store.root, cancelled=lambda: cancel.is_set(),
            deadline=started + self.timeout_seconds,
            color_group=job["payload"].get("color_group"), calibration=job["payload"].get("calibration"),
            require_climbing_model=True, color_version="interior-v4", boundary_refinement=False,
            progress=lambda stage, percent: self.store.mark_job(job["id"], "running", stage, percent)
                if not cancel.is_set() else None)
        for index, item in enumerate(job["payload"].get("preserved_objects", [])):
            result["objects"].append({**item, "id": f"preserved-{index:03d}"})
        if time.monotonic() - started > self.timeout_seconds: raise TimeoutError("识别任务超过 180 秒")
        if cancel.is_set() or self.store.get_job(job["id"])["cancel_requested"]: return
        self.store.mark_job(job["id"], "running", "写入标定与对象", 85)
        self.store.set_analysis_result(board["id"], result)

    def _cleanup(self, job: dict, cancel: threading.Event, started: float):
        route = self.store.get_route(job["route_id"], job["owner"])
        board = self.store.get_board(route["board_version_id"], job["owner"])
        image = decode_photo(self.store.asset_path(board["original_asset"]["filename"]).read_bytes())
        height, width = image.shape[:2]
        payload = job["payload"]
        def polygons(values):
            mask = np.zeros((height, width), np.uint8)
            for polygon in values:
                cv2.fillPoly(mask, [np.asarray(polygon, np.int32)], 255)
            return mask
        removal, preserve = polygons(payload.get("removal_polygons", [])), polygons(payload.get("preserve_polygons", []))
        target = np.zeros((height, width), np.uint8)
        objects = {item["id"]: item for item in board["objects"]}
        for member in route["members"]:
            contour = np.asarray(objects[member["object_id"]]["contour"], np.int32)
            if len(contour) >= 3: cv2.fillPoly(target, [contour], 255)
        if not np.any(removal):
            for obj in board["objects"]:
                if obj["id"] not in {m["object_id"] for m in route["members"]}:
                    cv2.fillPoly(removal, [np.asarray(obj["contour"], np.int32)], 255)
        result = restore_wall(image, removal, target, method=payload.get("method", "opencv"), preserve_mask=preserve)
        if cancel.is_set() or time.monotonic() - started > self.timeout_seconds: return
        def save(array, suffix="png"):
            ok, encoded = cv2.imencode("."+suffix, array)
            if not ok: raise PhotoProcessingError("无法保存净化结果")
            return self.store.save_asset(encoded.tobytes(), suffix, array.shape[1], array.shape[0])
        removal_ref, preserve_ref = save(removal), save(preserve)
        background_ref, composite_ref = save(result.background), save(result.composite)
        with self.store.transaction() as db:
            db.execute("INSERT INTO background_variants VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, route["id"],
                       route["version"], board["input_fingerprint"], fingerprint_payload([m["object_id"] for m in route["members"]]),
                       self.store._json(removal_ref), self.store._json(preserve_ref), self.store._json(background_ref),
                       self.store._json(composite_ref), payload.get("method", "opencv"), "completed", utcnow()))


def create_photo_route_v2_router(store: PhotoRouteV2Store, jobs: PhotoRouteJobManager) -> APIRouter:
    router = APIRouter(prefix="/api/photo-routes/v2", tags=["photo-route-v2"])
    def owner(request: Request) -> str: return request.state.pilot_user.username

    @router.post("/boards/upload")
    async def upload_board(request: Request, photo: UploadFile = File(...), board_name: str = Form(default="")):
        data = await photo.read()
        board, job = store.create_upload(owner(request), photo.filename or board_name or "board.jpg", data)
        jobs.enqueue(job["id"])
        return {"board": board, "job": job}

    @router.get("/boards")
    def boards(request: Request, archived: bool = False): return store.list_boards(owner(request), archived)

    @router.get("/boards/{board_id}")
    def board(board_id: str, request: Request): return store.get_board(board_id, owner(request))

    @router.post("/boards/{board_id}/versions")
    def board_version(board_id: str, request: Request): return store.new_board_version(board_id, owner(request))

    @router.post("/boards/{board_id}/refine")
    def refine_board(board_id: str, payload: ColorRefinement, request: Request):
        result = store.create_color_refinement(board_id, owner(request), payload)
        jobs.enqueue(result["job"]["id"])
        return result

    @router.put("/boards/{board_id}/calibration")
    def calibrate(board_id: str, payload: CalibrationUpdate, request: Request): return store.update_calibration(board_id, owner(request), payload)

    @router.post("/boards/{board_id}/objects")
    def add_object(board_id: str, payload: ObjectCreate, request: Request): return store.add_object(board_id, owner(request), payload)

    @router.patch("/boards/{board_id}/objects/{object_id}")
    def patch_object(board_id: str, object_id: str, payload: ObjectPatch, request: Request):
        return store.patch_object(board_id, object_id, owner(request), payload)

    @router.post("/boards/{board_id}/objects/{object_id}/split")
    def split_object(board_id: str, object_id: str, payload: SplitObject, request: Request):
        return store.split_object(board_id, object_id, owner(request), payload)

    @router.post("/boards/{board_id}/objects/merge")
    def merge_objects(board_id: str, payload: MergeObjects, request: Request):
        return store.merge_objects(board_id, owner(request), payload)

    @router.delete("/boards/{board_id}/objects/{object_id}")
    def delete_object(board_id: str, object_id: str, request: Request, expected_version: int):
        return store.reject_object(board_id, object_id, owner(request), expected_version)

    @router.get("/jobs/{job_id}")
    def job(job_id: str, request: Request): return store.get_job(job_id, owner(request))

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        result = store.cancel_job(job_id, owner(request)); jobs.cancel(job_id); return result

    @router.post("/jobs/{job_id}/retry")
    def retry(job_id: str, request: Request):
        result = store.retry_job(job_id, owner(request)); jobs.enqueue(job_id); return result

    @router.post("/routes/from-color")
    def from_color(payload: ColorRouteCreate, request: Request): return store.create_route_from_color(owner(request), payload)

    @router.get("/routes")
    def routes(request: Request, board_version_id: str | None = None, color: str | None = None,
               status: str | None = None, search: str | None = None, archived: bool = False):
        return store.list_routes(owner(request), board_id=board_version_id, color=color, status=status, search=search, archived=archived)

    @router.get("/routes/{route_id}")
    def route(route_id: str, request: Request): return store.get_route(route_id, owner(request))

    @router.put("/routes/{route_id}")
    def update_route(route_id: str, payload: RouteUpdate, request: Request): return store.update_route(route_id, owner(request), payload)

    @router.post("/routes/{route_id}/complete")
    def complete(route_id: str, request: Request): return store.complete_route(route_id, owner(request))

    @router.get("/routes/{route_id}/revisions")
    def revisions(route_id: str, request: Request): return store.revisions(route_id, owner(request))

    @router.get("/routes/{route_id}/background")
    def background(route_id: str, request: Request): return store.latest_background(route_id, owner(request))

    @router.post("/routes/{route_id}/revisions/{version}/restore")
    def restore(route_id: str, version: int, request: Request): return store.restore_revision(route_id, version, owner(request))

    @router.post("/routes/{route_id}/archive")
    def archive(route_id: str, request: Request): return store.archive_route(route_id, owner(request), True)

    @router.post("/routes/{route_id}/restore")
    def unarchive(route_id: str, request: Request): return store.archive_route(route_id, owner(request), False)

    @router.post("/routes/{route_id}/cleanup")
    def cleanup(route_id: str, payload: CleanupRequest, request: Request):
        route = store.get_route(route_id, owner(request))
        job = store.create_job(owner(request), "cleanup", board_id=route["board_version_id"], route_id=route_id,
                               payload=payload.model_dump(mode="json")); jobs.enqueue(job["id"]); return job

    @router.get("/assets/{filename}")
    def asset(filename: str, request: Request):
        # Ownership is checked by requiring the digest to occur in an owner-visible record.
        needle = f'"filename":"{filename}"'
        with store.connect() as db:
            visible = db.execute("SELECT 1 FROM board_versions WHERE owner=? AND original_asset LIKE ? UNION SELECT 1 FROM board_objects o JOIN board_versions b ON b.id=o.board_version_id WHERE b.owner=? AND (o.cutout_asset LIKE ? OR o.mask_asset LIKE ?) UNION SELECT 1 FROM background_variants v JOIN routes r ON r.id=v.route_id WHERE r.owner=? AND (v.removal_mask_asset LIKE ? OR v.preserve_mask_asset LIKE ? OR v.background_asset LIKE ? OR v.composite_asset LIKE ?) LIMIT 1",
                                 (owner(request), f"%{needle}%", owner(request), f"%{needle}%", f"%{needle}%",
                                  owner(request), f"%{needle}%", f"%{needle}%", f"%{needle}%", f"%{needle}%")).fetchone()
        if not visible: raise HTTPException(404, "未找到该素材")
        return FileResponse(store.asset_path(filename), headers={"Cache-Control": "private, no-cache"})

    return router
