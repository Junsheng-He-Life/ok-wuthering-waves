"""Xin's provisional actions use simulated HUD changes and no native input."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Xin import Xin
from src.combat.MaterialBossHealing import BossHealRequested


class TestXinRotation(unittest.TestCase):
    def setUp(self):
        self.now = 100.

    def advance(self, seconds=.2):
        self.now += seconds

    def character(self):
        char = Xin.__new__(Xin)
        char.char_name, char.confidence = 'char_xin', .99
        char.logger = Mock()
        char.task = SimpleNamespace(
            _verified_battle=True, _plan_boss=False, use_liberation=True,
            use_bounded_liberation_retry=lambda: True,
            in_liberation=False, result={},
            next_frame=Mock(side_effect=self.advance), mouse_up=Mock(), mouse_down=Mock(),
            in_team=Mock(return_value=(True, 0, 3)),
            raise_not_in_combat=Mock(side_effect=RuntimeError('legacy timeout')))
        char.check_combat = Mock()
        char.wait_intro = Mock()
        char.liberation_available = Mock(return_value=False)
        char.resonance_available = Mock(return_value=False)
        char.is_mouse_forte_full = Mock(return_value=False)
        char.has_cd = Mock(return_value=False)
        char.send_liberation_key = Mock()
        char.send_resonance_key = Mock()
        char.record_resonance_use = Mock()
        char.continues_normal_attack = Mock()
        char.switch_next_char = Mock()
        char.heavy_attack = Mock(side_effect=AssertionError('unverified heavy attack'))
        char.sleep = Mock()
        return char

    def invoke(self, action):
        with patch('time.time', side_effect=lambda: self.now), \
                patch('time.monotonic', side_effect=lambda: self.now):
            return action()

    def test_unverified_identity_never_sends_input(self):
        for name, confidence in (('unknown', .99), ('char_xin', .79),
                                 ('char_xin', float('nan')), ('char_xin', True)):
            with self.subTest(name=name, confidence=confidence):
                char = self.character()
                char.char_name, char.confidence = name, confidence
                with self.assertRaisesRegex(RuntimeError, '未被可靠识别'):
                    char.do_perform()
                char.task.next_frame.assert_not_called()
                char.send_resonance_key.assert_not_called()
                char.continues_normal_attack.assert_not_called()

    def test_unready_skills_leave_short_attacks_and_switch(self):
        char = self.character()
        self.invoke(char.do_perform)
        char.send_liberation_key.assert_not_called()
        char.send_resonance_key.assert_not_called()
        char.continues_normal_attack.assert_called_once_with(.6)
        char.switch_next_char.assert_called_once()
        char.heavy_attack.assert_not_called()
        char.task.mouse_up.assert_called_once()

    def test_health_guard_interrupts_before_any_rotation_input(self):
        char = self.character()
        char.check_combat.side_effect = BossHealRequested(0, (2000, 10000))
        with self.assertRaises(BossHealRequested):
            self.invoke(char.do_perform)
        char.wait_intro.assert_not_called()
        char.send_liberation_key.assert_not_called()
        char.send_resonance_key.assert_not_called()
        char.continues_normal_attack.assert_not_called()
        char.task.mouse_up.assert_called_once()

    def test_stale_e_uses_short_budget_then_returns_to_attacks(self):
        char = self.character()
        char.resonance_available.return_value = True
        self.invoke(char.do_perform)
        self.assertGreater(char.send_resonance_key.call_count, 0)
        # Includes fresh HUD observations outside the E retry itself.
        self.assertLess(self.now - 100, 1.5)
        self.assertGreaterEqual(char.check_combat.call_count, 4)
        char.continues_normal_attack.assert_called_once_with(.6)
        char.switch_next_char.assert_called_once()

    def test_stale_r_is_bounded_and_retries_do_not_remove_attack_window(self):
        char = self.character()
        char.liberation_available.return_value = True
        self.assertFalse(self.invoke(char.click_liberation))
        self.assertLessEqual(self.now - 100, 1.4 + 1e-8)
        self.assertGreater(char.check_combat.call_count, 0)
        presses = char.send_liberation_key.call_count
        self.advance(1)
        self.assertFalse(self.invoke(char.click_liberation))
        self.assertEqual(presses, char.send_liberation_key.call_count)
        char.task.raise_not_in_combat.assert_not_called()

    def test_r_does_not_enter_legacy_loop_without_supervised_policy(self):
        for verified, policy in ((False, lambda: True), (True, lambda: False), (True, None)):
            with self.subTest(verified=verified, policy=policy):
                char = self.character()
                char.task._verified_battle = verified
                char.task.use_bounded_liberation_retry = policy
                char.liberation_available.return_value = True
                self.assertFalse(self.invoke(char.click_liberation))
                char.send_liberation_key.assert_not_called()

    def test_r_refreshes_hud_before_checking_new_e(self):
        char = self.character()
        char.liberation_available.return_value = True
        char.click_liberation = Mock(return_value=True)
        char.click_resonance = Mock(return_value=(True, .1, False))
        char.resonance_available.side_effect = lambda: char.task.next_frame.call_count >= 3
        self.invoke(char.do_perform)
        char.click_liberation.assert_called_once_with(send_click=False, wait_if_cd_ready=0)
        char.click_resonance.assert_called_once_with(send_click=False, time_out=.6)

    def test_health_guard_after_e_prevents_more_attacks(self):
        char = self.character()
        char.resonance_available.return_value = True
        char.click_resonance = Mock(return_value=(True, .1, False))
        char.check_combat.side_effect = [None, None, BossHealRequested(0, (2000, 10000))]
        with self.assertRaises(BossHealRequested):
            self.invoke(char.do_perform)
        char.continues_normal_attack.assert_not_called()
        char.switch_next_char.assert_not_called()
        char.task.mouse_up.assert_called_once()

    def test_normal_filler_retains_immediate_skill_hook(self):
        char = self.character()
        del char.continues_normal_attack
        char.task.use_ready_combat_skill = Mock(return_value=True)
        char.task.click = Mock()
        self.invoke(lambda: char.continues_normal_attack(.6))
        char.task.use_ready_combat_skill.assert_called_once()
        char.task.click.assert_not_called()

    def test_generic_full_forte_without_mouse_prompt_never_holds(self):
        char = self.character()
        char.is_forte_full = Mock(return_value=True)
        self.invoke(char.do_perform)
        char.task.mouse_down.assert_not_called()
        char.is_forte_full.assert_not_called()
        self.assertNotIn('xin_marked_heavy', char.task.result)

    def test_marked_heavy_holds_only_point_six_five_seconds_and_logs_input(self):
        char = self.character()
        char.is_mouse_forte_full.return_value = True
        char.sleep.side_effect = self.advance
        self.assertTrue(self.invoke(char.marked_heavy_attack))
        self.assertAlmostEqual(.65, self.now - 100)
        self.assertTrue(all(call.args[0] <= .1 for call in char.sleep.call_args_list))
        char.task.mouse_down.assert_called_once()
        char.task.mouse_up.assert_called_once()
        event = char.task.result['xin_marked_heavy'][0]
        self.assertEqual('released', event['status'])
        self.assertEqual(.65, event['held_seconds'])

    def test_health_guard_during_hold_releases_immediately_and_propagates(self):
        char = self.character()
        char.is_mouse_forte_full.return_value = True
        char.sleep.side_effect = self.advance
        char.check_combat.side_effect = [None, BossHealRequested(0, (2000, 10000))]
        with self.assertRaises(BossHealRequested):
            self.invoke(char.marked_heavy_attack)
        self.assertAlmostEqual(.1, self.now - 100)
        char.task.mouse_up.assert_called_once()
        self.assertEqual('interrupted', char.task.result['xin_marked_heavy'][0]['status'])

    def test_dodge_release_does_not_resume_the_hold(self):
        char = self.character()
        char.is_mouse_forte_full.return_value = True
        char.sleep.side_effect = self.advance
        def guard():
            if char.task.mouse_down.called:
                char.task.held_attack_interrupted = True
        char.check_combat.side_effect = guard
        self.assertTrue(self.invoke(char.marked_heavy_attack))
        char.task.mouse_down.assert_called_once()
        self.assertAlmostEqual(.1, self.now - 100)
        self.assertEqual('interrupted', char.task.result['xin_marked_heavy'][0]['status'])

    def test_mouse_prompt_must_survive_the_pre_input_health_refresh(self):
        char = self.character()
        char.is_mouse_forte_full.side_effect = [True, False]
        self.assertFalse(self.invoke(char.marked_heavy_attack))
        char.task.mouse_down.assert_not_called()

    def test_new_r_after_heavy_is_checked_on_fresh_released_hud(self):
        char = self.character()
        char.is_mouse_forte_full.return_value = True
        char.sleep.side_effect = self.advance
        char.liberation_available.side_effect = lambda: (
            char.task.mouse_up.called and char.task.next_frame.call_count >= 3)
        char.click_liberation = Mock(return_value=True)
        self.invoke(char.do_perform)
        char.click_liberation.assert_called_once_with(send_click=False, wait_if_cd_ready=0)
        self.assertEqual('released', char.task.result['xin_marked_heavy'][0]['status'])


if __name__ == '__main__':
    unittest.main()
