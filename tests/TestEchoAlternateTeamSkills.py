"""Synthetic casts exercise alternate-team state without input or capture."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Changli import Changli
from src.char.Encore import Encore
from src.combat.EchoCombatPolicy import EchoCombatPolicy
from src.combat.MaterialBossHealing import BossHealRequested


class TestEchoAlternateTeamSkills(unittest.TestCase):
    def setUp(self):
        self.now = 100.

    def advance(self, duration):
        self.now += duration

    def character(self, cls, echo=True):
        char = cls.__new__(cls)
        char.task = SimpleNamespace(
            allow_opportunistic_skills=lambda: echo,
            use_bounded_liberation_retry=lambda: True,
            use_liberation=True, _verified_battle=True, _plan_boss=False,
            in_liberation=False, result={},
            next_frame=Mock(side_effect=lambda: self.advance(.4)),
            in_team=Mock(return_value=(True, 0, 3)),
            raise_not_in_combat=Mock(side_effect=RuntimeError('legacy timeout')))
        char.confidence = .99
        char.char_name = 'char_encore' if cls is Encore else 'char_changli'
        char.logger = Mock()
        char.has_cd = Mock(return_value=False)
        char.liberation_available = Mock(return_value=True)
        char.send_liberation_key = Mock()
        char.check_combat = Mock()
        char.add_freeze_duration = Mock()
        char.is_mouse_forte_full = Mock(return_value=True)
        char.heavy_attack = Mock()
        return char

    def invoke(self, action):
        # Python modules share the same time module; both character and base
        # skill code observe this clock, advanced by synthetic capture frames.
        with patch('time.time', side_effect=lambda: self.now), \
                patch('time.monotonic', side_effect=lambda: self.now):
            return action()

    def guarded_cast(self, char):
        char.liberation_available.side_effect = lambda: not char.has_cd.return_value

        def guard():
            if char.send_liberation_key.called:
                began = self.now
                self.advance(3.1)
                char.task.last_guarded_hud_gap = (began, self.now)
                char.has_cd.return_value = True

        char.check_combat.side_effect = guard

    def test_encore_opportunistic_confirmed_r_starts_enhanced_window(self):
        char = self.character(Encore)
        char.liberation_time = 0
        char.is_e_forte_full = Mock(return_value=False)
        self.guarded_cast(char)
        task = char.task
        task.check_combat = Mock()
        task.get_current_char = Mock(return_value=char)
        task.mouse_up = Mock()
        self.assertTrue(self.invoke(lambda: EchoCombatPolicy.use_ready_combat_skill(task)))
        self.assertEqual(self.now, char.liberation_time)
        self.assertEqual(char.last_liberation, char.liberation_time)
        char.send_liberation_key.assert_called_once()

    def test_encore_failed_opportunistic_r_does_not_start_enhanced_window(self):
        char = self.character(Encore)
        char.liberation_time = 12.
        self.assertFalse(self.invoke(char.click_liberation))
        self.assertEqual(12., char.liberation_time)

    def test_encore_non_echo_keeps_own_rotation_clock(self):
        char = self.character(Encore, echo=False)
        char.liberation_time = 12.
        self.invoke(char.record_liberation_use)
        self.assertEqual(100., char.last_liberation)
        self.assertEqual(12., char.liberation_time)

    def test_changli_stale_icon_is_bounded_and_leaves_attack_window(self):
        char = self.character(Changli)
        self.assertFalse(self.invoke(char.liberation_and_heavy))
        self.assertLessEqual(self.now - 100, 1.6 + 1e-8)
        self.assertGreaterEqual(char.check_combat.call_count, 2)
        presses = char.send_liberation_key.call_count
        self.advance(1)
        self.assertFalse(self.invoke(char.should_try_liberation))
        self.assertFalse(self.invoke(char.liberation_and_heavy))
        self.assertEqual(presses, char.send_liberation_key.call_count)
        char.task.raise_not_in_combat.assert_not_called()

    def test_changli_guard_can_interrupt_before_r_input(self):
        char = self.character(Changli)
        request = BossHealRequested(0, (2000, 10000))
        char.check_combat.side_effect = request
        with self.assertRaises(BossHealRequested):
            self.invoke(char.liberation_and_heavy)
        char.send_liberation_key.assert_not_called()

    def test_changli_existing_cooldown_prevents_retry(self):
        char = self.character(Changli)
        char.has_cd.return_value = True
        self.assertFalse(self.invoke(char.liberation_and_heavy))
        char.send_liberation_key.assert_not_called()

    def test_changli_guarded_real_cast_still_uses_full_forte(self):
        char = self.character(Changli)
        self.guarded_cast(char)
        self.assertTrue(self.invoke(char.liberation_and_heavy))
        char.send_liberation_key.assert_called_once()
        char.heavy_attack.assert_called_once()
        self.assertFalse(char.task.in_liberation)

    def test_changli_orange_probe_remains_single_and_bounded(self):
        char = self.character(Changli)
        char.liberation_available.return_value = False
        char.task.wait_until = Mock(return_value=False)
        self.assertFalse(self.invoke(char.liberation_and_heavy))
        char.send_liberation_key.assert_called_once()
        self.assertEqual(.4, char.task.wait_until.call_args.kwargs['time_out'])
        self.assertFalse(self.invoke(char.should_try_liberation))

    def test_changli_non_echo_keeps_legacy_timeout(self):
        char = self.character(Changli, echo=False)
        char.task.next_frame.side_effect = lambda: self.advance(3)
        with self.assertRaisesRegex(RuntimeError, 'legacy timeout'):
            self.invoke(char.liberation_and_heavy)
        self.assertGreater(self.now - 100, 5)
        char.check_combat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
