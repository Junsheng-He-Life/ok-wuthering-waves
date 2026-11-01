import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.MaterialRunUI import MaterialRunUI
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.VerifiedDomainCombat import DomainBattleFailed
from src.combat.XuanlingTeam import XuanlingTeam


class TestMaterialRunBudget(unittest.TestCase):
    def test_two_single_claims_exhaust_limit(self):
        b = MaterialRunBudget()
        for before, after in ((89, 49), (49, 10)):
            b.begin_claim()
            b.finish_claim(before, after)
        self.assertFalse(b.can_claim())
        self.assertEqual(80, b.spent)

    def test_uncertain_claim_cannot_retry_or_recover(self):
        b = MaterialRunBudget()
        b.begin_claim()
        with self.assertRaises(RuntimeError):
            b.finish_claim(80, 80)
        with self.assertRaises(RuntimeError):
            b.begin_claim()
        with self.assertRaises(RuntimeError):
            b.retry()

    def test_reserve_and_recovery_caps(self):
        b = MaterialRunBudget()
        b.record_refill(60)
        with self.assertRaises(RuntimeError):
            b.record_refill(60)
        b.retry()
        with self.assertRaises(RuntimeError):
            b.retry()

    def test_stamina_cap_can_be_lower_than_runs(self):
        b = MaterialRunBudget(max_runs=5, max_stamina=40)
        b.begin_claim()
        b.finish_claim(70, 30)
        self.assertFalse(b.can_claim())


