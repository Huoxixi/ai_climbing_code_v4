"""Build a self-contained local reference editor without model pseudo-labels."""
import argparse,json
from pathlib import Path

HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>骨架原帧参考标注</title>
<style>body{margin:0;background:#101820;color:#e9f1f3;font:16px system-ui}header{padding:14px 20px;background:#1b2934;display:flex;gap:12px;align-items:center;flex-wrap:wrap}button,select,input{font:inherit;padding:7px;border-radius:5px}main{display:grid;grid-template-columns:300px 1fr;height:calc(100vh - 100px)}aside{padding:15px;overflow:auto}#view{overflow:auto}canvas{background:#25333d;cursor:crosshair}p{line-height:1.6}.note{color:#b6c6ce}#status{color:#66dfbd}button{cursor:pointer}label{display:block;margin:12px 0}</style>
<header><b>原帧参考标注 · 无模型预填</b><button onclick="move(-1)">上一帧</button><select id="frame" onchange="go(+this.value)"></select><button onclick="move(1)">下一帧</button><button onclick="zoom(.25)">放大</button><button onclick="zoom(-.25)">缩小</button><button onclick="download()">导出标注 JSON</button></header>
<main><aside><p id="info"></p><label>标注人<input id="reviewer" placeholder="填写姓名或代号" oninput="saveReviewer()"></label><label>关节<select id="joint" onchange="render()"></select></label><button onclick="missing('occluded')">被遮挡</button> <button onclick="missing('unobservable')">无法判断</button><p id="status"></p><p class="note">左右指人物自身的解剖学左右。点选腕关节，不能用指尖、岩点或手框中心替代。隐藏位置不要猜。</p><p class="note">点击图像记录位置；选择遮挡或无法判断会清除该关节点。放大后仍按原片像素保存。人体身份和手部区域等完整字段保留在 JSON 中，尚需复核。</p><p class="note">关闭前请导出。可导入已保存 JSON 继续；页面不联网、不改原片、不把单人标注自动认作独立复核。</p><input type="file" accept="application/json" onchange="restore(this.files[0])"></aside><div id="view"><canvas id="canvas"></canvas></div></main>
<script>const data=__TASK_DATA__;let tasks=data.tasks,index=tasks.findIndex(t=>t.case==='09'&&t.source_frame_id===258),scale=.7; if(index<0)index=0;
const byId=id=>document.getElementById(id),c=byId('canvas'),ctx=c.getContext('2d'),img=new Image();let ready=false;
const labels={left_shoulder:'左肩',right_shoulder:'右肩',left_elbow:'左肘',right_elbow:'右肘',left_wrist:'左腕',right_wrist:'右腕',left_hip:'左髋',right_hip:'右髋',left_knee:'左膝',right_knee:'右膝',left_ankle:'左踝',right_ankle:'右踝'};
const order=['left_wrist','right_wrist','left_ankle','right_ankle','left_shoulder','right_shoulder','left_hip','right_hip','left_elbow','right_elbow','left_knee','right_knee'];
for(const j of order){const o=document.createElement('option');o.value=j;o.textContent=labels[j];byId('joint').append(o)}
function menu(){byId('frame').replaceChildren();tasks.forEach((t,i)=>{let o=document.createElement('option');o.value=i;o.textContent=t.case+' / 帧 '+t.source_frame_id;byId('frame').append(o)})}
function go(i){index=Math.max(0,Math.min(tasks.length-1,i));byId('frame').value=index;let t=tasks[index];byId('reviewer').value=t.reviewer||'';byId('info').textContent=`${index+1}/${tasks.length} · ${t.case} · ${t.time_seconds.toFixed(2)}秒 · 原帧${t.source_frame_id}`;ready=false;img.src=t.image;}
img.onload=()=>{ready=true;c.width=img.width;c.height=img.height;c.style.width=img.width*scale+'px';render()};
function render(){if(!ready)return;ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(img,0,0);let t=tasks[index],selected=byId('joint').value;for(let [j,p]of Object.entries(t.joints)){if(!p.xy_px)continue;ctx.strokeStyle=j===selected?'#ffcc33':j.startsWith('left')?'#39ddff':'#ef80f9';ctx.lineWidth=3;ctx.beginPath();ctx.arc(p.xy_px[0],p.xy_px[1],7,0,7);ctx.stroke();ctx.font='18px sans-serif';ctx.fillStyle=ctx.strokeStyle;ctx.fillText(labels[j]||j,p.xy_px[0]+10,p.xy_px[1]-5)}let p=t.joints[selected];byId('status').textContent=(labels[selected]||selected)+'：'+(p.xy_px?p.xy_px.map(x=>x.toFixed(1)).join(', '):p.visibility||'待标注');}
c.onclick=e=>{let box=c.getBoundingClientRect(),t=tasks[index],j=byId('joint').value;t.joints[j]={xy_px:[(e.clientX-box.left)*c.width/box.width,(e.clientY-box.top)*c.height/box.height],visibility:'visible'};t.annotation_status='draft_requires_review';saveReviewer();render()};
function missing(v){tasks[index].joints[byId('joint').value]={xy_px:null,visibility:v};tasks[index].annotation_status='draft_requires_review';saveReviewer();render()}
function saveReviewer(){tasks[index].reviewer=byId('reviewer').value||null}function move(d){go(index+d)}function zoom(d){scale=Math.max(.3,Math.min(3,scale+d));c.style.width=c.width*scale+'px'}
function download(){data.tasks=tasks;let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='climbing-original-reference-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function restore(f){if(!f)return;let x=JSON.parse(await f.text());if(x.definition.version!==data.definition.version||x.tasks.length!==tasks.length)throw Error('参考集版本不匹配');for(let i=0;i<tasks.length;i++)if(x.tasks[i].source_sha256!==tasks[i].source_sha256||x.tasks[i].source_frame_id!==tasks[i].source_frame_id)throw Error('原片或帧号不匹配');tasks=x.tasks;menu();go(index)}menu();go(index);
</script></html>'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tasks',type=Path,required=True);args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    if not args.tasks.resolve().is_relative_to(project/'.tmp'):raise ValueError('Private local references required')
    data=json.loads(args.tasks.read_text('utf8'))
    # Escape script delimiters even though controlled task definitions contain no HTML.
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
    (args.tasks.parent/'review.html').write_text(HTML.replace('__TASK_DATA__',payload),'utf8')
    print(json.dumps({'frames':len(data['tasks']),'editor':str(args.tasks.parent/'review.html'),'labels_prefilled':0}),flush=True)


if __name__=='__main__':main()
