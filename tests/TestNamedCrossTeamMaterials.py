"""Scope, image identity and shared-bag tests without a game backend."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.runtime.DesktopJobs import DesktopRequest
from src.task.MaterialIdentity import MaterialIconLibrary, aggregate_named_materials, named_job_key, popup_identity, refresh_named_jobs
from src.task.PresetTeamUI import parse_team_numbers
from src.task.CrossTeamMaterialTask import CrossTeamMaterialTask
from src.task.SharedMaterialPlanner import apply_shared_material_plan


def job(target, name, owned, required):
    return dict(target=target, kind='突破', repeat=0, material_names=[name],
                material_counts=[[owned, required]], identity_source='verified_icon', satisfied=owned >= required)


class TestNamedCrossTeamMaterials(unittest.TestCase):
    def test_unreadable_target_is_retried_but_unconfirmed_target_never_clicked(self):
        from src.task.NamedMaterialScan import NamedMaterialScanner
        from src.task.MaterialTileVision import MaterialTile
        from ok import Box
        for readings, may_click in (([False, True], True), ([False]*3, False)):
            with self.subTest(readings=readings):
                task = SimpleNamespace(width=1920, height=1080,
                    material_target_matches=Mock(side_effect=readings),
                    click=Mock(side_effect=RuntimeError('verified detail click')))
                def wait(predicate, **kwargs):
                    for _ in range(len(readings)):
                        if predicate():
                            return True
                    return False
                task.wait_until = wait
                scanner = object.__new__(NamedMaterialScanner)
                scanner.task = task
                scanner.library = SimpleNamespace(match=Mock(return_value=None))
                expected = 'verified detail click' if may_click else '培养目标未确认'
                counter = Box(1366, 320, 60, 20, name='75/10')
                counter.material_tile = MaterialTile(1318, 236, 96, 97)
                with self.assertRaisesRegex(RuntimeError, expected):
                    scanner.identify('心', counter,
                                     np.zeros((1080, 1920, 3), dtype=np.uint8))
                self.assertEqual(may_click, task.click.called)

    def test_enlarged_ocr_preserves_source_click_coordinates(self):
        from src.task.MaterialImageOCR import read_enlarged_region
        from ok import Box
        task = SimpleNamespace(frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
                               ocr=Mock(return_value=[Box(50, 80, 150, 120, name='01')]))
        row = read_enlarged_region(task, Box(50, 97, 75, 843))[0]
        self.assertEqual((60, 117, 50, 40), (row.x, row.y, row.width, row.height))
        self.assertEqual((2569, 265, 3), task.ocr.call_args.kwargs['frame'].shape)

    def test_party_scope_is_bounded_and_explicit(self):
        self.assertEqual((1, 2, 3, 4, 5), parse_team_numbers('1,2,3,4,5'))
        for value in ('', '1,1', '0', '11', '2,4,', '2;4', '1-5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_team_numbers(value)

    def test_single_target_requires_fresh_observed_roster(self):
        task = SimpleNamespace(target_override='达妮娅')
        select = CrossTeamMaterialTask.select_material_targets
        self.assertEqual(['达妮娅'], select(task, ['爱弥斯', '达妮娅', '千咲']))
        with self.assertRaisesRegex(RuntimeError, '不在本次核验'):
            select(task, ['心', '今汐', '卜灵'])
        task.target_override = ''
        self.assertEqual(['爱弥斯', '达妮娅'], select(task, ['爱弥斯', '达妮娅', '爱弥斯']))

    def test_single_scope_still_verifies_combat_party(self):
        task = SimpleNamespace(requested_material_targets=['达妮娅'], verify_plan_party=Mock())
        self.assertEqual(['达妮娅'], CrossTeamMaterialTask.resolve_plan_targets(task, '达妮娅'))
        task.verify_plan_party.assert_called_once()
        task.verify_plan_party.reset_mock()
        with self.assertRaisesRegex(RuntimeError, '扫描范围不一致'):
            CrossTeamMaterialTask.resolve_plan_targets(task, '心')
        task.verify_plan_party.assert_not_called()

    def test_xin_has_the_verified_cultivation_name(self):
        from src.task.TeamMaterialTargets import registered_target_name
        self.assertEqual('心', registered_target_name('char_xin'))

    def test_request_retains_one_budget_for_long_running_scope(self):
        args = DesktopRequest(kind='materials', target_teams='1,2,3,4,5', combat_teams='2,4,5',
                              claims=6, waveplates=240).arguments(152)
        for flag, value in (('--target-teams', '1,2,3,4,5'), ('--combat-teams', '2,4,5'),
                            ('--solvent-limit', '0'), ('--reserve-limit', '0'), ('--max-stamina', '240'),
                            ('--solvent-total', '152'), ('--timeout', '0')):
            self.assertEqual(value, args[args.index(flag)+1])
        self.assertIn('--continuous', args)

    def test_same_material_stock_counted_once_and_demand_combined(self):
        jobs = [job('甲', '哀歌声核', 10, 8), job('乙', '哀歌声核', 10, 8)]
        rows, unknown = aggregate_named_materials(jobs)
        self.assertFalse(unknown)
        self.assertEqual((10, 16, 6), (rows[0]['inventory'], rows[0]['required_total'], rows[0]['raw_missing']))
        apply_shared_material_plan(jobs)
        self.assertTrue(all(not r['satisfied'] for r in jobs))

    def test_conflicting_inventory_does_not_choose_larger_or_smaller(self):
        rows, _ = aggregate_named_materials([job('甲', '哀歌声核', 10, 8), job('乙', '哀歌声核', 11, 8)])
        self.assertIsNone(rows[0]['inventory'])
        self.assertIsNone(rows[0]['raw_missing'])

    def test_material_identity_survives_row_reordering(self):
        first = job('甲', '哀歌声核', 0, 8)
        second = dict(first, repeat=4)
        self.assertEqual(named_job_key(first), named_job_key(second))
        self.assertNotEqual(named_job_key(first), named_job_key(job('甲', '其他材料', 0, 8)))

    def test_unknown_names_are_not_replaced_by_row_numbers(self):
        rows, unknown = aggregate_named_materials([{'target': '甲', 'kind': '周本', 'repeat': 2, 'material_counts': [[0, 10]]}])
        self.assertEqual([], rows)
        self.assertIn('待核对', unknown[0]['reason'])

    def test_icon_library_requires_popup_evidence_and_unique_appearance(self):
        rng = np.random.default_rng(42)
        icon = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            library = MaterialIconLibrary(Path(folder)/'identities')
            self.assertIsNone(library.match(icon))
            with self.assertRaises(ValueError):
                library.remember('甲', icon, '')
            library.remember('甲', icon, 'verified-frame.png')
            self.assertEqual('甲', library.match(icon.copy()))
            self.assertEqual('甲', library.match(np.roll(icon, (2, -3), axis=(0, 1))))
            self.assertIsNone(library.match(255-icon))
            library.remember('乙', icon, 'different-frame.png')
            self.assertIsNone(library.match(icon))

    def test_popup_requires_unique_title_and_explicit_stock(self):
        rows = [SimpleNamespace(name='哀歌声核', y=150), SimpleNamespace(name='拥有：12', y=400),
                SimpleNamespace(name='共鸣者突破材料', y=212)]
        self.assertEqual(('哀歌声核', 12), popup_identity(rows, 1080))
        with self.assertRaises(RuntimeError):
            popup_identity(rows[:1], 1080)

    def test_disallowed_party_cannot_send_navigation_or_combat_input(self):
        task = SimpleNamespace(selected_combat_team=1, combat_teams='2,4,5', return_to_world=Mock())
        with self.assertRaisesRegex(RuntimeError, '允许列表'):
            CrossTeamMaterialTask.verify_plan_party(task)
        task.return_to_world.assert_not_called()

    def test_changed_party_identity_stops_before_entry(self):
        task = SimpleNamespace(selected_combat_team=5, combat_teams='2,4,5',
                               expected_combat_members=['a', 'b', 'c'], return_to_world=Mock())
        members = [dict(character=c) for c in ('x', 'b', 'c')]
        with patch('src.task.CrossTeamMaterialTask.observe_members', return_value=members), \
             patch('src.task.CrossTeamMaterialTask.trusted_members', return_value=True), \
             self.assertRaisesRegex(RuntimeError, '当前战斗成员'):
            CrossTeamMaterialTask.verify_plan_party(task)

    def test_partial_named_scan_exposes_unvisited_targets(self):
        with tempfile.TemporaryDirectory() as folder, patch('src.task.CrossTeamMaterialTask._atomic_json') as write:
            task = SimpleNamespace(target_teams='1,2,3,4,5', combat_teams='2,4,5', selected_combat_team=5)
            CrossTeamMaterialTask.publish_named_snapshot(task, [job('甲', '哀歌声核', 1, 8)], ['甲', '乙'], False)
            data = write.call_args.args[1]
            self.assertFalse(data['scan_complete'])
            self.assertEqual([{'target': '乙', 'reason': '尚未扫描'}], data['unknown'])

    def test_fresh_material_set_cannot_disappear_when_row_changes(self):
        queued = [job('甲', '旧材料', 0, 10)]
        fresh = [job('甲', '新材料', 2, 8)]
        refresh_named_jobs(queued, fresh)
        self.assertTrue(queued[0]['superseded'])
        rows, unknown = aggregate_named_materials(queued)
        self.assertEqual(['新材料'], [r['item_name'] for r in rows])
        self.assertEqual(6, rows[0]['raw_missing'])


if __name__ == '__main__':
    unittest.main()
