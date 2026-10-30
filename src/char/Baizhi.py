from src.char.BaseChar import BaseChar


class Baizhi(BaseChar):

    def emergency_heal_actions(self):
        """Try ready healing R/E without waiting for energy or full concerto."""
        self.task.mouse_up()
        try:
            self.task.next_frame()
            self.check_combat()
            policy = getattr(self.task, 'use_bounded_liberation_retry', None)
            bounded = (getattr(self.task, '_verified_battle', False)
                       and (getattr(self.task, '_plan_boss', False)
                            or callable(policy) and policy()))
            if (bounded and self.liberation_available()
                    and self.click_liberation(wait_if_cd_ready=0)):
                return True
            self.task.next_frame()
            self.check_combat()
            if self.resonance_available():
                # click_resonance returns a tuple even when no key was sent.
                # Its first field records an attempted cast, not an HP gain.
                return bool(self.click_resonance(send_click=False, time_out=.6)[0])
            return False
        finally:
            self.task.mouse_up()

    def do_perform(self):
        if self.has_intro:
            self.logger.debug('has_intro wait click 1.2 sec')
            self.continues_normal_attack(1.2, click_resonance_if_ready_and_return=True)
        self.click_liberation(con_less_than=1)
        self.click_resonance()
        self.click_echo()
        self.switch_next_char()
