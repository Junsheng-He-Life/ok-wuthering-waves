import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from src.task.TeamMaterialPlan import build_team_plan, plan_fingerprint, TEAM_NAMES
from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.TeamMaterialEntry import TeamMaterialEntry
from src.task.CultivationTargetUI import material_action, material_counts, NoCurrentMaterialNeed
from ok import Box


class TestTeamMaterialPlan(unittest.TestCase):
    def test_red_leading_digit_is_rechecked_before_farming_more_materials(self):
        from src.task.CultivationTargetUI import supplement_material_counts
        row = Box(740, 330, 180, 30, name='武器与技能素材')
        boxes = [row, Box(1360, 380, 50, 20, name='105/25'),
                 Box(1480, 380, 50, 20, name='0/67')]
        task = SimpleNamespace(width=1920, log_info=Mock(), ocr=Mock(side_effect=[
            [], [], [Box(0, 0, 40, 20, name='105/25')], [Box(0, 0, 40, 20, name='10/67')]]))
        updated = supplement_material_counts(task, boxes)
        self.assertEqual([[105, 25], [10, 67]], material_counts(updated, row, 1920))

    def test_enlarged_counter_replaces_truncated_false_completion(self):
        from src.task.CultivationTargetUI import supplement_weekly_counts
        row = Box(740, 450, 180, 30, name='技能升级材料')
        boxes = [row, Box(1480, 510, 50, 20, name='4/2')]
        task = SimpleNamespace(width=1920, log_info=Mock(),
            ocr=Mock(return_value=[Box(10, 10, 80, 30, name='4/24')]))
        updated = supplement_weekly_counts(task, boxes)
        self.assertEqual([[4, 24]], material_counts(updated, row, 1920))

    def test_buling_weekly_accepts_observed_domain_title_and_selects_ninety(self):
        import re
        label = Box(740, 450, 180, 30, name='技能升级材料')
        action = Box(1660, 450, 80, 30, name='前往')
        quota = Box(740, 485, 400, 30, name='本周剩余可收取次数：3/3')
        title = Box(1240, 150, 330, 30, name='战歌重奏・烬夜天启')
        level = Box(200, 590, 180, 30, name='推荐等级90')
        solo = Box(1450, 960, 180, 30, name='单人挑战')
        def menu(pattern, region, timeout):
            return next((b for b in (title, level, solo) if re.fullmatch(pattern, b.name)), None)
        task = SimpleNamespace(plan_job={'kind': '周本'}, expected_target='卜灵',
            width=1920, height=1080, material_target_matches=Mock(return_value=True),
            ocr=Mock(return_value=[label, action, quota]), menu_text=Mock(side_effect=menu),
            click_box=Mock(), finish_domain_destination=Mock(return_value=True))
        self.assertTrue(TeamMaterialEntry.enter_character_material_domain(task, {}))
        self.assertEqual('leviathan', task._material_boss_source['boss_key'])
        self.assertEqual([action, level, solo], [c.args[0] for c in task.click_box.call_args_list])

    def test_partial_avatar_banner_does_not_change_character_name(self):
        from src.task.BaseWWTask import BaseWWTask
        task = SimpleNamespace(
            box_of_screen=Mock(return_value=Box(120, 76, 322, 88)),
            _normalize_material_text=BaseWWTask._normalize_material_text,
            ocr=Mock(return_value=[Box(192, 104, 72, 20, name='培养目标'),
                                   Box(192, 131, 20, 20, name='心'),
                                   Box(160, 136, 20, 10, name='期')]))
        self.assertEqual('心', BaseWWTask.current_material_target_name(task))

    def test_missing_small_name_is_read_from_enlarged_name_line(self):
        from src.task.BaseWWTask import BaseWWTask
        import numpy as np
        task = SimpleNamespace(
            height=1080, frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
            box_of_screen=Mock(return_value=Box(0, 0, 100, 100)),
            _normalize_material_text=BaseWWTask._normalize_material_text,
            ocr=Mock(side_effect=[
                [Box(280, 160, 100, 30, name='培养目标'),
                 Box(238, 208, 30, 15, name='当期')],
                [Box(280, 196, 30, 30, name='心')]]))
        self.assertEqual('心', BaseWWTask.current_material_target_name(task))
        self.assertEqual((340, 340, 3), task.ocr.call_args.kwargs['frame'].shape)
        self.assertEqual(.8, task.ocr.call_args.kwargs['threshold'])

    def test_single_character_target_cannot_match_another_name(self):
        from src.task.CharacterMaterialTask import CharacterMaterialTask
        task = SimpleNamespace(
            _normalize_material_text=CharacterMaterialTask._normalize_material_text,
            current_material_target_name=Mock(return_value='鉴心'))
        self.assertFalse(CharacterMaterialTask.material_target_matches(task, '心'))
        task.current_material_target_name.return_value = '心'
        self.assertTrue(CharacterMaterialTask.material_target_matches(task, '心'))

    def test_missing_ascension_is_skippable_only_at_verified_list_end(self):
        with self.assertRaises(NoCurrentMaterialNeed):
            material_action([Box(900, 900, 200, 30, name='声骸培养')], '突破', 3440, 1440)
        with self.assertRaises(RuntimeError) as error:
            material_action([], '突破', 3440, 1440)
        self.assertNotIsInstance(error.exception, NoCurrentMaterialNeed)

    def test_direct_material_row_selects_button_on_same_row(self):
        label = Box(900, 300, 250, 30, name='武器与技能素材')
        correct = Box(3100, 300, 100, 30, name='前往')
        other = Box(3100, 650, 100, 30, name='前往')
        self.assertIs(correct, material_action([other, label, correct], '武器/技能', 3440, 1440))

    def test_weekly_direct_entry_refuses_no_remaining_claims(self):
        boxes = [Box(900, 500, 200, 30, name='技能升级材料'),
                 Box(900, 540, 400, 30, name='本周剩余可收取次数：0/3'),
                 Box(3100, 520, 100, 30, name='前往')]
        with self.assertRaisesRegex(RuntimeError, '剩余领奖次数'):
            material_action(boxes, '周本', 3440, 1440)

    def test_weekly_queue_cannot_exceed_three_claims(self):
        with self.assertRaises(ValueError):
            build_team_plan(['秧秧·玄翎', '弗洛洛', '穗穗'], {'周本每人次数': 2})

    def test_weekly_missing_owned_digit_requires_another_read(self):
        row = Box(741, 545, 159, 34, name='技能升级材料')
        counter = Box(1492, 610, 26, 12, name='/26')
        self.assertEqual([], material_counts([row, counter], row, 1920))

    def test_shared_material_requires_verified_target_without_catalog_fallback(self):
        task = SimpleNamespace(plan_job={'kind': '贝币'}, expected_target='穗穗',
            material_target_matches=Mock(return_value=False),
            open_boss_book=Mock(), click_box=Mock())
        with self.assertRaisesRegex(RuntimeError, '培养目标校验失败'):
            TeamMaterialEntry.enter_character_material_domain(task, {'category': 'moni'})
        task.open_boss_book.assert_not_called()
        task.click_box.assert_not_called()

    def test_every_member_gets_three_specialized_categories(self):
        names = ['秧秧·玄翎', '弗洛洛', '穗穗']
        jobs = build_team_plan(names, {})
        self.assertEqual(12, len(jobs))
        for name in names:
            self.assertEqual({'武器/技能', '突破', '周本'}, {j['kind'] for j in jobs[:9] if j['target'] == name})
        self.assertEqual(['角色经验', '武器经验', '贝币'], [j['kind'] for j in jobs[9:]])

    def test_shared_budget_cannot_afford_sixty_after_forty(self):
        budget = MaterialRunBudget(2, 80, 0)
        budget.begin_claim()
        budget.finish_claim(120, 80)
        budget.claim_cost = 60
        self.assertFalse(budget.can_claim())
        with self.assertRaises(RuntimeError):
            budget.begin_claim()

    def test_sixty_claim_requires_its_own_cost_not_forty(self):
        budget = MaterialRunBudget(2, 120, 0, claim_cost=60)
        budget.begin_claim()
        with self.assertRaises(RuntimeError):
            budget.finish_claim(120, 80)
        self.assertTrue(budget.claim_pending)

    def test_checkpoint_does_not_advance_before_settlement(self):
        task = TeamMaterialTask.__new__(TeamMaterialTask)
        task.progress = {'next_job': 0}
        task.plan_job = {'target': '穗穗'}
        task.job_index = 0
        task.shared_budget = MaterialRunBudget()
        with tempfile.TemporaryDirectory() as root:
            task.state_path = Path(root) / 'state.json'
            task.shared_budget.begin_claim()
            task.checkpoint_claim()
            self.assertTrue(task.progress['claim_pending'])
            self.assertEqual(0, task.progress['next_job'])
            task.shared_budget.finish_claim(80, 40)
            task.checkpoint_claim()
            self.assertFalse(task.progress['claim_pending'])
            self.assertEqual(1, task.progress['next_job'])

    def test_budget_changes_do_not_reset_job_progress(self):
        names = ['秧秧·玄翎', '弗洛洛', '穗穗']
        self.assertEqual(plan_fingerprint(build_team_plan(names, {'本次波片上限': 40})),
                         plan_fingerprint(build_team_plan(names, {'本次波片上限': 80})))