class TestVerifiedMenus(unittest.TestCase):
    def test_boss_single_confirmation_requires_explicit_sixty_cost(self):
        for sentence_found in (False, True):
            task = MaterialRunUI()
            task.find_treasure_icon = task.find_f_with_claim_text = Mock(return_value=True)
            task.walk_to_claim_prompt = task.pick_f = task.log_info = Mock()
            task.open_verified_reward = Mock()
            task.get_stamina = Mock(return_value=(105,159,264))
            task.click_box = Mock()
            box = SimpleNamespace(name='确认')
            task.menu_text = Mock(side_effect=[None, None,
                box if sentence_found else None, box, box, SimpleNamespace(name='剩余45')])
            budget = MaterialRunBudget(1,60,0,0,claim_cost=60)
            if sentence_found:
                self.assertEqual(45, task.claim_one_reward(budget))
                self.assertEqual(60, budget.spent)
                task.click_box.assert_called_once()
            else:
                with self.assertRaisesRegex(RuntimeError, 'cost 60'):
                    task.claim_one_reward(budget)
                task.click_box.assert_not_called()

    def test_revival_overlay_is_dismissed_before_domain_detection(self):
        task = MaterialRunUI()
        task.menu_text = Mock(side_effect=[True, False, False, False, True])
        task.send_key = Mock()
        task.in_realm = Mock(side_effect=[True, False])
        task.find_one = Mock(return_value=None)
        task.menu_click = Mock()
        task.wait_until = Mock(return_value=True)
        task.sleep = Mock()
        task.leave_verified_domain()
        self.assertEqual(task.send_key.call_count, 2)
        task.menu_click.assert_called_once_with(r'确认|Confirm', (.5, .5, .8, .8))
        self.assertEqual(120, task.wait_until.call_args.kwargs['time_out'])

    def test_stuck_revival_overlay_never_confirms_item(self):
        task = MaterialRunUI()
        task.menu_text = Mock(return_value=True)
        task.send_key = Mock()
        task.menu_click = Mock()
        with self.assertRaisesRegex(RuntimeError, '复苏物品窗口未关闭'):
            task.leave_verified_domain()
        task.menu_click.assert_not_called()

    def test_unknown_domain_state_does_not_wait_for_unrequested_exit(self):
        task = MaterialRunUI()
        task.menu_text = Mock(return_value=None)
        task.in_realm = Mock(return_value=False)
        task.find_world_earth_icon = Mock(return_value=None)
        task.wait_until = Mock()
        task.send_key = task.menu_click = Mock()
        task.frame = object()
        with patch('src.task.MaterialRunUI.cv2.imwrite'), self.assertRaisesRegex(RuntimeError, '不等待加载'):
            task.leave_verified_domain()
        task.wait_until.assert_not_called()
        task.send_key.assert_not_called()

    def test_moving_map_does_not_click_a_stale_waypoint(self):
        task = MaterialRunUI()
        # Synthetic detector observations model map panning followed by a
        # stationary active beacon; this test does not replay image pixels.
        task.frame = object()
        points = [SimpleNamespace(name='beacon', x=x, y=300, confidence=.95)
                  for x in (100, 180, 260, 260, 260)]
        task.live_map_beacon = Mock(side_effect=points)
        task.waypoint_has_active_color = Mock(return_value=True)
        observed = []
        def wait(callback, **kw):
            for _ in points:
                observed.append(callback())
            return observed[-1]
        task.wait_until = wait
        with patch('src.task.MaterialRunUI.time.monotonic', side_effect=[0, .2, .4, .6, .9]):
            result = task.stable_map_waypoint()
        self.assertEqual([None] * 4, observed[:4])
        self.assertIs(points[-1], result)
        self.assertEqual(5, task.live_map_beacon.call_count)
        task.live_map_beacon.assert_called_with(task.frame)

    def test_live_ultrawide_hp_crop_includes_leading_digits(self):
        import cv2
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        from src.task.BaseWWTask import BaseWWTask
        strip = cv2.imread(str(Path(__file__).parent / 'images/hp-xuanling-live-strip.png'))
        geometry = BaseWWTask.__new__(BaseWWTask)
        geometry._executor = SimpleNamespace(
            method=SimpleNamespace(width=3440, height=1440),
            device_manager=SimpleNamespace(supported_ratio=16 / 9))
        engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)
        task = MaterialRunUI()
        task.box_of_screen = geometry.box_of_screen
        task.log_info = Mock()
        def ocr(box, frame_processor, **kw):
            x, y = box.x - 1400, box.y - 1350
            image = strip[y:y + box.height, x:x + box.width]
            result = engine.ocr(frame_processor(image), cls=False)[0]
            return [SimpleNamespace(name=text) for _, (text, score) in result
                    if score >= kw['threshold']]
        task.ocr = ocr
        self.assertEqual((18664, 18664), task.read_current_hp())

    def test_small_full_hp_line_is_read_without_losing_a_digit(self):
        import cv2
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        image = cv2.imread(str(Path(__file__).parent / 'images/hp-phrolova-3440.png'))
        engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        def ocr(**kwargs):
            result = engine.ocr(kwargs['frame_processor'](image), cls=False)[0]
            return [SimpleNamespace(name=text) for _, (text, score) in result
                    if score >= kwargs['threshold']]
        task.ocr = ocr
        self.assertEqual((14793, 14793), task.read_current_hp())

    def test_inconsistent_hp_values_are_not_accepted(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        task.ocr = lambda **kw: [SimpleNamespace(name='14793/1479')]
        self.assertIsNone(task.read_current_hp())

    def test_slash_misread_as_seven_requires_previously_verified_max_hp(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        task.ocr = Mock(side_effect=[
            [SimpleNamespace(name='16525/16525')],
            [SimpleNamespace(name='15277716525')],
        ])
        self.assertEqual((16525, 16525), task.read_current_hp())
        self.assertEqual((15277, 16525), task.read_current_hp())
        self.assertTrue(task._hp_observation['repaired_separator'])

    def test_four_digit_current_hp_with_slash_misread_is_repaired(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        task.ocr = Mock(side_effect=[
            [SimpleNamespace(name='17504/17504')],
            [SimpleNamespace(name='9117717504')],
        ])
        self.assertEqual((17504, 17504), task.read_current_hp())
        self.assertEqual((9117, 17504), task.read_current_hp())
        self.assertTrue(task._hp_observation['repaired_separator'])

    def test_unverified_or_ambiguous_digit_only_hp_is_rejected(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        task.ocr = lambda **kw: [SimpleNamespace(name='15277716525')]
        self.assertIsNone(task.read_current_hp())
        task._known_hp_totals = {17504}
        self.assertIsNone(task.read_current_hp())

    def test_zero_hp_is_death_not_unreadable(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.ocr = lambda **kw: [SimpleNamespace(name='0/18664')]
        self.assertEqual((0, 18664), task.read_current_hp())

    def test_premium_source_is_never_confirmed(self):
        task = MaterialRunUI()
        task.ensure_main = Mock()
        task.return_to_world = Mock()
        task.send_key = Mock()
        task.get_stamina = lambda: (20, 60, 80)
        task.open_waveplate_refill = Mock()
        task.click_relative = task.click = task.focus_material_menu = Mock()
        task.width_of_screen = task.height_of_screen = Mock(return_value=1000)
        task.menu_text = Mock(side_effect=[True, None])
        task.menu_click = Mock()
        task.refill_click = Mock()
        with self.assertRaisesRegex(RuntimeError, 'reserve source'):
            task.refill_reserve(MaterialRunBudget())
        task.menu_click.assert_not_called()
        task.refill_click.assert_not_called()

    def test_ambiguous_menu_label_is_not_clicked(self):
        task = MaterialRunUI()
        task.ocr = lambda *args: [SimpleNamespace(name='确认'), SimpleNamespace(name='确认')]
        task.wait_until = lambda callback, **kw: callback()
        task.click_box = Mock()
        with self.assertRaisesRegex(RuntimeError, 'uniquely'):
            task.menu_click('确认')
        task.click_box.assert_not_called()


class TestRotationAndWorkflow(unittest.TestCase):
    def test_xuanling_ready_e_preempts_liberation_and_releases_attack(self):
        from src.char.YangYangSp import YangYangSp
        char = YangYangSp.__new__(YangYangSp)
        char.has_intro = True
        actions = []
        char.task = SimpleNamespace(mouse_down=Mock(side_effect=lambda: actions.append('hold')),
                                    mouse_up=Mock(side_effect=lambda: actions.append('release')))
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 0, 20])
        char.resonance_available = Mock(return_value=True)
        char.liberation_available = Mock(return_value=True)
        char.click_liberation = Mock()
        char.click_resonance = Mock(side_effect=lambda **kw: (actions.append('E') or True, 0, False))
        char.sleep = char.check_combat = char.switch_next_char = char.logger = Mock()
        with patch('src.char.YangYangSp.time.time', side_effect=[1, 1, 1.1, 1.4]):
            char.do_perform()
        self.assertEqual(['hold', 'release', 'E', 'hold', 'release'], actions)
        char.click_liberation.assert_not_called()

    def test_xuanling_failed_liberation_resumes_held_attack(self):
        from src.char.YangYangSp import YangYangSp
        char = YangYangSp.__new__(YangYangSp)
        char.has_intro = True
        char.task = SimpleNamespace(mouse_down=Mock(), mouse_up=Mock())
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 20])
        char.liberation_available = lambda: True
        char.resonance_available = lambda: False
        char.click_liberation = Mock(return_value=False)
        char.sleep = Mock()
        char.logger = Mock()
        char.check_combat = Mock()
        char.switch_next_char = Mock()
        char.do_perform()
        self.assertEqual(2, char.task.mouse_down.call_count)
        char.check_combat.assert_called_once()

    def test_suisui_initial_e_does_not_skip_liberation(self):
        from src.char.Suisui import Suisui
        char = Suisui.__new__(Suisui)
        char.should_heavy = char.has_intro = False
        char.forte3_available = Mock(side_effect=[False, False, True, True])
        char.forte2_available = lambda: False
        char.time_elapsed_accounting_for_freeze = lambda _: 0
        char.cycle_start = Mock()
        char.try_e = Mock(return_value=True)
        char.click = char.cycle_sleep = Mock()
        char.logger = Mock()
        char.task = SimpleNamespace(next_frame=Mock())
        char.click_liberation = Mock(return_value=True)
        char.is_con_full = lambda: True
        char.switch_next_char = Mock()
        char.do_perform()
        char.switch_next_char.assert_called_once()
        char.click_liberation.assert_called_once()

    def test_suisui_forte_timeout_still_casts_ready_liberation(self):
        from src.char.Suisui import Suisui
        char = Suisui.__new__(Suisui)
        char.should_heavy = False
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[30, 0, 0])
        char.click_liberation = Mock(return_value=True)
        char.is_con_full = char.forte3_available = lambda: True
        char.task = SimpleNamespace(next_frame=Mock())
        char.logger = Mock()
        char.perform_forte3_rotation()
        char.click_liberation.assert_called_once()

    def test_xuanling_resumes_attack_after_guarded_animation(self):
        from src.char.YangYangSp import YangYangSp
        char = YangYangSp.__new__(YangYangSp)
        char.has_intro = True
        char.task = SimpleNamespace(mouse_down=Mock(), mouse_up=Mock())
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 0, 20])
        char.liberation_available = char.resonance_available = lambda: False
        char.click_echo = lambda **kw: True
        char.sleep = lambda *a, **kw: setattr(char.task, 'held_attack_interrupted', True)
        char.check_combat = Mock()
        char.switch_next_char = Mock()
        char.do_perform()
        self.assertEqual(3, char.task.mouse_down.call_count)
        char.task.mouse_up.assert_called_once()

    def test_outro_recipient_follows_identity_after_slot_reordering(self):
        task = XuanlingTeam()
        task.chars = [SimpleNamespace(char_name=name) for name in
                      ('char_phrolova', 'yangyang_sp', 'char_suisui')]
        for index, expected in ((0, 1), (1, 2), (2, 0)):
            char = task.chars[index]
            target = task.preferred_switch_target(char, [c for c in task.chars if c is not char], True)
            self.assertIs(task.chars[expected], target)

    def runner(self):
        task = SafeMaterialTask.__new__(SafeMaterialTask)
        task.phase = 'loop'
        task.expected_target = '弗洛洛'
        task.exact_stage = '旋雾之森'
        task.run_limit, task.reserve_limit = 2, 0
        task.rotation_events = []
        for name in ('ensure_main', 'return_to_world', 'heal_at_beacon', 'open_materials_book',
                     'fight_verified_domain', 'leave_verified_domain', 'mouse_up',
                     'send_key_up', '_stop_combat_debug_frame_recorder', 'save_run_report', 'log_info'):
            setattr(task, name, Mock())
        task.ensure_cultivation_target = lambda target: '弗洛洛'
        task.get_stamina = lambda: (80, 300, 380)
        task.enter_character_material_domain = lambda route: True
        def claim(budget):
            budget.begin_claim()
            budget.finish_claim(80, 40)
            return 40
        task.claim_one_reward = Mock(side_effect=claim)
        return task

    def test_workflow_stops_after_two_claims_and_heals(self):
        task = self.runner()
        task.run()
        self.assertEqual('completed', task.result['status'])
        self.assertEqual(2, task.claim_one_reward.call_count)
        self.assertEqual(3, task.heal_at_beacon.call_count)

    def test_practice_never_refills_or_claims_even_with_empty_stamina(self):
        task = self.runner()
        task.phase = 'practice'
        task.get_stamina = lambda: (0, 300, 300)
        task.refill_reserve = Mock()
        task.run()
        self.assertEqual('practice_completed_no_claim', task.result['status'])
        task.claim_one_reward.assert_not_called()
        task.refill_reserve.assert_not_called()
        self.assertEqual(0, task.result['budget']['max_stamina'])
        self.assertEqual(0, task.result['budget']['max_reserve'])

    def test_failed_fights_do_not_claim_and_recovery_is_bounded(self):
        task = self.runner()
        task.fight_verified_domain.side_effect = DomainBattleFailed('timeout')
        with self.assertRaisesRegex(RuntimeError, 'recovery limit'):
            task.run()
        task.claim_one_reward.assert_not_called()
        self.assertEqual(2, task.fight_verified_domain.call_count)

    def test_uncertain_settlement_never_starts_another_fight(self):
        task = self.runner()
        def uncertain(budget):
            budget.begin_claim()
            raise RuntimeError('settlement uncertain')
        task.claim_one_reward.side_effect = uncertain
        with self.assertRaisesRegex(RuntimeError, 'settlement uncertain'):
            task.run()
        task.fight_verified_domain.assert_called_once()
        self.assertTrue(task.result['budget']['claim_pending'])


