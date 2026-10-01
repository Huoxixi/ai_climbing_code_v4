"""Geometry and evidence fusion for the opt-in video replay hold map."""
from __future__ import annotations

import cv2
import numpy as np
from collections import Counter


def align_to_reference(source: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray | None, dict]:
    """Register a wall image to a video frame; reject weak or implausible matches."""
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    source_scale = min(1.0, 960.0 / max(source_gray.shape))
    reference_scale = min(1.0, 960.0 / max(reference_gray.shape))
    source_small = cv2.resize(source_gray, None, fx=source_scale, fy=source_scale,
                              interpolation=cv2.INTER_AREA) if source_scale < 1 else source_gray
    reference_small = cv2.resize(reference_gray, None, fx=reference_scale, fy=reference_scale,
                                 interpolation=cv2.INTER_AREA) if reference_scale < 1 else reference_gray
    detector = cv2.ORB_create(nfeatures=2400)
    source_points, source_desc = detector.detectAndCompute(source_small, None)
    reference_points, reference_desc = detector.detectAndCompute(reference_small, None)
    if source_desc is None or reference_desc is None:
        return None, {"reason": "insufficient_features"}
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(source_desc, reference_desc, k=2)
    good = [first for pair in pairs if len(pair) == 2 for first, second in [pair]
            if first.distance < .72 * second.distance]
    if len(good) < 16:
        return None, {"reason": "insufficient_matches", "matches": len(good)}
    src = np.float32([source_points[item.queryIdx].pt for item in good]).reshape(-1, 1, 2)
    dst = np.float32([reference_points[item.trainIdx].pt for item in good]).reshape(-1, 1, 2)
    matrix, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.5)
    count = int(inliers.sum()) if inliers is not None else 0
    if matrix is None or count < 12 or count / len(good) < .5:
        return None, {"reason": "weak_homography", "matches": len(good), "inliers": count}
    source_inliers = src[inliers.ravel() > 0].reshape(-1, 2)
    target_inliers = dst[inliers.ravel() > 0].reshape(-1, 2)
    source_span = np.ptp(source_inliers, axis=0) / np.asarray(source_small.shape[::-1])
    target_span = np.ptp(target_inliers, axis=0) / np.asarray(reference_small.shape[::-1])
    if min(*source_span, *target_span) < .18:
        return None, {"reason": "matches_too_local", "matches": len(good), "inliers": count}
    source_shrink = np.diag([source_scale, source_scale, 1.0])
    reference_expand = np.diag([1 / reference_scale, 1 / reference_scale, 1.0])
    matrix = reference_expand @ matrix @ source_shrink
    height, width = source.shape[:2]
    corners = cv2.perspectiveTransform(
        np.float32([[[0, 0]], [[width, 0]], [[width, height]], [[0, height]]]), matrix,
    ).reshape(4, 2)
    area = abs(float(cv2.contourArea(corners.astype(np.float32))))
    target_area = float(reference.shape[0] * reference.shape[1])
    if not np.isfinite(matrix).all() or area < .08 * target_area or area > 8 * target_area \
            or not cv2.isContourConvex(corners.astype(np.float32)):
        return None, {"reason": "implausible_projection", "matches": len(good), "inliers": count}
    projected = cv2.perspectiveTransform(src[inliers.ravel() > 0],
                                         np.diag([reference_scale, reference_scale, 1.0])
                                         @ matrix @ np.diag([1 / source_scale, 1 / source_scale, 1.0]))
    error = float(np.median(np.linalg.norm(projected.reshape(-1, 2) - dst[inliers.ravel() > 0].reshape(-1, 2), axis=1)))
    if error > 3.5:
        return None, {"reason": "reprojection_error", "error_px": round(error / reference_scale, 2)}
    return matrix, {"matches": len(good), "inliers": count, "median_error_px": round(error / reference_scale, 2)}


def transform_polygon(polygon: list, matrix: np.ndarray, width: int, height: int) -> list[list[float]]:
    points = np.asarray(polygon, np.float32).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(points, matrix).reshape(-1, 2)
    return [[round(float(x / width), 6), round(float(y / height), 6)] for x, y in mapped
            if np.isfinite(x) and np.isfinite(y)]


