"""Receive timestamped native window frames using one bounded latest-frame slot.

This data I/O adapter never activates a window or sends input. Capture begins
only on an explicit start() call and uses the existing native helper builder.
"""
from __future__ import annotations

import math
import subprocess
import threading
import time

from .capture_protocol import read_timed_frame


class MacFrameSource:
    """Capture one window as BGR uint8 HWC observations with timing metadata.

    Parameters are a positive uint32 macOS window ID and an integer 1--120 fps.
    ``helper`` is an optional MacOSHelper-compatible dependency for offline
    tests. Frames are consumed at most once; a slow reader receives the newest
    frame, with sequence gaps recorded. Stale streams raise after 5 seconds.
    """

    def __init__(self, window_id: int, fps: int = 15, *, helper=None):
        if type(window_id) is not int or not 0 < window_id <= 0xFFFFFFFF:
            raise ValueError("window_id must be a positive uint32 integer")
        if type(fps) is not int or not 1 <= fps <= 120:
            raise ValueError("fps must be an integer from 1 to 120")
        self.window_id, self.fps, self.helper = window_id, fps, helper
        self._condition = threading.Condition()
        self._closed = threading.Event()
        self._process = None
        self._threads = []
        self._latest = None
        self._error = None
        self._stderr = b""
        self._stderr_done = threading.Event()
        self._received_sequence = self._delivered_sequence = 0
        self._last_received_ns = self._started_ns = 0

    def start(self):
        """Start capture without focus/input changes; a source starts only once."""
        if self._process is not None or self._closed.is_set():
            raise RuntimeError("frame source already started or closed")
        if self.helper is None:
            from ok.platform.macos.helper import MacOSHelper
            self.helper = MacOSHelper()
        command = self.helper.command("stream-timed", self.window_id, self.fps)
        self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self._started_ns = time.monotonic_ns()
        try:
            for name, target in (("stderr", self._read_stderr), ("frames", self._read_frames)):
                thread = threading.Thread(target=target, name=f"imitation-capture-{name}", daemon=True)
                thread.start()
                self._threads.append(thread)
        except Exception:
            self.close()
            raise

    def _read_frames(self):
        try:
            while not self._closed.is_set():
                frame = read_timed_frame(self._process.stdout)
                if frame is None:
                    raise EOFError("native frame stream ended")
                with self._condition:
                    if self._closed.is_set():
                        return
                    if frame["sequence"] <= self._received_sequence:
                        raise ValueError("native frame sequence did not increase")
                    self._received_sequence = frame["sequence"]
                    self._last_received_ns = frame["received_ns"]
                    self._latest = frame
                    self._condition.notify_all()
        except Exception as exc:
            if not self._closed.is_set():
                with self._condition:
                    self._error = exc
                    self._condition.notify_all()

    def _read_stderr(self):
        try:
            while not self._closed.is_set():
                chunk = self._process.stderr.read(4096)
                if not chunk:
                    return
                with self._condition:
                    self._stderr = (self._stderr + chunk)[-8192:]
        except (OSError, ValueError):
            return
        finally:
            self._stderr_done.set()

    def check_health(self):
        """Raise RuntimeError for dead, malformed, closed, or stale capture.

        No UI, permission prompt, fallback capture, or automatic restart occurs.
        A successfully started stream has five seconds to deliver its first
        complete frame; after that the same limit applies between frames.
        """
        process = self._process
        if self._closed.is_set() or process is None:
            raise RuntimeError("frame source is closed or not started")
        if isinstance(self._error, EOFError) or process.poll() is not None:
            # EOF and the final error line arrive on different pipes. Wait only
            # on terminal failure, outside the condition needed by stderr's reader.
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
            self._stderr_done.wait(.2)
        with self._condition:
            code = process.poll()
            detail = self._stderr.decode("utf-8", errors="replace").strip() or "<empty>"
            context = f"exit_code={code if code is not None else 'running'}; stderr_tail={detail}"
            if self._error is not None:
                raise RuntimeError(f"frame source failed: {self._error}; {context}") from self._error
            if code is not None:
                raise RuntimeError(f"native capture exited; {context}")
            since = self._last_received_ns or self._started_ns
            if time.monotonic_ns() - since > 5_000_000_000:
                raise RuntimeError(f"native capture produced no complete frame for 5 seconds; {context}")

    def read(self, timeout: float = 1.0) -> dict | None:
        """Consume the newest observation, waiting up to timeout seconds.

        None means a healthy stream has not delivered a new frame before the
        timeout. ``dropped_since_read`` counts native sequence IDs not delivered
        to this consumer, including frames replaced in the single-slot buffer.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        deadline = time.monotonic() + timeout
        while True:
            self.check_health()
            with self._condition:
                if self._latest is not None:
                    frame, self._latest = self._latest, None
                    frame["dropped_since_read"] = frame["sequence"] - self._delivered_sequence - 1
                    self._delivered_sequence = frame["sequence"]
                    return frame
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, .25))

    def close(self):
        """Stop this helper, close pipes, and join reader threads; idempotent."""
        self._closed.set()
        with self._condition:
            self._latest = None
            self._condition.notify_all()
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        for thread in self._threads:
            thread.join(timeout=2)
        if any(thread.is_alive() for thread in self._threads):
            raise RuntimeError("capture reader did not stop after helper termination")
