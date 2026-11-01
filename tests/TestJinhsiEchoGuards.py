"""Synthetic Jinhsi HUD transitions; no controller or capture is constructed."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Jinhsi import Jinhsi
from src.combat.MaterialBossHealing import BossHealRequested


class TestJinhsiEchoGuards(unittest.TestCase):
    def setUp(self):
        self.now = 100.

    def advance(self):
        self.now += .5

    def character(self, echo=True):
        char = Jinhsi.__new__(Jinhsi)
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: echo,
            in_liberation=False,
            in_team=Mock(return_value=(True, 0, 3)),
            next_frame=Mock(side_effect=self.advance), click=Mock())
        char.logger = Mock()
        char.incarnation = False
        char.incarnation_cd = False
        char.has_cd = Mock(return_value=False)
        char.send_resonance_key = Mock()
        char.click_liberation = Mock(return_value=False)
        char.continues_normal_attack = Mock()
        char.click_echo = Mock(return_value=True)
        char.check_combat = Mock()
        char.add_freeze_duration = Mock()
        return char

    def invoke(self, action):
        with patch('time.time', side_effect=lambda: self.now):
            return action()

    def test_missing_e_cooldown_yields_to_r_without_claiming_transformation(self):
        char = self.character()
        self.invoke(char.handle_intro)
        self.assertLessEqual(self.now - 100, 3)
        self.assertGreater(char.send_resonance_key.call_count, 0)
        char.click_liberation.assert_called_once_with(send_click=True, wait_if_cd_ready=0)
        char.continues_normal_attack.assert_called_once_with(.3)
        self.assertFalse(char.incarnation)
        self.assertFalse(char.incarnation_cd)

    def test_actual_early_e_cooldown_keeps_original_stage_transition(self):
        char = self.character()
        char.has_cd.side_effect = lambda _: self.now > 100
        self.invoke(char.handle_intro)
        self.assertTrue(char.incarnation_cd)
        self.assertFalse(char.incarnation)
        char.send_resonance_key.assert_called_once()
        char.click_liberation.assert_not_called()

    def test_delayed_cooldown_frame_is_checked_before_retry_deadline(self):
        char = self.character()
        # Capture/guard work can return the confirming frame after the input
        # budget expires. Consume it without issuing another E or losing stage.
        char.task.next_frame.side_effect = lambda: setattr(self, 'now', 103.)
        char.has_cd.side_effect = lambda _: self.now >= 103.
        self.invoke(char.handle_intro)
        char.send_resonance_key.assert_called_once()
        char.click_liberation.assert_called_once_with(send_click=True)
        self.assertTrue(char.incarnation)
        self.assertFalse(char.incarnation_cd)

    def test_visible_incarnation_hud_allows_rescue_before_input(self):
        char = self.character()
        request = BossHealRequested(0, (2500, 10000))

        def guard():
            self.assertFalse(char.task.in_liberation)
            raise request

        char.check_combat.side_effect = guard
        with self.assertRaises(BossHealRequested):
            self.invoke(char.handle_incarnation)
        char.send_resonance_key.assert_not_called()
        char.task.click.assert_not_called()
        self.assertFalse(char.task.in_liberation)

    def test_only_actual_hidden_hud_marks_cinematic(self):
        char = self.character()
        char.task.in_team.side_effect = [(True, 0, 3), (False, -1, 3),
                                        (False, -1, 3), (True, 0, 3)]
        guard_flags = []
        input_flags = []
        char.check_combat.side_effect = lambda: guard_flags.append(char.task.in_liberation)
        char.task.click.side_effect = lambda **kw: input_flags.append(char.task.in_liberation)
        char.send_resonance_key.side_effect = lambda **kw: input_flags.append(char.task.in_liberation)
        self.invoke(char.handle_incarnation)
        self.assertIn(True, guard_flags)
        self.assertIn(False, guard_flags)
        self.assertTrue(input_flags)
        self.assertFalse(any(input_flags))
        self.assertFalse(char.task.in_liberation)

    def test_exception_during_cinematic_clears_guard_suppression(self):
        char = self.character()
        char.task.in_team.return_value = (False, -1, 3)
        char.task.next_frame.side_effect = RuntimeError('capture interrupted')
        with self.assertRaisesRegex(RuntimeError, 'capture interrupted'):
            self.invoke(char.handle_incarnation)
        self.assertFalse(char.task.in_liberation)

    def test_non_echo_keeps_existing_intro_retry(self):
        char = self.character(echo=False)

        def stop_test():
            if self.now >= 104:
                raise RuntimeError('test stops legacy loop')

        char.check_combat.side_effect = stop_test
        with self.assertRaisesRegex(RuntimeError, 'test stops legacy loop'):
            self.invoke(char.handle_intro)
        char.click_liberation.assert_not_called()
        self.assertGreater(self.now - 100, char.ECHO_INTRO_RETRY_SECONDS)

    def test_non_echo_keeps_existing_incarnation_input_timing(self):
        char = self.character(echo=False)
        flags = []
        char.task.click.side_effect = lambda **kw: flags.append(char.task.in_liberation)
        char.send_resonance_key.side_effect = lambda **kw: flags.append(char.task.in_liberation)
        self.invoke(char.handle_incarnation)
        self.assertTrue(flags)
        self.assertTrue(all(flags))
        self.assertFalse(char.task.in_liberation)


if __name__ == '__main__':
    unittest.main()
