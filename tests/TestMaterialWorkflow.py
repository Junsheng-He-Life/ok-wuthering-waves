import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.task.MaterialRunUI import MaterialRunUI
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.MaterialWorkflow import MaterialWorkflow
from src.task.MaterialRefillUI import MaterialResourceLimit, RefillOutcomeUncertain
from src.task.TeamMaterialTask import TeamMaterialTask
from tests import TestMaterialRunSafety as workflow_fixtures


class TestRewardRefill(unittest.TestCase):
    def reward(self, stamina, refill_amount=60):
        task = MaterialRunUI()
        state = {'stamina': stamina, 'reserve': 0, 'panel': 'reward', 'clicks': 0}
        task.open_verified_reward = Mock()
        task.reward_dialog_visible = Mock(return_value=True)
        task.get_stamina = lambda: (state['stamina'], state['reserve'], state['stamina'])
        task.reward_option = lambda b: (object(), 2)
        task.log_info = task.next_frame = Mock()
        def click(*args, **kwargs):
            state['clicks'] += 1
            if state['stamina'] < 80:
                state['panel'] = 'refill'
            else:
                state['stamina'] -= 80
                state['panel'] = 'success'
        task.click_box = click
        task.refill_text = lambda *a, **k: state['panel'] == 'refill'
        def refill(budget, before, reserve, opened):
            self.assertFalse(budget.claim_pending)
            self.assertTrue(opened)
            budget.record_solvent()
            state['stamina'] += refill_amount
            state['panel'] = 'reward'
        task.refill_at_reward = Mock(side_effect=refill)
        def text(pattern, *args, **kwargs):
            if pattern.startswith('挑战成功'):
                return state['panel'] == 'success'
            if pattern.startswith('剩余'):
                return SimpleNamespace(name=f"剩余{state['stamina']}")
        task.reward_text = text
        return task, state

    def test_double_at_zero_refills_twice_then_spends_eighty(self):
        task, state = self.reward(0)
        budget = MaterialRunBudget(2, 80, max_solvents=2)
        self.assertEqual(40, task.claim_one_reward(budget))
        self.assertEqual((2, 80, 2, False),
                         (budget.claimed, budget.spent, budget.solvents_used, budget.claim_pending))
        self.assertEqual(2, task.refill_at_reward.call_count)
        self.assertEqual(3, state['clicks'])

    def test_double_at_twenty_needs_one_refill(self):
        task, state = self.reward(20)
        budget = MaterialRunBudget(2, 80, max_solvents=1)
        self.assertEqual(0, task.claim_one_reward(budget))
        task.refill_at_reward.assert_called_once()
        self.assertEqual(80, budget.spent)

    def test_double_selection_does_not_require_current_stamina(self):
        task = MaterialRunUI()
        task.settlement_batch_allowed = lambda: True
        task.reward_text = Mock(side_effect=[SimpleNamespace(name='单倍领取'), True,
                                            SimpleNamespace(name='双倍领取'), True])
        task.get_stamina = Mock(side_effect=AssertionError('selection must not read stamina'))
        self.assertEqual(2, task.reward_option(MaterialRunBudget())[1])

    def test_confirmed_success_with_wrong_delta_stays_pending(self):
        task, state = self.reward(100)
        task.reward_text = Mock(side_effect=[True, *[SimpleNamespace(name='剩余60') for _ in range(3)]])
        budget = MaterialRunBudget(2, 80)
        with self.assertRaisesRegex(RuntimeError, 'delta uncertain'):
            task.claim_one_reward(budget)
        self.assertTrue(budget.claim_pending)
        self.assertEqual(1, state['clicks'])

    def test_rejected_claim_checkpoint_does_not_complete_job(self):
        task = TeamMaterialTask.__new__(TeamMaterialTask)
        task.progress = {'next_job': 0}
        task.plan_job = {'target': '心'}
        task.job_index = task._job_claimed_at_start = 0
        task.shared_budget = MaterialRunBudget()
        task.write_progress = Mock()
        task.shared_budget.begin_claim(2)
        task.checkpoint_claim()
        task.shared_budget.cancel_rejected_claim()
        task.checkpoint_claim()
        self.assertEqual(0, task.progress['next_job'])
        self.assertNotIn(0, task.progress.get('completed_jobs', []))
        self.assertFalse(task.progress['claim_pending'])


