"""Observed body-motion statistics on the original video clock."""
from copy import deepcopy
import math
from .replay_torso_trajectory import torso_trajectory


def prepare_motion_evidence(result, source, cancelled=None):
    """Restore missing legacy camera transforms locally, preserving pose labels."""
    output = deepcopy(result)
    missing = [s for s in output.get('pose_samples', [])
               if s.get('observed') and s.get('wall_reference_transform') is None]
    if not missing:
        return output
    import cv2
    from .replay_hold_fusion import align_to_reference
    capture = cv2.VideoCapture(str(source))
    try:
        reference_index = (result.get('hold_evidence') or {}).get('reference_frame', 0)
        capture.set(cv2.CAP_PROP_POS_FRAMES, reference_index)
        ok, reference = capture.read()
        if not ok:
            return output
        for sample in missing:
            if cancelled and cancelled():
                raise InterruptedError()
            index = sample.get('source_frame_id')
            if index is None:
                continue
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame.shape != reference.shape:
                continue
            matrix, diagnostics = align_to_reference(frame, reference)
            sample['wall_reference_transform'] = matrix.tolist() if matrix is not None else None
            sample['wall_alignment'] = 'aligned' if matrix is not None else 'unknown'
            sample['motion_registration'] = dict(diagnostics, basis='local_legacy_transform_recovery')
    finally:
        capture.release()
    return output


def motion_summary(organized):
    duration = organized['source_duration_seconds']
    if not isinstance(duration, (int,float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Motion summary requires a positive source duration')
    segments = []
    cursor = 0.
    def add(start, end, kind):
        if end <= start:
            return
        if segments and segments[-1]['kind'] == kind and abs(segments[-1]['end_seconds'] - start) < 1e-6:
            segments[-1]['end_seconds'] = end
        else:
            segments.append({'start_seconds': start, 'end_seconds': end, 'kind': kind})
    for row in sorted(organized.get('motion_intervals', []), key=lambda r: r['start_seconds']):
        start = max(0., min(duration, row['start_seconds']))
        end = max(0., min(duration, row['end_seconds']))
        if start < cursor - 1e-6:
            raise ValueError('Motion evidence overlaps')
        add(cursor, start, 'unknown')
        add(start, end, row['kind'] if row['kind'] in ('moving', 'relative_still') else 'unknown')
        cursor = max(cursor, end)
    add(cursor, duration, 'unknown')
    totals = {kind: sum(s['end_seconds']-s['start_seconds'] for s in segments if s['kind'] == kind)
              for kind in ('moving', 'relative_still', 'unknown')}
    # Allocate one-decimal percentages so rounding still totals exactly 100%.
    shares = {k: math.floor(v / duration * 1000) for k,v in totals.items()}
    ranked = sorted(totals, key=lambda k: -(totals[k]/duration*1000-shares[k]))
    for kind in ranked[:1000-sum(shares.values())]:
        shares[kind] += 1
    still = [s for s in segments if s['kind'] == 'relative_still']
    longest = max(still, key=lambda s: s['end_seconds']-s['start_seconds'], default=None)
    # A short or missing observation cannot establish a stable pose interval.
    confirmed = longest is not None and longest['end_seconds']-longest['start_seconds'] >= 1-1e-6
    longest = dict(longest, value=round(longest['end_seconds']-longest['start_seconds'],1)) if confirmed else None
    labels = {'moving':'移动', 'relative_still':'姿态停留', 'unknown':'未观测'}
    return {'version':'observed-body-motion-v1', 'time_basis':'source_video',
            'duration_seconds':duration, 'coverage':round((duration-totals['unknown'])/duration,4),
            'segments':segments, 'totals':[{'kind':k, 'label':labels[k], 'seconds':round(v,1), 'percent':shares[k]/10} for k,v in totals.items()],
            'longest_still':longest, 'longest_status':'observed' if confirmed else 'unconfirmed',
            'basis':'registered_body_and_limbs', 'scope':'video_record'}


def enrich_motion_summary(organized):
    output = deepcopy(organized)
    motion = motion_summary(output)
    output['motion_summary'] = motion
    output['torso_trajectory'] = torso_trajectory(output)
    output['metrics'] = [m for m in output.get('metrics',[]) if m['key'] != 'longest_still']
    longest = motion['longest_still']
    output['metrics'].append({'key':'longest_still', 'label':'最长可见姿态停留',
        'value':longest['value'] if longest else None, 'display_value':None if longest else ('未见 ≥1 秒' if motion['coverage'] >= .8 else '尚未确认'),
        'unit':'秒' if longest else '', 'approximate':bool(longest),
        'start_seconds':longest['start_seconds'] if longest else None,
        'end_seconds':longest['end_seconds'] if longest else None,
        'basis':'continuous_registered_motion', 'scope':'video_record'})
    return output
