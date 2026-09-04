"""Build transparent PNG caches for every local hold source image."""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.hold_image_processing import (  # noqa: E402
    PROCESSING_VERSION,
    SUPPORTED_IMAGE_SUFFIXES,
    ensure_processed_hold_image,
)


DATA_DIR = BACKEND_DIR / "data"
SOURCE_DIR = DATA_DIR / "holds_images"
OUTPUT_DIR = DATA_DIR / "holds_images_processed"
MAPPING_PATH = DATA_DIR / "holds_mapping.json"


def referenced_source_stems() -> set[str]:
    if not MAPPING_PATH.exists():
        return set()
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    stems: set[str] = set()
    processed_suffix = f"_{PROCESSING_VERSION}"
    for variants in mapping.values():
        for image_url in variants.values():
            if not str(image_url).startswith("/images/"):
                continue
            stem = Path(PurePosixPath(str(image_url)).name).stem
            if stem.endswith(processed_suffix):
                stem = stem[: -len(processed_suffix)]
            stems.add(stem)
    return stems


def main() -> int:
    referenced = referenced_source_stems()
    sources = sorted(
        path
        for path in SOURCE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )
    failed: list[str] = []
    unused: list[str] = []

    for source in sources:
        output = ensure_processed_hold_image(source, OUTPUT_DIR)
        label = "已引用" if source.stem in referenced else "未引用"
        if source.stem not in referenced:
            unused.append(source.name)
        if output is None:
            failed.append(source.name)
            print(f"[失败] {source.name}（{label}）")
        else:
            print(f"[完成] {source.name} -> {output.name}（{label}）")

    print(
        f"处理汇总：源图 {len(sources)} 张，成功 {len(sources) - len(failed)} 张，"
        f"失败 {len(failed)} 张，未引用 {len(unused)} 张。"
    )
    if unused:
        print("未引用文件：" + "、".join(unused))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
