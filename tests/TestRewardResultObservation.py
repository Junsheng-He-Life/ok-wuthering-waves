"""Settlement rereads never repeat a claim or relax the verified debit."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from scripts.test_material_stability import isolated_test_workspace
from src.task.MaterialRewardUI import MaterialRewardUI
from src.task.MaterialRunBudget import MaterialRunBudget


class TestRewardResultObservation(unittest.TestCase):
    def task(self, readings, success=True):
        task = MaterialRewardUI()
        task.result = {}
        task.frame = np.zeros((12, 20, 3), np.uint8)
        task.next_frame = Mock()
        task.log_info = Mock()
        task.click_box = Mock()
        values = iter(readings)

        def read(pattern, *args, **kwargs):
            if pattern.startswith('挑战成功'):
                return success
            value = next(values)
            return SimpleNamespace(name=f'剩余{value}') if value is not None else None

        task.reward_text = read
        return task

    def budget(self):
        budget = MaterialRunBudget(2, 120, 0, 0, claim_cost=60)
        budget.begin_claim(2)
        return budget

    def test_transitional_wrong_number_is_reread_without_click(self):
        with isolated_test_workspace():
            task = self.task([138, 18])
            budget = self.budget()
            checkpoint = Mock()
            self.assertEqual(18, task.verify_reward_result(budget, 138, checkpoint))
            self.assertEqual((2, 120, False), (budget.claimed, budget.spent, budget.claim_pending))
            self.assertEqual(1, task.next_frame.call_count)
            task.click_box.assert_not_called()
            checkpoint.assert_called_once()
            observations = task.result['reward_observations']
            self.assertEqual([False, True], [row['matched'] for row in observations])
            for row in observations:
                self.assertTrue(Path(row['image']).is_file())
                saved = json.loads(Path(row['image']).with_suffix('.json').read_text())
                self.assertEqual(138, saved['stamina_before'])
                self.assertEqual(120, saved['expected_cost'])

    def test_all_wrong_numbers_preserve_pending_and_every_observation(self):
        with isolated_test_workspace():
            task = self.task([138, 118, 88])
            budget = self.budget()
            checkpoint = Mock()
            with self.assertRaisesRegex(RuntimeError, 'delta uncertain after 3 observations'):
                task.verify_reward_result(budget, 138, checkpoint)
            self.assertEqual((0, 0, True), (budget.claimed, budget.spent, budget.claim_pending))
            self.assertEqual(2, task.next_frame.call_count)
            self.assertEqual(['剩余138', '剩余118', '剩余88'],
                             [r['raw'] for r in task.result['reward_observations']])
            checkpoint.assert_not_called()
            task.click_box.assert_not_called()
            self.assertFalse(hasattr(task, '_last_claim_stamina'))

    def test_one_natural_regeneration_tick_remains_allowed(self):
        with isolated_test_workspace():
            task = self.task([19])
            budget = self.budget()
            self.assertEqual(19, task.verify_reward_result(budget, 138))
            self.assertEqual(120, budget.spent)
            self.assertFalse(budget.claim_pending)
            task.next_frame.assert_not_called()

    def test_two_ticks_do_not_silently_expand_cost_tolerance(self):
        with isolated_test_workspace():
            task = self.task([20, 20, 20])
            budget = self.budget()
            with self.assertRaisesRegex(RuntimeError, 'delta uncertain'):
                task.verify_reward_result(budget, 138)
            self.assertTrue(budget.claim_pending)
            self.assertEqual(0, budget.spent)

    def test_unreadable_then_wrong_then_valid_uses_only_three_observations(self):
        with isolated_test_workspace():
            task = self.task([None, 118, 18])
            self.assertEqual(18, task.verify_reward_result(self.budget(), 138))
            self.assertEqual(2, task.next_frame.call_count)
            self.assertIsNone(task.result['reward_observations'][0]['stamina_after'])
            task.click_box.assert_not_called()

    def test_missing_success_marker_never_finishes_or_reads_remaining(self):
        with isolated_test_workspace():
            task = self.task([], success=False)
            budget = self.budget()
            with self.assertRaisesRegex(RuntimeError, 'settlement uncertain'):
                task.verify_reward_result(budget, 138)
            self.assertTrue(budget.claim_pending)
            self.assertNotIn('reward_observations', task.result)
            task.click_box.assert_not_called()

    def test_original_claim_click_is_not_replayed_by_result_retry(self):
        with isolated_test_workspace():
            task = self.task([138, 18])
            task.open_verified_reward = Mock()
            task.get_stamina = Mock(return_value=(138, 0, 138))
            task.reward_option = Mock(return_value=(object(), 2))
            task.checkpoint_claim = Mock()
            budget = MaterialRunBudget(2, 120, 0, 0, claim_cost=60)
            self.assertEqual(18, task.claim_one_reward(budget))
            task.click_box.assert_called_once()
            self.assertEqual(138, task._claim_observation_context['stamina_before'])
            self.assertEqual(120, task._claim_observation_context['expected_cost'])


if __name__ == '__main__':
    unittest.main()
