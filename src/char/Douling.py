import time

from src.char.BaseChar import BaseChar, SwitchPriority
from src.char.DoulingHud import healing_heavy_visible


class Douling(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._segment = 1

    def do_perform(self):
        self.check_combat()
        self.task.next_frame()
        if self.heavy_prompt_ready(healing_only=True):
            # E/plunge adds another hexagram and can overwrite a ready equal
            # pair. Spend the observed healing pair before continuing setup.
            self._heavy_attack_hold(.8, healing_only=True)
        if self._segment == 1:
            self._do_segment1()
        else:
            self._do_segment2()

    def _do_segment1(self):
        self._normal_attack_cycle(1.2)
        if self.flying():
            self.wait_down()
        self.check_combat()
        clicked = self.click_resonance(send_click=True, time_out=0.5)[0]
        if not clicked:
            self._finish_and_reset()
            return
        self.sleep(0.2)
        if self.flying():
            self.wait_down()
        self.check_combat()
        self._normal_attack_cycle(1.0)
        self._segment = 2
        self.switch_next_char()

    def _do_segment2(self):
        self.check_combat()
        self.task.jump(after_sleep=0.01)
        self.sleep(0.05)
        self.check_combat()
        if self.flying():
            self.click()
            self.sleep(0.05)
        else:
            self.wait_down()
        self.check_combat()
        self._heavy_attack_hold(2.5)
        self.click_echo(time_out=0)
        self.click_liberation()
        self._segment = 1
        self.switch_next_char()

    def _finish_and_reset(self):
        self.click_echo(time_out=0)
        self.click_liberation()
        self._segment = 1
        self.switch_next_char()

    def _normal_attack_cycle(self, duration):
        start = time.time()
        while time.time() - start < duration:
            self.cycle_start()
            if self.flying():
                self.wait_down()
                break
            self.click()
            self.cycle_sleep()

    def heavy_prompt_ready(self, healing_only=False):
        return (healing_heavy_visible(getattr(self.task, 'frame', None))
                or not healing_only and bool(self.task.find_one('douling_heavy', threshold=.85)))

    def emergency_heal_actions(self):
        # Do not claim R/E alone heals. Only the observed equal-pair heavy
        # prompt authorizes rescue; the shared controller checks actual HP.
        if self._heavy_attack_hold(.8, healing_only=True):
            return True
        # E and a landing attack each grant Zhen. Clear a prepared mixed pair
        # first, then prepare the regeneration pair within a short budget.
        # Source: wiki.kurobbs.com/mc/item/1429461100965666816 (2026-11-03).
        if not self.resonance_available():
            return False
        started = time.monotonic()
        if self.task.find_one('douling_heavy', threshold=.85):
            self._heavy_attack_hold(.5)
        self.check_combat()
        if not self.click_resonance(send_click=False,time_out=.6)[0]:
            return False
        self.task.jump(after_sleep=.05)
        self.sleep(.1)
        self.check_combat()
        if self.flying():
            self.click()
        if not self.task.wait_until(lambda: not self.flying(),time_out=1.2,
                                    raise_if_not_found=False):
            return False
        self.task.next_frame()
        self.check_combat()
        if time.monotonic()-started > 3:
            return False
        return self._heavy_attack_hold(.8,healing_only=True)

    def _heavy_attack_hold(self, duration, healing_only=False):
        retries = 3
        for _ in range(retries):
            self.check_combat()
            self.task.next_frame()
            # The native heavy-action prompt is required: an unprepared hold
            # consumes HP (鬼门占卦), rather than healing or building resources.
            if not self.heavy_prompt_ready(healing_only):
                self.logger.debug('Heavy prompt unverified; continue without a blind hold')
                return False
            self.task.held_attack_interrupted = False
            self.task.mouse_down()
            start = time.monotonic()
            interrupted = False
            try:
                while time.monotonic() - start < duration:
                    if self.flying() or getattr(self.task, 'held_attack_interrupted', False):
                        interrupted = True
                        break
                    if not self.heavy_prompt_ready(healing_only):
                        break
                    self.sleep(0.1)
            finally:
                self.task.mouse_up()
            self.sleep(0.01)
            if not interrupted:
                return True
            self.wait_down()

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        if self.time_elapsed_accounting_for_freeze(self.last_perform) < 8:
            return SwitchPriority.NO
        return SwitchPriority.NORMAL
