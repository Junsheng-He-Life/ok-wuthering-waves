"""Replay the translucent world HUD against real world/domain/reward crops."""
from pathlib import Path
from types import SimpleNamespace
import unittest

import cv2
import numpy as np
from config import config
from ok.feature.FeatureSet import FeatureSet
from src.task.BaseWWTask import BaseWWTask


class TestWorldIconRecognition(unittest.TestCase):
    def matches(self, index):
        crop = cv2.imread(str(Path(__file__).parent / 'images' /
                              f'world-icon-replay-{index}.png'))
        self.assertIsNotNone(crop)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[:crop.shape[0], :crop.shape[1]] = crop
        features = FeatureSet(False, 'assets/coco_annotations.json', .002, .002,
                             hcenter_features=config['template_matching']['hcenter_features'])
        task = SimpleNamespace(find_one=lambda label, **kw:
                               features.find_one_feature(frame, label, **kw))
        return BaseWWTask.find_world_earth_icon(task)

    def test_bright_and_dark_world_backgrounds_keep_the_same_globe(self):
        for index in (0, 1, 5):
            with self.subTest(index=index):
                self.assertTrue(self.matches(index))

    def test_domain_exit_and_reward_headers_are_not_world_globes(self):
        for index in (2, 3, 4):
            with self.subTest(index=index):
                self.assertFalse(self.matches(index))
