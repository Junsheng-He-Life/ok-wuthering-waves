"""Validate GUI requests before starting the established controller CLI."""
from dataclasses import dataclass
import re
from src.runtime.CultivationPolicy import cultivation_kinds

TASKS = {'materials': '按角色培养（自选项目）', 'tacet': '无音区声骸',
         'boss': 'Boss声骸', 'material_stage': '指定材料副本'}


def targets(text):
    names = [x.strip() for x in re.split('[,，]', text) if x.strip()]
    if len(names) not in (0, 1, 3) or len(set(names)) != len(names):
        raise ValueError('培养角色留空，或填1名，或按当前槽位填3名不同角色，以逗号分隔。')
    if any(len(name) > 40 or any(ord(c) < 32 for c in name) for name in names):
        raise ValueError('角色名称格式不正确。')
    return names


@dataclass(frozen=True)
class DesktopRequest:
    kind: str = 'tacet'
    stage: str = ''
    target: str = ''
    runs: int = 1
    waveplates: int = 0
    reserve: int = 0
    solvents: int = 0
    claim_rewards: bool = False
    cultivation_selection: tuple | None = None

    def arguments(self, solvents_used=0):
        if self.kind not in TASKS:
            raise ValueError('未知任务类型。')
        names = targets(self.target)
        selection = (cultivation_kinds(self.cultivation_selection)
                     if self.cultivation_selection is not None else None)
        if selection is not None and self.kind != 'materials':
            raise ValueError('刷取项目只用于按角色培养任务。')
        if self.kind != 'materials' and (not self.stage.strip() or len(self.stage) > 100
                                         or any(ord(c) < 32 for c in self.stage)):
            raise ValueError('请选择或填写指南中的完整副本名。')
        if self.kind == 'material_stage' and len(names) != 1:
            raise ValueError('指定材料副本请填一名培养角色；战斗仍使用游戏当前队伍。')
        if self.kind == 'materials' and selection is None and not self.claim_rewards:
            raise ValueError('培养计划需要领奖；只测试战斗请选择“指定材料副本”并关闭领奖。')
        for label, value, upper in [('场数/奖励份数', self.runs, 100),
                                    ('波片', self.waveplates, 4000),
                                    ('储备', self.reserve, 240), ('溶剂', self.solvents, 133)]:
            if type(value) is not int or not 0 <= value <= upper:
                raise ValueError(f'{label}必须为0–{upper}的整数。')
        if self.runs < 1:
            raise ValueError('至少测试1场或领取1份。')
        minimum_cost = 40 if self.kind in ('materials','material_stage') else 60
        if selection is not None and not any(kind in selection for kind in ('武器/技能','角色经验','武器经验','贝币')):
            minimum_cost = 60
        if self.claim_rewards and self.waveplates < minimum_cost:
            raise ValueError('波片额度不足一份奖励；请调整额度或关闭领奖。')
        if type(solvents_used) is not int or solvents_used < 0:
            raise ValueError('资源账本未核实。')
        phase = 'plan' if self.kind == 'materials' else 'echo'
        if selection is not None:
            phase = 'cultivation'
        args = ['--phase', phase, '--desktop-session', '--runs', str(self.runs),
                '--max-stamina', str(self.waveplates if self.claim_rewards else 0),
                '--reserve-limit', str(self.reserve if self.claim_rewards else 0),
                '--solvent-limit', str(self.solvents if self.claim_rewards else 0),
                '--solvent-total', str(solvents_used + (self.solvents if self.claim_rewards else 0)),
                '--timeout', '600', '--record-hud']
        if selection is not None:
            args += ['--cultivation-kinds', ','.join(selection)]
            if not self.claim_rewards:
                args += ['--echo-no-claim']
        if self.kind in ('tacet', 'boss', 'material_stage'):
            mode = 'material' if self.kind == 'material_stage' else self.kind
            args += ['--echo-mode', mode, '--stage', self.stage.strip()]
            if not self.claim_rewards:
                args += ['--echo-no-claim']
            if self.kind == 'material_stage': args += ['--target',names[0]]
        elif names:
            args += ['--target', names[0]] if len(names) == 1 else ['--targets', ','.join(names)]
        elif self.kind == 'materials':
            args += ['--current-team-targets']
        return args


def action_arguments(action, kind='tacet', target='', cultivation_selection=None):
    common = ['--desktop-session', '--max-stamina','0','--reserve-limit','0','--solvent-limit','0']
    if action == 'team':
        return ['--phase','team','--timeout','180',*common]
    if action == 'recover':
        return ['--phase','recover','--timeout','180',*common]
    if action == 'catalog':
        if kind in ('tacet','boss','material_stage'):
            return ['--phase','echo-catalog','--echo-mode','material' if kind=='material_stage' else kind,'--timeout','180',*common]
        names = targets(target)
        if kind == 'material_stage':
            return ['--phase','scan','--timeout','180',*common]
        args = ['--phase','catalog','--timeout','600',*common]
        if cultivation_selection is not None:
            args[1] = 'cultivation-catalog'
            args += ['--cultivation-kinds', ','.join(cultivation_kinds(cultivation_selection)), '--echo-no-claim']
        if names:
            args += ['--target', names[0]] if len(names)==1 else ['--targets', ','.join(names)]
        return args
    raise ValueError('未知操作。')
