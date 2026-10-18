"""Conservative pose-only onset; uncertain clips require a user start mark."""
import numpy as np
from .replay_action_trajectory import prepare_tracks, chain_pair_reasons, finite

BASIS = 'pose_onset_or_user_start_v1'


def pose_climbing_window(result):
    duration = result.get('source_duration_seconds', (result.get('video') or {}).get('duration_seconds', 0))
    output = {'basis': BASIS, 'status': 'start_unconfirmed', 'start_seconds': None,
              'end_seconds': None, 'end_basis': 'last_reliable_observation', 'finish_confirmed': False}
    if not finite(duration) or duration <= 0:
        return output
    rows = prepare_tracks(result)
    from .replay_center_of_mass import estimate_center_of_mass
    size = result.get('video') or {}
    aspect = np.array([size.get('width', 1), size.get('height', 1)], float)
    aspect /= max(1., min(aspect))
    def reliable(row):
        return (row['scale'] is not None and row['points'] is not None
                and estimate_center_of_mass({'observed': True,
                    'kpts_xy': (row['points'] / aspect).tolist(),
                    'kpts_score': row['valid'].astype(float).tolist()}) is not None)
    valid = [row for row in rows if 0 <= row['time'] <= duration and reliable(row)]
    marked = result.get('trajectory_start_seconds')
    if finite(marked) and 0 <= marked < duration:
        output.update(status='user_confirmed', start_seconds=marked)
    else:
        # Two raised, stationary hands + sustained upward body and foot movement.
        # A complete standing/walking skeleton or a single raised hand is insufficient.
        run = []
        for row in rows:
            if (not reliable(row) or not 0 <= row['time'] <= duration
                    or run and (row['time'] - run[-1]['time'] > .6
                    or any(chain_pair_reasons(run[-1], row, limb)
                           for limb in ('left_hand', 'right_hand', 'left_foot', 'right_foot')))):
                run = []
                continue
            run.append(row)
            while run and row['time'] - run[0]['time'] > 2.5:
                run.pop(0)
            if len(run) < 4 or row['time'] - run[0]['time'] < .8:
                continue
            first = run[0]
            scale = float(np.median([r['scale'] for r in run]))
            raised = all(all(r['points'][w, 1] < r['points'][s, 1] - .1 * scale
                             for w, s in ((9, 5), (10, 6))) for r in run)
            fixed = all(np.max(np.linalg.norm(np.array([r['points'][w] for r in run])
                             - first['points'][w], axis=1)) < .18 * scale for w in (9, 10))
            risen = [r for r in run if first['body'][1] - r['body'][1] >= .25 * scale
                     and max(first['points'][f, 1] - r['points'][f, 1] for f in (15, 16)) >= .15 * scale]
            if raised and fixed and len(risen) >= 2 and row['time'] - risen[0]['time'] >= .4:
                output.update(status='pose_start_observed', start_seconds=first['time'])
                break
    start = output['start_seconds']
    if start is not None:
        output['end_seconds'] = max((r['time'] for r in valid if r['time'] >= start), default=None)
    return output
