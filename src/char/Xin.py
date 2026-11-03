"""HUD-driven Xin actions supported by the recorded in-game skill descriptions."""
import math
from numbers import Real
import time

from src.char.BaseChar import BaseChar


class Xin(BaseChar):
    """Use explicit heavy/E/R prompts, without inferring forms from a white bar."""

    def reset_state(self):
        super().reset_state()
        self._phase2_active = False
        self._phase2_finish_allowed = False

    def identity_verified(self):
        return (self.char_name == 'char_xin' and isinstance(self.confidence, Real)
                and not isinstance(self.confidence, bool)
                and math.isfinite(self.confidence) and self.confidence >= .8)

    def click_liberation(self, con_less_than=-1, send_click=False, wait_if_cd_ready=0):
        # BaseChar's supervised path checks health between R attempts, caps a
        # stale ready icon at 1.2 seconds and leaves two seconds before retry.
        # Do not fall back to its legacy 15-second loop in another task type.
        policy = getattr(self.task, 'use_bounded_liberation_retry', None)
        if (not self.identity_verified() or not getattr(self.task, '_verified_battle', False)
                or not callable(policy) or not policy()):
            return False
        phase2 = getattr(self, '_phase2_active', False)
        if phase2 and not getattr(self, '_phase2_finish_allowed', False):
            return False
        cast = super().click_liberation(con_less_than=con_less_than, send_click=send_click,
                                       wait_if_cd_ready=0)
        if cast:
            self._phase2_active = not phase2
            if not phase2:
                self._phase2_started = time.monotonic()
                self._phase2_enhanced_e = self._phase2_attack_chunks = 0
                self._phase2_heavy_completed = False
                self.logger.info('Xin second phase entered by confirmed Liberation; retain the field')
        return cast

    def allows_opportunistic_skill(self, name):
        # The shared filler hook must not fire the second R immediately or
        # consume the enhanced E behind this character's phase accounting.
        return name == 'echo' or not getattr(self, '_phase2_active', False)

    def perform_second_phase(self):
        started = time.monotonic()
        event = {'status':'active','enhanced_e':0,'requested_normal_seconds':0}
        self.task.result.setdefault('xin_second_phase',[]).append(event)
        try:
            while getattr(self,'_phase2_active',False):
                self.refresh_combat_hud()
                elapsed = time.monotonic()-started
                if self.is_e_forte_full() and self.resonance_available():
                    self.send_resonance_key()
                    self.refresh_combat_hud()
                    if not self.is_e_forte_full():
                        self._phase2_enhanced_e += 1
                        event['enhanced_e'] = self._phase2_enhanced_e
                # The special heavy unlocks the terminal R. Normal attack
                # duration and a ready-looking R cannot replace this action.
                if self.marked_heavy_attack():
                    self.refresh_combat_hud()
                    if not self.is_mouse_forte_full():
                        self._phase2_heavy_completed = True
                        event['marked_heavy_consumed'] = True
                ready = (elapsed >= 6 and self._phase2_attack_chunks >= 8
                         and getattr(self, '_phase2_heavy_completed', False))
                if ready and self.liberation_available():
                    self._phase2_finish_allowed = True
                    try:
                        if self.click_liberation(send_click=False,wait_if_cd_ready=0):
                            event.update(status='finisher_confirmed',seconds=round(time.monotonic()-started,2))
                            return
                    finally:
                        self._phase2_finish_allowed = False
                if elapsed >= 25:
                    event.update(status='output_window_ended_finisher_unverified',seconds=round(elapsed,2))
                    self.logger.info('Xin output window ended; keep form state and allow guarded rotation')
                    return
                self.continues_normal_attack(.35)
                self._phase2_attack_chunks += 1
                event['requested_normal_seconds'] = round(.35*self._phase2_attack_chunks,2)
        finally:
            self.task.mouse_up()

    def refresh_combat_hud(self):
        self.task.next_frame()
        self.check_combat()

    def marked_heavy_attack(self):
        # The recorded circuit description says this heavy unlocks R. Its
        # mouse prompt is the trigger; generic white forte pixels are not.
        if not self.identity_verified() or not self.is_mouse_forte_full():
            return False
        self.check_combat()
        if not self.is_mouse_forte_full():
            return False
        started = time.monotonic()
        deadline = started + .65
        event = {'trigger': 'mouse_forte', 'limit_seconds': .65, 'status': 'holding'}
        result = getattr(self.task, 'result', None)
        if isinstance(result, dict):
            result.setdefault('xin_marked_heavy', []).append(event)
        self.logger.info('Xin mouse-forte prompt: begin bounded 0.65s heavy input')
        self.task.held_attack_interrupted = False
        try:
            native_hold = getattr(self.task, 'native_bounded_heavy', None)
            native_result = native_hold(.65) if callable(native_hold) else None
            if native_result is not None:
                event.update(native_result)
                return event['status'] == 'released'
            self.task.mouse_down()
            while (remaining := deadline - time.monotonic()) > 0:
                self.sleep(min(.1, remaining))
                self.check_combat()
                if getattr(self.task, 'held_attack_interrupted', False):
                    event['status'] = 'interrupted'
                    break
            else:
                event['status'] = 'released'
        except BaseException:
            event['status'] = 'interrupted'
            raise
        finally:
            self.task.mouse_up()
            event['held_seconds'] = round(time.monotonic() - started, 4)
            self.logger.info(f'Xin marked heavy input {event["status"]}: {event["held_seconds"]}s')
        return True

    def do_perform(self):
        if not self.identity_verified():
            raise RuntimeError('心的当前身份未被可靠识别；不执行角色输入')
        try:
            if getattr(self,'_phase2_active',False):
                self.perform_second_phase()
                self.switch_next_char()
                return
            self.refresh_combat_hud()
            self.wait_intro(time_out=.6)
            self.refresh_combat_hud()
            if self.marked_heavy_attack():
                # R can become available only after the special heavy. The
                # fresh HUD decides whether to cast; the hold alone proves no cast.
                self.refresh_combat_hud()
            if self.liberation_available():
                self.click_liberation(send_click=False, wait_if_cd_ready=0)
                self.refresh_combat_hud()
            if getattr(self,'_phase2_active',False):
                self.perform_second_phase()
                self.switch_next_char()
                return
            if self.resonance_available():
                self.click_resonance(send_click=False, time_out=.6)
                self.refresh_combat_hud()
            # The inherited native cadence rechecks health and ready skills
            # between short attack chunks; it never queues a whole rotation.
            self.continues_normal_attack(.6)
            self.check_combat()
            if getattr(self,'_phase2_active',False):
                self.perform_second_phase()
            self.switch_next_char()
        finally:
            self.task.mouse_up()
