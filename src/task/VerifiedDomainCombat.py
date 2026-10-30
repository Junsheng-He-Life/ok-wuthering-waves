"""Bounded domain combat entered only through a verified start prompt."""
import re
import time

from src.task.BaseCombatTask import NotInCombatException
from src.combat.CombatCheck import CombatCheck
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.combat.MaterialBossHealing import BossHealRequested
from src.combat.NativeAttackCadence import NativeAttackCadence


class DomainBattleFailed(RuntimeError):
    pass


class VerifiedDomainCombat(NativeAttackCadence, MaterialBossGuard):
    _verified_battle = False
    record_hud = False

    def allow_combat_without_target(self):
        """Use the original lock-on requirement when acquiring an encounter."""
        return False

    def original_combat_detected(self):
        """Run OKWW's lock indicator / health-bar and retarget entry check."""
        return CombatCheck.in_combat(self)

    def confirm_combat_entry(self):
        """Discard the previous encounter's latch before the opening rotation.

        A challenge interaction or a visible bar is only an entry candidate.
        Let CombatCheck confirm lock-on before sending attacks; settlement,
        reward verification and the active rotation retain their own policies.
        """
        self.do_reset_to_false()
        if not self.wait_until(self.original_combat_detected, time_out=8,
                               raise_if_not_found=False):
            self.fail_battle('原版接敌判断未确认锁定目标；停止本场战斗')
        self.log_info('combat entry confirmed by original OKWW detection')

    def material_victory_visible(self):
        if self.find_treasure_icon():
            return True
        if not getattr(self, '_plan_boss', False) or not self.in_team()[0] or self.check_health_bar():
            return False
        return any(re.fullmatch(r'领取奖励|ClaimRewards?', re.sub(r'\s+', '', b.name))
                   for b in self.ocr(0, .20, .28, .34))

    def record_rotation_hud(self, label):
        if not self.record_hud:
            return
        from pathlib import Path
        import cv2
        folder = Path('logs/combat-hud')
        folder.mkdir(parents=True, exist_ok=True)
        frame = self.frame
        cv2.imwrite(str(folder / f'{time.time_ns()}-{label}.png'),
                    frame[int(frame.shape[0] * .86):].copy())

    def prepare_verified_battle(self):
        self.walk_to_domain_interaction()
        if not self.find_f_with_text(target_text=[re.compile(r'开始挑战|开启挑战|Start Challenge')]):
            raise RuntimeError('start prompt not verified; no interaction')
        return True

    def resume_verified_rotation(self):
        """Reacquire a non-boss encounter after a character action timeout.

        A failed liberation animation check does not prove victory. Release
        the old combat latch and require the original lock-on detector again;
        the battle deadline and health guards still bound this recovery.
        """
        if getattr(self, '_plan_boss', False):
            return False
        self.do_reset_to_false()

        def reacquired():
            if not self.in_combat():
                return True
            if not self.in_team_and_world():
                return False
            # The enemy may be behind the camera, where no health bar can
            # trigger CombatCheck's usual retarget branch. A lock attempt is
            # safe here because entry was verified and no attack is emitted.
            self.target_enemy(wait=False)
            self.next_frame()
            return self.original_combat_detected()

        restored = self.wait_until(reacquired, time_out=8, raise_if_not_found=False)
        if restored:
            self.log_info('character action interrupted; encounter reacquired or victory verified')
        return bool(restored)

    def fight_verified_domain(self):
        self._settlement_health = (0, [])
        restarted = getattr(self, '_material_restarted', False)
        self._material_restarted = False
        needs_start = False if restarted and self.check_health_bar() else self.prepare_verified_battle()
        if not self.load_chars():
            raise RuntimeError('live team could not be read; combat not started')
        for char in self.chars:
            if char is not None:
                char.recovery_until = 0
        unknown = [i + 1 for i, c in enumerate(self.chars)
                   if c is None or c.char_name == 'unknown' or c.confidence < .8]
        if unknown:
            raise RuntimeError(f'unrecognized team slots {unknown}; combat not started')
        if needs_start:
            self.pick_f(handle_claim=False)
        self.combat_start = time.time()
        battle_started = time.monotonic()
        # Tacet trials expose a five-minute challenge timer. Their wave-local
        # counters can reset to 0/1, so material-domain kill extensions do not
        # describe their progress. Keep the same finite five-minute hard cap.
        self._battle_deadline = battle_started + (300 if getattr(self, 'echo_mode', None) == 'tacet' else 150)
        self._battle_hard_deadline = battle_started + 300
        self._deadline_kills = 0
        self.boss_profile = None
        self._boss_hp_samples = {}
        self._boss_last_dodge = 0
        self._boss_healing = False
        self._boss_heal_last = self._boss_self_heal_last = -100
        self._boss_team_health = {}
        self._boss_heal_deadline = None
        self._boss_acquire_deadline = None
        self._hp_observation = None
        self._hp_observation_frame = None
        self._verified_battle = True
        self._in_combat = False
        self._battle_end_probe = 0
        self._battle_hud_probe = 0
        self._battle_snapshot_at = 0
        self._battle_end_seen = False
        self._boss_guard_at = 0
        self._boss_unreadable_hp = 0
        self._boss_target_missing_at = None
        self._boss_rotation_recoveries = 0
        self.last_guarded_hud_gap = None
        self.combat_end_condition = self.domain_combat_finished
        self.rotation_events = []
        try:
            # Record acquisition too; it precedes on_combat_started().
            self._save_combat_debug_frames_enabled = bool(self.record_hud)
            self._start_combat_debug_frame_recorder()
            if getattr(self, '_plan_boss', False):
                self.configure_material_boss()
                try:
                    self.acquire_material_boss()
                except BossHealRequested as request:
                    self.heal_material_boss(request)
            self.confirm_combat_entry()
            try:
                self.on_combat_started()
            except BossHealRequested as request:
                self.heal_material_boss(request)
            prepare_rotation = getattr(self, 'prepare_team_rotation', None)
            if prepare_rotation:
                try:
                    prepare_rotation()
                except BossHealRequested as request:
                    self.heal_material_boss(request)
            while True:
                try:
                    if not self.in_combat():
                        break
                except BossHealRequested as request:
                    self.heal_material_boss(request)
                    continue
                char = self.get_current_char()
                started = time.monotonic()
                try:
                    char.perform()
                except BossHealRequested as request:
                    self.heal_material_boss(request)
                except NotInCombatException as exc:
                    # A skill timeout is not proof that the encounter ended.
                    # If the boss HUD is still present, restore the target and
                    # move to another character instead of abandoning the fight.
                    self._in_combat = False
                    self.mouse_up()
                    self.next_frame()
                    try:
                        if self.resume_verified_rotation():
                            continue
                    except BossHealRequested as request:
                        # Health guards also run while reacquiring. Route
                        # their request through the same rescue as rotation.
                        self.heal_material_boss(request)
                        continue
                    if (getattr(self, '_plan_boss', False)
                            and self.in_team()[0] and self.check_health_bar()):
                        self._in_combat = True
                        self._boss_rotation_recoveries += 1
                        self.log_info(f'Boss HP bar remains after {exc}; '
                                      f'recover rotation {self._boss_rotation_recoveries}')
                        self.acquire_material_boss()
                        if self._battle_end_seen:
                            break
                        self.switch_next_char(char)
                        continue
                    # Enemy HUD can vanish before the reward marker appears.
                    # Verify a delayed reward before entering outer recovery.
                    if not self.wait_until(self.material_victory_visible, time_out=8,
                                           raise_if_not_found=False):
                        self.fail_battle('combat ended without reward chest')
                    break
                finally:
                    event = {'character': char.char_name, 'seconds': round(time.monotonic() - started, 2)}
                    self.rotation_events.append(event)
                    self.log_info(f'rotation segment {event}')
            if not self.wait_until(self.material_victory_visible, time_out=6, raise_if_not_found=False):
                self.fail_battle('success not verified')
        finally:
            self._verified_battle = self._in_combat = False
            self.mouse_up()
            for key in ('w', 'a', 's', 'd', 'shift'):
                self.send_key_up(key)
            self._stop_combat_debug_frame_recorder(log_result=False)

    def in_combat(self, target=False):
        if not self._verified_battle:
            return super().in_combat(target=target)
        self._raise_if_manual_exit_before_input()
        if (getattr(self, '_boss_healing', False)
                and time.monotonic() >= self._boss_heal_deadline):
            self.fail_battle('紧急治疗超时；返回信标')
        if time.monotonic() >= self._battle_deadline:
            if (getattr(self, '_plan_boss', False) and self.in_team()[0]
                    and self.check_health_bar()):
                self._battle_deadline = time.monotonic() + 30
                self.log_info('Boss HP bar remains; continue guarded combat')
            elif not self.extend_domain_deadline():
                self.fail_battle('battle timed out (no verified kill progress or hard limit)')
        now = time.monotonic()
        if self.record_hud and now >= self._battle_snapshot_at:
            import cv2
            cv2.imwrite('logs/combat-state-latest.png', self.frame)
            self._battle_snapshot_at = now + 10
        if now >= self._battle_end_probe:
            self._battle_end_probe = now + .8
            self._battle_end_seen = bool(self.material_victory_visible())
            if self.find_one('revive_confirm_hcenter_vcenter', threshold=.8):
                self.fail_battle('revive dialog detected')
        if self._battle_end_seen:
            return False
        check_hud = now >= getattr(self, '_battle_hud_probe', 0)
        if check_hud:
            self._battle_hud_probe = now + .2
        boss_hud_visible = (getattr(self, '_plan_boss', False)
                            and self.in_team()[0] and self.check_health_bar())
        if check_hud and not boss_hud_visible and not self.in_team_and_world():
            # No input during cinematics. Do not misclassify a briefly hidden HUD.
            self.mouse_up()
            self.held_attack_interrupted = True
            self._in_combat = False
            hidden_at = time.time()
            try:
                restored = self.wait_until(
                    lambda: self.material_victory_visible() or self.in_team_and_world() or (
                        getattr(self, '_plan_boss', False) and self.in_team()[0] and self.check_health_bar()),
                    time_out=max(30, self.boss_policy_value('transition_seconds', 6))
                    if getattr(self, '_plan_boss', False) else 6,
                    raise_if_not_found=False)
            finally:
                self._in_combat = True
            if not restored:
                self.fail_battle('HUD unavailable after animation grace')
            if self.material_victory_visible():
                return False
            self.last_guarded_hud_gap = (hidden_at, time.time())
        self.guard_material_boss()
        return not self._battle_end_seen

    def extend_domain_deadline(self):
        # Domain kill counters justify extra time; never extend a boss or a
        # stalled counter. The independent hard limit cannot be renewed.
        now = time.monotonic()
        if getattr(self, '_plan_boss', False) or now >= self._battle_hard_deadline:
            return False
        text = ''.join(b.name for b in self.ocr(0, .18, .30, .34))
        match = re.search(r'击败敌人[：:]?\s*(\d+)\s*/\s*(\d+)', text)
        if not match:
            return False
        killed, total = map(int, match.groups())
        if not self._deadline_kills < killed < total:
            return False
        self._deadline_kills = killed
        self._battle_deadline = min(now + 90, self._battle_hard_deadline)
        self.log_info(f'domain timeout extended with verified kills {killed}/{total}')
        return True

    def revive_action(self):
        # Recovery belongs to the outer bounded workflow, never a nested rotation.
        self.fail_battle('death detected; leave and heal through outer workflow')
