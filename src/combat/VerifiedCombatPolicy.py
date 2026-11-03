"""Shared action and objective supervision for every verified farming party."""
import time

from src.combat.EncounterProgress import EncounterProgress, read_objective


class VerifiedCombatPolicy:
    def f_break(self):
        if getattr(self, '_verified_battle', False):
            if not (self.can_break or self.check_f_break()):
                return
            # A cached break prompt can outlive the last enemy. Refresh and
            # reject the reward interaction before forwarding the same F key.
            self.next_frame()
            if self.find_f_with_claim_text() or self.material_victory_visible():
                self.can_break = False
                return
        return super().f_break()

    def preferred_switch_target(self, current_char, candidates, has_intro):
        order = ('char_douling', 'char_xin', 'char_jinhsi')
        chars = getattr(self, 'chars', [])
        if (getattr(self, '_verified_battle', False) and len(chars) == 3
                and all(c and c.confidence >= .8 for c in chars)
                and {c.char_name for c in chars} == set(order)):
            for offset in (1, 2):
                name = order[(order.index(current_char.char_name) + offset) % 3]
                match = next((c for c in candidates if c.char_name == name), None)
                if match:
                    return match
            return None
        return super().preferred_switch_target(current_char, candidates, has_intro)

    def wait_for_full_con_before_switch(self):
        chars = getattr(self, 'chars', [])
        names = {getattr(c, 'char_name', '') for c in chars}
        if (getattr(self, '_verified_battle', False)
                and names == {'char_xin', 'char_jinhsi', 'char_douling'}):
            char = self.get_current_char(raise_exception=False)
            if char is None:
                return False
            # Character-owned phase completion happens before requesting a
            # switch. An unreadable Concerto ring cannot repeat that whole
            # sequence indefinitely or keep the healer off field.
            limit = 10 if char.char_name == 'char_douling' else 14
            started = max(char.last_switch_in_time, getattr(self, 'combat_start', 0))
            return started > 0 and time.time() - started < limit
        return super().wait_for_full_con_before_switch()

    def boss_policy_value(self, name, default):
        if name == 'reactive_dodge' and getattr(self, '_verified_battle', False):
            return True
        return super().boss_policy_value(name, default)

    def rotation_candidate_allowed(self, candidate):
        if not getattr(self, '_verified_battle', False):
            return True
        until = getattr(candidate, 'recovery_until', 0)
        if until == float('inf'):
            return False
        if getattr(candidate, 'recovery_required', False):
            from src.combat.PortraitHealth import portrait_health
            bars = portrait_health(getattr(self, 'frame', None))
            slot = candidate.index
            # Time alone cannot readmit a still-wounded actor. This bar gates
            # re-entry; the normal numeric guard then verifies actual HP.
            return 0 <= slot < 3 and bars[slot] is not None and bars[slot] >= .75
        return time.monotonic() >= until

    def use_bounded_liberation_retry(self):
        return True

    def use_ready_combat_skill(self):
        if (not getattr(self, '_verified_battle', False)
                or getattr(self, '_ready_skill_polling', False)
                or getattr(self, '_boss_healing', False)
                or getattr(self, 'in_liberation', False)
                or time.monotonic() < getattr(self, '_ready_skill_poll_after', 0)):
            return False
        self._ready_skill_polling = True
        try:
            self.check_combat()
            char = self.get_current_char()
            if not char or char.confidence < .8:
                return False
            permits = getattr(char, 'allows_opportunistic_skill', None)
            # Special E chains remain in the character module. A persistent
            # E prompt cannot starve an independently ready Liberation.
            issued = False
            if (not callable(permits) or permits('liberation')) and char.liberation_available():
                self.mouse_up()
                self.held_attack_interrupted = True
                issued = bool(char.click_liberation(send_click=False, wait_if_cd_ready=0))
                self.next_frame()
            if ((not callable(permits) or permits('resonance'))
                    and time.monotonic() >= getattr(char, '_enhanced_e_request_after', 0)
                    and char.is_e_forte_full() and char.resonance_available()):
                self.mouse_up()
                self.held_attack_interrupted = True
                char.send_resonance_key(down_time=.12)
                char._enhanced_e_request_after = time.monotonic() + 2
                self.next_frame()
                confirmed = char.has_cd('resonance')
                issued = bool(confirmed) or issued
            echo_ready = getattr(char, 'echo_available', None)
            if ((not callable(permits) or permits('echo'))
                    and time.monotonic() >= getattr(char, '_echo_request_after', 0)
                    and callable(echo_ready) and echo_ready()):
                self.mouse_up()
                self.held_attack_interrupted = True
                # One native request, independent of the R/E outcome. The
                # normal HUD/cooldown observation controls the next attempt.
                requested = bool(char.click_echo(time_out=0))
                char._echo_request_after = time.monotonic() + 2
                self.next_frame()
                # A single-press Q helper reports input, not a cast. A stale
                # white Q cannot repeatedly consume the normal-attack budget.
                confirmed = requested and char.has_cd('echo')
                issued = bool(confirmed) or issued
            return issued
        finally:
            self._ready_skill_polling = False
            self._ready_skill_poll_after = time.monotonic() + .8

    def observe_encounter_progress(self):
        if (getattr(self, '_plan_boss', False) or getattr(self, '_boss_healing', False)
                or getattr(self, 'in_liberation', False)):
            return
        now = time.monotonic()
        if now < getattr(self, '_objective_poll_after', 0):
            return
        # Charge OCR time to the poll interval, leaving attack time afterward.
        self._objective_poll_after = now + 3
        try:
            text = ''.join(b.name for b in self.ocr(0, .18, .30, .34))
            tracker = getattr(self, '_encounter_progress', None)
            if tracker is None:
                self._encounter_progress = tracker = EncounterProgress()
            method = getattr(getattr(self, '_executor', None), 'method', None)
            sequence = getattr(method, '_delivered_frame_sequence', None)
            event = tracker.observe(text, now, sequence)
            if event:
                self.result.setdefault('objective_progress', []).append(event)
                self.log_info(f'confirmed encounter progress: {event}')
        finally:
            self._objective_poll_after = time.monotonic() + 3

    def encounter_objective_visible(self):
        value = read_objective(''.join(b.name for b in self.ocr(0, .18, .30, .34)))
        return value is not None and value[1] < value[2]
