"""Synthetic Cartethyia E observations; no game backend is constructed."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Cartethyia import Cartethyia
from src.combat.MaterialBossHealing import BossHealRequested


class TestCartethyiaEchoGuards(unittest.TestCase):
    def setUp(self):
        self.now = 100.

    def advance(self):
        self.now += .5

    def character(self, echo=True, fill=0):
        char = Cartethyia.__new__(Cartethyia)
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: echo,
            next_frame=Mock(side_effect=self.advance), in_liberation=False)
        char.logger = Mock()
        char.has_cd = Mock(return_value=False)
        char.current_resonance = Mock(return_value=fill)
        char.resonance_available = Mock(return_value=True)
        char.send_resonance_key = Mock()
        char.record_resonance_use = Mock()
        char.try_lib_big = Mock(return_value=False)
        char.check_combat = Mock()
        char.click = Mock(side_effect=self.advance)
        char.res_time = -1
        return char

    def invoke(self, action):
        with patch('time.time', side_effect=lambda: self.now), \
                patch('time.monotonic', side_effect=lambda: self.now):
            return action()

    def test_ready_but_zero_fill_expires_without_a_first_e_press(self):
        char = self.character()
        self.assertFalse(self.invoke(char.click_resonance_with_lib_big))
        self.assertEqual(char.ECHO_RESONANCE_RETRY_SECONDS, self.now - 100)
        char.send_resonance_key.assert_not_called()
        char.record_resonance_use.assert_not_called()
        self.assertGreater(char.check_combat.call_count, 0)

    def test_persistent_ready_after_e_yields_but_keeps_use_timestamp(self):
        char = self.character(fill=.5)
        self.assertFalse(self.invoke(char.click_resonance_with_lib_big))
        self.assertEqual(char.ECHO_RESONANCE_RETRY_SECONDS, self.now - 100)
        self.assertGreater(char.send_resonance_key.call_count, 0)
        char.record_resonance_use.assert_called_once()
        self.assertEqual(self.now, char.res_time)

    def test_observed_early_e_completion_keeps_success(self):
        char = self.character(fill=.5)
        char.resonance_available.side_effect = lambda: self.now < 100.5
        self.assertTrue(self.invoke(char.click_resonance_with_lib_big))
        char.send_resonance_key.assert_called_once()
        char.record_resonance_use.assert_called_once()

    def test_zero_fill_timeout_reaches_normal_attacks_and_switch(self):
        char = self.character()
        char.has_intro = False
        char.is_small = Mock(return_value=False)
        char.click_echo = Mock()
        char.fleurdelys_n4_duration = Mock(return_value=1)
        char.click_with_interval = Mock()
        char.switch_next_char = Mock()
        self.invoke(char.do_perform)
        self.assertGreater(char.click_with_interval.call_count, 0)
        char.switch_next_char.assert_called_once()
        self.assertLessEqual(self.now - 100, char.ECHO_RESONANCE_RETRY_SECONDS + 1)

    def test_health_rescue_propagates_before_any_e_input(self):
        char = self.character(fill=.5)
        char.check_combat.side_effect = BossHealRequested(0, (3000, 10000))
        with self.assertRaises(BossHealRequested):
            self.invoke(char.click_resonance_with_lib_big)
        char.send_resonance_key.assert_not_called()
        self.assertFalse(char.task.in_liberation)

    def test_cooldown_skips_retry_and_input(self):
        char = self.character()
        char.has_cd.return_value = True
        self.assertFalse(self.invoke(char.click_resonance_with_lib_big))
        char.task.next_frame.assert_not_called()
        char.send_resonance_key.assert_not_called()

    def test_non_echo_preserves_legacy_zero_fill_behavior(self):
        char = self.character(echo=False)

        def stop_legacy_loop():
            if self.now >= 104:
                raise RuntimeError('test stops legacy loop')

        char.check_combat.side_effect = stop_legacy_loop
        with self.assertRaisesRegex(RuntimeError, 'test stops legacy loop'):
            self.invoke(char.click_resonance_with_lib_big)
        self.assertGreater(self.now - 100, char.ECHO_RESONANCE_RETRY_SECONDS)
        char.record_resonance_use.assert_not_called()


if __name__ == '__main__':
    unittest.main()
