"""Read-only shared JSON with per-member overlays; no migration of original files."""
import copy
import hashlib
from contextvars import ContextVar
from pathlib import Path
from fastapi import HTTPException

member = ContextVar('member_storage_user', default=None)
SCOPED_FILES = {'saved_boards.json', 'holds_mapping.json', 'holds_vectors.json',
                'hold_assets_meta.json', 'standard_board_activity.json'}


def member_key():
    return 'u-' + hashlib.sha256(member.get().encode()).hexdigest()


def private_path(path):
    path = Path(path)
    if not member.get() or path.name not in SCOPED_FILES:
        return str(path)
    return str(path.parent / 'members' / member_key() / path.name)


def combine(path, public, personal):
    if Path(path).name == 'saved_boards.json':
        return [{**b, 'visibility': 'public'} for b in public] + [{**b, 'visibility': 'private'} for b in personal]
    if Path(path).name == 'standard_board_activity.json':
        return personal
    result = copy.deepcopy(public)
    for key, value in personal.items():
        if Path(path).name in {'holds_mapping.json', 'holds_vectors.json'}:
            result.setdefault(key, {}).update(value)
        else:
            result[key] = value
    return result


def difference(path, public, merged):
    name = Path(path).name
    if name == 'saved_boards.json':
        public_ids = {b.get('saved_id') for b in public}
        expected = [{**b, 'visibility': 'public'} for b in public]
        actual = [b for b in merged if b.get('saved_id') in public_ids]
        if actual != expected:
            raise HTTPException(403, '公共岩板只能查看或另存为个人副本。')
        return [{**b, 'visibility': 'private'} for b in merged if b.get('saved_id') not in public_ids]
    if name == 'standard_board_activity.json':
        return merged
    result = copy.deepcopy(merged)
    for key, value in public.items():
        if name in {'holds_mapping.json', 'holds_vectors.json'}:
            for variant, content in value.items():
                if merged.get(key, {}).get(variant) != content:
                    raise HTTPException(403, '公共岩点不能覆盖，请使用新的岩点名称。')
                result[key].pop(variant, None)
            if not result[key]:
                result.pop(key)
        else:
            if merged.get(key) != value:
                raise HTTPException(403, '公共资源不能修改。')
            result.pop(key, None)
    return result
