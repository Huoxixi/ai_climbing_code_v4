"""Reversible owner revisions stored on action results, never on source tracks."""
from copy import deepcopy
import math
import uuid
from .replay_action_naming import ACTIONS, CONDITIONS, LIMB_NAMES, enrich_names, finite, hold_key


def revise_result(original, payload, actor):
    result = enrich_names(original)
    group = next((g for g in result["groups"] if g["id"] == payload["group_id"]), None)
    if group is None:
        raise ValueError("动作片段已变化，请重新选择")
    event_id = payload.get("event_id")
    previous = next((e for e in group["events"] if e.get("id") == event_id), None) if event_id else None
    if event_id and previous is None:
        raise ValueError("动作已变化，请重新选择")
    limb, action = payload["limb"], payload["action"]
    if limb not in LIMB_NAMES or action not in ACTIONS:
        raise ValueError("请选择词典中的肢体和动作")
    start, end = payload["start_seconds"], payload["end_seconds"]
    duration = result["source_duration_seconds"]
    if not finite(start) or not finite(end) or not group["start_seconds"] <= start < end <= min(duration, group["end_seconds"]):
        raise ValueError("动作起止须位于当前原片片段内")
    holds = {hold_key(h.get("id")) for h in result.get("holds", [])}
    source, target = hold_key(payload.get("source_hold_id")), hold_key(payload.get("target_hold_id"))
    if any(k and k not in holds for k in (source, target)):
        raise ValueError("所选岩点不属于当前分析版本")
    required = {"contact": target, "release": source, "readjust": source, "attempt": target}
    if action in required and not required[action]:
        raise ValueError("该动作需要确认相应岩点")
    if action == "readjust" and target and source != target:
        raise ValueError("原点调整不能填写不同的终点")
    at = payload.get("contact_seconds")
    if at is not None and (not finite(at) or not start <= at <= end):
        raise ValueError("接触时刻须位于动作内")
    at = end if at is None else at
    video = result["video"]
    fps = video["fps"]
    last = video["frame_count"] - 1
    evidence = [{"frame_id": f"frame-{i}", "time_seconds": round(i / fps, 6)}
                for i in sorted({min(last, max(0, round(t * fps))) for t in (start, (start + end) / 2, end)})]
    facts = []
    def fact(kind, hold, left, right):
        facts.append({"kind": kind, "hold_id": hold, "start_seconds": left, "end_seconds": right,
                      "status": "human_confirmed", "evidence": evidence, "reviewer": actor})
    if source and action not in {"wall_contact", "attempt"}:
        fact("source_contact", source, start, at)
    if action == "release":
        fact("release", source, start, at)
    elif action == "readjust":
        fact("readjust", source, start, at)
    elif action == "attempt":
        fact("attempt", target, start, at)
    elif action == "wall_contact":
        fact("wall_contact", None, start, at)
    elif target:
        fact("target_contact", target, at, end)
    tags = payload.get("technique_codes", [])
    if not isinstance(tags, list) or len(tags) > 8 or any(t not in CONDITIONS for t in tags) or len(set(tags)) != len(tags):
        raise ValueError("请选择词典中的技术标签")
    event = {"id": event_id or f"{group['id']}-manual-{uuid.uuid4().hex[:12]}", "limb": limb, "action": action,
             "start_seconds": start, "end_seconds": end, "evidence": evidence, "facts": facts,
             "evidence_status": "human_confirmed", "event_status": "human_confirmed", "reviewer": actor,
             "technique_tags": [{"code": t, "name": CONDITIONS[t][0], "status": "human_confirmed", "reviewer": actor, "evidence": evidence} for t in tags],
             "direction": payload.get("direction") if payload.get("direction") in {"up", "down", "left", "right"} else None}
    if previous:
        event["previous_limb"] = previous.get("previous_limb", previous["limb"])
        group["events"][group["events"].index(previous)] = event
    else:
        group["events"].append(event)
    group["events"].sort(key=lambda e: (e["start_seconds"], e["end_seconds"], e["id"]))
    group.update(evidence_status="locally_verified", coverage_status="human_reviewed")
    return enrich_names(result)


def corrected_contact_evidence(result, source):
    """Replace reviewed intervals only; keep untouched automatic evidence marked."""
    output = deepcopy(source)
    rows = deepcopy((source.get("attempt") or {}).get("contacts", []))
    for group in result["groups"]:
        for event in group["events"]:
            if event.get("event_status") != "human_confirmed":
                continue
            left, right = event["start_seconds"], event["end_seconds"]
            kept = []
            # A side correction invalidates both the old and the replacement
            # chain in that interval. Other limbs keep their original evidence.
            limbs = {event["limb"], event.get("previous_limb", event["limb"])}
            for row in rows:
                start, end = row.get("start_time_seconds"), row.get("end_time_seconds")
                if row.get("limb") not in limbs or not finite(start) or not finite(end) or end <= left or start >= right:
                    kept.append(row)
                else:
                    if start < left:
                        kept.append({**row, "end_time_seconds": left})
                    if end > right:
                        kept.append({**row, "start_time_seconds": right})
            rows = kept
            for fact in event["facts"]:
                if fact["kind"] not in {"source_contact", "target_contact", "readjust"} or not fact["hold_id"]:
                    continue
                start, end = fact["start_seconds"], fact["end_seconds"]
                # A final-frame confirmed contact remains a touch, not an
                # invented held interval extending into the unseen future.
                if end <= start:
                    start = max(left, end - min(1 / result["video"]["fps"], .01))
                if end > start:
                    rows.append({"limb": event["limb"], "hold_id": fact["hold_id"], "start_time_seconds": start,
                                 "end_time_seconds": end, "basis": "human_action_review"})
    output.setdefault("attempt", {})["contacts"] = rows
    return output
