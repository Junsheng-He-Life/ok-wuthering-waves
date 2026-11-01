import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.task.VerifiedDomainCombat import VerifiedDomainCombat, NotInCombatException
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.combat.MaterialBossHealing import BossHealRequested


class TestDomainProgress(unittest.TestCase):
    def test_visible_boss_cannot_renew_hard_deadline(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        task = SimpleNamespace(_verified_battle=True, _plan_boss=True,
            _battle_deadline=100, _battle_hard_deadline=100,
            _raise_if_manual_exit_before_input=Mock(),
            material_victory_visible=Mock(return_value=False),
            in_team=Mock(return_value=(True, 0)), check_health_bar=Mock(return_value=True),
            fail_battle=Mock(side_effect=DomainBattleFailed('hard deadline')))
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=101):
            with self.assertRaisesRegex(DomainBattleFailed, 'hard deadline'):
                VerifiedDomainCombat.in_combat(task)
        self.assertEqual(100, task._battle_deadline)

    def test_victory_at_deadline_is_preserved_for_reward(self):
        task = SimpleNamespace(_verified_battle=True, _plan_boss=True,
            _battle_deadline=100, _battle_hard_deadline=100,
            _raise_if_manual_exit_before_input=Mock(),
            material_victory_visible=Mock(return_value=True), fail_battle=Mock())
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=101):
            self.assertFalse(VerifiedDomainCombat.in_combat(task))
        self.assertTrue(task._battle_end_seen)
        task.fail_battle.assert_not_called()

    def test_reacquisition_health_request_reaches_existing_healer(self):
        task = VerifiedDomainCombat()
        char = SimpleNamespace(char_name='known', confidence=.99,
                               perform=Mock(side_effect=NotInCombatException('action timeout')))
        task.chars = [char]
        task.prepare_verified_battle = Mock(return_value=False)
        task.load_chars = task.confirm_combat_entry = task.on_combat_started = Mock()
        task.domain_combat_finished = Mock()
        task._start_combat_debug_frame_recorder = task._stop_combat_debug_frame_recorder = Mock()
        task.mouse_up = task.send_key_up = task.next_frame = task.log_info = Mock()
        task.get_current_char = Mock(return_value=char)
        task.in_combat = Mock(side_effect=[True, False])
        request = BossHealRequested(0, (100, 200))
        task.resume_verified_rotation = Mock(side_effect=request)
        task.heal_material_boss = Mock()
        task.material_victory_visible = Mock(return_value=True)
        task.wait_until = Mock(side_effect=lambda callback, **kwargs: callback())
        task.fight_verified_domain()
        task.heal_material_boss.assert_called_once_with(request)

    def test_delayed_reward_marker_does_not_trigger_recovery(self):
        task = VerifiedDomainCombat()
        char = SimpleNamespace(char_name='char_aemeath', confidence=.9,
                               perform=Mock(side_effect=NotInCombatException()))
        task.chars = [char]
        task.prepare_verified_battle = Mock(return_value=False)
        task.confirm_combat_entry = Mock()
        task.load_chars = task.on_combat_started = Mock()
        task._start_combat_debug_frame_recorder = task._stop_combat_debug_frame_recorder = Mock()
        task.in_combat = Mock(return_value=True)
        task.domain_combat_finished = Mock()
        task.get_current_char = Mock(return_value=char)
        task.find_battle_reward_marker = Mock(side_effect=[False, True, True])
        task.mouse_up = task.send_key_up = task.log_info = Mock()
        task.next_frame = Mock()
        task.resume_verified_rotation = Mock(return_value=False)
        task.fail_battle = Mock(side_effect=AssertionError('unexpected recovery'))
        def wait(callback, **kwargs):
            self.assertFalse(task._in_combat)
            for _ in range(3):
                if callback():
                    return True
            return False
        task.wait_until = Mock(side_effect=wait)
        task.fight_verified_domain()
        task.fail_battle.assert_not_called()
        self.assertEqual(2, task.wait_until.call_count)

    def test_tacet_uses_five_minute_cap_without_changing_material_cap(self):
        for mode, seconds in (('tacet', 300), ('boss', 150), (None, 150)):
            with self.subTest(mode=mode):
                task = VerifiedDomainCombat()
                task.echo_mode = mode
                task.chars = [SimpleNamespace(char_name='known', confidence=.99)]
                task.prepare_verified_battle = Mock(return_value=False)
                task.load_chars = Mock()
                task.domain_combat_finished = Mock(return_value=False)
                task._start_combat_debug_frame_recorder = Mock()
                task._stop_combat_debug_frame_recorder = Mock()
                task.mouse_up = task.send_key_up = Mock()
                task.confirm_combat_entry = Mock(side_effect=RuntimeError('stop before input'))
                with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=100):
                    with self.assertRaisesRegex(RuntimeError, 'stop before input'):
                        task.fight_verified_domain()
                self.assertEqual(100 + seconds, task._battle_deadline)
                self.assertEqual(400, task._battle_hard_deadline)

    def test_skill_timeout_with_boss_bar_recovers_rotation(self):
        task = VerifiedDomainCombat()
        char = SimpleNamespace(char_name='char_chisa', confidence=.99,
                               perform=Mock(side_effect=NotInCombatException('skill timeout')))
        task.chars = [char]
        task._plan_boss = True
        task.prepare_verified_battle = Mock(return_value=False)
        task.confirm_combat_entry = Mock()
        task.load_chars = task.on_combat_started = Mock()
        task._start_combat_debug_frame_recorder = task._stop_combat_debug_frame_recorder = Mock()
        task.in_combat = Mock(side_effect=[True, False])
        task.domain_combat_finished = Mock()
        task.get_current_char = Mock(return_value=char)
        task.in_team = Mock(return_value=(True, 2, 3))
        task.check_health_bar = Mock(return_value=True)
        task.find_treasure_icon = Mock(return_value=True)
        task.wait_until = Mock(return_value=True)
        task.next_frame = task.mouse_up = task.send_key_up = task.log_info = Mock()
        task.configure_material_boss = task.acquire_material_boss = Mock()
        task.switch_next_char = Mock()
        task.fight_verified_domain()
        task.acquire_material_boss.assert_called()
        task.switch_next_char.assert_called_once_with(char)
        self.assertEqual(1, task._boss_rotation_recoveries)

    def test_progress_extends_once_but_stalled_counter_does_not(self):
        task = SimpleNamespace(_plan_boss=False, _battle_hard_deadline=300,
                               _deadline_kills=0, ocr=Mock(return_value=[SimpleNamespace(name='限时击败敌人：4/5')]),
                               log_info=Mock())
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=150):
            self.assertTrue(VerifiedDomainCombat.extend_domain_deadline(task))
            self.assertEqual(240, task._battle_deadline)
            self.assertFalse(VerifiedDomainCombat.extend_domain_deadline(task))
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=300):
            self.assertFalse(VerifiedDomainCombat.extend_domain_deadline(task))

    def test_normal_material_domain_checks_health_without_boss_acquisition(self):
        task = MaterialBossGuard()
        task._plan_boss = False
        task._boss_guard_at = 0
        task.check_material_boss_health = Mock()
        task.boss_target_locked = Mock()
        task.guard_material_boss()
        task.check_material_boss_health.assert_called_once()
        task.boss_target_locked.assert_not_called()
