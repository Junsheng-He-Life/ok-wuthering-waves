import unittest
from unittest.mock import Mock, patch
from src.combat.MaterialBossProfiles import resolve_boss_profile
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestMaterialBossProfiles(unittest.TestCase):
    def test_variants_and_ambiguous_titles_do_not_inherit_normal_policy(self):
        self.assertIsNone(resolve_boss_profile('梦魇·芬莱克'))
        self.assertIsNone(resolve_boss_profile('全息 芬莱克'))
        self.assertIsNone(resolve_boss_profile('芬莱克 赫卡忒'))
        self.assertIsNone(resolve_boss_profile('未知敌人'))

    def test_observed_fenrico_and_unknown_new_mechanics_are_distinct(self):
        profile = resolve_boss_profile('Lv.85 芬莱克·异海归途')
        self.assertEqual('fenrico', profile.key)
        self.assertTrue(profile.reactive_dodge)
        self.assertFalse(resolve_boss_profile('千傀重楼').supported)
        self.assertTrue(resolve_boss_profile('万囮牢·朽躯').supported)
        self.assertEqual('wanelao', resolve_boss_profile('Lv.90万四牢·朽躯').key)
        self.assertEqual('wanelao', resolve_boss_profile('Lv.90万@牢·朽躯').key)
        self.assertEqual('wanelao', resolve_boss_profile('孤焰酬义由万囤牢·朽躯掉落').key)
        self.assertEqual('tianyansuxin', resolve_boss_profile('Lv.90 天演溯心').key)
        self.assertIsNone(resolve_boss_profile('梦魇·万@牢·朽躯'))
        self.assertIsNone(resolve_boss_profile('全息 万四牢·朽躯'))
        self.assertIsNone(resolve_boss_profile('万四牢'))
        self.assertNotEqual(profile.acquire_seconds,
                            resolve_boss_profile('无铭探索者').acquire_seconds)

    def task(self):
        task = MaterialBossGuard()
        task.boss_profile = resolve_boss_profile('芬莱克')
        task._boss_hp_samples = {}
        task._boss_last_dodge = 0
        task._boss_unreadable_hp = 0
        task.in_team = Mock(return_value=(True, 0))
        task.mouse_up, task.send_key, task.log_info = Mock(), Mock(), Mock()
        return task

    def test_burst_damage_reacts_once_and_does_not_compare_different_slots(self):
        task = self.task()
        task.read_current_hp = Mock(side_effect=[(10000,10000), (8000,10000), (7000,10000)])
        with patch('src.combat.MaterialBossGuard.time.monotonic', side_effect=[10, 11, 12]):
            task.check_material_boss_health()
            task.check_material_boss_health()
            task.in_team.return_value = (True, 1)
            task.check_material_boss_health()
        task.send_key.assert_called_once_with('shift', down_time=.08)
        self.assertTrue(task.held_attack_interrupted)

    def test_death_always_recovers_before_dodge(self):
        task = self.task()
        task.read_current_hp = Mock(return_value=(0, 18664))
        with self.assertRaises(DomainBattleFailed):
            task.check_material_boss_health()
        task.send_key.assert_not_called()

    def test_weekly_preflight_rejects_before_any_game_input(self):
        from src.task.TeamMaterialEntry import TeamMaterialEntry
        task = TeamMaterialEntry()
        task.plan_job = {'kind': '周本', 'target': '穗穗'}
        with self.assertRaisesRegex(RuntimeError, '进场前停止'):
            task.preflight_material_job()
        task.plan_job = {'kind': '突破'}
        task.expected_target = '穗穗'
        task.material_target_matches = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, '补充储备前'):
            task.preflight_material_job()
