"""Bounded supervised field actions within the existing controller lease."""
import json
from pathlib import Path
import re
import time

import cv2

from src.task.CharacterMaterialTask import CharacterMaterialTask
from src.combat.PortraitHealth import portrait_health


class SettlementOperator:
    command_path = Path('logs/settlement-command.json')

    def use_bounded_liberation_retry(self):
        # The world adapter uses the material rotation's short R retry path;
        # a missed Liberation must not suspend attacks or health checks.
        return True

    def healing_replacement_available(self, candidate):
        self.next_frame()
        ratios = portrait_health(self.frame) if self.in_team_and_world() else [None] * 3
        ratio = ratios[candidate.index]
        return ratio is not None and ratio >= .7

    def engage_visible_field_enemies(self):
        if not self.in_team_and_world() or not self.original_combat_detected():
            return False
        self.log_info('聚落原版接敌判断确认，接入材料战斗轮转')
        self.fight_field_enemies()
        return True

    def prepare_verified_battle(self):
        if getattr(self, '_field_fight', False):
            # Entry was just confirmed on the caller's frame. No domain-start
            # interaction or forward acquisition belongs to a live settlement.
            return False
        return super().prepare_verified_battle()

    def fight_field_enemies(self):
        self._field_fight = True
        self._field_quiet_since = None
        self._field_deadline = time.monotonic() + 300
        self._field_counter_at = 0
        self._field_extended_kills = -1
        try:
            self.fight_verified_domain()
            self.result['battles'].append(self.rotation_events)
        finally:
            self._field_fight = self._verified_battle = self._in_combat = False

    @staticmethod
    def settlement_counter(words):
        text = re.sub(r'\s+', '', ''.join(words))
        counts = re.findall(r'已击败残象[：:]?(\d+)[/／](\d+)', text)
        if len(counts) == 1:
            killed, total = map(int, counts[0])
            if 0 <= killed <= total and 0 < total <= 1000:
                return killed, total
        return None

    def material_victory_visible(self):
        if not getattr(self, '_field_fight', False):
            return super().material_victory_visible()
        if not self.in_team_and_world():
            return False
        now = time.monotonic()
        if now >= getattr(self, '_field_counter_at', 0):
            self._field_counter_at = now + 1
            count = self.settlement_counter([b.name for b in self.ocr(0, .35, .3, .48)])
            self._field_counter = count
            if count:
                self.result['settlement_counter'] = count
        count = getattr(self, '_field_counter', None)
        # Neither clipped bars nor a single enemy's drop closes the settlement.
        # The observed settlement HUD must explicitly reach its full kill count.
        return bool(count and count[0] == count[1])

    def resume_verified_rotation(self):
        if (not getattr(self, '_field_fight', False) or not self.in_team_and_world()
                or self.material_victory_visible() or not self.original_combat_detected()):
            return False
        self.native_attack_string(3)
        self.log_info('聚落角色动作中断，原版接敌确认后续接普攻与材料轮转')
        return True

    def extend_domain_deadline(self):
        if not getattr(self, '_field_fight', False):
            return super().extend_domain_deadline()
        count = getattr(self, '_field_counter', None)
        if not count or count[0] <= self._field_extended_kills:
            return False
        self._field_extended_kills = count[0]
        self._battle_deadline = min(time.monotonic() + 60, self._field_deadline)
        return True

    def in_combat(self, target=False):
        if (getattr(self, '_field_fight', False)
                and time.monotonic() >= self._field_deadline):
            self.fail_battle('聚落战斗达到300秒测试上限')
        return super().in_combat(target=target)

    def require_field_hud(self):
        self.focus_material_menu()
        self.next_frame()
        if not self.in_team_and_world() or not self.in_team()[0]:
            raise RuntimeError('聚落操作前大世界队伍界面未确认')

    @staticmethod
    def movement_request(command):
        direction = command.get('direction', 'w')
        seconds = float(command.get('seconds', .2))
        if direction not in ('w', 'a', 's', 'd') or not 0 < seconds <= 3:
            raise ValueError('聚落移动只接受w/a/s/d，每段最多3秒')
        return direction, seconds

    def perform_settlement_command(self, command):
        action = command['action']
        if action == 'inspect':
            return
        if action == 'map':
            self.require_field_hud()
            self.send_key('m', after_sleep=1)
            self._trial_map = True
        elif action == 'close':
            if self.in_team_and_world():
                self._trial_map = False
                return
            if not self._trial_map:
                raise RuntimeError('测试器没有打开地图；不发送未知页面Esc')
            self.send_key('esc', after_sleep=.6)
            self._trial_map = not self.in_team_and_world()
        elif action == 'map-click':
            if not self._trial_map:
                raise RuntimeError('只允许在测试器已打开的地图中点选')
            x, y = float(command['x']), float(command['y'])
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError('地图坐标超出画面')
            self.click_relative(x, y, after_sleep=.8)
            self._trial_map = not self.in_team_and_world()
        elif action == 'navigate':
            if not self._trial_map:
                raise RuntimeError('导航追踪需要先核对聚落地图详情')
            if not self.menu_text(self.exact_stage, (.68, 0, 1, .15), timeout=1):
                raise RuntimeError('地图目标不是本次聚落')
            self.menu_click(r'导航追踪', (.68, .78, 1, .9), timeout=1)
            self.sleep(1)
            self._trial_map = not self.in_team_and_world()
        elif action == 'move':
            direction, seconds = self.movement_request(command)
            self.require_field_hud()
            deadline = time.monotonic() + seconds
            self.send_key_down(direction)
            try:
                while time.monotonic() < deadline:
                    self.next_frame()
                    if not self.in_team()[0] or self.check_health_bar():
                        break
                    self.sleep(min(.1, max(.01, deadline-time.monotonic())))
            finally:
                self.send_key_up(direction)
        elif action == 'center':
            self.require_field_hud()
            self.center_camera()
        elif action == 'key':
            self.require_field_hud()
            key = command['key']
            if key not in ('space', '1', '2', '3', 't', 'r', 'e', 'shift'):
                raise ValueError('聚落单键测试只允许跳跃、切人或已观察的T巡航入口')
            duration = float(command.get('seconds', .08))
            if not 0 < duration <= 1:
                raise ValueError('单键按住时间须为0–1秒')
            self.send_key(key, down_time=duration, after_sleep=.4)
        elif action == 'look':
            self.require_field_hud()
            dx, dy = int(command.get('dx', 0)), int(command.get('dy', 0))
            if max(abs(dx), abs(dy)) > 1200:
                raise ValueError('单次转向超过1200原生单位')
            # Same relative camera events as scripts/step_imitation_game.py;
            # no additional capture stream or external input worker is used.
            import Quartz as q
            for step in range(12):
                self.executor.check_enabled()
                if not self.executor.interaction.clickable():
                    raise RuntimeError('游戏前台丢失；停止转向')
                event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved,
                                                q.CGEventGetLocation(q.CGEventCreate(None)), 0)
                for value, field in ((dx, q.kCGMouseEventDeltaX), (dy, q.kCGMouseEventDeltaY)):
                    q.CGEventSetIntegerValueField(event, field,
                        round(value*(step+1)/12)-round(value*step/12))
                q.CGEventSetFlags(event, 0)
                q.CGEventPost(q.kCGHIDEventTap, event)
                self.sleep(.02)
        elif action == 'fight':
            self.require_field_hud()
            if not self.original_combat_detected():
                raise RuntimeError('原版接敌判断未确认目标；不启动聚落战斗')
            self.fight_field_enemies()
        elif action == 'pickup':
            self.require_field_hud()
            for _ in range(6):
                if not self.search_echo():
                    break
        elif action == 'finish':
            self.require_field_hud()
            self.heal_at_beacon()
            self.inspect_echo_inventory('settlement-after')
            self.open_materials_book()
            self.result['stamina_after'] = self.get_stamina()
            if not CharacterMaterialTask.enter_character_material_domain(self, {
                    'category': 'canxiang', 'fallback_stage_name': self.exact_stage}):
                raise RuntimeError('结束前聚落进度页面未确认')
            words = [b.name for b in self.ocr(.69, .27, .99, .39)]
            count = self.settlement_counter(words)
            self.result['settlement_counter'] = count
            self.result['settlement_cleared'] = bool(count and count[0] == count[1])
            self.result['test_verdict'] = ('combat_progress_verified' if count and count[0] > 0
                                           else 'navigation_not_verified')
            self.result['status'] = 'settlement_test_completed'
        else:
            raise ValueError('未知聚落测试操作')

    def run_settlement_session(self):
        self.claim_enabled = self._plan_boss = False
        self._trial_map = False
        self.focus_material_menu()
        self.next_frame()
        if self.menu_text(r'选择复苏物品', (.15, .1, .85, .35), timeout=.3):
            self.send_key('esc', after_sleep=.5)
            self.wait_in_team_and_world(time_out=10)
            self.heal_at_beacon(force_teleport=True, verify_before=False)
        if self.menu_text(r'失去意识', (.3, .2, .7, .4), timeout=.3):
            self.save_settlement_view('defeated-before-recovery')
            self.menu_click(r'复苏', (.35, .8, .65, .92), timeout=1)
            self.wait_in_team_and_world(time_out=120)
            self.heal_at_beacon(force_teleport=True, verify_before=False)
        for _ in range(2):
            if self.in_team_and_world():
                break
            if (self.menu_text(self.exact_stage, (.68, 0, 1, .15), timeout=.5)
                    or self.menu_text(r'星炬学院.*|探索度.*', (0, 0, .3, .2), timeout=.5)):
                self.send_key('esc', after_sleep=.6)
            else:
                break
        self.return_to_world()
        self.next_frame()
        ratios = portrait_health(self.frame)
        self.result['entry_portrait_health'] = ratios
        if any(ratio is None or ratio < .85 for ratio in ratios):
            self.heal_at_beacon(force_teleport=True, verify_before=False)
        if self.menu_text(r'下车.*|R下车.*', (.8, .75, 1, .85), timeout=.5):
            self.send_key('r', after_sleep=1)
        self.next_frame()
        if not self.check_health_bar():
            self.inspect_echo_inventory('settlement-before')
            self.send_key('1', after_sleep=1.2)
        else:
            self.result['inventory_before_skipped'] = 'enemies_visible; fight_before_inventory_menu'
        self.next_frame()
        for attempt in range(3):
            self.load_chars()
            if len(self.chars) == 3 and all(c and c.char_name != 'unknown' and c.confidence >= .8
                                           for c in self.chars):
                break
            self.save_settlement_view(f'session-party-unverified-{attempt}')
            self.sleep(1)
            self.next_frame()
        else:
            raise RuntimeError('聚落战斗测试前队伍未完整识别')
        self.result.update(stage=self.exact_stage, team=[c.char_name for c in self.chars],
                           session_token=str(time.time_ns()), status='waiting_for_operator')
        # Do not stand under attack while taking the initial full-screen OCR.
        self.engage_visible_field_enemies()
        self.save_settlement_view('session-ready')
        seen, deadline, preview_at = set(), time.monotonic() + 540, 0
        while time.monotonic() < deadline:
            self.next_frame()
            try:
                if self.engage_visible_field_enemies():
                    self.save_settlement_view('automatic-combat-segment-ended')
                    continue
            except Exception as exc:
                self.result.update(status='settlement_combat_failed', error=str(exc))
                self.save_settlement_view('automatic-combat-failed')
                return
            if time.monotonic() >= preview_at:
                cv2.imwrite('logs/settlement-trial/live.png', self.frame)
                preview_at = time.monotonic() + 1
            if self.command_path.exists():
                command = json.loads(self.command_path.read_text())
                key = command.get('id')
                if command.get('session_token') == self.result['session_token'] and key not in seen:
                    seen.add(key)
                    self.result['last_command'] = dict(command, state='started')
                    self.save_echo_progress()
                    try:
                        self.perform_settlement_command(command)
                        # Movement can reveal an enemy. Fight before taking a
                        # full OCR snapshot or waiting for another operator call.
                        if command['action'] in ('move', 'center', 'look', 'close', 'key'):
                            self.engage_visible_field_enemies()
                        self.result['last_command']['state'] = 'completed'
                    except Exception as exc:
                        self.mouse_up()
                        for direction in ('w', 'a', 's', 'd'):
                            self.send_key_up(direction)
                        self.result['last_command'].update(state='stopped', error=str(exc))
                    self.save_settlement_view('operator-' + str(key))
                    if self.result['status'] == 'settlement_test_completed':
                        return
            self.sleep(.2)
        self.result['status'] = 'settlement_session_time_limit'
