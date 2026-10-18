"""Stage a folder change; copy only after workers have stopped on next launch."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import uuid


def read_settings(paths):
    file = paths.config / 'storage.json'
    return json.loads(file.read_text('utf-8')) if file.is_file() else {}


def write_settings(paths, value):
    paths.config.mkdir(parents=True, exist_ok=True)
    temporary = paths.config / ('storage-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), 'utf-8')
    temporary.replace(paths.config / 'storage.json')


def validate_destination(paths, directory):
    target = Path(directory).resolve()
    if target == paths.data.resolve():
        return target
    if (target == paths.install or paths.install in target.parents or
            target == paths.user or paths.user in target.parents or
            paths.data.resolve() in target.parents or
            target in paths.data.resolve().parents or
            any(part.lower() in {'.local', '.private'} for part in target.parts)):
        raise ValueError('请选择独立的空文件夹。')
    if not target.is_dir() or any(target.iterdir()):
        raise ValueError('请选择空文件夹，以免覆盖已有文件。')
    probe = target / ('write-check-' + uuid.uuid4().hex)
    try:
        with probe.open('xb') as stream:
            stream.write(b'ok')
    finally:
        probe.unlink(missing_ok=True)
    return target


def schedule_change(paths, directory):
    target = validate_destination(paths, directory)
    saved = read_settings(paths)
    if target == paths.data.resolve():
        saved.pop('pending_directory', None)
    else:
        saved['pending_directory'] = str(target)
    write_settings(paths, saved)
    return {'directory': str(target), 'restart_required': target != paths.data.resolve()}


def relocate(value, source, target):
    if isinstance(value, dict):
        return {key: relocate(item, source, target) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate(item, source, target) for item in value]
    if isinstance(value, str):
        # Stored media references include absolute Windows paths; do not alter prose.
        for old, new in ((str(source), str(target)),
                         (source.as_posix(), target.as_posix())):
            if value == old or value.startswith(old + '/') or value.startswith(old + '\\'):
                return new + value[len(old):]
    return value


def apply_pending_change(paths):
    saved = read_settings(paths)
    if not saved.get('pending_directory'):
        return paths
    target = validate_destination(paths, saved['pending_directory'])
    source = paths.data.resolve()
    if target == source:
        saved.pop('pending_directory', None)
        write_settings(paths, saved)
        return paths
    # Reject linked data rather than copying outside the selected source tree.
    for file in source.rglob('*'):
        if (file.is_symlink() or source not in file.resolve().parents or
                (hasattr(file, 'is_junction') and file.is_junction())):
            raise ValueError('资料中存在链接文件夹，未切换存储位置。')
    staging = target.parent / ('.ai-climbing-copy-' + uuid.uuid4().hex)
    try:
        shutil.copytree(source, staging)
        for file in staging.rglob('*.json'):
            value = json.loads(file.read_text('utf-8'))
            updated = relocate(value, source, target)
            if updated != value:
                file.write_text(json.dumps(updated, ensure_ascii=False), 'utf-8')
        # Recheck after copying. Never merge into or overwrite user files.
        validate_destination(paths, target)
        target.rmdir()
        staging.rename(target)
        saved = {'directory': str(target)}
        write_settings(paths, saved)
        return replace(paths, storage=target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
