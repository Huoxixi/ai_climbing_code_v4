"""Controlled observational vocabulary; no coaching or force inference.

Pose backends and knowledge retrieval never grant a technique approval. All
machine technique detections remain candidates until a real holdout audit.
"""
from copy import deepcopy
import math

NAMING_VERSION = "replay-action-names-v2"
LIMB_NAMES = {"left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚"}
ACTIONS = {"move_up", "move", "adjust", "reach", "lift", "contact", "release", "readjust", "attempt", "wall_contact"}
CONDITIONS = {
    "CROSS": ("交叉手", "Cross", "KB-HAND-004", ["path_visible", "retained_hand_visible", "midline_crossed"]),
    "HIGH_STEP": ("高抬脚", "High step", "KB-FOOT-006", ["body_scale_reliable", "high_foot_visible", "target_contact_visible"]),
    "HIP_TURN": ("侧身转髋", "Hip rotation", "KB-BODY-001", ["shoulders_hips_visible", "rotation_sequence_visible"]),
    "OUTSIDE_FLAG": ("外侧旗式", "Outside flag", "KB-BODY-002", ["support_foot_visible", "free_leg_visible", "lateral_extension_visible"]),
    "BACK_FLAG": ("后旗式", "Back flag", "KB-BODY-003", ["support_foot_visible", "free_leg_visible", "behind_relation_visible"]),
    "INSIDE_FLAG": ("内侧旗式", "Inside flag", "KB-BODY-003", ["support_foot_visible", "free_leg_visible", "front_relation_visible"]),
    "DROP_KNEE": ("沉膝／埃及式", "Drop knee", "KB-BODY-004", ["foot_contact_visible", "knee_rotation_visible", "hip_rotation_visible"]),
    "ROCK_OVER": ("移髋过脚", "Rock over", "KB-FOOT-005", ["foot_contact_visible", "hip_over_foot_sequence_visible"]),
    "HEEL_HOOK": ("勾脚跟", "Heel hook", None, ["heel_contact_detail_visible", "contact_sequence_visible"]),
    "TOE_HOOK": ("勾脚尖", "Toe hook", None, ["toe_upper_contact_detail_visible", "contact_sequence_visible"]),
    "MANTLE": ("撑上", "Mantle", None, ["hand_press_sequence_visible", "edge_visible", "body_over_edge_visible"]),
    "DYNAMIC_REACH": ("动态够点", "Dynamic reach", "KB-DYN-001", ["dense_source_frames", "launch_sequence_visible", "target_contact_visible"]),
    "DYNO": ("跳跃", "Dyno", "KB-DYN-001", ["dense_source_frames", "all_support_release_visible", "flight_visible", "target_contact_visible"]),
    "DOUBLE_DYNO": ("双手跳跃", "Double dyno", "KB-DYN-001", ["dense_source_frames", "both_hands_release_visible", "flight_visible", "both_hands_contact_visible"]),
}
RELATION_LABELS = {"HAND_MATCH": "双手并点", "FOOT_MATCH": "双脚并点", "HAND_SWAP": "换手", "FOOT_SWAP": "换脚", "BUMP": "连续换点", "SIMULTANEOUS": "同步动作"}
THRESHOLDS = {"swap_gap_seconds": .5, "contact_overlap_seconds": .1, "simultaneous_seconds": .15, "bump_gap_seconds": .3}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def hold_key(value):
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and value not in ("", "unknown") else None


def catalogue():
    return {"version": NAMING_VERSION, "actions": sorted(ACTIONS), "limbs": LIMB_NAMES,
            "techniques": [{"code": code, "name": row[0], "english": row[1], "unit_id": row[2],
                            "required_conditions": row[3], "automatic_confirmation": False}
                           for code, row in CONDITIONS.items()], "thresholds": THRESHOLDS,
            "validation_status": "independent_video_review_pending"}


