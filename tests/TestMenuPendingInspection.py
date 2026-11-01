"""Pending spending permits screenshots, never a menu action or mixed queue."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.task.MenuInspectionTask import MenuInspectionTask


class TestMenuPendingInspection(unittest.TestCase):
    def task(self, action='inspect', steps=None):
        return SimpleNamespace(
            phase='menu-step', menu_steps=steps, menu_action=action,
            menu_expect='标题' if action != 'inspect' else '',
            expected_target='按钮', menu_point=[.5, .5], menu_scroll=None,
            menu_after_expect='', result=None,
            assert_no_pending_refill=Mock(side_effect=RuntimeError('pending')),
            focus_material_menu=Mock(), execute_menu_step=Mock(),
            save_menu_observation=Mock(return_value={'image': 'saved.png'}),
            mouse_up=Mock(), save_menu_result=Mock())

    def test_inspection_remains_available_without_clearing_pending(self):
        task = self.task()
        MenuInspectionTask.run(task)
        task.assert_no_pending_refill.assert_not_called()
        self.assertEqual('inspect', task.execute_menu_step.call_args.args[0]['action'])
        self.assertEqual('menu_observed', task.result['status'])

    def test_action_is_blocked_before_focus_or_input(self):
        task = self.task(action='point')
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            MenuInspectionTask.run(task)
        task.focus_material_menu.assert_not_called()
        task.execute_menu_step.assert_not_called()

    def test_mixed_batch_is_blocked_before_any_step(self):
        task = self.task(steps=[
            {'action': 'inspect', 'expect': '标题'},
            {'action': 'text', 'expect': '标题', 'target': '按钮'}])
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            MenuInspectionTask.run(task)
        task.focus_material_menu.assert_not_called()
        task.execute_menu_step.assert_not_called()
