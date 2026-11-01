from src.char.BaseChar import BaseChar
from src.combat.RotationSequence import run_sequence, optional_step, observed_burst


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
        def opening():
            if self.has_intro:
                self.wait_intro(.5)
            self.continues_normal_attack(.3)
            self.click_echo(time_out=0)
        return run_sequence(self, [
            ('opening', lambda: optional_step(opening)),
            ('resonance', self.resonance_action),
            ('liberation', lambda: observed_burst(self)),
            ('followup_resonance', self.resonance_action),
            ('attacks', lambda: optional_step(lambda: self.continues_normal_attack(2))),
            ('followup_liberation', lambda: observed_burst(self)),
        ])
