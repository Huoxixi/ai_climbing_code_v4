#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        relative = PurePosixPath(member.name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] != "data"
        ):
            raise RuntimeError(f"压缩包包含不安全路径：{member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError(f"压缩包包含不允许的特殊文件：{member.name}")
        if not member.isfile() and not member.isdir():
            raise RuntimeError(f"压缩包包含未知条目：{member.name}")
    return members


def validate_extracted(data_dir: Path, expected: dict) -> dict:
    for path in data_dir.rglob("*.json"):
        with path.open("r", encoding="utf-8") as handle:
            json.load(handle)

    boards = json.loads((data_dir / "saved_boards.json").read_text(encoding="utf-8"))
    if not isinstance(boards, list):
        raise RuntimeError("saved_boards.json 必须是列表。")
    board_ids = [str(board.get("saved_id") or "") for board in boards]
    if any(not board_id for board_id in board_ids) or len(board_ids) != len(set(board_ids)):
        raise RuntimeError("岩板 saved_id 缺失或重复。")

    try:
        from PIL import Image
    except ImportError:
        try:
            import cv2
            import numpy
        except ImportError as exc:
            raise RuntimeError("验证迁移包需要 Pillow 或 OpenCV。") from exc

        for path in data_dir.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in IMAGE_SUFFIXES
                and cv2.imdecode(
                    numpy.fromfile(path, dtype=numpy.uint8),
                    cv2.IMREAD_UNCHANGED,
                )
                is None
            ):
                raise RuntimeError(f"图片无法读取：{path}")
    else:
        for path in data_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                with Image.open(path) as image:
                    image.verify()

    source_images = sum(
        1
        for path in (data_dir / "holds_images").rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    processed_images = sum(
        1
        for path in (data_dir / "holds_images_processed").rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    actual = {
        "board_count": len(boards),
        "source_image_count": source_images,
        "processed_image_count": processed_images,
    }
    for key, value in actual.items():
        if value != int(expected[key]):
            raise RuntimeError(
                f"{key} 数量不一致：期望 {expected[key]}，实际 {value}"
            )
    return actual


def validate(
    archive_path: Path,
    manifest_path: Path,
    extract_dir: Path,
) -> dict:
    archive_path = archive_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = manifest["artifacts"].get(archive_path.name)
    if not artifact:
        raise RuntimeError(f"manifest.json 未登记 {archive_path.name}")
    actual_hash = sha256_file(archive_path)
    if actual_hash != artifact["sha256"]:
        raise RuntimeError("迁移包 SHA-256 与 manifest.json 不一致。")

    if extract_dir.exists():
        raise RuntimeError(f"解压目标已经存在：{extract_dir}")
    extract_dir.mkdir(parents=True)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = safe_members(archive)
            archive.extractall(extract_dir, members=members, filter="data")
        data_dir = extract_dir / "data"
        actual = validate_extracted(data_dir, manifest["data_summary"])
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise

    return {
        "archive": archive_path.name,
        "sha256": actual_hash,
        **actual,
        "extract_dir": str(extract_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证攀岩系统数据迁移包")
    parser.add_argument("archive", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("extract_dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate(args.archive, args.manifest, args.extract_dir)
    except Exception as exc:
        print(f"迁移包验证失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
