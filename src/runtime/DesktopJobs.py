"""Validated desktop requests mapped to the existing bounded task runner."""
from dataclasses import dataclass
from pathlib import Path


TASKS = {
    'tacet': ('无音区声骸', 'echo'),
    'boss': ('Boss 声骸', 'echo'),
    'materials': ('全队培养材料', 'plan'),
}


@dataclass(frozen=True)
class DesktopRequest:
    kind: str = 'tacet'
    stage: str = ''
    claims: int = 2
    waveplates: int = 120
    solvents: int = 0
    reserve: int = 0
    claim_rewards: bool = True
    experimental: bool = False

    def validate(self):
        if self.kind not in TASKS:
            raise ValueError('请选择支持的任务。')
        if self.kind != 'materials' and not self.stage.strip():
            raise ValueError('请先读取关卡列表，再选择要刷取的关卡。')
        if len(self.stage) > 100 or any(ord(c) < 32 for c in self.stage):
            raise ValueError('关卡名称格式不正确，请重新读取列表。')
        for name, value, minimum, maximum in (
            ('领奖份数', self.claims, 1, 6), ('波片额度', self.waveplates, 0, 360),
            ('溶剂额度', self.solvents, 0, 6), ('储备额度', self.reserve, 0, 240),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'{name}须为 {minimum}–{maximum} 的整数。')
        if self.claim_rewards and self.waveplates < (40 if self.kind == 'materials' else 60):
            raise ValueError('波片额度不足以领取一份奖励，请提高额度或选择只吸收。')
        if self.kind == 'materials' and not self.claim_rewards:
            raise ValueError('培养材料任务需要领取奖励。')
        return self

    def arguments(self, solvents_used=0):
        self.validate()
        if type(solvents_used) is not int or solvents_used < 0:
            raise ValueError('溶剂账本不可用，请先检查资源记录。')
        claim = self.claim_rewards
        args = ['--phase', TASKS[self.kind][1], '--desktop-session', '--desktop-preflight',
                '--runs', str(self.claims), '--max-stamina', str(self.waveplates if claim else 0),
                '--reserve-limit', str(self.reserve if claim else 0),
                '--solvent-limit', str(self.solvents if claim else 0),
                '--solvent-total', str(solvents_used + (self.solvents if claim else 0)),
                '--timeout', '600']
        if self.kind != 'materials':
            args += ['--echo-mode', self.kind, '--stage', self.stage.strip()]
            if not claim:
                args += ['--echo-no-claim']
        if self.experimental:
            args += ['--desktop-experimental']
        return args


def action_arguments(action, kind='tacet', stage=''):
    if action == 'preflight':
        args = ['--phase', 'preflight', '--desktop-session', '--desktop-preflight-mode', kind, '--timeout', '180']
        if stage:
            args += ['--stage', stage]
        return args
    if action == 'catalog':
        if kind == 'materials':
            return ['--phase', 'catalog', '--desktop-session', '--timeout', '600']
        if kind not in ('tacet', 'boss'):
            raise ValueError('未知关卡分类')
        return ['--phase', 'echo-catalog', '--echo-mode', kind, '--desktop-session', '--timeout', '180']
    if action == 'recover':
        return ['--phase', 'recover', '--desktop-session', '--timeout', '180']
    if action == 'observe':
        return ['--phase', 'menu-step', '--menu-action', 'inspect', '--desktop-session', '--timeout', '60']
    raise ValueError('未知操作')


def read_json(path, default=None):
    import json
    try:
        file = Path(path)
        if file.stat().st_size > 4_000_000:
            return default
        value = json.loads(file.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def result_summary(result):
    """Do not infer success from a zero process exit or a nondecreasing bag count."""
    status = result.get('status', 'unknown')
    if status == 'completed':
        title = '本轮已完成'
    elif status in ('interrupted', 'timeout'):
        title = '任务已停止' if status == 'interrupted' else '已达到本轮时限'
    elif status == 'preflight_blocked':
        title = '队伍检查未通过'
    elif status in ('stopped', 'not_started', 'running', 'unknown'):
        title = '需要处理后再继续'
    elif status in ('preflight_completed', 'catalog_no_spending', 'menu_observed',
                    'inventory_inspected_no_spending', 'diagnosed', 'world_verified', 'read_only'):
        title = '检查已完成'
    else:
        title = '任务已结束，请查看结果'
    budget = result.get('budget') or {}
    budget = budget if isinstance(budget, dict) else {}
    preflight = result.get('preflight') or {}
    preflight = preflight if isinstance(preflight, dict) else {}
    return {'title': title, 'status': status,
            'message': result.get('error') or result.get('message') or
                       '；'.join(str(issue) for issue in preflight.get('issues', [])),
            'spent': budget.get('spent', 0), 'claimed': budget.get('claimed', 0),
            'solvents': budget.get('solvents_used', 0), 'reserve': budget.get('reserve_used', 0),
            'pending': bool(budget.get('claim_pending'))}
