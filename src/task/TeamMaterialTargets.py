"""Resolve cultivation targets from the freshly recognized combat party."""
import gettext
import math
from functools import lru_cache
from numbers import Real
from pathlib import Path


@lru_cache(maxsize=1)
def _chinese_catalog():
    # The material UI currently reads Simplified Chinese, independently of the
    # desktop panel's language. Reuse the same names as the shipped roster UI.
    return gettext.translation(
        'ok', localedir=str(Path(__file__).resolve().parents[2] / 'i18n'),
        languages=['zh_CN'], fallback=True)


def registered_target_name(character):
    from src.char.CharFactory import char_dict
    from src.task.BaseCombatTask import mismatched_names
    from src.task.TeamMaterialPlan import TEAM_NAMES

    info = char_dict[character]
    canonical = info['canonical_name']
    if canonical in TEAM_NAMES:
        return TEAM_NAMES[canonical]
    class_name = info['cls'].__name__
    display_name = mismatched_names.get(class_name, class_name)
    translated = _chinese_catalog().gettext(display_name)
    if translated == display_name:
        raise RuntimeError(f'角色 {character} 尚无已登记的中文培养目标名；请先补齐角色映射')
    return translated


def parse_target_names(value):
    names = [name.strip() for name in str(value or '').replace('，', ',').split(',') if name.strip()]
    if len(names) != 3 or len(set(names)) != 3:
        raise ValueError('请按队伍1、2、3号位填写三个不同的游戏内培养目标名，以逗号分隔；留空可自动识别')
    return names


def resolve_material_targets(chars, configured='', single_target=''):
    """Require live identities before selecting either party or explicit targets.

    A saved list is an assertion about slot identities, not permission to farm
    the previous party. Explicit single-target farming remains independent of
    the combat party, but still requires three recognized combat characters.
    """
    from src.char.CharFactory import char_dict

    if len(chars) != 3:
        raise RuntimeError('材料任务需要三个已识别的队伍角色；请补齐队伍后重新扫描')
    canonical = []
    for slot, char in enumerate(chars, 1):
        name = getattr(char, 'char_name', '')
        confidence = getattr(char, 'confidence', 0)
        if (name not in char_dict or not isinstance(confidence, Real)
                or not math.isfinite(confidence) or confidence < .8):
            raise RuntimeError(f'{slot}号位角色未被已注册的角色模板可靠识别；请重新扫描或校准模板')
        canonical.append(char_dict[name]['canonical_name'])
    if len(set(canonical)) != 3:
        raise RuntimeError('队伍头像识别结果重复；请重新扫描或校准模板')
    if target := str(single_target or '').strip():
        return [target]
    observed = [registered_target_name(name) for name in canonical]
    if len(set(observed)) != 3:
        raise RuntimeError('队伍培养目标名称不唯一；请核对角色映射')
    if str(configured or '').strip():
        requested = parse_target_names(configured)
        mismatches = [f'{i + 1}号位识别为 {live}，设置为 {saved}'
                      for i, (live, saved) in enumerate(zip(observed, requested)) if live != saved]
        if mismatches:
            raise RuntimeError('培养目标与当前队伍不一致：' + '；'.join(mismatches)
                               + '。请清空队伍培养目标名称以自动跟随，或按当前槽位修正；替其他角色刷材料请使用单个培养目标')
    return observed
