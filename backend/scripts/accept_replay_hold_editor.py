"""Read-only acceptance of the user's fixed ten materials; isolated outputs only.

Run from backend with the local specialist runtime. No real replay jobs, poses,
cloud calls or source media are modified. A batch run is engineering evidence,
not a labeled accuracy score.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import threading
from contextlib import contextmanager

import cv2
import numpy as np
from PIL import Image, ImageDraw

from core.climb_replay import ReplayAnalyzerBase, ClimbReplayStore, probe_video
from core.replay_hold_editor import (EditorFrameRequest, EditorPreviewRequest, editor_frame,
    editor_preview, editor_commit, clear_editor_cache)


@contextmanager
def measured_resources():
    import psutil
    process = psutil.Process()
    metrics = {"process_peak_rss_mib":0, "system_min_available_mib":None}
    done = threading.Event()
    def sample():
        while True:
            rss = process.memory_info().rss / 1024**2
            available = psutil.virtual_memory().available / 1024**2
            metrics["process_peak_rss_mib"] = round(max(metrics["process_peak_rss_mib"],rss),2)
            metrics["system_min_available_mib"] = round(min(metrics["system_min_available_mib"] or available,available),2)
            if done.wait(.05):
                break
    monitor=threading.Thread(target=sample,daemon=True)
    monitor.start()
    try:
        yield metrics
    finally:
        done.set();monitor.join(timeout=1)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def read_at(path, info, seconds):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(info.frame_count - 1, round(seconds * info.fps)))
        ok, image = cap.read()
        if not ok:
            raise RuntimeError("material frame decode failed")
        return image
    finally:
        cap.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--case", type=int)
    parser.add_argument("--focused", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Current 2026-10-06 recuts have a different timeline from the historical
    # parent originals. Treat each current upload as its own immutable source.
    sources = sorted((args.materials / "浏览器兼容版").glob("[0-9][0-9]_*.mp4"))
    if len(sources) != 10:
        raise RuntimeError(f"Expected exactly ten originals, found {len(sources)}")
    manifest = []
    sheet = Image.new("RGB", (1280, 1800), "#17201b")
    draw = ImageDraw.Draw(sheet)
    for index, original in enumerate(sources):
        compatible = original
        if not compatible.is_file():
            raise RuntimeError("Missing browser-compatible material")
        info = probe_video(compatible)
        raw = probe_video(original)
        entry = {"case": index + 1, "name": original.name, "original_sha256": digest(original),
                 "compatible_sha256": digest(compatible), "original_size_wh": [raw.width, raw.height],
                 "compatible_size_wh": [info.width, info.height], "duration": info.duration_seconds}
        manifest.append(entry)
        for col, seconds in enumerate((1, info.duration_seconds * .6)):
            frame = read_at(compatible, info, seconds)
            tile = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tile.thumbnail((310, 330))
            x, y = (index % 2) * 640 + col * 320, (index // 2) * 360
            sheet.paste(tile, (x + (320 - tile.width) // 2, y + 24))
            draw.text((x + 8, y + 5), f"{index+1:02} / {seconds:.2f}s", fill="white")
    (args.output / "materials.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet.save(args.output / "contact.jpg", quality=92)
    print("prepared exactly ten originals and compatible copies", flush=True)
    if args.prepare_only:
        return
    # Colors are review aids, never ground truth. Video samples remain mandatory in production.
    report = []
    for index, (original, entry) in enumerate(zip(sources, manifest)):
        if args.case and args.case != index + 1:
            continue
        compatible = original
        case_dir = args.output / f"case-{index+1:02}"
        case_dir.mkdir(exist_ok=True)
        started = time.monotonic()
        info = probe_video(compatible)
        copy_path = case_dir / "engineering-input.mp4"
        shutil.copy2(compatible, copy_path)
        store = ClimbReplayStore(case_dir / "isolated-store")
        job = store.create(owner="acceptance-local", route_id=None, route_color="待复核", source=copy_path,
            original_name=original.name, info=info, consent={"scope":"engineering-acceptance"}, retention_mode="keep_private_original")
        # Keep the user's untouched source outside the job: the batch only copies it.
        target = store._path(job["id"]).parent / "source.mp4"
        shutil.copy2(original, target)
        draft = {"holds": [], "hold_candidates": [], "hold_evidence":{"reference_frame":0}}
        store.update(job["id"], status="awaiting_hold_review", hold_draft=draft,
            high_resolution_source={"storage_name":"source.mp4", "trim_start_seconds":0, "checksum_sha256":entry["original_sha256"]})
        row = {"case":index+1, "material_sha256":entry["original_sha256"], "checks":{}}
        try:
            frame = editor_frame(store, job["id"], "acceptance-local", EditorFrameRequest())
            row["checks"]["native_resolution"] = [frame["width"], frame["height"]] == entry["original_size_wh"]
            row["checks"]["reference_aligned"] = frame["aligned"]
            # Broad initial region only exercises real local inference; it is not a
            # claim that the intended route or all wall holds have been identified.
            t = time.monotonic()
            regions = [[.23,.55,.38,.62], [.30,.10,.46,.21], [.19,.21,.38,.31],
                       [.23,.30,.48,.39], [.10,.53,.34,.68], [.10,.04,.24,.16],
                       [.46,.75,.63,.87], [.57,.40,.65,.53], [.22,.55,.39,.66], [.74,.47,.92,.62]]
            region = regions[index] if args.focused else [.1,.1,.9,.9]
            row["region_xyxy"] = region
            with measured_resources() as resources:
                preview = editor_preview(store, job["id"], "acceptance-local", EditorPreviewRequest(
                    frame_token=frame["frame_token"], mode="model", region_xyxy=region))
            row["resources"] = resources
            row["retained_upload_mib"] = round(original.stat().st_size / 1024**2,2)
            row["local_seconds"] = round(time.monotonic()-t,3)
            row["local_candidates"] = len(preview["candidates"])
            row["model_version"] = preview.get("model_version")
            row["checks"]["model_executed"] = bool(preview.get("model_version"))
            # Exact-save and identity-preserving revision use a small, declared
            # engineering contour. It must never count as a labeled rock hold.
            shape = [[.45,.45],[.5,.45],[.5,.5],[.475,.48],[.45,.5]]
            manual = editor_preview(store, job["id"], "acceptance-local", EditorPreviewRequest(
                frame_token=frame["frame_token"], mode="manual", polygon=shape))["candidates"][0]
            saved = editor_commit(store, job["id"], "acceptance-local", manual["proposal_id"])
            hold = saved["hold_draft"]["holds"][0]
            row["checks"]["manual_exact_save"] = hold["polygon"] == manual["reference_polygon"]
            row["checks"]["no_pose_or_cloud"] = not saved.get("analysis_runs") and not saved.get("analysis_request")
            newframe = editor_frame(store, job["id"], "acceptance-local", EditorFrameRequest())
            revision = editor_preview(store, job["id"], "acceptance-local", EditorPreviewRequest(
                frame_token=newframe["frame_token"], mode="manual", polygon=[[.45,.45],[.51,.45],[.51,.5],[.45,.5]], hold_id=hold["id"]))["candidates"][0]
            edited = editor_commit(store, job["id"], "acceptance-local", revision["proposal_id"])
            row["checks"]["edit_keeps_identity"] = len(edited["hold_draft"]["holds"]) == 1 and edited["hold_draft"]["holds"][0]["id"] == hold["id"]
            # Save all native candidates for visual review; no route membership claim.
            image = read_at(original, probe_video(original), 0)
            for number, candidate in enumerate(preview["candidates"], 1):
                points = np.rint(np.asarray(candidate["source_polygon"]) * [image.shape[1], image.shape[0]]).astype(np.int32)
                cv2.polylines(image,[points],True,(0,210,255),2)
                cv2.putText(image,str(number),tuple(points[0]),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,210,255),2)
            cv2.imwrite(str(case_dir / "local-candidates.jpg"), image)
            row["status"] = "engineering_pass" if all(row["checks"].values()) else "engineering_failed"
        except Exception as exc:
            row["status"] = "engineering_failed"
            row["error_type"] = type(exc).__name__
            row["error"] = getattr(exc, "detail", "engineering path failed")
        clear_editor_cache(store, job["id"])
        row["source_unchanged"] = digest(original) == entry["original_sha256"] and digest(compatible) == entry["compatible_sha256"]
        row["seconds"] = round(time.monotonic()-started,3)
        report.append(row)
        (args.output / (f"report-case-{args.case:02}.json" if args.case else "report-focused.json" if args.focused else "report.json")).write_text(
            json.dumps({"scope":"ten-material-engineering-acceptance-not-labeled-accuracy", "results":report},ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"case {index+1:02}: {row['status']}; local candidates {row.get('local_candidates', 0)}; {row['seconds']}s",flush=True)
    if any(row["status"] != "engineering_pass" or not row["source_unchanged"] for row in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
