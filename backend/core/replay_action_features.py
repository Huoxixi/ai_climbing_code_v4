"""Versioned action facts and research-only HIGH_STEP/CROSS features."""
from copy import deepcopy
import numpy as np
from .replay_action_trajectory import prepare_tracks, analyze_event, LIMBS, LIMB_NAMES
from .replay_observation_validity import joint_mask

VERSION = 'action-evidence-features-v1'
TECHNIQUE_PROTOCOL = {
    'HIGH_STEP': {'name': '高抬脚', 'status': 'independent_validation_pending',
        'required_conditions': ['body_scale_reliable', 'high_foot_visible', 'target_contact_visible'],
        'confusions': ['普通抬脚', '身体下降造成相对脚位升高', '遮挡误定位'],
        'boundary': '抬脚准备至可见落点后稳定；接触不可见时仅保留抬脚观察'},
    'CROSS': {'name': '交叉手', 'status': 'independent_validation_pending',
        'required_conditions': ['path_visible', 'retained_hand_visible', 'midline_crossed'],
        'confusions': ['左右骨架交换', '身体整体横移', '双手同时移动'],
        'boundary': '移动手离开初始位置至目标附近稳定，保留另一手及躯干连续证据'},
}
DISCLAMER = 'AI 评语基于视频中的可见信息，可能存在识别偏差，请结合原片核对。'


def raw_angles(samples, video, start, end, chain):
    rows = []
    for s in samples:
        if not s.get('observed') or not start <= s.get('time_seconds', -1) <= end:
            continue
        try:
            source = np.asarray(s['kpts_xy'], float)
            points = source * [video['width'], video['height']]
            scores = np.asarray(s['kpts_score'])
            valid=joint_mask(source,source,scores,s.get('joint_eligibility'))
            if not all(valid[i] for i in chain) or not np.isfinite(points[list(chain)]).all():
                continue
            a, b, c = points[list(chain)]
            u, v = a-b, c-b
            denominator = np.linalg.norm(u) * np.linalg.norm(v)
            if denominator <= 1e-8:
                continue
            rows.append({'time_seconds': s['time_seconds'], 'frame_id': f"frame-{s['source_frame_id']}",
                'degrees': round(float(np.degrees(np.arccos(np.clip(np.dot(u,v)/denominator,-1,1)))), 2)})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    for previous, current in zip(rows, rows[1:]):
        dt = current['time_seconds']-previous['time_seconds']
        current['angular_velocity_degrees_per_second'] = round((current['degrees']-previous['degrees'])/dt,3) if 0 < dt <= .3 else None
    if rows:
        rows[0]['angular_velocity_degrees_per_second'] = None
    return rows


def technique_conditions(limb, rows, detail):
    if detail.get('status') != 'observed' or len(rows) < 3:
        return []
    # Geometry proposes a research label; missing contact cannot be manufactured.
    chain = LIMBS[limb]
    eligible = [r for r in rows if r['points'] is not None and r['scale'] and all(r['valid'][i] for i in chain)]
    if len(eligible) < 3:
        return []
    code = 'HIGH_STEP' if limb.endswith('foot') else 'CROSS'
    states = {key: 'unknown' for key in TECHNIQUE_PROTOCOL[code]['required_conditions']}
    states['body_scale_reliable' if code == 'HIGH_STEP' else 'path_visible'] = 'satisfied'
    if code == 'HIGH_STEP':
        high = any(r['points'][chain[-1], 1] <= r['points'][chain[0], 1] for r in eligible)
        states['high_foot_visible'] = 'satisfied' if high else 'not_satisfied'
    else:
        visible = [r for r in eligible if all(r['valid'][i] for i in (5,6,11,12,9,10))]
        if len(visible) >= 3:
            values = [r['points'][chain[-1],0] - np.mean(r['points'][[5,6,11,12],0]) for r in visible]
            other = 10 if limb == 'left_hand' else 9
            retained = max(np.linalg.norm(r['points'][other]-visible[0]['points'][other])/r['scale'] for r in visible)
            states['retained_hand_visible'] = 'satisfied' if retained <= .12 else 'not_satisfied'
            states['midline_crossed'] = 'satisfied' if min(values) < 0 < max(values) else 'not_satisfied'
    return [{'code': code, 'status': 'candidate', 'conditions': states,
             'automatic_confirmation': False, 'protocol_version': VERSION}]


