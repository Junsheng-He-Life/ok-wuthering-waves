import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
import threading
import subprocess

import numpy as np

from src.runtime.MacViewport import title_rows, opaque_game_frame, covers_display


class TestMacViewport(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'macOS capture backend')
    def test_recognition_size_and_clicks_share_the_cropped_viewport(self):
        from src.runtime.MacViewport import install_mac_viewport
        install_mac_viewport()
        from ok.device.capture_methods.macos import MacScreenCaptureMethod
        capture = MacScreenCaptureMethod.__new__(MacScreenCaptureMethod)
        capture.mac_window = SimpleNamespace(width=640,
            get_abs_cords=lambda x, y: (436 + x / 2, 275 + y / 2))
        bgra = np.zeros((864, 1280, 4), dtype=np.uint8)
        bgra[:, :, 3] = 255
        bgra[:64, :, :3] = [42, 40, 38]
        capture._latest_frame = capture._opaque_content_frame(bgra)
        capture._size = (1280, 864)  # Stream metadata still includes the title bar.
        self.assertEqual((1280, 800), (capture.width, capture.height))
        self.assertEqual((756, 507), capture.get_abs_cords(640, 400))
        # Loading changes title pixels, not the established window decoration.
        bgra[:64, :, :3] = 0
        self.assertEqual((800, 1280, 3), capture._opaque_content_frame(bgra).shape)

    def test_fullscreen_recording_badge_does_not_expand_content_bounds(self):
        bgra = np.zeros((1000, 1600, 4), dtype=np.uint8)
        bgra[30:, :1560, :3] = [30, 60, 90]
        bgra[30:, :1560, 3] = 255
        bgra[:20, :70] = 255  # Isolated macOS recording indicator.
        result = opaque_game_frame(bgra)
        self.assertEqual((1000, 1600, 3), result.shape)
        self.assertTrue(np.all(result == [30, 60, 90]))

    def test_fullscreen_geometry_excludes_menu_bar_but_has_no_title(self):
        bounds = SimpleNamespace(origin=SimpleNamespace(x=0),
                                 size=SimpleNamespace(width=1512, height=982))
        self.assertTrue(covers_display(SimpleNamespace(x=0, width=1512, height=949), bounds))
        self.assertFalse(covers_display(SimpleNamespace(x=436, width=640, height=432), bounds))

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS capture backend')
    def test_gray_fullscreen_team_page_is_never_cropped_as_title(self):
        from src.runtime.MacViewport import install_mac_viewport
        install_mac_viewport()
        from ok.device.capture_methods.macos import MacScreenCaptureMethod
        capture = MacScreenCaptureMethod.__new__(MacScreenCaptureMethod)
        capture.mac_window = SimpleNamespace(x=0, width=1512, height=949)
        bgra = np.full((1898, 3024, 4), 38, dtype=np.uint8)
        bgra[:, :, 3] = 255
        with patch('src.runtime.MacViewport.fullscreen_window', return_value=True):
            self.assertEqual((1898,3024,3), capture._opaque_content_frame(bgra).shape)
        self.assertEqual(0, capture._game_title_rows)

    def test_retina_title_is_removed_at_its_point_scale(self):
        frame = np.zeros((864, 1280, 3), dtype=np.uint8)
        frame[:64] = 38
        self.assertEqual(64, title_rows(frame, 640))
        frame[:64] = [42, 40, 38]
        self.assertEqual(64, title_rows(frame, 640))

    def test_loading_and_flat_colored_game_content_are_retained(self):
        self.assertEqual(0, title_rows(np.zeros((800, 1280, 3), dtype=np.uint8), 640))
        frame = np.full((800, 1280, 3), [38, 55, 80], dtype=np.uint8)
        self.assertEqual(0, title_rows(frame, 640))

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS capture backend')
    def test_system_fallback_keeps_raw_retina_extent_for_title_click_mapping(self):
        from src.runtime.MacViewport import install_mac_viewport
        from ok.device.capture_methods.macos import MacScreenCaptureMethod
        from ok.platform.macos.window import MacWindow
        install_mac_viewport()
        window = MacWindow.__new__(MacWindow)
        window.window_id, window.pid = 12, 34
        window.x, window.y, window.width, window.height = 436, 275, 640, 432
        window.display_id, window.display_scale = 1, 2.0
        window.capture_width = window.capture_height = 0
        window.helper = SimpleNamespace()
        capture = MacScreenCaptureMethod(window, threading.Event())
        frame = np.full((864, 1280, 3), 120, np.uint8)
        frame[:64] = [42, 40, 38]
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             patch('cv2.imread', return_value=frame), \
             patch('src.runtime.MacViewport.fullscreen_window', return_value=False):
            result = capture._capture_system_snapshot()
        self.assertEqual((800, 1280, 3), result.shape)
        self.assertEqual((1280, 864), (window.capture_width, window.capture_height))
        self.assertEqual((756, 507), capture.get_abs_cords(640, 400))

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS capture backend')
    def test_same_sized_new_display_invalidates_fullscreen_and_title_cache(self):
        from src.runtime.MacViewport import install_mac_viewport
        from ok.device.capture_methods.macos import MacScreenCaptureMethod
        install_mac_viewport()
        capture = MacScreenCaptureMethod.__new__(MacScreenCaptureMethod)
        capture.mac_window = SimpleNamespace(width=640, height=432, capture_target_signature=(1,))
        bgra = np.full((864, 1280, 4), 38, np.uint8)
        bgra[:, :, 3] = 255
        with patch('src.runtime.MacViewport.fullscreen_window', side_effect=[False, True]):
            self.assertEqual(800, capture._opaque_content_frame(bgra).shape[0])
            capture.mac_window.capture_target_signature = (2,)
            self.assertEqual(864, capture._opaque_content_frame(bgra).shape[0])

    def test_matching_width_on_other_vertical_display_is_not_fullscreen(self):
        bounds = SimpleNamespace(origin=SimpleNamespace(x=0, y=-982),
                                 size=SimpleNamespace(width=1512, height=982))
        self.assertFalse(covers_display(SimpleNamespace(x=0, y=33, width=1512, height=949), bounds))
