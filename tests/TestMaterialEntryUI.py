"""Replay the 2026-10-01 low-waveplate stop through the actual entry flow."""
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
from ok import Box
from src.task.BaseWWTask import BaseWWTask
from src.task.MaterialEntryUI import MaterialEntryUI, entry_warning_buttons
from src.task.MaterialRefillUI import MaterialResourceLimit
from src.task.MaterialRunBudget import MaterialRunBudget


SENTENCE = '结晶波片不足，无法获取奖励，请确认是否继续进入？'


def warning_boxes(width=3024, height=1898, sentence=SENTENCE):
    return [Box(int(x*width), int(y*height), int(w*width), int(.025*height), name=text)
            for x, y, w, text in ((.23, .33, .05, '提示'),
                (.31, .45, .39, sentence), (.31, .60, .06, '取消'), (.63, .60, .06, '确认'))]


class EntryHarness(MaterialEntryUI):
    click_team_challenge = BaseWWTask.click_team_challenge

    def __init__(self, *, allowance=1, panel='catalog', stuck=False):
        self.width, self.height = 3024, 1898
        self._run_budget = MaterialRunBudget(max_reserve=0, max_solvents=allowance)
        self.phase = 'loop'
        self.panel, self.stuck = panel, stuck
        self.clicked = []
        self.sentence = SENTENCE
        self.next_frame = self.focus_material_menu = self.log_info = self.screenshot = Mock()

    def ocr(self, **kwargs):
        return warning_boxes(sentence=self.sentence) if self.panel == 'notice' else []

    def wait_until(self, predicate, **kwargs):
        for _ in range(3):
            result = predicate()
            if result:
                return result
        return None

    def click_box(self, box, **kwargs):
        self.clicked.append(box.name)
        if box.name == '单人挑战':
            self.panel = 'notice'
        elif box.name == '确认' and not self.stuck:
            self.panel = 'team'
        elif box.name == '取消':
            self.panel = 'catalog'

    def wait_click_feature(self, *args, **kwargs):
        if self.panel != 'team':
            return False
        self.clicked.append('开始挑战')
        self.panel = 'world'
        return True

    def wait_ocr(self, *args, **kwargs):
        return [Box(0, 0, 10, 10, name='单人挑战')] if self.panel == 'catalog' else []


class TestMaterialEntryUI(unittest.TestCase):
    def test_empty_stamina_notice_is_handled_before_team_button(self):
        task = EntryHarness()
        self.assertTrue(task.click_team_challenge())
        self.assertEqual(['单人挑战', '确认', '开始挑战'], task.clicked)
        self.assertEqual(0, task._run_budget.solvents_used)
        self.assertFalse(task._run_budget.claim_pending)

    def test_existing_notice_can_resume_without_reclicking_solo(self):
        task = EntryHarness(panel='notice')
        self.assertTrue(task.click_team_challenge())
        self.assertEqual(['确认', '开始挑战'], task.clicked)

    def test_no_allowance_cancels_entry(self):
        task = EntryHarness(allowance=0)
        with self.assertRaises(MaterialResourceLimit):
            task.click_team_challenge()
        self.assertEqual(['单人挑战', '取消'], task.clicked)

    def test_practice_can_enter_without_refill_permission(self):
        task = EntryHarness(allowance=0)
        task.phase = 'practice'
        self.assertTrue(task.click_team_challenge())
        self.assertEqual(0, task._run_budget.solvents_used)

    def test_pending_claim_never_authorizes_another_entry(self):
        task = EntryHarness()
        task._run_budget.begin_claim()
        with self.assertRaises(MaterialResourceLimit):
            task.click_team_challenge()
        self.assertNotIn('确认', task.clicked)

    def test_unresponsive_notice_is_not_confirmed_twice(self):
        task = EntryHarness(stuck=True)
        with self.assertRaisesRegex(RuntimeError, '未关闭'):
            task.click_team_challenge()
        self.assertEqual(['单人挑战', '确认'], task.clicked)

    def test_changed_page_after_focus_is_not_clicked(self):
        task = EntryHarness(panel='notice')
        task.focus_material_menu = lambda: setattr(task, 'panel', 'unknown')
        with self.assertRaisesRegex(RuntimeError, '发生变化'):
            task.click_team_challenge()
        self.assertEqual([], task.clicked)

    def test_other_confirmations_and_duplicate_controls_are_rejected(self):
        for sentence in ('是否消耗星声补充结晶波片？', '确认离开副本？', '结晶波片不足'):
            self.assertIsNone(entry_warning_buttons(warning_boxes(sentence=sentence), 3024, 1898))
        boxes = warning_boxes()
        boxes.append(boxes[-1])
        self.assertIsNone(entry_warning_buttons(boxes, 3024, 1898))

    def test_current_zero_waveplate_notice_uses_expected_claim_cost(self):
        sentence = '领取奖励需要消耗40点结晶波片，当前拥有0点，是否继续？'
        boxes = warning_boxes(1920, 1080, sentence)
        self.assertIsNotNone(entry_warning_buttons(boxes, 1920, 1080, expected_cost=40))
        self.assertIsNone(entry_warning_buttons(boxes, 1920, 1080, expected_cost=60))
        self.assertIsNone(entry_warning_buttons(
            warning_boxes(1920, 1080, sentence.replace('0点', '40点')),
            1920, 1080, expected_cost=40))

    def test_viewport_units_are_independent_of_display_size(self):
        for width, height in ((1920, 1080), (3440, 1440), (3024, 1898)):
            cancel, confirm = entry_warning_buttons(warning_boxes(width, height), width, height)
            self.assertEqual(('取消', '确认'), (cancel.name, confirm.name))

    def test_real_october_first_frame_through_ocr(self):
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        frame = cv2.imread(str(Path(__file__).parent / 'images/low-waveplate-entry-3024.png'))
        h, w = frame.shape[:2]
        x, y = round(w*.20), round(h*.28)
        crop = frame[y:round(h*.70), x:round(w*.80)]
        engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)
        results = engine.ocr(crop, cls=False)[0]
        boxes = []
        for polygon, (text, confidence) in results:
            if confidence < .6:
                continue
            left, top = min(p[0] for p in polygon), min(p[1] for p in polygon)
            right, bottom = max(p[0] for p in polygon), max(p[1] for p in polygon)
            boxes.append(Box(x+left, y+top, right-left, bottom-top, name=text))
        buttons = entry_warning_buttons(boxes, w, h)
        self.assertIsNotNone(buttons, [box.name for box in boxes])
        self.assertEqual(('取消', '确认'), tuple(box.name for box in buttons))
