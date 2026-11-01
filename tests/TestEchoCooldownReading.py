"""Replay native Echo skill-row crops without constructing a controller.

Fixtures are the unchanged x=.82..97, y=.86..93 region of saved 1920x1080
frames 1793277466617457000 (R cooldown 20.4) and 1793277455644244000
(lit R with no cooldown digits), recorded on 2026-10-29.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
from onnxocr.onnx_paddleocr import ONNXPaddleOcr

from src.task.BaseCombatTask import BaseCombatTask
from src.task.BaseWWTask import isolate_white_text_to_black


class TestEchoCooldownReading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)

    def task(self, fixture=None, enabled=True):
        task = SimpleNamespace(
            scene=SimpleNamespace(cd_refreshed=False), cds={},
            get_current_char=lambda: SimpleNamespace(index=0),
            width_of_screen=lambda ratio: round(1920 * ratio),
            _cd_ocr_relative_x=lambda ratio: ratio,
            allow_opportunistic_skills=lambda: enabled,
            time_elapsed_accounting_for_freeze=lambda timestamp: 0,
            log_debug=Mock())
        task.refresh_cd = lambda: BaseCombatTask.refresh_cd(task)
        task.get_cd = lambda name, index=None: BaseCombatTask.get_cd(task, name, index)
        task.ocr = Mock(return_value=[])
        if fixture:
            crop = cv2.imread(str(Path(__file__).parent / 'images' / fixture))
            self.assertEqual((76, 288, 3), crop.shape)

            def ocr(x, y, to_x, to_y, frame_processor, match):
                self.assertEqual((.82, .86, .97, .93), (x, y, to_x, to_y))
                image = frame_processor(crop) if frame_processor else crop
                result = self.engine.ocr(image, cls=False)[0] or []
                return [SimpleNamespace(name=text, x=1574 + pos[0][0])
                        for pos, (text, confidence) in result
                        if confidence >= .2 and match.search(text)]

            task.ocr = Mock(side_effect=ocr)
        return task

    def test_native_echo_reads_visible_gray_cooldown_digits(self):
        task = self.task('echo-xuanling-r-cooldown-1920.png')
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            self.assertAlmostEqual(20.4, task.get_cd('liberation'), places=1)
            self.assertTrue(BaseCombatTask.has_cd(task, 'liberation'))
        self.assertIsNone(task.ocr.call_args.kwargs['frame_processor'])
        task.ocr.assert_called_once()

    def test_ready_icon_without_digits_is_not_a_cooldown(self):
        task = self.task('echo-xuanling-r-ready-1920.png')
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            self.assertFalse(BaseCombatTask.has_cd(task, 'liberation'))
            self.assertEqual(0, task.get_cd('liberation'))

    def test_existing_isolation_loses_digits_in_regression_fixture(self):
        task = self.task('echo-xuanling-r-cooldown-1920.png', enabled=False)
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            self.assertEqual(0, task.get_cd('liberation'))
        self.assertIs(isolate_white_text_to_black,
                      task.ocr.call_args.kwargs['frame_processor'])

    def test_non_native_and_disabled_policies_keep_existing_processor(self):
        for platform, enabled in [('win32', True), ('darwin', False)]:
            with self.subTest(platform=platform, enabled=enabled):
                task = self.task(enabled=enabled)
                with patch('src.task.BaseCombatTask.sys.platform', platform):
                    task.refresh_cd()
                self.assertIs(isolate_white_text_to_black,
                              task.ocr.call_args.kwargs['frame_processor'])

    def test_material_battle_reads_actual_failed_cast_frame_without_echo_policy(self):
        task = self.task('material-chisa-e-cooldown-20261101.png', enabled=False)
        task._verified_battle = True
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            self.assertAlmostEqual(11.0, task.get_cd('resonance'), places=1)
            self.assertAlmostEqual(18.7, task.get_cd('echo'), places=1)
        self.assertIsNone(task.ocr.call_args.kwargs['frame_processor'])

    def test_material_failure_frame_was_erased_by_old_white_filter(self):
        task = self.task('material-chisa-e-cooldown-20261101.png', enabled=False)
        with patch('src.task.BaseCombatTask.sys.platform', 'darwin'):
            self.assertEqual(0, task.get_cd('resonance'))


if __name__ == '__main__':
    unittest.main()
