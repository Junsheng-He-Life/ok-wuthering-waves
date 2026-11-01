"""Offline restarts must observe all current targets before scheduling work."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.TeamMaterialTask import TeamMaterialTask


class TestMaterialPlanRefresh(unittest.TestCase):
    names = ['爱弥斯', '达妮娅', '千咲']

    def task(self, folder, previous, continuous=False):
        task = TeamMaterialTask.__new__(TeamMaterialTask)
        task.state_path = Path(folder) / 'needs.json'
        task.state_path.write_text(json.dumps(previous))
        # Deliberately no activity file: restart does not depend on reading an
        # old event to decide which target needs a fresh inventory observation.
        task.activity_path = Path(folder) / 'missing-activity.json'
        task.config = {task.TARGET_NAMES_CONFIG: '', task.SINGLE_TARGET_CONFIG: '',
                       '持续轮刷': continuous, '重置已完成进度': False,
                       '本次最多领奖': 2, '本次波片上限': 80,
                       '本次储备上限': 0, '本次溶剂上限': 0}
        task.chars = [SimpleNamespace(char_name=name, confidence=.99)
                      for name in ('char_aemeath', 'char_denia', 'char_chisa')]
        task._activity = SimpleNamespace(solvent_allowance=Mock(return_value=0))
        for method in ('assert_no_pending_refill', 'focus_material_menu',
                       'return_to_world', 'load_chars', 'info_set', 'log_info',
                       'update_activity', 'write_progress', 'save_run_report'):
            setattr(task, method, Mock())
        task.load_chars.return_value = True
        task.refresh_changed_targets = Mock(side_effect=AssertionError('partial restart scan'))
        # Deferred jobs exercise queue initialization without constructing any
        # device, controller or combat task.
        task.scan_required_jobs = Mock(return_value=[{
            'target': name, 'kind': '武器/技能', 'repeat': 0, 'cost': 40,
            'material_counts': [[0, 10]], 'satisfied': False,
            'deferred_reason': 'offline fixture: no game route',
            'route': {'category': 'ningsu', 'fallback_stage_name': ''},
        } for name in self.names])
        return task

    def test_completed_checkpoint_cannot_hide_new_material_needs(self):
        for continuous in (False, True):
            with self.subTest(continuous=continuous), tempfile.TemporaryDirectory() as folder:
                previous = {'jobs': [{'target': n, 'satisfied': True} for n in self.names],
                            'next_job': 3, 'completed_jobs': [0, 1, 2], 'claim_pending': False}
                task = self.task(folder, previous, continuous)
                task.run_material_plan()
                task.scan_required_jobs.assert_called_once_with(self.names)
                task.refresh_changed_targets.assert_not_called()
                self.assertEqual([], task.progress['completed_jobs'])
                self.assertTrue(all(not j['satisfied'] for j in task.progress['jobs']))
                self.assertEqual(self.names, task.progress['targets'])
                self.assertEqual([c.char_name for c in task.chars], task.progress['roster'])
                self.assertIn('observed_at', task.progress)

    def test_single_target_checkpoint_cannot_omit_other_party_members(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {'jobs': [{'target': self.names[0]}],
                                      'next_job': 1, 'claim_pending': False})
            task.run_material_plan()
            task.scan_required_jobs.assert_called_once_with(self.names)
            self.assertEqual(3, len(task.progress['jobs']))

    def test_uncertain_claim_stops_before_any_game_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {'claim_pending': True})
            with self.assertRaisesRegex(RuntimeError, '上次领奖结果未确认'):
                task.run_material_plan()
            task.focus_material_menu.assert_not_called()
            task.load_chars.assert_not_called()
            task.scan_required_jobs.assert_not_called()
            task.write_progress.assert_not_called()

    def test_failed_party_observation_cannot_reuse_old_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = {'claim_pending': False, 'jobs': [{'target': '旧目标'}]}
            task = self.task(folder, previous)
            task.load_chars.return_value = None
            with self.assertRaisesRegex(RuntimeError, '本次队伍未识别'):
                task.run_material_plan()
            task.scan_required_jobs.assert_not_called()
            task.write_progress.assert_not_called()
            self.assertEqual(previous, json.loads(task.state_path.read_text()))

    def test_preflight_failure_does_not_publish_previous_success(self):
        task = SimpleNamespace(phase='loop', result={'status': 'plan_completed'},
                               begin_activity=Mock(), update_activity=Mock(),
                               run_material_plan=Mock(side_effect=RuntimeError('本次队伍未识别')))
        with self.assertRaisesRegex(RuntimeError, '本次队伍未识别'):
            TeamMaterialTask.run(task)
        self.assertEqual('stopped', task.result['status'])
        self.assertEqual('本次队伍未识别', task.result['error'])

    def test_claim_refreshes_all_targets_that_share_the_bag(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {})
            initial = task.scan_required_jobs.return_value
            fresh = json.loads(json.dumps(initial))
            initial[0].pop('deferred_reason')
            for row in fresh:
                row['material_counts'] = [[7, 10]]
            task.scan_required_jobs.side_effect = [initial, fresh]
            def claim(_task):
                _task.shared_budget.begin_claim(2)
                _task.shared_budget.finish_claim(80, 0)
                _task.result = {'status': 'job_completed'}
            with patch('src.task.TeamMaterialTask.SafeMaterialTask.run', autospec=True, side_effect=claim), \
                 patch('src.task.SharedMaterialPlanner.apply_shared_material_plan', side_effect=lambda jobs: jobs):
                task.run_material_plan()
            self.assertEqual([self.names, self.names], [c.args[0] for c in task.scan_required_jobs.call_args_list])
            self.assertTrue(all(j['material_counts'] == [[7, 10]] for j in task.progress['jobs']))

    def test_failed_or_incomplete_scan_preserves_previous_checkpoint(self):
        for incomplete in (False, True):
            with self.subTest(incomplete=incomplete), tempfile.TemporaryDirectory() as folder:
                previous = {'claim_pending': False, 'jobs': [{'target': '旧目标'}]}
                task = self.task(folder, previous)
                if incomplete:
                    task.scan_required_jobs.return_value = task.scan_required_jobs.return_value[:1]
                else:
                    task.scan_required_jobs.side_effect = RuntimeError('unreadable inventory')
                with self.assertRaises(RuntimeError):
                    task.run_material_plan()
                task.write_progress.assert_not_called()
                self.assertEqual(previous, json.loads(task.state_path.read_text()))

    def test_refresh_failure_keeps_verified_reward_and_spending_in_report(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {})
            initial = task.scan_required_jobs.return_value
            initial[0].pop('deferred_reason')
            task.scan_required_jobs.side_effect = [initial, RuntimeError('目标名称未确认')]
            def claim(_task):
                _task.shared_budget.begin_claim(2)
                _task.shared_budget.finish_claim(240, 160)
                _task.result = {'status': 'job_completed', 'current_stage': '完成',
                                'battles': [{'victory': True}], 'stage_seconds': {'战斗': 90}}
            with patch('src.task.TeamMaterialTask.SafeMaterialTask.run', autospec=True, side_effect=claim), \
                 patch('src.task.SharedMaterialPlanner.apply_shared_material_plan', side_effect=lambda jobs: jobs), \
                 self.assertRaisesRegex(RuntimeError, '目标名称未确认'):
                task.run_material_plan()
            self.assertEqual(1, len(task.result['jobs']))
            encounter = task.result['jobs'][0]
            self.assertEqual('job_completed', encounter['status'])
            self.assertEqual('完成', encounter['current_stage'])
            self.assertEqual([{'victory': True}], encounter['battles'])
            self.assertEqual(80, task.result['budget']['spent'])
            self.assertEqual(2, task.result['budget']['claimed'])
            self.assertFalse(task.result['budget']['claim_pending'])
            self.assertEqual('刷新库存', task.progress['workflow']['stage'])
            self.assertEqual([[0, 10]], task.progress['jobs'][0]['material_counts'])

    def test_successful_round_does_not_retry_failed_shared_material(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {}, continuous=True)
            task.config.update({'本次最多领奖': 6, '本次波片上限': 240})
            jobs = task.scan_required_jobs.return_value
            for i, row in enumerate(jobs):
                row.pop('deferred_reason')
                row['material_names'] = ['失败材料' if i != 1 else '可刷材料']
            task.refresh_after_claim = Mock(side_effect=lambda *_: json.loads(json.dumps(jobs)))
            attempts = []
            def run(_task):
                name = _task.plan_job['material_names'][0]
                attempts.append(name)
                self.assertLess(len(attempts), 5, 'failed route repeated across rounds')
                if name == '失败材料':
                    _task.result = {'status': 'job_failed_recovered', 'recovered': True,
                                    'error': 'no healthy ally'}
                else:
                    _task.shared_budget.begin_claim(1)
                    _task.shared_budget.finish_claim(240, 200)
                    _task.result = {'status': 'job_completed'}
                    if attempts.count(name) == 2:
                        _task.plan_job['satisfied'] = True
            with patch('src.task.TeamMaterialTask.SafeMaterialTask.run', autospec=True, side_effect=run), \
                 patch('src.task.SharedMaterialPlanner.apply_shared_material_plan', side_effect=lambda rows: rows):
                task.run_material_plan()
            self.assertEqual(['失败材料', '可刷材料', '可刷材料'], attempts)
            self.assertEqual('plan_paused', task.result['status'])
            self.assertEqual(80, task.result['budget']['spent'])
            self.assertEqual(['失败材料'], task.result['blocked_materials'][0]['material_names'])
            self.assertFalse(jobs[0]['satisfied'])
            self.assertFalse(jobs[2]['satisfied'])
            self.assertEqual({'0', '2'}, set(task.progress['failed_jobs']))

    def test_only_failed_and_unsupported_jobs_stop_without_retry_or_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {}, continuous=True)
            task.scan_required_jobs.return_value[0].pop('deferred_reason')
            def fail(_task):
                _task.result = {'status': 'job_failed_recovered', 'recovered': True,
                                'error': 'battle failed'}
            with patch('src.task.TeamMaterialTask.SafeMaterialTask.run', autospec=True, side_effect=fail) as runner:
                task.run_material_plan()
            runner.assert_called_once()
            self.assertEqual('plan_paused', task.result['status'])
            self.assertEqual(0, task.result['budget']['spent'])
            self.assertEqual([], task.progress['completed_jobs'])

    def test_explicit_material_deferral_matches_exact_names_and_preserves_need(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, {}, continuous=True)
            jobs = task.scan_required_jobs.return_value
            for i, row in enumerate(jobs):
                row.pop('deferred_reason')
                row['material_names'] = ['待查材料' if i != 1 else '待查材料另一种']
            task.deferred_material_names = ['待查材料']
            task.refresh_after_claim = Mock(side_effect=lambda *_: json.loads(json.dumps(jobs)))
            def claim(_task):
                self.assertEqual(['待查材料另一种'], _task.plan_job['material_names'])
                _task.shared_budget.begin_claim(2)
                _task.shared_budget.finish_claim(240, 160)
                _task.result = {'status': 'job_completed'}
            with patch('src.task.TeamMaterialTask.SafeMaterialTask.run', autospec=True, side_effect=claim) as runner, \
                 patch('src.task.SharedMaterialPlanner.apply_shared_material_plan', side_effect=lambda rows: rows):
                task.run_material_plan()
            runner.assert_called_once()
            self.assertEqual([1], task.progress['completed_jobs'])
            self.assertFalse(jobs[0]['satisfied'])
            self.assertFalse(jobs[2]['satisfied'])
            self.assertEqual(['待查材料'], task.result['deferred_material_names'])


if __name__ == '__main__':
    unittest.main()
