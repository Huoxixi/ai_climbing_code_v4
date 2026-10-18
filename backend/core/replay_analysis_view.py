"""Original on the left; registered evidence only on the right."""
from copy import deepcopy
import math
import cv2
import numpy as np

from .replay_action_trajectory import registered_points
from .replay_torso_trajectory import center_of_mass_trajectory, WINDOW_BASIS
from .replay_center_of_mass import center_of_mass_point, VERSION as MASS_VERSION
from .replay_foot_points import registered_feet, interpolate_feet, EDGES as FOOT_EDGES
from .replay_head_geometry import draw_head, head_geometry, project_head

LAYOUT = 'split_analysis_right_v11'
VISUAL_VERSION = 'registered-observation-limb-labels-v14'
EDGES = ((5,6),(5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16))
COLORS = {'left_hand':(235,196,80),'right_hand':(193,92,237),
          'left_foot':(106,179,255),'right_foot':(87,222,143)}


def limb_badges(sample, width, height):
    """Label observed anatomical sides without reassigning or moving joints."""
    radius = max(7, min(11, width / 80))
    badges = []
    head = project_head(head_geometry(sample,width,height),lambda p: [p[0]*width,p[1]*height])
    clear_head = lambda p: head is None or p[0]<min(q[0] for q in head['outline'])-radius-3 \
        or p[0]>max(q[0] for q in head['outline'])+radius+3 \
        or p[1]<min(q[1] for q in head['outline'])-radius-3 \
        or p[1]>max(q[1] for q in head['outline'])+radius+3
    for joint, text, side in ((9,'左',-1),(10,'右',1),(15,'左',-1),(16,'右',1)):
        xy = sample['kpts_xy'][joint]
        if sample['kpts_score'][joint] < .5 or not all(math.isfinite(v) and 0 < v < 1 for v in xy):
            continue
        anchor = [xy[0]*width, xy[1]*height]
        positions = [[max(radius+2,min(width-radius-2,anchor[0]+dx*radius*1.8)),
                      max(radius+2,min(height-radius-2,anchor[1]+dy*radius*1.8))]
                     for dx,dy in ((side,0),(side,-1),(side,1),(-side,0),(-side,-1),(-side,1),(0,-2),(0,2))]
        clear_badges = lambda p: all(math.dist(p,b['center']) >= radius*2+2 for b in badges)
        center = next((p for p in positions if clear_head(p) and clear_badges(p)),
                      next((p for p in positions if clear_head(p)),
                           next((p for p in positions if clear_badges(p)),positions[0])))
        badges.append(dict(joint=joint,text=text,anchor=anchor,center=center,radius=radius))
    return badges


def visual_evidence(result):
    video = result.get('video') or {}
    poses = []
    for sample in result.get('pose_samples', []):
        frame = sample.get('source_frame_id')
        if not isinstance(frame,int) or isinstance(frame,bool):
            time,fps = sample.get('time_seconds'),video.get('fps')
            if not isinstance(time,(int,float)) or not isinstance(fps,(int,float)) or not math.isfinite(time) or not math.isfinite(fps) or time<0 or fps<=0:
                continue
            frame = round(time*fps)
        if frame<0:
            continue
        mapped = registered_points(sample, video)
        original = deepcopy(sample)
        original['wall_reference_transform'] = np.eye(3).tolist()
        original['wall_alignment'] = 'reference'
        original['wall_alignment_diagnostics'] = {}
        if mapped is not None:
            original['joint_eligibility'] = mapped[1].tolist()
        poses.append({'source_frame_id':frame,
            'feet':registered_feet(sample,video),
            'source_kpts_xy': deepcopy(sample.get('kpts_xy')) if mapped is not None else [[0.,0.]]*17,
            'source_feet': registered_feet(original,video) if mapped is not None else None,
            'time_seconds':sample.get('time_seconds'), 'observed':mapped is not None,
            'kpts_xy':mapped[0].round(6).tolist() if mapped is not None else [[0.,0.]]*17,
            'kpts_score':[(1. if sample.get('joint_eligibility') is not None else float(s)) if valid else 0. for s,valid in zip(sample['kpts_score'],mapped[1])] if mapped is not None else [0.]*17})
    poses.sort(key=lambda s:s['source_frame_id'])
    contacts = deepcopy((result.get('attempt') or {}).get('contacts') or [])
    fps = video.get('fps') or 0
    for contact in contacts:
        for prefix in ('start','end'):
            time = contact.get(f'{prefix}_time_seconds')
            if isinstance(time,(int,float)) and math.isfinite(time) and fps>0:
                contact[f'{prefix}_source_frame'] = time*fps
    return {'version':VISUAL_VERSION, 'video':deepcopy(video), 'pose_samples':poses,
            'contacts':contacts,
            'center_of_mass_trajectory':deepcopy(result.get('center_of_mass_trajectory'))
                if (result.get('center_of_mass_trajectory') or {}).get('version')==MASS_VERSION
                and ((result.get('center_of_mass_trajectory') or {}).get('climbing_window') or {}).get('basis')==WINDOW_BASIS
                else center_of_mass_trajectory(result),
            'center_of_mass':{'version':MASS_VERSION,'label':'估算重心','dimensionality':'2d_projection'}}


