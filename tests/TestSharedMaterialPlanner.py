from contextlib import chdir
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from src.task.SharedMaterialPlanner import combined_plan, apply_shared_material_plan, FAMILIES


class TestSharedMaterialPlanner(unittest.TestCase):
    def test_denia_reserves_heart_demand_and_refreshes_shared_stock(self):
        family = FAMILIES['弦线']
        heart = [(314,10),(402,13),(70,46),(8,67)]
        denia = [(373,5),(477,5),(56,37),(5,76)]
        items = [dict(target=target,item_name=n,inventory=a,required=b)
                 for target,counts in [('心',heart),('达妮娅',denia)]
                 for n,(a,b) in zip(family,counts)]
        jobs = [dict(target='达妮娅',kind='武器/技能',repeat=0,material_counts=denia),
                dict(target='心',kind='武器/技能',repeat=0,
                     material_counts=[(owned, needed) for (owned, _), (_, needed) in zip(denia, heart)])]
        rows = {r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(143,rows['如歌的弦线']['required_total'])
        self.assertEqual([5],rows['如歌的弦线']['inventory_observations'])
        self.assertGreater(rows['如歌的弦线']['missing_after_synthesis'],0)

    def test_chisa_refreshes_observed_high_grades_for_both_roles(self):
        items = [dict(target=target,item_name=n,inventory=a,required=b)
                 for target,counts in [('今汐',[(418,0),(483,15),(84,45),(11,84)]),
                                       ('千咲',[(418,0),(483,0),(73,34),(11,84)])]
                 for n,(a,b) in zip(FAMILIES['海蚀嵌合体'],counts)]
        jobs = [dict(target='千咲',kind='武器/技能',repeat=0,
                     material_counts=[(77,34),(12,84)]),
                dict(target='今汐',kind='武器/技能',repeat=0,
                     material_counts=[(77,45),(12,84)])]
        rows = {r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(168,rows['海蚀嵌合体239']['required_total'])
        self.assertEqual([77],rows['海蚀嵌合体235']['inventory_observations'])
        self.assertEqual([12],rows['海蚀嵌合体239']['inventory_observations'])

    def test_aemeath_uses_only_inspected_polarizer_grades(self):
        counts = [(42,5),(4,51)]
        items = [dict(target='爱弥斯',item_name=n,inventory=a,required=b)
                 for n,(a,b) in zip(FAMILIES['偏振体'],counts)]
        jobs = [dict(target='爱弥斯',kind='武器/技能',repeat=0,material_counts=counts)]
        rows = {r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(35,rows['叠翼偏振体']['missing_after_synthesis'])
        self.assertEqual({'多翼偏振体','叠翼偏振体'},set(rows))

    def test_heart_weapon_reserves_vortex_in_buling_farm_plan(self):
        counts = [(290,25),(329,28),(62,55),(3,67)]
        items = [dict(target='卜灵',item_name=n,inventory=a,required=b)
                 for n,(a,b) in zip(FAMILIES['涡流'],counts)]
        items.append(dict(target='心',item_name='急板涡流',inventory=3,required=12))
        jobs = [dict(target='卜灵',kind='武器/技能',repeat=0,material_counts=counts),
                dict(target='心',kind='武器/技能',repeat=1,material_counts=[(3,12)])]
        rows={r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(79,rows['急板涡流']['required_total'])
        self.assertEqual(31,rows['急板涡流']['missing_after_synthesis'])

    def test_historical_hidden_low_tier_stock_cannot_suppress_live_shortage(self):
        counts = [(418,0),(483,15),(84,45),(11,84)]
        items = [dict(target='今汐',item_name=n,inventory=a,required=b)
                 for n,(a,b) in zip(FAMILIES['海蚀嵌合体'],counts)]
        jobs=[dict(target='今汐',kind='武器/技能',repeat=0,material_counts=counts[2:])]
        rows={r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(60,rows['海蚀嵌合体239']['missing_after_synthesis'])
        self.assertNotIn('海蚀嵌合体210', rows)
        self.assertNotIn('海蚀嵌合体226', rows)

    def test_boss_and_common_inventory_refresh_from_live_scan(self):
        items = [dict(target='今汐',item_name='哀歌声核',inventory=9,required=16),
                 dict(target='今汐',item_name='中频啸叫声核',inventory=219,required=15)]
        jobs = [dict(target='今汐',kind='突破',material_counts=[(14,16)]),
                dict(target='今汐',kind='武器/技能',repeat=1,material_counts=[(256,15),(0,25),(1,61)])]
        rows = {r['item_name']:r for r in combined_plan(jobs,{'items':items})}
        self.assertEqual(14, rows['哀歌声核']['inventory'])
        self.assertEqual(2, rows['哀歌声核']['missing_after_synthesis'])
        self.assertEqual(256, rows['中频啸叫声核']['inventory'])

    def test_old_goal_and_off_scope_targets_do_not_override_current_scan(self):
        audit = {'items': [dict(target=target,item_name=name,inventory=100,required=5)
                           for target in ('爱弥斯', '旧队友')
                           for name in FAMILIES['偏振体']]}
        jobs = [dict(target='爱弥斯', kind='武器/技能', material_counts=[(0,10),(0,100)])]
        rows = {r['item_name']: r for r in combined_plan(jobs, audit)}
        self.assertEqual(100, rows['叠翼偏振体']['required_total'])
        self.assertEqual(100, rows['叠翼偏振体']['missing_after_synthesis'])
        self.assertEqual({'爱弥斯': 100}, rows['叠翼偏振体']['by_target'])

    def test_disagreeing_live_stock_is_unresolved(self):
        jobs = [dict(target=target,kind='武器/技能',material_counts=[(stock,10)])
                for target, stock in [('今汐', 20), ('千咲', 21)]]
        row = combined_plan(jobs)[0]
        self.assertTrue(row['inventory_conflict'])
        self.assertIsNone(row['missing_after_synthesis'])

    def test_unreadable_counts_never_supply_inventory(self):
        for counts in (None, [], [None], [1], [[0]], [[0, -1]], [[True, 1]]):
            with self.subTest(counts=counts):
                jobs = [dict(target='今汐',kind='武器/技能',material_counts=counts)]
                self.assertEqual([], combined_plan(jobs))

    def test_personal_completed_policy_cannot_finish_new_boss_shortage(self):
        with TemporaryDirectory() as folder, chdir(folder):
            policy = Path('configs/macos-desktop/shared-material-policy.json')
            policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({'enabled': True, 'targets': ['旧队友'],
                                          'completed_materials': ['哀歌声核']}))
            audit = Path('logs/material-audit-latest.json')
            audit.parent.mkdir(parents=True)
            audit.write_text('{damaged historical audit')
            jobs = [dict(target='今汐',kind='突破',material_counts=[(0,16)],satisfied=False)]
            apply_shared_material_plan(jobs)
            self.assertFalse(jobs[0]['satisfied'])
            self.assertNotIn('completion_reason', jobs[0])
            report = json.loads(Path('logs/material-status/shared-plan-live.json').read_text())
            self.assertEqual(16, report[0]['missing_after_synthesis'])

    def test_new_install_uses_fresh_shared_stock_and_creates_report_folder(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target=target,kind='武器/技能',material_counts=[(10,8)],satisfied=True)
                    for target in ('今汐', '千咲')]
            apply_shared_material_plan(jobs)
            self.assertTrue(Path('logs/material-status/shared-plan-live.json').is_file())
            for job in jobs:
                self.assertFalse(job['satisfied'])
                self.assertEqual({'海蚀嵌合体239': 6}, job['combined_synthesis_missing'])

    def test_shared_demand_replaces_individual_synthesis_estimate(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target=target,kind='武器/技能',material_counts=[(30,0),(0,8)],
                         satisfied=False, conversion_pending=True,
                         deferred_reason='低级余量可能已足以合成补齐；先核验配方，不继续消耗体力')
                    for target in ('今汐', '千咲')]
            apply_shared_material_plan(jobs)
            for job in jobs:
                self.assertEqual(6, job['combined_synthesis_missing']['海蚀嵌合体239'])
                self.assertNotIn('conversion_pending', job)
                self.assertNotIn('deferred_reason', job)

    def test_live_visible_synthesis_can_defer_without_claiming_completion(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target='爱弥斯',kind='武器/技能',material_counts=[(31,1),(0,10)],
                         satisfied=False)]
            apply_shared_material_plan(jobs)
            self.assertTrue(jobs[0]['conversion_pending'])
            self.assertFalse(jobs[0]['satisfied'])

    def test_unknown_target_and_secondary_route_are_not_assigned_to_old_teammate(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target='新角色',kind='武器/技能',material_counts=[(0,10)],satisfied=False),
                    dict(target='心',kind='武器/技能',repeat=1,material_counts=[(0,12)],
                         satisfied=False, deferred_reason='野外素材采集适配尚未完成')]
            original = [dict(job) for job in jobs]
            apply_shared_material_plan(jobs)
            self.assertEqual(original, jobs)

    def test_conflicting_live_stock_blocks_farming_and_completion(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target=target,kind='武器/技能',material_counts=[(stock,10)],satisfied=True)
                    for target, stock in [('今汐', 20), ('千咲', 21)]]
            apply_shared_material_plan(jobs)
            for job in jobs:
                self.assertFalse(job['satisfied'])
                self.assertIn('冲突', job['deferred_reason'])

    def test_recalculation_clears_resolved_synthesis_but_keeps_other_stop_reasons(self):
        with TemporaryDirectory() as folder, chdir(folder):
            jobs = [dict(target='爱弥斯',kind='武器/技能',material_counts=[(31,1),(0,10)],
                         satisfied=False)]
            apply_shared_material_plan(jobs)
            self.assertTrue(jobs[0]['conversion_pending'])
            jobs[0]['material_counts'] = [(1,1),(10,10)]
            apply_shared_material_plan(jobs)
            self.assertTrue(jobs[0]['satisfied'])
            self.assertNotIn('deferred_reason', jobs[0])
            self.assertNotIn('conversion_pending', jobs[0])
            jobs[0].update(material_counts=[(0,1),(0,10)], deferred_reason='导航失败',
                           conversion_pending=True)
            apply_shared_material_plan(jobs)
            self.assertEqual('导航失败', jobs[0]['deferred_reason'])

    def test_corrupt_or_disabled_policy_does_not_enable_optimization(self):
        with TemporaryDirectory() as folder, chdir(folder):
            path = Path('configs/macos-desktop/shared-material-policy.json')
            path.parent.mkdir(parents=True)
            for content in ('{broken', '{"enabled": false}'):
                with self.subTest(content=content):
                    path.write_text(content)
                    jobs = [dict(target='爱弥斯',kind='武器/技能',material_counts=[(31,1),(0,10)])]
                    original = [dict(job) for job in jobs]
                    self.assertEqual(original, apply_shared_material_plan(jobs))
