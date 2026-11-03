"""Bounded domain combat entered only through a verified start prompt."""
import re
import time

from src.task.BaseCombatTask import NotInCombatException
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.combat.MaterialBossHealing import BossHealRequested
from src.combat.NativeAttackCadence import NativeAttackCadence
from src.combat.VerifiedCombatPolicy import VerifiedCombatPolicy
from src.combat.EncounterProgress import EncounterProgress


class DomainBattleFailed(RuntimeError):
    pass


class VerifiedDomainCombat(VerifiedCombatPolicy, NativeAttackCadence, MaterialBossGuard):
    _verified_battle = False
    record_hud = False

    def material_victory_visible(self):
        if self.find_treasure_icon():
            return True
        dialog = getattr(self, 'reward_choice_dialog_current_frame', None)
        if (getattr(self, '_verified_battle', False) and not self.in_team()[0]
                and callable(dialog) and dialog()):
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

    def fight_verified_domain(self):
        self._settlement_health = (0, [])
        restarted = getattr(self, '_material_restarted', False)
        self._material_restarted = False
        needs_start = False if restarted and self.check_health_bar() else self.prepare_verified_battle()
        self.load_chars()
        for char in self.chars:
            if char is not None:
                char.recovery_until = 0
                char.recovery_required = False
        unknown = [i + 1 for i, c in enumerate(self.chars)
                   if c is None or c.char_name == 'unknown' or c.confidence < .8]
        if unknown:
            raise RuntimeError(f'unrecognized team slots {unknown}; combat not started')
        if needs_start:
            self.pick_f(handle_claim=False)
        self.combat_start = time.time()
        self._battle_deadline = time.monotonic() + 150
        self._battle_hard_deadline = self._battle_deadline + 150
        self._deadline_kills = 0
        self._encounter_progress = EncounterProgress()
        self._objective_poll_after = 0
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
        self._verified_battle = self._in_combat = True
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
                    if (not self.material_victory_visible() and self.in_team()[0]
                            and (self.check_health_bar() or self.encounter_objective_visible())):
                        self._in_combat = True
                        self._boss_rotation_recoveries += 1
                        self.log_info(f'Encounter remains active after {exc}; '
                                      f'recover rotation {self._boss_rotation_recoveries}')
                        if getattr(self, '_plan_boss', False):
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
        self.observe_encounter_progress()
        if time.monotonic() >= getattr(self, '_battle_hard_deadline', float('inf')):
            self.fail_battle('battle reached its independent hard limit')
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
        tracker = getattr(self, '_encounter_progress', None)
        if tracker is not None:
            if not tracker.consume_extension(now):
                return False
            self._battle_deadline = min(now + 90, self._battle_hard_deadline)
            self.log_info('domain timeout extended by fresh confirmed objective progress')
            return True
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
