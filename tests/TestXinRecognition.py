"""Replay real party sidebars through the strict, full-roster character scan.

The template sidebar derives from 1793281599598401000-after.png. The separate
positive capture is 1793281711927392000-before.png. Negative captures are
1793280715324366000-after.png (detonation team) and
1793279610184262000-before.png (Xuanling team), all recorded on 2026-10-30.
Sidebar fixtures retain pixels x=1670:1920, y=180:600 at their original scale.
Only the template source is registered as a feature; the held-out frame is not.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from config import config
from ok.feature.FeatureSet import FeatureSet
from ok.task.task import FindFeature
from src.Labels import Labels
from src.char.BaseChar import CharType, Elements
from src.char.CharFactory import char_dict
from src.char.Xin import Xin
from src.task.BaseCombatTask import BaseCombatTask


class PortraitReplay:
    """Use the production matcher and slot bounds with no device or executor."""
    character_match_threshold = BaseCombatTask.character_match_threshold
    expand_character_search = True
    debug = False
    char_config = {}
    find_best_match_in_box = FindFeature.find_best_match_in_box

    def __init__(self, features, frame):
        self.features, self.frame = features, frame
        self.height, self.width = frame.shape[:2]
        self.chars = [SimpleNamespace(char_name='char_jianxin', confidence=.99)] * 3
        self.team_hint = {str(slot): 'char_jianxin' for slot in range(3)}
        self.log_info = Mock()

    def preferred_character_hint(self, index):
        return ''

    def trust_cached_character_hints(self):
        return False

    def trust_preferred_character_hints(self):
        return False

    def get_box_by_name(self, name):
        return self.features.get_box_by_name(self.frame, name)

    def find_one(self, name, **kwargs):
        matches = self.features.find_one_feature(self.frame, name, **kwargs)
        return max(matches, key=lambda match: match.confidence) if matches else None

    def read_party(self):
        return [BaseCombatTask._load_char_slot(self, slot, f'box_char_{slot + 1}')
                for slot in range(3)]


class TestXinRecognition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = config['template_matching']
        cls.features = FeatureSet(False, 'assets/coco_annotations.json', .002, .002,
                                  default_threshold=.8,
                                  feature_processor=settings.get('feature_processor'),
                                  hcenter_features=settings.get('hcenter_features'),
                                  vcenter_features=settings.get('vcenter_features'))

    def replay(self, fixture=None):
        if fixture is None:
            fixture = 'xin-template-sidebar-1920.png'
        sidebar = cv2.imread(str(Path(__file__).parent / 'images' / fixture))
        self.assertEqual((420, 250, 3), sidebar.shape)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[180:600, 1670:1920] = sidebar
        return PortraitReplay(self.features, frame)

    def assert_party(self, task, expected):
        chars = task.read_party()
        self.assertEqual(expected, [char.char_name for char in chars])
        self.assertTrue(all(char.confidence >= .8 for char in chars))
        return chars

    def test_registered_as_distinct_electric_dps_without_threshold_change(self):
        info = char_dict[Labels.char_xin]
        self.assertIs(Xin, info['cls'])
        self.assertEqual(CharType.MAIN_DPS, info['char_type'])
        self.assertEqual(Elements.ELECTRIC, info['ring_index'])
        self.assertNotEqual(info['cls'], char_dict[Labels.char_jianxin]['cls'])
        self.assertEqual(.8, PortraitReplay.character_match_threshold)

    def test_exported_template_preserves_source_roi_and_one_independent_category(self):
        data = json.loads(Path('assets/coco_annotations.json').read_text())
        categories = [item for item in data['categories'] if item['name'] == 'char_xin']
        self.assertEqual(1, len(categories))
        annotations = [item for item in data['annotations'] if item['category_id'] == categories[0]['id']]
        self.assertEqual(1, len(annotations))
        image = next(item for item in data['images'] if item['id'] == annotations[0]['image_id'])
        self.assertEqual('images/macos-xin-1920.png', image['file_name'])
        x, y, w, h = map(round, annotations[0]['bbox'])
        exported = cv2.imread('assets/images/macos-xin-1920.png')[y:y+h, x:x+w]
        source = self.replay().frame[y:y+h, x:x+w]
        np.testing.assert_array_equal(source, exported)
        self.assertTrue(np.any(exported))

    def test_template_source_resolves_all_three_current_slots(self):
        chars = self.assert_party(self.replay(), ['char_xin', 'char_jinhsi', 'char_douling'])
        self.assertIsInstance(chars[0], Xin)

    def test_independent_capture_resolves_party_over_stale_jianxin_hints(self):
        task = self.replay('xin-party2-heldout-sidebar-1920.png')
        source = self.replay().frame
        self.assertFalse(np.array_equal(source[229:278, 1777:1821], task.frame[229:278, 1777:1821]))
        chars = self.assert_party(task, ['char_xin', 'char_jinhsi', 'char_douling'])
        self.assertGreater(chars[0].confidence, .95)
        self.assertIsInstance(chars[0], Xin)

    def test_other_real_teams_remain_distinct_and_reject_xin_template(self):
        cases = (
            ('xin-negative-detonation-sidebar-1920.png', ['char_aemeath', 'char_denia', 'char_chisa']),
            ('xin-negative-xuanling-sidebar-1920.png', ['yangyang_sp', 'char_phrolova', 'char_suisui']))
        for fixture, expected in cases:
            with self.subTest(fixture=fixture):
                task = self.replay(fixture)
                self.assert_party(task, expected)
                for slot in range(3):
                    box = task.get_box_by_name(f'box_char_{slot + 1}')
                    dx, dy = round(task.height * .05), round(task.height * .012)
                    box = box.copy(x_offset=-dx, y_offset=-dy, width_offset=2 * dx, height_offset=2 * dy)
                    self.assertFalse(task.find_one('char_xin', box=box, threshold=.8))

    def test_unreadable_slot_does_not_inherit_cached_xin_identity(self):
        task = self.replay('xin-party2-heldout-sidebar-1920.png')
        task.chars[0] = SimpleNamespace(char_name='char_xin', confidence=.99)
        task.team_hint['0'] = 'char_xin'
        task.frame[180:310, 1670:1920] = 0
        char = BaseCombatTask._load_char_slot(task, 0, 'box_char_1')
        self.assertEqual('unknown', char.char_name)
        self.assertNotIsInstance(char, Xin)


if __name__ == '__main__':
    unittest.main()
