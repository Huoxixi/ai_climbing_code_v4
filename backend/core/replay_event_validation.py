"""Fail closed before any paid interpretation of an unsegmented timeline."""
import math
from collections import Counter


def validate_event_sequence(result):
    groups = result.get('groups') or []
    windows = []
    reasons = []
    duration = result.get('source_duration_seconds') or (result.get('video') or {}).get('duration_seconds')
    for group in groups:
        start, end = group.get('start_seconds'), group.get('end_seconds')
        if (not all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in (start, end))
                or not 0 <= start < end or (duration and end > duration + .001)):
            reasons.append('invalid_source_times')
            continue
        windows.append((round(start, 3), round(end, 3)))
    if len(set(windows)) < 2:
        reasons.append('fewer_than_two_event_windows')
    if windows and max(Counter(windows).values()) / len(windows) >= .8:
        reasons.append('repeated_event_windows')
    if windows and duration and all(start <= .1 and end >= duration - .1 for start, end in windows):
        reasons.append('whole_video_windows')
    ordered = sorted(set(windows))
    if any(b[0] < a[1] - .001 for a, b in zip(ordered, ordered[1:])):
        reasons.append('overlapping_event_windows')
    if 'action_evidence' in result:
        supported = {(round(a['start_seconds'],3),round(a['end_seconds'],3))
            for a in [*result['action_evidence'].get('actions', []),
                      *result['action_evidence'].get('commentary_actions', [])]
            if a.get('quality', {}).get('status') == 'observed' and a.get('commentary') and len(a.get('evidence_frames') or []) >= 3}
        if len(supported) < 2:
            reasons.append('fewer_than_two_supported_events')
        if not supported.issubset(set(windows)):
            reasons.append('component_times_disagree_with_events')
    return {'analysis_valid': not reasons, 'distinct_event_windows': len(set(windows)),
            'reasons': sorted(set(reasons)),
            'message': '' if not reasons else '尚未切分出至少两个不同的动作时间段，已禁止生成收费评语。请先重新整理本地动作。'}


def require_event_sequence(result):
    validation = validate_event_sequence(result)
    if not validation['analysis_valid']:
        raise ValueError(validation['message'])

