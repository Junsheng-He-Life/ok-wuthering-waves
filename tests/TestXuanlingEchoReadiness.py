"""Replay disabled/ready E icons and preserve uninterrupted held attacks.

The 68x56 crops retain the original E template box from saved 1920x1080
frames 1793277851337177000 (disabled) and 1793188948226169000 (enhanced E).
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
from ok import Box, calculate_color_percentage

from src.char.YangYangSp import YangYangSp
from src.task.BaseCombatTask import BaseCombatTask


class TestXuanlingEchoReadiness(unittest.TestCase):
    def character(self, fixture='echo-xuanling-e-disabled-1920.png', enabled=True, cooldown=False):
        crop = cv2.imread(str(Path(__file__).parent / 'images' / fixture))
        self.assertEqual((56, 68, 3), crop.shape)
        task = SimpleNamespace(
            allow_opportunistic_skills=lambda: enabled,
            has_cd=Mock(return_value=cooldown),
            get_box_by_name=lambda name: Box(0, 0, 68, 56, name=name),
            calculate_color_percentage=lambda color, box: calculate_color_percentage(crop, color, box))
        task.box_highlighted = lambda name: BaseCombatTask.box_highlighted(task, name)
        task.available = lambda name, **kw: BaseCombatTask.available(task, name, **kw)
        char = YangYangSp.__new__(YangYangSp)
        char.task = task
        char.is_current_char = True
        char.logger = Mock()
        task.get_current_char = Mock(return_value=char)
        return char

    def test_gray_e_without_countdown_is_disabled_during_echo_combat(self):
        char = self.character()
        self.assertFalse(char.resonance_available())
        char.task.has_cd.assert_called_once_with('resonance')

    def test_real_enhanced_e_icon_is_ready(self):
        char = self.character('echo-xuanling-e-enhanced-1920.png')
        self.assertTrue(char.resonance_available())

    def test_cooldown_still_blocks_bright_e(self):
        char = self.character('echo-xuanling-e-enhanced-1920.png', cooldown=True)
        self.assertFalse(char.resonance_available())

    def test_other_tasks_keep_original_no_countdown_rule(self):
        char = self.character(enabled=False)
        self.assertTrue(char.resonance_available())

    def rotation_character(self):
        char = self.character()
        actions = []
        char.task.mouse_down = Mock(side_effect=lambda: actions.append('hold'))
        char.task.mouse_up = Mock(side_effect=lambda: actions.append('release'))
        char.task.next_frame = Mock()
        char.has_intro = False
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, .1, .2, 9])
        char.liberation_available = char.echo_available = Mock(return_value=False)
        char.click_resonance = Mock(side_effect=lambda **kw: (
            actions.append('E') or True, 0, False))
        char.click_liberation = Mock()
        char.click_echo = Mock()
        char.sleep = Mock()
        char.check_combat = Mock()
        char.switch_next_char = Mock(side_effect=lambda: actions.append('switch'))
        return char, actions

    def test_gray_e_does_not_release_or_restart_held_attack(self):
        char, actions = self.rotation_character()
        char.do_perform()
        self.assertEqual(['hold', 'release', 'switch'], actions)
        char.click_resonance.assert_not_called()
        char.click_liberation.assert_not_called()
        char.click_echo.assert_not_called()

    def test_e_becomes_ready_at_visit_deadline_before_switch(self):
        char, actions = self.rotation_character()
        char.time_elapsed_accounting_for_freeze.side_effect = [0, 9]
        char.resonance_available = Mock(side_effect=[False, True])
        char.do_perform()
        self.assertEqual(['hold', 'release', 'E', 'switch'], actions)
        char.task.next_frame.assert_called_once()
        char.check_combat.assert_called_once()
        char.click_resonance.assert_called_once_with(send_click=False, time_out=.6)

    def test_persistent_ready_icon_gets_only_one_final_attempt(self):
        char, actions = self.rotation_character()
        char.time_elapsed_accounting_for_freeze.side_effect = [9]
        char.resonance_available = Mock(return_value=True)
        char.do_perform()
        self.assertEqual(['hold', 'release', 'E', 'switch'], actions)
        char.click_resonance.assert_called_once_with(send_click=False, time_out=.6)

    def test_health_exception_in_rotation_does_not_run_final_skill(self):
        char, actions = self.rotation_character()
        char.sleep.side_effect = [RuntimeError('healing requested'), None]
        with self.assertRaisesRegex(RuntimeError, 'healing requested'):
            char.do_perform()
        self.assertEqual(['hold', 'release'], actions)
        char.task.next_frame.assert_not_called()
        char.click_resonance.assert_not_called()
        char.switch_next_char.assert_not_called()

    def test_final_health_guard_prevents_skill_and_switch(self):
        char, actions = self.rotation_character()
        char.time_elapsed_accounting_for_freeze.side_effect = [9]
        char.resonance_available = Mock(return_value=True)
        char.check_combat.side_effect = RuntimeError('healing requested')
        with self.assertRaisesRegex(RuntimeError, 'healing requested'):
            char.do_perform()
        self.assertEqual(['hold', 'release'], actions)
        char.click_resonance.assert_not_called()
        char.switch_next_char.assert_not_called()

    def test_final_skill_does_not_use_another_characters_hud(self):
        char, actions = self.rotation_character()
        char.time_elapsed_accounting_for_freeze.side_effect = [9]
        char.task.get_current_char.return_value = object()
        char.resonance_available = Mock(return_value=True)
        char.do_perform()
        char.resonance_available.assert_not_called()
        char.click_resonance.assert_not_called()


if __name__ == '__main__':
    unittest.main()
