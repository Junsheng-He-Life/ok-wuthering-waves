"""Replay annotated ring crops from existing in-process combat recordings."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from src.task.BaseCombatTask import BaseCombatTask, con_colors


FIXTURES = Path(__file__).parent / 'images'
SAMPLES = json.loads((FIXTURES / 'concerto-recorded-manifest.json').read_text())


class TestRecordedConcertoRings(unittest.TestCase):
    def test_real_full_and_partial_rings_across_teams(self):
        # Human-reviewed full rings: 7 fire/havoc/ice examples from teams 4/5.
        # Ten negatives include thick half rings and nearly full spectro rings
        # whose small unfilled gray arcs the old density-only rule accepted.
        for sample in SAMPLES:
            with self.subTest(image=sample['image']):
                image = cv2.imread(str(FIXTURES / sample['image']))
                self.assertEqual(sample['full'], BaseCombatTask.is_sparse_con_ring_full(
                    image, con_colors[sample['color_index']]))

    def test_recorded_rings_preserve_decision_when_capture_is_doubled(self):
        for sample in SAMPLES:
            with self.subTest(image=sample['image']):
                image = cv2.imread(str(FIXTURES / sample['image']))
                image = cv2.resize(image, (126, 126), interpolation=cv2.INTER_NEAREST)
                self.assertEqual(sample['full'], BaseCombatTask.is_sparse_con_ring_full(
                    image, con_colors[sample['color_index']]))

    def test_gray_ring_and_colored_center_are_not_a_full_ring(self):
        image = np.zeros((63, 63, 3), np.uint8)
        cv2.circle(image, (37, 31), 25, (120, 120, 120), 3)
        cv2.circle(image, (37, 31), 12, (90, 115, 215), 3)
        self.assertFalse(BaseCombatTask.is_sparse_con_ring_full(image, con_colors[2]))

    def test_complete_get_current_con_path_cannot_bypass_negative_geometry(self):
        for sample in SAMPLES:
            with self.subTest(image=sample['image']):
                image = cv2.imread(str(FIXTURES / sample['image']))
                color_index = sample['color_index']
                box = SimpleNamespace(confidence=0, crop_frame=lambda frame: frame)
                task = SimpleNamespace(
                    frame=image, get_con_box=lambda: box,
                    _ensure_ring_index=lambda: color_index,
                    screen_width=1920, screen_height=1080,
                    use_sparse_con_ring_detection=lambda: True,
                    is_sparse_con_ring_full=BaseCombatTask.is_sparse_con_ring_full,
                    get_current_char=lambda: sample['image'], logger=Mock(),
                    con_full_size={str(color_index): 100}, draw_boxes=Mock())
                task.count_rings = lambda *args: BaseCombatTask.count_rings(task, *args)
                result = BaseCombatTask.get_current_con(task)
                self.assertEqual(sample['full'], result == 1)


if __name__ == '__main__':
    unittest.main()
