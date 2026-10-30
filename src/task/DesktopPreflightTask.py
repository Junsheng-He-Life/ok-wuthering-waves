"""Inspect a fresh party in the overworld before a desktop beta run."""
from datetime import datetime
import math
from pathlib import Path

from src.runtime.TeamReadiness import (MINIMUM_BETA_LEVEL, VERIFIED_STAGE,
    evaluate_team_readiness, read_hud_level_variants, read_world_level)
from src.task.MaterialActivity import _atomic_json
from src.task.SafeMaterialTask import SafeMaterialTask


def safe_world(task):
    # Do not call in_combat()/has_target(): their entry probes may send inputs.
    return bool(task.in_team()[0] and task.find_world_earth_icon()
                and not task.in_realm() and not task.check_health_bar())


def require_safe_world(task):
    task.next_frame()
    if not safe_world(task):
        raise RuntimeError('队伍检查需要安全的大世界画面；请先离开战斗或副本。')


def observe_members(task):
    from src.char.CharFactory import char_dict
    from src.task.TeamMaterialTargets import registered_target_name
    if not task.load_chars():
        raise RuntimeError('本次队伍识别失败；未使用上次识别结果。')
    members = []
    for slot, char in enumerate(task.chars, 1):
        identity = getattr(char, 'char_name', '')
        registered = identity in char_dict
        canonical = char_dict[identity]['canonical_name'] if registered else identity
        try:
            name = registered_target_name(identity) if registered else '未识别角色'
        except RuntimeError:
            name = canonical
        confidence = getattr(char, 'confidence', 0)
        members.append({'slot': slot, 'character': canonical, 'name': name,
                        'confidence': float(confidence), 'registered': registered,
                        'level': None, 'health': None, 'equipment_verified': False})
    return members


def trusted_members(members):
    return (len(members) == 3 and len({m['character'] for m in members}) == 3
            and all(m['registered'] and math.isfinite(m['confidence']) and m['confidence'] >= .8
                    for m in members))


def _world_rows(task):
    return [dict(text=b.name, x=b.x, y=b.y, width=b.width, height=b.height)
            for b in task.ocr(0, 0, 1, 1)]


def prepare_level_crop(image):
    # Padding separates the small Lv label from the crop boundary. Returned OCR
    # coordinates are deliberately unused; this is a reading, never a click.
    import cv2
    enlarged = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(enlarged, 16, 16, 16, 16, cv2.BORDER_CONSTANT,
                              value=(30, 30, 30))


