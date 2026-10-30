"""Observe foreground game input through a passive macOS Quartz event tap.

Records contain callback ``t_ns`` from Python's monotonic clock. Quartz's
``event_source_ns`` is diagnostic only: its epoch is not assumed to match
frame timestamps. Mouse deltas retain Quartz relative units; scroll deltas
retain Quartz integer wheel units. No character text or cursor position is
read. Ctrl/Option are reserved recorder controls, never action labels.
"""

import threading
import time


# Physical ANSI keycodes: WASD, QERFT, B/M, 1-4, Tab, Space, Escape, F2.
GAME_KEYS = frozenset({0, 1, 2, 3, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21,
                       46, 48, 49, 53, 120})
MODIFIER_KEYS = frozenset({54, 55, 56, 58, 59, 60, 61, 62})
RESERVED_MODIFIERS = frozenset({54, 55, 58, 59, 61, 62})
CONTROL_KEYS = {18: 'toggle', 19: 'success', 20: 'failure', 29: 'stop'}
BUTTONS = {0: 'left', 1: 'right', 2: 'middle'}


class MacInputObserver:
    """Stream fixed game controls only while ``pid`` is the foreground app.

    ``emit(dict)`` and ``control(str)`` normally run on the observer thread;
    explicit ``check_focus()`` emits on its caller. Both must be fast,
    thread-safe sinks. Records use kinds key (code/down), button
    (button/down), mouse_move or scroll (dx/dy), focus (active), and reset
    (reason). A reset invalidates held action state; exporters must not join
    samples across it. Ctrl+Option+1/2/3/0 controls recording globally, with a
    ``control_hotkey`` reset immediately before its control callback.

    Optional Quartz, foreground-PID and clock dependencies allow offline
    tests. Construction neither requests permissions nor starts monitoring.
    """

    def __init__(self, pid, emit, control, *, quartz=None, frontmost_pid=None,
                 clock=time.monotonic_ns):
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError('pid must be a positive process identifier')
        self.pid, self.emit, self.control = pid, emit, control
        self.q, self._frontmost_pid, self.clock = quartz, frontmost_pid, clock
        self._active = None
        self._keys, self._buttons, self._control_down = set(), set(), set()
        self._lock = threading.RLock()
        self._stop, self._ready = threading.Event(), threading.Event()
        self._thread = self._tap = self._loop = None
        self._error = None

    def _write(self, kind, *, source=None, **fields):
        record = {'t_ns': self.clock(), 'kind': kind, **fields}
        if source is not None:
            record['event_source_ns'] = source
        self.emit(record)

    def _reset(self, reason, source=None):
        self._keys.clear()
        self._buttons.clear()
        self._write('reset', reason=reason, source=source)

    def snapshot(self):
        """Return held physical keys (including modifiers) and button names.

        Queries only the fixed whitelist when the target is foreground;
        background or unstarted observers return empty lists. Callers should
        wait for both lists to empty before starting a training segment.
        """
        with self._lock:
            if self.q is None or not self._active:
                return {'keys': [], 'buttons': []}
            q, state = self.q, self.q.kCGEventSourceStateCombinedSessionState
            return {
                'keys': sorted(k for k in GAME_KEYS | MODIFIER_KEYS | CONTROL_KEYS.keys()
                               if q.CGEventSourceKeyState(state, k)),
                'buttons': [name for code, name in BUTTONS.items()
                            if q.CGEventSourceButtonState(state, code)],
            }

    def check_focus(self):
        """Poll foreground PID; emit focus/reset boundaries even without input."""
        with self._lock:
            active = self._frontmost_pid() == self.pid
            if active != self._active:
                self._active = active
                self._write('focus', active=active)
                self._reset('focus_changed')
            return active

    def _transition(self, kind, value, down, source):
        held = self._keys if kind == 'key' else self._buttons
        if down == (value in held):
            return
        (held.add if down else held.discard)(value)
        field = 'code' if kind == 'key' else 'button'
        self._write(kind, source=source, **{field: value, 'down': down})

    def _handle(self, event_type, event):
        q = self.q
        if event_type in (q.kCGEventTapDisabledByTimeout, q.kCGEventTapDisabledByUserInput):
            self._control_down.clear()
            self._reset('tap_disabled')
            q.CGEventTapEnable(self._tap, True)
            return
        active = self.check_focus()
        if not active and event_type not in (q.kCGEventKeyDown, q.kCGEventKeyUp):
            return
        source = int(q.CGEventGetTimestamp(event))
        get = lambda field: int(q.CGEventGetIntegerValueField(event, field))
        if event_type in (q.kCGEventKeyDown, q.kCGEventKeyUp, q.kCGEventFlagsChanged):
            code = get(q.kCGKeyboardEventKeycode)
            flags = int(q.CGEventGetFlags(event))
            chord = q.kCGEventFlagMaskControl | q.kCGEventFlagMaskAlternate
            control_chord = flags & chord == chord
            if code in self._control_down:
                if event_type == q.kCGEventKeyUp:
                    self._control_down.discard(code)
                return
            if code in CONTROL_KEYS and control_chord and event_type == q.kCGEventKeyDown:
                if get(q.kCGKeyboardEventAutorepeat):
                    return
                self._control_down.add(code)
                self._reset('control_hotkey', source)
                self.control(CONTROL_KEYS[code])
                return
            if not active or code in RESERVED_MODIFIERS:
                return
            if event_type == q.kCGEventFlagsChanged:
                if code not in MODIFIER_KEYS:
                    return
                down = bool(q.CGEventSourceKeyState(q.kCGEventSourceStateCombinedSessionState, code))
            else:
                if code not in GAME_KEYS or (event_type == q.kCGEventKeyDown
                                            and get(q.kCGKeyboardEventAutorepeat)):
                    return
                down = event_type == q.kCGEventKeyDown
                if down and flags & (chord | q.kCGEventFlagMaskCommand):
                    return
            self._transition('key', code, down, source)
        elif active:
            if event_type in (q.kCGEventMouseMoved, q.kCGEventLeftMouseDragged,
                              q.kCGEventRightMouseDragged, q.kCGEventOtherMouseDragged):
                self._write('mouse_move', source=source,
                            dx=get(q.kCGMouseEventDeltaX), dy=get(q.kCGMouseEventDeltaY))
            elif event_type == q.kCGEventScrollWheel:
                self._write('scroll', source=source, dx=get(q.kCGScrollWheelEventDeltaAxis2),
                            dy=get(q.kCGScrollWheelEventDeltaAxis1))
            else:
                button = BUTTONS.get(get(q.kCGMouseEventButtonNumber))
                if button is not None:
                    down = event_type in (q.kCGEventLeftMouseDown, q.kCGEventRightMouseDown,
                                          q.kCGEventOtherMouseDown)
                    self._transition('button', button, down, source)

    def _callback(self, proxy, event_type, event, refcon):
        try:
            with self._lock:
                self._handle(event_type, event)
        except Exception as exc:
            self._error = exc
            self._stop.set()
        return event  # A listen-only observer never suppresses or replaces input.

    def start(self):
        """Start passive monitoring, or raise without prompting for permission."""
        if self._thread is not None:
            raise RuntimeError('MacInputObserver instances can only be started once')
        if self.q is None:
            import Quartz
            self.q = Quartz
        preflight = getattr(self.q, 'CGPreflightListenEventAccess', None)
        if preflight is None or not preflight():
            raise PermissionError('Input Monitoring permission is required for this Python '
                                  'or launcher in macOS System Settings > Privacy & Security; '
                                  'no permission request was opened.')
        self._thread = threading.Thread(target=self._run, name='game-input-observer', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self.close()
            raise RuntimeError('Timed out starting the macOS input observer')
        self.check_health()
        return self

    def _run(self):
        q, source = self.q, None
        try:
            if self._frontmost_pid is None:
                self._frontmost_pid = _foreground_pid_reader()
            event_names = ('KeyDown', 'KeyUp', 'FlagsChanged', 'MouseMoved', 'ScrollWheel',
                           'LeftMouseDown', 'LeftMouseUp', 'RightMouseDown', 'RightMouseUp',
                           'OtherMouseDown', 'OtherMouseUp', 'LeftMouseDragged',
                           'RightMouseDragged', 'OtherMouseDragged')
            mask = sum(1 << getattr(q, 'kCGEvent' + name) for name in event_names)
            self._tap = q.CGEventTapCreate(q.kCGSessionEventTap, q.kCGTailAppendEventTap,
                                         q.kCGEventTapOptionListenOnly, mask, self._callback, None)
            if self._tap is None:
                raise PermissionError('Could not create a listen-only input tap; check Input Monitoring permission.')
            source = q.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = q.CFRunLoopGetCurrent()
            q.CFRunLoopAddSource(self._loop, source, q.kCFRunLoopDefaultMode)
            q.CGEventTapEnable(self._tap, True)
            self.check_focus()
            self._ready.set()
            while not self._stop.is_set():
                q.CFRunLoopRunInMode(q.kCFRunLoopDefaultMode, 0.05, False)
                self.check_focus()
        except Exception as exc:
            self._error = exc
        finally:
            self._ready.set()
            if source is not None:
                q.CFRunLoopRemoveSource(self._loop, source, q.kCFRunLoopDefaultMode)
            if self._tap is not None:
                q.CFMachPortInvalidate(self._tap)

    def check_health(self):
        """Raise RuntimeError for callback, setup, or unexpected thread failure."""
        if self._error is not None:
            raise RuntimeError(f'macOS input observer failed: {self._error}') from self._error
        if self._thread is None or (not self._thread.is_alive() and not self._stop.is_set()):
            raise RuntimeError('macOS input observer is not running')

    def close(self):
        """Stop observing and release the event tap; never send game input."""
        self._stop.set()
        if self._loop is not None:
            self.q.CFRunLoopStop(self._loop)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError('macOS input observer did not stop within two seconds')


def _foreground_pid_reader():
    """Read foreground PID synchronously, without NSWorkspace notification lag."""
    import ctypes

    serial_type = ctypes.c_uint32 * 2
    api = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    api.GetFrontProcess.argtypes = [ctypes.POINTER(serial_type)]
    api.GetFrontProcess.restype = ctypes.c_int16
    api.GetProcessPID.argtypes = [ctypes.POINTER(serial_type), ctypes.POINTER(ctypes.c_int32)]
    api.GetProcessPID.restype = ctypes.c_int32

    def read_pid():
        serial, pid = serial_type(), ctypes.c_int32()
        if api.GetFrontProcess(ctypes.byref(serial)) or api.GetProcessPID(ctypes.byref(serial), ctypes.byref(pid)):
            raise RuntimeError('macOS could not resolve the foreground process')
        return pid.value

    return read_pid
