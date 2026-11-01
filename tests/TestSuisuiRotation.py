import unittest
from unittest.mock import Mock
from src.char.Suisui import Suisui


class TestSuisuiRotation(unittest.TestCase):
    def character(self):
        char = Suisui.__new__(Suisui)
        char.task = Mock()
        char.logger = Mock()
        char.should_heavy = False
        char.has_intro = False
        char.time_elapsed_accounting_for_freeze = Mock(return_value=0)
        char.is_con_full = Mock(return_value=True)
        char.click = Mock()
        char.cycle_start = Mock()
        char.cycle_sleep = Mock()
        char.try_e = Mock(return_value=False)
        char.forte2_available = Mock(return_value=True)
        return char

    def test_ready_liberation_precedes_intro_heavy(self):
        char = self.character()
        events = []
        char.should_heavy = char.has_intro = True
        char.click_liberation = Mock(side_effect=lambda **kw: events.append('R') or True)
        char.heavy_attack = Mock(side_effect=lambda *a: events.append('heavy'))
        char.click_resonance = Mock()
        char.forte3_available = Mock(return_value=True)
        char.perform_forte3_rotation()
        self.assertEqual(['R', 'heavy'], events)
        char.click.assert_not_called()

    def test_liberation_becomes_ready_during_enhanced_chain(self):
        char = self.character()
        events = []
        ready = iter([False, False, True])
        char.click_liberation = Mock(side_effect=lambda **kw: events.append('R') or next(ready))
        char.click = Mock(side_effect=lambda **kw: events.append('attack'))
        char.forte3_available = Mock(side_effect=[False, True, True])
        char.perform_forte3_rotation()
        self.assertEqual(['R', 'R', 'attack', 'R'], events)
