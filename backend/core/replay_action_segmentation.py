"""Action windows require sustained horizontal or vertical displacement."""
import numpy as np

from .replay_action_trajectory import LIMBS, prepare_tracks, chain_pair_reasons, active_relative_delta
from .replay_center_of_mass import estimate_center_of_mass

AXIS_DISPLACEMENT_BODY_UNITS = .18
LIMB_DISPLACEMENT_BODY_UNITS = .25
SETTLE_SECONDS = .8
STABLE_BODY_BAND = .04


def observable(row):
    """A hidden wrist must not discard the visible torso and other limbs."""
    return (row['points'] is not None and row['scale'] is not None
            and sum(row['valid'][5:17]) >= 8
            and sum(row['valid'][i] for i in (5, 6, 11, 12)) >= 3)


def discontinuous(a, b):
    if b.get('boundary_discontinuity'):
        return True
    if not 0 < b['time'] - a['time'] <= .6:
        return True
    return any(chain_pair_reasons(a, b, limb) for limb, chain in LIMBS.items()
               if all(a['valid'][i] and b['valid'][i] for i in chain))


def quiet_pair(anchor, row):
    common = [i for i in range(5, 17) if anchor['valid'][i] and row['valid'][i]]
    return (len(common) >= 8
            and np.max(np.linalg.norm(row['points'][common]-anchor['points'][common], axis=1))
            <= STABLE_BODY_BAND * min(row['scale'], anchor['scale']))


