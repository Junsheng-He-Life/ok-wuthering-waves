from src.char.BaseChar import BaseChar


class Denia(BaseChar):

    def do_perform(self):
        team_rotation = getattr(self.task, 'detonation_team_active', None)
        if callable(team_rotation) and team_rotation():
            return self.do_detonation_support()
        if self.has_intro:
            self.wait_intro(1.2)
        if self.resonance_available() and self.click_resonance()[0]:
            pass
        if self.click_liberation():
            self.click_resonance()
        self.click_echo()
        self.switch_next_char()

    def do_detonation_support(self):
        visit = (self.last_switch_in_time, self.task.combat_start)
        if getattr(self, '_detonation_visit', None) != visit:
            self._detonation_visit = visit
            self._detonation_chain_done = False
        if not self._detonation_chain_done:
            if self.has_intro:
                self.wait_intro(.5)
            self.continues_normal_attack(.3)
            self.click_echo(time_out=0)
            self.click_resonance(time_out=.8)
            if self.click_liberation(wait_if_cd_ready=0):
                # The first R changes form. E's follow-up can be cast before
                # normal cooldown readiness; two bounded presses cover it.
                self.click_resonance(time_out=.8)
                self.task.send_key(self.get_resonance_key(), after_sleep=.2)
            self.continues_normal_attack(2)
            self.click_liberation(wait_if_cd_ready=0)
            self._detonation_chain_done = True
        else:
            if self.resonance_available():
                self.click_resonance(time_out=.6)
            self.continues_normal_attack(.6, until_con_full=True)
            self.click_liberation(wait_if_cd_ready=0)
        return self.switch_next_char()