def anchors(ids, frames, start, end, minimum=2):
    if not isinstance(ids, list) or len(ids) < minimum or len(ids) > 64 or any(not isinstance(k, str) for k in ids):
        return None
    if len(set(ids)) != len(ids) or any(k not in frames for k in ids):
        return None
    times = [frames[k].get("time_seconds") for k in ids]
    if any(not finite(t) for t in times) or times != sorted(times) or not start <= times[0] < times[-1] <= end:
        return None
    return [{"frame_id": k, "time_seconds": frames[k]["time_seconds"]} for k in ids]


def checked_details(event, check, frames, holds):
    """Agreement is checked per fact, never inherited from event verification."""
    result = {"facts": [], "technique_tags": [], "direction": None}
    start, end = event["start_seconds"], event["end_seconds"]
    allowed_holds = {hold_key(h.get("id")) for h in holds}
    allowed_holds.discard(None)
    facts, checks = event.get("facts", []), check.get("facts", [])
    if not isinstance(facts, list) or not isinstance(checks, list):
        facts, checks = [], []
    for fact in facts[:12]:
        if not isinstance(fact, dict) or not isinstance(fact.get("kind"), str) or fact.get("kind") not in {"source_contact", "target_contact", "release", "readjust", "attempt", "wall_contact"}:
            continue
        evidence = anchors(fact.get("frame_ids"), frames, start, end)
        key = hold_key(fact.get("hold_id"))
        if not evidence or (fact["kind"] != "wall_contact" and key not in allowed_holds):
            continue
        if fact["kind"] != "wall_contact" and any(not any(hold_key(r.get("hold_id")) == key for r in frames[anchor["frame_id"]].get("hold_regions", [])) for anchor in evidence):
            continue
        matching = [c for c in checks if isinstance(c, dict) and c.get("kind") == fact["kind"] and hold_key(c.get("hold_id")) == key]
        if len(matching) != 1 or matching[0].get("state") != "satisfied":
            continue
        checked = anchors(matching[0].get("frame_ids"), frames, start, end)
        # The checker must inspect every proposed anchor, not a disjoint moment.
        if not checked or not set(fact["frame_ids"]) <= set(matching[0]["frame_ids"]):
            continue
        result["facts"].append({"kind": fact["kind"], "hold_id": key, "evidence": evidence,
                                "start_seconds": evidence[0]["time_seconds"], "end_seconds": evidence[-1]["time_seconds"],
                                "status": "locally_verified"})
    direction = event.get("direction")
    if isinstance(direction, str) and direction in {"up", "down", "left", "right"} and check.get("direction") == direction and check.get("direction_state") == "satisfied":
        points = [frames[k].get('wall_limb_points', {}).get(event.get('limb')) for k in event.get('frame_ids', [])]
        if len(points) >= 3 and all(isinstance(p, list) and len(p) == 2 and all(finite(v) for v in p) for p in points):
            dx, dy = points[-1][0]-points[0][0], points[-1][1]-points[0][1]
            observed = ('left' if dx < 0 else 'right') if abs(dx) > max(.025, abs(dy)*1.2) else ('up' if dy < 0 else 'down') if abs(dy) > max(.025, abs(dx)*1.2) else None
            if observed == direction:
                result['direction'] = direction
    proposed, verified = event.get("techniques", []), check.get("techniques", [])
    if not isinstance(proposed, list) or not isinstance(verified, list):
        return result
    for code in dict.fromkeys(t.get("code") for t in proposed if isinstance(t, dict) and isinstance(t.get("code"), str)):
        if code not in CONDITIONS:
            continue
        p = [t for t in proposed if isinstance(t, dict) and t.get("code") == code]
        c = [t for t in verified if isinstance(t, dict) and t.get("code") == code]
        if len(p) != 1 or len(c) != 1:
            continue
        evidence = anchors(p[0].get("frame_ids"), frames, start, end, 3)
        proof = anchors(c[0].get("frame_ids"), frames, start, end, 3)
        required = CONDITIONS[code][3]
        proposed_conditions, checked_conditions = p[0].get("conditions"), c[0].get("conditions")
        if (not evidence or not proof or not set(p[0]["frame_ids"]) <= set(c[0]["frame_ids"])
                or not isinstance(proposed_conditions, dict) or not isinstance(checked_conditions, dict)
                or c[0].get("conflict") is not False or c[0].get("occluded") is not False
                or any(proposed_conditions.get(k) != "satisfied" or checked_conditions.get(k) != "satisfied" for k in required)):
            continue
        result["technique_tags"].append({"code": code, "name": CONDITIONS[code][0], "status": "candidate",
                                         "conditions": {k: "satisfied" for k in required}, "evidence": evidence,
                                         "unit_id": CONDITIONS[code][2]})
    return result


