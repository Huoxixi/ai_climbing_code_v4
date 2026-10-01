"""Build and serve a private, focused real-video review page (standard library only).

The server exposes an explicit file whitelist on loopback. It never enumerates
directories, loads application configuration, or reads the project's .local data.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def private_path(path: Path) -> Path:
    resolved = path.resolve()
    if any(part.casefold() == ".local" for part in resolved.parts):
        raise ValueError("The isolated sample preview must not access .local")
    return resolved


def number(value, fallback=None):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def read_json(path: Path) -> dict:
    value = json.loads(private_path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def build_page(output: Path, evidence: Path) -> Path:
    output, evidence = private_path(output), private_path(evidence)
    summary = read_json(output / "summary.json")
    storyboard = read_json(output / "storyboard.json")
    review = read_json(output / "review.json")
    media = summary.get("media") or {}
    analysis_duration = number(media.get("analysis_duration_seconds"))
    if analysis_duration is None:
        previous = read_json(evidence / "result.json")
        result = previous.get("result") if isinstance(previous.get("result"), dict) else previous
        visual = result.get("visual_replay") or {}
        analysis_duration = number(visual.get("analysis_duration_seconds"))
        if analysis_duration is None:
            analysis_duration = number((result.get("video") or {}).get("duration_seconds"))
    if analysis_duration is None or analysis_duration <= 0:
        raise ValueError("The real analysis duration is required for accurate chapter seeks")
    data = {"summary": summary, "storyboard": storyboard, "review": review,
            "analysisDuration": analysis_duration}
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    # JSON is data, not executable script; still escape HTML raw-text terminators.
    for raw, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                         ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        encoded = encoded.replace(raw, escaped)
    target = private_path(output / "index.html")
    target.write_text(PAGE.replace("__REVIEW_DATA__", encoded), encoding="utf-8")
    return target


PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>攀爬复盘 · 动作与停留</title>
<style>
:root{color-scheme:light;--paper:#f6f4ee;--ink:#183432;--muted:#5d6d68;--line:#d5ddd6;--teal:#07685f;--wash:#e5efea;--warn:#8a4c2b;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--paper)}
*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:auto;padding:36px 28px 72px}button,a,input{touch-action:manipulation}button{font:inherit}a{color:var(--teal);text-underline-offset:4px}button{cursor:pointer}button:disabled{cursor:default;opacity:.5}:focus-visible{outline:3px solid var(--teal);outline-offset:4px}::selection{color:#fff;background:var(--teal)}
h1{font-size:clamp(28px,4vw,42px);font-weight:650;letter-spacing:-.04em;line-height:1.22;margin:0 0 14px}h2{font-size:20px;line-height:1.4;margin:0 0 10px;font-weight:650}p{line-height:1.75;margin:0}.intro{max-width:48em;color:var(--muted);font-size:15px}.heading{margin-bottom:25px}.notice{margin:14px 0 0;font-size:13px;color:var(--muted)}
.viewer{border-top:1px solid var(--line);padding-top:16px}.switcher{display:flex;flex-wrap:wrap;gap:4px 18px;margin-bottom:14px}.switcher button{background:none;color:var(--muted);border:0;border-bottom:2px solid transparent;padding:10px 0;min-height:44px;font-size:14px}.switcher button[aria-pressed="true"]{color:var(--teal);border-bottom-color:var(--teal);font-weight:700}.screen{background:#102421;display:flex;justify-content:center;min-height:240px;overflow:hidden}video{display:block;width:100%;max-height:min(80vh,900px);object-fit:contain;background:#102421;aspect-ratio:720/880}.player-meta{display:flex;justify-content:space-between;gap:12px;margin:13px 0 9px}.player-meta strong{font-size:15px}.player-meta span{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}.player-copy{font-size:14px;color:var(--muted);max-width:70ch}.actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px 20px;margin:16px 0}.primary{border:1px solid var(--teal);background:var(--teal);color:white;padding:11px 17px;min-height:44px;border-radius:3px;font-weight:650;font-size:14px}.primary:hover{background:#07564f}.actions a{display:inline-flex;align-items:center;min-height:44px;font-size:14px}.status{min-height:22px;font-size:13px;color:var(--muted)}.status.error{color:var(--warn)}
.chapters{border-top:1px solid var(--line);padding-top:20px;margin-top:20px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px}.section-head p{font-size:13px;color:var(--muted)}.chapter-list{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-wrap:wrap;gap:9px}.chapter-list button{border:1px solid var(--line);background:transparent;border-radius:3px;text-align:left;min-height:48px;padding:10px 13px;font-size:14px;color:var(--ink)}.chapter-list button:hover{background:var(--wash);border-color:#86b8a9}.chapter-list small{margin-right:10px;color:var(--teal);font-variant-numeric:tabular-nums}
.analysis{border-top:1px solid var(--line);margin-top:30px;padding-top:25px}.metrics{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin:22px 0 28px}.metric dt{font-size:14px;color:var(--muted);margin-bottom:7px}.metric dd{margin:0;font-size:clamp(24px,4vw,32px);font-weight:600;font-variant-numeric:tabular-nums;line-height:1.35}.metric p{font-size:13px;color:var(--muted);margin-top:6px}.limbs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;border-top:1px solid var(--line);padding-top:18px}.limb strong{font-size:13px;font-weight:500;color:var(--muted)}.limb p{font-size:25px;font-weight:600;font-variant-numeric:tabular-nums}.limb p span{font-size:13px;font-weight:400;margin-left:5px;color:var(--muted)}.limb small{display:block;color:var(--muted);font-size:12px;margin-top:3px;line-height:1.6;overflow-wrap:anywhere}.evidence-note{font-size:13px;color:var(--muted);margin-top:18px;max-width:74ch}.changes{list-style:none;padding:0;margin:10px 0 18px}.changes li{padding:12px 0;border-bottom:1px solid var(--line);font-size:14px;line-height:1.7}.changes strong{font-weight:650}.changes p{font-size:13px;color:var(--muted);margin-top:4px;max-width:76ch}
details{border-top:1px solid var(--line);margin-top:28px;padding-top:18px}summary{cursor:pointer;min-height:44px;font-size:17px;font-weight:650;line-height:1.6}summary small{font-size:13px;font-weight:400;color:var(--muted);margin-left:12px}.detail-intro{color:var(--muted);font-size:13px;margin:5px 0 15px}.table-wrap{overflow-x:auto;width:100%;scrollbar-width:thin}table{border-collapse:collapse;width:100%;font-size:13px;min-width:480px;text-align:left}th,td{padding:13px 12px 13px 0;border-bottom:1px solid var(--line);vertical-align:top;line-height:1.65}th{font-weight:600;color:var(--muted)}td:first-child{min-width:112px}td:nth-child(2){white-space:nowrap;font-variant-numeric:tabular-nums}.phase-seek{border:0;background:transparent;color:var(--teal);padding:0;min-height:44px;text-align:left;font-size:13px;text-decoration:underline;text-underline-offset:4px}.phase-type{font-weight:650;display:block}.phase-note{color:var(--muted);font-size:12px;display:block;max-width:30em}.phase-limbs{display:grid;grid-template-columns:1fr 1fr;gap:2px 15px;min-width:180px}.phase-unknown td{color:var(--muted);background:#edece6}.phase-unknown .phase-type{color:var(--warn)}.documents{font-size:13px;display:flex;gap:20px;flex-wrap:wrap;margin-top:18px}.footer{border-top:1px solid var(--line);font-size:12px;color:var(--muted);padding-top:18px;margin-top:32px;line-height:1.7}.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(min-width:900px){.viewer{display:grid;grid-template-columns:minmax(0,760px) 1fr;gap:0 28px;align-items:start}.switcher,.screen{grid-column:1}.view-notes{grid-column:2;grid-row:2;position:sticky;top:24px}.player-meta{display:block;margin:0 0 12px}.player-meta span{display:block;margin-top:8px}.actions{align-items:stretch;flex-direction:column;gap:4px}.actions .primary{width:100%}.actions a{justify-content:center}.screen video{max-height:83vh}.viewer .status{margin-top:10px}}
@media(max-width:600px){main{padding:23px 17px 46px}.heading{margin-bottom:20px}.intro{font-size:14px}.switcher{gap:3px 16px}.switcher button{font-size:13px}.screen{margin:0 -17px}.screen video{max-height:76svh}.player-meta{align-items:baseline}.player-meta span{font-size:12px}.section-head{display:block}.section-head p{margin-top:2px}.chapter-list{gap:7px}.chapter-list button{font-size:13px;padding:9px 10px}.metrics{gap:18px}.limbs{grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 24px}.limb p{font-size:24px}summary small{display:block;margin:3px 0 8px}.table-wrap{margin-right:0}.documents{gap:12px 20px}.actions{gap:5px 15px}.actions .primary{flex:1}.actions a{font-size:13px}.chapter-list li{max-width:100%}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style></head>
<body><main>
<header class="heading"><h1>看清动作，也看清停留。</h1><p class="intro">从真实攀爬回到关键时刻。结尾用真人片段解释最长停留和关键换点，完整阶段记录放在下方，随时回看原片核对。</p><p class="notice">本页记录是 AI 对原视频的本地核查估计，尚未获得你的确认。本版待视觉验收；旧 v2.1 已被否决，保留为对照。</p></header>
<section class="viewer" aria-label="动态样片与原视频对照">
<div class="switcher" role="group" aria-label="选择观看版本"><button type="button" data-view="new" aria-pressed="true">新样片</button><button type="button" data-view="source" aria-pressed="false">原视频</button><button type="button" data-view="baseline" aria-pressed="false">基础复盘</button><button type="button" data-view="rejected" aria-pressed="false">旧 v2.1 · 已否决</button></div>
<div class="screen"><video id="player" controls playsinline preload="metadata" src="/enhanced.webm" aria-label="新的完整复盘样片"></video></div>
<div class="view-notes"><div class="player-meta"><strong id="view-title">新的完整复盘样片</strong><span id="view-duration"></span></div><p class="player-copy" id="view-copy">前半段保留旧版自动分析；新结尾采用另存的本地核查统计。因此正文与结尾的个别读数可能不同，修正原因见下方记录。</p><div class="actions"><button type="button" class="primary" id="jump-tail">看结尾重点复盘</button><a href="/enhanced.webm?download" download="攀爬重点复盘.webm">下载完整样片</a><a href="/tail.webm?download" download="攀爬重点复盘-结尾.webm">下载结尾片段</a></div><p class="status" id="player-status" role="status" aria-live="polite"></p></div>
</section>
<section class="chapters" aria-labelledby="chapters-title"><div class="section-head"><h2 id="chapters-title">结尾分镜</h2><p>选择一段，直接开始观看。</p></div><ol class="chapter-list" id="chapter-list"></ol></section>
<section class="analysis" aria-labelledby="analysis-title"><div class="section-head"><h2 id="analysis-title">这次攀爬的记录</h2><p>数值对应原视频时间。</p></div><dl class="metrics"><div class="metric"><dt id="timing-label">已观察时长</dt><dd id="timing-value">—</dd><p id="timing-note"></p></div><div class="metric"><dt>最长已确认停留</dt><dd id="longest-value">—</dd><p id="longest-note">四肢不换点，身体调整仍属于同一阶段。</p></div></dl><div class="limbs" id="limb-summary" aria-label="各肢体使用的不同岩点数量"></div><p class="evidence-note" id="evidence-note">各肢体按不同岩点去重计数，重复接触同一点不增加点数。这里的“已确认”仅指本次 AI 对原片的核查结果，时间为估计，尚未获得你的确认。停留不等于思考。</p></section>
<details id="review-details" open><summary>本次核查修正<small>AI 本地核查 · 待你确认</small></summary><p class="detail-intro">保留原自动记录，在这版样片中单独采用以下修正。</p><ul class="changes" id="review-changes"></ul><a href="/review.json" target="_blank" rel="noopener">查看完整核查记录</a></details>
<details id="phase-details"><summary>完整阶段记录<small id="phase-count"></small></summary><p class="detail-intro">时间为 AI 核查估计，显示到约 0.1 秒不代表逐帧准确。点按时间会切到原视频的阶段起点。离点与未确认分开记录，空缺不计为已确认的保持。</p><div class="table-wrap" tabindex="0" role="region" aria-label="阶段明细表，可横向滚动"><table><thead><tr><th scope="col">原片区间</th><th scope="col">时长</th><th scope="col">阶段 / 状态</th><th scope="col">四肢触点</th></tr></thead><tbody id="phase-rows"></tbody></table></div><div class="documents"><a href="/summary.json" target="_blank" rel="noopener">查看本地统计依据</a><a href="/storyboard.json" target="_blank" rel="noopener">查看分镜记录</a></div></details>
<footer class="footer">仅用于本地样片核对。真实视频和分析证据未上传；工程检查与数值一致性不代表视觉验收通过。</footer>
</main><script type="application/json" id="review-data">__REVIEW_DATA__</script><script>
(()=>{'use strict';
const data=JSON.parse(document.getElementById('review-data').textContent), summary=data.summary, storyboard=data.storyboard, review=data.review;
const analysisDuration=data.analysisDuration, player=document.getElementById('player'), status=document.getElementById('player-status');
const limbs={left_hand:'左手',right_hand:'右手',left_foot:'左脚',right_foot:'右脚'};
const number=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))?Number(value):null;
const seconds=value=>{const n=number(value);return n===null?'未确认':n.toFixed(1)+' 秒'};
const approxSeconds=value=>{const n=number(value);if(n===null)return '未确认';return n>0&&n<.1?'不到0.1秒':'约 '+seconds(n)};
const clock=value=>{const n=number(value);if(n===null)return '—';const rounded=Math.round(n*10)/10;return Math.floor(rounded/60)+':'+(rounded%60).toFixed(1).padStart(4,'0')};
const approxInterval=(start,end)=>{const left=clock(start),right=clock(end);return '约 '+left+(left===right?'':'–'+right)};
const elem=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node};
const humanStatus=value=>({verified:'AI 核查估计',reviewed:'AI 核查估计',user_confirmed:'用户确认',manual_verified:'AI 核查估计',observed:'已观察',reliable:'可靠记录',confirmed:'AI 核查估计',automatic:'自动记录',estimated:'估计',needs_review:'待复核',review_required:'待复核',unknown:'观测空缺',unconfirmed:'未确认',partial:'部分可见',unverified:'待复核'}[value]||'见记录说明');
const views={new:{url:'/enhanced.webm',title:'新的完整复盘样片',copy:'前半段保留旧版自动分析；新结尾采用另存的本地核查统计。因此正文与结尾的个别读数可能不同，修正原因见下方记录。'},source:{url:'/source.mp4',title:'原视频 · 核对真实动作',copy:'这里播放原视频。阶段表中的时间均定位到这份原片，不会把结尾动画当作原始证据。'},baseline:{url:'/baseline.webm',title:'基础复盘 · 同一次分析',copy:'保留原有自动分析画面和读数。新结尾对左脚等记录的修正单独保存，见下方核查修正。'},rejected:{url:'/rejected-v21.webm',title:'旧 v2.1 · 已否决',copy:'这一版没有通过用户的视觉验收。保留它只为比较旧版节奏和表达问题。'}};
let currentView='new', seekRequest=0;
function announce(text,error=false){status.textContent=text;status.classList.toggle('error',error)}
function updateMeta(){document.getElementById('view-duration').textContent=Number.isFinite(player.duration)?'片长 '+seconds(player.duration):''}
function showView(key,time=null,autoplay=false){
const request=++seekRequest,view=views[key];if(!view)return;
const changed=currentView!==key;currentView=key;
document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.view===key)));
document.getElementById('view-title').textContent=view.title;document.getElementById('view-copy').textContent=view.copy;player.setAttribute('aria-label',view.title);announce('');
const seek=()=>{if(request!==seekRequest)return;if(time!==null&&Number.isFinite(player.duration)){player.currentTime=Math.max(0,Math.min(time,Math.max(0,player.duration-.04)));announce((key==='source'?'已定位原片 ':'已定位样片 ')+clock(time));}updateMeta();if(autoplay)player.play().catch(()=>announce('已定位。请按播放继续观看。'))};
if(changed){player.pause();player.src=view.url;document.getElementById('view-duration').textContent='';player.addEventListener('loadedmetadata',seek,{once:true});player.load()}else if(player.readyState>=1){seek()}else{player.addEventListener('loadedmetadata',seek,{once:true})}
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{const time=player.currentTime<analysisDuration?player.currentTime:0;showView(button.dataset.view,time,false)}));
document.getElementById('jump-tail').addEventListener('click',()=>{showView('new',analysisDuration,true);player.focus()});
player.addEventListener('loadedmetadata',updateMeta);player.addEventListener('error',()=>announce('当前视频暂时无法播放，请确认本地样片已生成，再刷新页面。',true));
const shots=Array.isArray(storyboard.shots)?storyboard.shots:[];
shots.forEach((shot,index)=>{const offset=number(shot.start_seconds);if(offset===null)return;const li=elem('li'),button=elem('button');button.type='button';button.append(elem('small',String(index+1).padStart(2,'0')),document.createTextNode(shot.title||'重点片段'));button.setAttribute('aria-label','观看'+(shot.title||'重点片段')+'，样片 '+clock(analysisDuration+offset));button.addEventListener('click',()=>{showView('new',analysisDuration+offset,true);player.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});player.focus({preventScroll:true})});li.append(button);document.getElementById('chapter-list').append(li)});
if(!shots.length)document.getElementById('chapter-list').append(elem('li','分镜时间尚未记录。'));
const timing=summary.timing||{},complete=['completed','complete','topped_out','finished','完成'].includes(timing.outcome);
document.getElementById('timing-label').textContent=complete?'总攀爬用时':'已观察时长';document.getElementById('timing-value').textContent=approxSeconds(timing.elapsed_seconds);
const outcomes={completed:'已完攀',complete:'已完攀',topped_out:'已完攀',finished:'已完攀',incomplete:'未完攀',not_completed:'未完攀',truncated:'片段截断',partial:'片段截断',unknown:'完成状态待确认'};
document.getElementById('timing-note').textContent=(outcomes[timing.outcome]||'完成状态待确认')+' · 约 '+clock(timing.start_seconds)+'–'+clock(timing.end_seconds)+' · '+humanStatus(timing.status||timing.source);
const phases=Array.isArray(summary.phases)?summary.phases:[],longest=typeof summary.longest_hold==='object'&&summary.longest_hold!==null?summary.longest_hold:phases.find(p=>p.id===summary.longest_hold);
document.getElementById('longest-value').textContent=longest?approxSeconds(longest.duration_seconds):'未确认';if(longest)document.getElementById('longest-note').textContent='约 '+clock(longest.start_seconds)+'–'+clock(longest.end_seconds)+' · 四肢未换点';
Object.entries(limbs).forEach(([key,label])=>{const value=(summary.limbs||{})[key]||{},node=elem('div',undefined,'limb'),count=number(value.count);node.append(elem('strong',label));const p=elem('p',count===null?'—':String(count));p.append(elem('span','个不同岩点'));node.append(p,elem('small',Array.isArray(value.hold_ids)&&value.hold_ids.length?'岩点 '+value.hold_ids.join('、'):count===0?'未记录到可靠用点':'用点记录不足'));document.getElementById('limb-summary').append(node)});
const unknownCount=phases.filter(p=>p.kind==='unknown').length;
document.getElementById('phase-count').textContent=phases.length+' 段'+(unknownCount?' · '+unknownCount+' 段观测空缺':'');
function contactLabel(value){if(value===null)return '离点（已核查）';if(value===undefined||value==='unknown')return '未确认';if(value==='free'||value==='off')return '离点（已核查）';if(typeof value==='object'){if(value.hold_id===null)return '离点（已核查）';if(value.hold_id==='unknown'||value.hold_id===undefined)return '未确认';return '岩点 '+value.hold_id}return '岩点 '+value}
const changeLabels={'left_foot.unique_holds':'左脚不同岩点数','left_hand.hold_7':'左手 · 7 号点','timing':'总攀爬计时'};
const changes=Array.isArray(review.changes)?review.changes:[];
changes.forEach(change=>{const row=elem('li'),label=changeLabels[change.field]||'接触记录修正';let title=label;if(Array.isArray(change.automatic)&&Array.isArray(change.reviewed))title+='：'+new Set(change.automatic).size+' → '+new Set(change.reviewed).size+' 个';row.append(elem('strong',title),elem('p',change.reason||'请结合原视频核对。'));document.getElementById('review-changes').append(row)});
if(!changes.length)document.getElementById('review-changes').append(elem('li','未单独记录修正项，请查看完整核查记录。'));
const noteNames={missing_measured_limb_evidence:'采样证据不足',conflicting_or_unknown_contact:'接触记录有冲突或缺失',change_to_different_hold:'换至不同岩点',same_hold_regrip_merged:'同点调整合并记录',contact_state_unobserved:'接触状态未看清',unreviewed_phase_gap:'阶段尚未核查'};
const phaseNote=value=>{const text=String(value),position=text.indexOf(':'),prefix=position>=0?text.slice(0,position):'',body=position>=0?text.slice(position+1):text;return (limbs[prefix]?limbs[prefix]+'：':'')+(noteNames[body]||body)};
phases.forEach(phase=>{const row=elem('tr',undefined,phase.kind==='unknown'?'phase-unknown':''),timeCell=elem('td'),time=number(phase.start_seconds),button=elem('button',approxInterval(phase.start_seconds,phase.end_seconds),'phase-seek');button.type='button';button.disabled=time===null;button.setAttribute('aria-label','在原片查看约 '+clock(phase.start_seconds)+' 开始的阶段');button.addEventListener('click',()=>{showView('source',time,true);player.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});player.focus({preventScroll:true})});timeCell.append(button);const type=elem('td');type.append(elem('span',({hold:'姿态保持',transition:'换点过程',unknown:'观测空缺'}[phase.kind]||'待核对阶段'),'phase-type'));type.append(elem('span',phase.kind==='unknown'?'不计入已确认保持':humanStatus(phase.status),'phase-note'));const notes=Array.isArray(phase.notes)?phase.notes.map(phaseNote).join('；'):typeof phase.notes==='string'?phaseNote(phase.notes):'';if(notes)type.append(elem('span',notes,'phase-note'));const contactCell=elem('td'),contactGrid=elem('div',undefined,'phase-limbs');Object.entries(limbs).forEach(([key,label])=>contactGrid.append(elem('span',label+' · '+contactLabel((phase.contacts||{})[key]))));contactCell.append(contactGrid);row.append(timeCell,elem('td',approxSeconds(phase.duration_seconds)),type,contactCell);document.getElementById('phase-rows').append(row)});
if(!phases.length){const row=elem('tr'),cell=elem('td','暂无阶段记录。');cell.colSpan=4;row.append(cell);document.getElementById('phase-rows').append(row)}
})();
</script></body></html>'''


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Accept one RFC byte range, including open-ended and suffix ranges."""
    if header is None:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError("Unsupported or unsatisfiable byte range")
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("Unsatisfiable suffix range")
        return max(0, size - suffix), size - 1
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, end


