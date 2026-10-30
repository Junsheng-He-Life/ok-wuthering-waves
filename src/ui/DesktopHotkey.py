"""Listen only for the pause key while a desktop task is active."""
from PySide6.QtCore import QObject, Signal


class DesktopHotkey(QObject):
    toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.listener = None
        self.key = None
        self.down = False
        self.attempted = False

    def enable(self):
        if self.listener:
            return True
        if self.attempted:
            return False
        self.attempted = True
        try:
            import Quartz
            if not Quartz.AXIsProcessTrusted():
                return False
            from pynput import keyboard
            self.key = keyboard.Key.f9
            self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            self.listener.start()
            return True
        except Exception:
            self.disable(reset=False)
            return False

    def _press(self, key):
        if key == self.key and not self.down:
            self.down = True
            self.toggled.emit()

    def _release(self, key):
        if key == self.key:
            self.down = False

    def disable(self, reset=True):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            finally:
                self.listener = None
        self.down = False
        if reset:
            self.attempted = False
