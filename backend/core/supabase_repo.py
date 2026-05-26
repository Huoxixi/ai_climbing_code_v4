import base64
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from core.models import BoardAsset


class SupabaseRepositoryError(RuntimeError):
    pass


def is_supabase_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)


def extract_user_id_from_auth_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if token.startswith("mock-token-"):
        return None

    parts = token.split(".")
    if len(parts) < 2:
        return None

    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return None

    subject = claims.get("sub")
    try:
        return str(uuid.UUID(str(subject))) if subject else None
    except ValueError:
        return None


class SupabaseRepository:
    def __init__(self) -> None:
        self.base_url = settings.supabase_url.rstrip("/")
        self.key = settings.supabase_service_role_key
        self.bucket = settings.supabase_storage_bucket

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.key)

    def _headers(self, prefer: Optional[str] = None, content_type: str = "application/json") -> Dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": content_type,
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _table_url(self, table: str) -> str:
        return f"{self.base_url}/rest/v1/{table}"

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        if not self.enabled:
            raise SupabaseRepositoryError("Supabase is not configured")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, **kwargs)

        if response.status_code >= 400:
            raise SupabaseRepositoryError(f"Supabase {method} {url} failed: {response.status_code} {response.text}")

        if not response.content:
            return None
        return response.json()

    async def list_boards(self, owner_id: Optional[str]) -> List[Dict[str, Any]]:
        params: Dict[str, str] = {
            "select": "*,route_holds(*),route_beta_steps(*)",
            "archived_at": "is.null",
            "order": "updated_at.desc",
        }
        if owner_id:
            params["or"] = f"(owner_id.eq.{owner_id},visibility.eq.public)"

        rows = await self._request("GET", self._table_url("board_assets"), headers=self._headers(), params=params)
        return [self._board_from_row(row) for row in rows or []]

    async def create_board(self, payload: Dict[str, Any], owner_id: Optional[str]) -> Dict[str, Any]:
        board = self._normalize_board(payload)
        board_id = str(uuid.uuid4())
        board_row = self._board_row(board, board_id, owner_id)

        rows = await self._request(
            "POST",
            self._table_url("board_assets"),
            headers=self._headers("return=representation"),
            json=board_row,
        )
        saved_row = rows[0]
        await self._replace_board_children(saved_row["id"], board)
        return await self.get_board(saved_row["id"])

    async def update_board(self, saved_id: str, payload: Dict[str, Any], owner_id: Optional[str]) -> Dict[str, Any]:
        board = self._normalize_board({**payload, "saved_id": saved_id})
        patch = self._board_row(board, saved_id, owner_id)
        patch.pop("id", None)
        if owner_id is None:
            patch.pop("owner_id", None)

        rows = await self._request(
            "PATCH",
            self._table_url("board_assets"),
            headers=self._headers("return=representation"),
            params={"id": f"eq.{saved_id}", "archived_at": "is.null"},
            json=patch,
        )
        if not rows:
            raise SupabaseRepositoryError("Board not found")
        await self._replace_board_children(saved_id, board)
        return await self.get_board(saved_id)

    async def archive_board(self, saved_id: str) -> bool:
        rows = await self._request(
            "PATCH",
            self._table_url("board_assets"),
            headers=self._headers("return=representation"),
            params={"id": f"eq.{saved_id}", "archived_at": "is.null"},
            json={"archived_at": datetime.now(timezone.utc).isoformat()},
        )
        return bool(rows)

    async def get_board(self, saved_id: str) -> Dict[str, Any]:
        rows = await self._request(
            "GET",
            self._table_url("board_assets"),
            headers=self._headers(),
            params={"select": "*,route_holds(*),route_beta_steps(*)", "id": f"eq.{saved_id}", "limit": "1"},
        )
        if not rows:
            raise SupabaseRepositoryError("Board not found")
        return self._board_from_row(rows[0])

    async def get_holds_mapping(self) -> Dict[str, Dict[str, str]]:
        rows = await self._request(
            "GET",
            self._table_url("hold_assets"),
            headers=self._headers(),
            params={"select": "hold_type,variant,public_image_url,image_path", "archived_at": "is.null", "order": "hold_type.asc,variant.asc"},
        )
        mapping: Dict[str, Dict[str, str]] = {}
        for row in rows or []:
            image_url = row.get("public_image_url") or self.public_storage_url(row.get("image_path"))
            if image_url:
                mapping.setdefault(row["hold_type"], {})[row["variant"]] = image_url
        return mapping

    async def get_holds_vectors(self) -> Dict[str, Dict[str, str]]:
        rows = await self._request(
            "GET",
            self._table_url("hold_assets"),
            headers=self._headers(),
            params={"select": "hold_type,variant,svg_path", "archived_at": "is.null", "order": "hold_type.asc,variant.asc"},
        )
        vectors: Dict[str, Dict[str, str]] = {}
        for row in rows or []:
            if row.get("svg_path"):
                vectors.setdefault(row["hold_type"], {})[row["variant"]] = row["svg_path"]
        return vectors

    async def upsert_hold_asset(
        self,
        hold_type: str,
        variant: str,
        image_path: str,
        svg_path: str,
        owner_id: Optional[str],
        is_system: bool = False,
    ) -> Dict[str, Any]:
        row = {
            "owner_id": owner_id,
            "hold_type": hold_type,
            "variant": variant,
            "image_path": image_path,
            "public_image_url": self.public_storage_url(image_path),
            "svg_path": svg_path,
            "metadata": {},
            "is_system": is_system,
            "archived_at": None,
        }
        existing = await self._request(
            "GET",
            self._table_url("hold_assets"),
            headers=self._headers(),
            params={
                "select": "id",
                "hold_type": f"eq.{hold_type}",
                "variant": f"eq.{variant}",
                "archived_at": "is.null",
                "limit": "1",
            },
        )
        if existing:
            rows = await self._request(
                "PATCH",
                self._table_url("hold_assets"),
                headers=self._headers("return=representation"),
                params={"id": f"eq.{existing[0]['id']}"},
                json=row,
            )
            return rows[0]

        rows = await self._request("POST", self._table_url("hold_assets"), headers=self._headers("return=representation"), json=row)
        return rows[0]

    async def archive_hold_asset(self, hold_type: str, variant: str) -> bool:
        rows = await self._request(
            "PATCH",
            self._table_url("hold_assets"),
            headers=self._headers("return=representation"),
            params={"hold_type": f"eq.{hold_type}", "variant": f"eq.{variant}", "archived_at": "is.null"},
            json={"archived_at": datetime.now(timezone.utc).isoformat()},
        )
        return bool(rows)

    async def upload_hold_image(self, filename: str, image_bytes: bytes, content_type: str) -> str:
        object_name = f"system/{filename}"
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{object_name}"
        await self._request(
            "POST",
            url,
            headers=self._headers("upsert=true", content_type=content_type),
            content=image_bytes,
        )
        return object_name

    def public_storage_url(self, object_name: Optional[str]) -> Optional[str]:
        if not object_name:
            return None
        if object_name.startswith("http://") or object_name.startswith("https://") or object_name.startswith("/images/"):
            return object_name
        return f"{self.base_url}/storage/v1/object/public/{self.bucket}/{object_name}"

    async def create_task(self, task_id: str, payload: Dict[str, Any], owner_id: Optional[str]) -> None:
        mode = payload.get("mode") or ("compose_route" if "board" in payload else "legacy_generate")
        await self._request(
            "POST",
            self._table_url("ai_generation_tasks"),
            headers=self._headers(),
            json={
                "id": task_id,
                "owner_id": owner_id,
                "mode": mode,
                "status": "pending",
                "request_payload": payload,
            },
        )

    async def update_task(self, task_id: str, status: str, result: Any = None, error: Optional[str] = None) -> None:
        patch: Dict[str, Any] = {"status": status}
        if status == "running":
            patch["started_at"] = datetime.now(timezone.utc).isoformat()
        if status in {"completed", "failed", "cancelled"}:
            patch["completed_at"] = datetime.now(timezone.utc).isoformat()
        if result is not None:
            patch["result_payload"] = result
        if error is not None:
            patch["error_message"] = error

        await self._request(
            "PATCH",
            self._table_url("ai_generation_tasks"),
            headers=self._headers(),
            params={"id": f"eq.{task_id}"},
            json=patch,
        )

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        rows = await self._request(
            "GET",
            self._table_url("ai_generation_tasks"),
            headers=self._headers(),
            params={"select": "id,status,result_payload,error_message", "id": f"eq.{task_id}", "limit": "1"},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "task_id": row["id"],
            "status": row["status"],
            "result": row.get("result_payload"),
            "error": row.get("error_message"),
        }

    def _normalize_board(self, payload: Dict[str, Any]) -> BoardAsset:
        return BoardAsset(**payload)

    def _board_row(self, board: BoardAsset, board_id: str, owner_id: Optional[str]) -> Dict[str, Any]:
        board_spec = board.board_spec.model_dump(mode="json") if board.board_spec else None
        return {
            "id": board_id,
            "owner_id": owner_id,
            "route_name": board.route_name,
            "setter_commentary": board.setter_commentary,
            "source_type": board.source_type,
            "visibility": board.visibility,
            "difficulty": board.difficulty,
            "board_template_id": board_spec.get("preset_id") if isinstance(board_spec, dict) else None,
            "board_spec": board_spec,
            "tags": board.tags,
            "created_at": board.created_at,
            "updated_at": board.updated_at,
        }

    async def _replace_board_children(self, board_id: str, board: BoardAsset) -> None:
        await self._request("DELETE", self._table_url("route_beta_steps"), headers=self._headers(), params={"board_asset_id": f"eq.{board_id}"})
        await self._request("DELETE", self._table_url("route_holds"), headers=self._headers(), params={"board_asset_id": f"eq.{board_id}"})

        hold_rows = []
        for index, hold in enumerate(board.placed_holds):
            raw = hold.model_dump(mode="json")
            hold_rows.append(
                {
                    "board_asset_id": board_id,
                    "coord_id": hold.id,
                    "x_label": hold.x,
                    "y_index": hold.y,
                    "hold_type": hold.hold_type.value,
                    "variant": hold.variant,
                    "rotation": hold.rotation,
                    "scale": hold.scale,
                    "is_start": hold.is_start,
                    "sort_order": index,
                    "raw": raw,
                }
            )
        if hold_rows:
            await self._request("POST", self._table_url("route_holds"), headers=self._headers(), json=hold_rows)

        beta_rows = []
        for index, step in enumerate(board.beta_sequence):
            raw = step.model_dump(mode="json")
            beta_rows.append(
                {
                    "board_asset_id": board_id,
                    "step_index": step.step if step.step is not None else index,
                    "limb": step.limb.value,
                    "hold_coord_id": step.hold_id,
                    "intent": step.intent,
                    "is_top": step.is_top,
                    "lh": step.lh,
                    "rh": step.rh,
                    "lf": step.lf,
                    "rf": step.rf,
                    "raw": raw,
                }
            )
        if beta_rows:
            await self._request("POST", self._table_url("route_beta_steps"), headers=self._headers(), json=beta_rows)

    def _board_from_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        holds = sorted(row.get("route_holds") or [], key=lambda item: item.get("sort_order", 0))
        steps = sorted(row.get("route_beta_steps") or [], key=lambda item: item.get("step_index", 0))
        return {
            "saved_id": row["id"],
            "owner_id": row.get("owner_id"),
            "source_type": row.get("source_type") or "manual",
            "visibility": row.get("visibility") or "private",
            "tags": row.get("tags") or [],
            "difficulty": row.get("difficulty") or "V3",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "board_spec": row.get("board_spec"),
            "route_name": row.get("route_name") or "未命名岩板",
            "setter_commentary": row.get("setter_commentary") or "",
            "placed_holds": [item.get("raw") or self._hold_from_row(item) for item in holds],
            "beta_sequence": [item.get("raw") or self._beta_from_row(item) for item in steps],
        }

    def _hold_from_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["coord_id"],
            "x": row["x_label"],
            "y": row["y_index"],
            "hold_type": row["hold_type"],
            "rotation": row.get("rotation") or 0,
            "scale": float(row.get("scale") or 1),
            "is_start": bool(row.get("is_start")),
            "variant": row.get("variant") or "default",
        }

    def _beta_from_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "step": row["step_index"],
            "limb": row["limb"],
            "hold_id": row["hold_coord_id"],
            "intent": row.get("intent") or "Move",
            "is_top": bool(row.get("is_top")),
            "lh": row.get("lh"),
            "rh": row.get("rh"),
            "lf": row.get("lf"),
            "rf": row.get("rf"),
        }