class AnalysisView:
    def __init__(self, result):
        from .climb_replay import build_pose_render_timeline
        self.video = result['video']
        evidence = visual_evidence(result)
        self.timeline = build_pose_render_timeline(evidence['pose_samples'], self.video['frame_count'])
        samples = {s['source_frame_id']:s for s in evidence['pose_samples']}
        missing = {s['source_frame_id'] for s in evidence['pose_samples'] if not s['observed']}
        self.timeline = {frame:sample for frame,sample in self.timeline.items()
            if sample.get('render_mode')!='edge_hold' and not (sample.get('render_mode')=='interpolated'
                and (any(sample['left_sample_frame']<bad<sample['right_sample_frame'] for bad in missing)
                    or (sample['right_sample_frame']-sample['left_sample_frame'])/self.video['fps']>.6))}
        for sample in self.timeline.values():
            if sample.get('render_mode')=='interpolated':
                left,right = samples[sample['left_sample_frame']],samples[sample['right_sample_frame']]
                sample['kpts_score'] = [min(a,b) for a,b in zip(left['kpts_score'],right['kpts_score'])]
                alpha=(sample['source_frame_id']-left['source_frame_id'])/(right['source_frame_id']-left['source_frame_id'])
                sample['feet']=interpolate_feet(left.get('feet'),right.get('feet'),alpha)
            else:
                sample['feet']=samples[sample['source_frame_id']].get('feet')
        self.trajectory = evidence['center_of_mass_trajectory']
        self.holds = result.get('holds') or []
        self.contacts = evidence['contacts']
        # The same observation/eligibility/interpolation contract, in source pixels.
        original = deepcopy(result)
        for sample in original.get('pose_samples', []):
            qualified = registered_points(sample, self.video)
            if qualified is None:
                sample['observed'] = False
            else:
                sample['joint_eligibility'] = qualified[1].tolist()
            sample['wall_reference_transform'] = np.eye(3).tolist()
            sample['wall_alignment'] = 'reference'
            sample['wall_alignment_diagnostics'] = {}
        self.source_timeline = None
        if not result.get('_source_coordinate_view'):
            original['_source_coordinate_view'] = True
            self.source_timeline = AnalysisView(original).timeline

    def compose(self, raw, index, size, *, show_skeleton=False, show_human=True,
                show_diagram=True, background=None, reference_to_background=None):
        """Compose scene and independent complete diagram without distorting either."""
        width, height = size
        scene = show_human or show_skeleton
        panes = int(scene) + int(show_diagram)
        if not panes:
            raise ValueError('Choose at least one picture')
        if show_skeleton and not show_human and background is None:
            raise ValueError('Empty background is unavailable')
        pane = width // panes
        canvas = np.full((height, width, 3), (13,16,18), np.uint8)
        if scene:
            image = raw if show_human else background
            scale = min(pane/image.shape[1], height/image.shape[0])
            w, h = max(1,round(image.shape[1]*scale)), max(1,round(image.shape[0]*scale))
            x, y = (pane-w)//2, (height-h)//2
            canvas[y:y+h,x:x+w] = cv2.resize(image,(w,h),interpolation=cv2.INTER_AREA)
            if show_skeleton:
                sample = (self.source_timeline if show_human else self.timeline).get(index)
                if sample:
                    matrix = np.eye(3) if show_human else np.asarray(reference_to_background, float)
                    def project(point, inside=True):
                        p = matrix @ [point[0]*self.video['width'], point[1]*self.video['height'], 1.]
                        if not np.isfinite(p).all() or abs(p[2]) < 1e-8:
                            return None
                        px, py = p[:2]/p[2]/[self.video['width'],self.video['height']]
                        return (x+px*w,y+py*h) if not inside else (round(x+px*w),round(y+py*h)) if 0<px<1 and 0<py<1 else None
                    # Restrict artwork to the scene; never paint another pane.
                    scene_crop = canvas[y:y+h,x:x+w]
                    def head_point(p):
                        q = project(p, False)
                        return (q[0]-x,q[1]-y) if q is not None else None
                    draw_head(scene_crop,sample,self.video['width'],self.video['height'],head_point)
                    stroke = max(2,round(min(w,h)/220))
                    def bones(points, scores, edges):
                        for a,b in edges:
                            if min(scores[a],scores[b]) >= .5:
                                pa,pb = project(points[a]),project(points[b])
                                if pa is not None and pb is not None:
                                    cv2.line(canvas,pa,pb,(144,222,232),stroke,cv2.LINE_AA)
                    bones(sample['kpts_xy'],sample['kpts_score'],EDGES)
                    feet = sample.get('feet')
                    if feet:
                        bones(feet['kpts_xy'],feet['kpts_score'],FOOT_EDGES)
        if show_diagram:
            diagram = self.frame(raw,index,(pane*2,height))[:,pane:]
            offset = pane if scene else 0
            canvas[:,offset:offset+pane] = diagram
        return canvas

    def frame(self, raw, index, size):
        width,height = size
        pane = width//2
        scale = min(pane/raw.shape[1],height/raw.shape[0])
        w,h = max(1,round(raw.shape[1]*scale)),max(1,round(raw.shape[0]*scale))
        x,y = (pane-w)//2,(height-h)//2
        canvas = np.full((height,width,3),(13,16,18),np.uint8)
        canvas[y:y+h,x:x+w] = cv2.resize(raw,(w,h),interpolation=cv2.INTER_AREA)
        right = canvas[:,pane:]
        stroke = max(1,round(min(w,h)/240))
        def point(xy):
            return (round(x+xy[0]*w),round(y+xy[1]*h))
        active = {}
        for contact in self.contacts:
            start,end = contact.get('start_source_frame'),contact.get('end_source_frame')
            limb = contact.get('limb')
            if (limb in COLORS and isinstance(start,(int,float)) and isinstance(end,(int,float))
                    and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end
                    and start <= index <= end and (limb not in active or start > active[limb][0])):
                active[limb] = (start,str(contact.get('hold_id')))
        occupied = {hold:limb for limb,(_,hold) in active.items()}
        finished = index >= self.video['frame_count'] - 1
        used = {str(c.get('hold_id')) for c in self.contacts if c.get('limb') in COLORS
            and isinstance(c.get('start_source_frame'),(int,float)) and isinstance(c.get('end_source_frame'),(int,float))
            and math.isfinite(c['start_source_frame']) and math.isfinite(c['end_source_frame'])
            and 0 <= c['start_source_frame'] <= c['end_source_frame'] and c['start_source_frame'] <= index}
        for hold in self.holds:
            polygon = hold.get('polygon') or []
            if len(polygon)<3 and len(hold.get('bbox') or [])>=4:
                bx,by,bw,bh = hold['bbox'][:4]
                polygon = [[bx,by],[bx+bw,by],[bx+bw,by+bh],[bx,by+bh]]
            if len(polygon)<3:
                continue
            poly = np.asarray([point(p) for p in polygon],np.int32)
            limb = occupied.get(str(hold.get('id')))
            color = COLORS.get(limb,(128,135,129))
            if finished and str(hold.get('id')) in used:
                color = (75,208,241)
            if limb or finished and str(hold.get('id')) in used:
                cv2.fillPoly(right,[poly],color,cv2.LINE_AA)
            cv2.polylines(right,[poly],True,color,stroke,cv2.LINE_AA)
        time = index/self.video['fps']
        for run in self.trajectory.get('segments',[]):
            points = [point(p['xy']) for p in run if p['time_seconds'] <= time]
            if len(points)>=2:
                cv2.polylines(right,[np.asarray(points,np.int32)],False,(238,231,117),stroke,cv2.LINE_AA)
        sample = self.timeline.get(index)
        if sample:
            xy,scores = sample['kpts_xy'],sample['kpts_score']
            draw_head(right,sample,self.video['width'],self.video['height'],
                      lambda p: (x+p[0]*w,y+p[1]*h))
            for a,b in EDGES:
                if min(scores[a],scores[b])>=.5:
                    cv2.line(right,point(xy[a]),point(xy[b]),(144,222,232),stroke+1,cv2.LINE_AA)
            for p,score in zip(xy[5:],scores[5:]):
                if score>=.5:
                    cv2.circle(right,point(p),stroke+1,(151,232,245),-1,cv2.LINE_AA)
            feet=sample.get('feet')
            if feet:
                for a,b in FOOT_EDGES:
                    if min(feet['kpts_score'][a],feet['kpts_score'][b])>=.5:
                        cv2.line(right,point(feet['kpts_xy'][a]),point(feet['kpts_xy'][b]),(144,222,232),stroke+1,cv2.LINE_AA)
            center = center_of_mass_point(sample)
            if center is not None:
                cv2.circle(right,point(center),max(3,stroke+2),(255,255,255),-1,cv2.LINE_AA)
            from .climb_replay import draw_cjk_labels
            labels = []
            for badge in limb_badges(sample,w,h):
                anchor = (round(x+badge['anchor'][0]),round(y+badge['anchor'][1]))
                cx,cy = round(x+badge['center'][0]),round(y+badge['center'][1])
                radius = round(badge['radius'])
                cv2.line(right,anchor,(cx,cy),(185,217,221),1,cv2.LINE_AA)
                left,top = max(0,cx-radius-1),max(0,cy-radius-1)
                crop = right[top:min(height,cy+radius+2),left:min(right.shape[1],cx+radius+2)]
                layer = crop.copy()
                cv2.circle(layer,(cx-left,cy-top),radius,(15,16,14),-1,cv2.LINE_AA)
                cv2.addWeighted(layer,.82,crop,.18,0,dst=crop)
                cv2.circle(right,(cx,cy),radius,(185,217,221),1,cv2.LINE_AA)
                size = round(badge['radius']*1.35)
                labels.append(dict(text=badge['text'],fallback='L' if badge['text']=='左' else 'R',
                    origin=(cx-size//2,cy-size//2-2),size=size,color=(212,233,238)))
            draw_cjk_labels(right,labels)
        return canvas
