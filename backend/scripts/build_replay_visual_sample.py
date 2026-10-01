"""Produce honest dynamic previews from existing, non-private evidence masks.

The photos and masks are real; the contact order is deliberately illustrative.
This script never searches .local or calls a model. It is not a substitute for
acceptance on a real video's reviewed contact records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.replay_visual_renderer import (LIMB_COLORS, build_visual_manifest,
                                         render_visual_tail, _screen_labels)


def illustrative_contacts(holds):
    """All four limbs are explicitly scripted; never used for real analysis."""
    ordered = sorted(holds, key=lambda hold: -float(np.mean([p[1] for p in hold["polygon"]])))
    count = min(8, len(ordered))
    selected = [ordered[round(i * (len(ordered) - 1) / max(1, count - 1))] for i in range(count)]
    if count < 4:
        raise ValueError("Four-limb demonstration requires at least four visible holds")
    moves = [(0., "left_foot", 0), (0., "right_foot", 1),
             (0., "left_hand", 2), (0., "right_hand", 3)]
    clock = 1.
    for target in range(4, count):
        hand = "left_hand" if target % 2 == 0 else "right_hand"
        foot = "right_foot" if target % 2 == 0 else "left_foot"
        moves.extend([(clock, hand, target), (clock + 1., foot, target - 2)])
        clock += 2.
    return [{"hold_id": selected[index]["id"], "limb": limb, "start_time_seconds": seconds,
             "source": "illustrative_demo_order"} for seconds, limb, index in moves]


def freeze(source: Path, evidence: Path, directory: Path, fps: int, *, limited=False, excluded=()):
    report = json.loads((evidence / "report.json").read_text(encoding="utf-8"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != report["source_sha256"]:
        raise ValueError("The source photo does not match the existing mask evidence")
    pixels = cv2.imdecode(np.fromfile(str(source), np.uint8), cv2.IMREAD_COLOR)
    h, w = pixels.shape[:2]
    holds = []
    for item in report["objects"]:
        if item["id"] in excluded:
            continue
        mask_path = evidence / f"{item['id']}-mask.png"
        mask = cv2.imdecode(np.fromfile(str(mask_path), np.uint8), cv2.IMREAD_GRAYSCALE)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        polygon = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(float)
        # These historical evidence masks use the working source resolution.
        polygon /= [mask.shape[1], mask.shape[0]]
        holds.append({"id": len(holds) + 1, "polygon": polygon.tolist(), "mask_evidence": str(mask_path.name)})
    contacts = illustrative_contacts(holds)
    result = {"holds": holds, "attempt": {"contacts": contacts}, "analysis_version": "demonstration-not-analysis"}
    reference = directory / "reference.jpg"
    reference.write_bytes(source.read_bytes())
    metadata = {"width": w, "height": h, "source_frame_id": None,
                "source_sha256": report["source_sha256"], "reference_sha256": report["source_sha256"],
                "quality": "limited" if limited else "clear", "demonstration": True,
                "provenance": "Existing project photograph and native historical mask evidence; illustrative contact order"}
    manifest = build_visual_manifest(result, metadata, fps=fps)
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "frozen-input.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return reference, manifest


def write_flat_comparison(reference: Path, manifest: dict, directory: Path):
    """An explicitly labelled flat-map baseline, not a historical job export."""
    w, h = manifest["width"], manifest["height"]
    flat = cv2.VideoWriter(str(directory / "flat-map-demo.webm"), cv2.VideoWriter_fourcc(*"VP80"), manifest["fps"], (w, h))
    cw, ch = w, h // 2
    compare = cv2.VideoWriter(str(directory / "comparison.webm"), cv2.VideoWriter_fourcc(*"VP80"), manifest["fps"], (cw, ch))
    if not flat.isOpened() or not compare.isOpened():
        raise RuntimeError("Video encoder unavailable")
    label_pixels, alpha = _screen_labels(manifest)
    enhanced_capture = cv2.VideoCapture(str(directory / "enhanced.webm"))
    try:
        for index in range(manifest["frame_count"]):
            ok, enhanced = enhanced_capture.read()
            if not ok:
                raise RuntimeError("Enhanced sample did not decode completely")
            canvas = np.full((h, w, 3), (23, 27, 29), np.uint8)
            active = {str(e["hold_id"]): e for e in manifest["events"] if e["tail_time_seconds"] <= index / manifest["fps"]}
            for hold in manifest["holds"]:
                polygon = np.round(np.asarray(hold["polygon"]) * [w - 1, h - 1]).astype(np.int32)
                event = active.get(str(hold["id"]))
                color = LIMB_COLORS[event["limb"]] if event else (75, 82, 85)
                if event:
                    cv2.fillPoly(canvas, [polygon], color, cv2.LINE_AA)
                cv2.polylines(canvas, [polygon], True, color, 2, cv2.LINE_AA)
            canvas = (canvas * (1 - alpha) + label_pixels * alpha).astype(np.uint8)
            flat.write(canvas)
            joined = np.concatenate((cv2.resize(canvas, (w // 2, h // 2)), cv2.resize(enhanced, (w // 2, h // 2))), axis=1)
            cv2.putText(joined, "FLAT MAP DEMO", (12, 18), cv2.FONT_HERSHEY_SIMPLEX, .38, (220, 225, 225), 1, cv2.LINE_AA)
            cv2.putText(joined, "TEXTURED REPLAY", (w // 2 + 12, 18), cv2.FONT_HERSHEY_SIMPLEX, .38, (220, 225, 225), 1, cv2.LINE_AA)
            compare.write(joined)
            if index == manifest["frame_count"] - 1:
                cv2.imencode(".jpg", enhanced)[1].tofile(str(directory / "poster.jpg"))
    finally:
        enhanced_capture.release()
        flat.release()
        compare.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, choices=(24, 30), default=24)
    parser.add_argument("--limited", action="store_true")
    parser.add_argument("--exclude-id", action="append", default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reference, manifest = freeze(args.source, args.evidence, args.output, args.fps, limited=args.limited, excluded=args.exclude_id)
    metrics = render_visual_tail(reference, manifest, args.output / "enhanced.webm")
    write_flat_comparison(reference, manifest, args.output)
    (args.output / "render-metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "index.html").write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>线路回放 · 视觉样片</title><style>body{margin:0;background:#151a18;color:#eceee9;font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:24px}h1{font-size:28px}p{color:#bfc9c2}video{width:100%;max-height:76vh;background:#090e0b;border-radius:12px}section{display:grid;grid-template-columns:1fr 1fr;gap:20px}a{color:#cbe9a8}small{color:#c9ba90}@media(max-width:640px){section{grid-template-columns:1fr}}</style><h1>真实岩壁，按顺序回顾用点</h1><p>8 秒完整动态样片 · CPU 合成 · 原始纹理与轮廓统一运镜</p><small>此样片使用真实岩壁照片和已有岩点轮廓，用点顺序为演示编排，并非真实攀爬记录。左侧为平面呈现对照复刻，并非旧版实测导出。</small><h2>并排动态对照</h2><video controls playsinline preload="metadata" src="comparison.webm"></video><section><article><h2>平面呈现对照</h2><video controls playsinline preload="metadata" src="flat-map-demo.webm"></video></article><article><h2>增强版完整样片</h2><video controls playsinline preload="metadata" poster="poster.jpg" src="enhanced.webm"></video></article></section><p><a href="enhanced.webm" download>下载增强样片</a> · <a href="comparison.webm" download>下载并排对照</a></p><p>待人工观看确认：整体观感、空间感、线路清晰度、画面自然度。真实视频用点记录、目标手机及 4 GiB 服务器验收另行记录。</p></html>''', encoding="utf-8")
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
