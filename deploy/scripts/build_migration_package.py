#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "backend" / "data"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".private" / "migration"
ALWAYS_EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}
RUNTIME_EXCLUDED_ROOTS = {"demo_backups", "local_simulation"}
TEMPORARY_SUFFIXES = {".tmp", ".pyc", ".pyo"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha() -> str:
    return subprocess.check_output(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def should_include(relative: Path, runtime: bool) -> bool:
    if any(part in ALWAYS_EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.suffix.lower() in TEMPORARY_SUFFIXES:
        return False
    if runtime and relative.parts and relative.parts[0] in RUNTIME_EXCLUDED_ROOTS:
        return False
    return True


def collect_files(data_dir: Path, runtime: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"数据目录中不允许存在符号链接：{path}")
        if path.is_file() and should_include(path.relative_to(data_dir), runtime):
            files.append(path)
    return files


def validate_json_files(files: Iterable[Path]) -> None:
    for path in files:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)


def validate_images(files: Iterable[Path]) -> None:
    try:
        from PIL import Image
    except ImportError:
        try:
            import cv2
            import numpy
        except ImportError as exc:
            raise RuntimeError("生成迁移包需要 Pillow 或 OpenCV。") from exc

        for path in files:
            if (
                path.suffix.lower() in IMAGE_SUFFIXES
                and cv2.imdecode(numpy.fromfile(path, dtype=numpy.uint8), cv2.IMREAD_UNCHANGED)
                is None
            ):
                raise RuntimeError(f"图片无法读取：{path}")
        return

    for path in files:
        if path.suffix.lower() in IMAGE_SUFFIXES:
            with Image.open(path) as image:
                image.verify()


def board_inventory(data_dir: Path) -> list[dict]:
    boards_path = data_dir / "saved_boards.json"
    boards = json.loads(boards_path.read_text(encoding="utf-8"))
    if not isinstance(boards, list):
        raise RuntimeError("saved_boards.json 必须是列表。")

    seen: set[str] = set()
    inventory: list[dict] = []
    for board in boards:
        saved_id = str(board.get("saved_id") or "").strip()
        if not saved_id:
            raise RuntimeError("存在没有 saved_id 的岩板。")
        if saved_id in seen:
            raise RuntimeError(f"岩板 saved_id 重复：{saved_id}")
        seen.add(saved_id)
        inventory.append(
            {
                "saved_id": saved_id,
                "route_name": str(board.get("route_name") or "未命名岩板"),
                "archived": bool(board.get("archived_at")),
                "placed_hold_count": len(board.get("placed_holds") or []),
                "beta_step_count": len(board.get("beta_sequence") or []),
            }
        )
    return inventory


def standard_route_counts() -> tuple[int, int]:
    backend_dir = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_dir))
    os.environ.setdefault("LOCAL_ONLY", "true")
    os.environ.setdefault("DISABLE_SUPABASE", "true")
    os.environ.setdefault("ENABLE_SIMULATION", "false")
    from core.standard_board import load_standard_routes

    routes = load_standard_routes()
    return len(routes), sum(1 for route in routes if route.valid_for_climb)


def file_manifest(files: Iterable[Path], data_dir: Path) -> list[dict]:
    return [
        {
            "path": path.relative_to(data_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]


def write_archive(files: Iterable[Path], data_dir: Path, destination: Path) -> None:
    with destination.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            compresslevel=9,
            mtime=0,
        ) as gzip_handle:
            with tarfile.open(fileobj=gzip_handle, mode="w") as archive:
                for path in files:
                    relative = PurePosixPath("data") / PurePosixPath(
                        path.relative_to(data_dir).as_posix()
                    )
                    info = archive.gettarinfo(str(path), arcname=str(relative))
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = 0
                    info.mode = 0o644
                    with path.open("rb") as source:
                        archive.addfile(info, source)


def write_sha256(path: Path) -> Path:
    checksum_path = Path(f"{path}.sha256")
    checksum_path.write_text(
        f"{sha256_file(path)}  {path.name}\n",
        encoding="utf-8",
    )
    return checksum_path


def build(data_dir: Path, output_root: Path) -> Path:
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        raise RuntimeError(f"数据目录不存在：{data_dir}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root.resolve() / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)

    full_files = collect_files(data_dir, runtime=False)
    runtime_files = collect_files(data_dir, runtime=True)
    validate_json_files(full_files)
    validate_images(full_files)
    boards = board_inventory(data_dir)
    standard_total, standard_valid = standard_route_counts()

    full_archive = output_dir / "full-local-snapshot.tar.gz"
    runtime_archive = output_dir / "runtime-data.tar.gz"
    write_archive(full_files, data_dir, full_archive)
    write_archive(runtime_files, data_dir, runtime_archive)
    write_sha256(full_archive)
    write_sha256(runtime_archive)

    board_path = output_dir / "board-inventory.json"
    board_path.write_text(
        json.dumps(boards, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_git_sha": git_sha(),
        "data_summary": {
            "board_count": len(boards),
            "source_image_count": sum(
                1
                for path in runtime_files
                if path.relative_to(data_dir).parts[:1] == ("holds_images",)
                and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            "processed_image_count": sum(
                1
                for path in runtime_files
                if path.relative_to(data_dir).parts[:1]
                == ("holds_images_processed",)
                and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            "standard_route_count": standard_total,
            "valid_standard_route_count": standard_valid,
        },
        "artifacts": {
            "full-local-snapshot.tar.gz": {
                "size": full_archive.stat().st_size,
                "sha256": sha256_file(full_archive),
                "file_count": len(full_files),
                "source_bytes": sum(path.stat().st_size for path in full_files),
            },
            "runtime-data.tar.gz": {
                "size": runtime_archive.stat().st_size,
                "sha256": sha256_file(runtime_archive),
                "file_count": len(runtime_files),
                "source_bytes": sum(path.stat().st_size for path in runtime_files),
            },
        },
        "runtime_excluded_roots": sorted(RUNTIME_EXCLUDED_ROOTS),
        "runtime_files": file_manifest(runtime_files, data_dir),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = output_dir / "migration-report.txt"
    report.write_text(
        "\n".join(
            [
                "攀岩定线系统本地数据迁移报告",
                f"生成时间：{manifest['created_at']}",
                f"Git 提交：{manifest['source_git_sha']}",
                f"岩板：{len(boards)}",
                f"岩点原图：{manifest['data_summary']['source_image_count']}",
                f"处理图：{manifest['data_summary']['processed_image_count']}",
                f"标准线路：{standard_total}",
                f"当前可攀标准线路：{standard_valid}",
                f"完整快照文件数：{len(full_files)}",
                f"运行迁移文件数：{len(runtime_files)}",
                "状态：本地生成及内容验证通过，等待服务器和 OSS 校验。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成攀岩系统数据迁移包")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_dir = build(args.data_dir, args.output_root)
    except Exception as exc:
        print(f"迁移包生成失败：{exc}", file=sys.stderr)
        return 1
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
