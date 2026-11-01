"""Interrupted actions and injury exclusions must not decay into unsafe input."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.BaseChar import BaseChar
from src.combat.MaterialBossHealing import MaterialBossHealing
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.task.BaseCombatTask import BaseCombatTask


class TestCombatProtection(unittest.TestCase):
    def test_interrupted_sleep_restores_guard_and_nested_state(self):
        for previous in (False, True):
            task = SimpleNamespace(skip_combat_check=previous,
                sleep=Mock(side_effect=RuntimeError('interrupt')))
            char = SimpleNamespace(task=task)
            with self.subTest(previous=previous), self.assertRaises(RuntimeError):
                BaseChar.sleep(char, .2, check_combat=False)
            self.assertIs(task.skip_combat_check, previous)

    def test_interrupted_perform_releases_animation_hint(self):
        task = SimpleNamespace(in_liberation=False)
        def interrupted():
            task.in_liberation = True
            raise RuntimeError('health rescue')
        char = SimpleNamespace(task=task, do_perform=interrupted)
        with self.assertRaises(RuntimeError):
            BaseChar.perform(char)
        self.assertFalse(task.in_liberation)

    def test_injury_cannot_expire_into_preferred_rotation(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = [BaseChar(task, i) for i in range(3)]
        current, injured, healthy = task.chars
        task.preferred_switch_target = Mock(side_effect=lambda _, candidates, intro: candidates[0])
        MaterialBossHealing.quarantine_injured(task, injured)
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=time.monotonic()+3600):
            self.assertIs(healthy, task._choose_switch_target(current, True))
        self.assertNotIn(injured, task.preferred_switch_target.call_args.args[1])

    def test_only_verified_healthy_numeric_sample_clears_injury(self):
        task = MaterialBossHealing()
        char = SimpleNamespace()
        task.quarantine_injured(char)
        task.observe_recovery_health(char, (6603, 18410))
        self.assertTrue(char.recovery_needs_health)
        self.assertEqual(float('inf'), char.recovery_until)
        task.observe_recovery_health(char, (14000, 18410))
        self.assertFalse(char.recovery_needs_health)
        self.assertEqual(0, char.recovery_until)

    def test_visible_hud_still_checks_health_during_animation_hint(self):
        task = MaterialBossGuard()
        task.in_liberation = True
        task.in_team = Mock(return_value=(True, 0))
        task.check_boss_acquire_deadline = Mock()
        task.check_material_boss_health = Mock()
        task.guard_echo_target = Mock()
        task._boss_guard_at = 0
        task.guard_material_boss()
        task.check_material_boss_health.assert_called_once()
        task.guard_echo_target.assert_not_called()

    def test_hidden_cinematic_keeps_health_grace(self):
        task = MaterialBossGuard()
        task.in_liberation = True
        task.in_team = Mock(return_value=(False, -1))
        task.check_boss_acquire_deadline = Mock()
        task.check_material_boss_health = Mock()
        task.guard_material_boss()
        task.check_material_boss_health.assert_not_called()