def enrich_action_features(organized, job):
    output = deepcopy(organized)
    output.pop('commentary_segments',None)
    output.pop('commentary_omitted_event_ids',None)
    tracks = prepare_tracks(output)
    result = job.get('result') or {}
    source = (job.get('media') or {}).get('source_video') or {}
    original = job.get('high_resolution_source') or {}
    provenance = {'source_sha256': original.get('checksum_sha256') or source.get('checksum_sha256'),
        'analysis_copy_sha256':source.get('checksum_sha256'), 'pose_model': result.get('models',{}).get('pose'),
        'hold_revision': result.get('hold_review_version',0), 'holds_sha256': None,
        'feature_version': VERSION, 'time_basis': 'source_video',
        'trim_start_seconds': (job.get('preparation') or {}).get('trim_start_seconds',0)}
    from .replay_actions import digest
    provenance['holds_sha256'] = digest(result.get('holds', []))
    actions = []
    directions = {'left':'向左', 'right':'向右', 'up':'向上', 'down':'向下',
        'up_left':'向左上方','up_right':'向右上方','down_left':'向左下方','down_right':'向右下方'}
    for group in output.get('groups', []):
        start, end = group['start_seconds'], group['end_seconds']
        rows = [r for r in tracks if start <= r['time'] <= end]
        features = []
        human_events = [e for e in group.get('events',[]) if e.get('evidence_status') == 'human_confirmed']
        selected_limbs = set(group.get('candidate_limbs', LIMBS)) | {e.get('limb') for e in human_events}
        for limb in LIMBS:
            if limb not in selected_limbs:
                continue
            if limb not in LIMBS:
                continue
            detail = analyze_event(output, limb, start, end, tracks)
            measurements = detail.get('measurements') or {}
            if (detail.get('status') == 'observed' and
                    (measurements.get('wall_displacement_body_units', 0) < .25
                     or measurements.get('relative_extent_body_units', 0) < .25)):
                detail['status'] = 'minor_change'
            evidence = [e for e in detail.get('evidence', []) if start <= e['time_seconds'] <= end]
            observed = detail.get('status') in {'observed', 'supported'} and len(evidence) >= 3
            related = [e for e in group.get('events', []) if e.get('limb') == limb]
            angles = raw_angles(output.get('pose_samples',[]), output['video'], start, end, LIMBS[limb])
            gaps = np.diff([r['time'] for r in rows])
            direction = detail.get('measurements',{}).get('wall_direction') or detail.get('wall_direction') or detail.get('direction')
            action = {'id': f"{group['id']}:{limb}", 'group_id': group['id'], 'limb': limb,
                'related_event_ids':[e.get('id') for e in related if e.get('id')],
                'basic_events':[{'type':e.get('action'), 'evidence_status':e.get('evidence_status'),
                    'start_seconds':e.get('start_seconds'), 'end_seconds':e.get('end_seconds')} for e in related],
                'start_seconds': start, 'end_seconds': end, 'duration_seconds': round(end-start,3),
                'source_hold_id': next((e.get('source_hold_id') for e in related if e.get('source_hold_id') is not None),None),
                'target_hold_id': next((e.get('target_hold_id') for e in related if e.get('target_hold_id') is not None),None),
                'target_distance': None, 'support_hold_candidates': [],
                'joint_angles': {'definition':'source_image_projected_pixel_angle', 'unit':'degrees', 'series':angles},
                'relative_displacement': {'coordinate_basis':'wall_reference_torso_relative', 'unit':'torso_length',
                                          'measurements':detail.get('measurements',{}), 'trace':detail.get('trace',[])},
                'quality': {'status':detail.get('status'), 'coverage':detail.get('coverage',0),
                    'max_sample_gap_seconds': round(float(max(gaps)),6) if len(gaps) else None,
                    'reasons':detail.get('reasons',[])}, 'evidence_frames':evidence,
                'phases':detail.get('phases',[]), 'candidate_techniques':technique_conditions(limb,rows,detail),
                'model_score':None, 'human_review':[{'event_id':e.get('id'),'status':'human_confirmed',
                    'start_seconds':e.get('start_seconds'),'end_seconds':e.get('end_seconds'),
                    'action':e.get('action')} for e in human_events if e.get('limb')==limb] or None, 'provenance':provenance,
                'commentary': (f"{LIMB_NAMES[limb]}{directions.get(direction,'')}移动。" if observed else None),
                'commentary_basis':'local_observation' if observed else 'insufficient',
                'context_description':({'stationary':'可见位置基本稳定。', 'body_carried':'随身体共同移动。',
                    'minor_change':'位置轻微变化，未作为独立移动动作。', 'conflict':'局部轨迹不一致，暂不评价。'}.get(detail.get('status'))),
                'limitations': detail.get('limitations',[])}
            features.append(action)
            actions.append(action)
        bodies = [r for r in rows if r['body'] is not None and r['scale'] and r['points'] is not None and all(r['valid'][i] for i in (5,6,11,12))]
        if (len(bodies) >= 3 and bodies[-1]['time']-bodies[0]['time'] >= .25
                and all(0 < b['time']-a['time'] <= .6 and np.linalg.norm(b['body']-a['body'])/(b['time']-a['time'])/min(a['scale'],b['scale']) <= 4.5 for a,b in zip(bodies,bodies[1:]))):
            from .replay_action_trajectory import _direction
            delta = bodies[-1]['body']-bodies[0]['body']
            scale = float(np.median([r['scale'] for r in bodies]))
            direction = _direction(delta,scale)
            coverage = (bodies[-1]['time']-bodies[0]['time']) / max(.001,end-start)
            # Body translation is its own visible event, including moves without a hold transition.
            if direction and coverage >= .8 and np.linalg.norm(delta)/scale >= .18:
                body = {'id':f"{group['id']}:body", 'group_id':group['id'],'limb':'body',
                    'start_seconds':start,'end_seconds':end,'duration_seconds':round(end-start,3),
                    'source_hold_id':None,'target_hold_id':None,'target_distance':None,'support_hold_candidates':[],
                    'related_event_ids':[], 'basic_events':[{'type':'body_move','start_seconds':start,'end_seconds':end,'evidence_status':'trajectory_observed'}],
                    'joint_angles':{'definition':'not_applicable','unit':None,'series':[]},
                    'relative_displacement':{'coordinate_basis':'wall_reference_shoulder_hip_mean','unit':'torso_length',
                        'measurements':{'displacement':round(float(np.linalg.norm(delta)/scale),4)},
                        'trace':[{'time_seconds':r['time'],'x':float(r['body'][0]),'y':float(r['body'][1])} for r in bodies]},
                    'quality':{'status':'observed','coverage':min(1,coverage),
                        'max_sample_gap_seconds':max(b['time']-a['time'] for a,b in zip(bodies,bodies[1:])), 'reasons':[]},
                    'evidence_frames':[{'frame_id':r['frame_id'],'time_seconds':r['time']} for r in bodies],
                    'phases':[],'candidate_techniques':[],'model_score':None,'human_review':None,'provenance':provenance,
                    'commentary':f"身体{directions[direction]}移动。",'commentary_basis':'local_observation',
                    'limitations':['肩髋均值的二维位移，不代表真实重心或受力']}
                features.append(body);actions.append(body)
        group['action_features'] = features
    output['candidate_groups'] = deepcopy(output.get('groups', []))
    output['action_evidence'] = {'version':VERSION, 'actions':actions, 'technique_protocol':TECHNIQUE_PROTOCOL,
        'wholebody_detail_status':'133_points_retained; hand_and_foot_detail_validation_pending',
        'provenance':provenance}
    output['commentary_disclaimer'] = DISCLAMER
    output.setdefault('priority_focus',None)
    from .replay_event_validation import validate_event_sequence
    from .replay_important_actions import enrich_important_actions
    output = enrich_important_actions(output)
    output['event_validation'] = validate_event_sequence(output)
    if result.get('skeleton_only') or job.get('skeleton_only'):
        from .replay_skeleton_mode import without_hold_data
        output = without_hold_data(output)
    return output
