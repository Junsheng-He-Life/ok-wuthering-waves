"""Offline echo checks: simulated encounters, input, spending and restarts."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.EchoFarmTask import EchoFarmTask, BossEchoTask, TacetEchoTask
from src.task.EchoPickupUI import EchoPickupUI
from src.task.MaterialActivity import MaterialActivity
from src.task.MaterialRefillUI import MaterialRefillUI, RefillOutcomeUncertain
from src.task.MaterialRewardUI import MaterialRewardUI
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestEchoFarmTask(unittest.TestCase):
    def task(self, folder, mode='boss', **settings):
        cls = BossEchoTask if mode == 'boss' else TacetEchoTask
        task = cls.__new__(cls)
        task.config = {'声骸关卡': '哀声鸷' if mode == 'boss' else '无音区·测试',
                       '本次战斗上限': 2, '战后领奖': True, '本次最多领奖': 2,
                       '本次波片上限': 120, '本次储备上限': 0, '本次溶剂上限': 0,
                       **settings}
        task.result = {'status': 'running', 'battles': []}
        task.echo_pending_path = Path(folder) / 'pending.json'
        task.echo_state_path = Path(folder) / 'progress.json'
        task.activity_path = Path(folder) / 'activity.json'
        task.material_state_path = Path(folder) / 'materials.json'
        task.begin_echo_activity()
        task.configure_echo_run()
        return task

    def queue(self, task):
        task.return_to_world = task.load_chars = Mock()
        task.chars = [SimpleNamespace(char_name=name, confidence=.99)
                      for name in ('char_aemeath', 'char_denia', 'char_chisa')]
        task.set_workflow_stage = task.navigate_echo = Mock()
        task.rotation_events = [{'character': 'char_aemeath'}]
        task.fight_verified_domain = Mock()
        task.search_echo = Mock(return_value=True)
        task.leave_echo_encounter = task.heal_at_beacon = Mock()
        def claim(budget):
            budget.begin_claim()
            task.checkpoint_claim()
            budget.finish_claim(120, 60)
            task.checkpoint_claim()
        task.claim_one_reward = Mock(side_effect=claim)

    def test_boss_and_tacet_both_claim_after_verified_win(self):
        for mode in ('boss', 'tacet'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                task = self.task(folder, mode)
                self.queue(task)
                task.run_echo_queue()
                self.assertEqual(2, task.claim_one_reward.call_count)
                self.assertEqual(120, task._run_budget.spent)
                self.assertEqual(2, task._activity.data['claim_units'])
                self.assertFalse(task.echo_pending_path.exists())
                self.assertEqual('completed', task.result['status'])

    def test_absorb_only_ignores_saved_resource_allowances(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, **{'战后领奖': False, '本次储备上限': 240, '本次溶剂上限': 50})
            self.queue(task)
            task.run_echo_queue()
            self.assertEqual(2, task.fight_verified_domain.call_count)
            task.claim_one_reward.assert_not_called()
            self.assertEqual((0, 0, 0), (task._run_budget.max_stamina,
                              task._run_budget.max_reserve, task._run_budget.max_solvents))
            # The public methods are guarded too, independent of queue logic.
            with self.assertRaisesRegex(RuntimeError, '禁止'):
                BossEchoTask.claim_one_reward(task, task._run_budget)
            with self.assertRaisesRegex(RuntimeError, '禁止'):
                task.refill_at_reward(task._run_budget, 0, 240)

    def test_stamina_cap_stops_before_an_extra_encounter(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, **{'本次波片上限': 60})
            self.queue(task)
            task.run_echo_queue()
            task.fight_verified_domain.assert_called_once()
            self.assertEqual(60, task._run_budget.spent)

    def test_failed_battle_never_searches_or_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            self.queue(task)
            task.fight_verified_domain.side_effect = DomainBattleFailed('timeout')
            with self.assertRaises(DomainBattleFailed):
                task.run_echo_queue()
            task.claim_one_reward.assert_not_called()
            task.search_echo.assert_not_called()

    def test_unknown_party_never_enters(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            self.queue(task)
            task.chars[1].char_name = 'unknown'
            with self.assertRaisesRegex(RuntimeError, '三人队伍'):
                task.run_echo_queue()
            task.navigate_echo.assert_not_called()

    def test_failed_fresh_party_read_cannot_reuse_previous_trusted_team(self):
        for load_result in (False, None):
            with self.subTest(load_result=load_result), tempfile.TemporaryDirectory() as folder:
                task = self.task(folder)
                self.queue(task)
                old_chars = task.chars
                task.load_chars = Mock(return_value=load_result)
                with self.assertRaisesRegex(RuntimeError, '不沿用旧队伍'):
                    task.run_echo_queue()
                self.assertIs(old_chars, task.chars)
                task.navigate_echo.assert_not_called()
                task.fight_verified_domain.assert_not_called()
                task.claim_one_reward.assert_not_called()

    def test_unsupported_boss_and_empty_stage_stop_before_navigation(self):
        for stage in ('', '梦魇·赫卡忒', 'not a boss'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    self.task(folder, **{'声骸关卡': stage})

    def test_missing_history_does_not_grant_solvents(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, **{'本次溶剂上限': 10})
            self.assertEqual(0, task._run_budget.max_solvents)

    def test_pending_claim_persists_and_blocks_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task._run_budget.begin_claim()
            task.checkpoint_claim()
            self.assertTrue(json.loads(task.echo_pending_path.read_text())['budget']['claim_pending'])
            task.assert_no_pending_refill = Mock()
            with self.assertRaisesRegex(RuntimeError, '未核对'):
                task.assert_echo_start_safe()

    def test_checkpoint_failure_keeps_guard_after_verified_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task._run_budget.begin_claim()
            task.checkpoint_claim()
            task._run_budget.finish_claim(120, 60)
            task.save_echo_progress = Mock(side_effect=OSError('disk full'))
            with self.assertRaises(OSError):
                task.checkpoint_claim()
            self.assertTrue(task.echo_pending_path.exists())
            self.assertEqual(60, MaterialActivity(task.activity_path).data['waveplates_spent'])

    def test_failed_ledger_save_does_not_double_count_on_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task._run_budget.begin_claim()
            task._run_budget.finish_claim(120, 60)
            save = task._activity.save
            task._activity.save = Mock(side_effect=OSError('interrupted save'))
            with self.assertRaises(OSError):
                task.update_activity()
            task._activity.save = save
            task.update_activity()
            self.assertEqual(60, MaterialActivity(task.activity_path).data['waveplates_spent'])

    def test_material_pending_claim_blocks_echoes(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task.assert_no_pending_refill = Mock()
            task.material_state_path.write_text('{"claim_pending": true}')
            with self.assertRaisesRegex(RuntimeError, '材料队列'):
                task.assert_echo_start_safe()

    def test_echo_pending_claim_blocks_material_start(self):
        original = Path.exists
        with patch('pathlib.Path.exists', lambda p: str(p) == 'logs/echo-claim-pending.json' or original(p)):
            with self.assertRaisesRegex(RefillOutcomeUncertain, '声骸领奖'):
                MaterialRefillUI().assert_no_pending_refill()

    def test_absorb_gate_rejects_reward_f_prompt(self):
        task = EchoPickupUI()
        task.next_frame = Mock()
        task.send_key = Mock()
        task.absorb_echo_text = lambda **kw: '吸收'
        task.find_f_with_text = lambda target_text: target_text == '领取奖励'
        self.assertFalse(task.pick_f())
        task.send_key.assert_not_called()

    def test_unknown_absorb_language_cannot_fall_back_to_generic_f(self):
        task = EchoPickupUI()
        task.next_frame = Mock()
        task.absorb_echo_text = Mock(return_value=None)
        task.find_f_with_text = Mock()
        with self.assertRaisesRegex(RuntimeError, '语言'):
            task.pick_echo()
        task.find_f_with_text.assert_not_called()

    def test_absorb_uncertain_never_replays_f(self):
        task = EchoPickupUI()
        task.next_frame = Mock()
        task.send_key_up = Mock()
        task.send_key = Mock()
        task.absorb_echo_text = lambda **kw: '吸收'
        task.find_f_with_text = Mock(return_value=True)
        task.frame = object()
        task.wait_until = Mock(return_value=False)
        with patch('src.task.EchoPickupUI.cv2.imwrite'), patch('src.task.EchoPickupUI.Path.mkdir'):
            with self.assertRaisesRegex(RuntimeError, '不重复'):
                task.pick_echo()
        self.assertEqual(1, sum(call.args == ('f',) for call in task.send_key.call_args_list))

    def test_open_world_boss_does_not_open_leave_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder)
            task.find_world_earth_icon = Mock(return_value=True)
            task.in_team = Mock(return_value=(True, 0))
            task.in_realm = Mock(return_value=False)
            task.menu_text = Mock(return_value=False)
            task.leave_verified_domain = Mock()
            task.leave_echo_encounter()
            task.leave_verified_domain.assert_not_called()

    def test_real_claim_path_saves_guard_before_click_and_ledger_before_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, **{'本次最多领奖': 1, '本次波片上限': 60})
            task.open_verified_reward = Mock()
            task.get_stamina = Mock(return_value=(120, 0, 120))
            task.reward_option = Mock(return_value=(object(), 1))
            task.set_workflow_stage = task.log_info = Mock()
            task.reward_text = Mock(side_effect=[True, SimpleNamespace(name='剩余60')])
            def click(*args, **kwargs):
                self.assertTrue(task.echo_pending_path.exists())
                self.assertEqual(0, MaterialActivity(task.activity_path).data['waveplates_spent'])
            task.click_box = Mock(side_effect=click)
            self.assertEqual(60, task.claim_one_reward(task._run_budget))
            task.click_box.assert_called_once()
            self.assertFalse(task.echo_pending_path.exists())
            self.assertEqual(60, MaterialActivity(task.activity_path).data['waveplates_spent'])

    def test_tacet_accepts_already_active_encounter_without_start_f(self):
        with tempfile.TemporaryDirectory() as folder:
            task = self.task(folder, 'tacet')
            task.in_team = Mock(return_value=(True, 0))
            task.original_combat_detected = Mock(return_value=True)
            task.send_key = Mock()
            self.assertFalse(task.prepare_verified_battle())
            task.send_key.assert_not_called()

    def test_sixty_cost_double_claim_is_counted_as_two(self):
        ui = MaterialRewardUI()
        ui.reward_text = Mock(side_effect=[SimpleNamespace(name='60单倍领取'), True,
                                           SimpleNamespace(name='120双倍领取'), True])
        budget = MaterialRunBudget(2, 120, 0, 0, claim_cost=60)
        _, multiplier = ui.reward_option(budget)
        budget.begin_claim(multiplier)
        budget.finish_claim(120, 0)
        self.assertEqual((2, 120), (budget.claimed, budget.spent))

    def test_inventory_reader_accepts_merged_header_without_mutating_items(self):
        task = SimpleNamespace(
            phase='echo-inventory', result={}, frame=object(),
            menu_text=Mock(side_effect=[True, True, True]),
            click_relative=Mock(), return_to_world=Mock(), send_key=Mock(), next_frame=Mock(),
            key_config={'Bag Key': 'b'},
            ocr=Mock(side_effect=[[SimpleNamespace(name='声骸902/3000')],
                                  [SimpleNamespace(name='声骸902/3000')]]))
        with patch('cv2.imwrite'):
            check = EchoFarmTask.inspect_echo_inventory(task)
        self.assertEqual((902, 3000), (check['count'], check['capacity']))
        self.assertEqual('bag_header_displayed_count_unit_unverified', check['count_scope'])
        self.assertEqual(check['count_scope'], task.result['inventory_count_scope'])
        self.assertFalse(task.result['inventory_quantity_verified'])
        task.click_relative.assert_called_once_with(.039, .30, after_sleep=.8)
        task.send_key.assert_called_once_with('esc', after_sleep=.6)
        task.return_to_world.assert_not_called()

    def test_unchanged_header_does_not_verify_stacked_echo_quantity(self):
        task = SimpleNamespace(
            phase='echo', echo_mode='tacet', assert_echo_start_safe=Mock(),
            begin_echo_activity=Mock(), configure_echo_run=Mock(), run_echo_queue=Mock(),
            mouse_up=Mock(), send_key_up=Mock(), _stop_combat_debug_frame_recorder=Mock(),
            update_activity=Mock(), save_run_report=Mock())

        def inspect(label):
            task.result.update(inventory_count_scope='bag_header_displayed_count_unit_unverified',
                               inventory_quantity_verified=False)
            return {'count': 921}

        task.inspect_echo_inventory = Mock(side_effect=inspect)
        EchoFarmTask.run(task)
        self.assertEqual(0, task.result['inventory_header_count_delta'])
        self.assertEqual(0, task.result['inventory_added'])
        self.assertTrue(task.result['inventory_verified'])
        self.assertFalse(task.result['inventory_quantity_verified'])

    def test_inventory_reader_stops_before_clicking_an_unknown_bag_page(self):
        task = SimpleNamespace(
            phase='echo-inventory', result={}, menu_text=Mock(return_value=False),
            frame=object(), log_info=Mock(), ocr=Mock(return_value=[]),
            return_to_world=Mock(), send_key=Mock(), click_relative=Mock(), key_config={})
        with patch('cv2.imwrite'), self.assertRaisesRegex(RuntimeError, '背包标题未确认'):
            EchoFarmTask.inspect_echo_inventory(task)
        task.click_relative.assert_not_called()
        task.send_key.assert_called_once_with('b', after_sleep=1)


if __name__ == '__main__':
    unittest.main()
