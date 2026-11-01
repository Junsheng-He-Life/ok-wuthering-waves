import unittest
from types import SimpleNamespace as Box
from src.task.WaveplateReading import parse_waveplates

class TestWaveplateReading(unittest.TestCase):
    def test_live_add_button_tracks_badge_at_two_scales(self):
        from pathlib import Path
        import cv2
        from src.task.WaveplateReading import find_waveplate_add_box
        image = cv2.imread(str(Path(__file__).parent / 'images/waveplate-add-live.png'))
        for scale in (1., 1.5):
            frame = cv2.resize(image, None, fx=scale, fy=scale)
            badge = Box(name='11/240', x=98*scale, y=43*scale, width=110*scale, height=39*scale)
            button = find_waveplate_add_box(frame, [badge])
            self.assertIsNotNone(button)
            self.assertAlmostEqual(254.5*scale, button.x+button.width/2, delta=2)

    def test_add_button_rejects_missing_or_ambiguous_badge_and_blank_frame(self):
        import numpy as np
        from src.task.WaveplateReading import find_waveplate_add_box
        frame = np.zeros((110,310,3), dtype='uint8')
        badge = Box(name='11/240', x=98, y=43, width=110, height=39)
        for rows in ([], [badge], [badge,badge]):
            self.assertIsNone(find_waveplate_add_box(frame, rows))

    def test_16_10_counter_merged_with_refill_plus(self):
        boxes = [Box(name='125', x=724, width=55),
                 Box(name='55/240 +', x=886, width=126)]
        self.assertEqual((55, 125, 180), parse_waveplates(boxes, 1280))

    def test_1080p_material_page_counters(self):
        boxes = [Box(name='124', x=1113, width=67),
                 Box(name='240/240', x=1329, width=129),
                 Box(name='+', x=1479, width=51)]
        self.assertEqual((240, 124, 364), parse_waveplates(boxes, 1920))

    def test_plain_current_not_reserve(self):
        boxes=[Box(name='0',x=700,width=20),Box(name='71',x=800,width=20)]
        self.assertEqual((71,0,71),parse_waveplates(boxes,1000))
        boxes[1].name='71/240'
        self.assertEqual((71,0,71),parse_waveplates(boxes,1000))
    def test_missing_or_duplicate_counter_not_zero(self):
        b=Box(name='71',x=800,width=20)
        self.assertEqual((-1,-1,-1),parse_waveplates([b],1000))
        self.assertEqual((-1,-1,-1),parse_waveplates([b,b],1000))

    def test_reward_dialog_shifted_reserve(self):
        boxes=[Box(name='0',x=731,width=20),Box(name='72/240',x=820,width=30)]
        self.assertEqual((72,0,72),parse_waveplates(boxes,1000))

    def test_reward_missing_zero_uses_crop_left_of_current_badge(self):
        from unittest.mock import Mock
        from src.task.BaseWWTask import BaseWWTask
        from ok import Box
        current = Box(1429, 45, 120, 40, name='158/240')
        task = type('BoxTask', (), {})()
        task.width, task.height = 1920, 1080
        task.ocr = Mock(side_effect=[[current], [Box(1250, 45, 20, 40, name='0')]])
        task.wait_until = lambda fn, **kw: fn()
        task.info_set = Mock()
        self.assertEqual((158, 0, 158), BaseWWTask.get_stamina(task))
        crop = task.ocr.call_args.kwargs['box']
        self.assertLess(crop.x + crop.width, current.x)
        self.assertLess(crop.x, 1250)
        self.assertGreater(crop.x + crop.width, 1270)
