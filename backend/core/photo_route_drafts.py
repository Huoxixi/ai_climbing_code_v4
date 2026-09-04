"""Local, versioned photo-route drafts. No inference or remote storage clients."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PhotoBoardSpec(Contract):
    preset_id: Literal["photo-wall-30x20-v1"] = "photo-wall-30x20-v1"
    columns: Literal[30] = 30
    rows: Literal[20] = 20
    hole_spacing_x_mm: Literal[200] = 200
    hole_spacing_y_mm: Literal[200] = 200
    board_width_mm: Literal[6200] = 6200
    board_height_mm: Literal[4100] = 4100
    margin_left_mm: Literal[200] = 200
    margin_right_mm: Literal[200] = 200
    margin_bottom_mm: Literal[100] = 100
    margin_top_mm: Literal[200] = 200
    snap_mode: Literal["none"] = "none"


class AssetRef(Contract):
    filename: str = Field(pattern=r"^[a-f0-9]{64}\.(png|jpg|webp)$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0, le=40000)
    height: int = Field(gt=0, le=40000)

    @model_validator(mode="after")
    def matching_digest(self):
        if self.filename.split(".")[0] != self.sha256:
            raise ValueError("素材名称与指纹不一致")
        return self


class PhotoRouteObject(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    kind: Literal["hold", "volume"] = "hold"
    cutout: AssetRef
    mask: AssetRef
    source_bbox_px: tuple[int, int, int, int]
    center_x_mm: float
    center_y_mm: float
    scale_mm_per_px: float = Field(gt=0)
    rotation_deg: float = Field(ge=-360, le=360, default=0)
    z_index: int = Field(ge=0, le=10000, default=0)
    roles: list[Literal["start", "end"]] = Field(default_factory=list, max_length=2)
    contour_status: Literal["provisional", "needs_correction"] = "provisional"

    @model_validator(mode="after")
    def valid_geometry(self):
        x, y, w, h = self.source_bbox_px
        if min(x, y) < 0 or min(w, h) <= 0 or (w, h) != (self.cutout.width, self.cutout.height):
            raise ValueError("抠图与原始像素边界不一致")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("起终点角色不能重复")
        angle = math.radians(self.rotation_deg)
        half_w = (abs(w * math.cos(angle)) + abs(h * math.sin(angle))) * self.scale_mm_per_px / 2
        half_h = (abs(w * math.sin(angle)) + abs(h * math.cos(angle))) * self.scale_mm_per_px / 2
        if (self.center_x_mm - half_w < -1e-6 or self.center_x_mm + half_w > 6200 + 1e-6
                or self.center_y_mm - half_h < -1e-6 or self.center_y_mm + half_h > 4100 + 1e-6):
            raise ValueError("对象超出岩板范围")
        return self


class PhotoSourceRef(Contract):
    original: AssetRef
    working_dimensions: tuple[int, int]
    algorithm: str
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    background: AssetRef | None = None


class PhotoRouteDraft(Contract):
    id: str
    owner: str
    extraction_id: str
    name: str = Field(default="", max_length=120)
    color: str = Field(default="", max_length=40)
    original_grade: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=4000)
    status: Literal["draft"] = "draft"
    version: int = Field(ge=1, default=1)
    created_at: str
    updated_at: str
    board_spec: PhotoBoardSpec = Field(default_factory=PhotoBoardSpec)
    source: PhotoSourceRef
    objects: list[PhotoRouteObject] = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_objects(self):
        if len({obj.id for obj in self.objects}) != len(self.objects):
            raise ValueError("对象编号重复")
        width, height = self.source.working_dimensions
        if min(width, height) <= 0:
            raise ValueError("原始画布尺寸无效")
        for obj in self.objects:
            x, y, w, h = obj.source_bbox_px
            if x + w > width or y + h > height:
                raise ValueError("对象超出原始画布范围")
        return self


class DraftUpdate(Contract):
    expected_version: int = Field(ge=1)
    name: str = Field(default="", max_length=120)
    color: str = Field(default="", max_length=40)
    original_grade: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=4000)
    objects: list[PhotoRouteObject] = Field(min_length=1, max_length=600)


class DraftImport(Contract):
    extraction_id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")


def fit_objects(objects: list[dict]) -> list[dict]:
    if not objects:
        raise ValueError("提取结果没有可用对象")
    left = min(o["source_bbox_px"][0] for o in objects)
    top = min(o["source_bbox_px"][1] for o in objects)
    right = max(o["source_bbox_px"][0] + o["source_bbox_px"][2] for o in objects)
    bottom = max(o["source_bbox_px"][1] + o["source_bbox_px"][3] for o in objects)
    if right <= left or bottom <= top:
        raise ValueError("提取结果边界无效")
    scale = min(5800 / (right - left), 3800 / (bottom - top))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    return [{**o, "center_x_mm": 3100 + (o["source_bbox_px"][0] + o["source_bbox_px"][2] / 2 - cx) * scale,
             "center_y_mm": 2000 - (o["source_bbox_px"][1] + o["source_bbox_px"][3] / 2 - cy) * scale,
             "scale_mm_per_px": scale, "rotation_deg": 0} for o in objects]


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class PhotoRouteStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.assets = self.root / "assets"
        self.catalog = self.root / "extractions"
        self.file = self.root / "drafts.json"
        self._thread_lock = threading.RLock()

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, (self.root / ".lock").open("a+b") as lock:
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self):
        return json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else []

    def asset_path(self, ref: AssetRef) -> Path:
        path = (self.assets / ref.filename).resolve()
        if not path.is_relative_to(self.assets.resolve()) or not path.is_file():
            raise HTTPException(422, "素材不存在或路径无效")
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref.sha256:
            raise HTTPException(422, "素材指纹校验失败，请重新导入提取结果")
        return path

    def check_assets(self, draft: PhotoRouteDraft):
        refs = [draft.source.original, draft.source.background]
        refs.extend(ref for obj in draft.objects for ref in (obj.cutout, obj.mask))
        for ref in refs:
            if ref:
                self.asset_path(ref)

    def catalog_list(self):
        return [{"extraction_id": p.stem, "name": data["name"], "color": data["color"],
                 "object_count": len(data["objects"])}
                for p in sorted(self.catalog.glob("*.json"))
                for data in [json.loads(p.read_text(encoding="utf-8"))]]

    def list(self, owner: str):
        with self.locked():
            return sorted([d for d in self._read() if d["owner"] == owner], key=lambda d: d["updated_at"], reverse=True)

    def get(self, draft_id: str, owner: str):
        with self.locked():
            return self._find(self._read(), draft_id, owner)

    @staticmethod
    def _find(drafts, draft_id, owner):
        draft = next((d for d in drafts if d["id"] == draft_id and d["owner"] == owner), None)
        if draft is None:
            raise HTTPException(404, "未找到该照片线路草稿")
        return draft

    def import_draft(self, extraction_id: str, owner: str):
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", extraction_id):
            raise HTTPException(422, "提取结果编号无效")
        manifest_path = (self.catalog / f"{extraction_id}.json").resolve()
        if not manifest_path.is_relative_to(self.catalog.resolve()) or not manifest_path.is_file():
            raise HTTPException(404, "提取结果尚未导入本机")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        draft = PhotoRouteDraft(id=uuid.uuid4().hex, owner=owner, extraction_id=extraction_id,
                                name=manifest["name"], color=manifest["color"], source=manifest["source"],
                                objects=fit_objects(manifest["objects"]), created_at=now, updated_at=now)
        self.check_assets(draft)
        with self.locked():
            drafts = self._read()
            existing = next((d for d in drafts if d["owner"] == owner and d["extraction_id"] == extraction_id), None)
            if existing:
                return existing
            data = draft.model_dump(mode="json")
            drafts.append(data)
            atomic_json(self.file, drafts)
            return data

    def update(self, draft_id: str, owner: str, update: DraftUpdate):
        with self.locked():
            drafts = self._read()
            old = self._find(drafts, draft_id, owner)
            if old["version"] != update.expected_version:
                raise HTTPException(409, {"message": "草稿已有新版本，当前修改已保留", "version": old["version"]})
            old_objects = {o["id"]: o for o in old["objects"]}
            if set(old_objects) != {o.id for o in update.objects} or len(old_objects) != len(update.objects):
                raise HTTPException(422, "本阶段不能添加或删除提取对象")
            for obj in update.objects:
                for field in ("cutout", "mask", "source_bbox_px", "contour_status"):
                    if obj.model_dump(mode="json")[field] != old_objects[obj.id][field]:
                        raise HTTPException(422, "不能改写原始素材、像素边界或复核状态")
            data = {**old, **update.model_dump(mode="json", exclude={"expected_version"}),
                    "version": old["version"] + 1, "updated_at": datetime.now(timezone.utc).isoformat()}
            draft = PhotoRouteDraft.model_validate(data)
            self.check_assets(draft)
            data = draft.model_dump(mode="json")
            drafts[drafts.index(old)] = data
            atomic_json(self.file, drafts)
            return data


def create_photo_route_router(store: PhotoRouteStore) -> APIRouter:
    router = APIRouter()

    def owner(request):
        return request.state.pilot_user.username

    @router.get("/api/photo-routes/extractions")
    def extractions():
        return store.catalog_list()

    @router.post("/api/photo-routes/drafts/import", response_model=PhotoRouteDraft)
    def import_draft(payload: DraftImport, request: Request):
        try:
            return store.import_draft(payload.extraction_id, owner(request))
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "提取包内容无效，请检查本地导入结果") from exc

    @router.get("/api/photo-routes/drafts", response_model=list[PhotoRouteDraft])
    def list_drafts(request: Request):
        return store.list(owner(request))

    @router.get("/api/photo-routes/drafts/{draft_id}", response_model=PhotoRouteDraft)
    def get_draft(draft_id: str, request: Request):
        return store.get(draft_id, owner(request))

    @router.put("/api/photo-routes/drafts/{draft_id}", response_model=PhotoRouteDraft)
    def update_draft(draft_id: str, payload: DraftUpdate, request: Request):
        return store.update(draft_id, owner(request), payload)

    @router.get("/photo-route-assets/{filename}")
    def get_asset(filename: str, request: Request):
        # Assets are private to a user's imported drafts, even when a filename is guessed.
        for draft in store.list(owner(request)):
            refs = [draft["source"]["original"], draft["source"].get("background")]
            refs.extend(ref for obj in draft["objects"] for ref in (obj["cutout"], obj["mask"]))
            for ref in refs:
                if ref and ref["filename"] == filename:
                    asset = AssetRef.model_validate(ref)
                    return FileResponse(store.asset_path(asset), headers={"Cache-Control": "private, no-cache"})
        raise HTTPException(404, "未找到该素材")

    return router