def _collect_team_readiness(task):
    """Use the task's capture and controller; never launch a second capture helper."""
    task.assert_no_pending_refill()
    task.focus_material_menu()
    require_safe_world(task)
    original_slot = task.in_team()[1]
    members = observe_members(task)
    identities = [m['character'] for m in members]
    if not trusted_members(members):
        raise RuntimeError('当前三人身份未完整识别，未切人或打开菜单。')
    observations = []
    for member in members:
        member['level'] = None
        require_safe_world(task)
        task.send_key(str(member['slot']), after_sleep=.8)
        if not task.wait_until(lambda: task.in_team()[0] and task.in_team()[1] == member['slot'] - 1,
                               time_out=3, raise_if_not_found=False):
            if task.menu_text(r'选择复苏物品', timeout=.3):
                task.send_key('esc', after_sleep=.5)
            raise RuntimeError(f"{member['slot']}号位无法切换，请先返回与治疗；未使用复苏物品。")
        values, raw = [], []
        for _ in range(2):
            require_safe_world(task)
            if task.in_team()[1] != member['slot'] - 1:
                raise RuntimeError('读取等级时当前角色改变，请重新检查队伍。')
            box = task.box_of_screen(.575, .93, .65, .98, hcenter=True)
            native = [b.name for b in task.ocr(box=box)]
            padded = [b.name for b in task.ocr(box=box, frame_processor=prepare_level_crop)]
            raw.append({'native': native, 'padded': padded})
            values.append(read_hud_level_variants((native, padded)))
            task.sleep(.2)
        if values[0] is not None and values[0] == values[1]:
            member['level'] = values[0]
        hp = task.read_current_hp()
        member['health'] = list(hp) if hp else None
        observations.append({'slot': member['slot'], 'level_text': raw})
    require_safe_world(task)
    task.send_key('esc', after_sleep=1)
    if not task.menu_text(r'终端', (0, 0, .25, .15), timeout=3):
        raise RuntimeError('终端页面未确认，停止队伍检查；未继续发送菜单输入。')
    world_values = []
    for _ in range(2):
        task.next_frame()
        rows = _world_rows(task)
        world_values.append(read_world_level(rows))
        # Save only the rank-related row; avoid persisting the terminal's UID/profile.
        observations.append({'world_level': world_values[-1]})
        task.sleep(.2)
    world_level = world_values[0] if world_values[0] == world_values[1] else None
    if not task.menu_text(r'终端', (0, 0, .25, .15), timeout=.5):
        raise RuntimeError('终端页面发生变化，停止检查；未发送返回输入。')
    task.send_key('esc', after_sleep=1)
    require_safe_world(task)
    final_members = observe_members(task)
    if [m['character'] for m in final_members] != identities or not trusted_members(final_members):
        raise RuntimeError('检查期间队伍发生变化，请重新检查。')
    if type(original_slot) is int and 0 <= original_slot < 3:
        task.send_key(str(original_slot + 1), after_sleep=.6)
        if not task.wait_until(lambda: task.in_team()[0] and task.in_team()[1] == original_slot,
                               time_out=3, raise_if_not_found=False):
            raise RuntimeError('检查后无法恢复原出场角色，请重新检查队伍。')
        require_safe_world(task)
    report = evaluate_team_readiness(members, world_level,
        mode=getattr(task, 'desktop_preflight_mode', getattr(task, 'echo_mode', 'materials')),
        stage=getattr(task, 'desktop_preflight_stage', '') or getattr(task, 'exact_stage', '')
              or getattr(task, 'echo_stage_override', '') or task.config.get('声骸关卡', VERIFIED_STAGE),
        allow_experimental=getattr(task, 'desktop_allow_experimental', False),
        minimum_level=getattr(task, 'desktop_minimum_level', MINIMUM_BETA_LEVEL))
    report.update(status='preflight_completed' if report['can_start'] else 'preflight_blocked',
                  checked_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                  observations=observations, source='fresh_game_observation')
    _atomic_json(Path('logs/desktop-preflight.json'), report)
    task.result['preflight'] = report
    return report


def collect_team_readiness(task):
    """Invalidate old inspection output before touching the current game state."""
    report = {'status': 'running', 'members': [], 'world_level': None, 'can_start': False,
              'source': 'fresh_game_observation', 'issues': []}
    task.result['preflight'] = report
    _atomic_json(Path('logs/desktop-preflight.json'), report)
    try:
        return _collect_team_readiness(task)
    except Exception as exc:
        report.update(status='stopped', issues=[str(exc)],
                      checked_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        _atomic_json(Path('logs/desktop-preflight.json'), report)
        raise


def require_desktop_preflight(task):
    report = collect_team_readiness(task)
    if not report['can_start']:
        raise RuntimeError('队伍检查未通过：' + '；'.join(report['issues']))
    return report


class DesktopPreflightTask(SafeMaterialTask):
    phase = 'preflight'
    desktop_preflight_mode = 'tacet'
    desktop_preflight_stage = VERIFIED_STAGE
    desktop_allow_experimental = False
    desktop_minimum_level = MINIMUM_BETA_LEVEL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '检查当前队伍'
        self.description = '读取当前三人等级、生命值与索拉等级，不进场、不消费。'
        self.default_config.clear()
        self.support_schedule_task = False

    def trust_cached_character_hints(self):
        return False

    def trust_preferred_character_hints(self):
        return False

    def run(self):
        self.result = {'status': 'running', 'phase': self.phase}
        try:
            report = collect_team_readiness(self)
            self.result['status'] = 'preflight_completed' if report['can_start'] else 'preflight_blocked'
        except Exception as exc:
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            _atomic_json(Path('logs/desktop-preflight-result.json'), self.result)
