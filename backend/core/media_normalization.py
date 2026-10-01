"""Normalize phone photos on the server; the uploaded file on the phone is untouched."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


HEIF_SUFFIXES = {".heic", ".heif"}
HEIF_MIME_TYPES = {"image/heic", "image/heif"}


def is_heif_photo(filename: str, content_type: str = "") -> bool:
    return (Path(filename or "").suffix.lower() in HEIF_SUFFIXES
            or content_type.lower().split(";", 1)[0].strip() in HEIF_MIME_TYPES)


def normalize_photo_bytes(
    data: bytes,
    filename: str,
    content_type: str = "",
    *,
    max_input_bytes: int = 25 * 1024 * 1024,
    max_output_bytes: int = 20 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    """Return JPEG bytes for HEIC/HEIF; leave ordinary photos unchanged."""
    if not is_heif_photo(filename, content_type):
        return data, filename, content_type
    if not data or len(data) > max_input_bytes:
        raise ValueError(f"HEIC 照片不能超过 {max_input_bytes // (1024 * 1024)} MB")
    try:
        from pillow_heif import register_heif_opener
    except ImportError as exc:
        raise RuntimeError("服务器尚未启用 HEIC 解码，请联系管理员检查媒体处理组件") from exc
    register_heif_opener()
    try:
        with Image.open(io.BytesIO(data)) as original:
            if original.format not in {"HEIF", "HEIC"}:
                raise ValueError("文件内容不是有效的 HEIC/HEIF 照片")
            if original.width * original.height > 40_000_000:
                raise ValueError("照片超过 4000 万像素，当前无法处理")
            image = ImageOps.exif_transpose(original).convert("RGB")
            for quality in (90, 82, 72):
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                if output.tell() <= max_output_bytes:
                    name = f"{Path(filename).stem or 'photo'}.jpg"
                    return output.getvalue(), name, "image/jpeg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("HEIC 照片无法解码，文件可能已损坏或使用了当前不支持的编码") from exc
    raise ValueError("照片转换后仍超过处理上限，请选择更小的照片")
