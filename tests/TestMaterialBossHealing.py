import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
from src.combat.MaterialBossHealing import MaterialBossHealing, BossHealRequested
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestMaterialBossHealing(unittest.TestCase):
    def task(self):
        task = MaterialBossHealing()
        task.chars = [SimpleNamespace(char_name='yangyang_sp', confidence=.99),
                      SimpleNamespace(char_name='char_phrolova', confidence=.99),
                      SimpleNamespace(char_name='char_suisui', confidence=.99,
                                      emergency_heal_actions=Mock(return_value=True))]
        task.in_team = Mock(return_value=(True, 0, 3))
        return task

    def test_wounded_ally_interrupts_rotation_before_retreat(self):
        task = self.task()
        with self.assertRaises(BossHealRequested) as cm:
            task.request_boss_healing((5000, 10000))
        self.assertEqual(0, cm.exception.slot)

    def test_chisa_is_selected_for_injured_ally_and_self(self):
        task = self.task()
        task.chars[2].char_name = 'char_chisa'
        for slot in (0, 2):
            task.in_team.return_value = (True, slot, 3)
            with self.assertRaises(BossHealRequested) as cm:
                task.request_boss_healing((5000, 10000))
            self.assertEqual(slot, cm.exception.slot)

    def test_chisa_self_rescue_casts_team_heal_without_swap_out(self):
        task = self.rescue((8000, 10000))
        task.chars[2].char_name = 'char_chisa'
        task.in_team.return_value = (True, 2, 3)
        task.heal_material_boss(BossHealRequested(2, (5000, 10000)))
        task.chars[2].emergency_heal_actions.assert_called_once()
        self.assertEqual('verified', task.result['healing'][0]['status'])

    def test_victory_during_healing_returns_to_reward_only_with_live_marker(self):
        from src.task.BaseCombatTask import NotInCombatException
        for victory in (True, False):
            task = self.rescue((8000, 10000))
            task.chars[2].emergency_heal_actions.side_effect = NotInCombatException('combat ended')
            task.material_victory_visible = Mock(return_value=victory)
            if victory:
                task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
                self.assertTrue(task._battle_end_seen)
                self.assertEqual('victory_during_healing', task.result['healing'][0]['status'])
            else:
                with self.assertRaisesRegex(DomainBattleFailed, '胜利未确认'):
                    task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
            self.assertFalse(task._boss_healing)

    def test_chisa_without_liberation_yields_to_verified_healthy_ally(self):
        task = self.rescue((6000, 10000))
        task.chars[2].char_name = 'char_chisa'
        task.chars[2].emergency_heal_actions.return_value = False
        task.in_team.return_value = (True, 2, 3)
        task.chars[0].index = 0
        task.verify_healing_replacement = Mock(return_value=task.chars[0])
        task.heal_material_boss(BossHealRequested(2, (6000, 10000)))
        task.verify_healing_replacement.assert_called_once_with(2)
        self.assertEqual('deferred_to_healthy_ally', task.result['healing'][0]['status'])
        self.assertGreater(task.chars[2].recovery_until, time.monotonic())
        self.assertFalse(task._boss_healing)

    def test_critical_hp_never_starts_long_healing_rotation(self):
        with self.assertRaises(BossHealRequested):
            self.task().request_boss_healing((0, 10000))

    def test_critical_hp_switches_to_healthy_ally_without_waiting_for_heal(self):
        task = self.rescue((9000, 10000))
        task.chars[1].index = 1
        task.verify_healing_replacement = Mock(return_value=task.chars[1])
        task.heal_material_boss(BossHealRequested(0, (600, 10000)))
        task.verify_healing_replacement.assert_called_once_with(0)
        task.chars[2].emergency_heal_actions.assert_not_called()
        self.assertEqual('critical_swap', task.result['healing'][0]['status'])
        self.assertFalse(task._boss_healing)

    def test_no_executable_healer_requests_replacement_at_retreat_threshold(self):
        task = self.task()
        del task.chars[2].emergency_heal_actions
        self.assertFalse(task.request_boss_healing((4100, 10000)))
        for hp in (4000, 2900):
            with self.subTest(hp=hp), self.assertRaises(BossHealRequested):
                task.request_boss_healing((hp, 10000))

    def test_protective_swap_uses_verified_replacement_without_claiming_a_heal(self):
        task = self.rescue((9000, 10000))
        del task.chars[2].emergency_heal_actions
        task.chars[1].index = 1
        task.verify_healing_replacement = Mock(return_value=task.chars[1])
        task.heal_material_boss(BossHealRequested(0, (3800, 10000)))
        task.verify_healing_replacement.assert_called_once_with(0)
        event = task.result['healing'][0]
        self.assertEqual('protective_swap', event['status'])
        self.assertNotIn('after', event)
        self.assertGreater(task.chars[0].recovery_until, time.monotonic())
        self.assertFalse(task._boss_healing)

    def test_protective_swap_still_retreats_when_no_replacement_is_verified(self):
        task = self.rescue((9000, 10000))
        del task.chars[2].emergency_heal_actions
        task.verify_healing_replacement = Mock(side_effect=DomainBattleFailed('no healthy ally'))
        with self.assertRaisesRegex(DomainBattleFailed, 'no healthy ally'):
            task.heal_material_boss(BossHealRequested(0, (3800, 10000)))
        self.assertFalse(task._boss_healing)

    def test_wounded_healer_does_not_attempt_stationary_self_rescue(self):
        task = self.task()
        task.in_team.return_value = (True, 2, 3)
        with self.assertRaises(BossHealRequested):
            task.request_boss_healing((6000,10000))

    def test_healer_can_yield_to_recent_healthy_ally_after_ally_rescue(self):
        task = self.task()
        task.in_team.return_value = (True, 2, 3)
        task._boss_team_health = {0: (time.monotonic(), (9000,10000))}
        task._boss_heal_last = time.monotonic()
        with self.assertRaises(BossHealRequested):
            task.request_boss_healing((6000,10000))

    def test_old_or_injured_replacement_is_not_trusted(self):
        task = self.task()
        task._boss_team_health = {0: (time.monotonic()-20, (9000,10000)),
                                  1: (time.monotonic(), (4000,10000))}
        self.assertIsNone(task.healthy_healing_replacement(2))

    def test_unavailable_replacement_is_rejected_before_any_switch(self):
        task = self.task()
        for index, char in enumerate(task.chars):
            char.index = index
        task._boss_team_health = {0: (time.monotonic(), (9000, 10000))}
        task.healing_replacement_available = Mock(return_value=False)
        task.healing_switch = Mock()
        task.fail_battle = Mock(side_effect=DomainBattleFailed('no current healthy reserve'))
        with self.assertRaisesRegex(DomainBattleFailed, 'no current healthy reserve'):
            task.verify_healing_replacement(2)
        task.healing_switch.assert_not_called()
        self.assertEqual(task.healing_replacement_available.call_count, 2)

    def test_rejected_preferred_reserve_cannot_block_verified_alternative(self):
        task = self.task()
        for index, char in enumerate(task.chars):
            char.index = index
        task._boss_team_health = {0: (time.monotonic(), (9000, 10000))}
        task.healing_replacement_available = lambda c: c.index == 1
        task.healing_switch = Mock(side_effect=lambda c: setattr(task.in_team, 'return_value', (True, c.index, 3)))
        task.read_boss_hp = Mock(return_value=(8000, 10000))
        task.wait_until = lambda fn, **kw: fn()
        self.assertIs(task.verify_healing_replacement(2), task.chars[1])
        task.healing_switch.assert_called_once_with(task.chars[1])

    def test_self_rescue_keeps_wounded_healer_off_field(self):
        task = self.rescue((8000,10000))
        for i, char in enumerate(task.chars):
            char.index = i
        task.in_team.return_value = (True, 2, 3)
        task._boss_team_health = {0: (time.monotonic(), (9000,10000))}
        task.sleep = Mock()
        task.healing_switch.side_effect = lambda c: setattr(task.in_team, 'return_value', (True,c.index,3))
        task.heal_material_boss(BossHealRequested(2,(6000,10000)))
        self.assertEqual([task.chars[0]],
                         [c.args[0] for c in task.healing_switch.call_args_list])
        task.chars[2].emergency_heal_actions.assert_not_called()
        self.assertEqual('self_rescue_deferred', task.result['healing'][0]['status'])
        self.assertGreater(task.chars[2].recovery_until, time.monotonic())
        self.assertNotIn('after', task.result['healing'][0])

    def test_healing_does_not_recursively_request_healing(self):
        task = self.task()
        task._boss_healing = True
        task._boss_heal_deadline = float('inf')
        self.assertTrue(task.request_boss_healing((3000, 10000)))

    def rescue(self, hp):
        task = self.task()
        task.result = {}
        task.mouse_up = Mock()
        task.healing_switch = Mock()
        task.next_frame = task.log_info = Mock()
        task.read_current_hp = Mock(return_value=hp)
        task.wait_until = lambda predicate, **kw: predicate()
        return task

    def test_success_requires_original_ally_hp_increase(self):
        task = self.rescue((6000,10000))
        task.heal_material_boss(BossHealRequested(0,(5000,10000)))
        self.assertEqual('verified', task.result['healing'][0]['status'])
        self.assertIs(task.chars[0], task.healing_switch.call_args.args[0])
        self.assertFalse(task._boss_healing)

    def test_unsafe_healing_verification_yields_without_claiming_recovery(self):
        for name in ('char_douling', 'char_chisa', 'char_verina'):
            for current_hp in (3900, 1900):
                task = self.rescue((current_hp, 10000))
                task.chars[2].char_name = name
                task.chars[1].index = 1
                task.verify_healing_replacement = Mock(return_value=task.chars[1])
                task.heal_material_boss(BossHealRequested(0, (6000, 10000)))
                event = task.result['healing'][0]
                self.assertEqual('unverified_heal_deferred', event['status'])
                self.assertEqual(2, event['resume_slot'])
                self.assertEqual((current_hp, 10000), event['after'])
                self.assertNotIn('positive_hp_readings', event)
                self.assertTrue(task.chars[0].recovery_needs_health)
                task.verify_healing_replacement.assert_called_once_with(0)
                self.assertFalse(task._boss_healing)
                self.assertFalse(task.in_liberation)

    def test_victory_during_unsafe_heal_replacement_still_requires_marker(self):
        from src.task.BaseCombatTask import NotInCombatException
        for victory in (True, False):
            task = self.rescue((1900, 10000))
            task.verify_healing_replacement = Mock(side_effect=NotInCombatException('combat ended'))
            task.material_victory_visible = Mock(return_value=victory)
            if victory:
                task.heal_material_boss(BossHealRequested(0, (6000, 10000)))
                self.assertEqual('victory_during_healing', task.result['healing'][0]['status'])
                self.assertTrue(task._battle_end_seen)
            else:
                with self.assertRaisesRegex(DomainBattleFailed, '胜利未确认'):
                    task.heal_material_boss(BossHealRequested(0, (6000, 10000)))
            self.assertFalse(task._boss_healing)

    def test_unsafe_healing_still_stops_without_verified_replacement(self):
        task = self.rescue((1900, 10000))
        task.verify_healing_replacement = Mock(side_effect=DomainBattleFailed('no healthy ally'))
        with self.assertRaisesRegex(DomainBattleFailed, 'no healthy ally'):
            task.heal_material_boss(BossHealRequested(0, (6000, 10000)))
        self.assertEqual('failed', task.result['healing'][0]['status'])
        self.assertFalse(task._boss_healing)
        task.mouse_up.assert_called()

    def test_healer_hp_or_no_gain_never_counts_as_success(self):
        for hp, slot in [((5000,10000),0), ((10000,10000),2)]:
            task = self.rescue(hp)
            task.in_team.return_value = (True, slot, 3)
            with self.assertRaises(DomainBattleFailed):
                task.heal_material_boss(BossHealRequested(0,(5000,10000)))
            self.assertFalse(task._boss_healing)
            self.assertEqual('failed',task.result['healing'][0]['status'])

    def test_empty_liberation_defers_injured_ally_to_healthy_teammate(self):
        task = self.rescue((6000, 10000))
        task.chars[2].char_name = 'char_chisa'
        task.chars[2].emergency_heal_actions.return_value = False
        task.chars[1].index = 1
        task.verify_healing_replacement = Mock(return_value=task.chars[1])
        task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
        task.healing_switch.assert_called_once_with(task.chars[2])
        self.assertFalse(task.result['healing'][0]['action_issued'])
        self.assertEqual('deferred_to_healthy_ally', task.result['healing'][0]['status'])
        self.assertEqual(2, task.result['healing'][0]['resume_slot'])
        self.assertFalse(task._boss_healing)

    def test_empty_liberation_without_healthy_ally_still_retreats(self):
        task = self.rescue((6000, 10000))
        task.chars[2].char_name = 'char_chisa'
        task.chars[2].emergency_heal_actions.return_value = False
        task.verify_healing_replacement = Mock(side_effect=DomainBattleFailed('无健康队友'))
        with self.assertRaises(DomainBattleFailed):
            task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
        self.assertEqual('failed', task.result['healing'][0]['status'])

    def test_failed_healer_backoff_covers_self_and_ally_but_not_other_healers(self):
        task = self.rescue((6000, 10000))
        healer = task.chars[2]
        healer.char_name = 'char_chisa'
        healer.emergency_heal_actions.return_value = False
        task.chars[1].index = 1
        task.verify_healing_replacement = Mock(return_value=task.chars[1])
        with patch('src.combat.MaterialBossHealing.time.monotonic', return_value=100):
            task.heal_material_boss(BossHealRequested(0, (6000, 10000)))
            self.assertEqual(125, healer.heal_retry_after)
            for slot in (1, 2):
                task.in_team.return_value = (True, slot, 3)
                self.assertFalse(task.request_boss_healing((6000, 10000)))
            task.chars[1].emergency_heal_actions = Mock(return_value=True)
            self.assertEqual([task.chars[1]], task.healing_candidates())
            # Critical HP still requests a verified replacement during backoff.
            with self.assertRaises(BossHealRequested):
                task.request_boss_healing((1000, 10000))
        with patch('src.combat.MaterialBossHealing.time.monotonic', return_value=126):
            self.assertIn(healer, task.healing_candidates())

    def test_suisui_without_ready_heal_defers_to_verified_healthy_ally(self):
        task = self.rescue((6000, 10000))
        task.chars[2].emergency_heal_actions.return_value = False
        task.chars[1].index = 1
        task.verify_healing_replacement = Mock(return_value=task.chars[1])
        task.heal_material_boss(BossHealRequested(0, (3800, 10000)))
        task.verify_healing_replacement.assert_called_once_with(0)
        self.assertEqual('deferred_to_healthy_ally', task.result['healing'][0]['status'])
        self.assertGreater(task.chars[0].recovery_until, time.monotonic())

    def test_suisui_without_ready_heal_or_healthy_ally_still_retreats(self):
        task = self.rescue((6000, 10000))
        task.chars[2].emergency_heal_actions.return_value = False
        task.verify_healing_replacement = Mock(side_effect=DomainBattleFailed('no healthy ally'))
        with self.assertRaisesRegex(DomainBattleFailed, 'no healthy ally'):
            task.heal_material_boss(BossHealRequested(0, (3800, 10000)))
        self.assertEqual('failed', task.result['healing'][0]['status'])


class TestObservedHealingTrend(unittest.TestCase):
    def test_recorded_small_ticks_are_real_healing(self):
        readings = []
        before = (18504,33398)
        self.assertFalse(MaterialBossHealing.healing_progress(before, readings, (18713,33398)))
        self.assertFalse(MaterialBossHealing.healing_progress(before, readings, (18713,33398)))
        self.assertTrue(MaterialBossHealing.healing_progress(before, readings, (18922,33398)))

    def test_damage_and_max_hp_change_cannot_supply_positive_ticks(self):
        readings = []
        before = (18504,33398)
        for hp in ((18713,33398), (18600,33398), (18713,35000)):
            self.assertFalse(MaterialBossHealing.healing_progress(before, readings, hp))


class TestHealingActionResult(unittest.TestCase):
    def test_suisui_reports_alternative_e_prompt_or_timeout(self):
        from src.char.Suisui import Suisui
        for issued in (False, True):
            char = SimpleNamespace(check_combat=Mock(), is_e_forte_full=Mock(return_value=False),
                try_e=Mock(return_value=issued), click=Mock())
            with patch('src.char.Suisui.time.monotonic', side_effect=[0, 1, 8]):
                self.assertEqual(issued, Suisui.emergency_heal_actions(char))
