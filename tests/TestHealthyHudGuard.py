import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np

from src.combat.HealthyHudGuard import fresh_healthy_portrait


class TestHealthyHudGuard(unittest.TestCase):
    def task(self):
        return SimpleNamespace(_verified_battle=True, _boss_healing=False,
            boss_policy_value=lambda *_: False, _routine_numeric_due=103,
            frame=np.zeros((10, 10, 3), np.uint8), result={},
            in_team=lambda: (True, 1, 3),
            _executor=SimpleNamespace(_last_frame_time=100.,
                method=SimpleNamespace(_delivered_frame_sequence=10)))

    def test_healthy_current_slot_is_fast_but_does_not_invent_numeric_hp(self):
        task = self.task()
        with patch('src.combat.HealthyHudGuard.time.time', return_value=100), \
             patch('src.combat.HealthyHudGuard.time.monotonic', return_value=100), \
             patch('src.combat.HealthyHudGuard.portrait_health', return_value=[None, .85, .2]):
            self.assertTrue(fresh_healthy_portrait(task))
        self.assertIsNone(task._hp_observation['parsed'])
        self.assertEqual(1, task._hp_observation['slot_at_decision'])

    def test_low_unknown_hidden_old_and_healing_all_require_numeric_reader(self):
        for case in ('low', 'unknown', 'hidden', 'old', 'healing', 'periodic', 'dodge'):
            task = self.task()
            bars = [1., 1., 1.]
            if case == 'low': bars[1] = .74
            if case == 'unknown': bars[1] = None
            if case == 'hidden': task.in_team = lambda: (False, -1, 0)
            if case == 'old': task._executor._last_frame_time = 99
            if case == 'healing': task._boss_healing = True
            if case == 'periodic': task._routine_numeric_due = 100
            if case == 'dodge': task.boss_policy_value = lambda *_: True
            with self.subTest(case=case), \
                 patch('src.combat.HealthyHudGuard.time.time', return_value=100), \
                 patch('src.combat.HealthyHudGuard.time.monotonic', return_value=100), \
                 patch('src.combat.HealthyHudGuard.portrait_health', return_value=bars):
                self.assertFalse(fresh_healthy_portrait(task))

    def test_repeated_sequence_cannot_refresh_evidence_age(self):
        task = self.task()
        with patch('src.combat.HealthyHudGuard.time.time', return_value=100), \
             patch('src.combat.HealthyHudGuard.time.monotonic', side_effect=[100, 100.6, 100.7]), \
             patch('src.combat.HealthyHudGuard.portrait_health', return_value=[1., 1., 1.]):
            self.assertTrue(fresh_healthy_portrait(task))
            self.assertFalse(fresh_healthy_portrait(task))
            task._executor.method._delivered_frame_sequence = 11
            self.assertTrue(fresh_healthy_portrait(task))

    def test_reactive_mode_fast_path_still_requires_numeric_on_damage(self):
        task = self.task()
        task.boss_policy_value = lambda *_: True
        with patch('src.combat.HealthyHudGuard.time.time', return_value=100), \
             patch('src.combat.HealthyHudGuard.time.monotonic', return_value=100), \
             patch('src.combat.HealthyHudGuard.portrait_health', side_effect=[
                 [1., 1., 1.], [1., 1., 1.], [1., .85, 1.]]):
            self.assertFalse(fresh_healthy_portrait(task))
            self.assertTrue(fresh_healthy_portrait(task))
            self.assertFalse(fresh_healthy_portrait(task))
