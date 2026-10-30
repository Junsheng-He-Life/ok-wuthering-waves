"""Build a finite material queue; shared resources are scheduled once per team."""
import hashlib
import json

TEAM_NAMES = {'yangyang_sp': '秧秧·玄翎', 'char_phrolova': '弗洛洛', 'char_suisui': '穗穗'}
ROLE_KINDS = (('武器/技能', 'ningsu', 40), ('突破', 'qiangdi', 60), ('周本', 'zhange', 60))
SHARED_KINDS = ('角色经验', '武器经验', '贝币')


def build_team_plan(names, settings):
    if len(names) != 3 or len(set(names)) != 3:
        raise ValueError('必须识别三个不同的队伍角色')
    jobs = []
    for kind, category, cost in ROLE_KINDS:
        count = int(settings.get(f'{kind}每人次数', 1))
        if not 0 <= count <= 3:
            raise ValueError(f'{kind}次数必须为 0–3')
        if kind == '周本' and count > 1:
            raise ValueError('一轮计划最多安排三次周本，每人最多一次；游戏剩余次数仍须满足')
        for repeat in range(count):
            for name in names:
                jobs.append({'target': name, 'kind': kind, 'cost': cost,
                             'repeat': repeat, 'route': {'category': category,
                             'fallback_stage_name': str(settings.get(f'{name}{kind}关卡', '')).strip()}})
    for kind in SHARED_KINDS:
        count = int(settings.get(f'{kind}次数', 1))
        if not 0 <= count <= 10:
            raise ValueError(f'{kind}次数必须为 0–10')
        for repeat in range(count):
            jobs.append({'target': names[0], 'kind': kind, 'cost': 40, 'repeat': repeat,
                         'route': {'category': 'moni', 'fallback_stage_name': str(settings.get(f'{kind}关卡', '')).strip()}})
    return jobs


def plan_fingerprint(jobs):
    # Runtime evidence must not reset completed jobs on the next launch.
    stable = [{k: v for k, v in job.items() if k not in ('material_source', 'resolved_stage')}
              for job in jobs]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
