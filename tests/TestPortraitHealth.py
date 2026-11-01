import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
from src.combat.PortraitHealth import portrait_health
from src.combat.BossHealthReading import BossHealthReading
from src.combat.MaterialBossGuard import MaterialBossGuard


class TestPortraitHealth(unittest.TestCase):
    def test_missing_numeric_hp_requires_fresh_active_portrait(self):
        for bars, stamp, expected_stop in (([1., 1., .73], 9.8, False),
                                           ([1., 1., .73], 8., True),
                                           ([1., None, .73], 9.8, False),
                                           ([1., 1., .4], 9.8, True)):
            with self.subTest(bars=bars, stamp=stamp):
                task = MaterialBossGuard()
                task.read_boss_hp = Mock(return_value=None)
                task._boss_unreadable_hp = 2
                task._hp_observation = dict(team_verified=True, slot_at_decision=2, capture_sequence=10, monotonic=stamp, portrait_ratios=bars)
                task.in_team = Mock(return_value=(True, 2, 3))
                task.check_health_bar = Mock(return_value=False)
                task.log_info = Mock()
                task.fail_battle = Mock(side_effect=RuntimeError('stop'))
                with patch('src.combat.MaterialBossGuard.time.monotonic', return_value=10):
                    if expected_stop:
                        with self.assertRaisesRegex(RuntimeError, 'stop'):
                            task.check_material_boss_health()
                    else:
                        task.check_material_boss_health()
                        task.fail_battle.assert_not_called()

    def test_observed_three_member_bars(self):
        for name, expected in [('1790519157857288000', [.54,.86,.87]),
                               ('1790519163350399000', [.57,.86,.72])]:
            frame = np.zeros((1440,3440,3),np.uint8)
            crop = cv2.imread(str(Path(__file__).parent/'images'/f'portrait-bars-{name}.png'))
            frame[240:770,3180:3370] = crop
            actual = portrait_health(frame)
            for a,b in zip(actual,expected):
                self.assertAlmostEqual(a,b,delta=.03)
        self.assertEqual([None]*3, portrait_health(np.zeros((1440,3440,3),np.uint8)))

    def task(self, samples, sequences=(1,2)):
        t = BossHealthReading()
        t.in_team = Mock(return_value=(True,2,3))
        t.next_frame = Mock()
        t.save_battle_trigger = Mock()
        iterator = iter(zip(samples,sequences))
        def read():
            hp,seq = next(iterator)
            t._hp_observation = {'capture_sequence':seq}
            return hp
        t.read_current_hp = read
        return t

    def test_healthy_portrait_rejects_false_numeric_without_inventing_hp(self):
        t = self.task([(3549,33398)])
        with patch('src.combat.BossHealthReading.portrait_health',return_value=[.5,.8,.72]):
            hp=t.read_boss_hp()
        self.assertIsNone(hp)
        self.assertEqual(t._hp_observation['rejected'], 'numeric_portrait_disagreement')
        self.assertNotIn('approximate_portrait_hp', t._hp_observation)
        t.next_frame.assert_not_called()

    def test_critical_needs_two_new_frames_of_same_slot(self):
        for seqs, expected in [((1,2),(1000,10000)), ((1,1),None)]:
            t=self.task([(1000,10000),(1000,10000)],seqs)
            with patch('src.combat.BossHealthReading.portrait_health',return_value=[None]*3):
                self.assertEqual(expected,t.read_boss_hp())
        t=self.task([(1000,10000),(8000,10000)])
        with patch('src.combat.BossHealthReading.portrait_health',return_value=[None]*3):
            self.assertIsNone(t.read_boss_hp())

    def test_healing_does_not_disable_damage_dodge(self):
        t=MaterialBossGuard()
        t.read_boss_hp=Mock(return_value=(7000,10000))
        t.in_team=Mock(return_value=(True,2,3))
        t.boss_policy_value=Mock(return_value=True)
        t._boss_hp_samples={2:(9,.9)}
        t._boss_last_dodge=0
        t.request_boss_healing=Mock(return_value=True)
        t.mouse_up=t.send_key=t.log_info=Mock()
        with patch('src.combat.MaterialBossGuard.time.monotonic',return_value=10):
            t.check_material_boss_health()
        self.assertIn(unittest.mock.call('shift',down_time=.08), t.send_key.call_args_list)
