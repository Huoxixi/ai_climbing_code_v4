"""Select informative, measured events; ordinary moves remain timeline data."""
from copy import deepcopy
import numpy as np
from .replay_action_trajectory import prepare_tracks, chain_pair_reasons, _angle
from .replay_center_of_mass import estimate_center_of_mass

VERSION = 'important-climbing-events-v2'
# Projected engineering threshold, not a universal technique definition.
SIDE_LEAN_DEGREES = 25.
TITLES = {'HIGH_STEP':'高抬腿', 'LEG_DRIVE':'蹬腿发力', 'WEIGHT_SHIFT':'重心调整', 'SIDE_HANG':'侧挂'}


def enrich_important_actions(result):
    output = deepcopy(result)
    tracks = prepare_tracks(output)
    video = output.get('video') or {}
    aspect = np.asarray([video.get('width',1),video.get('height',1)],float)
    aspect /= max(1.,float(min(aspect)))
    selected = []
    for group in output.get('groups', []):
        if group.get('ending_stable') is False:
            group['important_action'] = None
            continue
        if group['id']+':important' in output.get('commentary_omitted_event_ids', []):
            group['important_action'] = None
            continue
        start, end = group['start_seconds'], group['end_seconds']
        rows = [r for r in tracks if start <= r['time'] <= end]
        candidates = []
        if len(rows) < 3 or rows[-1]['time']-rows[0]['time'] < .25:
            group['important_action'] = None
            continue
        gaps = [b['time']-a['time'] for a,b in zip(rows,rows[1:])]
        coverage = (rows[-1]['time']-rows[0]['time'])/max(.001,end-start)
        if any(not 0 < dt <= .6 for dt in gaps) or coverage < .8:
            group['important_action'] = None
            continue
        mass = []
        references = []
        for row in rows:
            estimate = estimate_center_of_mass({'observed':True,
                'kpts_xy':(row['points']/aspect).tolist(), 'kpts_score':row['valid'].astype(float).tolist()}) if row['points'] is not None else None
            mass.append(np.asarray(estimate['xy'])*aspect if estimate else None)
            references.append(tuple(estimate['joints']) if estimate else None)
        mass_reliable = (all(p is not None for p in mass) and len(set(references))==1
            and all(r['scale'] for r in rows)
            and not any(chain_pair_reasons(a,b,limb) for a,b in zip(rows,rows[1:])
                        for limb in ('left_hand','right_hand','left_foot','right_foot'))
            and all(np.linalg.norm(b-a)/dt/min(left['scale'],right['scale'])<=4.5
                    for a,b,dt,left,right in zip(mass,mass[1:],gaps,rows,rows[1:])))
        for limb, chain in (('left_foot',(11,13,15)), ('right_foot',(12,14,16))):
            if any(r['points'] is None or r['scale'] is None or not all(r['valid'][i] for i in chain) for r in rows):
                continue
            if any(chain_pair_reasons(a,b,limb) for a,b in zip(rows,rows[1:])):
                continue
            scale = float(np.median([r['scale'] for r in rows]))
            hip, knee, ankle = chain
            angles = [_angle(r['points'],chain) for r in rows]
            if any(a is None for a in angles):
                continue
            relative = [(r['points'][ankle,1]-r['points'][hip,1])/r['scale'] for r in rows]
            raise_units = relative[0]-min(relative)
            knee_height = min((r['points'][knee,1]-r['points'][hip,1])/r['scale'] for r in rows)
            ankle_up = (rows[0]['points'][ankle,1]-rows[-1]['points'][ankle,1])/scale
            side = '左' if limb.startswith('left') else '右'
            if raise_units >= .3 and ankle_up >= .25 and knee_height <= .15 and min(angles) <= 115:
                candidates.append({'kind':'HIGH_STEP','limb':limb,'score':raise_units,
                    'text':f'{side}腿明显屈膝抬高，膝部接近髋部高度，为较高的落脚位置做准备。',
                    'facts':{'relative_foot_raise_torso_units':round(raise_units,3),
                             'minimum_knee_angle_degrees':round(min(angles),1),
                             'knee_height_below_hip_torso_units':round(knee_height,3)}})
            foot_span = max(float(np.linalg.norm(r['points'][ankle]-rows[0]['points'][ankle])/scale) for r in rows)
            # Locate the rapid extension inside the complete action window;
            # preparation and the stable tail must not dilute its velocity.
            drives = []
            if mass_reliable:
                for first in range(len(rows)-2):
                    for last in range(first+2, len(rows)):
                        dt = rows[last]['time']-rows[first]['time']
                        extension = angles[last]-angles[first]
                        delta = (mass[last]-mass[first])/scale
                        motion = float(np.linalg.norm(delta))
                        local_foot = max(float(np.linalg.norm(r['points'][ankle]-rows[first]['points'][ankle])/scale) for r in rows[first:last+1])
                        if (.15 <= dt <= 1. and angles[first] <= 135 and angles[last] >= 150
                                and extension >= 25 and extension/dt >= 45
                                and motion >= .18 and motion/dt >= .3 and local_foot <= .18
                                and delta[1] <= .04
                                and all(angles[k+1]-angles[k] >= -5 for k in range(first,last))):
                            drives.append((extension/dt,first,last,extension,motion,local_foot))
            if drives:
                angular_speed, first, last, extension, rise, foot_span = max(drives)
                candidates.append({'kind':'LEG_DRIVE','limb':limb,'score':rise+extension/100,
                    'text':f'{side}脚位置基本保持，弯曲的{side}膝迅速伸直，估算重心同步快速移动；可见蹬腿与身体移动的衔接，随后身体稳定。',
                    'facts':{'knee_extension_degrees':round(extension,1),
                             'knee_extension_degrees_per_second':round(angular_speed,1),
                             'rapid_phase_start_seconds':rows[first]['time'],
                             'rapid_phase_end_seconds':rows[last]['time'],
                             'center_of_mass_motion_torso_units':round(rise,3),
                             'foot_motion_torso_units':round(foot_span,3)}})
        if all(r['points'] is not None and all(r['valid'][i] for i in (5,6,11,12)) for r in rows):
            tilts = []
            for row in rows:
                axis = np.mean(row['points'][[5,6]],axis=0)-np.mean(row['points'][[11,12]],axis=0)
                tilts.append(float(np.degrees(np.arctan2(axis[0],-axis[1]))))
            # Sustained final posture rejects a brief swing or a single noisy frame.
            tail = [i for i,r in enumerate(rows) if r['time'] >= rows[-1]['time']-.8-1e-6]
            final = float(np.median([tilts[i] for i in tail]))
            if (len(tail)>=3 and rows[-1]['time']-rows[tail[0]]['time']>=.5
                    and abs(final)>=SIDE_LEAN_DEGREES and abs(final-tilts[0])>=15
                    and all(abs(tilts[i]-final)<=8 for i in tail)
                    and not any(chain_pair_reasons(a,b,limb) for a,b in zip(rows,rows[1:]) for limb in ('left_hand','right_hand'))):
                candidates.append({'kind':'SIDE_HANG','limb':'body','score':abs(final)/90,
                    'text':f'躯干明显向{"右" if final>0 else "左"}侧倾斜，肩髋连线相对画面竖直方向约{abs(final):.0f}°，随后保持稳定侧倾姿态。',
                    'facts':{'projected_torso_tilt_degrees':round(final,1),
                             'tilt_change_degrees':round(final-tilts[0],1),
                             'engineering_threshold_degrees':SIDE_LEAN_DEGREES}})
        if mass_reliable:
            scale = float(np.median([r['scale'] for r in rows]))
            delta = (mass[-1]-mass[0])/scale
            feet_span = max(float(np.linalg.norm(r['points'][i]-rows[0]['points'][i])/scale)
                            for r in rows for i in (15,16))
            if abs(delta[0]) >= .22 and abs(delta[0]) >= abs(delta[1])*1.4 and feet_span <= .22:
                direction = '左' if delta[0]<0 else '右'
                candidates.append({'kind':'WEIGHT_SHIFT','limb':'body','score':abs(delta[0]),
                    'text':f'双脚位置基本保持，估算重心明显向{direction}侧转移，身体随之横移；这一阶段以调整身体位置为主。',
                    'facts':{'center_of_mass_horizontal_torso_units':round(float(delta[0]),3),
                             'foot_motion_torso_units':round(feet_span,3)}})
        previous = group.get('important_action') or {}
        if not candidates:
            group['important_action'] = None
            continue
        # One explanation per event, prioritizing leg coordination over generic translation.
        choice = max(candidates, key=lambda c:({'LEG_DRIVE':4,'SIDE_HANG':3,'HIGH_STEP':2,'WEIGHT_SHIFT':1}[c['kind']],c['score']))
        action = {'id':group['id']+':important','group_id':group['id'],'limb':choice['limb'],
            'important_event':True, 'kind':choice['kind'],'title':TITLES[choice['kind']], 'policy_version':VERSION,
            'start_seconds':start, 'end_seconds':end, 'source_hold_id':None,'target_hold_id':None,
            'joint_angles':{'definition':'source_projected_angle','unit':'degrees','series':[]},
            'relative_displacement':choice['facts'],'phases':[],
            'quality':{'status':'observed','coverage':min(1.,coverage),'max_sample_gap_seconds':max(gaps),'reasons':[]},
            'evidence_frames':[{'frame_id':r['frame_id'],'time_seconds':r['time']} for r in rows],
            'provenance':{'feature_version':VERSION,'time_basis':'source_video'},
            'commentary':choice['text'],'commentary_basis':'local_key_observation',
            'limitations':['二维姿态估算，不能测量真实受力或确认岩点承重']}
        if (previous.get('policy_version')==VERSION and previous.get('kind')==action['kind']
                and previous.get('start_seconds')==start and previous.get('end_seconds')==end
                and previous.get('commentary_basis')=='vision_evidence'):
            for key in ('commentary','commentary_basis','commentary_evidence'):
                action[key] = deepcopy(previous[key])
        group['important_action'] = action
        selected.append(action)
    output['commentary_policy'] = {'version':VERSION,'important_only':True,'selected_event_count':len(selected),
        'skipped_event_count':len(output.get('groups',[]))-len(selected),
        'empty_message':'未找到证据充分的重要动作，普通移动片段不作评语。'}
    output.setdefault('action_evidence', {})['commentary_actions'] = selected
    return output
