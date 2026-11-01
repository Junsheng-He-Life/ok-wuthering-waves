"""Echo decisions use synthetic HUD states, never a controller or capture."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.combat.EchoCombatPolicy import EchoCombatPolicy
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.task.EchoFarmTask import EchoFarmTask
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.CharacterMaterialTask import CharacterMaterialTask


class Policy(EchoCombatPolicy, MaterialBossGuard):
    phase = 'echo'


class TestEchoCombatPolicy(unittest.TestCase):
    def test_material_workflow_retains_local_character_chains(self):
        from src.combat.DetonationTeam import DetonationTeam
        from src.char.Chisa import Chisa
        from src.char.Denia import Denia
        task = SafeMaterialTask.__new__(SafeMaterialTask)
        task._verified_battle = True
        task.chars = [SimpleNamespace(char_name=n, confidence=.99)
                      for n in ('char_chisa', 'char_denia', 'char_aemeath')]
        self.assertTrue(task.detonation_team_active())
        self.assertIs(SafeMaterialTask.preferred_switch_target,
                      DetonationTeam.preferred_switch_target)
        self.assertFalse(hasattr(task, 'allow_opportunistic_skills'))
        for cls in (Chisa, Denia):
            char = cls.__new__(cls)
            char.task = task
            char.do_detonation_support = Mock()
            char.switch_next_char = Mock()
            char.do_perform()
            char.do_detonation_support.assert_called_once()
            char.switch_next_char.assert_not_called()

    def task(self):
        task = Policy()
        task._verified_battle = True
        task._battle_end_seen = False
        task._boss_target_missing_at = None
        task.result = {}
        task.in_team_and_world = Mock(return_value=True)
        task.boss_target_locked = Mock(return_value=False)
        task.mouse_up = Mock()
        task.middle_click = Mock()
        task.next_frame = Mock()
        task.log_info = Mock()
        task.check_combat = Mock()
        return task

    def test_lock_loss_gets_one_recheck_after_grace_then_rate_limited(self):
        task = self.task()
        with patch('src.combat.EchoCombatPolicy.time.monotonic', side_effect=[10, 11, 12, 12.5]):
            for _ in range(4):
                task.guard_echo_target()
        task.middle_click.assert_called_once()
        self.assertTrue(task.held_attack_interrupted)
        self.assertEqual(task.result['target_rechecks'], [{'locked': False}])

    def test_visible_lock_is_not_toggled_off(self):
        task = self.task()
        task.boss_target_locked.return_value = True
        task._boss_target_missing_at = 1
        task.guard_echo_target()
        task.middle_click.assert_not_called()
        self.assertIsNone(task._boss_target_missing_at)

    def test_confirmed_relock_clears_missing_timer(self):
        task = self.task()
        task._boss_target_missing_at = 1
        task.boss_target_locked.side_effect = [False, True]
        task.guard_echo_target()
        self.assertIsNone(task._boss_target_missing_at)
        self.assertEqual(task.result['target_rechecks'], [{'locked': True}])

    def test_victory_healing_cinematic_and_inactive_task_never_retarget(self):
        for field, value in (('_battle_end_seen', True), ('_boss_healing', True),
                             ('in_liberation', True), ('_verified_battle', False)):
            task = self.task()
            setattr(task, field, value)
            task.guard_echo_target()
            task.middle_click.assert_not_called()

    def test_catalog_and_settlement_do_not_inherit_echo_skill_policy(self):
        task = self.task()
        for phase in ('echo-catalog', 'echo-inventory', 'settlement-test'):
            task.phase = phase
            self.assertFalse(task.allow_opportunistic_skills())
            self.assertFalse(task.use_ready_combat_skill())

    def test_echo_enables_bounded_r_and_damage_dodge_without_boss_profile(self):
        task = EchoFarmTask.__new__(EchoFarmTask)
        task._verified_battle = True
        self.assertTrue(task.use_bounded_liberation_retry())
        self.assertTrue(task.allow_immediate_visible_liberation())
        self.assertTrue(task.boss_policy_value('reactive_dodge', False))
        task.boss_profile = SimpleNamespace(reactive_dodge=False)
        self.assertTrue(task.boss_policy_value('reactive_dodge', False))

    def test_non_boss_focus_loss_releases_held_attack_and_restores_game(self):
        task = SafeMaterialTask.__new__(SafeMaterialTask)
        window = SimpleNamespace(is_foreground=Mock(return_value=False),
                                 bring_to_front=Mock(return_value=True))
        task._executor = SimpleNamespace(interaction=SimpleNamespace(mac_window=window))
        task._verified_battle = True
        task._plan_boss = False
        task.mouse_up = Mock()
        task.log_info = Mock()
        with patch.object(CharacterMaterialTask, 'next_frame') as frame:
            task.next_frame()
        task.mouse_up.assert_called_once()
        window.bring_to_front.assert_called_once()
        frame.assert_called_once()
        self.assertTrue(task.held_attack_interrupted)

    def test_same_slot_damage_dodges_once_with_release_and_cooldown(self):
        task = self.task()
        task._boss_hp_samples = {}
        task._boss_last_dodge = 0
        task._boss_unreadable_hp = 0
        task.read_boss_hp = Mock(side_effect=[(100, 100), (85, 100), (70, 100)])
        task.in_team = Mock(return_value=(True, 0, 3))
        task.request_boss_healing = Mock(return_value=False)
        task.send_key = Mock()
        with patch('src.combat.MaterialBossGuard.time.monotonic', side_effect=[10, 11, 12]):
            for _ in range(3):
                task.check_material_boss_health()
        task.mouse_up.assert_called_once()
        task.send_key.assert_called_once_with('shift', down_time=.08)
        self.assertEqual(len(task.result['damage_dodges']), 1)

    def test_damage_from_different_slots_is_not_compared(self):
        task = self.task()
        task._boss_hp_samples = {0: (10, 1.)}
        task._boss_last_dodge = 0
        task.read_boss_hp = Mock(return_value=(70, 100))
        task.in_team = Mock(return_value=(True, 1, 3))
        task.request_boss_healing = Mock(return_value=False)
        task.send_key = Mock()
        with patch('src.combat.MaterialBossGuard.time.monotonic', return_value=11):
            task.check_material_boss_health()
        task.send_key.assert_not_called()

    def skill_task(self):
        task = self.task()
        char = SimpleNamespace(confidence=.99, is_e_forte_full=Mock(return_value=True),
                               resonance_available=Mock(return_value=True),
                               liberation_available=Mock(return_value=True),
                               click_resonance=Mock(return_value=(True, .1, False)),
                               click_liberation=Mock(return_value=True))
        task.get_current_char = Mock(return_value=char)
        return task, char

    def test_enhanced_e_does_not_starve_independent_r(self):
        task, char = self.skill_task()
        self.assertTrue(task.use_ready_combat_skill())
        char.click_resonance.assert_called_once_with(send_click=False, time_out=.6)
        char.click_liberation.assert_called_once_with(send_click=False, wait_if_cd_ready=0)
        task.use_ready_combat_skill()
        self.assertEqual(char.click_liberation.call_count, 1)

    def test_ordinary_e_is_left_to_character_module(self):
        task, char = self.skill_task()
        char.is_e_forte_full.return_value = False
        task.use_ready_combat_skill()
        char.click_resonance.assert_not_called()
        char.click_liberation.assert_called_once()

    def test_slow_unconfirmed_e_cannot_replace_every_attack_chunk(self):
        task, char = self.skill_task()
        clock = [10.]
        def skill(**kwargs):
            clock[0] += 1
            return True, 1., False
        char.click_resonance.side_effect = skill
        char.liberation_available.return_value = False
        with patch('src.combat.EchoCombatPolicy.time.monotonic', side_effect=lambda: clock[0]):
            self.assertTrue(task.use_ready_combat_skill())
            self.assertFalse(task.use_ready_combat_skill())
        char.click_resonance.assert_called_once()

    def test_nested_skill_guard_cannot_reenter_poll(self):
        task, char = self.skill_task()
        char.click_liberation.side_effect = lambda **_: task.use_ready_combat_skill()
        task.use_ready_combat_skill()
        char.click_liberation.assert_called_once()
        self.assertFalse(task._echo_skill_polling)

    def test_health_interrupt_releases_reentry_latch_without_skill_input(self):
        task, char = self.skill_task()
        task.check_combat.side_effect = RuntimeError('health guard')
        with self.assertRaisesRegex(RuntimeError, 'health guard'):
            task.use_ready_combat_skill()
        char.click_resonance.assert_not_called()
        self.assertFalse(task._echo_skill_polling)
