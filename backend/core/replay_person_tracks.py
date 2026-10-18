"""Clip-local multi-person association and separate offline target selection.

All identities remain candidates until the clip is inspected. Assignment never
depends on which person is selected, and never creates a missing detection.
Motion/colour association is a transparent baseline, not learned ReID.
"""
from dataclasses import dataclass, field
import math

import numpy as np

VERSION = 'offline-multitrack-clip-target-v3'
DETECTION_VERSION = 'scored-person-two-stage-v1'
# Preserve the former effective native-NMS high threshold. Low detections can
# only continue an existing identity; they cannot start a track.
PERSON_HIGH_SCORE = .3
PERSON_LOW_SCORE = .1


def body_context_coverage(row):
    """Number of observed body candidates inside this actual detector context.

    This chooses context among proposals of the SAME torso, not person identity.
    A compact torso box must not outrank a proposal containing the observed legs.
    Model points remain unverified; no missing joint is created by this metric.
    """
    points=(row.get('body') or {}).get('body_xy')
    if points is None:return 0
    points=np.asarray(points,float)
    box=np.asarray(row['box'],float)
    if points.shape!=(12,2):return 0
    return int(np.count_nonzero(np.isfinite(points).all(axis=1)
        & (points>=box[:2]).all(axis=1)&(points<=box[2:]).all(axis=1)))


def consolidate_bodies(observations):
    """Detector proposals are not person identities. Merge only bodies with
    matching observed shoulders AND hips, retaining all source proposals.
    Pure overlapping boxes cannot merge two crossing people.
    """
    result = []
    for row in observations:
        row = {**row, 'detector_proposals': [row['box_xyxy_px']]}
        body = row.get('body') or {}
        torso = body.get('torso_xy')
        if torso is not None:
            torso = np.asarray(torso, float)
            scale = np.linalg.norm(torso[:2].mean(axis=0)-torso[2:].mean(axis=0))
            for i, previous in enumerate(result):
                other = (previous.get('body') or {}).get('torso_xy')
                if other is None or scale<=0:
                    continue
                if np.max(np.linalg.norm(torso-np.asarray(other),axis=1)) <= .1*scale:
                    proposals = previous['detector_proposals']+row['detector_proposals']
                    # Choose complete body context before compactness; identity
                    # consolidation does not authorize cutting off observed legs.
                    area=lambda value:float(np.prod(np.asarray(value['box'])[2:]-value['box'][:2]))
                    if (body_context_coverage(row),-area(row)) > (body_context_coverage(previous),-area(previous)):
                        result[i] = row
                    result[i]['detector_proposals'] = proposals
                    break
            else:
                result.append(row)
        else:
            result.append(row)
    return result


def assignment(cost):
    """Minimum-cost rectangular assignment (Hungarian); no scipy dependency."""
    cost = np.asarray(cost, float)
    if not cost.size:
        return []
    transposed = cost.shape[0] > cost.shape[1]
    if transposed:
        cost = cost.T
    rows, cols = cost.shape
    u, v = np.zeros(rows+1), np.zeros(cols+1)
    p, way = np.zeros(cols+1, int), np.zeros(cols+1, int)
    for i in range(1, rows+1):
        p[0] = i
        j0 = 0
        minimum, used = np.full(cols+1, np.inf), np.zeros(cols+1, bool)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], np.inf, 0
            for j in range(1, cols+1):
                if not used[j]:
                    current = cost[i0-1, j-1] - u[i0] - v[j]
                    if current < minimum[j]:
                        minimum[j], way[j] = current, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(cols+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(p[j]-1, j-1) for j in range(1, cols+1) if p[j]]
    return [(j,i) for i,j in pairs] if transposed else pairs


def overlap(a, b):
    low, high = np.maximum(a[:2], b[:2]), np.minimum(a[2:], b[2:])
    intersection = np.prod(np.maximum(0, high-low))
    return float(intersection/max(1e-10, np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-intersection))


