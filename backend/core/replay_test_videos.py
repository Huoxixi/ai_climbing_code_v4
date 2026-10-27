"""Configured acceptance videos, live file metadata and private responses."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse


class ReplayTestVideoCatalog:
    """Capture configured cases once; inspect local file availability on each read."""

    def __init__(
        self,
        test_video_cases: list[dict[str, Any]] | None = None,
        test_video_path: Path | None = None,
        test_video_source_url: str | None = None,
    ):
        configured_test_videos: list[dict[str, Any]] = []
        for index, item in enumerate(test_video_cases or []):
            path_value = item.get("path")
            case_id = str(item.get("id") or f"case-{index + 1}").strip()
            if not path_value or not case_id or not all(
                    char.isalnum() or char in {"-", "_"} for char in case_id):
                continue
            configured_test_videos.append({
                "id": case_id,
                "label": str(item.get("label") or f"本地案例 {index + 1}").strip(),
                "description": str(item.get("description") or "本地验收素材").strip(),
                "path": Path(path_value).resolve(),
                "comparison_path": (Path(item["comparison_path"]).resolve()
                                    if item.get("comparison_path") else None),
                "comparison_route_color": str(item.get("comparison_route_color") or "").strip(),
                "comparison_action_count": int(item.get("comparison_action_count") or 0),
                "source_url": item.get("source_url"),
            })
        if not configured_test_videos and test_video_path:
            configured_test_videos.append({
                "id": "case-1",
                "label": "本地案例 1",
                "description": "本地验收素材",
                "path": Path(test_video_path).resolve(),
                "comparison_path": None,
                "comparison_route_color": "",
                "comparison_action_count": 0,
                "source_url": test_video_source_url,
            })
        self._configured_test_videos = configured_test_videos

    def available_test_videos(self) -> list[dict[str, Any]]:
        return [item for item in self._configured_test_videos
                if item["path"].is_file() and item["path"].suffix.lower() == ".mp4"]

    @staticmethod
    def public_test_video(item: dict[str, Any]) -> dict[str, Any]:
        path = item["path"]
        return {
            "id": item["id"],
            "label": item["label"],
            "description": item["description"],
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "comparison_available": bool(
                item.get("comparison_path")
                and item["comparison_path"].is_file()
                and item["comparison_path"].suffix.lower() == ".webm"
            ),
            "comparison_route_color": item.get("comparison_route_color") or None,
            "comparison_action_count": item.get("comparison_action_count") or None,
            "source_url": item.get("source_url"),
            "usage": "local_acceptance_only",
        }

    @staticmethod
    def test_video_response(item: dict[str, Any]) -> FileResponse:
        return FileResponse(
            item["path"],
            media_type="video/mp4",
            filename=item["path"].name,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @staticmethod
    def comparison_video_response(item: dict[str, Any], *, download: bool) -> FileResponse:
        path = item.get("comparison_path")
        if not path or not path.is_file() or path.suffix.lower() != ".webm":
            raise HTTPException(404, "最新对照版视频不存在")
        return FileResponse(
            path,
            media_type="video/webm",
            filename=path.name if download else None,
            content_disposition_type="attachment" if download else "inline",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
