"""Regression cases from the 2026-10-30 alternate-team Echo trial."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.Aemeath import Aemeath
from src.char.BaseChar import BaseChar
from src.combat.DetonationTeam import DetonationTeam, ORDER
from src.combat.EchoCombatPolicy import EchoCombatPolicy


class TestDetonationEchoState(unittest.TestCase):
    def aemeath(self, echo=True, second=False):
        task = SimpleNamespace(
            allow_opportunistic_skills=lambda: echo, result={},
            check_combat=Mock(), mouse_up=Mock(), next_frame=Mock())
        char = Aemeath(task, 0)
        char.lib2_available = Mock(return_value=second)
        char.can_cast_lib1 = Mock(return_value=True)
        char.liberation_available = Mock(return_value=True)
        char.is_e_forte_full = Mock(return_value=False)
        char.f_break = Mock()
        char._execute_post_lib2_combo = Mock()
        char._execute_lib2_guard = Mock()
        char._execute_lib1_or_fallback_guard = Mock()
        task.get_current_char = Mock(return_value=char)
        return char

    def test_ready_hook_lib1_enters_second_stage_guard_instead_of_no_cast_fallback(self):
        char = self.aemeath()
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            self.assertTrue(EchoCombatPolicy.use_ready_combat_skill(char.task))
        self.assertEqual(1, char._lib1_cast_count)
        self.assertEqual(0, char._lib2_cast_count)
        char._process_end_of_turn_liberations()
        char._execute_lib2_guard.assert_called_once()
        char._execute_lib1_or_fallback_guard.assert_not_called()

    def test_ready_hook_lib2_clears_pending_state_and_runs_finish_once(self):
        char = self.aemeath(second=True)
        char.pending_lib2 = True
        with patch.object(BaseChar, 'click_liberation', return_value=True), \
                patch('time.time', return_value=100):
            self.assertTrue(EchoCombatPolicy.use_ready_combat_skill(char.task))
        self.assertFalse(char.pending_lib2)
        self.assertEqual(100, char.last_liber)
        self.assertEqual(1, char._lib2_cast_count)
        char._execute_post_lib2_combo.assert_called_once()
        char._process_end_of_turn_liberations()
        char._execute_lib2_guard.assert_not_called()
        char._execute_lib1_or_fallback_guard.assert_not_called()

    def test_owned_lib_entry_does_not_double_count_or_repeat_finisher(self):
        char = self.aemeath(second=True)
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            self.assertTrue(char.lib())
        self.assertEqual(1, char._lib2_cast_count)
        char.f_break.assert_called_once()
        char._execute_post_lib2_combo.assert_called_once()

    def test_failed_opportunistic_cast_keeps_pending_state_and_counts(self):
        char = self.aemeath(second=True)
        char.pending_lib2 = True
        with patch.object(BaseChar, 'click_liberation', return_value=False):
            self.assertFalse(EchoCombatPolicy.use_ready_combat_skill(char.task))
        self.assertTrue(char.pending_lib2)
        self.assertEqual(0, char._lib2_cast_count)
        self.assertEqual(-1, char.last_liber)
        char.f_break.assert_not_called()
        char._execute_post_lib2_combo.assert_not_called()

    def test_non_echo_keeps_state_updates_in_owned_lib_entry(self):
        char = self.aemeath(echo=False)
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            self.assertTrue(char.click_liberation())
            self.assertEqual(0, char._lib1_cast_count)
            self.assertTrue(char.lib())
        self.assertEqual(1, char._lib1_cast_count)

    def test_deferred_switch_callback_preserves_opportunistic_lib1_state(self):
        char = self.aemeath()
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            self.assertTrue(EchoCombatPolicy.use_ready_combat_skill(char.task))
        char.opening_normal_attack_burst = Mock()
        char.perform_everything = Mock()
        char.switch_next_char = Mock()
        char.do_perform()
        self.assertEqual(1, char._lib1_cast_count)
        char._execute_lib2_guard.assert_called_once()
        char._execute_lib1_or_fallback_guard.assert_not_called()

    def test_real_switch_in_starts_fresh_cast_counts(self):
        char = self.aemeath()
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            self.assertTrue(char.lib())
        char.last_switch_in_time = 200
        char.opening_normal_attack_burst = Mock()
        char.perform_everything = Mock()
        char.switch_next_char = Mock()
        char.do_perform()
        self.assertEqual(0, char._lib1_cast_count)
        char._execute_lib1_or_fallback_guard.assert_called_once()
        char._execute_lib2_guard.assert_not_called()

    def perform_char(self, echo=True):
        char = self.aemeath(echo=echo)
        char.task.detonation_team_active = Mock(return_value=True)
        char.click_echo = Mock()
        char.opening_normal_attack_burst = Mock()
        char.perform_everything = Mock()
        char.switch_next_char = Mock()
        char.continues_normal_attack = Mock()
        return char

    def test_same_visit_repeats_only_short_filler_without_restarting_full_rotation(self):
        char = self.perform_char()
        char.do_perform()
        char.do_perform()
        char.do_perform()
        char.click_echo.assert_called_once_with(time_out=0)
        char.opening_normal_attack_burst.assert_called_once()
        char.perform_everything.assert_called_once()
        char._execute_lib1_or_fallback_guard.assert_called_once()
        char._execute_lib2_guard.assert_not_called()
        self.assertEqual(3, char.switch_next_char.call_count)
        self.assertEqual([((.35,), {}), ((.35,), {})],
                         char.continues_normal_attack.call_args_list)
        self.assertEqual(4, char.task.check_combat.call_count)

    def test_repeat_visit_does_not_restart_intro_or_pending_second_r_guard(self):
        char = self.perform_char()
        char.has_intro = True
        char.record_intro_liberation = Mock()
        char.check_outro = Mock(return_value='char_denia')
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            char.lib()
        char.do_perform()
        char.do_perform()
        char.record_intro_liberation.assert_called_once()
        char._execute_lib2_guard.assert_called_once()
        self.assertEqual(1, char._lib1_cast_count)
        self.assertEqual([((1.2,), {}), ((.35,), {})],
                         char.continues_normal_attack.call_args_list)

    def test_repeat_short_filler_can_confirm_ready_second_r_through_existing_hook(self):
        char = self.perform_char()
        char.do_perform()
        char.lib2_available.return_value = True
        char.pending_lib2 = True
        char.continues_normal_attack.side_effect = lambda duration: (
            EchoCombatPolicy.use_ready_combat_skill(char.task))
        with patch.object(BaseChar, 'click_liberation', return_value=True):
            char.do_perform()
        self.assertEqual(1, char._lib2_cast_count)
        self.assertFalse(char.pending_lib2)
        char._execute_post_lib2_combo.assert_called_once()
        char._execute_lib2_guard.assert_not_called()
        char.perform_everything.assert_called_once()

    def test_repeat_visit_stops_at_health_guard_before_filler_or_switch(self):
        char = self.perform_char()
        char.do_perform()
        char.switch_next_char.reset_mock()
        char.task.check_combat.side_effect = RuntimeError('heal required')
        with self.assertRaisesRegex(RuntimeError, 'heal required'):
            char.do_perform()
        char.continues_normal_attack.assert_not_called()
        char.switch_next_char.assert_not_called()
        char.opening_normal_attack_burst.assert_called_once()

    def test_true_switch_or_new_battle_allows_one_new_complete_rotation(self):
        char = self.perform_char()
        char.do_perform()
        char.do_perform()
        char.last_switch_in_time = 100
        char.do_perform()
        char.task.combat_start = 200
        char.do_perform()
        self.assertEqual(3, char.opening_normal_attack_burst.call_count)
        self.assertEqual(3, char.perform_everything.call_count)
        self.assertEqual(3, char._execute_lib1_or_fallback_guard.call_count)
        char.continues_normal_attack.assert_called_once_with(.35)

    def test_non_echo_repeated_perform_keeps_legacy_full_rotation(self):
        char = self.perform_char(echo=False)
        char.do_perform()
        char.do_perform()
        self.assertEqual(2, char.opening_normal_attack_burst.call_count)
        self.assertEqual(2, char.perform_everything.call_count)
        self.assertEqual(2, char._execute_lib1_or_fallback_guard.call_count)
        char.continues_normal_attack.assert_not_called()

    def guard_char(self):
        char = self.aemeath()
        char.rotation_timeout = Mock(return_value=5)
        char.cast_enhanced_e_if_ready = Mock(return_value=False)
        char.handle_heavy = Mock(return_value=False)
        char.click = Mock()
        return char

    def test_second_r_uses_fresh_frame_before_persistent_e_and_heavy_signals(self):
        char = self.guard_char()
        events = []
        char.task.next_frame.side_effect = lambda: events.append('frame')
        char.lib2_available = Mock(side_effect=lambda: events.append('lib2') or True)
        char.lib = Mock(return_value=True)
        char.cast_enhanced_e_if_ready.return_value = True
        char.handle_heavy.return_value = True
        with patch('src.char.Aemeath.time.monotonic', return_value=0):
            Aemeath._execute_lib2_guard(char)
        self.assertEqual(['frame', 'lib2'], events)
        char.lib.assert_called_once()
        char.cast_enhanced_e_if_ready.assert_not_called()
        char.handle_heavy.assert_not_called()

    def test_guard_passes_remaining_deadline_to_heavy_followup(self):
        char = self.guard_char()
        clock = [0]
        def heavy(**kwargs):
            clock[0] = 5
            return True
        char.handle_heavy.side_effect = heavy
        with patch('src.char.Aemeath.time.monotonic', side_effect=lambda: clock[0]):
            Aemeath._execute_lib2_guard(char)
        char.handle_heavy.assert_called_once_with(deadline=5)
        char.click.assert_not_called()

    def test_guard_does_not_issue_actions_when_health_check_consumes_budget(self):
        char = self.guard_char()
        clock = [0]
        char.task.check_combat.side_effect = lambda: clock.__setitem__(0, 6)
        with patch('src.char.Aemeath.time.monotonic', side_effect=lambda: clock[0]):
            Aemeath._execute_lib2_guard(char)
        char.lib2_available.assert_not_called()
        char.cast_enhanced_e_if_ready.assert_not_called()
        char.handle_heavy.assert_not_called()
        char.click.assert_not_called()

    def test_post_heavy_does_not_start_more_presses_after_native_chunk_overrun(self):
        char = self.aemeath()
        clock = [0]
        char.sleep = Mock()
        char.task.native_attack_string = Mock(
            side_effect=lambda *args: clock.__setitem__(0, 6) or True)
        with patch('src.char.Aemeath.time.monotonic', side_effect=lambda: clock[0]):
            char.post_heavy_normal_attack_burst(deadline=5)
        char.task.native_attack_string.assert_called_once_with(
            1, char.POST_HEAVY_NORMAL_ATTACK_INTERVAL)

    def test_post_heavy_skips_input_if_fresh_health_check_uses_remaining_time(self):
        char = self.aemeath()
        clock = [0]
        char.sleep = Mock()
        char.task.check_combat.side_effect = lambda: clock.__setitem__(0, 6)
        char.task.native_attack_string = Mock()
        char.click = Mock()
        with patch('src.char.Aemeath.time.monotonic', side_effect=lambda: clock[0]):
            char.post_heavy_normal_attack_burst(deadline=5)
        char.task.native_attack_string.assert_not_called()
        char.click.assert_not_called()

    def test_bounded_heavy_releases_mouse_on_health_guard_failure(self):
        char = self.aemeath()
        char.task.mouse_down = Mock()
        char.task.check_combat.side_effect = RuntimeError('low health')
        with patch('src.char.Aemeath.time.monotonic', return_value=0), \
                self.assertRaisesRegex(RuntimeError, 'low health'):
            char.heavy_wait_highlight_down(deadline=5)
        char.task.mouse_down.assert_called_once()
        char.task.mouse_up.assert_called_once()

    def test_bounded_heavy_stops_if_guard_released_the_hold(self):
        char = self.aemeath()
        char.task.mouse_down = Mock()
        char.sleep = Mock()
        char.heavy_ready_state = Mock(return_value='mecha')
        char.task.check_combat.side_effect = lambda: setattr(
            char.task, 'held_attack_interrupted', True)
        with patch('src.char.Aemeath.time.monotonic', return_value=0):
            self.assertFalse(char.heavy_wait_highlight_down(deadline=5))
        char.task.mouse_up.assert_called_once()
        char.task.next_frame.assert_not_called()

    def test_expired_heavy_budget_does_not_press_mouse(self):
        char = self.aemeath()
        char.task.mouse_down = Mock()
        with patch('src.char.Aemeath.time.monotonic', return_value=5):
            self.assertFalse(char.heavy_wait_highlight_down(deadline=5))
        char.task.mouse_down.assert_not_called()

    def team(self, current, echo=True, chain_done=False):
        task = DetonationTeam()
        task._verified_battle = True
        task.combat_start = 100
        task.allow_opportunistic_skills = lambda: echo
        task.chars = [SimpleNamespace(char_name=name, confidence=.99,
                                     last_switch_in_time=100,
                                     _detonation_chain_done=chain_done)
                      for name in ORDER]
        task.get_current_char = Mock(return_value=next(c for c in task.chars if c.char_name == current))
        return task

    def test_completed_chisa_chain_does_not_wait_24_seconds_for_zero_ring(self):
        task = self.team('char_chisa', chain_done=True)
        with patch('time.time', return_value=105):
            self.assertTrue(task.wait_for_full_con_before_switch())
        with patch('time.time', return_value=107):
            self.assertFalse(task.wait_for_full_con_before_switch())

    def test_unfinished_chisa_and_damage_visits_still_have_finite_echo_budgets(self):
        chisa = self.team('char_chisa')
        damage = self.team('char_aemeath')
        with patch('time.time', return_value=107):
            self.assertTrue(chisa.wait_for_full_con_before_switch())
        with patch('time.time', return_value=109):
            self.assertFalse(chisa.wait_for_full_con_before_switch())
            self.assertTrue(damage.wait_for_full_con_before_switch())
        with patch('time.time', return_value=113):
            self.assertFalse(damage.wait_for_full_con_before_switch())

    def test_material_domain_uses_short_support_budget_too(self):
        task = self.team('char_chisa', echo=False, chain_done=True)
        with patch('time.time', return_value=105):
            self.assertTrue(task.wait_for_full_con_before_switch())
        with patch('time.time', return_value=107):
            self.assertFalse(task.wait_for_full_con_before_switch())


if __name__ == '__main__':
    unittest.main()