def colour_distance(a, b):
    if a is None or b is None:
        return .5
    return math.sqrt(max(0., 1-float(np.sqrt(np.asarray(a)*np.asarray(b)).sum())))


@dataclass
class PersonTrack:
    track_id: int
    observations: list = field(default_factory=list)

    def predicted_box(self, time, *, space=None):
        last = self.observations[-1]
        space = space or last.get('association_space', 'source')
        key = 'association_box' if space == 'reference' else 'box'
        box = np.array(last[key], float)
        if len(self.observations) > 1:
            previous = self.observations[-2]
            dt = last['time']-previous['time']
            if dt > 0:
                # A prediction is used for association only. Source coordinates
                # emitted to pose/render/contact always come from a real frame.
                velocity = (box[:2]+box[2:]-np.asarray(previous[key])[:2]
                            -np.asarray(previous[key])[2:])/(2*dt)
                box += np.tile(velocity*(time-last['time']), 2)
        return box


class ClipPersonTracks:
    def __init__(self, *, max_gap_seconds=1.5, low_score_recovery=False):
        self.max_gap_seconds = max_gap_seconds
        self.low_score_recovery = low_score_recovery
        self.tracks = []
        self.frames = {}
        self.selection = None

    def add_frame(self, source_frame_id, time, observations):
        if source_frame_id in self.frames:
            raise ValueError('A source frame must be associated once')
        if self.frames and time <= max(row['time'] for row in self.frames.values()):
            raise ValueError('Association requires increasing source time')
        active = [track for track in self.tracks
                  if time-track.observations[-1]['time'] <= self.max_gap_seconds]
        if self.low_score_recovery:
            high = [row for row in observations if row.get('detector_score', 1.) > PERSON_HIGH_SCORE]
            low = [row for row in observations
                   if PERSON_LOW_SCORE < row.get('detector_score', 1.) <= PERSON_HIGH_SCORE]
        else:
            high, low = observations, []
        observations = high
        # Each active track has its own unmatched column. A detection can never
        # be assigned to two people; disappearance never invokes target switching.
        costs = np.full((len(active), len(observations)+len(active)), 3., float)
        for i, track in enumerate(active):
            last = track.observations[-1]
            for j, observation in enumerate(observations):
                # Never compare a source-image box with a reference-image box.
                # If registration is unavailable on either side, use actual
                # source coordinates for both; no invented camera transform.
                reference = (observation.get('association_space') == 'reference'
                             and all(row.get('association_space') == 'reference'
                                     for row in track.observations[-2:]))
                predicted = track.predicted_box(time, space='reference' if reference else 'source')
                size = np.maximum(predicted[2:]-predicted[:2], 1e-6)
                box = np.asarray(observation['association_box'] if reference else observation['box'], float)
                center_distance = np.linalg.norm((box[:2]+box[2:]-predicted[:2]-predicted[2:])/(2*np.linalg.norm(size)))
                scale_distance = np.mean(np.abs(np.log(np.maximum(box[2:]-box[:2],1e-6)/size)))
                appearance = colour_distance(last.get('appearance'), observation.get('appearance'))
                costs[i,j] = (1-overlap(predicted,box)) + center_distance + scale_distance + appearance
        matched = {}
        for i, j in assignment(costs):
            if j < len(observations) and costs[i,j] < 3:
                matched[j] = active[i]
        # ByteTrack-style second association: only unused tracks may consume
        # low-score detections. High-score assignments remain final. IoU and
        # appearance reject unrelated weak proposals; no synthetic box is saved.
        used = {track.track_id for track in matched.values()}
        remaining = [track for track in active if track.track_id not in used]
        low_cost = np.full((len(remaining), len(low)+len(remaining)), .5)
        for i, track in enumerate(remaining):
            for j, row in enumerate(low):
                reference = (row.get('association_space') == 'reference'
                    and all(r.get('association_space') == 'reference' for r in track.observations[-2:]))
                predicted = track.predicted_box(time, space='reference' if reference else 'source')
                box = row['association_box'] if reference else row['box']
                distance = colour_distance(track.observations[-1].get('appearance'), row.get('appearance'))
                if distance <= .35:
                    low_cost[i,j] = 1-overlap(predicted, np.asarray(box))
        for i, j in assignment(low_cost):
            if j < len(low) and low_cost[i,j] < .5:
                matched[len(observations)] = remaining[i]
                observations.append({**low[j], 'detection_recovery': 'low_score_existing_track'})
        rows = []
        for j, observation in enumerate(observations):
            track = matched.get(j)
            if track is None:
                track = PersonTrack(len(self.tracks)+1)
                self.tracks.append(track)
            row = {**observation, 'source_frame_id': int(source_frame_id), 'time': float(time),
                   'track_id': track.track_id}
            track.observations.append(row)
            rows.append(row)
        self.frames[int(source_frame_id)] = {'time': float(time), 'observations': rows}

    def select_target(self):
        """Rank full trajectories, with explicit evidence and unresolved ties.

        The baseline's target prior is the sustained visible filming subject.
        This does not infer human intent when equally prominent climbers coexist.
        Pose motion is reported separately; a raised arm is not a target label.
        """
        ranked = []
        times = sorted(frame['time'] for frame in self.frames.values())
        step = float(np.median(np.diff(times))) if len(times)>1 else 1.
        duration = times[-1]-times[0]+step if times else 1.
        for track in self.tracks:
            rows = track.observations
            areas, visible, ys = [], [], []
            durations = []
            for i,row in enumerate(rows):
                box = np.asarray(row['box'], float)
                areas.append(float(np.prod(box[2:]-box[:2])))
                body = row.get('body') or {}
                visible.append(float(body.get('response_availability', body.get('visible_fraction', 1.))))
                if body.get('torso_center') is not None:
                    ys.append(body['torso_center'][1])
                next_time = rows[i+1]['time'] if i+1<len(rows) else row['time']+step
                durations.append(min(step, next_time-row['time']))
            route_values = [r['route_affinity'] for r in rows if r.get('route_affinity') is not None]
            # Integrate visible area through observed clip time. A single early
            # large box cannot determine the target; extra missing frames add zero.
            evidence = float(np.sum(np.asarray(areas)*visible*durations)/duration)
            route_affinity = float(np.mean(route_values)) if route_values else None
            if route_affinity is not None:
                evidence *= route_affinity
            ranked.append({'track_id':track.track_id, 'score':evidence,
                'observed_frames':len(rows), 'observed_seconds':float(sum(durations)),
                'median_area':float(np.median(areas)), 'body_response_availability':float(np.mean(visible)),
                'torso_vertical_range':float(np.ptp(ys)) if ys else None,
                'route_affinity':route_affinity})
        ranked.sort(key=lambda row:(-row['score'], row['track_id']))
        ambiguous = (len(ranked)>1 and ranked[0]['score'] <= ranked[1]['score']*1.15)
        target = ranked[0]['track_id'] if ranked and not ambiguous and ranked[0]['score']>0 else None
        self.selection = {'version':VERSION, 'target_track_id':target,
            'status':'selected' if target is not None else 'ambiguous' if ranked else 'no_detections',
            'basis':'clip_integrated_observed_area_response_availability_and_optional_registered_route',
            'identity_method':'global_one_to_one_motion_colour_baseline_not_learned_reid',
            'candidates':ranked}
        return self.selection

    def target_observation(self, source_frame_id):
        if self.selection is None:
            raise RuntimeError('Finalize the complete clip before requesting target observations')
        target = self.selection['target_track_id']
        rows = self.frames.get(int(source_frame_id), {}).get('observations', [])
        return next((row for row in rows if row['track_id']==target), None)

    def evidence(self):
        return {'selection':self.selection, 'frames':list(self.frames.values())}
