"""Use named shared inventory and reserved synthesis stock to stop excess runs."""
import json
from pathlib import Path
from src.task.SharedMaterialInventory import summarize_shared_inventory


FAMILIES = {
    # Only these two grades were inspected for Aemeath on 2026-10-25.
    # Do not invent inventory or conversions for unobserved lower grades.
    '偏振体': ['多翼偏振体','叠翼偏振体'],
    '镣环': ['基准镣环','改造镣环','特制镣环'],
    '弦线': ['拼凑的弦线','断续的弦线','凝固的弦线','如歌的弦线'],
    '涡流': ['慢板涡流','柔板涡流','行板涡流','急板涡流'],
    '海蚀嵌合体': ['海蚀嵌合体210','海蚀嵌合体226','海蚀嵌合体235','海蚀嵌合体239'],
    '机傀枢芯': ['低频机傀枢芯','中频机傀枢芯','高频机傀枢芯','全频机傀枢芯'],
    '啸叫声核': ['低频啸叫声核','中频啸叫声核','高频啸叫声核','全频啸叫声核'],
    '呓语声核': ['低频呓语声核','中频呓语声核','高频呓语声核','全频呓语声核'],
}
PRIMARY_FAMILY = {'心': '弦线', '卜灵': '涡流', '今汐': '海蚀嵌合体',
                  '爱弥斯': '偏振体', '达妮娅': '弦线', '千咲': '海蚀嵌合体'}
SYNTHESIS_DEFERRALS = ('低级余量可能已足以合成', '三角色需求合并后', '本轮培养需求合并后',
                      '本轮共用库存读数冲突')


def _clear_synthesis_deferral(job):
    job.pop('conversion_pending', None)
    if str(job.get('deferred_reason', '')).startswith(SYNTHESIS_DEFERRALS):
        job.pop('deferred_reason', None)


def _material_names(job):
    """Map only previously inspected rows; unknown characters remain unoptimized."""
    counts = job.get('material_counts', [])
    if not isinstance(counts, (list, tuple)) or not counts or any(
                         not isinstance(pair, (list, tuple)) or len(pair) != 2
                         or any(type(v) is not int or v < 0 for v in pair)
                         for pair in counts):
        return []
    target, kind, repeat = job['target'], job['kind'], job.get('repeat', 0)
    singles = {'突破': {'今汐': '哀歌声核', '卜灵': '群儡的秽冕'},
               '周本': {'心': '演轮残蜕', '今汐': '岁时之角刃', '卜灵': '深洋的咒诅'}}
    if kind in singles:
        name = singles[kind].get(target)
        return [name] if len(counts) == 1 and name else []
    if kind != '武器/技能':
        return []
    family = None
    if repeat == 0 and target in PRIMARY_FAMILY:
        family = FAMILIES[PRIMARY_FAMILY[target]]
    elif target == '心' and repeat == 1:
        family = ['急板涡流']
    elif repeat == {'心': 2, '今汐': 1, '卜灵': 1}.get(target):
        family_name = {'心': '机傀枢芯', '今汐': '啸叫声核', '卜灵': '呓语声核'}[target]
        family = FAMILIES[family_name]
    return family[-len(counts):] if family and len(counts) <= len(family) else []


def combined_plan(jobs, audit=None):
    """Combine this scan's requirements and stock, never historical audit counts.

    Callers must pass the complete current target scan. ``audit`` is retained
    for compatibility with the old report caller, but cannot supply missing
    grades, off-scope targets, or old cultivation goals. Disagreeing live stock
    observations remain unresolved instead of selecting a preferred character.
    """
    items = []
    for job in jobs:
        names = _material_names(job)
        if not names:
            continue
        items.extend(dict(target=job['target'], item_name=name, inventory=owned, required=needed)
                     for name, (owned, needed) in zip(names, job['material_counts']))
    recipes = [(a, b, 3) for family in FAMILIES.values() for a, b in zip(family, family[1:])]
    return summarize_shared_inventory(items, recipes)


def apply_shared_material_plan(jobs):
    policy_path = Path('configs/macos-desktop/shared-material-policy.json')
    if policy_path.exists():
        try:
            policy = json.loads(policy_path.read_text())
        except (OSError, ValueError):
            return jobs  # A damaged optional policy cannot enable an optimization.
        if not isinstance(policy, dict) or not policy.get('enabled', False):
            return jobs
    # The old policy's completed_materials was a personal, undated annotation.
    # Neither it nor an earlier audit can override a newly observed shortage.
    summary = combined_plan(jobs)
    by_name = {r['item_name']: r for r in summary}
    for job in jobs:
        if job['kind'] != '武器/技能' or job.get('repeat', 0) != 0:
            continue
        names = _material_names(job)
        if not names:
            continue
        entries = [by_name[name] for name in names]
        job['shared_materials'] = entries
        job['combined_synthesis_missing'] = {r['item_name']: r['missing_after_synthesis'] for r in entries}
        if any(r['missing_after_synthesis'] is None for r in entries):
            job['satisfied'] = False
            job.pop('conversion_pending', None)
            job['deferred_reason'] = '本轮共用库存读数冲突，需重新扫描后再规划'
        elif all(r['missing_after_synthesis'] == 0 for r in entries):
            if all(r['raw_missing'] == 0 for r in entries):
                job['satisfied'] = True
                _clear_synthesis_deferral(job)
                continue
            job['satisfied'] = False
            job['deferred_reason'] = '本轮培养需求合并后，可见共用库存足以合成；等待核验并合成'
            job['conversion_pending'] = True
        else:
            job['satisfied'] = False
            # A per-character synthesis estimate cannot reserve the same bag
            # for several characters. Keep unrelated route/error deferrals.
            _clear_synthesis_deferral(job)
    report = Path('logs/material-status/shared-plan-live.json')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return jobs
