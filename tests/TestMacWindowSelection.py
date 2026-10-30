import unittest
from ok.platform.macos.window import MacWindow, MacWindowInfo


class TestMacWindowSelection(unittest.TestCase):
    def window(self, number, on_screen, width=1920, height=1080):
        return MacWindowInfo(number, 1, 'game', 'Game', '', 0, 0, width, height, on_screen, True)

    def test_hidden_previous_window_cannot_pin_controller(self):
        tracker = MacWindow.__new__(MacWindow)
        tracker.window_id = 5
        tracker.bundle_ids, tracker.owner_names, tracker.titles = ['game'], [], []
        old = self.window(5, False)
        main = self.window(6, True)
        floating = self.window(7, True, 66, 20)
        self.assertIs(main, tracker._select_window([old, floating, main]))
