"""Responsive decisions at safe action boundaries in verified echo fights."""
import time


class EchoCombatPolicy:
    def allow_opportunistic_skills(self):
        return (getattr(self, 'phase', None) == 'echo'
                and bool(getattr(self, '_verified_battle', False)))

    def allow_immediate_visible_liberation(self):
        return self.allow_opportunistic_skills()

    def use_bounded_liberation_retry(self):
        # A ready-looking icon must not trap an arbitrary team in R retries.
        return True

    def boss_policy_value(self, name, default):
        if name == 'reactive_dodge' and self.allow_opportunistic_skills():
            return True
        return super().boss_policy_value(name, default)

    def guard_echo_target(self):
        """Recheck lost locks without toggling a confirmed lock or blocking attacks."""
        if (not self.allow_opportunistic_skills() or getattr(self, 'in_liberation', False)
                or getattr(self, '_boss_healing', False) or self._battle_end_seen
                or not self.in_team_and_world()):
            return
        now = time.monotonic()
        if self.boss_target_locked():
            self._boss_target_missing_at = None
            return
        if self._boss_target_missing_at is None:
            self._boss_target_missing_at = now
            return
        if now - self._boss_target_missing_at < 1.5:
            return
        # No forward search: waves may spawn on either side of the arena.
        # Setting the timestamp before input prevents sleep-hook recursion.
        self._boss_target_missing_at = now
        self.mouse_up()
        self.held_attack_interrupted = True
        self.middle_click()
        self.next_frame()
        locked = self.boss_target_locked()
        if locked:
            self._boss_target_missing_at = None
        self.result.setdefault('target_rechecks', []).append({'locked': bool(locked)})
        self.log_info(f'Echo lost-target recheck: locked={bool(locked)}')

    def use_ready_combat_skill(self):
        """Interrupt only normal-attack chunks, never a skill's own nested checks.

        Character modules still own their special E chains. The generic E
        opportunity requires the existing enhanced-E marker as well as ready
        skill HUD; R is independently checked so a persistent E cannot starve it.
        """
        if (not self.allow_opportunistic_skills() or getattr(self, '_echo_skill_polling', False)
                or getattr(self, 'in_liberation', False) or getattr(self, '_boss_healing', False)):
            return False
        now = time.monotonic()
        if now < getattr(self, '_echo_skill_poll_after', 0):
            return False
        self._echo_skill_poll_after = now + .8
        self._echo_skill_polling = True
        try:
            self.check_combat()
            char = self.get_current_char()
            if not char or char.confidence < .8:
                return False
            issued = False
            if char.is_e_forte_full() and char.resonance_available():
                self.mouse_up()
                self.held_attack_interrupted = True
                issued = bool(char.click_resonance(send_click=False, time_out=.6)[0])
                self.next_frame()
            if char.liberation_available():
                self.mouse_up()
                self.held_attack_interrupted = True
                issued = bool(char.click_liberation(send_click=False, wait_if_cd_ready=0)) or issued
            if issued:
                self.result['ready_skill_segments'] = self.result.get('ready_skill_segments', 0) + 1
            return issued
        finally:
            # Reserve actual attack time after the skill/animation, rather
            # than expiring the retry gap while the attempt is still running.
            self._echo_skill_poll_after = time.monotonic() + .8
            self._echo_skill_polling = False
