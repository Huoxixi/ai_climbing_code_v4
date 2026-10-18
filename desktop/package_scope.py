"""Keep setter code out of local desktop distributions."""
import ast
from pathlib import Path

LOCAL_CORE_PREFIXES = ('photo_', 'replay_', 'climb_replay', 'media_normalization', 'chunked_upload', '__init__')
SETTER_MARKERS = ('定线项目', '仿真审核', 'AI 实验室', '标准板库', '/api/generate', 'standard-board')


def local_core_modules(core: Path):
    """Include shared imports, including imports inside optional workers."""
    selected = {p.stem for p in core.glob('*.py') if p.name.startswith(LOCAL_CORE_PREFIXES)}
    pending = list(selected)
    while pending:
        name = pending.pop()
        for node in ast.walk(ast.parse((core / (name + '.py')).read_text(encoding='utf-8-sig'))):
            imports = []
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith('core.'):
                    imports.append(node.module.split('.')[1])
                elif node.level == 1:
                    imports.append(node.module.split('.')[0])
            elif isinstance(node, ast.Import):
                imports.extend(item.name.split('.')[1] for item in node.names if item.name.startswith('core.'))
            for dependency in imports:
                if dependency not in selected and (core / (dependency + '.py')).is_file():
                    selected.add(dependency)
                    pending.append(dependency)
    return selected


def assert_local_frontend(dist: Path):
    scripts = list(dist.rglob('*.js'))
    if not scripts or not (dist / 'index.html').is_file():
        raise RuntimeError('Build the boulder-local frontend before packaging')
    for script in scripts:
        text = script.read_text(encoding='utf-8')
        if any(marker in text for marker in SETTER_MARKERS):
            raise RuntimeError('Setter code found in frontend; use vite build --mode boulder-local')


def assert_local_package(package: Path):
    assert_local_frontend(package / 'frontend/dist')
    if (package / 'backend/agent').exists() or (package / 'backend/main.py').exists():
        raise RuntimeError('Legacy full application must not be distributed in the local package')
    if not (package / 'backend/boulder_local_app.py').is_file():
        raise RuntimeError('Missing local boulder backend')
    core = package / 'backend/core'
    expected = local_core_modules(core)
    if any(p.stem not in expected for p in core.glob('*.py')):
        raise RuntimeError('Unexpected backend module in local package')
