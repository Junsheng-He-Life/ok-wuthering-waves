import time

from src.Labels import Labels
from src.char.BaseChar import BaseChar, SwitchPriority


class Suisui(BaseChar):
    ATTACK_INTERVAL = 0.1
    FORTE_TIMEOUT = 16.0
    CONCERTO_TIMEOUT = 8.0
    FORTE3_SWITCH_LOCKOUT = 16.0
    MAIN_DPS_FORTE3_SWITCH_LOCKOUT = 32

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_forte3_switch = -1
        self.should_heavy = False
        self.last_e_attempt = -1

    def reset_state(self):
        super().reset_state()
        self.last_forte3_switch = -1
        self.should_heavy = False
        self.last_e_attempt = -1

    def do_perform(self):
        if not self.should_heavy:
            self.should_heavy = self.has_intro
        self.perform_forte3_rotation()
        self.switch_next_char()

    def emergency_heal_actions(self):
        """Build water energy and request E; the task verifies ally recovery.

        No automatic outro here: the rescue controller returns to the actual
        injured slot. An E request alone is never treated as successful healing.
        """
        deadline = time.monotonic() + 6
        issued = False
        while time.monotonic() < deadline:
            self.check_combat()
            if self.is_e_forte_full():
                self.send_resonance_key(down_time=.08)
                self.sleep(.5)
                return True  # The controller still requires observed ally HP gain.
            issued = self.try_e() or issued
            self.click(after_sleep=.1)
        return issued

    def perform_forte3_rotation(self):
        policy = getattr(self.task, 'allow_opportunistic_skills', None)
        opportunistic = callable(policy) and policy() is True
        liberation_clicked = self.click_liberation(wait_if_cd_ready=0)
        start = time.time()
        if self.should_heavy:
            if self.has_intro:
                self.heavy_attack(1.5)
            self.click_resonance()
            self.should_heavy = False
        while self.time_elapsed_accounting_for_freeze(start) < self.FORTE_TIMEOUT:
            # A ready liberation must not wait behind the entire enhanced chain.
            if not liberation_clicked:
                liberation_clicked = self.click_liberation(wait_if_cd_ready=0)
            if self.forte3_available():
                self.logger.info('Suisui forte3 verified; enhanced chain complete, check liberation')
                break
            self.cycle_start()
            # Keep attacking through forte2 until forte3 is observed. A fixed
            # seven-click count can end halfway through the enhanced chain.
            if not self.forte2_available() and self.try_e():
                self.logger.info('Suisui E requested; continue attacks and verify forte progression')
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)
        else:
            # An unreadable forte must not bypass a visibly ready liberation.
            self.logger.warning('Suisui forte3 detection timed out; still check liberation before leaving')

        start = time.time()
        while self.time_elapsed_accounting_for_freeze(start) < self.CONCERTO_TIMEOUT:
            if not liberation_clicked:
                liberation_clicked = self.click_liberation(wait_if_cd_ready=0)
                if liberation_clicked:
                    self.logger.info('Suisui liberation confirmed before outro')
                    self.task.next_frame()
                    continue
            if self.is_con_full() and (self.forte3_available() or liberation_clicked):
                return
            if opportunistic and self.try_e():
                # Enhanced E can become ready during the concerto fill too.
                # Inspect its new HUD before the next opportunity decision.
                self.task.next_frame()
            self.click(after_sleep=0.1)
        self.logger.warning('Suisui concerto fill timed out')

    def try_e(self):
        now = time.time()
        if now - self.last_e_attempt < 1:
            return False
        # The live game also exposes an E prompt next to the full forte bar.
        # It survives icon/form changes that invalidate the upstream E icon.
        if self.is_e_forte_full() or self.task.find_one(Labels.suisui_e1):
            self.last_e_attempt = now
            self.task.record_rotation_hud('suisui-before-e') if hasattr(self.task, 'record_rotation_hud') else None
            self.send_resonance_key(down_time=.08)
            self.sleep(.4)
            self.task.record_rotation_hud('suisui-after-e') if hasattr(self.task, 'record_rotation_hud') else None
            return True
        return False

    def forte3_available(self):
        # Current 3440x1440 HUD places the motifs ~40 px left of the upstream
        # 16:9 anchor. Keep the search local, but allow that measured drift.
        return bool(self.task.find_one(Labels.suisui_forte3, threshold=0.8,
                                       horizontal_variance=.016, vertical_variance=.004))

    def forte2_available(self):
        return bool(self.task.find_one(Labels.suisui_forte2, threshold=0.8,
                                       horizontal_variance=.016, vertical_variance=.004))

    def switch_out(self, con_full=False):
        super().switch_out(con_full=con_full)
        if con_full:
            self.last_forte3_switch = time.time()

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        if time.monotonic() < getattr(self, "recovery_until", 0):
            return SwitchPriority.NO
        since_last = self.time_elapsed_accounting_for_freeze(self.last_forte3_switch)
        if since_last > 40:
            return SwitchPriority.MUST
        elif since_last < self.FORTE3_SWITCH_LOCKOUT:
            return SwitchPriority.NO
        has_main_dps = any(
            char and char != self and char.is_main_dps
            for char in getattr(self.task, 'chars', [])
        )
        if has_main_dps:
            if current_char and current_char.is_main_dps and has_intro:
                return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)
