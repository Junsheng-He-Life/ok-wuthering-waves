"""Check farming encounter acquisition without capture or native input."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from src.combat.CombatCheck import CombatCheck

from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.EchoFarmTask import EchoFarmTask
from src.task.SettlementTrialTask import SettlementTrialTask
from src.task.VerifiedDomainCombat import VerifiedDomainCombat, DomainBattleFailed


class TestOriginalCombatEntry(unittest.TestCase):
    def recovery_task(self):
        task = VerifiedDomainCombat()
        task.do_reset_to_false = Mock()
        task.in_combat = Mock(return_value=True)
        task.in_team_and_world = Mock(return_value=True)
        task.original_combat_detected = Mock(return_value=True)
        task.target_enemy = task.next_frame = Mock()
        task.log_info = Mock()
        task.wait_until = Mock(side_effect=lambda callback, **kwargs: callback())
        return task

    def test_action_timeout_reacquires_live_enemy_before_resuming(self):
        task = self.recovery_task()
        self.assertTrue(task.resume_verified_rotation())
        task.do_reset_to_false.assert_called_once()
        task.original_combat_detected.assert_called_once()
        task.target_enemy.assert_any_call(wait=False)
        self.assertEqual(task.wait_until.call_args.kwargs['time_out'], 8)

    def test_action_timeout_without_lock_does_not_resume_attacks(self):
        task = self.recovery_task()
        task.original_combat_detected.return_value = False
        self.assertFalse(task.resume_verified_rotation())

    def test_verified_victory_does_not_retarget(self):
        task = self.recovery_task()
        task.in_combat.return_value = False
        self.assertTrue(task.resume_verified_rotation())
        task.original_combat_detected.assert_not_called()

    def test_action_recovery_preserves_deadline_failure(self):
        task = self.recovery_task()
        task.in_combat.side_effect = DomainBattleFailed('battle timed out')
        with self.assertRaisesRegex(DomainBattleFailed, 'battle timed out'):
            task.resume_verified_rotation()
        task.original_combat_detected.assert_not_called()

    def test_native_shifted_icon_compares_locked_and_unlocked_states(self):
        task = SimpleNamespace(width=1920, height=1080,
                               get_target_names=Mock(return_value=('has_target', 'no_target')),
                               is_browser=Mock(return_value=False),
                               find_best_match_in_box=Mock())
        with patch('src.combat.CombatCheck.sys.platform', 'darwin'):
            for state, expected in (('has_target', True), ('no_target', False)):
                task.find_best_match_in_box.return_value = SimpleNamespace(name=state)
                self.assertEqual(expected, CombatCheck.has_target(task))
                args, kwargs = task.find_best_match_in_box.call_args
                self.assertLessEqual(args[0].x, 1447)
                self.assertGreaterEqual(args[0].x + args[0].width, 1477)
                self.assertEqual(['has_target', 'no_target'], args[1])
                self.assertEqual(.6, kwargs['threshold'])

    def task(self):
        task = SafeMaterialTask.__new__(SafeMaterialTask)
        task._in_combat = False
        task.in_liberation = False
        task.config = {}
        task.combat_chars_ready = Mock(return_value=True)
        task.load_chars = Mock(return_value=True)
        task.has_target = Mock(return_value=False)
        task.check_health_bar = Mock(return_value=False)
        task.target_enemy = Mock(return_value=False)
        task.find_one = Mock(return_value=False)
        task.log_info = task.log_error = Mock()
        task.target_enemy_error_notified = False
        return task

    def test_locked_target_enters_without_requiring_a_visible_bar(self):
        task = self.task()
        task.has_target.return_value = True
        self.assertTrue(task.original_combat_detected())
        task.check_health_bar.assert_not_called()
        task.target_enemy.assert_not_called()

    def test_visible_bar_requires_successful_original_retarget(self):
        task = self.task()
        task.check_health_bar.return_value = True
        task.target_enemy.return_value = True
        self.assertTrue(task.original_combat_detected())
        task.target_enemy.assert_called_once_with(wait=True)

    def test_bar_without_lock_cannot_start_rotation(self):
        task = self.task()
        task.check_health_bar.return_value = True
        self.assertFalse(task.original_combat_detected())
        self.assertFalse(task._in_combat)
        task.target_enemy.assert_called_once_with(wait=True)

    def test_no_enemy_does_not_try_to_lock_or_enter(self):
        task = self.task()
        self.assertFalse(task.original_combat_detected())
        self.assertFalse(task._in_combat)
        task.target_enemy.assert_not_called()

    def test_all_farming_adapters_require_lock_on(self):
        for task_type in (SafeMaterialTask, EchoFarmTask, SettlementTrialTask):
            with self.subTest(task=task_type.__name__):
                task = task_type.__new__(task_type)
                self.assertFalse(task.allow_combat_without_target())

    def test_entry_discards_previous_encounter_before_detection(self):
        task = self.task()
        task._in_combat = True
        def reset():
            task._in_combat = False
        task.do_reset_to_false = Mock(side_effect=reset)
        def wait(callback, **kwargs):
            self.assertFalse(task._in_combat)
            return callback()
        task.wait_until = Mock(side_effect=wait)
        task.has_target.return_value = True
        task.confirm_combat_entry()
        task.do_reset_to_false.assert_called_once()
        self.assertTrue(task._in_combat)

    def test_unconfirmed_entry_never_reaches_opening_or_character_rotation(self):
        task = VerifiedDomainCombat()
        char = SimpleNamespace(char_name='char_aemeath', confidence=.99, perform=Mock())
        task.chars = [char]
        task.prepare_verified_battle = Mock(return_value=False)
        task.load_chars = task.do_reset_to_false = Mock()
        task.original_combat_detected = Mock(return_value=False)
        task.wait_until = Mock(side_effect=lambda callback, **kwargs: callback())
        task.fail_battle = Mock(side_effect=DomainBattleFailed('entry not confirmed'))
        task.on_combat_started = Mock()
        task.domain_combat_finished = Mock(return_value=False)
        task._start_combat_debug_frame_recorder = task._stop_combat_debug_frame_recorder = Mock()
        task.mouse_up = task.send_key_up = Mock()
        with self.assertRaisesRegex(DomainBattleFailed, 'entry not confirmed'):
            task.fight_verified_domain()
        task.on_combat_started.assert_not_called()
        char.perform.assert_not_called()
        self.assertFalse(task._verified_battle or task._in_combat)

    def test_failed_fresh_team_read_stops_before_start_despite_old_trusted_chars(self):
        for load_result in (False, None):
            with self.subTest(load_result=load_result):
                task = VerifiedDomainCombat()
                task.chars = [SimpleNamespace(char_name=name, confidence=.99, perform=Mock())
                              for name in ('char_aemeath', 'char_denia', 'char_chisa')]
                old_chars = task.chars
                task.prepare_verified_battle = Mock(return_value=True)
                task.load_chars = Mock(return_value=load_result)
                task.pick_f = task.confirm_combat_entry = task.on_combat_started = Mock()
                task._start_combat_debug_frame_recorder = Mock()
                with self.assertRaisesRegex(RuntimeError, 'live team could not be read'):
                    task.fight_verified_domain()
                self.assertIs(old_chars, task.chars)
                task.pick_f.assert_not_called()
                task.confirm_combat_entry.assert_not_called()
                task.on_combat_started.assert_not_called()
                task._start_combat_debug_frame_recorder.assert_not_called()
                for char in task.chars:
                    char.perform.assert_not_called()
