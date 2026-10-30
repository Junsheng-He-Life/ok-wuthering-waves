"""Interpret fresh preflight observations without accessing a game or controller."""
import math
import re


PRIMARY_TEAM = frozenset(('yangyang_sp', 'char_phrolova', 'char_suisui'))
BACKUP_TEAM = frozenset(('char_aemeath', 'char_denia', 'char_chisa'))
VERIFIED_STAGE = '玄幽东岳无音区'
MINIMUM_BETA_LEVEL = 80


def read_hud_level(words):
    """Require one unambiguous level label; bare HP digits never become a level."""
    values = []
    for word in words:
        match = re.fullmatch(r'Lv[.．]?([1-9][0-9]?)', re.sub(r'\s+', '', str(word)), re.I)
        if match and 1 <= int(match[1]) <= 90:
            values.append(int(match[1]))
    return values[0] if len(values) == 1 else None


def read_hud_level_variants(variants):
    values = {value for words in variants if (value := read_hud_level(words)) is not None}
    return next(iter(values)) if len(values) == 1 else None


def read_world_level(rows):
    """Read only the value on the unique 索拉等级 row, not 联觉等级 or a UID."""
    labels = [r for r in rows if re.sub(r'\s+', '', r['text']) == '索拉等级']
    if len(labels) != 1:
        return None
    label = labels[0]
    center = label['y'] + label['height'] / 2
    values = []
    for row in rows:
        match = re.fullmatch(r'([1-8])阶(?:[0Oo○ⓘiI])?', re.sub(r'\s+', '', row['text']))
        if (match and row['x'] > label['x'] + label['width']
                and abs(row['y'] + row['height'] / 2 - center)
                <= max(row['height'], label['height']) * .7):
            values.append(int(match[1]))
    return values[0] if len(values) == 1 else None


def evaluate_team_readiness(members, world_level, *, mode='tacet', stage=VERIFIED_STAGE,
                            allow_experimental=False, minimum_level=MINIMUM_BETA_LEVEL):
    """Return eligibility for this beta; levels do not establish equipment quality."""
    if type(minimum_level) is not int or not MINIMUM_BETA_LEVEL <= minimum_level <= 90:
        raise ValueError('内测最低等级须为80至90；这不是游戏通用战力标准')
    members = [dict(member) for member in members]
    issues, warnings = [], ['武器、声骸与技能练度尚未自动核对；通过基础检查不保证通关。']
    identities = [m.get('character') for m in members]
    trusted = len(members) == 3 and len(set(identities)) == 3
    for member in members:
        confidence = member.get('confidence')
        trusted = trusted and bool(member.get('registered')) and bool(member.get('character'))
        trusted = trusted and (isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                               and math.isfinite(confidence) and confidence >= .8)
    if not trusted:
        issues.append('当前三人身份未完整确认，请重新检查队伍。')
    if type(world_level) is not int or not 1 <= world_level <= 8:
        world_level = None
        issues.append('索拉等级未确认，请回到大世界重新检查。')
    for member in members:
        label = member.get('name') or f"{member.get('slot', '?')}号位"
        level = member.get('level')
        if type(level) is not int or not 1 <= level <= 90:
            member['level'] = None
            issues.append(f'{label}的等级未确认。')
        elif level < minimum_level:
            issues.append(f'{label}为{level}级，低于本内测版{minimum_level}级门槛，请换队或先培养。')
        hp = member.get('health')
        if (not isinstance(hp, (list, tuple)) or len(hp) != 2
                or any(type(value) is not int for value in hp)
                or not 0 <= hp[0] <= hp[1] or hp[1] <= 0):
            issues.append(f'{label}的生命值未确认。')
        elif hp[0] < hp[1] * .85:
            issues.append(f'{label}生命值不足85%，请先使用返回与治疗。')
    team = frozenset(identity for identity in identities if identity)
    primary_scope = team == PRIMARY_TEAM and mode == 'tacet' and stage == VERIFIED_STAGE and world_level == 8
    support_level = 'beta_candidate' if primary_scope else 'experimental'
    if team == BACKUP_TEAM:
        warnings.append('爱弥斯／达妮娅／千咲组合曾通关但出现减员，尚未列为稳定队伍。')
    if not primary_scope:
        warnings.append('此队伍、世界等级或关卡组合尚未完成本版本稳定性验收。')
        if not allow_experimental:
            issues.append('如需测试该组合，请显式开启“实验性队伍与关卡”；这不会跳过等级和身份检查。')
    return {'members': members, 'world_level': world_level, 'identity_verified': bool(trusted),
            'can_start': not issues, 'support_level': support_level, 'issues': issues,
            'warnings': warnings, 'minimum_level': minimum_level,
            'policy_note': '80级为当前内测版本的保守门槛，不是游戏通用战力规则。',
            'equipment_verified': False, 'mode': mode, 'stage': stage}
