"""Role-selection regressions from the Changli/Encore/Verina Echo trial."""
import unittest
from unittest.mock import Mock, patch

from src.char.BaseChar import BaseChar, CharType, SwitchPriority
from src.combat.DetonationTeam import DetonationTeam
from src.combat.XuanlingTeam import XuanlingTeam
from src.task.BaseCombatTask import BaseCombatTask


class CustomTeamsTask(DetonationTeam, XuanlingTeam, BaseCombatTask):
    pass


class TestEchoIntroSupport(unittest.TestCase):
    def task(self, task_cls=BaseCombatTask):
        task = task_cls.__new__(task_cls)
        task._verified_battle = True
        task.allow_opportunistic_skills = lambda: True
        task.chars = [BaseChar(task, i, char_type=role, confidence=.99)
                      for i, role in enumerate((CharType.MAIN_DPS,
                                               CharType.MAIN_DPS, CharType.HEALER))]
        for char in task.chars:
            char.has_buff = Mock(return_value=False)
        return task, task.chars

    def test_expired_healer_interrupts_two_main_dps_intro_loop(self):
        task, (current, second_dps, healer) = self.task()
        self.assertIs(healer, task._choose_switch_target(current, True))
        self.assertIs(healer, task._choose_switch_target(second_dps, True))

    def test_active_healer_buff_keeps_intro_on_other_main_dps(self):
        task, (current, second_dps, healer) = self.task()
        healer.has_buff.return_value = True
        self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_recovering_healer_remains_excluded(self):
        task, (current, second_dps, healer) = self.task()
        healer.recovery_until = 130
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=100):
            self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_recovery_expiry_makes_expired_healer_eligible(self):
        task, (current, _, healer) = self.task()
        healer.recovery_until = 130
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=130):
            self.assertIs(healer, task._choose_switch_target(current, True))

    def test_character_must_priority_keeps_its_short_skill_window(self):
        task, (current, second_dps, _) = self.task()
        second_dps.get_switch_priority = Mock(return_value=SwitchPriority.MUST)
        self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_character_no_priority_still_blocks_healer(self):
        task, (current, second_dps, healer) = self.task()
        healer.get_switch_priority = Mock(return_value=SwitchPriority.NO)
        self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_non_echo_keeps_existing_intro_priority(self):
        task, (current, second_dps, _) = self.task()
        task.allow_opportunistic_skills = lambda: False
        self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_unverified_or_low_confidence_team_does_not_use_new_rule(self):
        task, (current, second_dps, healer) = self.task()
        task._verified_battle = False
        self.assertIs(second_dps, task._choose_switch_target(current, True))
        task._verified_battle = True
        healer.confidence = .79
        self.assertIs(second_dps, task._choose_switch_target(current, True))

    def test_single_main_dps_retains_existing_intro_recipient_priority(self):
        task, (current, support, healer) = self.task()
        support.set_char_type(CharType.SUB_DPS)
        self.assertIs(support, task._choose_switch_target(current, True))

    def test_detonation_and_xuanling_custom_chains_precede_expired_buff(self):
        for names in [('char_denia', 'char_aemeath', 'char_chisa'),
                      ('char_phrolova', 'yangyang_sp', 'char_suisui')]:
            with self.subTest(names=names):
                task, (current, desired, healer) = self.task(CustomTeamsTask)
                for char, name in zip(task.chars, names):
                    char.char_name = name
                self.assertIs(desired, task._choose_switch_target(current, True))


if __name__ == '__main__':
    unittest.main()
