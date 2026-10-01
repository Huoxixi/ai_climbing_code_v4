"""Build a local acceptance page from real analysis output, without inference.

Only the three explicitly selected videos and the generated page are served.
The original is read in place and never copied into the documentation folder.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


LIMBS = {"left_hand": "左手", "right_hand": "右手", "left_foot": "左脚", "right_foot": "右脚"}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def seconds(value):
    return "记录未提供" if value is None else f"{value:.2f}".rstrip("0").rstrip(".") + " 秒"


def build_page(result_path: Path, output: Path, *, source_duration=None,
               enhanced_url="enhanced.webm", basic_url="basic.webm", source_url="source-video"):
    raw = json.loads(result_path.read_text(encoding="utf-8"))
    result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    video = result.get("video") or raw.get("video") or {}
    route_color = (result.get("route") or {}).get("color") or raw.get("route_color")
    route_title = f"{route_color}线路 · 真实攀爬复盘" if isinstance(route_color, str) and route_color else "这次真实攀爬的完整复盘"
    visual = result.get("visual_replay") or {}
    if visual.get("status") != "ready":
        raise ValueError("完整增强视频尚未就绪，不能把待生成结果展示为完成")
    analysis = finite(visual.get("analysis_duration_seconds"))
    tail = finite(visual.get("tail_start_seconds", visual.get("start_seconds")))
    total = finite(visual.get("total_duration_seconds"))
    if analysis is None or tail is None or total is None or not 0 < analysis <= tail < total:
        raise ValueError("需要真实的分析区间、尾段起点及成片时长")
    contacts = (result.get("attempt") or {}).get("contacts") or []
    counts = {limb: sum(isinstance(event, dict) and event.get("limb") == limb for event in contacts) for limb in LIMBS}
    missing = [name for limb, name in LIMBS.items() if not counts[limb]]
    foot_note = ("本次没有识别到脚部接触；回放仅展示已有记录，没有补造脚部用点。"
                 if not counts["left_foot"] and not counts["right_foot"] else
                 f"本次未识别到{'、'.join(missing)}接触；对应部分不补画。" if missing else
                 "本次分析记录包含左右手、左右脚接触。请结合原视频核对漏检、误检和接触顺序。")
    summary = {"evidence_kind": "real_video_analysis", "route_color": route_color, "analysis_duration_seconds": analysis,
               "tail_start_seconds": tail, "total_duration_seconds": total,
               "tail_duration_seconds": total - tail, "source_duration_seconds": finite(source_duration),
               "contact_counts": counts, "contact_count_basis": "result.attempt.contacts",
               "missing_limbs": missing, "visual_version": visual.get("visual_version"),
               "analysis_video": {key: video.get(key) for key in ("width", "height", "fps", "frame_count")}}
    rows = "".join(f"<tr><th scope='row'>{name}</th><td>{counts[limb]} 次</td></tr>" for limb, name in LIMBS.items())
    original_duration = seconds(finite(source_duration)) if source_duration is not None else "以原视频播放器显示为准"
    page = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>真实视频复盘 · 成片验收</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;color:#f4f5ef;background:#111611}
*{box-sizing:border-box}body{margin:0}main{max-width:1400px;margin:auto;padding:32px 24px 56px}
h1{font-size:clamp(25px,3vw,36px);line-height:1.25;margin:0 0 12px}h2{font-size:19px;margin:0 0 10px}
p{font-size:15px;line-height:1.75;color:#c3cdc2;max-width:76ch;margin:0 0 16px}a{color:#f3d657;text-underline-offset:4px}
.viewers{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(260px,1fr);gap:26px;margin-top:26px;align-items:start}
video{display:block;width:100%;max-height:76vh;object-fit:contain;background:#080c08;border-radius:10px}
.secondary video{max-height:32vh}.secondary article+article{margin-top:24px}.actions{display:flex;flex-wrap:wrap;gap:10px 14px;margin:12px 0}
.actions a,.actions button{display:inline-flex;align-items:center;min-height:44px;padding:9px 14px;border:1px solid #66705f;border-radius:8px;background:#1b221b;color:#f4f5ef;font:inherit;font-size:14px;text-decoration:none;cursor:pointer}
.actions button{background:#f0cf43;color:#252408;border-color:#f0cf43;font-weight:650}.actions a:hover{background:#283327}
:focus-visible{outline:3px solid #f0cf43;outline-offset:3px}::selection{background:#e0c441;color:#182015}
.evidence{margin-top:32px;padding-top:24px;border-top:1px solid #46513e;display:grid;grid-template-columns:1fr 1fr;gap:24px}
table{width:100%;border-collapse:collapse;font-size:15px;max-width:430px}th,td{text-align:left;padding:9px 0;border-bottom:1px solid #394435}td{text-align:right;font-variant-numeric:tabular-nums}
.time{font-variant-numeric:tabular-nums}.note{font-size:13px;color:#b8c1b3;margin-top:10px}
@media(max-width:760px){main{padding:22px 16px 40px}.viewers,.evidence{grid-template-columns:1fr}.viewers{gap:24px}.secondary{display:grid;grid-template-columns:1fr 1fr;gap:14px}.secondary article+article{margin-top:0}.secondary video{max-height:42vh}video{max-height:68vh}.secondary h2{font-size:17px}}
@media(max-width:420px){.secondary{grid-template-columns:1fr}.secondary article+article{margin-top:12px}.actions a,.actions button{flex-grow:1;justify-content:center}}
</style></head><body><main>
<h1>__ROUTE_TITLE__</h1>
<p>从原视频的分析画面看到最后的线路回放。基础版和增强版使用同一次分析记录；新增尾段只负责展示，不作为动作或教练分析的证据。</p>
<div class="viewers"><article><h2>完整增强视频</h2><video id="enhanced" controls playsinline preload="metadata" src="__ENHANCED_URL__"></video>
<div class="actions"><button type="button" id="jump-tail">查看结尾线路回放</button><a href="__ENHANCED_URL__?download" download="真实视频-完整增强复盘.webm">下载完整增强视频</a></div>
<p class="time">真实分析 __ANALYSIS__ · 线路回放 __TAIL__ · 成片共 __TOTAL__</p></article>
<div class="secondary"><article><h2>同一次分析的基础版</h2><video controls playsinline preload="metadata" src="__BASIC_URL__"></video><p class="note">真实视频叠加岩点与动作信息，没有新增结尾。</p></article>
<article><h2>原视频</h2><video controls playsinline preload="metadata" src="__SOURCE_URL__"></video><p class="note">原视频时长：__SOURCE_DURATION__。仅用于本地验收，未复制到文档目录。</p></article></div></div>
<section class="evidence" aria-label="本次记录与验收范围"><div><h2>本次识别到的接触记录</h2><table><thead><tr><th scope="col">手脚</th><th scope="col" style="text-align:right">事件数</th></tr></thead><tbody>__ROWS__</tbody></table>
<p class="note">计数直接来自本次 result.attempt.contacts，属于自动分析记录，仍需人工结合视频核对。</p></div>
<div><h2>请结合原画面核对</h2><p>__FOOT_NOTE__</p><p>尾段的手脚标签表示各肢体<strong>最近一次用点记录</strong>，不代表结束时四肢同时处于这些位置。参考画面保留了局部人物遮挡；受遮挡的岩点仅用中性轮廓定位，看不见的墙面和岩点纹理没有补画。</p><p>重点看岩点是否随真实墙面保持对齐、手脚标记是否对应本次接触、结尾是否完整，以及基础分析画面与新尾段衔接是否自然。</p><a href="acceptance-summary.json">查看本次成片与接触摘要</a></div></section>
</main><script>
const mainVideo=document.getElementById('enhanced');
document.getElementById('jump-tail').addEventListener('click',()=>{mainVideo.currentTime=__START__;mainVideo.play().catch(()=>{});mainVideo.focus()});
document.querySelectorAll('video').forEach(video=>video.addEventListener('play',()=>document.querySelectorAll('video').forEach(other=>{if(other!==video)other.pause()})));
</script></body></html>"""
    values = {"ANALYSIS": seconds(analysis), "TAIL": seconds(total - tail), "TOTAL": seconds(total),
              "SOURCE_DURATION": original_duration, "ROWS": rows, "FOOT_NOTE": foot_note, "START": str(tail),
              "ENHANCED_URL": enhanced_url, "BASIC_URL": basic_url, "SOURCE_URL": source_url,
              "ROUTE_TITLE": route_title}
    for key, value in values.items():
        page = page.replace(f"__{key}__", value if key in {"ROWS", "START"} else html.escape(value))
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def serve(output: Path, enhanced: Path, basic: Path, source: Path, port: int):
    files = {"/": output / "index.html", "/index.html": output / "index.html",
             "/acceptance-summary.json": output / "acceptance-summary.json",
             "/enhanced.webm": enhanced, "/basic.webm": basic, "/source-video": source}
    files.update({f"/{path.name}": path for path in (enhanced, basic, source)})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            path = files.get(url.path)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            requested = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            start = int(requested[1]) if requested else 0
            end = min(int(requested[2]), size - 1) if requested and requested[2] else size - 1
            if start > end or start >= size:
                self.send_error(416)
                return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if url.query == "download":
                self.send_header("Content-Disposition", f'attachment; filename="{url.path.rsplit("/", 1)[-1]}"')
            self.end_headers()
            try:
                with path.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = stream.read(min(1024 * 256, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    print(f"Local real-video review: http://127.0.0.1:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--enhanced", type=Path)
    parser.add_argument("--basic", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--source-duration", type=float)
    parser.add_argument("--enhanced-url", default="enhanced.webm")
    parser.add_argument("--basic-url", default="basic.webm")
    parser.add_argument("--source-url", default="source-video")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=4192)
    args = parser.parse_args()
    selected = [args.result, args.output, args.enhanced, args.basic, args.source]
    if any(path and ".local" in path.resolve().parts for path in selected):
        raise ValueError("This isolated acceptance page must not access .local")
    build_page(args.result, args.output, source_duration=args.source_duration,
               enhanced_url=args.enhanced_url, basic_url=args.basic_url, source_url=args.source_url)
    if args.serve:
        if not args.source:
            raise ValueError("An explicitly selected original video is required to serve the review")
        serve(args.output, args.enhanced or args.output / "enhanced.webm",
              args.basic or args.output / "basic.webm", args.source, args.port)


if __name__ == "__main__":
    main()
