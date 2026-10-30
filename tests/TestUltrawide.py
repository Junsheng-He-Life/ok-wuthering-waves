import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from ok.task.TaskExecutor import TaskExecutor
from src.task.BaseWWTask import BaseWWTask, MATERIAL_TARGET_BOX, MATERIAL_LOCATION_ACTION_BOX
from src.task.MaterialTrialTask import MaterialTrialTask


class TestUltrawide(unittest.TestCase):
    def task(self, width=3440, height=1440):
        task = BaseWWTask.__new__(BaseWWTask)
        task._executor = SimpleNamespace(
            method=SimpleNamespace(width=width, height=height),
            device_manager=SimpleNamespace(supported_ratio=16 / 9),
        )
        return task

    def test_material_panels_keep_size_and_opposite_edge_anchors(self):
        task = self.task()
        target = task.box_of_screen(*MATERIAL_TARGET_BOX)
        action = task.box_of_screen(*MATERIAL_LOCATION_ACTION_BOX)
        self.assertEqual((243, 640), (target.x, target.width))
        self.assertEqual((2992, 346), (action.x, action.width))
        normal = self.task(2560, 1440)
        self.assertEqual(target, normal.box_of_screen(*MATERIAL_TARGET_BOX))
        self.assertEqual(880, action.x - normal.box_of_screen(*MATERIAL_LOCATION_ACTION_BOX).x)

    def test_reward_marker_search_covers_ultrawide_right_side(self):
        task = self.task()
        task.find_one = Mock(return_value=None)
        task.find_treasure_icon()
        viewport = task.find_one.call_args.kwargs['box']
        self.assertLess(viewport.x, 2660)
        self.assertGreater(viewport.x + viewport.width, 2700)
        self.assertGreater(viewport.x + viewport.width, 3300)

    def test_center_click_does_not_drift_to_right_edge(self):
        task = self.task()
        task.click = Mock()
        task.click_relative(.6, .5, hcenter=True)
        self.assertEqual((1976, 720), task.click.call_args.args[:2])

    def test_allowed_display_ratio_preserves_ui_reference(self):
        executor = TaskExecutor.__new__(TaskExecutor)
        method = SimpleNamespace(width=3440, height=1440, get_frame=lambda: np.zeros((1, 1, 3)))
        executor.device_manager = SimpleNamespace(capture_method=method, update_resolution_for_hwnd=lambda: None)
        self.assertTrue(executor.check_frame_and_resolution(['16:9', '43:18'], (1280, 720))[0])

    def test_changed_material_row_never_clicks(self):
        task = self.task()
        task.log_info = Mock()
        task.click_box = Mock()
        task._visible_material_locations = lambda _: []
        with self.assertRaisesRegex(RuntimeError, 'changed before click'):
            task.enter_visible_material_location({'name': '旋雾之森', 'normalized_name': '旋雾之森', 'action': '直接挑战', 'is_direct': True})
        task.click_box.assert_not_called()

    def test_trial_combat_never_uses_reward_or_repeat_loop(self):
        task = MaterialTrialTask.__new__(MaterialTrialTask)
        task._executor = SimpleNamespace(nullable_frame=lambda: None)
        task.phase = 'combat'
        for name in ('walk_to_domain_interaction', 'pick_f', 'combat_once', 'screenshot', '_stop_combat_debug_frame_recorder'):
            setattr(task, name, Mock())
        task.in_team_and_world = lambda: True
        task.find_f_with_text = lambda **_: True
        task.wait_until = lambda *_, **__: True
        task.use_stamina = Mock(side_effect=AssertionError('must not claim'))
        task.farm_in_domain = Mock(side_effect=AssertionError('must not repeat'))
        task.run()
        self.assertEqual('combat_complete_reward_unclaimed', task.result['status'])
        task.combat_once.assert_called_once()
        task.use_stamina.assert_not_called()

    def test_resume_sleep_preserves_manual_exit_guard(self):
        task = MaterialTrialTask.__new__(MaterialTrialTask)
        task.phase = 'resume'
        task._raise_if_manual_exit_before_input = Mock(side_effect=RuntimeError('manual exit'))
        with self.assertRaisesRegex(RuntimeError, 'manual exit'):
            task.sleep_check()

    def test_basic_stops_without_attack_if_hud_does_not_return(self):
        task = MaterialTrialTask.__new__(MaterialTrialTask)
        task._executor = SimpleNamespace(nullable_frame=lambda: None)
        task.phase = 'basic'
        for name in ('walk_to_domain_interaction', 'pick_f', 'click', 'send_key',
                     'screenshot', '_stop_combat_debug_frame_recorder'):
            setattr(task, name, Mock())
        task.in_team_and_world = Mock(side_effect=[True, False])
        task.find_f_with_text = lambda **_: True
        task.find_treasure_icon = lambda: False
        task.wait_until = lambda *_, **__: False
        with self.assertRaisesRegex(RuntimeError, 'HUD disappeared'):
            task.run()
        task.click.assert_not_called()
        task.send_key.assert_not_called()

    def test_approach_requires_visible_reward_chest(self):
        task = MaterialTrialTask.__new__(MaterialTrialTask)
        task._executor = SimpleNamespace(nullable_frame=lambda: None)
        task.phase = 'approach'
        task.in_team_and_world = lambda: True
        task.find_treasure_icon = lambda: False
        task.walk_to_treasure = Mock()
        task.screenshot = Mock()
        task._stop_combat_debug_frame_recorder = Mock()
        with self.assertRaisesRegex(RuntimeError, 'reward chest'):
            task.run()
        task.walk_to_treasure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
