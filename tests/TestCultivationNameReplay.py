"""Replay the 2026-11-01 target-check stop without a device or controller.

Fixture: x=180:665, y=100:235 from the 1920x1080 in-process error frame
logs/cross-team/1793449174480000000/1793451804784837000-error.png.
The frame still shows 心 after the reward; use the production OCR model.
"""
import unittest
from pathlib import Path

import cv2
import numpy as np
from ok import Box
from onnxocr.onnx_paddleocr import ONNXPaddleOcr

from src.task.BaseWWTask import BaseWWTask, MATERIAL_TARGET_BOX
from src.task.CharacterMaterialTask import CharacterMaterialTask


class RecordedTarget:
    current_material_target_name = BaseWWTask.current_material_target_name
    material_target_matches = CharacterMaterialTask.material_target_matches
    _normalize_material_text = staticmethod(BaseWWTask._normalize_material_text)
    width, height = 1920, 1080

    def __init__(self, engine, miss_broad_read=False):
        self.engine, self.miss_broad_read = engine, miss_broad_read
        self.frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        card = cv2.imread(str(Path(__file__).parent/'images/cultivation-xin-after-reward-card.png'))
        self.frame[100:235, 180:665] = card
        self.enlarged_reads = 0

    def box_of_screen(self, left, top, right, bottom):
        return Box(round(left*self.width), round(top*self.height),
                   round((right-left)*self.width), round((bottom-top)*self.height))

    def ocr(self, *, box=None, frame=None, threshold=0):
        if frame is None:
            if self.miss_broad_read:
                return []
            image = self.frame[box.y:box.y+box.height, box.x:box.x+box.width]
            dx, dy = box.x, box.y
        else:
            image, dx, dy = frame, 0, 0
            self.enlarged_reads += 1
        rows = []
        for polygon, (name, confidence) in self.engine.ocr(image)[0]:
            if confidence < threshold:
                continue
            points = np.asarray(polygon)
            left, top = points.min(axis=0)
            right, bottom = points.max(axis=0)
            rows.append(Box(round(left)+dx, round(top)+dy, round(right-left),
                            round(bottom-top), name=name, confidence=confidence))
        return rows


class TestCultivationNameReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)

    def test_error_frame_retains_exact_target_identity(self):
        task = RecordedTarget(self.engine)
        broad = task.ocr(box=task.box_of_screen(*MATERIAL_TARGET_BOX), threshold=.2)
        self.assertTrue(any(row.name == 'N' and row.confidence < .8 for row in broad))
        self.assertTrue(task.material_target_matches('心'))
        self.assertEqual(1, task.enlarged_reads)
        self.assertFalse(task.material_target_matches('鉴心'))
        self.assertEqual('心', task._material_target_observation['observed'])

    def test_missed_broad_read_recovers_from_actual_enlarged_pixels(self):
        task = RecordedTarget(self.engine, miss_broad_read=True)
        self.assertTrue(task.material_target_matches('心'))
        self.assertEqual(1, task.enlarged_reads)
        task.frame[:] = 0
        self.assertFalse(task.material_target_matches('心'))

    def test_revival_title_crop_retains_complete_words(self):
        from src.task.MaterialRunUI import MaterialRunUI, REVIVAL_TITLE_REGION
        from types import SimpleNamespace
        from unittest.mock import Mock
        crop = cv2.imread(str(Path(__file__).parent/'images/revival-item-title-20261101.png'))
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[151:302, 288:1248] = crop
        def read(*region):
            left, top, right, bottom = region
            image = frame[round(top*1080):round(bottom*1080), round(left*1920):round(right*1920)]
            return [SimpleNamespace(name=name) for _, (name, score) in self.engine.ocr(image)[0] if score >= .8]
        task = SimpleNamespace(ocr=read, wait_until=lambda fn, **kw: fn())
        self.assertTrue(MaterialRunUI.menu_text(task, r'选择复苏物品', REVIVAL_TITLE_REGION, timeout=.5))
        frame[:] = 0
        self.assertIsNone(MaterialRunUI.menu_text(task, r'选择复苏物品', REVIVAL_TITLE_REGION, timeout=.5))


if __name__ == '__main__':
    unittest.main()
