import time
from src.char.BaseChar import BaseChar, SwitchPriority


class Mornye(BaseChar):
    FORTE_READY_THRESHOLD = 0.60
    FORTE_DIAGNOSTIC_PROBE_THRESHOLD = 0.01
    FORTE_DIAGNOSTIC_INTERVAL = 1.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_heavy = 0
        self.last_forte_diagnostic = -1
        self.forte_diagnostic_screenshot_saved = False

    def reset_state(self):
        super().reset_state()
        self.last_forte_diagnostic = -1
        self.forte_diagnostic_screenshot_saved = False

    def do_perform(self):
        if self.has_intro:
            self.continues_normal_attack(1.33)
        self.check_f_on_switch = True
        if not self.on_air():
            if self.combo_limit():
                self.logger.debug("perform quick actions")
                if self.click_liberation():
                    return self.switch_next_char()
                elif self.click_echo():
                    return self.switch_next_char()
                elif self.cast_resonance_if_ready():
                    """地面奶一下，防止主C死亡"""
                    return self.switch_next_char()
                else:
                    self.continues_normal_attack(0.1)
                    return self.switch_next_char()
            self.not_on_air_actions()

        if self.on_air():
            self.on_air_actions()
        self.switch_next_char()

    def on_air(self):
        return self.has_long_action2()

    def on_air_actions(self):
        detect_ready = self.echo_available()
        self.logger.debug("on_air start attacking")
        start = time.time()
        time_out = self.rotation_timeout(10, 4)
        while (
                time.time() - start < time_out
                and self.on_air()
        ):
            if self.is_mouse_forte_full():
                self.logger.info(
                    "Mornye forte full in air: heavy attack immediately"
                )
                if self.heavy_click_forte(
                        check_fun=lambda: (
                            self.is_mouse_forte_full()
                            and not self.detect_elbow_strike(detect_ready)
                        )):
                    if self.detect_elbow_strike(detect_ready):
                        continue
                    if not self.task.wait_until(
                            lambda: self.is_con_full(),
                            time_out=1.5):
                        self.logger.debug(
                            "not condition full, try clicking echo"
                        )
                        self.click_echo(duration=0.2)
                    self.last_heavy = time.time()
                    self.check_f_on_switch = False
                    break
            self.diagnose_mouse_forte_miss("air")
            if self.detect_elbow_strike(detect_ready):
                self.logger.debug("Detected an elbow strike, attempting to reset.")
                self.task.wait_until(lambda: not self.detect_elbow_strike(detect_ready),
                                     post_action=lambda: self.continues_right_click(0.05), time_out=1.5)
            self.click_liberation()
            self.cast_resonance_if_ready()
            self.click()
            self.sleep(0.01)
        self.logger.debug("finished attacking on_air")

    def not_on_air_actions(self):
        self.logger.debug("not on_air start attacking")
        start = time.time()
        time_out = self.rotation_timeout(10, 4)
        try_douge = True
        while time.time() - start < time_out and not self.on_air():
            if self.is_mouse_forte_full():
                self.logger.info(
                    "Mornye forte full on ground: heavy attack immediately"
                )
                if try_douge:
                    self.task.click(key="right")
                    try_douge = False
                self.heavy_attack()
                self.last_heavy = time.time()
                self.check_f_on_switch = False
                continue
            self.diagnose_mouse_forte_miss("ground")
            if self.click_liberation():
                continue
            if self.cast_resonance_if_ready():
                continue
            self.click()
            self.check_combat()
            self.sleep(0.1)

    def cast_resonance_if_ready(self):
        """Use Mornye's ready E without entering the generic retry loop."""
        if time.monotonic() < getattr(self, '_e_request_after', 0) or not self.resonance_available():
            return False
        self.logger.info("Mornye resonance ready: press E immediately")
        self.send_resonance_key(post_sleep=0.12)
        self._e_request_after = time.monotonic() + 2
        self.task.next_frame()
        if not self.has_cd('resonance'):
            return False
        self.record_resonance_use()
        return True

    def diagnose_mouse_forte_miss(self, context):
        """Rate-limit failed Forte probes and preserve one E-ready frame."""
        now = time.time()
        if (
                self.last_forte_diagnostic >= 0
                and now - self.last_forte_diagnostic
                < self.FORTE_DIAGNOSTIC_INTERVAL):
            return
        self.last_forte_diagnostic = now

        find_mouse_forte = getattr(self.task, "find_mouse_forte", None)
        if not callable(find_mouse_forte):
            return
        match = find_mouse_forte(
            threshold=self.FORTE_DIAGNOSTIC_PROBE_THRESHOLD
        )
        confidence = float(getattr(match, "confidence", 0) or 0)
        self.logger.info(
            f"Mornye forte not ready in {context}: "
            f"best mouse_forte confidence={confidence:.3f}, "
            f"required={self.FORTE_READY_THRESHOLD:.3f}"
        )

        if (
                not self.forte_diagnostic_screenshot_saved
                and self.resonance_available()):
            self.task.screenshot(
                f"mornye_forte_not_matched_{context}_e_ready"
            )
            self.forte_diagnostic_screenshot_saved = True
            self.logger.info(
                "Mornye saved Forte diagnostic screenshot while E was ready"
            )

    def on_combat_end(self, chars):
        self.switch_other_char()

    def combo_limit(self):
        return self.time_elapsed_accounting_for_freeze(self.last_heavy) < 23

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        if has_intro and current_char and current_char.char_name in {'char_aemeath'}:
            return SwitchPriority.MUST
        from src.char.Linnai import Linnai
        if has_intro and current_char and self.task.has_char(Linnai) and current_char.char_name != 'char_linnai':
            return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)
        
    def detect_elbow_strike(self, ready):
        return ready and not self.available('echo', check_color=True)
