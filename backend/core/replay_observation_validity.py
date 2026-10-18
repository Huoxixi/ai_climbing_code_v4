"""Shared source-pixel registration and joint eligibility, not probability calibration."""
import numpy as np

MINIMUM_SCORE = .5
MAX_ERROR_PX = 3.


def registration_reason(matrix, diagnostics=None):
    try:
        transform = np.asarray(matrix, float)
        if transform.shape != (3, 3) or not np.isfinite(transform).all():
            return 'missing_or_nonfinite_transform'
        if abs(transform[2,2]) < 1e-12 or abs(np.linalg.det(transform / transform[2,2])) < 1e-9:
            return 'singular_transform'
        diagnostics = diagnostics or {}
        for key, limit, minimum in (('median_error_px', MAX_ERROR_PX, False), ('inliers', 12, True)):
            value = diagnostics.get(key)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int,float,np.number)) or not np.isfinite(value) or (value < limit if minimum else value > limit):
                    return 'registration_' + key
        return None
    except (ValueError, TypeError, OverflowError, np.linalg.LinAlgError):
        return 'invalid_registration'


def joint_mask(source, mapped, scores, eligibility=None):
    source, mapped, scores = np.asarray(source, float), np.asarray(mapped, float), np.asarray(scores, float)
    if eligibility is not None:
        flags = np.asarray(eligibility)
        if flags.shape != scores.shape or flags.dtype != np.dtype(bool):
            return np.zeros(scores.shape, bool)
        score_eligible = flags & np.isfinite(scores) & (scores > 0)
    else:
        score_eligible = np.isfinite(scores) & (scores >= MINIMUM_SCORE) & (scores <= 1.)
    return (np.isfinite(source).all(axis=1) & np.isfinite(mapped).all(axis=1)
            & score_eligible
            & (source > 0).all(axis=1) & (source < 1).all(axis=1)
            & (mapped > 0).all(axis=1) & (mapped < 1).all(axis=1))
