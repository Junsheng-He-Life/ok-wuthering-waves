"""Refresh observed shared stock by material name, without multiplying bags."""
from copy import deepcopy

from src.task.MaterialIdentity import named_job_key


class FullMaterialRefreshRequired(RuntimeError):
    pass


def refresh_targets(jobs, claimed_job, limit=4):
    """Cover the claimed family and common reward types with a few targets.

    Family links require an overlapping verified name, never a row ordinal.
    Missing identities, unbounded coverage and unsupported routes use a full
    scan. The caller also periodically forces a full scan.
    """
    if claimed_job.get('kind') not in ('武器/技能', '突破', '角色经验', '武器经验', '贝币'):
        return None
    active = [j for j in jobs if not j.get('superseded')]
    needed = set(claimed_job.get('material_names') or [])
    if not needed:
        return None
    family = [j for j in active if j['kind'] == claimed_job['kind'] and not j.get('deferred_reason')]
    while True:
        expanded = needed | {n for j in family if needed.intersection(j.get('material_names', []))
                             for n in j.get('material_names', [])}
        if expanded == needed:
            break
        needed = expanded
    common = [j for j in active if j['kind'] in ('角色经验', '武器经验', '贝币')]
    if any(not j.get('material_names') for j in common):
        return None
    needed.update(n for j in common for n in j['material_names'])
    coverage = {}
    for j in active:
        coverage.setdefault(j['target'], set()).update(j.get('material_names') or [])
    selected = [claimed_job['target']]
    remaining = needed - coverage.get(selected[0], set())
    while remaining:
        candidates = [n for n in coverage if n not in selected]
        best = max(candidates, key=lambda n: len(coverage[n] & remaining), default=None)
        if best is None or not coverage[best] & remaining or len(selected) >= limit:
            return None
        selected.append(best)
        remaining -= coverage[best]
    return selected, needed


def merge_inventory_refresh(jobs, fresh, targets, required_names):
    """Return an atomic copy; conflicts never mutate the live queue.

    Only explicitly read material names receive new inventory and timestamps.
    Requirements on unvisited characters remain intact. A changed cultivation
    plan or a stock decrease requires a complete observation instead.
    """
    old = [j for j in jobs if j['target'] in targets and not j.get('superseded')]
    if {j['target'] for j in fresh} != set(targets):
        raise FullMaterialRefreshRequired('局部刷新角色不完整')
    if {named_job_key(j) for j in old} != {named_job_key(j) for j in fresh}:
        raise FullMaterialRefreshRequired('培养需求组合改变')
    by_key = {named_job_key(j): j for j in fresh}
    result = deepcopy(jobs)
    for j in result:
        replacement = by_key.get(named_job_key(j)) if j['target'] in targets else None
        if replacement is not None:
            j.clear()
            j.update(deepcopy(replacement))
    # Check old stock as well as replacement rows before accepting updates.
    sync_observed_inventory(jobs, fresh, required_names)
    return sync_observed_inventory(result, fresh, required_names)


def sync_observed_inventory(jobs, fresh, required_names=()):
    """Update only names read in a full target scan or an entry-check page."""
    stock, stamps = {}, {}
    for j in fresh:
        names, counts = j.get('material_names') or [], j.get('material_counts') or []
        if names and len(names) != len(counts):
            raise FullMaterialRefreshRequired('材料数量与名称未对齐')
        for name, (owned, _) in zip(names, counts):
            if owned is None or (name in stock and stock[name] != owned):
                raise FullMaterialRefreshRequired(f'{name}的共享库存冲突')
            stock[name] = owned
            stamps[name] = j.get('observed_at')
    if not set(required_names) <= stock.keys():
        raise FullMaterialRefreshRequired('奖励相关材料未全部读到')
    for j in jobs:
        if j.get('superseded'):
            continue
        for name, (owned, _) in zip(j.get('material_names') or [], j.get('material_counts') or []):
            if name in stock and owned is not None and stock[name] < owned:
                raise FullMaterialRefreshRequired('观察到库存减少，需要完整核对')
    result = deepcopy(jobs)
    for j in result:
        if j.get('superseded'):
            continue
        for i, name in enumerate(j.get('material_names') or []):
            if name in stock:
                j['material_counts'][i][0] = stock[name]
                j.setdefault('inventory_observed_at', {})[name] = stamps[name]
        counts = j.get('material_counts') or []
        j['satisfied'] = bool(counts and j.get('material_names')) and all(a >= b for a, b in counts)
    return result
