"""Shared-bag refreshes preserve demand, uncertainty and full-scan fallback."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from src.task.NamedMaterialRefresh import refresh_targets, merge_inventory_refresh, FullMaterialRefreshRequired, sync_observed_inventory
from src.task.MaterialIdentity import aggregate_named_materials
from src.task.CrossTeamMaterialTask import CrossTeamMaterialTask


def job(target, names, stock, need, kind='武器/技能'):
    return dict(target=target, kind=kind, repeat=0, route={'category': 'ningsu'},
                material_names=names, material_counts=[[a, b] for a, b in zip(stock, need)],
                observed_at='old', satisfied=False)


class TestNamedMaterialRefresh(unittest.TestCase):
    def initial(self):
        return [job('心', ['凝固的弦线', '如歌的弦线'], [71, 6], [10, 60]),
                job('达妮娅', ['凝固的弦线', '如歌的弦线'], [71, 6], [37, 76]),
                job('穗穗', ['凝固的弦线', '如歌的弦线'], [71, 6], [38, 65]),
                job('安可', ['贝币'], [123, ], [999], '贝币'),
                job('长离', ['其他材料'], [0], [8])]

    def test_cover_reward_names_and_common_rewards_without_scanning_all_peers(self):
        jobs = self.initial()
        targets, needed = refresh_targets(jobs, jobs[1])
        self.assertEqual(['达妮娅', '安可'], targets)
        self.assertEqual({'凝固的弦线', '如歌的弦线', '贝币'}, needed)

    def test_new_inventory_is_counted_once_without_changing_other_role_requirements(self):
        jobs = self.initial()
        fresh = deepcopy([jobs[1], jobs[3]])
        fresh[0]['material_counts'] = [[75, 37], [7, 76]]
        fresh[1]['material_counts'] = [[234, 999]]
        for j in fresh:
            j['observed_at'] = 'new'
        merged = merge_inventory_refresh(jobs, fresh, ['达妮娅', '安可'], {'凝固的弦线', '如歌的弦线', '贝币'})
        self.assertEqual([[75, 10], [7, 60]], merged[0]['material_counts'])
        self.assertEqual([[75, 38], [7, 65]], merged[2]['material_counts'])
        rows, _ = aggregate_named_materials(merged)
        by_name = {r['item_name']: r for r in rows}
        self.assertEqual((75, 85, 10), tuple(by_name['凝固的弦线'][k] for k in ('inventory', 'required_total', 'raw_missing')))
        self.assertEqual('new', by_name['凝固的弦线']['inventory_observed_at'])
        self.assertEqual('old', by_name['其他材料']['inventory_observed_at'])
        self.assertEqual(71, jobs[0]['material_counts'][0][0])

    def test_conflict_missing_read_or_decrease_requires_full_refresh_without_mutation(self):
        for mode in ('conflict', 'missing', 'decrease', 'changed_need'):
            jobs = self.initial()
            before = deepcopy(jobs)
            fresh = deepcopy(jobs[:2])
            fresh[0]['material_counts'][0][0] = 75
            fresh[1]['material_counts'][0][0] = 75
            if mode == 'conflict':
                fresh[1]['material_counts'][0][0] = 76
            elif mode == 'missing':
                fresh.pop()
            elif mode == 'decrease':
                fresh[0]['material_counts'][0][0] = 70
                fresh[1]['material_counts'][0][0] = 70
            else:
                fresh[0]['material_names'] = ['新材料', '如歌的弦线']
            with self.subTest(mode=mode), self.assertRaises(FullMaterialRefreshRequired):
                merge_inventory_refresh(jobs, fresh, ['心', '达妮娅'], {'凝固的弦线'})
            self.assertEqual(before, jobs)

    def test_unknown_reward_or_unsupported_route_forces_full_scan(self):
        jobs = self.initial()
        jobs[3].pop('material_names')
        self.assertIsNone(refresh_targets(jobs, jobs[1]))
        jobs = self.initial()
        jobs[1]['kind'] = '周本'
        self.assertIsNone(refresh_targets(jobs, jobs[1]))

    def test_periodic_full_refresh_cannot_be_skipped(self):
        jobs = self.initial()
        task = SimpleNamespace(plan_job=jobs[1], _targeted_refreshes=2,
                               scan_required_jobs=Mock(return_value=jobs))
        self.assertEqual(jobs, CrossTeamMaterialTask.refresh_after_claim(task, jobs, ['心', '达妮娅', '穗穗', '安可', '长离']))
        task.scan_required_jobs.assert_called_once()

    def test_incomplete_target_refresh_falls_back_to_complete_scan(self):
        jobs = self.initial()
        task = SimpleNamespace(plan_job=jobs[1], _targeted_refreshes=0, set_workflow_stage=Mock(),
            record_event=Mock(), publish_named_snapshot=Mock(), scan_required_jobs=Mock(return_value=jobs))
        with patch('src.task.NamedMaterialScan.NamedMaterialScanner') as scanner:
            scanner.return_value.scan.return_value = []
            CrossTeamMaterialTask.refresh_after_claim(task, jobs, ['心', '达妮娅', '穗穗', '安可', '长离'])
        task.scan_required_jobs.assert_called_once()
        self.assertEqual('full_refresh_fallback', task.record_event.call_args.args[0])

    def test_entry_check_refreshes_incidental_stock_and_skips_satisfied_shared_need(self):
        from src.task.CultivationTargetUI import NoCurrentMaterialNeed
        jobs = self.initial()[:3]
        for row in jobs:
            row['identity_source'] = 'verified_icon'
        observed = deepcopy(jobs[1])
        observed['material_counts'] = [[100, 37], [250, 76]]
        observed['observed_at'] = 'entry'
        task = SimpleNamespace(plan_job=jobs[1], expected_target='达妮娅', progress={'jobs': jobs},
                               reset_material_list_top=Mock(), write_progress=Mock())
        with patch('src.task.NamedMaterialScan.NamedMaterialScanner') as scanner:
            scanner.return_value.page.return_value = ([observed], False)
            with self.assertRaises(NoCurrentMaterialNeed):
                CrossTeamMaterialTask.preflight_material_job(task)
        self.assertEqual([[100, 10], [250, 60]], jobs[0]['material_counts'])
        self.assertTrue(all(j['satisfied'] for j in jobs))

    def test_unknown_items_remain_unsatisfied_after_named_inventory_update(self):
        jobs = self.initial()
        jobs.append(dict(target='待核对角色', kind='采集', material_counts=[], satisfied=False))
        result = sync_observed_inventory(jobs, [jobs[0]])
        self.assertFalse(result[-1]['satisfied'])

    def test_terminal_summary_requires_full_scan_after_targeted_refresh(self):
        jobs = self.initial()
        task = CrossTeamMaterialTask.__new__(CrossTeamMaterialTask)
        task.config = {}
        task.progress = {'jobs': deepcopy(jobs)}
        task.result = {'status': 'plan_completed'}
        task.requested_material_targets = list(dict.fromkeys(j['target'] for j in jobs))
        task._targeted_refreshes = 1
        task.prepare_teams = task.set_workflow_stage = task.write_progress = task.record_event = Mock()
        task.scan_required_jobs = Mock(return_value=deepcopy(jobs))
        with patch('src.task.TeamMaterialTask.TeamMaterialTask.run_material_plan'):
            task.run_material_plan()
        task.scan_required_jobs.assert_called_once_with(task.requested_material_targets)
        self.assertEqual('materials_remaining', task.result['status'])
