"""Offline regressions for changing rosters and injured rotation members."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.Labels import Labels
from src.char.BaseChar import BaseChar, CharType
from src.char.CharFactory import get_char_by_pos
from src.combat.XuanlingTeam import XuanlingTeam, ORDER
from src.task.BaseCombatTask import BaseCombatTask
from src.task.CharacterMaterialTask import CharacterMaterialTask


class TestTeamCombatAdaptation(unittest.TestCase):
    def recognition(self, trust_cache=False, match=True):
        task = SimpleNamespace(
            debug=False, char_config={}, log_info=Mock(),
            trust_cached_character_hints=lambda: trust_cache,
            find_best_match_in_box=Mock(return_value=(
                SimpleNamespace(name=Labels.char_phrolova, confidence=.99)
                if match else None)),
        )
        old = BaseChar(task, 0, char_name=Labels.yangyang_sp, confidence=.99)
        return task, old

    def test_strict_scan_selects_new_roster_over_plausible_old_portrait(self):
        task, old = self.recognition()
        # A superficially matching old avatar must not stop the full scan.
        with patch('src.char.CharFactory.get_char_by_hint', return_value=old) as hint:
            char = get_char_by_pos(task, None, 0, old)
        self.assertEqual(Labels.char_phrolova, char.char_name)
        self.assertIsNot(old, char)
        hint.assert_not_called()
        task.find_best_match_in_box.assert_called_once()

    def test_strict_scan_does_not_reuse_old_roster_when_unreadable(self):
        task, old = self.recognition(match=False)
        with patch('src.char.CharFactory.get_char_by_hint', return_value=old) as hint:
            char = get_char_by_pos(task, None, 0, old)
        self.assertEqual('unknown', char.char_name)
        self.assertIsNot(old, char)
        hint.assert_not_called()

    def test_tasks_permitting_verified_cached_portraits_keep_fast_path(self):
        task, old = self.recognition(trust_cache=True)
        with patch('src.char.CharFactory.get_char_by_hint', return_value=old) as hint:
            char = get_char_by_pos(task, None, 0, old)
        self.assertIs(old, char)
        hint.assert_called_once()
        task.find_best_match_in_box.assert_not_called()

    def farming_task(self, char_type=CharType.MAIN_DPS):
        task = CharacterMaterialTask.__new__(CharacterMaterialTask)
        char = BaseChar(task, 0, char_type=char_type)
        char.last_switch_in_time = 100
        task.combat_start = 90
        task.get_current_char = Mock(return_value=char)
        return task, char

    def test_generic_team_releases_unfilled_concerto_after_twelve_seconds(self):
        task, _ = self.farming_task()
        with patch('src.task.CharacterMaterialTask.time.time', return_value=111.9):
            self.assertTrue(task.wait_for_full_con_before_switch())
        with patch('src.task.CharacterMaterialTask.time.time', return_value=112):
            self.assertFalse(task.wait_for_full_con_before_switch())

    def test_generic_healer_has_bounded_eighteen_second_window(self):
        task, _ = self.farming_task(CharType.HEALER)
        with patch('src.task.CharacterMaterialTask.time.time', return_value=117.9):
            self.assertTrue(task.wait_for_full_con_before_switch())
        with patch('src.task.CharacterMaterialTask.time.time', return_value=118):
            self.assertFalse(task.wait_for_full_con_before_switch())

    def test_new_battle_does_not_inherit_elapsed_window_from_previous_battle(self):
        task, _ = self.farming_task()
        task.combat_start = 200
        with patch('src.task.CharacterMaterialTask.time.time', return_value=201):
            self.assertTrue(task.wait_for_full_con_before_switch())

    def test_unknown_current_slot_does_not_wait_for_a_stale_ring(self):
        task, _ = self.farming_task()
        task.get_current_char.return_value = None
        self.assertFalse(task.wait_for_full_con_before_switch())

    def switching_task(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = [BaseChar(task, i) for i in range(3)]
        task.preferred_switch_target = Mock(side_effect=lambda current, candidates, intro: candidates[0])
        return task, task.chars

    def test_recovering_member_is_excluded_before_team_preference(self):
        task, chars = self.switching_task()
        chars[1].recovery_until = 130
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=100):
            self.assertIs(chars[2], task._choose_switch_target(chars[0], True))
        self.assertEqual([chars[2]], task.preferred_switch_target.call_args.args[1])

    def test_recovery_expiry_restores_member_to_rotation(self):
        task, chars = self.switching_task()
        chars[1].recovery_until = 130
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=130):
            self.assertIs(chars[1], task._choose_switch_target(chars[0], True))

    def test_all_other_members_recovering_keeps_current_character(self):
        task, chars = self.switching_task()
        chars[1].recovery_until = chars[2].recovery_until = float('inf')
        self.assertIs(chars[0], task._choose_switch_target(chars[0], False))
        task.preferred_switch_target.assert_not_called()

    def test_reordered_xuanling_team_skips_wounded_healer(self):
        task = XuanlingTeam()
        task.chars = [SimpleNamespace(char_name=name) for name in reversed(ORDER)]
        current = next(c for c in task.chars if c.char_name == 'yangyang_sp')
        healer = next(c for c in task.chars if c.char_name == 'char_suisui')
        healer.recovery_until = float('inf')
        candidates = [c for c in task.chars if c is not current]
        self.assertEqual('char_phrolova', task.preferred_switch_target(current, candidates, True).char_name)


if __name__ == '__main__':
    unittest.main()