def displacement_bouts(result):
    tracks = prepare_tracks(result)
    # Median aggregation uses only measured points inside a continuous run.
    # It removes frame-to-frame pose jitter, without filling missing joints.
    raw = [{**r, 'points':r['points'].copy() if r['points'] is not None else None} for r in tracks]
    breaks = [False]+[discontinuous(a,b) for a,b in zip(raw,raw[1:])]
    for index,row in enumerate(tracks):
        row['boundary_discontinuity'] = breaks[index]
        if not observable(row):
            continue
        left = right = index
        while left>0 and row['time']-raw[left-1]['time']<=.15+1e-6 and not breaks[left] and observable(raw[left-1]):
            left -= 1
        while right+1<len(raw) and raw[right+1]['time']-row['time']<=.15+1e-6 and not breaks[right+1] and observable(raw[right+1]):
            right += 1
        for joint in range(17):
            if row['valid'][joint]:
                measured = [r['points'][joint] for r in raw[left:right+1] if r['valid'][joint]]
                row['points'][joint] = np.median(measured,axis=0)
        torso = [i for i in (5,6,11,12) if row['valid'][i]]
        row['body'] = np.mean(row['points'][torso],axis=0)
        row['scale'] = float(np.median([np.linalg.norm(row['points'][a]-row['points'][b])
            for a,b in ((5,11),(6,12)) if row['valid'][a] and row['valid'][b]]))
    video = result.get('video') or {}
    aspect = np.asarray([video.get('width', 1), video.get('height', 1)], float)
    aspect /= max(1., float(min(aspect)))
    for row in tracks:
        estimate = estimate_center_of_mass({'observed': True,
            'kpts_xy': (row['points']/aspect).tolist(),
            'kpts_score': row['valid'].astype(float).tolist()}) if row['points'] is not None else None
        row['mass'] = np.asarray(estimate['xy'])*aspect if estimate else None
        # Torso position may locate a boundary; it is never displayed as COM.
        row['position'] = row['body']
    bouts = []

    def locate(run, limb):
        if len(run) < 3:
            return
        scale = float(np.median([r['scale'] for r in run]))
        # Torso compensation prevents a carried hand/foot from becoming another
        # action. Body position has its own channel in the registered wall frame.
        if limb:
            root, _, tip = LIMBS[limb]
            origin = run[0]['points'][tip] - run[0]['points'][root]
            deltas = [active_relative_delta(run[0], row, limb) for row in run]
            if any(delta is None for delta in deltas):
                return
            positions = np.asarray([origin + delta for delta in deltas])
            wall = np.asarray([row['points'][tip] for row in run])
        else:
            positions = np.asarray([row['position'] for row in run])
            wall = positions
            tilts = []
            for row in run:
                axis = np.mean(row['points'][[5,6]],axis=0)-np.mean(row['points'][[11,12]],axis=0)
                tilts.append(float(np.degrees(np.arctan2(axis[0],-axis[1]))))
            if abs(tilts[-1]) >= 25 and abs(tilts[-1]-tilts[0]) >= 15:
                bouts.append({'start':run[0]['time'],'end':run[-1]['time'],'limbs':set()})
        # Median filtering stays inside an observed continuous run. Neither gaps
        # nor a single displaced sample may create an action.
        times = np.asarray([row['time'] for row in run])
        ranges = [(np.searchsorted(times, t-.25-1e-8), np.searchsorted(times, t+.25+1e-8)) for t in times]
        positions = np.asarray([np.median(positions[left:right], axis=0) for left, right in ranges])
        wall = np.asarray([np.median(wall[left:right], axis=0) for left, right in ranges])
        threshold = max(.012, (LIMB_DISPLACEMENT_BODY_UNITS if limb else AXIS_DISPLACEMENT_BODY_UNITS) * scale)
        quiet_band = max(.001, .01 * scale)
        anchor = last_change = 0
        start = None

        def emit(end):
            if start is None or end - start < 2 or run[end]['time'] - run[start]['time'] < .25:
                return
            delta = positions[start:end+1] - positions[start]
            wall_delta = wall[start:end+1] - wall[start]
            # Require one axis to change noticeably. Diagonal jitter, contact
            # labels, clip length and brief pauses are not segmentation evidence.
            if (np.max(np.abs(delta)) < threshold or np.max(np.abs(wall_delta)) < threshold):
                return
            # Direction changes inside an unfinished move are not boundaries.
            bouts.append({'start':run[start]['time'], 'end':run[end]['time'],
                          'limbs':{limb} if limb else set()})

        for i in range(1, len(run)):
            if np.max(np.abs(positions[i] - positions[last_change])) > quiet_band:
                if start is None:
                    start = anchor
                last_change = i
            elif run[i]['time'] - run[last_change]['time'] >= SETTLE_SECONDS:
                emit(i)
                start = None
                anchor = last_change = i
        emit(last_change)

    for limb in (None, *LIMBS):
        run = []
        for row in tracks:
            valid = row['points'] is not None and row['scale'] is not None
            if limb:
                valid = valid and all(row['valid'][i] for i in LIMBS[limb])
            else:
                valid = valid and row['position'] is not None
            broken = run and (not 0 < row['time'] - run[-1]['time'] <= .6
                             or (limb and chain_pair_reasons(run[-1], row, limb)))
            if run and valid and not limb and not broken:
                # A sudden common skeleton jump is still a continuity failure.
                speed = np.linalg.norm(row['body'] - run[-1]['body']) / (row['time'] - run[-1]['time'])
                broken = speed / min(row['scale'], run[-1]['scale']) > 4.5
            if not valid or broken:
                locate(run, limb)
                run = []
            if valid:
                run.append(row)
        locate(run, limb)

    # Finish only after the whole observed body has settled, not when one hand
    # stops. Missing/invalid observations cannot confirm a stable ending.
    completed = []
    for bout in bouts:
        quiet = None
        previous = None
        for row in tracks:
            if row['time'] < bout['end'] - SETTLE_SECONDS:
                continue
            valid = observable(row)
            broken = previous is not None and discontinuous(previous, row)
            if not valid or broken:
                quiet = previous = None
                if row['time'] >= bout['end']:
                    completed.append({**bout, 'settled':False})
                    break
                continue
            if quiet is None or not quiet_pair(quiet, row):
                quiet = row
            previous = row
            if row['time'] >= bout['end'] and row['time']-quiet['time'] >= SETTLE_SECONDS-1e-6:
                completed.append({**bout, 'end':row['time'], 'settled':True})
                break
        else:
            completed.append({**bout, 'settled':False})
    events = []
    for bout in sorted(completed, key=lambda b:b['start']):
        if events and bout['start'] < events[-1]['end']:
            event = events[-1]
            if bout['end'] >= event['end']:
                event['end'], event['settled'] = bout['end'], bout['settled']
            event['limbs'].update(bout['limbs'])
            event['body'] |= not bout['limbs']
        else:
            events.append({**bout, 'body':not bout['limbs']})
    # A channel can span several moves because its relative geometry changes.
    # The measured whole-body stable periods still form authoritative breaks.
    partitioned = []
    for event in events:
        rows = [r for r in tracks if event['start'] <= r['time'] <= event['end']]
        # An unobservable final row must not erase already observed movement.
        while rows and not observable(rows[-1]):
            rows.pop()
        before = len(partitioned)
        first = 0
        quiet = None
        previous = None
        for index, row in enumerate(rows):
            valid = observable(row)
            if not valid or (previous and discontinuous(previous, row)):
                quiet = previous = None
                continue
            if quiet is None or not quiet_pair(quiet, row):
                quiet = row
            previous = row
            settled = row['time']-quiet['time'] >= SETTLE_SECONDS-1e-6
            if not settled and index != len(rows)-1:
                continue
            part = rows[first:index+1]
            reliable = [r for r in part if r['points'] is not None and r['scale']]
            if len(reliable)<3:
                continue
            scale = float(np.median([r['scale'] for r in reliable]))
            masses = [r['position'] for r in reliable]
            body = all(p is not None for p in masses) and np.max(np.abs(np.asarray(masses)-masses[0])) >= .18*scale
            tilts = [np.degrees(np.arctan2(*((np.mean(r['points'][[5,6]],axis=0)-np.mean(r['points'][[11,12]],axis=0))*[1,-1]))) for r in reliable]
            side_hang = abs(tilts[-1]) >= 25 and abs(tilts[-1]-tilts[0]) >= 15
            limbs = set()
            for limb, (root,_,tip) in LIMBS.items():
                if not all(all(r['valid'][j] for j in LIMBS[limb]) for r in reliable):
                    continue
                deltas = [active_relative_delta(reliable[0],r,limb) for r in reliable]
                if (all(d is not None for d in deltas) and np.max(np.abs(deltas)) >= .25*scale
                        and np.max(np.abs(np.asarray([r['points'][tip] for r in reliable])-reliable[0]['points'][tip]))>=.25*scale):
                    limbs.add(limb)
            if body or limbs or side_hang:
                partitioned.append({'start':part[0]['time'],'end':row['time'],'body':bool(body),
                                    'limbs':limbs,'settled':bool(settled)})
                first = index
        if len(partitioned)==before and rows and rows[-1]['time']-event['start']>=.25:
            partitioned.append({**event,'end':rows[-1]['time'],'settled':False})
    return partitioned
