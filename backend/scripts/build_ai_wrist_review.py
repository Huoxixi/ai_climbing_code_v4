"""Build local visual review artifacts for explicitly authored AI wrist drafts."""
import argparse
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HTML = runpy.run_path(str(Path(__file__).with_name('build_climbing_reference_review.py')))['HTML']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', type=Path, required=True)
    parser.add_argument('--views', type=Path, required=True)
    args = parser.parse_args()
    private = Path(__file__).resolve().parents[2] / '.tmp'
    if not all(p.resolve().is_relative_to(private.resolve()) for p in (args.tasks, args.views)):
        raise ValueError('Private local draft paths required')
    data = json.loads(args.tasks.read_text('utf8'))
    manifest = json.loads((args.views / 'visual-input-manifest.json').read_text('utf8'))
    references = {(row['case'], row['frame']): row for row in manifest}
    tasks = data['tasks']
    status_counts = Counter(t['joints'][s+'_wrist']['visibility'] for t in tasks for s in ('left', 'right'))
    if data['definition']['reference_status'] != 'AI_initial_wrist_only_not_independent_truth':
        raise ValueError('AI draft metadata required')
    dest = args.tasks.parent
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 17)
    palette = {'left': '#39ddff', 'right': '#ef80f9'}
    for case in sorted({t['case'] for t in tasks}):
        group = [t for t in tasks if t['case'] == case]
        for start in range(0, len(group), 4):
            chosen = group[start:start + 4]
            box = references[(case, chosen[0]['source_frame_id'])]['crop_xyxy']
            panel_h = max(560, 90 + 2 * (box[3] - box[1]))
            board = Image.new('RGB', (1240, panel_h * 2), '#11171c')
            for i, task in enumerate(chosen):
                ref = references[(case, task['source_frame_id'])]
                path = dest / task['image']
                if hashlib.sha256(path.read_bytes()).hexdigest() != ref['image_sha256']:
                    raise ValueError('Image differs from visually inspected source')
                raw = Image.open(path).convert('RGB')
                panel = Image.new('RGB', (620, panel_h), '#11171c')
                panel.paste(raw.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.Resampling.NEAREST), (50, 65))
                draw = ImageDraw.Draw(panel)
                draw.text((8, 5), f'{case} / frame {task["source_frame_id"]} / AI INITIAL - UNREVIEWED', font=font, fill='white')
                statuses = []
                for side in ('left', 'right'):
                    label = task['joints'][side + '_wrist']
                    statuses.append(f'{side[0].upper()}: {label["visibility"]}')
                    if label['xy_px'] is None:
                        continue
                    x, y = label['xy_px']
                    cx, cy = 50 + (x - box[0]) * 2, 65 + (y - box[1]) * 2
                    r = label['visual_radius_px'] * 2
                    color = palette[side]
                    draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=color, width=2)
                    draw.line((cx-5, cy, cx+5, cy), fill=color, width=2)
                    draw.line((cx, cy-5, cx, cy+5), fill=color, width=2)
                    draw.text((cx+9, cy+8), f'{side[0].upper()} {x},{y}', font=font, fill=color)
                hand = task['hand_regions']['right'].get('visible_hand_box_xyxy_px')
                if hand:
                    x1, y1, x2, y2 = hand
                    rect = (50+(x1-box[0])*2, 65+(y1-box[1])*2, 50+(x2-box[0])*2, 65+(y2-box[1])*2)
                    draw.rectangle(rect, outline='#ffbb55', width=2)
                    draw.text((rect[0]-80, rect[1]-22), 'R HAND ONLY', font=font, fill='#ffbb55')
                draw.text((8, 30), ' | '.join(statuses), font=font, fill='#c5d2d8')
                board.paste(panel, ((i % 2) * 620, (i // 2) * panel_h))
            board.save(dest / f'overlay-{case}-{start//4+1}.png')

    html = HTML.replace('骨架原帧参考标注', '手腕AI初标核对').replace('原帧参考标注 · 无模型预填', '手腕AI初标 · 待复核')
    html = html.replace('<button onclick="download()">', '<button id="toggle" onclick="showLabels=!showLabels;render()">显示／隐藏标注</button><button onclick="download()">')
    summary = f'<p><b>{len(tasks)}帧／{len(tasks)*2}条双腕状态</b><br>{status_counts["visible"]}个可定位点，{status_counts["occluded"]}处遮挡，{status_counts["unobservable"]}处无法定位。<br>全部为AI初标，尚无人审。</p><p id="info"></p>'
    html = html.replace('<p id="info"></p>', summary)
    html = html.replace('人体身份和手部区域等完整字段保留在 JSON 中，尚需复核。', '彩色圆圈表示目测定位半径，并非统计置信区间；橙框仅表示可见手部片段，腕点仍可为空。这里只补双腕，其余身体关节未标。')
    html = html.replace('页面不联网、不改原片、不把单人标注自动认作独立复核。', '页面离线使用。修改和导出仍是待复核草稿，不能自动提升为人工真值、训练标签或精度成绩。原始空白任务另行保留。')
    html = html.replace("let ready=false;", "let ready=false,showLabels=true;")
    html = html.replace("if(!p.xy_px)continue;", "if(!showLabels||!p.xy_px)continue;")
    html = html.replace("ctx.arc(p.xy_px[0],p.xy_px[1],7,0,7)", "ctx.arc(p.xy_px[0],p.xy_px[1],p.visual_radius_px||7,0,7)")
    html = html.replace("let p=t.joints[selected];", "if(showLabels){let h=t.hand_regions.right.visible_hand_box_xyxy_px;if(h){ctx.strokeStyle='#ffbb55';ctx.setLineDash([6,4]);ctx.strokeRect(h[0],h[1],h[2]-h[0],h[3]-h[1]);ctx.setLineDash([])}}let p=t.joints[selected];")
    html = html.replace("p.visibility||'待标注');", "p.visibility||'待标注')+' · AI初标待复核'+(p.visual_radius_px?' · 目测半径 '+p.visual_radius_px+' 像素':'');")
    old = "t.joints[j]={xy_px:[(e.clientX-box.left)*c.width/box.width,(e.clientY-box.top)*c.height/box.height],visibility:'visible'};"
    new = "t.joints[j]={...t.joints[j],xy_px:[(e.clientX-box.left)*c.width/box.width,(e.clientY-box.top)*c.height/box.height],visibility:'visible',visual_radius_px:null,localization_status:'editor_modified_requires_review',label_source:'local_editor_modified_draft',human_reviewed:false,independent_evaluation_eligible:false};"
    html = html.replace(old, new)
    html = html.replace("tasks[index].joints[byId('joint').value]={xy_px:null,visibility:v};", "let t=tasks[index],j=byId('joint').value;t.joints[j]={...t.joints[j],xy_px:null,visibility:v,visual_radius_px:null,localization_status:'editor_modified_requires_review',label_source:'local_editor_modified_draft',human_reviewed:false,independent_evaluation_eligible:false};")
    html = html.replace("'draft_requires_review'", "'ai_initial_wrist_only_requires_review'")
    html = html.replace("a.download='climbing-original-reference-draft.json'", "a.download='climbing-ai-wrist-draft-requires-review.json'")
    html = html.replace("menu();go(index);\n</script>", "menu();byId('joint').value='right_wrist';go(index);\n</script>")
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    (dest / 'review.html').write_text(html.replace('__TASK_DATA__', payload), 'utf8')
    print(json.dumps({'frames': len(tasks), 'overlays': len(list(dest.glob('overlay-*.png'))), 'editor': str(dest / 'review.html')}))


if __name__ == '__main__':
    main()
