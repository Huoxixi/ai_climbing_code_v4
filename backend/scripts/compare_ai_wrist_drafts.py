"""Compare source-bound pose observations with unreviewed AI visual drafts.

Distances here measure disagreement, never accuracy. Missing predictions remain
in denominators; hidden wrists never receive interpolated reference positions.
"""
import argparse
import csv
import hashlib
import html
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

from PIL import Image, ImageDraw, ImageFont

from core.replay_pose_observation import observation_record

SIDES = (('left', 9), ('right', 10))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_point(value):
    return value is not None and len(value) == 2 and all(v is not None and math.isfinite(v) for v in value)


def compare_joint(task, side, joint_id, record):
    label = task['joints'][side + '_wrist']
    observation = record.get('joint_observations', {}) if record else {}
    native = observation.get('raw_xy_px', [])
    point = native[joint_id] if len(native) > joint_id and finite_point(native[joint_id]) else None
    observed = bool(record and record.get('pose_evidence', {}).get('observed'))
    point = point if observed else None
    eligibility = record.get('joint_eligibility', []) if record else []
    eligible = bool(point is not None and len(eligibility) > joint_id and eligibility[joint_id])
    responses = observation.get('raw_response', [])
    response = responses[joint_id] if len(responses) > joint_id else None
    visible = label['visibility'] == 'visible' and finite_point(label['xy_px'])
    distance = math.dist(point, label['xy_px']) if visible and point is not None else None
    other = task['joints'][('right' if side == 'left' else 'left') + '_wrist']
    alternate_distance = math.dist(point, other['xy_px']) if visible and point is not None and other['visibility'] == 'visible' and finite_point(other['xy_px']) else None
    fragment = task['hand_regions'][side].get('visible_hand_box_xyxy_px')
    fragment_distance = None
    if point is not None and fragment:
        x, y = point
        x1, y1, x2, y2 = fragment
        fragment_distance = math.hypot(max(x1-x, 0, x-x2), max(y1-y, 0, y-y2))
    return {
        'case': task['case'], 'source_frame_id': task['source_frame_id'],
        'time_seconds': task['time_seconds'], 'side': side,
        'reference_visibility': label['visibility'], 'reference_xy_px': label['xy_px'],
        'reference_radius_px': label['visual_radius_px'], 'reference_human_reviewed': False,
        'source_sha256': task['source_sha256'], 'model_observed': observed,
        'model_xy_px': point, 'model_native_response': response, 'model_eligible': eligible,
        'distance_to_ai_draft_px': distance,
        'distance_to_opposite_ai_draft_px': alternate_distance,
        'opposite_draft_closer_by_20px': bool(distance is not None and alternate_distance is not None and distance-alternate_distance > 20),
        'eligible_gap_gt50px': bool(eligible and distance is not None and distance > 50),
        'prediction_on_unlocalizable_reference': bool(not visible and eligible),
        'visible_hand_fragment_xyxy_px': fragment,
        'distance_to_visible_fragment_box_px': fragment_distance,
        'interpretation': 'AI_draft_disagreement_not_accuracy' if visible else 'wrist_location_not_scorable',
        'note': label['note'],
    }


def summarize(rows):
    visible = [r for r in rows if r['reference_visibility'] == 'visible']
    localized = [r for r in visible if r['distance_to_ai_draft_px'] is not None]
    admitted = [r for r in localized if r['model_eligible']]
    distances = [r['distance_to_ai_draft_px'] for r in localized]
    hidden = [r for r in rows if r['reference_visibility'] != 'visible']
    return {
        'wrist_status_entries': len(rows), 'ai_locatable_denominator': len(visible),
        'native_locations_on_ai_locatable': len(localized),
        'eligible_locations_on_ai_locatable': len(admitted),
        'missing_native_on_ai_locatable': len(visible)-len(localized),
        'missing_or_ineligible_on_ai_locatable': len(visible)-len(admitted),
        'mean_disagreement_px': mean(distances) if distances else None,
        'median_disagreement_px': median(distances) if distances else None,
        'max_disagreement_px': max(distances) if distances else None,
        'native_gap_gt20px': sum(d > 20 for d in distances),
        'native_gap_gt50px': sum(d > 50 for d in distances),
        'native_gap_gt100px': sum(d > 100 for d in distances),
        'eligible_gap_gt50px': sum(r['eligible_gap_gt50px'] for r in visible),
        'opposite_draft_closer_by_20px': sum(r['opposite_draft_closer_by_20px'] for r in visible),
        'unlocalizable_reference_denominator': len(hidden),
        'eligible_on_unlocalizable_reference': sum(r['model_eligible'] for r in hidden),
        'accuracy_claim': False,
    }


