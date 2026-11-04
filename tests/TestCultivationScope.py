"""Selection boundaries, live-scan decisions and one shared zero-spend queue."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from src.runtime.CultivationPolicy import cultivation_kinds, recommended_echo_locations
from src.runtime.DesktopJobs import DesktopRequest, action_arguments
from src.task.CultivationTask import CultivationTask
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.TeamMaterialTask import TeamMaterialTask
from src.ui.DesktopWindow import DesktopWindow


class TestCultivationScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_empty_unknown_and_duplicate_scopes_never_mean_all(self):
        for value in ([], '', ['未知'], ['声骸', '声骸']):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cultivation_kinds(value)
        self.assertEqual(('突破', '贝币'), cultivation_kinds(['贝币', '突破']))

    def test_echo_only_cli_has_no_material_plan_and_forces_zero_spending(self):
        request = DesktopRequest(kind='materials', target='心', cultivation_selection=('声骸',),
                                 waveplates=1000, reserve=200, solvents=30)
        args = request.arguments(188)
        self.assertEqual('cultivation', args[args.index('--phase') + 1])
        self.assertEqual('声骸', args[args.index('--cultivation-kinds') + 1])
        self.assertIn('--echo-no-claim', args)
        self.assertNotIn('plan', args)
        for flag in ('--max-stamina', '--reserve-limit', '--solvent-limit'):
            self.assertEqual('0', args[args.index(flag) + 1])
        self.assertEqual('188', args[args.index('--solvent-total') + 1])

    def test_three_targets_share_one_selection_and_catalog_is_nonspending(self):
        args = action_arguments('catalog', 'materials', '心,今汐,卜灵', ('突破', '武器/技能'))
        self.assertEqual('cultivation-catalog', args[1])
        self.assertEqual('突破,武器/技能', args[args.index('--cultivation-kinds') + 1])
        self.assertEqual('心,今汐,卜灵', args[args.index('--targets') + 1])
        self.assertIn('--echo-no-claim', args)

    def test_echo_recommendations_do_not_expand_by_generic_drop_icons(self):
        marked = dict(name='A', normalized_name='A', is_target_row=True, observation_count=2,
                      target_marker_saturation=.13, target_avatar_similarity=.27, drop_fingerprint='same')
        rows = [marked, dict(marked, name='B', is_target_row=False),
                dict(marked, name='C', observation_count=1),
                dict(marked, name='D', target_avatar_similarity=0),
                dict(marked, name='E', normalized_name='row-0')]
        self.assertEqual([], recommended_echo_locations(rows))
        self.assertEqual([rows[0],rows[1],rows[3]], recommended_echo_locations(rows,verified_set='已核对套装'))

    def test_echo_only_does_not_scan_any_material_counts(self):
        task = CultivationTask.__new__(CultivationTask)
        task.cultivation_selection = ('声骸',);task.result = {}
        task.echo_recommendations = Mock(return_value=[])
        task.return_to_world = Mock()
        with patch.object(TeamMaterialTask, 'scan_required_jobs') as scan:
            jobs = task.scan_scope(['心', '今汐', '卜灵'])
        scan.assert_not_called()
        self.assertEqual(3, len(jobs))
        self.assertTrue(all(row['kind'] == '声骸' and row.get('deferred_reason') for row in jobs))

    def test_missing_recommendation_never_enters_an_unrelated_stage(self):
        task = CultivationTask.__new__(CultivationTask)
        task.expected_target='心';task.exact_stage='A'
        task.heal_at_beacon=Mock();task.echo_recommendations=Mock(return_value=[{'name':'B'}])
        task.enter_material_location=Mock()
        with self.assertRaisesRegex(RuntimeError, '筛选结果'):
            task.navigate_echo()
        task.enter_material_location.assert_not_called()

    def test_material_scan_filters_before_shared_planning_and_does_not_reuse_audit(self):
        task = CultivationTask.__new__(CultivationTask)
        task.selected_kinds=('突破', '贝币')
        with patch.object(TeamMaterialTask, 'scan_required_jobs', return_value=[]) as scan:
            task.selected_material_jobs(['心'])
        scan.assert_called_once_with(task, ['心'], selected_kinds=['突破', '贝币'], shared_plan=False)

    def test_actual_material_reader_keeps_only_selected_rows(self):
        from ok import Box
        task=SimpleNamespace(width=1920,height=1080)
        task.open_materials_book=task.select_material_target_with_recovery=task.reset_material_list_top=Mock()
        task.log_info=Mock()
        task.ocr=Mock(return_value=[])
        observed=[{'target':'心','kind':kind,'repeat':0,'material_counts':[[0,20]]}
                  for kind in ('突破','武器/技能','贝币')]
        with tempfile.TemporaryDirectory() as folder:
            old=Path.cwd();os.chdir(folder)
            try:
                with patch('src.task.CultivationTargetUI.viewport',return_value=Box(0,0,1,1)), \
                     patch('src.task.CultivationTargetUI.supplement_weekly_counts',side_effect=lambda task, boxes:boxes), \
                     patch('src.task.CultivationTargetUI.required_jobs',return_value=observed), \
                     patch('src.task.SharedMaterialPlanner.apply_shared_material_plan') as shared:
                    jobs=TeamMaterialTask.scan_required_jobs(task,['心'],selected_kinds=['突破'],shared_plan=False)
                shared.assert_not_called()
                self.assertEqual(['突破'],[j['kind'] for j in jobs])
            finally:os.chdir(old)

    def queue(self, kinds=('声骸',), runs=2):
        task=CultivationTask.__new__(CultivationTask)
        task.selected_kinds=kinds;task.result={'status':'running','battles':[]}
        task._echo_battle_limit=runs;task.claim_enabled=False
        task._run_budget=MaterialRunBudget(1,0,0,0)
        task.fresh_material_job=Mock(side_effect=lambda job:job)
        task.execute_job=Mock(side_effect=lambda job:task.result['battles'].append({'kind':job['kind']}))
        return task

    def test_queue_rejects_unselected_material_job(self):
        task=self.queue()
        with self.assertRaisesRegex(RuntimeError,'未勾选'):
            task.run_scope_queue([{'target':'心','kind':'突破'}])
        task.execute_job.assert_not_called()

    def test_no_claim_queue_shares_global_battle_limit_across_characters(self):
        task=self.queue(runs=2)
        task.run_scope_queue([{'target':name,'kind':'声骸','cost':60,'route':{}}
                              for name in ('心','今汐','卜灵')])
        self.assertEqual(['心','今汐'],[call.args[0]['target'] for call in task.execute_job.call_args_list])
        self.assertEqual(2,len(task.result['battles']))
        self.assertEqual(0,task._run_budget.spent)

    def test_pending_claim_budget_cannot_run_another_job(self):
        task=self.queue();task.claim_enabled=True
        task._run_budget=MaterialRunBudget(2,120,0,0);task._run_budget.begin_claim()
        task.run_scope_queue([{'target':'心','kind':'声骸','cost':60,'route':{}}])
        task.execute_job.assert_not_called()

    def test_pause_after_current_prevents_next_target(self):
        task=self.queue(runs=3)
        def execute(job):
            task.result['battles'].append({});task.stop_after_current=True
        task.execute_job.side_effect=execute
        task.run_scope_queue([{'target':name,'kind':'声骸','cost':60,'route':{}}
                              for name in ('心','今汐','卜灵')])
        task.execute_job.assert_called_once()
        self.assertEqual('stopped_after_current',task.result['status'])

    def test_no_claim_configuration_ignores_old_allowances(self):
        task=CultivationTask.__new__(CultivationTask);task.result={}
        task.config={'战后领奖':False,'本次战斗上限':2,'本次最多领奖':2,
                     '本次波片上限':1000,'本次储备上限':200,'本次溶剂上限':30}
        task._activity=SimpleNamespace(solvent_allowance=Mock())
        task.configure_scope()
        self.assertEqual((0,0,0),(task._run_budget.max_stamina,task._run_budget.max_reserve,task._run_budget.max_solvents))
        task._activity.solvent_allowance.assert_not_called()

    def test_material_only_queue_never_schedules_an_echo_job(self):
        task=self.queue(('突破','贝币'))
        jobs=[{'target':'心','kind':kind,'cost':40,'route':{}} for kind in ('突破','贝币')]
        task.run_scope_queue(jobs)
        self.assertEqual(['突破','贝币'],[call.args[0]['kind'] for call in task.execute_job.call_args_list])
        self.assertFalse(task.collect_material_echoes)

    def test_gui_scope_is_shared_default_echo_only_and_empty_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            window=DesktopWindow(folder,preview=True);self.addCleanup(window.close)
            window.kind.setCurrentIndex(window.kind.findData('materials'))
            self.assertEqual(('声骸',),window.selected_projects())
            window.cultivation_checks['贝币'].setChecked(True)
            self.assertEqual(('声骸','贝币'),window.selected_projects())
            self.assertFalse(window.stage.isEnabled())
            for check in window.cultivation_checks.values():check.setChecked(False)
            with self.assertRaises(ValueError):window.selected_projects()

    def test_actual_echo_execution_absorbs_without_claim_or_refill(self):
        task=CultivationTask.__new__(CultivationTask)
        task.result={'status':'running','battles':[]};task.claim_enabled=False
        task._run_budget=MaterialRunBudget(1,0,0,0);task.rotation_events=[]
        for name in ('set_workflow_stage','navigate_echo','fight_verified_domain',
                     'dismiss_unclaimed_reward_dialog','search_echo','claim_one_reward',
                     'leave_echo_encounter','heal_at_beacon','update_activity','save_echo_progress',
                     'run_material_workflow','refill_at_reward'):
            setattr(task,name,Mock())
        task.execute_job({'target':'心','kind':'声骸','cost':60,
                          'route':{'category':'wuyin','fallback_stage_name':'A'}})
        task.search_echo.assert_called_once();task.dismiss_unclaimed_reward_dialog.assert_called_once()
        task.claim_one_reward.assert_not_called();task.refill_at_reward.assert_not_called()
        task.run_material_workflow.assert_not_called()
        self.assertEqual('practice',task.phase)

    def test_actual_material_execution_uses_existing_practice_and_no_echo_search(self):
        task=CultivationTask.__new__(CultivationTask)
        task.result={'status':'running','battles':[]};task.claim_enabled=False
        task._run_budget=MaterialRunBudget(1,0,0,0)
        task.update_activity=task.save_echo_progress=Mock();task.search_echo=Mock()
        def practice(budget):
            self.assertIs(task._run_budget,budget)
            self.assertEqual('practice',task.phase)
            self.assertFalse(task.collect_material_echoes)
            task.result['status']='practice_completed_no_claim'
        task.run_material_workflow=Mock(side_effect=practice)
        task.execute_job({'target':'心','kind':'突破','cost':60,
                          'route':{'category':'qiangdi','fallback_stage_name':''}})
        task.run_material_workflow.assert_called_once();task.search_echo.assert_not_called()

    def test_claiming_echo_only_requires_a_60_waveplate_allowance(self):
        with self.assertRaisesRegex(ValueError,'额度不足'):
            DesktopRequest(kind='materials',cultivation_selection=('声骸',),claim_rewards=True,waveplates=40).arguments()

    def test_cultivation_pending_blocks_both_gui_and_other_controller_routes(self):
        import json
        from src.runtime.DesktopUserState import inspect_user_state
        from src.task.MaterialRefillUI import MaterialRefillUI, RefillOutcomeUncertain
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'configs/macos-desktop/cultivation-progress.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps({'budget':{'claim_pending':True}}))
            self.assertEqual('pending',inspect_user_state(root)['status'])
            old=Path.cwd();os.chdir(root)
            try:
                with self.assertRaisesRegex(RefillOutcomeUncertain,'培养计划'):
                    MaterialRefillUI().assert_no_pending_refill()
            finally:os.chdir(old)

    def test_archived_cultivation_run_cannot_be_reset_as_a_blank_install(self):
        from src.runtime.DesktopUserState import inspect_user_state
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir()
            (root/'logs/cultivation-123.json').write_text('{"status":"completed"}')
            self.assertFalse(inspect_user_state(root)['can_initialize'])

    def test_blocked_restart_preserves_the_original_pending_checkpoint(self):
        from src.task.MaterialRefillUI import RefillOutcomeUncertain
        with tempfile.TemporaryDirectory() as folder:
            old=Path.cwd();os.chdir(folder)
            try:
                task=CultivationTask.__new__(CultivationTask);task.phase='cultivation'
                task.echo_state_path.parent.mkdir(parents=True)
                original=b'{"budget":{"claim_pending":true},"stage":"keep original"}'
                task.echo_state_path.write_bytes(original)
                task.scope_names=Mock()
                task.mouse_up=task.send_key_up=task._stop_combat_debug_frame_recorder=Mock()
                with self.assertRaises(RefillOutcomeUncertain):task.run()
                self.assertEqual(original,task.echo_state_path.read_bytes())
                task.scope_names.assert_not_called()
            finally:os.chdir(old)

    def test_sonata_name_must_be_on_the_echo_atlas_row(self):
        from ok import Box
        from src.task.CultivationEchoUI import sonata_name_from_boxes
        boxes=[Box(900,750,100,30,name='声骸培养'),Box(1660,830,100,30,name='合鸣图鉴'),
               Box(760,830,200,30,name='衔梦照世之心'),Box(760,500,200,30,name='其他材料')]
        self.assertEqual('衔梦照世之心',sonata_name_from_boxes(boxes,1920,1080))
        with self.assertRaises(RuntimeError):sonata_name_from_boxes(boxes[:-2]+boxes[-1:],1920,1080)
        with self.assertRaises(RuntimeError):sonata_name_from_boxes(boxes+[Box(1000,830,180,30,name='另一个套装')],1920,1080)

    def test_existing_exact_sonata_filter_requires_the_matching_role(self):
        from src.task.CultivationEchoUI import CultivationEchoUI
        task=CultivationEchoUI();task.open_boss_book=Mock()
        task.menu_text=Mock(return_value=SimpleNamespace(name='衔梦照世之心'))
        task.material_target_matches=Mock(return_value=True)
        task.save_echo_observation=Mock();task.click_box=Mock()
        task.next_frame=Mock();task.wait_until=lambda fn,**kw:fn()
        task.select_sonata_filter('心','衔梦照世之心')
        task.material_target_matches.assert_called_with('心')
        task.click_box.assert_called_once()  # Dismiss the menu via the observed heading.

    def test_clicked_sonata_is_not_accepted_without_matching_filter_header(self):
        from src.task.CultivationEchoUI import CultivationEchoUI
        task=CultivationEchoUI();task.open_boss_book=Mock()
        task.menu_text=Mock(side_effect=[None,object(),object(),None])
        task.ocr=Mock(return_value=[]);task.next_frame=task.sleep=task.click_box=Mock()
        task.save_echo_observation=Mock()
        with self.assertRaisesRegex(RuntimeError,'筛选结果'):
            task.select_sonata_filter('心','衔梦照世之心')

    def test_target_ocr_retry_still_requires_exact_identity(self):
        from src.task.CultivationEchoUI import CultivationEchoUI
        task=CultivationEchoUI();task.next_frame=Mock()
        task.material_target_matches=Mock(side_effect=[False,True])
        task.wait_until=lambda fn,**kw:fn() or fn()
        self.assertTrue(task.cultivation_target_verified('心'))
        self.assertEqual(2,task.next_frame.call_count)
        task.material_target_matches=Mock(return_value=False)
        self.assertFalse(task.cultivation_target_verified('心'))


if __name__=='__main__':unittest.main()
