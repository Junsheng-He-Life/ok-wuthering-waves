"""HUD-driven Xin actions supported by the recorded in-game skill descriptions."""
import math
from numbers import Real
import time

from src.char.BaseChar import BaseChar


class Xin(BaseChar):
    """Use explicit heavy/E/R prompts, without inferring forms from a white bar."""

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
        return super().click_liberation(con_less_than=con_less_than, send_click=send_click,
                                       wait_if_cd_ready=0)

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
        event = {'trigger': 'mouse_forte', 'limit_seconds': .65, 'status': 'holding'}
        result = getattr(self.task, 'result', None)
        if isinstance(result, dict):
            result.setdefault('xin_marked_heavy', []).append(event)
        self.logger.info('Xin mouse-forte prompt: begin bounded 0.65s heavy input')
        self.task.held_attack_interrupted = False
        try:
            self.task.mouse_down()
            while (remaining := .65 - (time.monotonic() - started)) > 0:
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
            if self.resonance_available():
                self.click_resonance(send_click=False, time_out=.6)
                self.refresh_combat_hud()
            # The inherited native cadence rechecks health and ready skills
            # between short attack chunks; it never queues a whole rotation.
            self.continues_normal_attack(.6)
            self.check_combat()
            self.switch_next_char()
        finally:
            self.task.mouse_up()
