"""Register immutable local evidence packages and idempotently create editable drafts."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.hold_image_processing import write_bytes_atomic
from core.photo_route_drafts import PhotoRouteStore, atomic_json
from scripts.evaluate_photo_routes import result_fingerprint


def register_evidence(store, evidence, source_dir, color):
    run = evidence / "v6" / color
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    review = json.loads((run / "review.json").read_text(encoding="utf-8"))
    if result_fingerprint(report) != report["result_sha256"] or review["result_sha256"] != report["result_sha256"]:
        raise ValueError("提取结果和复核指纹不一致")
    if review["source_sha256"] != report["source_sha256"]:
        raise ValueError("复核来源照片不一致")

    def asset(path, expected_hash=None, size=None, alpha=False):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_hash and digest != expected_hash:
            raise ValueError(f"素材指纹不一致：{path.name}")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 40_000_000:
                raise ValueError("素材格式或尺寸无效")
            if size and image.size != tuple(size):
                raise ValueError(f"素材尺寸不一致：{path.name}")
            if alpha and ("A" not in image.getbands() or not image.getchannel("A").getbbox()):
                raise ValueError("抠图缺少有效透明蒙版")
            suffix = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format]
            result = {"filename": f"{digest}.{suffix}", "sha256": digest, "width": image.width, "height": image.height}
        target = store.assets / result["filename"]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("已保存素材被修改，停止导入")
        if not target.exists():
            write_bytes_atomic(target, data)
        return result

    # Report filenames may not escape the explicitly supplied source directory.
    source_path = (source_dir / report["source_name"]).resolve()
    if not source_path.is_relative_to(source_dir.resolve()):
        raise ValueError("来源照片路径无效")
    source = {"original": asset(source_path, report["source_sha256"], report["source_dimensions"]),
              "working_dimensions": report["working_dimensions"], "algorithm": report["algorithm"],
              "result_sha256": report["result_sha256"], "background": None}
    wall = evidence / "wall-v1" / color
    if (wall / "background.png").exists():
        wall_report = json.loads((wall / "report.json").read_text(encoding="utf-8"))
        if wall_report["source_sha256"] != report["source_sha256"]:
            raise ValueError("净化背景来源不一致")
        source["background"] = asset(wall / "background.png", size=report["working_dimensions"])
    judgments = {j["candidate_id"]: j for j in review["judgments"]}
    objects = []
    for entry in report["objects"]:
        obj_id = entry["id"]
        if not re.fullmatch(r"object-\d{2}", obj_id):
            raise ValueError("提取对象编号无效")
        judgment = judgments.get(obj_id)
        if not judgment or not judgment["target_ids"]:
            continue
        objects.append({"id": obj_id, "kind": "volume" if color == "blue" and obj_id == "object-03" else "hold",
                        "cutout": asset(run / f"{obj_id}.png", size=entry["bbox"][2:], alpha=True),
                        "mask": asset(run / f"{obj_id}-mask.png", entry["mask_sha256"], report["working_dimensions"]),
                        "source_bbox_px": entry["bbox"], "z_index": len(objects), "roles": [],
                        "contour_status": "needs_correction" if judgment.get("major_contour_error") else "provisional"})
    manifest = {"name": {"yellow": "黄色线路 · 提取草稿", "blue": "蓝色线路 · 提取草稿"}[color],
                "color": {"yellow": "黄色", "blue": "蓝色"}[color], "source": source, "objects": objects}
    extraction_id = f"{color}-v6-{report['result_sha256'][:12]}"
    target = store.catalog / f"{extraction_id}.json"
    with store.locked():
        if target.exists() and json.loads(target.read_text(encoding="utf-8")) != manifest:
            raise ValueError("提取包已存在且内容不同，不能覆盖")
        if not target.exists():
            atomic_json(target, manifest)
    return extraction_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path(__file__).resolve().parents[2] / "docs/photo-route-evidence")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data/photo_routes")
    parser.add_argument("--owner", default="owner")
    args = parser.parse_args()
    store = PhotoRouteStore(args.data_dir)
    for color in ("yellow", "blue"):
        extraction_id = register_evidence(store, args.evidence, args.source_dir, color)
        draft = store.import_draft(extraction_id, args.owner)
        print(json.dumps({"id": draft["id"], "objects": len(draft["objects"]), "version": draft["version"]}))


if __name__ == "__main__":
    main()
