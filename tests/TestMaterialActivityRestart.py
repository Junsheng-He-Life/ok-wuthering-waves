"""Reusing a GUI task cannot account for a previous claim twice."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.task.MaterialActivity import MaterialActivity, SOLVENT_TOTAL_CONFIG
from src.task.TeamMaterialTask import TeamMaterialTask


class TestMaterialActivityRestart(unittest.TestCase):
    def task(self, folder, uncertain=False):
        task = TeamMaterialTask.__new__(TeamMaterialTask)
        task.activity_path = Path(folder) / 'activity.json'
        activity = MaterialActivity(task.activity_path)
        activity.data['history_verified'] = True
        activity.save()
        task.state_path = Path(folder) / 'progress.json'
        task.state_path.write_text(json.dumps({
            'claim_pending': False, 'workflow': {'job_index': 0},
            'next_job': 0, 'completed_jobs': [],
            'jobs': [{'target': '心', 'kind': '武器/技能', 'cost': 40}]}))
        task.phase = 'claim'
        task.target_override = '心'
        task.config = {'本次最多领奖': 1, '本次波片上限': 40,
                       '本次储备上限': 5, '本次溶剂上限': 1,
                       SOLVENT_TOTAL_CONFIG: 10}
        for name in ('assert_no_pending_refill', 'info_set', 'focus_material_menu',
                     'restore_reward_dialog', 'send_key', 'leave_verified_domain',
                     'heal_at_beacon', 'save_run_report'):
            setattr(task, name, Mock())
        task.in_realm = task.find_treasure_icon = Mock(return_value=True)

        def claim(budget):
            budget.record_refill(5)
            budget.record_solvent()
            budget.begin_claim()
            task.checkpoint_claim()
            if uncertain:
                raise RuntimeError('claim result unknown')
            budget.finish_claim(80, 40)
            task.checkpoint_claim()
        task.claim_one_reward = Mock(side_effect=claim)
        return task

    def totals(self, task):
        data = MaterialActivity(task.activity_path).data
        return tuple(data[key] for key in ('claim_units', 'waveplates_spent',
                                           'reserve_waveplates_used', 'solvents_used'))

    @patch('src.task.MaterialNeedsReport.write_needs_report')
    def test_claim_then_new_run_does_not_recount_settlement(self, report):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task.run()
            self.assertEqual((1, 40, 5, 1), self.totals(task))
            task.phase = 'loop'
            task.run_material_plan = Mock()
            task.run()
            self.assertEqual((1, 40, 5, 1), self.totals(task))
            task.phase = 'claim'
            task.run()
            self.assertEqual((2, 80, 10, 2), self.totals(task))

    @patch('src.task.MaterialNeedsReport.write_needs_report')
    def test_uncertain_claim_remains_blocked_without_recounting_refill(self, report):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, uncertain=True)
            with self.assertRaisesRegex(RuntimeError, 'claim result unknown'):
                task.run()
            self.assertEqual((0, 0, 5, 1), self.totals(task))
            self.assertTrue(json.loads(task.state_path.read_text())['claim_pending'])
            task.phase = 'loop'
            task.focus_material_menu.reset_mock()
            with self.assertRaisesRegex(RuntimeError, '上次领奖结果未确认'):
                task.run()
            self.assertEqual((0, 0, 5, 1), self.totals(task))
            task.focus_material_menu.assert_not_called()
            self.assertTrue(json.loads(task.state_path.read_text())['claim_pending'])


if __name__ == '__main__':
    unittest.main()
