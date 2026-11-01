import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.combat.DetonationTeam import DetonationTeam, ORDER


class Fallback:
    def preferred_switch_target(self, *args):
        return 'fallback'


class Task(DetonationTeam, Fallback):
    pass


class TestDetonationTeam(unittest.TestCase):
    def task(self):
        task = Task()
        task._verified_battle = True
        task.chars = [SimpleNamespace(char_name=name, confidence=.99,
                                     continues_normal_attack=Mock())
                      for name in reversed(ORDER)]
        return task

    def test_live_names_determine_cycle_independent_of_slot(self):
        task = self.task()
        for char in task.chars:
            expected = ORDER[(ORDER.index(char.char_name) + 1) % 3]
            for intro in (False, True):
                target = task.preferred_switch_target(char, task.chars, intro)
                self.assertEqual(expected, target.char_name)

    def test_different_or_unrecognized_team_keeps_generic_scheduler(self):
        task = self.task()
        task.chars[2].confidence = .5
        self.assertEqual('fallback', task.preferred_switch_target(task.chars[0], task.chars, True))
        task.chars[2].confidence = .99
        task.chars[2].char_name = 'char_suisui'
        self.assertFalse(task.detonation_team_active())

    def test_wounded_healer_is_skipped_during_recovery(self):
        task = self.task()
        chisa = next(c for c in task.chars if c.char_name == 'char_chisa')
        aemeath = next(c for c in task.chars if c.char_name == 'char_aemeath')
        chisa.recovery_until = time.monotonic() + 30
        target = task.preferred_switch_target(aemeath, task.chars, True)
        self.assertEqual('char_denia', target.char_name)

    def test_opening_normals_then_chisa_before_damage_rotation(self):
        task = self.task()
        task.get_current_char = Mock(return_value=task.chars[0])
        task.healing_switch = task.log_info = Mock()
        task.prepare_team_rotation()
        task.chars[0].continues_normal_attack.assert_called_once_with(4)
        task.healing_switch.assert_any_call(task.chars[2])

    def test_material_healer_does_not_wait_24_seconds_for_concerto(self):
        task = self.task()
        chisa = task.chars[2]
        chisa.last_switch_in_time = task.combat_start = 100
        task.get_current_char = Mock(return_value=chisa)
        with patch('src.combat.DetonationTeam.time.time', return_value=107):
            self.assertTrue(task.wait_for_full_con_before_switch())
            chisa._detonation_chain_done = True
            self.assertFalse(task.wait_for_full_con_before_switch())
        chisa._detonation_chain_done = False
        with patch('src.combat.DetonationTeam.time.time', return_value=109):
            self.assertFalse(task.wait_for_full_con_before_switch())
        self.assertTrue(task.use_bounded_liberation_retry())
        task._verified_battle = False
        self.assertFalse(task.use_bounded_liberation_retry())
