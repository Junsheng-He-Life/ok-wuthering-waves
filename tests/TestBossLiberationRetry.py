import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.BaseChar import BaseChar
from src.combat.MaterialBossHealing import BossHealRequested, MaterialBossHealing


class TestBossLiberationRetry(unittest.TestCase):
    def character(self):
        return SimpleNamespace(
            task=SimpleNamespace(use_liberation=True, _verified_battle=True,
                                 _plan_boss=True, in_liberation=False,
                                 next_frame=Mock(), raise_not_in_combat=Mock()),
            has_cd=Mock(return_value=False), logger=Mock(),
            liberation_available=Mock(return_value=True),
            send_liberation_key=Mock(), alert_skill_failed=Mock())

    def test_stale_ready_icon_returns_to_attacks_instead_of_long_retry(self):
        char = self.character()
        with patch('src.char.BaseChar.time.time', side_effect=[0, .2, .3, 1.3]):
            self.assertFalse(BaseChar.click_liberation(char))
        char.send_liberation_key.assert_called_once()
        char.task.raise_not_in_combat.assert_not_called()
        char.alert_skill_failed.assert_not_called()

    def test_cooldown_after_rescue_prevents_another_cast_attempt(self):
        char = self.character()
        char.has_cd.return_value = True
        self.assertFalse(BaseChar.click_liberation(char))
        char.liberation_available.assert_not_called()
        char.send_liberation_key.assert_not_called()


class TestSupervisedLiberationRetry(unittest.TestCase):
    """Use a synthetic advancing clock; no framework or native input exists."""

    character = TestBossLiberationRetry.character

    def supervised_character(self):
        char = self.character()
        char.char_name = 'char_chisa'
        char.task._plan_boss = False
        char.task.result = {}
        char.task.use_bounded_liberation_retry = Mock(return_value=True)
        char.check_combat = Mock()
        char.record_liberation_use = Mock()
        char.add_freeze_duration = Mock()
        self.now = 100.
        char.task.next_frame.side_effect = lambda: self.advance(.4)
        return char

    def advance(self, duration):
        self.now += duration

    def invoke(self, char, **kwargs):
        with patch('src.char.BaseChar.time.time', side_effect=lambda: self.now), \
                patch('src.char.BaseChar.time.monotonic', side_effect=lambda: self.now):
            return BaseChar.click_liberation(char, **kwargs)

    def test_non_boss_opt_in_skips_visible_cooldown_without_pressing_r(self):
        char = self.supervised_character()
        char.has_cd.return_value = True
        self.assertFalse(self.invoke(char))
        char.send_liberation_key.assert_not_called()
        char.liberation_available.assert_not_called()
        metrics = char.task.result['bounded_liberation_retry']
        self.assertEqual(metrics['last_outcome'], 'cooldown')
        self.assertEqual(metrics['cooldown_skips'], 1)
        self.assertEqual(metrics['last_elapsed_seconds'], 0)

    def test_non_boss_opt_in_caps_retry_and_records_measured_duration(self):
        char = self.supervised_character()
        self.assertFalse(self.invoke(char))
        self.assertLessEqual(self.now - 100, 1.6)
        self.assertGreaterEqual(char.check_combat.call_count, 2)
        char.task.raise_not_in_combat.assert_not_called()
        char.alert_skill_failed.assert_not_called()
        char.record_liberation_use.assert_not_called()
        metrics = char.task.result['bounded_liberation_retry']
        self.assertEqual(metrics['last_outcome'], 'retry_timeout')
        self.assertEqual(metrics['retry_timeouts'], 1)
        self.assertAlmostEqual(metrics['last_elapsed_seconds'], self.now - 100)
        self.assertEqual(metrics['guard_checks'], char.check_combat.call_count)
        self.assertEqual(metrics['press_attempts'], char.send_liberation_key.call_count)

    def test_non_opted_in_world_task_keeps_original_behavior(self):
        char = self.supervised_character()
        del char.task.use_bounded_liberation_retry
        char.task.raise_not_in_combat.side_effect = RuntimeError('original timeout')
        char.task.next_frame.side_effect = lambda: self.advance(3)
        with self.assertRaisesRegex(RuntimeError, 'original timeout'):
            self.invoke(char)
        self.assertGreater(self.now - 100, 15)
        char.check_combat.assert_not_called()
        self.assertNotIn('bounded_liberation_retry', char.task.result)

    def test_failed_retry_leaves_two_seconds_for_attacking(self):
        char = self.supervised_character()
        self.assertFalse(self.invoke(char))
        presses = char.send_liberation_key.call_count
        self.advance(1)
        self.assertFalse(self.invoke(char))
        self.assertEqual(char.send_liberation_key.call_count, presses)
        self.assertEqual(char.task.result['bounded_liberation_retry']['last_outcome'], 'backoff')
        self.advance(1.1)
        self.assertFalse(self.invoke(char))
        self.assertGreater(char.send_liberation_key.call_count, presses)

    def test_opt_in_alone_does_not_enable_retry_outside_verified_battle(self):
        char = self.supervised_character()
        char.task._verified_battle = False
        char.liberation_available.return_value = False
        char.has_cd.return_value = True
        self.assertFalse(self.invoke(char, wait_if_cd_ready=0))
        char.liberation_available.assert_called_once()
        char.check_combat.assert_not_called()
        self.assertNotIn('bounded_liberation_retry', char.task.result)

    def test_health_guard_interrupts_retry_before_another_press(self):
        char = self.supervised_character()
        request = BossHealRequested(2, (2000, 10000))
        char.check_combat.side_effect = request
        with self.assertRaises(BossHealRequested) as raised:
            self.invoke(char)
        self.assertIs(raised.exception, request)
        char.send_liberation_key.assert_not_called()
        self.assertEqual(char.task.result['bounded_liberation_retry']['last_outcome'], 'guard_interrupted')

    def test_existing_healing_guard_does_not_recursively_request_rescue(self):
        char = self.supervised_character()
        healing = MaterialBossHealing()
        healing._boss_healing = True
        healing._boss_heal_deadline = 150.
        healing.in_team = Mock(return_value=(True, 2, 3))
        char.check_combat.side_effect = lambda: healing.request_boss_healing((1000, 10000))
        self.assertFalse(self.invoke(char))
        self.assertEqual(char.task.result['bounded_liberation_retry']['last_outcome'], 'retry_timeout')

    def test_real_three_second_guarded_animation_remains_confirmed(self):
        char = self.supervised_character()
        char.task.wait_until = Mock(side_effect=AssertionError('guard already observed the animation'))
        char.liberation_available.side_effect = lambda: not char.has_cd.return_value
        def guard():
            if char.send_liberation_key.called:
                began = self.now
                self.advance(3.1)
                char.task.last_guarded_hud_gap = (began, self.now)
                char.has_cd.return_value = True
        char.check_combat.side_effect = guard
        self.assertTrue(self.invoke(char))
        char.send_liberation_key.assert_called_once()
        char.record_liberation_use.assert_called_once()
        self.assertGreater(self.now - 100, 3)
        metrics = char.task.result['bounded_liberation_retry']
        self.assertEqual(metrics['last_outcome'], 'confirmed_after_guarded_animation')
        self.assertNotIn('retry_timeouts', metrics)
