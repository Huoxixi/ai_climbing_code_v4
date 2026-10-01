"""Build a deterministic real-video edit from each job's evidence-linked report.

The Agent describes this attempt; the template owns order, timing and evidence
gates. This pure planner neither calls a model nor reads media or user files.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re

from .replay_coaching_engine import _safe_text
from .replay_summary import LIMBS, build_replay_summary


VERSION = "replay-template-v1"
FPS = 30
MAX_SOURCE_SECONDS = 1800


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _frames(seconds):
    return max(1, math.ceil(seconds * FPS - 1e-8))


def _video(job):
    result = deepcopy(job.get("result") or {})
    video = {**(job.get("video") or {}), **(result.get("video") or {})}
    duration = _number(video.get("duration_seconds"))
    fps, count = _number(video.get("fps")), _number(video.get("frame_count"))
    if duration is None and fps and fps > 0 and count and count > 0:
        duration = count / fps
    if duration is None or not 0 < duration <= MAX_SOURCE_SECONDS:
        raise ValueError("A valid original video duration is required")
    for key in ("width", "height"):
        value = _number(video.get(key))
        if value is None or not value.is_integer() or not 64 <= value <= 8192:
            raise ValueError("Original video dimensions are required")
        video[key] = int(value)
    video["duration_seconds"] = duration
    result["video"] = video
    return result, video


def _anchors(row, duration, *, minimum=2):
    evidence = row.get("evidence")
    if not isinstance(evidence, list) or not minimum <= len(evidence) <= 256:
        return None
    output = []
    for item in evidence:
        if not isinstance(item, dict):
            return None
        key, at = item.get("frame_id"), _number(item.get("time_seconds"))
        if not isinstance(key, str) or not re.fullmatch(r"frame-\d+", key) or at is None or not 0 <= at <= duration:
            return None
        output.append({"frame_id": key, "time_seconds": at})
    times = [row["time_seconds"] for row in output]
    if len({row["frame_id"] for row in output}) != len(output) or times != sorted(times):
        return None
    return output


def _groups(report, duration, native_fps):
    """Use validated first-pass groups only; leave missing intervals explicit."""
    accepted, cursor = [], 0.
    rows = report.get("action_groups")
    for row in rows[:12] if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("evidence_status") != "sampled_observation":
            continue
        start, end = _number(row.get("start_seconds")), _number(row.get("end_seconds"))
        caption = _safe_text(row.get("caption"), observation=True, limit=90)
        anchors = _anchors(row, duration, minimum=3)
        if (start is None or end is None or not cursor <= start < end <= duration or not caption
                or anchors is None or abs(anchors[0]["time_seconds"] - start) > .001
                or abs(anchors[-1]["time_seconds"] - end) > .001):
            continue
        # The sampled final frame represents the final source-frame interval.
        # Extending that exclusive boundary preserves the complete finish.
        if native_fps and native_fps > 0 and duration - end <= 1 / native_fps + .001:
            end = duration
        if start > cursor + 1e-8:
            accepted.append(_unknown_group(cursor, start))
        limb = row.get("limb")
        accepted.append({"start": start, "end": end, "caption": caption,
                         "detail": "抽样画面观察 · 遮挡与帧间细节仍需核对",
                         "evidence_status": "sampled_observation", "evidence": anchors,
                         "focus_limb": limb if isinstance(limb, str) and limb in LIMBS else None})
        cursor = end
    if cursor < duration - 1e-8:
        accepted.append(_unknown_group(cursor, duration))
    return accepted


def _unknown_group(start, end):
    return {"start": start, "end": end,
            "caption": "本段暂缺讲解，保留完整慢放。",
            "detail": "画面依据不足，待核对",
            "evidence_status": "unknown", "evidence": [], "focus_limb": None}


def _tracking(result, duration):
    rows = result.get("pose_samples") or []
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        at = _number(row.get("time_seconds"))
        if at is None or not 0 <= at <= duration:
            continue
        xy, scores = row.get("kpts_xy"), row.get("kpts_score")
        if not isinstance(xy, list) or not isinstance(scores, list) or len(xy) < 17 or len(scores) < 17:
            continue
        clean_xy, clean_scores = [], []
        for point, score in zip(xy[:17], scores[:17]):
            valid = isinstance(point, (list, tuple)) and len(point) == 2
            x, y = (_number(v) for v in point) if valid else (None, None)
            score = _number(score)
            valid = valid and x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1
            clean_xy.append([x, y] if valid else [0., 0.])
            clean_scores.append(min(1., max(0., score)) if valid and score is not None else 0.)
        output.append({"time_seconds": at, "observed": row.get("observed") is True,
                       "kpts_xy": clean_xy, "kpts_score": clean_scores})
    return sorted(output, key=lambda row: row["time_seconds"])


def _side(samples, start, end):
    points = [point[0] for sample in samples if start <= sample["time_seconds"] <= end and sample["observed"]
              for point, confidence in zip(sample["kpts_xy"], sample["kpts_score"]) if confidence >= .5]
    return "left" if not points or sum(points) / len(points) >= .5 else "right"


def _metrics(summary):
    timing, coverage = summary["timing"], summary["coverage"]
    elapsed = timing.get("elapsed_seconds")
    confirmed = elapsed is not None and timing.get("status") not in {"unconfirmed", "unknown", "automatic"}
    outcome = timing.get("outcome", "unconfirmed")
    # A cut-off attempt is not a completed climb even when its observed window
    # was reviewed; label it by observed time, preserving reviewed boundaries.
    known_boundary = confirmed and outcome in {"completed", "topped_out", "fell", "fall", "fallen"}
    timing_metric = {"label": "攀爬用时" if known_boundary else "已观察时长",
                     "value_seconds": elapsed if known_boundary else timing["observed_duration_seconds"],
                     "outcome": outcome, "status": timing.get("status", "unconfirmed")}
    reviewed = summary["provenance"]["contact_source"] == "reviewed_contacts"
    limbs = [{"limb": limb, "label": row["label"],
              "count": row["count"] if reviewed or row["contact_count"] else None,
              "status": "reviewed" if reviewed else "automatic" if row["contact_count"] else "unknown"}
             for limb, row in summary["limbs"].items()]
    totals = {kind: coverage[f"{kind}_seconds"] for kind in ("hold", "transition", "unknown")}
    duration = coverage["duration_seconds"]
    percentages = {kind: round(value / duration * 100, 1) if duration else 0. for kind, value in totals.items()}
    if duration:
        # Round the largest category last so the displayed partition sums to 100.
        largest = max(totals, key=totals.get)
        percentages[largest] = round(100 - sum(value for kind, value in percentages.items() if kind != largest), 1)
    rhythm = {"start_seconds": coverage["start_seconds"], "end_seconds": coverage["end_seconds"],
              "duration_seconds": duration, "totals": totals, "percentages": percentages,
              **{f"{kind}_seconds": value for kind, value in totals.items()},
              "segments": [{key: row[key] for key in ("kind", "start_seconds", "end_seconds")}
                           for row in summary["phases"]]}
    longest = summary.get("longest_hold")
    if longest:
        label = ("最长停留（自动估计）" if longest["status"] == "automatic" else
                 "最长已确认停留" if totals["unknown"] > 0 else "最长停留")
        longest = {"label": label, **{key: longest[key] for key in
                   ("duration_seconds", "start_seconds", "end_seconds", "status")}}
    return {"data_kind": "counts", "timing": timing_metric, "limbs": limbs}, {
        "data_kind": "rhythm", "rhythm": rhythm, "longest_hold": longest}


def _verified_fact(row, duration):
    if not isinstance(row, dict):
        return None
    review = row.get("independent_review") or {}
    if (not isinstance(review, dict) or review.get("status") != "verified" or review.get("visible") is not True
            or review.get("temporal_coverage") is not True or review.get("record_conflict") is not False
            or review.get("label_dependent") is not False
            or row.get("fact_kind") not in {"position_change", "repetition", "sequence", "contact_process"}
            or row.get("review_worthy") is not True):
        return None
    start, end = _number(row.get("start_seconds")), _number(row.get("end_seconds"))
    anchors = _anchors(row, duration, minimum=3)
    caption = _safe_text(row.get("observation"), observation=True, limit=240)
    if (start is None or end is None or not 0 <= start < end <= duration or end - start > 20
            or not anchors or not caption or anchors[0]["time_seconds"] > start + .001
            or anchors[-1]["time_seconds"] < end - .001
            or not any(start < anchor["time_seconds"] < end for anchor in anchors)):
        return None
    return {"start": start, "end": end, "caption": caption, "evidence": anchors, "row": row}


def _allowed_improvement(row, fact, report):
    """Only render the fixed suggestion already admitted by the knowledge gate."""
    if not isinstance(row, dict) or row.get("observation_id") != fact["row"].get("id"):
        return False
    claim, version = row.get("claim_id"), row.get("claim_version")
    versions = (report.get("provenance") or {}).get("knowledge_versions") or {}
    checks = row.get("condition_checks")
    references = row.get("knowledge_refs")
    eligible = _number((report.get("knowledge_status") or {}).get("eligible_advice_claims", 0)) or 0
    if (not isinstance(claim, str) or not claim or not isinstance(versions, dict)
            or versions.get(claim) != version or version is None or eligible <= 0
            or not isinstance(checks, list) or not checks
            or not all(isinstance(check, dict) and check.get("verified") is True for check in checks)
            or not isinstance(references, list) or not any(isinstance(ref, dict)
                and ref.get("claim_id") == claim and ref.get("version") == version for ref in references)
            or fact["row"]["independent_review"].get("normal_explanation") != "ruled_out"):
        return False
    return bool(_safe_text(row.get("adjustment"), limit=500) and _safe_text(row.get("verification"), limit=350))


def build_template_plan(job: dict, report: dict, review: dict | None = None) -> dict:
    """Return an auditable edit using source seconds, never exported play time.

    All first-pass intervals cover the original once, including the finishing
    movement. Sparse/missing evidence produces an honest unknown interval.
    Focused advice must have passed the existing independent-review/claim gate.
    """
    if not isinstance(job, dict) or not isinstance(report, dict):
        raise ValueError("A replay job and evidence-linked report are required")
    result, video = _video(job)
    duration = video["duration_seconds"]
    summary = build_replay_summary(result, review)
    samples = _tracking(result, duration)
    groups = _groups(report, duration, _number(video.get("fps")))
    shots, cursor_frames = [], 0
    notices = []

    def append(kind, start, end, rate, caption, detail, *, length=None, evidence=None,
               evidence_status="unknown", focus_limb=None, **extra):
        nonlocal cursor_frames
        transition_frames = 0 if not shots or kind == "action" else 9
        cursor_frames += transition_frames
        shot_frames = _frames(max((end - start) / rate, length or 0))
        shot = {"id": f"shot-{len(shots) + 1:03d}", "kind": kind,
                "start_seconds": cursor_frames / FPS, "duration_seconds": shot_frames / FPS,
                "source_start_seconds": start, "source_end_seconds": end, "playback_rate": rate,
                "caption": caption, "detail": detail, "caption_side": _side(samples, start, end),
                "evidence_status": evidence_status, "evidence": deepcopy(evidence or []),
                "transition_seconds": transition_frames / FPS, **extra}
        if isinstance(focus_limb, str) and focus_limb in LIMBS:
            shot["focus_limb"] = focus_limb
        shots.append(shot)
        cursor_frames += shot_frames
        return shot

    for group in groups:
        reading = max(2.5, len(group["caption"]) / 7) if group["evidence_status"] != "unknown" else 0
        append("action", group["start"], group["end"], .5, group["caption"], group["detail"],
               evidence=group["evidence"], evidence_status=group["evidence_status"],
               focus_limb=group["focus_limb"], length=reading)
    if any(group["evidence_status"] == "unknown" for group in groups):
        notices.append("部分动作缺少可靠的分组解释，已保留对应原片慢放并标记未知。")
    if any(group["evidence_status"] == "sampled_observation" for group in groups):
        notices.append("首遍讲解来自抽样画面观察；重点段落另需局部复核，不将抽样视为逐帧确认。")

    counts, rhythm = _metrics(summary)
    at = max(0., duration - 1 / max(1., _number(video.get("fps")) or FPS))
    metric = counts["timing"]
    ending = {"completed": "已确认完攀", "topped_out": "已确认完攀", "fell": "到脱落为止", "fallen": "到脱落为止",
              "fall": "到脱落为止", "truncated": "片段提前结束，未确认完攀"}.get(metric["outcome"], "未确认离地与完攀边界")
    append("data", at, at, 1., f'{metric["label"]}约 {metric["value_seconds"]:.1f} 秒',
           ending + " · 四肢分别按不同岩点计数", length=4.5,
           evidence_status="derived_source_evidence", metrics=counts)
    longest = rhythm["longest_hold"]
    detail = (f'{longest["label"]}约 {longest["duration_seconds"]:.1f} 秒' if longest
              else "当前证据不足，未确定最长停留")
    append("data", at, at, 1., "整体攀爬节奏", detail, length=5.,
           evidence_status="derived_source_evidence", metrics=rhythm)

    observations = report.get("observations") if isinstance(report.get("observations"), list) else []
    improvements = report.get("improvements") if isinstance(report.get("improvements"), list) else []
    facts = [fact for row in observations if (fact := _verified_fact(row, duration))]
    # The verified selected adjustment is revisited first; remaining observations
    # are not relabelled as mistakes or assigned invented practice instructions.
    facts.sort(key=lambda fact: not any(_allowed_improvement(row, fact, report) for row in improvements))
    focus_count, advice_count = 0, 0
    for fact in facts:
        if focus_count == 2:
            break
        row = fact["row"]
        adjustment = next((item for item in improvements if _allowed_improvement(item, fact, report)), None)
        pages = [(fact["caption"], "重点回看 · 已复核的画面观察")]
        if adjustment:
            pages.extend([(_safe_text(adjustment["adjustment"], limit=500), "下一次可尝试的调整"),
                          (_safe_text(adjustment["verification"], limit=350), "下次练习时核对这一点")])
            advice_count += 1
        else:
            question = _safe_text(row.get("review_question"), observation=True, limit=160)
            if question:
                pages.append((question, "回看时核对 · 暂不提出动作修改"))
        steps, reading_frames = [], 0
        for caption, detail in pages:
            length_frames = _frames(max(3., len(caption) / 5.5))
            steps.append({"start_seconds": reading_frames / FPS,
                          "end_seconds": (reading_frames + length_frames) / FPS,
                          "caption": caption, "detail": detail})
            reading_frames += length_frames
        span_frames = _frames((fact["end"] - fact["start"]) / .5)
        total_frames = max(reading_frames, span_frames)
        steps[-1]["end_seconds"] = total_frames / FPS
        append("focus", fact["start"], fact["end"], .5, pages[0][0], pages[0][1],
               length=total_frames / FPS, evidence=fact["evidence"], evidence_status="independently_verified",
               focus_limb=row.get("limb"), caption_steps=steps,
               observation_id=row.get("id"), claim_id=adjustment["claim_id"] if adjustment else None)
        focus_count += 1
    if not focus_count:
        notices.append("尚无通过局部复核的重点动作，未补造重点回放或修改建议。")
    if not advice_count:
        notices.append("本次没有通过知识和适用条件检查的修改建议；当前仅提供观察与数据。")
        shots[-1]["detail"] += "\n尚无可靠修改建议"
    if cursor_frames / FPS > 7200:
        raise ValueError("Template exceeds render duration budget")
    return {"version": VERSION, "width": video["width"], "height": video["height"], "fps": FPS,
            "source_duration_seconds": duration, "duration_seconds": cursor_frames / FPS,
            "frame_count": cursor_frames, "tracking_samples": samples, "summary": summary,
            "notices": notices, "shots": shots, "provenance": {
                "timing_basis": "source_video_timestamps", "analysis_version":
                    (report.get("provenance") or {}).get("analysis_version"),
                "action_group_source": "agent_sampled_observations", "review_applied": review is not None}}