def crop_record(task, observation):
    if observation is None:
        return None
    return observation_record(
        observation['raw_xy_px'], observation['raw_response'], frame_id=0,
        source_frame_id=task['source_frame_id'], track_id=None, size=task['size_wh'],
        box=observation['box'], model='rtmw-l-384x288-cocktail14-20231122',
        model_evidence={'variant': observation['variant']}, selection={}, minimum_response=.5,
    )


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), 'utf8')


def draw_comparisons(tasks, rows, images, views, output):
    refs = {(v['case'], v['frame']): v for v in views}
    grouped = {(t['case'], t['source_frame_id']): [r for r in rows if (r['case'], r['source_frame_id']) == (t['case'], t['source_frame_id'])] for t in tasks}
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 17)
    for case in sorted({t['case'] for t in tasks}):
        group = [t for t in tasks if t['case'] == case]
        for start in range(0, len(group), 4):
            board = Image.new('RGB', (1440, 1440), '#11171c')
            for i, task in enumerate(group[start:start+4]):
                pair = grouped[(case, task['source_frame_id'])]
                raw = Image.open(images / task['image']).convert('RGB')
                source_box = refs[(case, task['source_frame_id'])]['crop_xyxy']
                xs = [source_box[0], source_box[2]]
                ys = [source_box[1], source_box[3]]
                for row in pair:
                    if row['model_xy_px']:
                        xs.append(row['model_xy_px'][0]); ys.append(row['model_xy_px'][1])
                box = (max(0, int(min(xs))-25), max(0, int(min(ys))-25), min(raw.width, int(max(xs))+26), min(raw.height, int(max(ys))+26))
                crop = raw.crop(box)
                scale = min(680/crop.width, 540/crop.height, 2.5)
                crop = crop.resize((round(crop.width*scale), round(crop.height*scale)))
                panel = Image.new('RGB', (720, 720), '#11171c'); panel.paste(crop, (20, 165))
                d = ImageDraw.Draw(panel)
                d.text((12, 8), f'{case} / frame {task["source_frame_id"]} / {task["time_seconds"]:.2f}s', font=font, fill='white')
                d.text((12, 33), 'Circle = AI draft; X = saved model; not verified truth', font=font, fill='#d6e0e5')
                for j, row in enumerate(pair):
                    side = row['side']; color = '#39ddff' if side == 'left' else '#ef80f9'
                    dist = row['distance_to_ai_draft_px']; eligible = row['model_eligible']
                    text = f'{side.upper()} draft: {row["reference_visibility"]} | gap: '+(f'{dist:.1f}px' if dist is not None else 'N/A')+f' | eligible: {eligible}'
                    d.text((12, 60+j*25), text, font=font, fill=color)
                    def point(xy): return (20+(xy[0]-box[0])*scale, 165+(xy[1]-box[1])*scale)
                    if row['reference_xy_px'] is not None:
                        x, y = point(row['reference_xy_px']);r=max(5, row['reference_radius_px']*scale)
                        d.ellipse((x-r,y-r,x+r,y+r), outline=color, width=2)
                        if row['model_xy_px']:
                            mx,my=point(row['model_xy_px']);d.line((x,y,mx,my), fill=color, width=2)
                    if row['model_xy_px']:
                        x,y=point(row['model_xy_px']);d.line((x-6,y-6,x+6,y+6),fill=color,width=3);d.line((x-6,y+6,x+6,y-6),fill=color,width=3)
                        d.text((x+9,y),side[0].upper()+' MODEL',font=font,fill=color)
                    if row['visible_hand_fragment_xyxy_px']:
                        h=row['visible_hand_fragment_xyxy_px'];x1,y1=point(h[:2]);x2,y2=point(h[2:]);d.rectangle((x1,y1,x2,y2),outline='#ffbb55',width=2)
                        d.text((x1-60,y1-24),'HAND FRAGMENT',font=font,fill='#ffbb55')
                d.text((12, 119), 'Hidden wrist: no reference coordinate, no location score.', font=font, fill='#b6c6ce')
                board.paste(panel, ((i%2)*720, (i//2)*720))
            board.save(output/f'compare-{case}-{start//4+1}.jpg', quality=94)


PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>腕点与AI初标差异</title>
<style>body{margin:0;background:#101820;color:#e9f1f3;font:16px system-ui}header{padding:16px;background:#1b2934;position:sticky;top:0}button,select{font:inherit;padding:7px;margin:4px}main{padding:18px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #34424e;text-align:left}a{color:#69dbec}.note{color:#c1cdd3;line-height:1.6}canvas{display:block;max-width:100%;height:auto;background:#25333d}.focus{display:grid;grid-template-columns:340px minmax(0,1fr);gap:20px}#detail{line-height:1.7}#list{margin-top:25px}#notice{color:#ffd285}</style>
<header><b>腕点差异核对 · AI初标待复核</b> <button onclick="move(-1)">上一帧</button><select id="frame" onchange="go(+this.value)"></select><button onclick="move(1)">下一帧</button><button onclick="showModel=!showModel;draw()">显示／隐藏算法</button><button onclick="showDraft=!showDraft;draw()">显示／隐藏初标</button></header>
<main><p id="notice">本页展示保存的算法输出与AI初标的差异，不能据此报告准确率、认定左右交换或确认遮挡处腕点。</p><div class="focus"><aside><h2 id="heading"></h2><div id="detail"></div><p class="note">圆圈：AI初标与目测定位半径；叉号：算法原生腕点。青色左侧，紫色右侧，均指人物自身左右。橙框只表示可见手部片段。</p><p class="note">只对75个可定位初标计算像素距离；其余69项不计位置分数。缺失和未通过筛选的预测仍保留在分母中。</p><a href="comparison-report.md">完整报告</a> · <a href="wrist-comparison.csv">逐腕CSV</a> · <a href="crop-comparison.csv">候选对照</a></aside><div><canvas id="canvas"></canvas></div></div><div id="list"><h2>优先核对：可定位点差异从大到小</h2><table><thead><tr><th>案例／原帧</th><th>肢体</th><th>差异（像素）</th><th>模型筛选</th><th>参考身份</th></tr></thead><tbody id="rows"></tbody></table></div></main>
<script>const data=__DATA__;let index=data.tasks.findIndex(t=>t.case==='02'&&t.source_frame_id===522),showModel=true,showDraft=true,ready=false;
const byId=id=>document.getElementById(id),c=byId('canvas'),ctx=c.getContext('2d'),img=new Image();
data.tasks.forEach((t,i)=>{let o=document.createElement('option');o.value=i;o.textContent=t.case+' / 帧 '+t.source_frame_id;byId('frame').append(o)});
function go(i){index=Math.max(0,Math.min(data.tasks.length-1,i));let t=data.tasks[index];byId('frame').value=index;byId('heading').textContent=t.case+'／'+t.source_frame_id+'帧 · '+t.time_seconds.toFixed(2)+'秒';byId('detail').replaceChildren();for(let r of t.comparison){let p=document.createElement('p');p.textContent=(r.side==='left'?'左腕':'右腕')+'：初标'+r.reference_visibility+'；差异'+(r.distance_to_ai_draft_px===null?'不计分':r.distance_to_ai_draft_px.toFixed(1)+'像素')+'；模型'+(r.model_eligible?'通过现有筛选':'未通过／缺失')+'。'+r.note;byId('detail').append(p)}ready=false;img.src=t.image;}
img.onload=()=>{ready=true;c.width=img.width;c.height=img.height;draw()};img.onerror=()=>{byId('detail').textContent='原图加载失败，请保留完整资料文件夹。'};
function draw(){if(!ready)return;ctx.drawImage(img,0,0);for(let r of data.tasks[index].comparison){let color=r.side==='left'?'#39ddff':'#ef80f9';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=3;let a=r.reference_xy_px,b=r.model_xy_px;if(showDraft&&a){ctx.beginPath();ctx.arc(a[0],a[1],r.reference_radius_px,0,Math.PI*2);ctx.stroke()}if(showModel&&b){ctx.beginPath();ctx.moveTo(b[0]-7,b[1]-7);ctx.lineTo(b[0]+7,b[1]+7);ctx.moveTo(b[0]-7,b[1]+7);ctx.lineTo(b[0]+7,b[1]-7);ctx.stroke();if(showDraft&&a){ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()}}if(showDraft&&r.visible_hand_fragment_xyxy_px){let h=r.visible_hand_fragment_xyxy_px;ctx.strokeStyle='#ffbb55';ctx.setLineDash([6,4]);ctx.strokeRect(h[0],h[1],h[2]-h[0],h[3]-h[1]);ctx.setLineDash([])}}}
function move(d){go(index+d)}
const ranked=data.rows.filter(r=>r.distance_to_ai_draft_px!==null).sort((a,b)=>b.distance_to_ai_draft_px-a.distance_to_ai_draft_px);
for(let r of ranked){let tr=document.createElement('tr');let td=document.createElement('td'),b=document.createElement('button');b.textContent=r.case+' / '+r.source_frame_id;b.onclick=()=>go(data.tasks.findIndex(t=>t.case===r.case&&t.source_frame_id===r.source_frame_id));td.append(b);tr.append(td);for(let v of [r.side==='left'?'左腕':'右腕',r.distance_to_ai_draft_px.toFixed(1),r.model_eligible?'通过':'未通过','AI初标待复核']){let e=document.createElement('td');e.textContent=v;tr.append(e)}byId('rows').append(tr)}go(index);
</script></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    private = Path(__file__).resolve().parents[2]/'.tmp'
    if not args.output.resolve().is_relative_to(private.resolve()):
        raise ValueError('Private local comparison output required')
    args.output.mkdir(parents=True, exist_ok=False)
    labels = json.loads(args.labels.read_text('utf8')); tasks = labels['tasks']
    if labels['definition']['reference_status'] != 'AI_initial_wrist_only_not_independent_truth':
        raise ValueError('Explicit AI draft identity required')
    if any(t['reviewed_by'] is not None or t['joints'][s+'_wrist']['human_reviewed'] for t in tasks for s,_ in SIDES):
        raise ValueError('This diagnostic expects unreviewed drafts')
    views = json.loads((args.evidence/'ai-wrist-reference-v1/visual-input-manifest.json').read_text('utf8'))
    view_index = {(v['case'],v['frame']):v for v in views}
    sources = {}; records = {}; hashes = {'labels':digest(args.labels)}
    keys = [(t['case'],t['source_frame_id']) for t in tasks]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate source frame')
    for case in sorted({t['case'] for t in tasks}):
        folder = args.evidence/f'detection/case-{case}'
        summary = json.loads((folder/'summary.json').read_text('utf8'))
        raw_cache = json.loads((folder/'raw-cache.json').read_text('utf8'))
        if not summary['source_unchanged'] or summary['source_sha256'] != raw_cache['binding']['source_sha256']:
            raise ValueError('Baseline source binding mismatch')
        sources[case] = {'source_sha256':summary['source_sha256'],'cache_binding':raw_cache['binding']}
        entries=json.loads((folder/'records.json').read_text('utf8'))
        record_keys=[r['source_frame_id'] for r in entries]
        if len(record_keys)!=len(set(record_keys)):
            raise ValueError('Duplicate baseline frame')
        records[case] = {r['source_frame_id']:r for r in entries}
        for name in ('summary.json','records.json','raw-cache.json'):
            hashes[f'{case}/{name}'] = digest(folder/name)
    rows=[]
    for task in tasks:
        if task['source_sha256'] != sources[task['case']]['source_sha256']:
            raise ValueError('AI draft and model source mismatch')
        if digest(args.labels.parent/task['image']) != view_index[(task['case'],task['source_frame_id'])]['image_sha256']:
            raise ValueError('Source PNG mismatch')
        record=records[task['case']].get(task['source_frame_id'])
        if record and record['pose_evidence'].get('source_size_wh',task['size_wh']) != task['size_wh']:
            raise ValueError('Coordinate canvas mismatch')
        for side,jid in SIDES:
            rows.append(compare_joint(task,side,jid,record))
    summary = {'scope':'AI draft disagreement on known development clips, not accuracy',
               'native_observations_reused':True,'new_model_inferences':0,'model_version':'rtmw-l-384x288-cocktail14-20231122',
               'overall':summarize(rows),'by_case':{case:summarize([r for r in rows if r['case']==case]) for case in sources},
               'sources':sources,'human_reviewed_frames':0,'independent_evaluation_eligible':False,
               'reporting_distance_bands_px':[20,50,100],
               'distance_band_semantics':'Descriptive pixel bins, not acceptance thresholds or calibrated tolerances'}
    write_json(args.output/'comparison.json',{'metadata':summary,'rows':rows})
    write_json(args.output/'summary.json',summary)
    with (args.output/'wrist-comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        flat=[{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows]
        writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)

    crops_path=args.evidence/'crops/results.json';crops=json.loads(crops_path.read_text('utf8'));hashes['crop_candidates']=digest(crops_path)
    variants=sorted({o['variant'] for o in crops['observations']})
    crop_index={(f'{o["case"]:02}',o['frame'],o['variant']):o for o in crops['observations']}
    if len(crop_index)!=len(crops['observations']):raise ValueError('Duplicate crop frame/variant')
    for case in sources:
        if crops['hashes'][str(int(case))]['before'] != sources[case]['source_sha256']:raise ValueError('Crop source mismatch')
    shared_frames={(t['case'],t['source_frame_id']) for t in tasks if all((t['case'],t['source_frame_id'],v) in crop_index for v in variants)}
    crop_rows=[];crop_summary={};base_index={(r['case'],r['source_frame_id'],r['side']):r for r in rows}
    for variant in variants:
        current=[]
        for task in tasks:
            rec=crop_record(task,crop_index.get((task['case'],task['source_frame_id'],variant)))
            for side,jid in SIDES:
                row=compare_joint(task,side,jid,rec);row['variant']=variant
                baseline=base_index[(task['case'],task['source_frame_id'],side)];base_dist=baseline['distance_to_ai_draft_px'];dist=row['distance_to_ai_draft_px']
                row['delta_vs_current_px']=dist-base_dist if base_dist is not None and dist is not None else None
                row['shared_frame_for_all_crops']=(task['case'],task['source_frame_id']) in shared_frames
                current.append(row)
        shared=[r for r in current if r['shared_frame_for_all_crops']]
        crop_summary[variant]={'all_reference_denominator':summarize(current),'common_frames':summarize(shared),
            'improved_by_20px_vs_current':sum(r['delta_vs_current_px'] is not None and r['delta_vs_current_px']<=-20 for r in shared),
            'worsened_by_20px_vs_current':sum(r['delta_vs_current_px'] is not None and r['delta_vs_current_px']>=20 for r in shared)}
        crop_rows.extend(current)
    current_shared=[r for r in rows if (r['case'],r['source_frame_id']) in shared_frames]
    write_json(args.output/'crop-comparison.json',{'shared_frames':len(shared_frames),'current_on_shared':summarize(current_shared),'candidates':crop_summary,'rows':crop_rows,'promoted_to_app':False,'scope':'Previously frozen crop experiments rescored against AI drafts, no independent accuracy claim'})
    with (args.output/'crop-comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=['case','source_frame_id','side','variant','reference_visibility','distance_to_ai_draft_px','model_eligible','delta_vs_current_px','shared_frame_for_all_crops','reference_human_reviewed']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows({k:r[k] for k in fields} for r in crop_rows)
    draw_comparisons(tasks, rows, args.labels.parent, views, args.output)
    page_tasks=[{**t,'image':'../手腕AI初标_20261016/'+t['image'],'comparison':[r for r in rows if (r['case'],r['source_frame_id'])==(t['case'],t['source_frame_id'])]} for t in tasks]
    page_data=json.dumps({'tasks':page_tasks,'rows':rows},ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    (args.output/'comparison.html').write_text(PAGE.replace('__DATA__',page_data),'utf8')
    write_json(args.output/'input-manifest.json',{'sha256':hashes,'source_images':views,'runtime_algorithm_modified':False,'initial_labels_modified':False})
    print(json.dumps({'overall':summary['overall'],'crops':crop_summary,'current_shared':summarize(current_shared),'shared_frames':len(shared_frames)},ensure_ascii=False))


if __name__=='__main__':
    main()