def create_server(output: Path, evidence: Path, port: int = 4182) -> ThreadingHTTPServer:
    output, evidence = private_path(output), private_path(evidence)
    files = {
        "/": output / "index.html", "/index.html": output / "index.html",
        "/summary.json": output / "summary.json", "/storyboard.json": output / "storyboard.json",
        "/review.json": output / "review.json",
        "/enhanced.webm": output / "enhanced.webm", "/tail.webm": output / "tail.webm",
        "/enhanced.mp4": output / "enhanced.mp4",
        "/baseline.webm": evidence / "baseline.webm", "/rejected-v21.webm": evidence / "enhanced.webm",
        "/source.mp4": evidence / "input.mp4",
    }
    files = {url: private_path(path) for url, path in files.items()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_HEAD(self):
            self._file_response(head=True)

        def do_GET(self):
            self._file_response(head=False)

        def _file_response(self, *, head: bool):
            url = urlsplit(self.path)
            path = files.get(url.path)
            if path is None or not path.is_file():
                self.send_error(404, "File not found")
                return
            try:
                with path.open("rb") as stream:
                    size = path.stat().st_size
                    try:
                        selected = parse_range(self.headers.get("Range"), size)
                    except ValueError:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                    start, end = selected if selected is not None else (0, size - 1)
                    self.send_response(206 if selected is not None else 200)
                    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    if media_type.startswith("text/") or media_type == "application/json":
                        media_type += "; charset=utf-8"
                    self.send_header("Content-Type", media_type)
                    self.send_header("Content-Length", str(max(0, end - start + 1)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Referrer-Policy", "no-referrer")
                    if selected is not None:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    if url.query == "download":
                        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                    self.end_headers()
                    if head:
                        return
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = stream.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except FileNotFoundError:
                self.send_error(404, "File not found")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New sample directory")
    parser.add_argument("--evidence", required=True, type=Path, help="Existing real-video evidence directory")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=4182)
    args = parser.parse_args()
    page = build_page(args.output, args.evidence)
    print(f"Preview page: {page}", flush=True)
    if args.serve:
        server = create_server(args.output, args.evidence, args.port)
        print(f"Local focused review: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
