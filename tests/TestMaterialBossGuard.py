import unittest
from unittest.mock import Mock, patch

from src.combat.MaterialBossGuard import MaterialBossGuard
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestMaterialBossGuard(unittest.TestCase):
    def make_task(self):
        task = MaterialBossGuard()
        for name in ('mouse_up', 'next_frame', 'middle_click', 'sleep', 'send_key', 'log_info'):
            setattr(task, name, Mock())
        task.in_team = Mock(return_value=(True, 0))
        task.check_health_bar = Mock(return_value=True)
        task.boss_target_locked = Mock(return_value=False)
        task._boss_unreadable_hp = 0
        task.read_current_hp = Mock(return_value=(10000, 10000))
        return task

    def test_health_bar_alone_never_accepts_target(self):
        task = self.make_task()
        with self.assertRaises(DomainBattleFailed):
            task.acquire_material_boss()
        self.assertEqual(12, task.send_key.call_count)
        self.assertTrue(task.held_attack_interrupted)

    def test_no_movement_after_hud_loss(self):
        task = self.make_task()
        task.in_team.return_value = (False, -1)
        with patch('src.combat.MaterialBossGuard.time.monotonic', side_effect=[0,1,2,9]):
            with self.assertRaises(DomainBattleFailed):
                task.acquire_material_boss()
        task.send_key.assert_not_called()

    def test_lock_stops_approach_without_toggling_it_off(self):
        task = self.make_task()
        task.boss_target_locked.return_value = True
        task.acquire_material_boss()
        task.middle_click.assert_not_called()
        task.send_key.assert_not_called()

    def test_low_health_exits_before_death(self):
        task = self.make_task()
        task.read_current_hp = Mock(return_value=(3900, 10000))
        with self.assertRaisesRegex(DomainBattleFailed, '40%'):
            task.check_material_boss_health()

    def test_unreadable_health_has_bounded_grace(self):
        task = self.make_task()
        task.read_current_hp = Mock(return_value=None)
        task.check_health_bar.return_value = False
        task.check_material_boss_health()
        task.check_material_boss_health()
        with self.assertRaises(DomainBattleFailed):
            task.check_material_boss_health()

    def test_obscured_player_hp_does_not_end_visible_boss_fight(self):
        task = self.make_task()
        task.read_current_hp = Mock(return_value=None)
        for _ in range(5):
            task.check_material_boss_health()
        self.assertEqual(5, task._boss_unreadable_hp)
        task.send_key.assert_not_called()

    def test_persistent_target_loss_reacquires(self):
        task = self.make_task()
        task._plan_boss = True
        task._boss_guard_at = 0
        task._boss_target_missing_at = None
        task.read_current_hp = Mock(return_value=(10000, 10000))
        task.acquire_material_boss = Mock()
        with patch('src.combat.MaterialBossGuard.time.monotonic', side_effect=[10, 13, 16]):
            for _ in range(3):
                task.guard_material_boss()
        task.acquire_material_boss.assert_called_once()

    def test_acquisition_sleep_checks_do_not_reenter_guard(self):
        task = self.make_task()
        task._plan_boss = True
        task.sleep.side_effect = lambda _: task.guard_material_boss()
        with self.assertRaises(DomainBattleFailed):
            task.acquire_material_boss()
        self.assertEqual(12, task.read_current_hp.call_count)
        self.assertFalse(task._boss_acquiring)

    def test_acquisition_checks_health_before_any_movement(self):
        task = self.make_task()
        task.read_current_hp.return_value = (1000, 10000)
        with self.assertRaises(DomainBattleFailed):
            task.acquire_material_boss()
        task.send_key.assert_not_called()
        task.middle_click.assert_not_called()

    def test_acquisition_timeout_enforced_by_sleep_hook(self):
        task = self.make_task()
        task._boss_acquiring = True
        task._boss_acquire_deadline = 8
        with patch('src.combat.MaterialBossGuard.time.monotonic', return_value=9):
            with self.assertRaisesRegex(DomainBattleFailed, '8 秒'):
                task.guard_material_boss()


    def test_transition_wait_does_not_exhaust_movement_attempts(self):
        task = self.make_task()
        task.check_health_bar = Mock(side_effect=[False]*15+[True])
        task.boss_target_locked.return_value = True
        task.acquire_material_boss()
        self.assertEqual(15,task.sleep.call_count)
        task.send_key.assert_not_called()

    def test_reward_ends_acquisition_without_movement(self):
        task = self.make_task()
        task.find_treasure_icon = Mock(return_value=True)
        task.acquire_material_boss()
        self.assertTrue(task._battle_end_seen)
        task.send_key.assert_not_called()
