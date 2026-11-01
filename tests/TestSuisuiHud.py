import unittest
from pathlib import Path
import cv2
import numpy as np
from config import config
from ok.feature.FeatureSet import FeatureSet
from src.char.Suisui import Suisui


class TestSuisuiHud(unittest.TestCase):
    def check_fixture(self, filename):
        strip = cv2.imread(str(Path(__file__).parent / 'images' / filename))
        frame = np.zeros((1440, 3440, 3), dtype=np.uint8)
        frame[-strip.shape[0]:, 1400:2050] = strip
        feature_set = FeatureSet(False, 'assets/coco_annotations.json', .002, .002,
                                 hcenter_features=config['template_matching']['hcenter_features'])
        class Task:
            def find_one(self, label, **kwargs):
                return feature_set.find_one_feature(frame, label, **kwargs)
        char = Suisui.__new__(Suisui)
        char.task = Task()
        return char

    def test_real_ultrawide_full_forte_is_found_after_horizontal_drift(self):
        char = self.check_fixture('suisui-full-forte-strip.png')
        self.assertTrue(char.forte2_available())
        self.assertTrue(char.forte3_available())

    def test_empty_enhanced_form_is_not_mistaken_for_full_forte(self):
        char = self.check_fixture('suisui-empty-forte-strip.png')
        self.assertFalse(char.forte2_available())
        self.assertFalse(char.forte3_available())
