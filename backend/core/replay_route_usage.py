"""Route usage from the selected route and deduplicated contact evidence."""
from copy import deepcopy
from .replay_summary import build_replay_summary

ROUTE_KEYS = ('route_total', 'route_used', 'route_usage')


def enrich_route_usage(organized, evidence=None):
    if organized.get('skeleton_only') or (evidence or {}).get('skeleton_only'):
        from .replay_skeleton_mode import without_hold_data
        return without_hold_data(organized)
    output = deepcopy(organized)
    source = evidence if evidence is not None else organized
    def identity(value):
        return str(value) if isinstance(value,(str,int)) and not isinstance(value,bool) and value not in ('unknown','') else None
    route = {identity(h.get('id')) for h in source.get('holds', []) if h.get('route_candidate') is not False}
    route.discard(None)
    known_contacts = 'contacts' in (source.get('attempt') or {})
    used = set()
    if known_contacts:
        summary = build_replay_summary(source)
        used = {identity(hold) for limb in summary['limbs'].values() for hold in limb['hold_ids']} & route
    total = len(route)
    used_count = len(used) if known_contacts and total else None
    percent = round(used_count / total * 100, 1) if used_count is not None and total else None
    output['route_usage'] = {'version':'route-contact-union-v1', 'route_hold_ids':sorted(route),
        'used_hold_ids':sorted(used), 'total':total, 'used':used_count, 'percent':percent,
        'basis':'automatic_route_and_contacts', 'same_hold_counted_once':True}
    prefix = [
        {'key':'route_total','label':'线路总岩点','value':total if total else None,'unit':'个' if total else '', 'display_value':None if total else '未识别'},
        {'key':'route_used','label':'使用岩点','value':used_count,'unit':'个' if used_count is not None else ''},
        {'key':'route_usage','label':'使用岩点比例','value':percent,'unit':'%' if percent is not None else '', 'display_value':f'{percent:.1f}' if percent is not None else '尚未确认'}]
    for metric in prefix:
        metric['basis'] = 'automatic_route_and_contacts'
    output['metrics'] = prefix + [m for m in output.get('metrics',[]) if m['key'] not in ROUTE_KEYS]
    return output
