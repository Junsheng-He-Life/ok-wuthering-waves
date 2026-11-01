"""Failed Echo fights retreat once; uncertain spending and user control win."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.EchoFarmTask import TacetEchoTask
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestEchoFailureRecovery(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(SafeMaterialTask, 'next_frame', return_value=None),
            patch('src.task.DomainTask.manual_domain_exit_override_active', return_value=False),
            patch('src.task.DomainTask.domain_leave_confirmation_visible', return_value=False),
        ]
        self.frames, self.manual_override, self.confirmation = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def task(self, world=False):
        task = TacetEchoTask.__new__(TacetEchoTask)
        task._executor = SimpleNamespace(paused=False, exit_event=SimpleNamespace(is_set=lambda: False))
        task._enabled = True
        task._paused = False
        task._manual_exit_requested = False
        task.result = {'status': 'stopped', 'error': 'original battle failure',
                       'trigger_evidence': ['saved-original-trigger']}
        task._run_budget = MaterialRunBudget(1, 60, 0, 0)
        task.assert_echo_start_safe = Mock()
        task.in_realm = Mock(return_value=not world)
        task.in_team = Mock(return_value=(True, 0, 3))
        task.find_world_earth_icon = Mock(return_value=world)
        task.menu_text = Mock(return_value=False)
        task.check_health_bar = Mock(return_value=False)
        task.boss_target_locked = Mock(return_value=False)
        task.set_workflow_stage = Mock()
        def leave():
            task.in_realm.return_value = False
            task.find_world_earth_icon.return_value = True
        task.leave_verified_domain = Mock(side_effect=leave)
        task.return_to_world = Mock()
        task.heal_at_beacon = Mock()
        task.claim_one_reward = Mock()
        task.refill_at_reward = Mock()
        return task

    def assert_no_departure(self, task):
        task.leave_verified_domain.assert_not_called()
        task.return_to_world.assert_not_called()
        task.heal_at_beacon.assert_not_called()
        task.claim_one_reward.assert_not_called()
        task.refill_at_reward.assert_not_called()

    def test_safe_instance_exit_checks_team_health_before_optional_teleport(self):
        task = self.task()
        task.recover_failed_echo_battle()
        task.leave_verified_domain.assert_called_once()
        task.return_to_world.assert_called_once()
        task.heal_at_beacon.assert_called_once_with()
        self.assertEqual('healed', task.result['failure_recovery']['status'])
        self.assertEqual('post_exit_health_check', task.result['failure_recovery']['healing_mode'])
        self.assertEqual('original battle failure', task.result['error'])
        self.assertEqual(['saved-original-trigger'], task.result['trigger_evidence'])
        self.assertEqual((0, 0, 0), (task._run_budget.spent, task._run_budget.claimed,
                                   task._run_budget.retries))
        task.claim_one_reward.assert_not_called()
        task.refill_at_reward.assert_not_called()

    def test_world_encounter_teleports_without_opening_domain_exit(self):
        task = self.task(world=True)
        task.recover_failed_echo_battle()
        task.leave_verified_domain.assert_not_called()
        task.heal_at_beacon.assert_called_once_with(force_teleport=True, verify_before=False)

    def test_combat_still_visible_after_exit_keeps_forced_retreat(self):
        for detector in ('check_health_bar', 'boss_target_locked'):
            with self.subTest(detector=detector):
                task = self.task()
                getattr(task, detector).return_value = True
                task.recover_failed_echo_battle()
                task.heal_at_beacon.assert_called_once_with(force_teleport=True, verify_before=False)

    def test_unknown_page_after_return_prevents_health_checks_and_map_input(self):
        task = self.task()
        task.return_to_world.side_effect = lambda: setattr(task.find_world_earth_icon, 'return_value', False)
        task.recover_failed_echo_battle()
        task.heal_at_beacon.assert_not_called()
        self.assertIn('world HUD lost', task.result['failure_recovery']['error'])

    def test_stopped_paused_or_manual_controller_never_starts_recovery(self):
        for field, value in (('_enabled', False), ('_paused', True), ('_manual_exit_requested', True)):
            with self.subTest(field=field):
                task = self.task()
                setattr(task, field, value)
                task.recover_failed_echo_battle()
                self.assertEqual('skipped', task.result['failure_recovery']['status'])
                self.assert_no_departure(task)
        task = self.task()
        task._executor.exit_event.is_set = lambda: True
        task.recover_failed_echo_battle()
        self.assert_no_departure(task)

    def test_visible_player_exit_confirmation_is_never_confirmed(self):
        task = self.task()
        self.confirmation.return_value = True
        task.recover_failed_echo_battle()
        self.assert_no_departure(task)
        self.assertIn('player leave', task.result['failure_recovery']['reason'])

    def test_pending_claim_or_durable_pending_state_preserves_scene(self):
        for pending in ('budget', 'durable'):
            with self.subTest(pending=pending):
                task = self.task()
                if pending == 'budget':
                    task._run_budget.claim_pending = True
                else:
                    task.assert_echo_start_safe.side_effect = RuntimeError('solvent pending')
                task.recover_failed_echo_battle()
                self.assert_no_departure(task)
                self.assertEqual('skipped', task.result['failure_recovery']['status'])

    def test_unknown_menu_never_invokes_generic_menu_recovery(self):
        task = self.task()
        task.in_team.return_value = (False, -1, 0)
        task.in_realm.return_value = False
        task.recover_failed_echo_battle()
        self.assert_no_departure(task)
        self.assertIn('unknown page', task.result['failure_recovery']['reason'])

    def test_stop_after_domain_exit_prevents_map_healing_input(self):
        task = self.task()
        task.leave_verified_domain.side_effect = lambda: setattr(task, '_enabled', False)
        task.recover_failed_echo_battle()
        task.heal_at_beacon.assert_not_called()
        task.return_to_world.assert_not_called()
        self.assertIn('stopped', task.result['failure_recovery']['error'])

    def test_total_recovery_deadline_interrupts_next_capture_boundary(self):
        task = self.task()
        task._echo_failure_recovery_active = True
        task._echo_failure_recovery_deadline = 100
        with patch('src.task.EchoFarmTask.time.monotonic', return_value=101):
            with self.assertRaisesRegex(RuntimeError, 'time limit'):
                task.next_frame()
        self.frames.assert_not_called()

    def run_failure(self, task, error, battle=True):
        task.begin_echo_activity = task.configure_echo_run = Mock()
        task.inspect_echo_inventory = Mock(return_value={'count': 100})
        def fail():
            task._echo_failed_during_battle = battle
            task.result.update(current_stage='战斗', trigger_evidence=['original-trigger'])
            raise error
        task.run_echo_queue = Mock(side_effect=fail)
        task.mouse_up = task.send_key_up = Mock()
        task._stop_combat_debug_frame_recorder = Mock()
        task.update_activity = task.save_run_report = Mock()
        with self.assertRaises(type(error)) as raised:
            task.run()
        self.assertIs(error, raised.exception)
        self.assertEqual(str(error), task.result['error'])
        self.assertEqual(['original-trigger'], task.result['trigger_evidence'])
        self.assertEqual('stopped', task.result['status'])
        task.run_echo_queue.assert_called_once()
        task.save_run_report.assert_called()

    def test_recovery_failure_preserves_original_exception_and_trigger(self):
        task = self.task()
        task.heal_at_beacon.side_effect = RuntimeError('beacon unreadable')
        self.run_failure(task, DomainBattleFailed('low HP'))
        self.assertEqual('beacon unreadable', task.result['failure_recovery']['error'])
        self.assertEqual('战斗', task.result['failure_stage'])

    def test_successful_retreat_still_reports_original_failed_battle(self):
        task = self.task()
        self.run_failure(task, DomainBattleFailed('low HP'))
        self.assertEqual('healed', task.result['failure_recovery']['status'])
        task.claim_one_reward.assert_not_called()
        task.refill_at_reward.assert_not_called()

    def test_other_exceptions_and_entry_failures_do_not_recover(self):
        for error, battle in ((RuntimeError('manual stop'), True),
                              (DomainBattleFailed('navigation failed'), False)):
            with self.subTest(error=error):
                task = self.task()
                self.run_failure(task, error, battle)
                self.assertNotIn('failure_recovery', task.result)
                self.assert_no_departure(task)


if __name__ == '__main__':
    unittest.main()
