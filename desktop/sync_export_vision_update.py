"""Create a new local package from a verified runtime and current app source."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from desktop import VERSION
from desktop.package_scope import assert_local_package, assert_local_frontend, local_core_modules


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    base = Path(sys.argv[1]).resolve()
    target = Path(sys.argv[2]).resolve()
    deliveries = Path('D:/ai_climbing_code/desktop-deliveries').resolve()
    if base.parent != deliveries or target.parent != deliveries or target.exists():
        raise RuntimeError('Use an existing delivery and a new sibling directory')
    assert_local_frontend(PROJECT / 'frontend/dist')
    manifest = json.loads((base / 'file-manifest.json').read_text('utf-8'))
    for item in manifest:
        if item['path'] in ('local-update.json', '使用说明.md'):
            # Both documents are replaced below, never reused as runtime input.
            continue
        path = base / item['path']
        if base not in path.resolve().parents or sha(path) != item['sha256']:
            raise RuntimeError('Base package verification failed: ' + item['path'])
    shutil.copytree(base, target, ignore=shutil.ignore_patterns('frontend', '__pycache__', '*.pyc', '*.pyo'))
    shutil.copytree(PROJECT / 'frontend/dist', target / 'frontend/dist')
    # Match the established desktop bootstrap marker.
    index = target / 'frontend/dist/index.html'
    html = index.read_text('utf-8')
    html = html.replace('<head>', '<head><script>window.__AI_CLIMBING_DESKTOP__=true;</script>', 1)
    index.write_text(html, encoding='utf-8')
    for name in local_core_modules(PROJECT / 'backend/core'):
        shutil.copy2(PROJECT / 'backend/core' / (name + '.py'), target / 'backend/core' / (name + '.py'))
    shutil.copy2(PROJECT / 'backend/boulder_local_app.py', target / 'backend/boulder_local_app.py')
    shutil.copy2(PROJECT / 'desktop/__init__.py', target / 'desktop/__init__.py')
    shutil.copy2(PROJECT / 'desktop/window_check.py', target / 'desktop/window_check.py')
    assert_local_package(target)
    update = {'version': VERSION, 'previous_package': str(base), 'application_source': str(PROJECT),
              'user_data_copied': False, 'paid_requests': 0,
              'features': ['whole-climb review with pose, joint angles, torso lean and source-time evidence',
                           'validated analysis actions in playback and export', 'saved-return recovery without new requests',
                           'simplified user workflow without experimental controls']}
    (target / 'local-update.json').write_text(json.dumps(update, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / '使用说明.md').write_text('# 本地攀岩 App ' + VERSION + '\n\n退出旧 App 后重新打开。导入视频、取色、补齐并确认岩点后，点击“开始复盘”。已配置 AI 服务时可确认本次资料发送与费用；本地复盘无需 AI 服务。\n\nAI 分析包含整体评价、具体动作与回看重点。点击动作即可回看，可慢放和循环。服务采用全程抽样画面时会明确说明，不会声称逐帧看过完整视频。\n\n“导出”只有“复盘视频”和“视频＋全部资料”，可选完整复盘或当前动作。已有分析返回可本地恢复，不会再次调用 AI；重新分析是新增请求，需另行确认费用。\n\n旧用户数据保持原目录，旧视频和返回保留。\n', encoding='utf-8')
    entries = [{'path': p.relative_to(target).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
               for p in sorted(target.rglob('*')) if p.is_file() and p.name not in ('file-manifest.json', 'resources.json')]
    (target / 'file-manifest.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    critical_names = {row['path'] for row in json.loads((base / 'resources.json').read_text('utf-8'))['critical']}
    critical_names.update({'backend/core/replay_export.py', 'backend/core/replay_vision_provider.py', 'backend/core/replay_vision_settings.py',
                           'backend/core/replay_commentary.py', 'backend/core/replay_action_jobs.py', 'backend/core/replay_full_analysis.py', 'desktop/__init__.py'})
    critical = [row for row in entries if row['path'] in critical_names or row['path'].startswith('frontend/dist/')]
    (target / 'resources.json').write_text(json.dumps({'critical': critical}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'version': VERSION, 'package': str(target), 'files': len(entries), 'verified': True}))


if __name__ == '__main__':
    main()
