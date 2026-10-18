"""Geometry and evidence fusion for the opt-in video replay hold map."""
from __future__ import annotations

import cv2
import numpy as np
from collections import Counter
import copy
from .replay_observation_validity import registration_reason, joint_mask


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
    if error / reference_scale > 3.:
        return None, {"reason": "reprojection_error", "error_px": round(error / reference_scale, 2)}
    return matrix, {"matches": len(good), "inliers": count, "median_error_px": error / reference_scale,
                    "error_units": "reference_image_pixels"}


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
    if record.get("wholebody"):
        result["wholebody"] = dict(record["wholebody"])
    reason = registration_reason(matrix, record.get('wall_alignment_diagnostics') or record.get('motion_registration'))
    result['contact_registration_reason'] = reason
    if reason:
        result["kpts_score"] = [0.0] * len(record["kpts_score"])
        if result.get("wholebody"):
            result["wholebody"]["kpts_score"] = [0.] * len(result["wholebody"].get("kpts_score") or [])
            result["wholebody"]["coordinates"] = "unregistered_source_image_normalized"
        return result
    source = np.asarray(record["kpts_xy"], np.float32)
    pixels = source * np.asarray([width, height], np.float32)
    mapped = cv2.perspectiveTransform(pixels.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    result["kpts_xy"] = [[round(float(x / width), 6), round(float(y / height), 6)]
                         for x, y in mapped]
    valid = joint_mask(source, result['kpts_xy'], record['kpts_score'], record.get('joint_eligibility'))
    # Internal contact compatibility channel only. Source responses remain intact
    # in the source record; these weights represent eligibility, not confidence.
    result["kpts_score"] = [1. if okay else 0. for okay in valid] if record.get('joint_eligibility') is not None else [score if okay else 0.0 for okay, score in zip(valid, record['kpts_score'])]
    if record.get('joint_eligibility') is not None:
        result['contact_source_responses'] = list(record['kpts_score'])
    if result.get("wholebody"):
        body = result["wholebody"]
        whole = np.asarray(body.get("kpts_xy") or [],np.float32)
        if whole.shape == (133,2) and len(body.get("kpts_score") or [])==133:
            mapped_whole = cv2.perspectiveTransform((whole*[width,height]).astype(np.float32).reshape(-1,1,2),matrix).reshape(-1,2)/[width,height]
            body["kpts_xy"] = np.where(np.isfinite(mapped_whole),mapped_whole,0.).round(6).tolist()
            valid_whole = joint_mask(whole,mapped_whole,body['kpts_score'],body.get('joint_eligibility'))
            body["kpts_score"] = [1. if okay else 0. for okay in valid_whole] if body.get('joint_eligibility') is not None else [score if okay else 0.
                                  for okay,score in zip(valid_whole,body["kpts_score"])]
            body["coordinates"] = "wall_reference_image_normalized"
        else:
            body["kpts_score"] = [0.] * len(body.get("kpts_score") or [])
            body["coordinates"] = "invalid_wholebody_observation"
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


def sampled_colour_matches(hold: dict, sample_group: str, limit: float = 60.) -> bool:
    """Colour is a prerequisite: evidence cannot rescue another colour."""
    if not hold.get('route_candidate') or hold.get('color_group') != sample_group:
        return False
    support=hold.get('colour_support') or {}
    if support.get('version')=='replay-connected-sample-support-v1':
        return support.get('pixel_limit')==limit and support.get('qualified') is True
    distance = hold.get('color_distance')
    if distance is None:
        return hold.get('color_source') in (None, 'preset')
    try:
        return bool(np.isfinite(float(distance)) and 0 <= float(distance) <= limit)
    except (TypeError, ValueError):
        return False


def contour_overlap(first: dict, second: dict) -> tuple[float, float]:
    """Local raster IoU / containment, including concave native contours.

    Experimental association only. A 512px local raster avoids allocating a
    whole source frame for each pair. Missing contours fall back to legacy boxes.
    """
    a, b = first.get("polygon"), second.get("polygon")
    if not a or not b or len(a) < 3 or len(b) < 3:
        return box_iou(first["bbox"], second["bbox"]), box_containment(first["bbox"], second["bbox"])
    if box_iou(first["bbox"], second["bbox"]) == 0:
        return 0., 0.
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    if a.shape[1:] != (2,) or b.shape[1:] != (2,) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return 0., 0.
    low = np.minimum(a.min(axis=0), b.min(axis=0))
    span = np.maximum(a.max(axis=0), b.max(axis=0)) - low
    if np.any(span <= 0):
        return 0., 0.
    masks = []
    for polygon in (a, b):
        mask = np.zeros((514,514), np.uint8)
        cv2.fillPoly(mask, [np.rint((polygon-low)/span*511+1).astype(np.int32)], 1)
        masks.append(mask)
    intersection = int(np.count_nonzero(masks[0] & masks[1]))
    areas = [int(np.count_nonzero(mask)) for mask in masks]
    return intersection/max(1,sum(areas)-intersection), intersection/max(1,min(areas))


def valid_native_contour(hold: dict) -> bool:
    """A finite, nondegenerate native contour; there is no minimum point size."""
    try:
        polygon = np.asarray(hold.get('polygon'), np.float32)
        return (hold.get('contour_source') in {'climbing_model_native_mask','model_guided_mobilesam_mask'}
                and polygon.ndim == 2 and polygon.shape[1] == 2 and len(polygon) >= 3
                and np.isfinite(polygon).all() and cv2.contourArea(polygon) > 0)
    except (TypeError, ValueError, cv2.error):
        return False


def native_contour_support(detections: list[dict], representative: dict, *,
                           sample_group: str | None = None, color_distance_limit: float = 60.) -> dict:
    """Keep measured colour/contour agreement across actual registered frames."""
    rows = []
    for detection in detections:
        colour_candidate = (sampled_colour_matches(detection, sample_group, color_distance_limit)
                            if sample_group is not None else detection.get('route_candidate') is True)
        if not colour_candidate:
            rows.append({'source_frame': detection.get('source_frame'),
                         'observation_id': detection.get('observation_id'),
                         'iou': None, 'complete': detection.get('contour_complete') is True,
                         'colour_candidate': False, 'evidence_checked': False})
            continue
        if not valid_native_contour(detection):
            continue
        iou, _ = contour_overlap(detection, representative)
        rows.append({'source_frame': detection.get('source_frame'),
                     'observation_id': detection.get('observation_id'),
                     'iou': round(iou, 4),
                     'complete': detection.get('contour_complete') is True,
                     'colour_candidate': True, 'evidence_checked': True})
    supporting = [r for r in rows if r['complete'] and r['colour_candidate'] and r['iou'] >= .5]
    frames = sorted({r['source_frame'] for r in supporting
                     if isinstance(r['source_frame'], int) and not isinstance(r['source_frame'], bool)})
    partial=[d['source_frame'] for d in detections if d.get('visible_partial_support')
        and (sampled_colour_matches(d,sample_group,color_distance_limit) if sample_group else d.get('route_candidate'))
        and contour_overlap(d,representative)[0]>=.9]
    result={'version': 'native-colour-contour-support-v1', 'observations': rows,
            'support_frames': frames, 'minimum_contour_iou': .5}
    if len(set(partial))>=3:
        result.update(support_frames=sorted(set(frames+partial)),visible_partial_frames=sorted(set(partial)),
            partial_contour_complete=False)
    return result


def select_sampled_route_holds(
    holds: list[dict], *, sample_group: str, minimum_appearances: int = 2,
    trace: list[dict] | None = None,
    geometry: str = "bbox",
    content_bounds: list[float] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Conservatively select a sampled-colour route; retain rejects for review.

    Size alone never rejects a candidate. Native, complete contours must agree
    in registered position/shape and colour across distinct source frames.
    Unsupported candidates remain available for review, not confirmed negatives.
    """
    allowed = {sample_group}
    if geometry not in {"bbox", "contour"}:
        raise ValueError("Unknown hold association policy")
    content_bounds = content_bounds or [0.,0.,1.,1.]
    if len(content_bounds)!=4 or not np.isfinite(content_bounds).all() or min(content_bounds[2:])<=0:
        raise ValueError("Invalid image content bounds")
    eligible = []
    rejected = []
    reasons = Counter()
    def reject(hold, reason):
        rejected.append(hold)
        reasons[reason] += 1
        if trace is not None:
            trace.append({"candidate_id": hold.get("candidate_id"), "stage": "selection",
                          "status": "rejected", "reason": reason})
    for hold in holds:
        if not sampled_colour_matches(hold, sample_group):
            reject(hold, "outside_sample_colour")
            continue
        if hold.get('native_class')==1:
            # Volume predictions are retained for review; known intersecting
            # native instances must not become an asserted automatic repair.
            reject(hold, 'native_volume_needs_review')
            continue
        if hold.get("contour_source") != "climbing_model_native_mask":
            reject(hold, "not_native_mask")
            continue
        appearance = int(hold.get("appearances") or 0)
        sampled = hold.get("identity_source") == "user_sampled_hold"
        if appearance < minimum_appearances and not sampled:
            reject(hold, "insufficient_observation_frames")
            continue
        if not valid_native_contour(hold):
            reject(hold, "invalid_native_contour")
            continue
        evidence = hold.get('contour_evidence') or {}
        support_frames = evidence.get('support_frames') or []
        distinct_support = {frame for frame in support_frames
                            if isinstance(frame, int) and not isinstance(frame, bool)}
        if not sampled and (evidence.get('version') != 'native-colour-contour-support-v1'
                            or len(distinct_support) < minimum_appearances):
            reject(hold, "insufficient_colour_contour_support")
            continue
        score = float(hold.get("score") or 0)
        if score < .65 and not sampled:
            reject(hold, "weak_mask")
            continue
        eligible.append(hold)

    eligible.sort(key=lambda hold: (
        # A newly resolved ambiguous cluster cannot displace a previously
        # qualified native object, even if it has more agreeing observations.
        bool(hold.get('sample_identity_resolution')),
        -len({frame for frame in (hold.get('contour_evidence') or {}).get('support_frames') or []
              if isinstance(frame, int) and not isinstance(frame, bool)}),
        -float(hold.get("score") or 0), -int(hold.get("appearances") or 0),
    ))
    selected = []
    for hold in eligible:
        def duplicate_of(kept):
            if geometry == "contour":
                iou, containment = contour_overlap(kept, hold)
                return containment >= .70 or iou >= .50
            return box_containment(kept["bbox"], hold["bbox"]) >= .70 or box_iou(kept["bbox"], hold["bbox"]) >= .50
        duplicate = next((kept for kept in selected if duplicate_of(kept)), None)
        if duplicate is None:
            selected.append(hold)
            if trace is not None:
                trace.append({"candidate_id": hold.get("candidate_id"), "stage": "selection",
                              "status": "selected"})
            continue
        if hold.get("identity_source") == "user_sampled_hold":
            duplicate["identity_source"] = "user_sampled_hold"
            duplicate["route_candidate_reason"] = "user_sampled_hold"
        reject(hold, "overlapping_mask")
    return selected, rejected, {"sample_group": sample_group,
                                "allowed_color_groups": sorted(allowed),
                                "content_bounds": content_bounds,
                                "selection_basis": "same_colour_first_then_native_contour_support_v2",
                                "selection_reasons": dict(reasons)}


def image_content_bounds(image: np.ndarray) -> list[float]:
    """Exclude only substantial, contiguous encoded black bars from area tests.

    Source coordinates and source pixels remain untouched. Narrow shadows,
    dark full frames, and implausibly small content retain the full image basis.
    """
    height, width = image.shape[:2]
    black = np.max(image, axis=2) <= 12
    rows, cols = np.mean(black,axis=1)>=.998, np.mean(black,axis=0)>=.998
    def limits(values):
        visible = np.flatnonzero(~values)
        return (int(visible[0]),int(visible[-1])+1) if len(visible) else (0,len(values))
    left,right = limits(cols)
    top,bottom = limits(rows)
    if width-(right-left) < width*.10:
        left,right = 0,width
    if height-(bottom-top) < height*.10:
        top,bottom = 0,height
    if right-left < max(64,width*.20) or bottom-top < max(64,height*.20):
        return [0.,0.,1.,1.]
    return [left/width,top/height,(right-left)/width,(bottom-top)/height]


def fuse_hold_detections(frames: list[list[dict]], *, color_distance_limit: float = 60.0,
                         sample_group: str | None = None,
                         geometry: str = "bbox", evidence_policy: str = "legacy") -> list[dict]:
    """Merge aligned masks by geometry; never merge two detections from one frame."""
    clusters: list[dict] = []
    if geometry not in {"bbox", "contour"}:
        raise ValueError("Unknown hold association policy")
    if evidence_policy not in {'legacy','material_boundary'}:
        raise ValueError('Unknown video evidence policy')
    for frame_index, detections in enumerate(frames):
        for detection in detections:
            best, best_score = None, .24
            for cluster in clusters:
                if frame_index in cluster["frames"]:
                    continue
                if evidence_policy=='material_boundary' and detection.get('native_class',0)!=cluster['hold'].get('native_class',0):
                    continue
                score = (contour_overlap(detection, cluster["hold"])[0] if geometry == "contour"
                         else box_iou(detection["bbox"], cluster["hold"]["bbox"]))
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
        members=cluster['detections']
        reliable=members
        material_identity=None
        if evidence_policy=='material_boundary':
            from .replay_hold_evidence import measure_material_quality, warm_material_supported, choose_native_representative
            members=copy.deepcopy(members)
            measure_material_quality(members)
            reliable=[d for d in members if (d.get('material_quality') or {}).get('eligible',True)]
            warm=warm_material_supported(reliable)
            partial_boundary_members=[]
            for d in members:
                original=d['color_group']
                if warm and d in reliable:
                    d['color_group']='黄色'
                    support=d.get('colour_support')
                    if support:
                        support['class_matches']=sample_group=='黄色'
                        support['qualified']=bool(support.get('metric_qualified') and support['class_matches'])
                        d['route_candidate']=support['qualified']
                if not (d.get('material_quality') or {}).get('eligible',True):
                    if (d['material_quality'].get('reasons')==['temporal_shape_area_outlier']
                            and sampled_colour_matches(d,sample_group,color_distance_limit)):
                        partial_boundary_members.append(copy.deepcopy(d))
                    d['route_candidate']=False
                    if d.get('colour_support'):d['colour_support']['qualified']=False
                d['observed_color_group']=original
            chosen=choose_native_representative(members,sample_group,sampled_colour_matches,contour_overlap,
                partial_boundary_members=partial_boundary_members) if sample_group is not None else cluster['hold']
            hold=dict(chosen)
            material_identity={'version':'replay-material-identity-v1','warm_material_supported':warm,
                'observations':[{'observation_id':d.get('observation_id'),'source_frame':d.get('source_frame'),
                    'original':d['observed_color_group'],'resolved':d['color_group'],
                    'quality':d.get('material_quality')} for d in members]}
        else:
            hold = dict(cluster["hold"])
        hold["bbox"] = (polygon_bbox(hold["polygon"]) if hold.get("polygon") else
                        [round(float(item), 6) for item in np.median(cluster["boxes"], axis=0)])
        hold["score"] = round(float(np.mean(cluster["scores"])), 4)
        hold["appearances"] = len(cluster["frames"])
        hold["contour_evidence"] = native_contour_support(members, hold,
                                                         sample_group=sample_group,
                                                         color_distance_limit=color_distance_limit)
        # Preserve every actual observation, including ones whose contour was
        # not retained. These are evidence references, not independent votes.
        hold["support_frames"] = sorted({int(item["source_frame"]) for item in cluster["detections"]
                                         if item.get("source_frame") is not None})
        hold["observation_ids"] = [item["observation_id"] for item in cluster["detections"]
                                   if item.get("observation_id") is not None]
        labels = [item["color_group"] for item in reliable if item.get("color_group")]
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
        if sample_group is not None:
            hold['route_candidate'] = sampled_colour_matches(hold, sample_group, color_distance_limit)
            if evidence_policy=='material_boundary' and any(d.get('colour_support') for d in members):
                from .replay_hold_evidence import COLOUR_SUPPORT_VERSION
                qualified=[d for d in reliable if sampled_colour_matches(d,sample_group,color_distance_limit)]
                support={'version':COLOUR_SUPPORT_VERSION,'pixel_limit':color_distance_limit,
                    'qualified':bool(reliable and len(qualified)*2>=len(reliable)),
                    'support_frames':sorted({d['source_frame'] for d in qualified}),
                    'observations':[{'observation_id':d.get('observation_id'),**(d.get('colour_support') or {})} for d in members]}
                hold['colour_support']=support
                hold['route_candidate']=support['qualified'] and hold['color_group']==sample_group
        if material_identity:
            hold['material_identity']=material_identity
        hold['native_observations']=[{'observation_id':d.get('observation_id'),'source_frame':d.get('source_frame'),
            'native_class':d.get('native_class',0)} for d in members]
        hold["color_votes"] = sum(bool(item.get("route_candidate")) for item in cluster["detections"])
        if evidence_policy == 'material_boundary' and sample_group is not None:
            from .replay_hold_evidence import resolve_unresolved_sample_cluster
            hold = resolve_unresolved_sample_cluster(hold, members, sample_group,
                                                     contour_overlap, sampled_colour_matches)
        result.append(hold)
    result.sort(key=lambda hold: (-hold["appearances"], -hold["score"]))
    for index, hold in enumerate(result, 1):
        hold["candidate_id"] = f"candidate-{index}"
    if evidence_policy=='material_boundary':
        _annotate_merge_relations(result)
    return result


def _annotate_merge_relations(holds):
    """Relations remain evidence references, never synthetic contours/support."""
    import itertools
    for merged in holds:
        area=cv2.contourArea(np.asarray(merged['polygon'],np.float32))
        parts=[]
        for other in holds:
            if other is merged or other['color_group']!=merged['color_group'] or box_iou(merged['bbox'],other['bbox'])==0:
                continue
            if cv2.contourArea(np.asarray(other['polygon'],np.float32))>=area*.80:continue
            if contour_overlap(merged,other)[1]>=.70:parts.append(other)
        links=[]
        for a,b in itertools.combinations(parts,2):
            shared=sorted(set(a.get('support_frames') or [])&set(b.get('support_frames') or []))
            if shared and contour_overlap(a,b)[0]<=.10:
                links.append({'parts':[a['candidate_id'],b['candidate_id']], 'coobserved_frames':shared,
                    'relation_only':True,'independent_contours_added':0})
        if links:merged['merge_relations']=links


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