def event_parts(event):
    """Generate only controlled words. Contact is never described before its time."""
    limb, action = event.get("limb"), event.get("action")
    if limb not in LIMB_NAMES or action not in ACTIONS:
        return []
    hand = limb.endswith("hand")
    prefix = "HAND" if hand else "FOOT"
    action_code = {"contact": "CONTACT", "release": "RELEASE", "readjust": "READJUST", "attempt": "ATTEMPT", "wall_contact": "WALL" if hand else "SMEAR"}.get(action, "READJUST" if action == "adjust" else "MOVE")
    event["base_action_code"] = prefix + "_" + action_code
    event["motion_phase"] = action
    motion = {"move_up": "向上伸手" if hand else "抬脚", "move": "伸手" if hand else "移脚",
              "adjust": "调整手部位置" if hand else "调整脚部位置", "reach": "伸手够点" if hand else "移脚靠近目标",
              "lift": "抬手" if hand else "抬脚", "contact": "伸手靠近目标" if hand else "移脚靠近目标",
              "release": "离点过程", "readjust": "调整手部位置" if hand else "调整脚部位置",
              "attempt": "伸手靠近目标" if hand else "移脚靠近目标", "wall_contact": "移向墙面"}[action]
    direction = event.get("direction")
    if direction in {"up", "down", "left", "right"} and action in {"move", "reach", "lift"}:
        motion = {"up": "向上", "down": "向下", "left": "向左", "right": "向右"}[direction] + ("伸手够点" if hand else "移脚")
    trajectory = event.get("trajectory_details") or {}
    use_trajectory = trajectory.get("status") == "observed" and event.get("event_status") != "human_confirmed"
    if use_trajectory:
        motion = trajectory.get("summary", motion)
    elif trajectory.get("status") in {"stationary", "body_carried", "conflict"} and event.get("event_status") != "human_confirmed":
        # A legacy visual label is retained in the audit object. Its wording is
        # not repeated as a new fact when the independent pose channel conflicts.
        motion = "动作细节待复核"
    facts = event.get("facts", [])
    parts = [{"start_seconds": event["start_seconds"], "end_seconds": event["end_seconds"], "text": motion}]
    source = next((f for f in facts if f["kind"] == "source_contact"), None)
    target = next((f for f in facts if f["kind"] == "target_contact"), None)
    final_fact = target
    if target:
        text = "接触岩点" if hand else "落到脚点"
        event["target_hold_id"] = target["hold_id"]
        if source:
            event["source_hold_id"] = source["hold_id"]
            if source["hold_id"] != target["hold_id"]:
                event["base_action_code"] = prefix + "_MOVE"
        text += " " + target["hold_id"]
    else:
        final_fact = next((f for f in facts if f["kind"] in {"release", "readjust", "attempt", "wall_contact"}), None)
        if final_fact:
            text = {"release": "离开岩点", "readjust": "原点重新抓握" if hand else "原点重新踩放",
                    "attempt": "触及后未保留接触" if hand else "踩到后未保留接触", "wall_contact": "接触墙面"}[final_fact["kind"]]
            if final_fact["kind"] != "wall_contact":
                text += " " + final_fact["hold_id"]
    if final_fact:
        boundary = final_fact["start_seconds"] if target else final_fact["end_seconds"]
        if event["start_seconds"] < boundary < event["end_seconds"]:
            parts[0]["end_seconds"] = boundary
            parts.append({"start_seconds": boundary, "end_seconds": event["end_seconds"], "text": text})
        elif boundary <= event["start_seconds"]:
            parts[0]["text"] = text
        else:
            # Preserve the landing at the final observed anchor; no backdating.
            parts.append({"start_seconds": boundary, "end_seconds": boundary, "text": text})
    if use_trajectory and trajectory.get("phases"):
        boundary = (final_fact["start_seconds"] if target else final_fact["end_seconds"]) if final_fact else event["end_seconds"]
        phases = []
        for phase in trajectory["phases"]:
            start = max(event["start_seconds"], phase["start_seconds"])
            end = min(boundary, event["end_seconds"], phase["end_seconds"])
            if end > start:
                phases.append({"start_seconds": start, "end_seconds": end, "text": phase["text"]})
        if phases:
            if phases[0]["start_seconds"] > event["start_seconds"]:
                phases.insert(0, {"start_seconds": event["start_seconds"], "end_seconds": phases[0]["start_seconds"], "text": motion})
            if phases[-1]["end_seconds"] < boundary:
                phases.append({"start_seconds": phases[-1]["end_seconds"], "end_seconds": boundary, "text": "末端位置变化继续，接触未确认"})
            parts = phases + ([parts[-1]] if final_fact else [])
    event['contact_status'] = 'human_confirmed' if any(f.get('status') == 'human_confirmed' for f in facts) else 'locally_verified' if facts else 'unknown'
    event['base_action_status'] = event['contact_status'] if final_fact else 'motion_only'
    for tag in event.get("technique_tags", []):
        if tag.get("status") == "human_confirmed" and tag.get("code") in CONDITIONS:
            parts[-1]["text"] += " · " + CONDITIONS[tag["code"]][0] + "（人工确认）"
            break  # The remaining reviewed labels stay in the event detail.
    return parts


