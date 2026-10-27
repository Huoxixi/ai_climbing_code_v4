"""Keep setter code out of local desktop distributions."""
import ast
from pathlib import Path
import shutil

DESKTOP_RUNTIME_FILES = (
    '__init__.py', 'paths.py', 'credentials.py', 'server.py', 'launcher.py',
    'storage.py', 'window_check.py', 'verify_package.py',
)
# replay_resources launches these reviewed modules with ``python -m``. They
# cannot be discovered through Python imports, so retain their complete closure.
CORE_SUBPROCESS_MODULES = (
    'replay_visual_renderer', 'replay_focus_renderer', 'replay_inplace_renderer',
    'replay_inplace_full_renderer', 'replay_inplace_rhythm_renderer',
    'replay_template_renderer', 'replay_action_renderer',
)
# User-rejected experiments stay excluded even if a future runtime import is
# added accidentally. This is a delivery guard; the research source is retained.
REJECTED_POSE_MODULES = frozenset({
    'replay_pose_candidates', 'replay_pose_chain_evidence',
    'replay_pose_coverage_selection', 'replay_pose_candidate_sequence',
    'replay_pose_occlusion_heatmaps', 'replay_pose_occlusion_heatmaps_v2',
})
SETTER_MARKERS = ('定线项目', '仿真审核', 'AI 实验室', '标准板库', '/api/generate', 'standard-board')


def _core_imports(path: Path):
    imports = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 or node.module == 'core':
                if node.level == 1 and node.module:
                    imports.add(node.module.split('.')[0])
                else:
                    imports.update(item.name.split('.')[0] for item in node.names)
            elif node.module and node.module.startswith('core.'):
                imports.add(node.module.split('.')[1])
        elif isinstance(node, ast.Import):
            imports.update(item.name.split('.')[1] for item in node.names if item.name.startswith('core.'))
    return imports


def local_core_modules(core: Path):
    """Follow every local-entry import, including optional branches and workers.

    Inspect syntax only: importing the actual application would create stores,
    start workers and load models while merely planning a delivery.
    """
    entry = core.parent / 'boulder_local_app.py'
    if not entry.is_file():
        raise RuntimeError('Missing local backend entrypoint: boulder_local_app.py')
    selected = set()
    pending = list(_core_imports(entry))
    if (core / '__init__.py').is_file():
        pending.append('__init__')
    while pending:
        name = pending.pop()
        if name in REJECTED_POSE_MODULES:
            raise RuntimeError('Rejected pose candidate in local backend dependency: ' + name)
        if name in selected:
            continue
        source = core / (name + '.py')
        if not source.is_file():
            raise RuntimeError('Missing local backend dependency: ' + name)
        selected.add(name)
        pending.extend(_core_imports(source) - selected)
        if name == 'replay_resources':
            pending.extend(CORE_SUBPROCESS_MODULES)
    return selected


def copy_desktop_runtime(source: Path, destination: Path):
    """Use the same complete runtime for new builds and finalization."""
    missing = [name for name in DESKTOP_RUNTIME_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError('Missing desktop runtime source: ' + ', '.join(missing))
    destination.mkdir(parents=True, exist_ok=True)
    for name in DESKTOP_RUNTIME_FILES:
        shutil.copy2(source / name, destination / name)


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
    actual = {p.stem for p in core.glob('*.py')}
    rejected = actual & REJECTED_POSE_MODULES
    if rejected:
        raise RuntimeError('Rejected pose candidate in local package: ' + ', '.join(sorted(rejected)))
    expected = local_core_modules(core)
    unexpected = actual - expected
    if unexpected:
        raise RuntimeError('Unexpected backend module in local package: ' + ', '.join(sorted(unexpected)))
    desktop = package / 'desktop'
    missing = [name for name in DESKTOP_RUNTIME_FILES if not (desktop / name).is_file()]
    if missing:
        raise RuntimeError('Missing desktop runtime module: ' + ', '.join(missing))
    unexpected = {p.name for p in desktop.glob('*.py')} - set(DESKTOP_RUNTIME_FILES)
    if unexpected:
        raise RuntimeError('Unexpected desktop module in local package: ' + ', '.join(sorted(unexpected)))
