import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.task.BaseCombatTask import BaseCombatTask
from src.task.VerifiedDomainCombat import VerifiedDomainCombat
from src.char.Aemeath import Aemeath


class TestCombatCadence(unittest.TestCase):
    def native_string(self):
        from src.combat.NativeAttackCadence import NativeAttackCadence
        from ok.device.interaction_methods.macos import MacForegroundInteraction
        task = NativeAttackCadence()
        interaction = Mock(spec=MacForegroundInteraction)
        interaction.clickable.return_value = True
        task._verified_battle = True
        task.executor = SimpleNamespace(interaction=interaction,
            check_enabled=Mock(), exit_event=SimpleNamespace(is_set=lambda: False))
        task.check_combat = Mock()
        task.next_frame = Mock()
        task._raise_if_manual_exit_before_input = Mock()
        return task, interaction

    def test_native_attack_string_checks_visuals_between_short_chunks(self):
        task, interaction = self.native_string()
        with patch('src.combat.NativeAttackCadence.sys.platform', 'darwin'), \
                patch('src.combat.NativeAttackCadence.time.sleep'):
            self.assertTrue(task.native_attack_string(7))
        self.assertEqual(7, interaction.click.call_count)
        self.assertEqual(7, task.executor.check_enabled.call_count)
        self.assertEqual(7, task._raise_if_manual_exit_before_input.call_count)
        self.assertEqual(4, task.check_combat.call_count)
        self.assertEqual(3, task.next_frame.call_count)
        for call in interaction.click.call_args_list:
            self.assertEqual(.08, call.kwargs['down_time'])

    def test_native_string_stops_immediately_for_exit_and_foreground_loss(self):
        for manual in (False, True):
            task, interaction = self.native_string()
            if manual:
                task._raise_if_manual_exit_before_input.side_effect = RuntimeError('manual exit')
            else:
                interaction.clickable.return_value = False
            with patch('src.combat.NativeAttackCadence.sys.platform', 'darwin'):
                if manual:
                    with self.assertRaisesRegex(RuntimeError, 'manual exit'):
                        task.native_attack_string(3)
                else:
                    self.assertTrue(task.native_attack_string(3))
            interaction.click.assert_not_called()

    def test_duration_filler_counts_slow_guard_and_input_against_wall_deadline(self):
        task, interaction = self.native_string()
        now = [0.]
        presses = []
        task.check_combat.side_effect = lambda: now.__setitem__(0, now[0] + .6)
        def press(**kwargs):
            presses.append(now[0])
            now[0] += .2
        interaction.click.side_effect = press
        with patch('src.combat.NativeAttackCadence.sys.platform', 'darwin'), \
             patch('src.combat.NativeAttackCadence.time.monotonic', side_effect=lambda: now[0]), \
             patch('src.combat.NativeAttackCadence.time.sleep', side_effect=lambda delay: now.__setitem__(0, now[0]+delay)):
            task.native_attack_string(12, .1, duration=1)
        self.assertEqual(2, len(presses))
        self.assertTrue(all(stamp < 1 for stamp in presses))

    def test_expired_guard_never_replays_a_stale_duration_queue(self):
        task, interaction = self.native_string()
        now = [0.]
        task.check_combat.side_effect = lambda: now.__setitem__(0, 3.)
        with patch('src.combat.NativeAttackCadence.sys.platform', 'darwin'), \
             patch('src.combat.NativeAttackCadence.time.monotonic', side_effect=lambda: now[0]):
            task.native_attack_string(12, duration=2)
        interaction.click.assert_not_called()

    def test_duration_adapter_keeps_fresh_native_frame_when_no_post_delay(self):
        from src.char.BaseChar import BaseChar
        char = SimpleNamespace(task=SimpleNamespace(native_attack_string=Mock(return_value=True)), sleep=Mock())
        BaseChar.continues_normal_attack(char, 2)
        self.assertEqual(2, char.task.native_attack_string.call_args.kwargs['duration'])
        char.sleep.assert_not_called()
        BaseChar.continues_normal_attack(char, 2, after_sleep=.2)
        char.sleep.assert_called_once_with(.2)

    def test_attack_duration_survives_game_facade_coordinate_resolution(self):
        from src.task.BaseWWTask import BaseWWTask
        from ok import BaseTask
        task = BaseWWTask.__new__(BaseWWTask)
        task.width_of_screen = Mock(return_value=1512)
        task.height_of_screen = Mock(return_value=949)
        with patch('src.task.BaseWWTask.sys.platform', 'darwin'), \
                patch.object(BaseTask, 'click') as backend:
            task.click()
            self.assertEqual(.08, backend.call_args.kwargs['down_time'])
            task.click(down_time=.12)
            self.assertEqual(.12, backend.call_args.kwargs['down_time'])
            task.click(100, 200)
            self.assertEqual(.2, backend.call_args.kwargs['down_time'])

    def test_native_bindings_survive_auto_detection_and_force_reload(self):
        task = SimpleNamespace(hot_key_verified=False,
            key_config={'Echo Key':'q', 'Liberation Key':'r', 'Resonance Key':'e'},
            set_key=Mock(), has_short_action=Mock(), info_set=Mock(),
            get_liberation_key=Mock(return_value='r'), get_echo_key=Mock(return_value='q'))
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            BaseCombatTask.load_hotkey(task)
            BaseCombatTask.load_hotkey(task, force=True)
        task.set_key.assert_not_called()
        self.assertEqual('r', task.key_config['Liberation Key'])

    def test_frequent_attack_hooks_do_not_repeat_expensive_reward_search(self):
        task = SimpleNamespace(_verified_battle=True, _battle_deadline=300,
            _battle_end_probe=0, _battle_hud_probe=0, _battle_end_seen=False,
            record_hud=False, _raise_if_manual_exit_before_input=Mock(),
            material_victory_visible=Mock(return_value=False), find_one=Mock(return_value=False),
            in_team_and_world=Mock(return_value=True), guard_material_boss=Mock())
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=10):
            for _ in range(12):
                self.assertTrue(VerifiedDomainCombat.in_combat(task))
        self.assertEqual(1, task.material_victory_visible.call_count)
        self.assertEqual(1, task.in_team_and_world.call_count)
        self.assertEqual(12, task._raise_if_manual_exit_before_input.call_count)
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=10.9):
            VerifiedDomainCombat.in_combat(task)
        self.assertEqual(2, task.material_victory_visible.call_count)

    def test_failed_first_liberation_keeps_attacking_without_waiting_for_second(self):
        char = SimpleNamespace(rotation_timeout=Mock(return_value=1),
            LIB1_FALLBACK_TIME_OUT=5, FAST_LIB1_FALLBACK_TIME_OUT=1,
            check_combat=Mock(), cast_enhanced_e_if_ready=Mock(return_value=False),
            liberation_available=Mock(return_value=True), can_cast_lib1=Mock(return_value=True),
            lib=Mock(return_value=False), _execute_lib2_guard=Mock(), click=Mock(), filler_normal_attacks=Mock(),
            task=SimpleNamespace(next_frame=Mock()), logger=Mock())
        with patch('src.char.Aemeath.time.time', side_effect=[0, .1, 2]):
            Aemeath._execute_lib1_or_fallback_guard(char)
        char._execute_lib2_guard.assert_not_called()
        char.filler_normal_attacks.assert_called_once()

    def test_persistent_heavy_cannot_renew_aemeath_visit(self):
        char = SimpleNamespace(rotation_timeout=Mock(return_value=8),
            should_wait_for_lib2=Mock(return_value=False), should_wait_for_enhance_e=Mock(return_value=False),
            has_intro=False, time_elapsed_accounting_for_freeze=Mock(return_value=0),
            cycle_start=Mock(), cast_enhanced_e_if_ready=Mock(return_value=False),
            click=Mock(), filler_normal_attacks=Mock(), lib=Mock(return_value=False), handle_heavy=Mock(return_value=True),
            f_break=Mock(), cycle_sleep=Mock(), task=SimpleNamespace(next_frame=Mock()))
        with patch('src.char.Aemeath.time.monotonic', side_effect=[0, 1, 9]):
            Aemeath.perform_everything(char)
        char.lib.assert_called_once()
        char.handle_heavy.assert_called_once()

    def test_ready_liberation_precedes_heavy_and_yields_after_visit_limit(self):
        char = SimpleNamespace(rotation_timeout=Mock(return_value=8),
            should_wait_for_lib2=Mock(return_value=True), should_wait_for_enhance_e=Mock(),
            has_intro=False, time_elapsed_accounting_for_freeze=Mock(return_value=0),
            cycle_start=Mock(), cast_enhanced_e_if_ready=Mock(return_value=False),
            click=Mock(), filler_normal_attacks=Mock(), lib=Mock(return_value=True), handle_heavy=Mock(),
            cycle_sleep=Mock(), task=SimpleNamespace(next_frame=Mock()))
        with patch('src.char.Aemeath.time.monotonic', side_effect=[0, 1, 9]):
            Aemeath.perform_everything(char)
        char.lib.assert_called_once()
        char.handle_heavy.assert_not_called()

    def test_aemeath_filler_uses_bounded_three_press_string(self):
        char = SimpleNamespace(task=SimpleNamespace(native_attack_string=Mock(return_value=True)), click=Mock())
        Aemeath.filler_normal_attacks(char)
        char.task.native_attack_string.assert_called_once_with(3, .03)
        char.click.assert_not_called()
        char.task.native_attack_string.return_value = False
        Aemeath.filler_normal_attacks(char)
        char.click.assert_called_once()

    def test_preview_reward_candidate_requires_full_confirmation(self):
        task = VerifiedDomainCombat()
        task._verified_battle = True
        task.find_treasure_icon = Mock(side_effect=[True, False])
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=10):
            self.assertFalse(task.find_battle_reward_marker())
        self.assertEqual({'target_height': 360}, task.find_treasure_icon.call_args_list[0].kwargs)
        self.assertEqual({}, task.find_treasure_icon.call_args_list[1].kwargs)

    def test_preview_negative_gets_periodic_full_resolution_backstop(self):
        task = VerifiedDomainCombat()
        task._verified_battle = True
        task._reward_full_probe_after = 11
        task.find_treasure_icon = Mock(return_value=False)
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=10):
            self.assertFalse(task.find_battle_reward_marker())
        self.assertEqual(1, task.find_treasure_icon.call_count)
        with patch('src.task.VerifiedDomainCombat.time.monotonic', return_value=12):
            task.find_treasure_icon.side_effect = [False, True]
            self.assertTrue(task.find_battle_reward_marker())
