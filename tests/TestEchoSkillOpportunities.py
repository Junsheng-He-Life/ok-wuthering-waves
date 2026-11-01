"""Exercise skill readiness changes inside existing character rotations."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Phrolova import Phrolova
from src.char.Suisui import Suisui
from src.char.YangYangSp import YangYangSp


class TestEchoSkillOpportunities(unittest.TestCase):
    def test_xuanling_persistent_e_gets_backoff_and_fresh_r_opportunity(self):
        char = YangYangSp.__new__(YangYangSp)
        events = []
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: True,
            mouse_down=Mock(side_effect=lambda: events.append('hold')),
            mouse_up=Mock(side_effect=lambda: events.append('release')),
            next_frame=Mock(side_effect=lambda: events.append('fresh')))
        char.has_intro = False
        char.logger = Mock()
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 0, 0, 20])
        char.resonance_available = Mock(return_value=True)
        char.liberation_available = Mock(return_value=True)
        char.click_resonance = Mock(side_effect=lambda **kw: (
            events.append('E') or False, 0, False))
        char.click_liberation = Mock(side_effect=lambda **kw: events.append('R') or False)
        char.sleep = char.check_combat = char.switch_next_char = Mock()

        with patch('src.char.YangYangSp.time.time', side_effect=[1, 1, 1.1, 1.4]), \
                patch('src.char.YangYangSp.time.monotonic', return_value=10):
            char.do_perform()

        char.click_resonance.assert_called_once_with(send_click=False, time_out=1)
        self.assertEqual(2, char.click_liberation.call_count)
        e_index = events.index('E')
        self.assertEqual('release', events[e_index - 1])
        self.assertEqual(['fresh', 'R'], events[e_index + 1:e_index + 3])
        self.assertEqual('release', events[-1])

    def phrolova(self, enabled):
        char = Phrolova.__new__(Phrolova)
        events = []
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: enabled,
            next_frame=Mock(side_effect=lambda: events.append('fresh')),
            wait_until=Mock(), click=Mock())
        char.has_intro = char.res_ready = False
        char.flying = char.liberation_available = char.heavy_and_liber = Mock(return_value=False)
        char.resonance_available = Mock(side_effect=[False, True])
        char.click_resonance = Mock(side_effect=lambda **kw: (
            events.append('E') or True, 0, False))
        char.click_echo = Mock(return_value=True)
        char.continues_normal_attack = char.check_combat = Mock()
        char.switch_next_char = Mock(side_effect=lambda: events.append('switch'))
        return char, events

    def test_phrolova_uses_newly_ready_e_before_leaving_without_cantarella(self):
        char, events = self.phrolova(True)
        with patch('src.char.Phrolova.time.time', side_effect=[0, .5, 1.1, 5]):
            char.do_perform()
        char.click_resonance.assert_called_once_with(time_out=1)
        self.assertFalse(char.res_ready)
        self.assertEqual(['E', 'fresh', 'fresh', 'switch'], events)

    def test_phrolova_other_tasks_keep_saved_e_rotation(self):
        char, events = self.phrolova(False)
        with patch('src.char.Phrolova.time.time', side_effect=[0, .5, 1.1]):
            char.do_perform()
        char.click_resonance.assert_not_called()
        self.assertTrue(char.res_ready)
        self.assertEqual(['switch'], events)

    def suisui(self, enabled):
        char = Suisui.__new__(Suisui)
        events = []
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: enabled,
            next_frame=Mock(side_effect=lambda: events.append('fresh')))
        char.logger = Mock()
        char.should_heavy = False
        char.click_liberation = Mock(return_value=True)
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 0, 9])
        char.forte3_available = Mock(return_value=True)
        char.is_con_full = Mock(return_value=False)
        char.try_e = Mock(side_effect=lambda: events.append('E') or True)
        char.click = Mock(side_effect=lambda **kw: events.append('attack'))
        return char, events

    def test_suisui_checks_enhanced_e_during_concerto_fill(self):
        char, events = self.suisui(True)
        char.perform_forte3_rotation()
        self.assertEqual(['E', 'fresh', 'attack'], events)
        char.try_e.assert_called_once()

    def test_suisui_other_tasks_keep_original_concerto_fill(self):
        char, events = self.suisui(False)
        char.perform_forte3_rotation()
        self.assertEqual(['attack'], events)
        char.try_e.assert_not_called()


if __name__ == '__main__':
    unittest.main()
