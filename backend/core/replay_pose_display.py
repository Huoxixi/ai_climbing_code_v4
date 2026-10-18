"""Source-image display helpers; these points are not mass or force estimates."""
import math


TORSO_CENTER_STYLE = "shoulder_hip_mean_min3_score05_v1"


def torso_center(sample):
    """Mean of at least three reliable COCO shoulder/hip points, in image space."""
    if not sample or sample.get("observed") is False:
        return None
    points, scores = sample.get("kpts_xy") or [], sample.get("kpts_score") or []
    valid = []
    for index in (5, 6, 11, 12):
        try:
            x, y = points[index]
            score = scores[index]
            if (all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in (x, y, score))
                    and .5 <= score <= 1 and 0 < x < 1 and 0 < y < 1):
                valid.append((x, y))
        except (IndexError, TypeError, ValueError):
            continue
    if len(valid) < 3:
        return None
    return [sum(point[axis] for point in valid) / len(valid) for axis in (0, 1)]