class TestDurableQueue(unittest.TestCase):
    def test_later_claim_does_not_complete_deferred_weeklies(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.TeamMaterialTask import TeamMaterialTask
        task = SimpleNamespace(progress={'next_job': 6}, write_progress=Mock())
        TeamMaterialTask.complete_job(task, 9)
        self.assertEqual(6, task.progress['next_job'])
        self.assertIn(9, task.progress['completed_jobs'])
        self.assertNotIn(6, task.progress['completed_jobs'])


class TestObservedNeeds(unittest.TestCase):
    def test_no_invented_shared_jobs_and_preserve_overworld_need(self):
        from src.task.CultivationTargetUI import required_jobs
        boxes = [Box(950, y, 260, 30, name=name) for y, name in
                 ((300, '共鸣者经验材料'), (500, '武器与技能素材'),
                  (700, '武器与技能素材'), (900, '技能升级材料'))]
        jobs = required_jobs(boxes, '穗穗', 3440)
        self.assertEqual(['角色经验', '武器/技能', '武器/技能', '周本'],
                         [job['kind'] for job in jobs])
        self.assertIn('deferred_reason', jobs[2])
        self.assertTrue(all(job['target'] == '穗穗' for job in jobs))


class TestRecoveredQueue(unittest.TestCase):
    def test_failed_job_moves_after_unattempted_without_being_completed(self):
        from src.task.TeamMaterialTask import TeamMaterialTask
        task = SimpleNamespace(progress={'next_job': 1, 'completed_jobs': [0,4],
                                         'failed_jobs': {'5': {}}})
        order = TeamMaterialTask.pending_job_indices(task, [None]*7)
        self.assertEqual([1,2,3,6,5], order)

    def test_only_verified_recovery_can_continue(self):
        from src.task.TeamMaterialTask import TeamMaterialTask
        task = SimpleNamespace(progress={}, shared_budget=SimpleNamespace(claim_pending=False),
                               write_progress=Mock())
        good = {'status':'job_failed_recovered', 'recovered':True, 'error':'low health'}
        TeamMaterialTask.record_recovered_failure(task, 5, good)
        self.assertIn('5', task.progress['failed_jobs'])
        for report in ({'status':'stopped'}, dict(good, recovered=False)):
            with self.assertRaises(RuntimeError):
                TeamMaterialTask.record_recovered_failure(task, 6, report)
        task.shared_budget.claim_pending = True
        with self.assertRaises(RuntimeError):
            TeamMaterialTask.record_recovered_failure(task, 6, good)

class TestMaterialCounters(unittest.TestCase):
    def test_sufficient_and_missing_counts_are_distinct(self):
        from src.task.CultivationTargetUI import required_jobs
        rows = [Box(950, 300, 260, 30, name='共鸣者经验材料'),
                Box(950, 500, 260, 30, name='共鸣者突破材料')]
        counts = [Box(2800, 345, 90, 20, name='54/54'),
                  Box(2800, 545, 90, 20, name='24/28')]
        jobs = required_jobs(rows + counts, '弗洛洛', 3440)
        self.assertTrue(jobs[0]['satisfied'])
        self.assertFalse(jobs[1]['satisfied'])
        self.assertEqual([[24,28]], jobs[1]['material_counts'])
        unknown = required_jobs(rows, '弗洛洛', 3440)
        self.assertFalse(unknown[0]['satisfied'])
        self.assertIn('deferred_reason', unknown[0])

    def test_explicit_unbounded_budget_keeps_uncertain_claim_guard(self):
        from src.task.MaterialRunBudget import MaterialRunBudget
        budget = MaterialRunBudget(-1, -1, -1, max_solvents=-1)
        for _ in range(25):
            budget.record_solvent()
            budget.record_refill(60)
            budget.begin_claim()
            self.assertFalse(budget.can_claim())
            budget.finish_claim(100,60)
        self.assertTrue(budget.can_claim())

    def test_material_source_evidence_does_not_restart_completed_plan(self):
        jobs = build_team_plan(['秧秧·玄翎', '弗洛洛', '穗穗'], {})
        signature = plan_fingerprint(jobs)
        jobs[0]['material_source'] = {'item': '孤焰酬义', 'boss_key': 'wanelao'}
        jobs[0]['resolved_stage'] = '万囮牢·朽躯'
        self.assertEqual(signature, plan_fingerprint(jobs))
        jobs[0]['target'] = '另一角色'
        self.assertNotEqual(signature, plan_fingerprint(jobs))
