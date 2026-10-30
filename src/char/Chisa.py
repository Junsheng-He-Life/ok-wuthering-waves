import time

from src.char.BaseChar import BaseChar, CharType, get_default_buff_time


class Chisa(BaseChar):
    def is_dps_config(self):
        return self.task and self.task.char_config.get("Chisa DPS")

    def get_char_type(self):
        if self.is_dps_config():
            return CharType.MAIN_DPS
        return super().get_char_type()

    def get_buff_time(self):
        if self.is_dps_config():
            return get_default_buff_time(CharType.MAIN_DPS)
        return super().get_buff_time()

    def do_perform(self):
        team_rotation = getattr(self.task, 'detonation_team_active', None)
        if callable(team_rotation) and team_rotation():
            return self.do_detonation_support()
        if not self.is_dps_config():
            return self.do_fast_support()
        return self.do_dps_perform()

    def emergency_heal_actions(self):
        """Try the team-healing Liberation; the controller verifies ally HP."""
        self.task.mouse_up()
        if self.click_liberation(wait_if_cd_ready=0):
            return True
        # A short energy top-up is allowed, never the complete support combo
        # while an ally is already injured.
        self.click_resonance(time_out=.6)
        self.continues_normal_attack(1.2)
        return self.click_liberation(wait_if_cd_ready=0)

    def do_detonation_support(self):
        self.check_f_on_switch = True
        visit = (self.last_switch_in_time, self.task.combat_start)
        if getattr(self, '_detonation_visit', None) != visit:
            self._detonation_visit = visit
            self._detonation_chain_done = False
        if not self._detonation_chain_done:
            if self.has_intro:
                self.wait_intro(.5)
            else:
                self.continues_normal_attack(.5)
            self.click_echo(time_out=0)
            self.click_resonance(time_out=.8)
            # Charge the enhanced E from attacks rather than assuming the
            # reference equipment's recharge or the Intro supplied enough.
            start = time.monotonic()
            while not self.is_forte_full() and time.monotonic() - start < 3:
                self.continues_normal_attack(.3)
            self.click_liberation(wait_if_cd_ready=0)
            if self.is_forte_full():
                self.perform_forte()
            else:
                self.click_resonance(time_out=.6)
            self._detonation_chain_done = True
        else:
            self.click_liberation(wait_if_cd_ready=0)
            if self.is_forte_full():
                self.perform_forte()
            elif self.resonance_available():
                self.click_resonance(time_out=.5)
            self.continues_normal_attack(.4, until_con_full=True)
        return self.switch_next_char()

    def do_fast_support(self):
        self.check_f_on_switch = True
        if self.has_intro:
            self.record_support_buff()
            self.click_echo(time_out=0)
            return self.switch_next_char()

        if self.flying() and not self.liberation_available() and not self.resonance_available():
            self.wait_down()
        self.click_echo(time_out=0)
        if self.click_liberation():
            self.record_support_buff()
            return self.switch_next_char()

        self.click_resonance(time_out=0.5)
        return self.switch_next_char()

    def record_support_buff(self):
        """Track the buff granted by Chisa's Intro Skill or Resonance Liberation."""
        self.last_buff_time = time.time()

    def switch_out(self, con_full=False):
        support_buff_time = self.last_buff_time
        super().switch_out(con_full=con_full)
        if not self.is_dps_config():
            self.last_buff_time = support_buff_time

    def do_dps_perform(self):
        timeout = 2.5
        self.check_f_on_switch = True
        if self.has_intro:
            self.continues_normal_attack(0.8)
            timeout = 2.3
        if self.flying() and not self.liberation_available() and not self.resonance_available():
            self.wait_down()
        self.click_echo()
        start = time.time()
        under_liber = False
        while time.time() - start < timeout:
            if time.time() - start < 0.5 and self.click_liberation():
                start = time.time()
                under_liber = True
                timeout = 10
                self.sleep(0.2)
            if time.time() - start < 0.5 and not self.is_forte_full() and self.click_resonance()[0]:
                start = time.time()
                if timeout != 10:
                    timeout = 1.7
            if (under_liber or self.is_dps_config()) and self.is_forte_full() and self.perform_forte():
                self.check_f_on_switch = False
                return self.switch_next_char()
            self.click()
            self.check_combat()
            self.task.next_frame()
        self.switch_next_char()

    def perform_forte(self):
        if self.flying():
            self.wait_down()
        self.task.send_key(self.get_resonance_key(), down_time=1.2)
        if self.is_forte_full():
            return False
        self.heavy_attack(3.5)
        return True