class TestRewardNavigation(unittest.TestCase):
    def test_observed_marker_behind_character_does_not_move_forward(self):
        direction, duration = MaterialRunUI.reward_step(1533, 1124, 3440, 1440)
        self.assertEqual('s', direction)
        self.assertLessEqual(duration, .2)

    def test_forward_and_lateral_steps_scale_with_viewport(self):
        for width, height in ((3440, 1440), (1920, 1080)):
            for x, y, expected in ((.5, .4, 'w'), (.8, .5, 'd'), (.2, .5, 'a')):
                self.assertEqual(expected, MaterialRunUI.reward_step(
                    x * width, y * height, width, height)[0])


class TestSolventBudget(unittest.TestCase):
    def test_solvent_is_opt_in_and_bounded(self):
        with self.assertRaises(RuntimeError):
            MaterialRunBudget().record_solvent()
        budget = MaterialRunBudget(max_solvents=1)
        budget.record_solvent()
        with self.assertRaises(RuntimeError):
            budget.record_solvent()
        self.assertEqual(1, budget.solvents_used)


class TestSolventExchange(unittest.TestCase):
    def test_final_confirmation_requires_all_four_fields(self):
        for missing in range(4):
            task = MaterialRunUI()
            task.refill_text = Mock(side_effect=[
                SimpleNamespace(name='兑换次数:1', x=508, y=618),
                *(False if i == missing else True for i in range(4))])
            with self.assertRaisesRegex(RuntimeError, '禁止确认'):
                task.verify_solvent_exchange()
        task.refill_text = Mock(side_effect=[SimpleNamespace(name='兑换次数:1', x=508, y=618),
                                             True, True, True, True])
        task.verify_solvent_exchange()
        self.assertEqual(5, task.refill_text.call_count)

    def test_two_solvents_are_verified_as_120_waveplates(self):
        task = MaterialRunUI()
        task.refill_text = Mock(side_effect=[
            SimpleNamespace(name='兑换次数:2', x=508, y=618),
            True, True, True, True])
        self.assertEqual(2, task.verify_solvent_exchange())
        patterns = [call.args[0] for call in task.refill_text.call_args_list]
        self.assertIn(r'结晶溶剂[x×X]2', patterns)
        self.assertIn(r'结晶波片[x×X]120', patterns)


