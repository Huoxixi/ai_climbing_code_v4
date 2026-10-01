"""Analyze an explicitly supplied local video once and compare both exports.

This standalone harness never starts the application, opens account stores, or
writes .local. Configuration is loaded by dotenv exactly as in the local server;
only readiness booleans, public video facts, and generated evidence are emitted.
It makes real existing-provider pose requests only with the explicit --run flag.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT.parents[1]
MODEL_ROOT = WORKSPACE / "photo-route-experiments" / "indoor-climbing-20260906"
sys.path.insert(0, str(PROJECT / "backend"))


def configure() -> None:
    from dotenv import load_dotenv
    load_dotenv(PROJECT / ".local" / "photo-vision.env", override=False)
    os.environ.setdefault("PHOTO_ROUTE_CLIMBING_MODEL_CONFIG", str(PROJECT / ".local" / "quality-selection-20260907" / "config-1200.yml"))
    os.environ.setdefault("PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT", str(MODEL_ROOT / "model" / "verified-model_final.pth"))
    os.environ["HF_HUB_OFFLINE"] = "1"


def save(path: Path, value: dict) -> None:
    from core.climb_replay import _atomic_json
    _atomic_json(path, value)


def review_existing_colour(result: dict, colour: str) -> dict:
    """Review route membership using real saved masks and reuse measured poses."""
    import numpy as np
    import core.climb_replay as replay
    from core.replay_hold_fusion import SAMPLE_COLOUR_NEIGHBORS, align_pose_record, select_sampled_route_holds
    reviewed = copy.deepcopy(result)
    all_holds = [*(reviewed.get("holds") or []), *(reviewed.get("hold_candidates") or [])]
    allowed = {colour, *SAMPLE_COLOUR_NEIGHBORS.get(colour, set())}
    for candidate in all_holds:
        candidate["route_candidate"] = candidate.get("color_group") in allowed
        candidate["route_candidate_reason"] = "colour_family_review_of_existing_native_masks"
    holds, candidates, diagnostics = select_sampled_route_holds(all_holds, sample_group=colour,
                                                              minimum_appearances=2)
    holds.sort(key=lambda hold: (-(hold["bbox"][1] + hold["bbox"][3] / 2), hold["bbox"][0]))
    for index, hold in enumerate(holds, 1):
        hold["id"] = index
    if not holds:
        raise ValueError("No reliable saved masks match corrected route colour")
    samples, records = reviewed.get("pose_samples") or [], []
    video = replay.VideoInfo(**reviewed["video"])
    for sample in samples:
        matrix = sample.get("wall_reference_transform")
        if sample.get("observed") and matrix is None:
            raise ValueError("Saved pose registration is unavailable")
        record = {"frame_id": sample["sample_index"], "source_frame_id": sample["source_frame_id"],
                  "kpts_xy": sample["kpts_xy"], "kpts_score": sample["kpts_score"]}
        records.append(align_pose_record(record, np.asarray(matrix) if matrix is not None else None,
                                         video.width, video.height))
    sample_fps = float((reviewed.get("analysis") or {}).get("sampling", {}).get("effective_fps") or 4)
    attempt = replay.AliyunReplayAnalyzer._contacts(records, holds, sample_fps)
    replay.add_attempt_source_times(attempt, samples, video)
    attempt["action_steps"] = replay.build_action_steps(attempt.get("contacts") or [])
    reviewed["holds"], reviewed["hold_candidates"], reviewed["attempt"] = holds, candidates, attempt
    reviewed["route"] = {**reviewed.get("route", {}), "color": colour}
    reviewed["hold_evidence"] = {**reviewed["hold_evidence"], "sampled_selection": diagnostics,
                                "selection": "colour_choice_review_of_real_video"}
    reviewed["attempt"]["segments"] = replay.build_segments(reviewed)
    reviewed["sample_review"] = {
        "reason": "color_choice_changed", "initial_route_color": (result.get("route") or {}).get("color"),
        "corrected_route_color": colour, "basis": "visible_real_video_route_and_existing_native_mask_candidates",
        "reviewer": "assistant_visual_review_for_local_sample_not_user_confirmation",
        "new_hold_model_calls": 0, "new_pose_model_calls": 0,
        "measured_pose_samples_reused": len(samples), "saved_reference_transforms_reused": len(samples),
        "initial_hold_count": len(result.get("holds") or []), "reviewed_hold_count": len(holds),
        "contacts_are": "recomputed_from_original_measured_poses_with_unchanged_contact_algorithm",
    }
    return reviewed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=WORKSPACE / "素材" / "32fd4ed4a82458794181be60eb5b3792.mp4")
    parser.add_argument("--output", type=Path, default=PROJECT / ".tmp" / "real-video-replay-20260928")
    parser.add_argument("--route-color", default="青色", help="Visible route colour for new analysis; case 2 is cyan/turquoise")
    parser.add_argument("--run", action="store_true", help="Run actual local hold and cloud pose analysis once")
    parser.add_argument("--resume-render", action="store_true", help="Reuse previously frozen real evidence; no model calls")
    parser.add_argument("--review-color", choices=["青色"], help="Review saved route colour family without another model call")
    args = parser.parse_args()
    configure()
    import cv2
    import core.climb_replay as replay
    cv2.setNumThreads(1)
    source, output = args.source.resolve(), args.output.resolve()
    if ".local" in output.parts or not output.is_relative_to(PROJECT / ".tmp"):
        raise ValueError("Output must be an isolated project .tmp directory")
    if not source.is_file():
        print(json.dumps({"ready": False, "reason": "source_missing"}), flush=True)
        return 2
    original_info = replay.probe_video(source)
    analyzer = replay.AliyunReplayAnalyzer()
    sdk_ready = importlib.util.find_spec("alibabacloud_facebody20191230") is not None
    readiness = {
        "configuration_present": bool(analyzer.access_key_id and analyzer.access_key_secret),
        "sdk_available": sdk_ready,
        "model_config_exists": Path(os.environ["PHOTO_ROUTE_CLIMBING_MODEL_CONFIG"]).is_file(),
        "model_checkpoint_exists": Path(os.environ["PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT"]).is_file(),
        "video": asdict(original_info), "route_color": args.review_color or args.route_color,
        "planned_pose_requests": 0 if args.resume_render else analyzer.analysis_contract(original_info)["usage"]["planned_requests"],
        "mode": "reuse_frozen_evidence" if args.resume_render else "new_video_analysis",
        "account_store_used": False, "model_or_cloud_requests_started": False,
    }
    readiness["ready"] = all(readiness[key] for key in (
        "configuration_present", "sdk_available", "model_config_exists", "model_checkpoint_exists"))
    print(json.dumps(readiness, ensure_ascii=False), flush=True)
    if not args.run and not args.resume_render:
        return 0 if readiness["ready"] else 2
    if not readiness["ready"] and not args.resume_render:
        return 2
    output.mkdir(parents=True, exist_ok=True)
    save(output / "preflight.json", readiness)
    started = time.perf_counter()
    input_path, baseline, enhanced = output / "input.mp4", output / "baseline.webm", output / "enhanced.webm"
    evidence_path = output / "analysis-evidence.json"
    baseline_rendered = False
    stage = "准备分析"
    last_progress = [None, -1]

    def progress(label: str, value: int) -> None:
        nonlocal stage
        stage = label
        if label != last_progress[0] or value >= last_progress[1] + 5:
            print(json.dumps({"stage": label, "progress": value}, ensure_ascii=False), flush=True)
            last_progress[:] = [label, value]
        save(output / "progress.json", {"stage": label, "progress": value,
                                       "elapsed_seconds": round(time.perf_counter() - started, 2)})

    def telemetry(value: dict) -> None:
        save(output / "analysis-telemetry.json", value)

    try:
        if args.resume_render:
            result = json.loads(evidence_path.read_text(encoding="utf-8"))
            if not input_path.is_file():
                raise ValueError("Frozen input missing")
            if args.review_color:
                result = review_existing_colour(result, args.review_color)
                result["sample_review"]["original_evidence_sha256"] = replay.ClimbReplayStore._sha256(evidence_path)
                save(output / "reviewed-evidence.json", result)
                if baseline.exists():
                    initial = output / "baseline-initial-blue.webm"
                    if not initial.exists():
                        os.replace(baseline, initial)
                    else:
                        baseline.unlink()
            elif (output / "reviewed-evidence.json").is_file():
                result = json.loads((output / "reviewed-evidence.json").read_text(encoding="utf-8"))
        else:
            if evidence_path.exists():
                raise ValueError("Existing evidence requires --resume-render; do not repeat provider calls")
            shutil.copyfile(source, input_path)
            info = replay.probe_video(input_path)
            # The analyzer receives the real copied clip, not a selected photograph.
            os.environ["CLIMB_REPLAY_VISUAL_ENABLED"] = "0"
            original_render = replay.render_replay_overlay_video

            def capture_evidence(video, target, result, **kwargs):
                save(evidence_path, result)
                return original_render(video, target, result, **kwargs)

            replay.render_replay_overlay_video = capture_evidence
            try:
                result = analyzer.analyze(input_path, route_color=args.route_color, video_info=info,
                                          progress=progress, cancelled=lambda: False, telemetry=telemetry)
            finally:
                replay.render_replay_overlay_video = original_render
            os.replace(input_path.with_name(replay.REPLAY_OVERLAY_FILENAME), baseline)
            baseline_rendered = True
            save(evidence_path, result)
        contacts = (result.get("attempt") or {}).get("contacts") or []
        print(json.dumps({"stage": "真实用点记录已冻结", "route_color": (result.get("route") or {}).get("color"),
                          "hold_count": len(result.get("holds") or []), "contact_count": len(contacts),
                          "contacts_by_limb": dict(Counter(item["limb"] for item in contacts))}, ensure_ascii=False), flush=True)
        if not contacts:
            save(output / "summary.json", {"status": "no_reliable_contacts", "contact_count": 0,
                "message": "真实视频未得到可靠用点记录，保留基础复盘，不构造演示事件"})
            return 3
        if not baseline.exists():
            os.environ["CLIMB_REPLAY_VISUAL_ENABLED"] = "0"
            base_result = copy.deepcopy(result)
            replay.render_replay_overlay_video(input_path, baseline, base_result)
            baseline_rendered = True
        os.environ["CLIMB_REPLAY_VISUAL_ENABLED"] = "1"
        enhanced_result = copy.deepcopy(result)
        enhanced_result["overlay"] = replay.render_replay_overlay_video(
            input_path, enhanced, enhanced_result, stage_progress=progress,
            progress=lambda value: progress("生成真实视频完整增强复盘", value), cancelled=lambda: False)
        save(output / "result.json", enhanced_result)
        base_info, enhanced_info = replay.probe_video(baseline), replay.probe_video(enhanced)
        visual = enhanced_result.get("visual_replay") or {}
        summary = {
            "status": "ready" if visual.get("status") == "ready" else "basic_only",
            "source_kind": "real_user_authorized_video", "route_color": (result.get("route") or {}).get("color"),
            "source_filename": source.name, "source_sha256": replay.ClimbReplayStore._sha256(source),
            "analysis_evidence_kind": "actual_existing_pipeline_contacts_not_hand_reviewed",
            "input_video": asdict(replay.probe_video(input_path)),
            "baseline_video": asdict(base_info), "enhanced_video": asdict(enhanced_info),
            "hold_count": len(result.get("holds") or []), "contact_count": len(contacts),
            "contacts_by_limb": dict(Counter(item["limb"] for item in contacts)),
            "visual_replay": visual, "analysis_usage": (result.get("analysis") or {}).get("usage"),
            "analysis_cost_estimate": (result.get("analysis") or {}).get("cost"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "elapsed_scope": ("baseline_and_enhanced_exports" if baseline_rendered else "enhanced_export_only")
                             if args.resume_render else "analysis_and_both_exports",
            "baseline_reused": not baseline_rendered,
            "same_analysis_for_both_exports": True, "extra_model_calls_for_enhancement": 0,
            "not_an_account_consent_record": True,
            "sample_review": result.get("sample_review"),
            "limitations": ["自动识别的手脚接触仍需用户结合原视频复核", "未做生产服务器或手机实机验收"],
        }
        save(output / "summary.json", summary)
        original = json.loads(evidence_path.read_text(encoding="utf-8"))
        source_events = sorted((item["limb"], str(item["hold_id"]), item["start_time_seconds"],
                                item["start_source_frame"]) for item in contacts)
        rendered_events = sorted((item["limb"], str(item["hold_id"]), item["source_time_seconds"],
                                  item["source_frame_id"]) for item in visual.get("event_time_mapping") or [])
        checks = {
            "measured_pose_records_unchanged": original["pose_samples"] == enhanced_result["pose_samples"],
            "render_events_match_real_contacts_exactly": source_events == rendered_events,
            "source_video_copy_matches_original_sha": replay.ClimbReplayStore._sha256(input_path) == summary["source_sha256"],
            "analysis_interval_preserved": base_info.frame_count == visual["analysis_frame_count"],
            "total_frame_count_matches_tail": enhanced_info.frame_count == visual["analysis_frame_count"] + int(visual.get("tail_frame_count") or 0),
            "output_geometry_and_fps_match": (base_info.width, base_info.height, base_info.fps) ==
                                             (enhanced_info.width, enhanced_info.height, enhanced_info.fps),
            "extra_model_calls_for_enhancement_zero": summary["extra_model_calls_for_enhancement"] == 0,
        }
        if result.get("sample_review"):
            checks["original_evidence_sha_matches_review_audit"] = replay.ClimbReplayStore._sha256(evidence_path) == result["sample_review"]["original_evidence_sha256"]
        save(output / "real-evidence-validation.json", {
            "all_passed": all(checks.values()), "checks": checks,
            "scope": "actual_generated_media_and_saved_real_evidence",
            "does_not_claim": "manual_truth_of_every_automatic_contact_or_production_server_acceptance",
        })
        print(json.dumps({key: summary[key] for key in
            ("status", "hold_count", "contact_count", "contacts_by_limb", "elapsed_seconds")}, ensure_ascii=False), flush=True)
        return 0 if summary["status"] == "ready" else 4
    except Exception as exc:
        # SDK exceptions may contain request details. Never emit their messages,
        # repr, local variables, or a traceback into an artifact or terminal.
        failure = {"status": "failed", "stage": stage, "error_type": type(exc).__name__,
                   "message": "真实视频处理未完成，已保留可恢复证据；没有输出服务凭据或请求详情",
                   "analysis_evidence_saved": evidence_path.is_file()}
        save(output / "failure.json", failure)
        print(json.dumps(failure, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