def enrich_names(organized):
    from .replay_action_trajectory import enrich_trajectories
    output = enrich_trajectories(organized)
    events = []
    for group in output.get("groups", []):
        for index, event in enumerate(group.get("events", [])):
            event.setdefault("id", f"{group['id']}-event-{index + 1:03d}")
            event.setdefault("facts", [])
            event.setdefault("technique_tags", [])
            event.setdefault("event_status", event.get("evidence_status", "needs_review"))
            event["naming_version"] = NAMING_VERSION
            # Derived contact identities must be rebuilt after every correction.
            event.pop("source_hold_id", None)
            event.pop("target_hold_id", None)
            event["caption_parts"] = event_parts(event)
            trajectory = event.get("trajectory_details") or {}
            display = trajectory["summary"] if trajectory.get("status") == "observed" and event.get("event_status") != "human_confirmed" and not event.get("target_hold_id") else event["caption_parts"][-1]["text"] if event["caption_parts"] else ""
            event["display_name"] = LIMB_NAMES.get(event.get("limb"), "") + display
            event["relations"] = []
            events.append(event)
        visible = [e for e in group.get("events", []) if e.get("caption_parts")]
        if visible:
            text = visible[0]["display_name"]
            for previous, current in zip(visible, visible[1:]):
                conjunction = "，同时" if current["start_seconds"] < previous["end_seconds"] else "，随后"
                if len(text + conjunction + current["display_name"]) <= 60:
                    text += conjunction + current["display_name"]
            group["description"] = text
    relations = []
    contacts = [(e, f) for e in events for f in e.get("facts", []) if f["kind"] in {"source_contact", "target_contact"}]
    def add(code, a, b, start, end, hold=None, status="locally_verified"):
        if a["id"] == b["id"]:
            return
        ids = sorted([a["id"], b["id"]])
        key = code + ":" + ":".join(ids) + ":" + str(hold)
        if any(r["id"] == key for r in relations):
            return
        relation = {"id": key, "code": code, "name": RELATION_LABELS[code], "event_ids": ids,
                    "start_seconds": start, "end_seconds": end, "hold_id": hold, "status": status}
        relations.append(relation)
        a["relations"].append(relation)
        b["relations"].append(relation)
    for i, (a, fa) in enumerate(contacts):
        for b, fb in contacts[i + 1:]:
            if a["limb"] == b["limb"] or a["limb"].split("_")[-1] != b["limb"].split("_")[-1] or fa["hold_id"] != fb["hold_id"]:
                continue
            left, right = max(fa["start_seconds"], fb["start_seconds"]), min(fa["end_seconds"], fb["end_seconds"])
            if right - left >= THRESHOLDS["contact_overlap_seconds"]:
                add("HAND_MATCH" if a["limb"].endswith("hand") else "FOOT_MATCH", a, b, left, right, fa["hold_id"])
    for a in events:
        releases = [f for f in a["facts"] if f["kind"] == "release"]
        for b, target in contacts:
            if a["limb"] == b["limb"] or a["limb"].split("_")[-1] != b["limb"].split("_")[-1] or target["kind"] != "target_contact":
                continue
            for release in releases:
                gap = target["start_seconds"] - release["end_seconds"]
                # A prior match is recorded as a match followed by release.
                prior_match = any(r["code"] in {"HAND_MATCH", "FOOT_MATCH"} and set(r["event_ids"]) == {a["id"], b["id"]} for r in relations)
                if release["hold_id"] == target["hold_id"] and 0 <= gap <= THRESHOLDS["swap_gap_seconds"] and not prior_match:
                    add("HAND_SWAP" if a["limb"].endswith("hand") else "FOOT_SWAP", a, b, release["end_seconds"], target["start_seconds"], target["hold_id"])
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            if a["limb"] != b["limb"]:
                left, right = max(a["start_seconds"], b["start_seconds"]), min(a["end_seconds"], b["end_seconds"])
                if right - left >= THRESHOLDS["simultaneous_seconds"] and "trajectory_observed" not in {a.get("evidence_status"), b.get("evidence_status")}:
                    add("SIMULTANEOUS", a, b, left, right)
    for limb in LIMB_NAMES:
        chain = sorted([e for e in events if e["limb"] == limb], key=lambda e: e["start_seconds"])
        for a, b in zip(chain, chain[1:]):
            gap = b["start_seconds"] - a["end_seconds"]
            if 0 <= gap <= THRESHOLDS["bump_gap_seconds"] and a.get("target_hold_id") and b.get("target_hold_id") and a["target_hold_id"] != b["target_hold_id"]:
                add("BUMP", a, b, a["start_seconds"], b["end_seconds"], status="candidate")
    output.update(naming_version=NAMING_VERSION, relations=relations, naming_validation="independent_video_review_pending")
    return output


