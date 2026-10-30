"""Keep macOS window decoration outside the game's recognition coordinates."""
import sys

import cv2
import numpy as np


def title_rows(frame, point_width):
    """Recognize the 32-point macOS title bar without cropping loading screens."""
    height, width = frame.shape[:2]
    top = round(32 * width / point_width) if point_width else 0
    if not 12 <= top <= min(128, height // 5):
        return 0
    # Ignore the traffic lights, window title, and rounded corners.
    sample = frame[2:top - 2, width // 3:2 * width // 3].astype(float)
    means = sample.mean(axis=(0, 1))
    if 20 <= means.mean() <= 65 and means.max() - means.min() < 8 and sample.std() < 4:
        return top
    return 0


def opaque_game_frame(bgra):
    """Ignore isolated recording badges when finding the full window content."""
    height, width = bgra.shape[:2]
    mask = bgra[:, :, 3] >= 254
    rows = np.flatnonzero(mask.mean(axis=1) >= .9)
    columns = np.flatnonzero(mask.mean(axis=0) >= .9)
    if not len(rows) or not len(columns):
        return bgra[:, :, :3].copy()
    x0, x1 = int(columns[0]), int(columns[-1]) + 1
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    if x1-x0 < .9*width or y1-y0 < .9*height:
        return bgra[:, :, :3].copy()
    return cv2.resize(bgra[y0:y1, x0:x1, :3], (width, height))


def covers_display(window, bounds):
    """A fullscreen window may exclude the menu bar from its reported bounds."""
    return (abs(getattr(window, 'x', -10000)-bounds.origin.x) <= 2
            and -2 <= getattr(window, 'y', 0)-getattr(bounds.origin, 'y', 0) <= 40
            and abs(window.width-bounds.size.width) <= 2
            and bounds.size.height-40 <= getattr(window, 'height', 0) <= bounds.size.height+2)


def fullscreen_window(window):
    import Quartz
    status, displays, count = Quartz.CGGetActiveDisplayList(32, None, None)
    return status == 0 and any(covers_display(window, Quartz.CGDisplayBounds(display))
                              for display in displays[:count])


def install_mac_viewport():
    if sys.platform != 'darwin':
        return
    from ok.device.capture_methods.macos import MacScreenCaptureMethod
    cls = MacScreenCaptureMethod
    if getattr(cls, '_game_viewport_installed', False):
        return
    normalize = cls._normalize_content_frame
    coordinates = cls.get_abs_cords
    width_property, height_property = cls.width, cls.height
    def crop(self, frame):
        geometry = (frame.shape[:2], self.mac_window.width,
                    getattr(self.mac_window, 'height', None),
                    getattr(self.mac_window, 'capture_target_signature', None))
        if getattr(self, '_game_title_geometry', None) != geometry:
            self._game_title_geometry = geometry
            self._game_title_rows = 0
            self._game_fullscreen = fullscreen_window(self.mac_window)
        if not self._game_fullscreen and not self._game_title_rows:
            self._game_title_rows = title_rows(frame, self.mac_window.width)
        return frame[self._game_title_rows:].copy() if self._game_title_rows else frame

    def opaque_content(self, bgra):
        return crop(self, opaque_game_frame(bgra))

    def normalize_content(self, frame):
        cropped = crop(self, frame)
        return cropped if self._game_title_rows else normalize(self, frame)

    def absolute_coordinates(self, x, y):
        # MacWindow retains the raw capture size, including window decoration.
        # Add the removed rows before converting pixels into screen points.
        if getattr(self, '_game_title_rows', 0):
            self.assert_geometry_current()
            return self.mac_window.get_abs_cords(x, y + self._game_title_rows)
        return coordinates(self, x, y)

    def content_width(self):
        frame = self._latest_frame
        return frame.shape[1] if frame is not None else width_property.fget(self)

    def content_height(self):
        frame = self._latest_frame
        return frame.shape[0] if frame is not None else height_property.fget(self)

    cls._opaque_content_frame = opaque_content
    cls._normalize_content_frame = normalize_content
    cls.get_abs_cords = absolute_coordinates
    # Current tasks may have recognized a button immediately before the screen
    # changes. End that round; a new runner performs resolution and party checks.
    cls.stop_on_geometry_change = True
    cls.width = property(content_width)
    cls.height = property(content_height)
    cls._game_viewport_installed = True
