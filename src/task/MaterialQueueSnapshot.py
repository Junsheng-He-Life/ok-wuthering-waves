"""Build dashboard rows from one saved scan, without reading account history."""


def _label(job, index, counts, audit):
    names = job.get('material_names', [])
    if len(names) == len(counts) and isinstance(names[index], str) and names[index]:
        return names[index]
    # Audit metadata is reusable only with an explicit row/tier identity.
    # Its inventory, synthesis estimates and completion flags are never used.
    matches = [item.get('item_name') for item in audit.get('items', [])
               if item.get('target') == job['target']
               and item.get('resource_kind') == job['kind']
               and item.get('repeat') == job.get('repeat', 0)
               and item.get('tier_from_end') == len(counts) - index
               and item.get('item_name')]
    if len(set(matches)) == 1:
        return matches[0]
    return f'{job["kind"]} · 第{job.get("repeat", 0) + 1}行 · 材料{index + 1}'


def build_queue_snapshot(progress, audit=None):
    """Keep current targets and raw shortages; missing observations stay unknown."""
    jobs = progress.get('jobs', [])
    targets = list(dict.fromkeys(progress.get('targets') or
                                 [job['target'] for job in jobs if job.get('target')]))
    roles = {target: [] for target in targets}
    observed = set()
    resource_rows = []
    for job in jobs:
        target = job.get('target')
        if target not in roles:
            continue
        observed.add(target)
        counts = job.get('material_counts') or []
        valid = bool(counts) and all(
            isinstance(pair, (tuple, list)) and len(pair) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in pair) for pair in counts)
        entries = counts if valid else [(None, None)]
        for index, (owned, required) in enumerate(entries):
            missing = max(0, required - owned) if valid else None
            if job.get('kind') in ('角色经验', '武器经验', '贝币'):
                resource_rows.append(missing)
            if missing == 0:
                continue
            label = (_label(job, index, counts, audit or {}) if valid
                     else f'{job.get("kind", "材料")} · 数量待核对')
            roles[target].append({'target': target, 'item_name': label, 'required': required,
                                  'stock': {'inventory': owned, 'missing': missing,
                                            'needs_verification': not valid},
                                  'note': job.get('deferred_reason', '')})
    for target in roles.keys() - observed:
        roles[target].append({'target': target, 'item_name': '培养目标材料待扫描', 'required': None,
                              'stock': {'inventory': None, 'missing': None,
                                        'needs_verification': True}, 'note': ''})
    resource_status = ('本次快照未记录，不推断已完成' if not resource_rows else
                       '有缺口或待核对数量' if any(value is None or value > 0 for value in resource_rows)
                       else '本次已记录的材料无缺口')
    return {'roles': roles, 'observed_at': progress.get('observed_at') or '未标注扫描时间',
            'resource_status': resource_status}