def caption_entries(groups, time):
    timeline = [(g, e) for g in groups for e in g.get("events", [])
                if e.get("evidence_status") in {"locally_verified", "human_confirmed", "trajectory_observed"} and e.get("limb") in LIMB_NAMES]
    entries = []
    for group, event in timeline:
        next_start = min((e["start_seconds"] for _, e in timeline if e["limb"] == event["limb"] and e["start_seconds"] > event["start_seconds"]), default=math.inf)
        next_after = min((e["start_seconds"] for _, e in timeline if e["start_seconds"] > event["start_seconds"] and e["start_seconds"] >= event["end_seconds"]), default=math.inf)
        tail = event["end_seconds"] if any(e is not event and e["start_seconds"] < event["end_seconds"] < e["end_seconds"] for _, e in timeline) else event["end_seconds"] + .55
        if not event["start_seconds"] <= time < min(tail, next_start, next_after):
            continue
        parts = event.get("caption_parts") or event_parts(deepcopy(event))
        active = [p for p in parts if p["start_seconds"] <= time]
        if not active:
            continue
        text = active[-1]["text"]
        relationships = [r for r in event.get("relations", []) if r["status"] != "candidate" and r["code"] != "SIMULTANEOUS" and r["start_seconds"] <= time <= r["end_seconds"] + .55]
        if relationships:
            text += " · " + relationships[0]["name"]
        entries.append({"id": event.get("id"), "limb": event["limb"], "text": text, "group_id": group["id"],
                        "group_index": groups.index(group), "start_seconds": event["start_seconds"], "end_seconds": event["end_seconds"]})
    return entries
