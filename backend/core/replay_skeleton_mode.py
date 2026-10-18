"""Explicit pose-only results: absent hold evidence is not zero hold usage."""
from copy import deepcopy

def skeleton_draft():
    return {'skeleton_only': True, 'holds': [], 'hold_candidates': [],
            'hold_evidence': {'reference_frame': 0}, 'models': {}, 'route': {}}

def without_hold_data(value):
    def related(key):
        key = key.lower()
        return ('hold' in key or 'contact' in key or key in {
            'route', 'route_usage', 'route_total', 'route_used', 'route_color', 'route_color_sample',
            'saved_route_reference', 'start_hold_id', 'end_hold_id'})
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k,v in item.items() if not related(k)}
        if isinstance(item, list):
            return [clean(v) for v in item if not (isinstance(v,dict) and (
                related(str(v.get('key',''))) or '岩点' in str(v.get('label',''))))]
        return deepcopy(item)
    result = clean(value)
    result['skeleton_only'] = True
    return result