class TestWholeHpReading(unittest.TestCase):
    def hp_task(self, raw, known=()):
        import numpy as np
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        task.ocr = Mock(return_value=[SimpleNamespace(name=raw)])
        task._known_hp_totals = set(known)
        task.frame = np.zeros((10, 10, 3), dtype=np.uint8)
        task.in_team = Mock(return_value=(True, 2, 3))
        return task

    def test_both_numeric_scales_conflicting_with_bar_stay_unknown(self):
        task = self.hp_task('14730/17578')
        with patch('src.combat.PortraitHealth.portrait_health', return_value=[1., 1., .27]):
            self.assertIsNone(task.read_current_hp())
        self.assertEqual(2, task.ocr.call_count)
        self.assertIsNone(task._hp_observation['parsed'])
        self.assertEqual('numeric_portrait_disagreement', task._hp_observation['rejected'])
        self.assertEqual(set(), task._known_hp_totals)

    def test_damaged_full_hp_separator_uses_current_same_frame_bar(self):
        for raw in ('38323738323', '38323/738323'):
            with self.subTest(raw=raw):
                task = self.hp_task(raw)
                with patch('src.combat.PortraitHealth.portrait_health',
                           return_value=[None, None, 1.0]) as portrait:
                    self.assertEqual((38323, 38323), task.read_current_hp())
                self.assertIs(portrait.call_args.args[0], task._hp_observation_frame)
                self.assertEqual({38323}, task._known_hp_totals)
                self.assertTrue(task._hp_observation['repaired_separator'])

    def test_damaged_separator_cannot_infer_full_hp_from_other_slot(self):
        for raw in ('38323738323', '38323/738323'):
            for current_bar in (None, .2):
                with self.subTest(raw=raw, bar=current_bar):
                    task = self.hp_task(raw)
                    with patch('src.combat.PortraitHealth.portrait_health',
                               return_value=[1.0, 1.0, current_bar]):
                        self.assertIsNone(task.read_current_hp())
                    self.assertEqual(set(), task._known_hp_totals)

    def test_repaired_low_hp_preserves_numeric_current_value(self):
        for raw in ('9000738323', '9000/738323'):
            with self.subTest(raw=raw):
                task = self.hp_task(raw, known=(38323,))
                with patch('src.combat.PortraitHealth.portrait_health',
                           return_value=[1.0, 1.0, .235]):
                    self.assertEqual((9000, 38323), task.read_current_hp())
                self.assertEqual({38323}, task._known_hp_totals)

    def test_unknown_low_digits_and_bright_bar_do_not_become_full_hp(self):
        task = self.hp_task('9000738323')
        with patch('src.combat.PortraitHealth.portrait_health', return_value=[1.0] * 3):
            self.assertIsNone(task.read_current_hp())
        task.ocr.return_value = [SimpleNamespace(name='9000/38323')]
        self.assertEqual((9000, 38323), task.read_current_hp())

    def test_six_digit_max_is_supported_when_same_frame_ratio_agrees(self):
        task = self.hp_task('60000/123456')
        with patch('src.combat.PortraitHealth.portrait_health', return_value=[None, None, .486]):
            self.assertEqual((60000, 123456), task.read_current_hp())
        self.assertEqual({123456}, task._known_hp_totals)

    def test_unverified_six_digit_max_never_pollutes_known_totals(self):
        for raw in ('60000/123456', '38323/738323', '0/000000'):
            with self.subTest(raw=raw):
                task = self.hp_task(raw)
                with patch('src.combat.PortraitHealth.portrait_health', return_value=[None] * 3):
                    self.assertIsNone(task.read_current_hp())
                self.assertEqual(set(), task._known_hp_totals)

    def test_corrupted_leading_digits_never_become_critical_suffix(self):
        task = MaterialRunUI()
        task.box_of_screen = Mock()
        task.log_info = Mock()
        for raw in ('2B549/33398', '23S49/33398', '23549/33398x', '18664718664'):
            task.ocr = Mock(return_value=[SimpleNamespace(name=raw)])
            self.assertIsNone(task.read_current_hp(), raw)
        for raw, expected in [('23549/33398',(23549,33398)), ('0/33398',(0,33398)),
                              ('12151/17504.', (12151,17504))]:
            task.ocr = Mock(return_value=[SimpleNamespace(name=raw)])
            self.assertEqual(expected, task.read_current_hp())


class TestFiftySolventLimit(unittest.TestCase):
    def test_fifty_allowed_but_fifty_first_rejected(self):
        budget = MaterialRunBudget(100, 4000, 120, max_solvents=50)
        for _ in range(50):
            budget.record_solvent()
        with self.assertRaises(RuntimeError):
            budget.record_solvent()
        self.assertEqual(50, budget.solvents_used)
