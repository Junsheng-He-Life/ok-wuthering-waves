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


def combined_plan(jobs, audit):
    items = [dict(r) for r in audit['items']]
    updates = {}
    for job in jobs:
        for item in items:
            if item.get('resource_kind') == job['kind'] and item['target'] == job['target']:
                counts = job.get('material_counts', [])
                tier = item.get('tier_from_end', 1)
                if len(counts) >= tier:
                    item['inventory'], item['required'] = counts[-tier]
    for job in jobs:
        counts = job.get('material_counts', [])
        names = None
        singles = {'突破': {'今汐': '哀歌声核', '卜灵': '群儡的秽冕'},
                   '周本': {'心': '演轮残蜕', '今汐': '岁时之角刃', '卜灵': '深洋的咒诅'}}
        if job['kind'] in singles and len(counts) == 1:
            names = [singles[job['kind']].get(job['target'])]
            if names[0] is None:
                continue
        elif job['kind'] != '武器/技能':
            continue
        if job['kind'] == '武器/技能' and job.get('repeat',0) == 0 and job['target'] in PRIMARY_FAMILY:
            family = FAMILIES[PRIMARY_FAMILY[job['target']]]
            counts = job.get('material_counts', [])
            if 0 < len(counts) <= len(family):
                names = family[-len(counts):]
        elif job['kind'] == '武器/技能' and job['target']=='心' and job.get('repeat')==1:
            counts = job.get('material_counts', [])
            if len(counts)==1:
                names = ['急板涡流']
        elif (job['kind'] == '武器/技能' and counts
              and job.get('repeat') == {'心': 2, '今汐': 1, '卜灵': 1}.get(job['target'])):
            family_name = {'心': '机傀枢芯', '今汐': '啸叫声核', '卜灵': '呓语声核'}.get(job['target'])
            if family_name and len(counts) <= 4:
                names = FAMILIES[family_name][-len(counts):]
        if names:
            for name, (owned, needed) in zip(names, counts):
                baseline = [r for r in items if r['item_name'] == name and r['target'] == job['target']]
                if baseline and all(r['required'] != needed for r in baseline):
                    continue  # Reject truncated OCR denominators rather than shrinking the goal.
                if name not in updates or job['target'] == '卜灵' or name != '急板涡流':
                    updates[name] = owned
                for r in items:
                    if r['item_name']==name and r['target']==job['target']:
                        r['required'] = needed
    # Every scan observes the same bag: replace all copies of its observation,
    # rather than adding per-role inventory balances together.
    for r in items:
        if r['item_name'] in updates:
            r['inventory'] = updates[r['item_name']]
    recipes = [(a,b,3) for f in FAMILIES.values() for a,b in zip(f,f[1:])]
    return summarize_shared_inventory(items, recipes)


def apply_shared_material_plan(jobs):
    audit_path = Path('logs/material-audit-latest.json')
    policy_path = Path('configs/macos-desktop/shared-material-policy.json')
    if not audit_path.exists() or not policy_path.exists():
        return jobs
    policy = json.loads(policy_path.read_text())
    if not policy.get('enabled'):
        return jobs
    completed = set(policy.get('completed_materials', []))
    for job in jobs:
        boss_item = {'今汐': '哀歌声核', '卜灵': '群儡的秽冕'}.get(job['target'])
        if job['kind'] == '突破' and boss_item in completed:
            job['satisfied'] = True
            job['completion_reason'] = '用户确认培养需求消失，已刷完'
            job.pop('deferred_reason', None)
    summary = combined_plan(jobs, json.loads(audit_path.read_text()))
    for row in summary:
        if row['item_name'] in completed:
            row['completed'] = True
            row['missing_after_synthesis'] = 0
    by_name = {r['item_name']: r for r in summary}
    for job in jobs:
        if job['kind']!='武器/技能':
            continue
        if job['target']=='心' and job.get('repeat')==1:
            job['deferred_reason'] = '急板涡流为心与卜灵共用，由卜灵涡流副本统一补缺'
            job['shared_materials'] = ['急板涡流']
        if job.get('repeat',0)!=0 or job['target'] not in PRIMARY_FAMILY:
            continue
        names = FAMILIES[PRIMARY_FAMILY[job['target']]]
        entries = [by_name[n] for n in names if n in by_name]
        job['shared_materials'] = entries
        job['combined_synthesis_missing'] = {r['item_name']:r['missing_after_synthesis'] for r in entries}
        if entries and all(r['missing_after_synthesis']==0 for r in entries):
            job['deferred_reason'] = '三角色需求合并后，现有共用库存足以合成；停止消耗波片，等待合成'
            job['conversion_pending'] = True
    Path('logs/material-status/shared-plan-live.json').write_text(
        json.dumps(summary,ensure_ascii=False,indent=2))
    return jobs