class TestStageRecovery(unittest.TestCase):
    def test_two_double_claims_share_one_entry_then_return_for_recheck(self):
        task = workflow_fixtures.TestRotationAndWorkflow().runner()
        task.shared_budget = MaterialRunBudget(8, 320)
        task.plan_job = {'kind': '武器/技能', 'material_counts': [[0, 50]],
                         'route': {'fallback_stage_name': '旋雾之森'}}
        task.navigate_material = Mock()
        task.config = {'结算批次策略': '效率优先', '每批连续挑战场数': 2}
        task.handle_material_entry_notice = Mock()
        task.focus_material_menu = Mock()
        task.click_box = Mock()
        task.menu_text = Mock(return_value=object())
        task.wait_until = Mock(return_value=True)
        task.fight_verified_domain.side_effect = lambda: setattr(task, 'rotation_events', [])
        def claim(budget):
            import time
            task._settlement_health = (time.monotonic(), [1, 1, 1])
            budget.begin_claim(2)
            budget.finish_claim(160, 80)
            return 80
        task.claim_one_reward = Mock(side_effect=claim)
        task.run()
        self.assertEqual('job_completed', task.result['status'])
        self.assertEqual(4, task.shared_budget.claimed)
        self.assertEqual(160, task.shared_budget.spent)
        self.assertEqual(2, task.fight_verified_domain.call_count)
        task.navigate_material.assert_called_once()
        task.leave_verified_domain.assert_called_once()
        task.click_box.assert_called_once()

    def test_exhausted_planned_navigation_recovers_without_claim_or_completion(self):
        task = workflow_fixtures.TestRotationAndWorkflow().runner()
        task.plan_job = {'route': {'fallback_stage_name': '旋雾之森'}}
        task.shared_budget = MaterialRunBudget()
        task.navigate_material = Mock(side_effect=RuntimeError('item tile not verified'))
        task.reset_material_navigation = Mock()
        task.focus_material_menu = Mock()
        task.run()
        self.assertEqual('job_failed_recovered', task.result['status'])
        self.assertTrue(task.result['recovered'])
        self.assertEqual(3, task.navigate_material.call_count)
        task.fight_verified_domain.assert_not_called()
        task.claim_one_reward.assert_not_called()
        self.assertFalse(task.shared_budget.claim_pending)

    def test_boss_tile_uses_count_in_matching_row_on_changed_display(self):
        from src.task.TeamMaterialEntry import TeamMaterialEntry
        from ok import Box
        action = Box(2400, 540, 300, 70, name='前往')
        boss_count = Box(2180, 620, 140, 35, name='16/46')
        other_count = Box(2190, 850, 140, 35, name='4/67')
        self.assertEqual((2250, 572.5), TeamMaterialEntry.boss_material_tile(
            [boss_count, other_count], action, 3024, 1900))
        with self.assertRaisesRegex(RuntimeError, '唯一确认'):
            TeamMaterialEntry.boss_material_tile([other_count], action, 3024, 1900)

    def stage(self, root):
        task = MaterialWorkflow()
        task.result = {}
        task.refill_pending_path = Path(root) / 'pending.json'
        task.log_info = task.focus_material_menu = Mock()
        return task

    def test_navigation_resets_only_navigation_and_records_time(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.stage(root)
            action = Mock(side_effect=[RuntimeError('window hidden'), 'entered'])
            recover = Mock()
            self.assertEqual('entered', task.run_recoverable_stage(
                '导航', action, MaterialRunBudget(), recover=recover))
            recover.assert_called_once()
            self.assertEqual('导航', task.result['recoveries'][0]['stage'])
            self.assertIn('恢复', task.result['stage_seconds'])

    def test_pending_claim_and_pending_refill_never_replay_stage(self):
        for pending_claim in (True, False):
            with tempfile.TemporaryDirectory() as root:
                task = self.stage(root)
                budget = MaterialRunBudget(claim_pending=pending_claim)
                if not pending_claim:
                    task.refill_pending_path.write_text('{}')
                action = Mock(side_effect=RuntimeError('uncertain'))
                with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                    task.run_recoverable_stage('领奖', action, budget)
                action.assert_called_once()

    def test_exchange_result_uncertainty_never_retries(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.stage(root)
            action = Mock(side_effect=RefillOutcomeUncertain('unknown result'))
            with self.assertRaises(RefillOutcomeUncertain):
                task.run_recoverable_stage('补给', action, MaterialRunBudget())
            action.assert_called_once()

    def test_workflow_enters_and_fights_without_pre_entry_refill_or_stamina_read(self):
        task = workflow_fixtures.TestRotationAndWorkflow().runner()
        task.get_stamina = Mock(side_effect=AssertionError('pre-entry stamina read'))
        task.refill_for_claim = Mock(side_effect=AssertionError('pre-entry refill'))
        task.run()
        self.assertEqual(2, task.fight_verified_domain.call_count)
        task.get_stamina.assert_not_called()
        task.refill_for_claim.assert_not_called()

    def test_planned_battle_recovers_and_retries_same_job_once(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        task = workflow_fixtures.TestRotationAndWorkflow().runner()
        task.plan_job = {'route': {'fallback_stage_name': '旋雾之森'}}
        task.shared_budget = MaterialRunBudget()
        task.fight_verified_domain.side_effect = [DomainBattleFailed('animation interruption'), None]
        task.run()
        self.assertEqual('job_completed', task.result['status'])
        self.assertEqual(2, task.fight_verified_domain.call_count)
        task.claim_one_reward.assert_called_once()
        self.assertEqual(1, task.shared_budget.retries)


class TestRefillCheckpoint(unittest.TestCase):
    def exchange(self, root, after=80, remaining=0, exchange_count=1):
        task = MaterialRunUI()
        task.refill_pending_path = Path(root) / 'pending.json'
        for name in ('focus_material_menu', 'click_relative', 'click', 'send_key', 'log_info'):
            setattr(task, name, Mock())
        task.width_of_screen = task.height_of_screen = Mock(return_value=1000)
        task.refill_text = Mock(side_effect=lambda pattern, *args, **kwargs:
            SimpleNamespace(name=f'兑换次数:{exchange_count}')
            if pattern == r'兑换次数[：:]\d+' else True)
        task.get_stamina = Mock(return_value=(after, remaining, after))
        task.confirmation_pending_states = []
        def click(pattern, *args, **kwargs):
            if pattern == '确认':
                pending = task.refill_pending_path.exists()
                task.confirmation_pending_states.append(pending)
                if pending:
                    task.final_confirm_observed_pending = True
        task.refill_click = Mock(side_effect=click)
        return task

    def test_exchange_in_reward_does_not_open_map_or_leave_domain(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.exchange(root)
            budget = MaterialRunBudget(max_solvents=1)
            self.assertEqual(80, task.refill_at_reward(budget, 20, 0))
            self.assertEqual(1, budget.solvents_used)
            self.assertTrue(task.final_confirm_observed_pending)
            self.assertFalse(task.refill_pending_path.exists())
            task.click_relative.assert_not_called()
            task.send_key.assert_called_once_with('esc', after_sleep=.6)

    def test_unknown_exchange_delta_retains_checkpoint_and_blocks_next_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.exchange(root, after=20)
            budget = MaterialRunBudget(max_solvents=2)
            with self.assertRaises(RefillOutcomeUncertain):
                task.refill_at_reward(budget, 20, 0)
            self.assertTrue(task.refill_pending_path.exists())
            confirmations = task.refill_click.call_count
            with self.assertRaises(RefillOutcomeUncertain):
                task.refill_at_reward(budget, 20, 0)
            self.assertEqual(confirmations, task.refill_click.call_count)
            self.assertEqual(1, budget.solvents_used)

    def test_partial_reserve_preview_is_accounted_before_final_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.exchange(root, after=80, remaining=5, exchange_count=60)
            budget = MaterialRunBudget(max_reserve=60)
            self.assertEqual(80, task.refill_at_reward(budget, 20, 65))
            self.assertEqual(60, budget.reserve_used)
            self.assertTrue(task.final_confirm_observed_pending)
            # Selecting the source only opens the preview. Spending happens
            # at its second confirmation, after the durable pending record.
            self.assertEqual([False, True], task.confirmation_pending_states)
            self.assertFalse(task.refill_pending_path.exists())

    def test_reserve_balance_above_allowance_still_selects_partial_exchange(self):
        task = MaterialRunUI()
        task._exchange_waveplates = Mock(return_value=80)
        budget = MaterialRunBudget(max_reserve=60, max_solvents=1)
        task.refill_at_reward(budget, 20, 65)
        task._exchange_waveplates.assert_called_once_with(budget, 20, 65, 'reserve', 60, True)

    def test_exhausted_reserve_allowance_selects_authorized_solvent(self):
        task = MaterialRunUI()
        task._exchange_waveplates = Mock(return_value=80)
        budget = MaterialRunBudget(max_reserve=60, reserve_used=60, max_solvents=1)
        task.refill_at_reward(budget, 20, 65)
        task._exchange_waveplates.assert_called_once_with(budget, 20, 65, 'solvent', 60, True)

    def test_oversized_reserve_preview_stops_before_spending(self):
        for before, reserve, limit, used, preview in (
                (20, 65, 60, 0, 65),       # Remaining authorization.
                (20, 65, 60, 10, 60),      # Previously consumed authorization.
                (220, 65, 65, 0, 25),      # Waveplate capacity.
                (20, 10, 60, 0, 20)):      # Actual reserve inventory.
            with self.subTest(before=before, reserve=reserve, used=used):
                with tempfile.TemporaryDirectory() as root:
                    task = self.exchange(root, exchange_count=preview)
                    budget = MaterialRunBudget(max_reserve=limit, reserve_used=used)
                    with self.assertRaises(MaterialResourceLimit):
                        task.refill_at_reward(budget, before, reserve)
                    self.assertEqual([False], task.confirmation_pending_states)
                    self.assertFalse(task.refill_pending_path.exists())
                    self.assertEqual(used, budget.reserve_used)
                    task.get_stamina.assert_not_called()

    def test_unverified_partial_reserve_delta_keeps_checkpoint_and_allowance(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.exchange(root, after=80, remaining=65, exchange_count=60)
            budget = MaterialRunBudget(max_reserve=120)
            with self.assertRaises(RefillOutcomeUncertain):
                task.refill_at_reward(budget, 20, 65)
            self.assertTrue(task.refill_pending_path.exists())
            self.assertEqual(60, budget.reserve_used)
            confirmations = task.refill_click.call_count
            with self.assertRaises(RefillOutcomeUncertain):
                task.refill_at_reward(budget, 20, 65)
            self.assertEqual(confirmations, task.refill_click.call_count)
            self.assertEqual(60, budget.reserve_used)

    def test_reward_origin_exchange_returns_directly_to_reward(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.exchange(root)
            task.refill_text = Mock(side_effect=lambda pattern, *a, **kw:
                                   SimpleNamespace(name='兑换次数:1')
                                   if pattern == r'兑换次数[：:]\d+' else
                                   pattern != r'补充结晶波片' or kw.get('timeout') != .5)
            task.reward_dialog_visible = Mock(return_value=True)
            self.assertEqual(80, task.refill_at_reward(MaterialRunBudget(max_solvents=1), 20, 0))
            task.reward_dialog_visible.assert_called_once_with(timeout=1)
            task.send_key.assert_not_called()
            self.assertFalse(task.refill_pending_path.exists())


class TestResumeRewardGuards(unittest.TestCase):
    def test_pending_claim_or_wrong_target_blocks_before_input(self):
        import json
        for pending, target, message in ((True, '心', '结果不明'),
                                         (False, '其他角色', '目标不符')):
            with tempfile.TemporaryDirectory() as root:
                task = TeamMaterialTask.__new__(TeamMaterialTask)
                task.state_path = Path(root) / 'state.json'
                task.state_path.write_text(json.dumps({
                    'claim_pending': pending, 'workflow': {'job_index': 0},
                    'jobs': [{'target': '心', 'cost': 40}]}))
                task.assert_no_pending_refill = Mock()
                task.target_override = target
                task.focus_material_menu = Mock()
                with self.assertRaisesRegex(RuntimeError, message):
                    task.resume_completed_reward()
                task.focus_material_menu.assert_not_called()