def polygon_bbox(points: list[list[float]]) -> list[float]:
    values = np.asarray(points, dtype=float)
    if len(values) < 3:
        return [0.0, 0.0, 0.0, 0.0]
    low, high = values.min(axis=0), values.max(axis=0)
    return [round(float(low[0]), 6), round(float(low[1]), 6),
            round(float(high[0] - low[0]), 6), round(float(high[1] - low[1]), 6)]


def align_pose_record(record: dict, matrix: np.ndarray | None, width: int, height: int) -> dict:
    """Keep displayed pose untouched; transform a copy solely for contact testing."""
    result = dict(record)
    if matrix is None:
        result["kpts_score"] = [0.0] * len(record["kpts_score"])
        return result
    source = np.asarray(record["kpts_xy"], np.float32)
    pixels = source * np.asarray([width, height], np.float32)
    mapped = cv2.perspectiveTransform(pixels.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    result["kpts_xy"] = [[round(float(x / width), 6), round(float(y / height), 6)]
                         for x, y in mapped]
    result["kpts_score"] = [score if 0 <= point[0] <= 1 and 0 <= point[1] <= 1 else 0.0
                            for point, score in zip(result["kpts_xy"], record["kpts_score"])]
    return result


def box_iou(first: list[float], second: list[float]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left, top, right, bottom = max(ax, bx), max(ay, by), min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def box_containment(first: list[float], second: list[float]) -> float:
    """Fraction of the smaller box covered by the intersection."""
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    intersection = max(0.0, min(ax + aw, bx + bw) - max(ax, bx)) * \
        max(0.0, min(ay + ah, by + bh) - max(ay, by))
    smaller = min(max(0.0, aw * ah), max(0.0, bw * bh))
    return intersection / smaller if smaller > 0 else 0.0


SAMPLE_COLOUR_NEIGHBORS = {
    "红色": {"橙色", "粉色"}, "橙色": {"红色", "黄色"},
    "黄色": {"橙色", "绿色"}, "绿色": {"黄色", "青色"},
    "青色": {"绿色", "蓝色"}, "蓝色": {"青色", "紫色"},
    "紫色": {"蓝色", "粉色"}, "粉色": {"红色", "紫色"},
}


def select_sampled_route_holds(
    holds: list[dict], *, sample_group: str, minimum_appearances: int = 2,
) -> tuple[list[dict], list[dict], dict]:
    """Conservatively select a sampled-colour route; retain rejects for review.

    A wide Lab distance is useful for recall but insufficient to make a hold a
    route member. This step removes speck-sized masks and non-neighbor colours,
    while allowing a small but well-observed foothold with a close colour sample.
    """
    allowed = {sample_group, *SAMPLE_COLOUR_NEIGHBORS.get(sample_group, set())}
    eligible = []
    rejected = []
    reasons = Counter()
    for hold in holds:
        if hold.get("contour_source") != "climbing_model_native_mask":
            rejected.append(hold)
            reasons["not_native_mask"] += 1
            continue
        appearance = int(hold.get("appearances") or 0)
        sampled = hold.get("identity_source") == "user_sampled_hold"
        if not hold.get("route_candidate") or (appearance < minimum_appearances and not sampled):
            rejected.append(hold)
            reasons["not_stable_colour_candidate"] += 1
            continue
        box = hold.get("bbox") or [0, 0, 0, 0]
        area = float(box[2]) * float(box[3])
        if area < .0015 and not sampled:
            rejected.append(hold)
            reasons["tiny_mask"] += 1
            continue
        score = float(hold.get("score") or 0)
        distance = hold.get("color_distance")
        strong_exception = (distance is not None and float(distance) <= 18
                            and appearance >= 3 and score >= .85)
        if hold.get("color_group") not in allowed and not strong_exception and not sampled:
            rejected.append(hold)
            reasons["unrelated_colour"] += 1
            continue
        if score < .65 and not sampled:
            rejected.append(hold)
            reasons["weak_mask"] += 1
            continue
        eligible.append(hold)

    eligible.sort(key=lambda hold: (
        -int(hold.get("appearances") or 0), -float(hold.get("score") or 0),
        -float(hold["bbox"][2] * hold["bbox"][3]),
    ))
    selected = []
    for hold in eligible:
        duplicate = next((kept for kept in selected
                          if box_containment(kept["bbox"], hold["bbox"]) >= .70
                          or box_iou(kept["bbox"], hold["bbox"]) >= .50), None)
        if duplicate is None:
            selected.append(hold)
            continue
        if hold.get("identity_source") == "user_sampled_hold":
            duplicate["identity_source"] = "user_sampled_hold"
            duplicate["route_candidate_reason"] = "user_sampled_hold"
        rejected.append(hold)
        reasons["overlapping_mask"] += 1
    return selected, rejected, {"sample_group": sample_group,
                                "allowed_color_groups": sorted(allowed),
                                "selection_reasons": dict(reasons)}


def fuse_hold_detections(frames: list[list[dict]], *, color_distance_limit: float = 34.0) -> list[dict]:
    """Merge aligned masks by geometry; never merge two detections from one frame."""
    clusters: list[dict] = []
    for frame_index, detections in enumerate(frames):
        for detection in detections:
            best, best_score = None, .24
            for cluster in clusters:
                if frame_index in cluster["frames"]:
                    continue
                score = box_iou(detection["bbox"], cluster["hold"]["bbox"])
                if score > best_score:
                    best, best_score = cluster, score
            if best is None:
                clusters.append({"hold": dict(detection), "frames": {frame_index}, "boxes": [detection["bbox"]],
                                 "scores": [detection["score"]], "detections": [detection]})
            else:
                best["frames"].add(frame_index)
                best["boxes"].append(detection["bbox"])
                best["scores"].append(detection["score"])
                best["detections"].append(detection)
                # The clearest contour is retained; geometry is stabilized independently.
                if detection["score"] > best["hold"]["score"]:
                    best["hold"] = dict(detection)
    result = []
    for cluster in clusters:
        hold = dict(cluster["hold"])
        hold["bbox"] = [round(float(item), 6) for item in np.median(cluster["boxes"], axis=0)]
        hold["score"] = round(float(np.mean(cluster["scores"])), 4)
        hold["appearances"] = len(cluster["frames"])
        labels = [item["color_group"] for item in cluster["detections"] if item.get("color_group")]
        if labels:
            hold["color_group"] = Counter(labels).most_common(1)[0][0]
        distances = [item["color_distance"] for item in cluster["detections"]
                     if item.get("color_distance") is not None]
        if distances:
            hold["color_distance"] = round(float(np.median(distances)), 4)
            hold["route_candidate"] = hold["color_distance"] <= color_distance_limit
        else:
            votes = sum(bool(item.get("route_candidate")) for item in cluster["detections"])
            hold["route_candidate"] = votes * 2 >= len(cluster["detections"])
        hold["color_votes"] = sum(bool(item.get("route_candidate")) for item in cluster["detections"])
        result.append(hold)
    result.sort(key=lambda hold: (-hold["appearances"], -hold["score"]))
    return result


def match_confirmed_route(holds: list[dict], projected: list[dict], *,
                          include_projected_unmatched: bool = False) -> tuple[list[dict], list[dict]]:
    """Use only confirmed saved-route members, with one-to-one geometric matching."""
    matched_ids: set[int] = set()
    selected: list[dict] = []
    projected_candidates: list[dict] = []
    for member in projected:
        best_index, best_score = None, .18
        for index, hold in enumerate(holds):
            if index in matched_ids:
                continue
            score = box_iou(member["bbox"], hold["bbox"])
            if score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            box = member["bbox"]
            visible_width = max(0.0, min(1.0, box[0] + box[2]) - max(0.0, box[0]))
            visible_height = max(0.0, min(1.0, box[1] + box[3]) - max(0.0, box[1]))
            if include_projected_unmatched and visible_width * visible_height > .3 * box[2] * box[3]:
                projected_candidates.append({"bbox": box, "polygon": member["polygon"], "score": .5,
                                             "appearances": 0, "saved_object_id": member["object_id"],
                                             "identity_source": "unverified_saved_photo_projection",
                                             "route_candidate": True, "route_candidate_reason": "confirmed_photo_projection_needs_review",
                                             "contour_source": "saved_photo_registered_contour"})
            continue
        matched_ids.add(best_index)
        chosen = dict(holds[best_index])
        chosen.update(saved_object_id=member["object_id"], identity_source="confirmed_saved_route",
                      route_candidate=True, route_candidate_reason="confirmed_geometry",
                      saved_route_iou=round(best_score, 4))
        selected.append(chosen)
    remaining = [dict(hold) for index, hold in enumerate(holds) if index not in matched_ids]
    remaining.extend(projected_candidates)
    return selected, remaining
