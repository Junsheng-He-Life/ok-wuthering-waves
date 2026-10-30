import time

from ok import Logger
from src import text_white_color
from src.char.BaseChar import BaseChar


class YangYangSp(BaseChar):
    INTRO_PERFORM_DURATION = 8.0
    PERFORM_DURATION = 3.2
    LONG_PRESS_RELEASE_DELAY = 0.1
    DISPLAY_NAME = 'Yangyang: Xuanling'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = Logger.get_logger(self.DISPLAY_NAME)

    @property
    def display_name(self):
        return self.DISPLAY_NAME

    def __repr__(self):
        return self.DISPLAY_NAME

    def resonance_available(self):
        ready = super().resonance_available()
        policy = getattr(self.task, 'allow_opportunistic_skills', None)
        if (ready and self.is_current_char and callable(policy) and policy() is True):
            # During enhanced normals E can be disabled without a countdown.
            # Saved native HUD samples give 0% white for that gray icon and
            # 10% for ready enhanced E; reject isolated effect/noise pixels.
            white = self.task.calculate_color_percentage(
                text_white_color, self.task.get_box_by_name('box_resonance'))
            return white >= .01
        return ready

    def do_perform(self):
        policy = getattr(self.task, 'allow_opportunistic_skills', None)
        opportunistic = callable(policy) and policy() is True
        duration = self.INTRO_PERFORM_DURATION if self.has_intro else self.PERFORM_DURATION
        start = time.time()
        self.task.held_attack_interrupted = False
        self.task.mouse_down()
        resonance_available = 0
        next_e_attempt = 0
        echo_used = False
        try:
            while self.time_elapsed_accounting_for_freeze(start) < duration:
                e_ready = self.resonance_available()
                e_attempted = False
                if e_ready and (not opportunistic or time.monotonic() >= next_e_attempt):
                    if resonance_available == 0:
                        resonance_available = time.time()
                    if time.time() - resonance_available > 0.2:
                        # Release the enhanced attack before E so its held
                        # input cannot swallow the skill. Ready E takes
                        # priority over a repeatedly available liberation.
                        self.task.mouse_up()
                        self.sleep(self.LONG_PRESS_RELEASE_DELAY)
                        self.task.held_attack_interrupted = True
                        if self.click_resonance(send_click=False, time_out=1)[0]:
                            self.logger.info('Xuanling E input issued after attack release; cast requires HUD verification')
                        resonance_available = 0
                        if opportunistic:
                            # A persistent ready icon is not proof of a cast.
                            # Give R a fresh-frame opportunity before retrying E.
                            next_e_attempt = time.monotonic() + 1
                            self.task.next_frame()
                            e_attempted = True
                r_window = (not e_ready or (opportunistic and (
                    e_attempted or time.monotonic() < next_e_attempt)))
                if r_window and self.liberation_available():
                    resonance_available = 0
                    self.logger.debug('liberation_available')
                    if self.click_liberation(send_click=False, wait_if_cd_ready=0):
                        duration += 2
                    # Even a failed R check can send a normal click while
                    # waiting for its animation, releasing the held attack.
                    self.task.held_attack_interrupted = True
                elif (r_window and not echo_used
                      and (not opportunistic or self.echo_available())):
                    resonance_available = 0
                    echo_used = self.click_echo(time_out=0)
                    # Even an unsuccessful Q attempt can send a normal click,
                    # which releases the previously held attack.
                    self.task.held_attack_interrupted = True
                elif not e_ready:
                    resonance_available = 0
                self.sleep(0.05)
                if getattr(self.task, 'held_attack_interrupted', False):
                    # A guarded cinematic wait may release the held button.
                    # Resume only after check_combat confirms the HUD returned.
                    self.check_combat()
                    self.task.mouse_down()
                    self.task.held_attack_interrupted = False
        finally:
            self.task.mouse_up()
            # Let the released heavy attack settle before another character reads
            # the shared long-action indicator.
            self.sleep(self.LONG_PRESS_RELEASE_DELAY, check_combat=False)
        if opportunistic and time.monotonic() >= next_e_attempt:
            # A cinematic can finish at the visit deadline with a new enhanced
            # E. Offer it once after normal completion, never in exception
            # cleanup and never while the preceding E attempt is backing off.
            self.task.next_frame()
            self.check_combat()
            if (self.task.get_current_char(raise_exception=False) is self
                    and self.resonance_available()):
                if self.click_resonance(send_click=False, time_out=.6)[0]:
                    self.logger.info('Xuanling final ready E input issued before switch; cast requires HUD verification')
        self.switch_next_char()
