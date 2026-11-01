"""Real card geometry/counter replay and bounded page recovery, no controller."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
from ok import Box

from tests.TestCultivationNameReplay import RecordedTarget
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
from src.task.MaterialTileVision import material_tiles, counters_for_row, verify_material_rows, MaterialPageReadError
from src.task.NamedMaterialScan import NamedMaterialScanner
from src.task.MaterialIdentity import MaterialIconLibrary


class TestMaterialTileVision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)

    def recorded(self):
        task = RecordedTarget(self.engine)
        # Same 1920x1080 error frame as the name fixture, crop x1056:1574,
        # y162:1015. Keep pixels/scale and restore only the card-search area.
        strip = cv2.imread(str(Path(__file__).parent/'images/material-cards-after-reward-1920.png'))
        task.frame[162:1015, 1056:1574] = strip
        return task

    def test_card_edges_locate_all_seven_icons_and_red_counters(self):
        task = self.recorded()
        tiles = material_tiles(task.frame)
        self.assertEqual(7, len(tiles))
        values = []
        for y in (272, 421, 571, 720, 869):
            values.extend(c.name for c in counters_for_row(task, Box(744, y, 200, 30), tiles, task.frame))
        self.assertEqual(['75/10', '7/60', '3/12', '1/18', '0/6', '0/50', '0/8'], values)

    def test_artwork_crop_survives_changed_digits_and_page_translation(self):
        task = self.recorded()
        tile = material_tiles(task.frame)[0]
        original = tile.icon(task.frame)
        edited = task.frame.copy()
        cv2.rectangle(edited, (tile.x+4, tile.y+80), (tile.x+tile.width-4, tile.y+94), (35, 35, 35), -1)
        np.testing.assert_array_equal(original, tile.icon(edited))
        translated = np.roll(task.frame, 5, axis=0)
        moved = material_tiles(translated)[0]
        np.testing.assert_array_equal(original, moved.icon(translated))
        with tempfile.TemporaryDirectory() as folder:
            library = MaterialIconLibrary(folder, geometry_version='tile-v1')
            library.remember('凝固的弦线', original, 'recorded-popup.png')
            self.assertEqual('凝固的弦线', library.match(moved.icon(translated)))
            self.assertIsNone(library.match(material_tiles(task.frame)[1].icon(task.frame)))

    def test_card_geometry_tracks_capture_scale(self):
        frame = self.recorded().frame
        original = material_tiles(frame)
        for scale in (1.5, 2):
            enlarged = cv2.resize(frame, None, fx=scale, fy=scale)
            tiles = material_tiles(enlarged)
            self.assertEqual(len(original), len(tiles))
            matched = set()
            for old in original:
                new = min(tiles, key=lambda t: abs(t.x/scale-old.x)+abs(t.y/scale-old.y))
                self.assertLess(abs(new.x/scale-old.x), 2)
                self.assertLess(abs(new.y/scale-old.y), 2)
                matched.add(new)
            self.assertEqual(len(original), len(matched))

    def test_old_crop_cache_is_not_silently_used_with_new_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            icon = material_tiles(self.recorded().frame)[0].icon(self.recorded().frame)
            MaterialIconLibrary(folder).remember('旧裁图', icon, 'old.png')
            self.assertIsNone(MaterialIconLibrary(folder, geometry_version='tile-v1').match(icon))

    def test_unreadable_material_heading_cannot_hide_a_visible_need(self):
        task = self.recorded()
        tiles = material_tiles(task.frame)
        with self.assertRaises(MaterialPageReadError):
            verify_material_rows(task, [], tiles, ['武器与技能素材'], task.frame)
        footer = Box(912, 180, 100, 30, name='声骸培养')
        self.assertEqual([footer], verify_material_rows(task, [footer], tiles,
                                                       ['武器与技能素材'], task.frame))

    def test_page_retry_is_bounded_records_errors_and_only_closes_known_popup(self):
        for failures in (1, 3):
            with self.subTest(failures=failures), tempfile.TemporaryDirectory() as folder:
                scanner = object.__new__(NamedMaterialScanner)
                scanner.folder = Path(folder)
                scanner.task = SimpleNamespace(frame=np.zeros((20, 20, 3), dtype=np.uint8),
                    width=1920, height=1080, log_info=Mock(), menu_text=Mock(return_value=False),
                    click=Mock(), sleep=Mock(), scroll_relative=Mock())
                scanner.read_page = Mock(side_effect=[MaterialPageReadError('unreadable')]*failures+[([], True)])
                if failures == 3:
                    with self.assertRaises(MaterialPageReadError):
                        scanner.page('心')
                else:
                    self.assertEqual(([], True), scanner.page('心'))
                errors = [json.loads(line) for line in (scanner.folder/'errors.jsonl').read_text().splitlines()]
                self.assertEqual(failures, len(errors))
                self.assertTrue(all(Path(e['image']).is_file() for e in errors))
                scanner.task.click.assert_not_called()
                scanner.task.scroll_relative.assert_not_called()

    def test_non_recognition_abort_is_never_retried(self):
        scanner = object.__new__(NamedMaterialScanner)
        scanner.read_page = Mock(side_effect=RuntimeError('pending claim'))
        with self.assertRaisesRegex(RuntimeError, 'pending claim'):
            scanner.page('心')
        scanner.read_page.assert_called_once()
