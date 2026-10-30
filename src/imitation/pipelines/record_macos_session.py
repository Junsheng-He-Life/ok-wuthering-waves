"""Orchestrate bounded, foreground-only human demonstrations on macOS."""

from pathlib import Path
import queue
import sys
import time


def inspect_recording_access(root, window_id=None):
    """Read permissions and select only a Wuthering Waves window, without prompts.

    Returns JSON-compatible permissions/window metadata. Selection never
    activates, resizes, or sends input to an application. ``window_id`` narrows
    selection within the recognized game, not arbitrary desktop windows.
    """
    if sys.platform != 'darwin':
        raise RuntimeError('Live demonstration capture currently requires macOS')
    sys.path.insert(0, str(Path(root).parent / 'ok-script'))
    from ok.platform.macos.helper import MacOSHelper
    import Quartz
    helper = MacOSHelper()
    permissions = helper.permissions(prompt=False)
    permissions['inputMonitoring'] = bool(Quartz.CGPreflightListenEventAccess())
    candidates = [w for w in helper.list_windows(on_screen_only=False)
                  if (w.get('bundleIdentifier') == 'com.kurogame.wutheringwaves.global'
                      or w.get('ownerName') in ('Wuthering Waves', '鸣潮'))
                  and w.get('width', 0) > 100 and w.get('height', 0) > 100
                  and (window_id is None or w.get('windowID') == window_id)]
    candidates.sort(key=lambda w: (bool(w.get('onScreen')), w['width'] * w['height']), reverse=True)
    return {'permissions': permissions, 'window': candidates[0] if candidates else None}


def record_macos_session(writer, window, *, fps=15, max_seconds=600):
    """Record until stop/deadline; return a reason string, closing native resources.

    The caller owns SessionWriter finalization and the shared controller lock.
    Input callbacks only enqueue small records; image encoding runs in this
    consumer thread. Queue overflow fails the session instead of silently
    dropping action labels. No input injection is imported or constructed.
    """
    from src.imitation.data_io.capture_macos_frames import MacFrameSource
    from src.imitation.data_io.observe_macos_input import MacInputObserver
    from src.imitation.pipelines.record_segments import RecordingController
    inbox = queue.Queue(maxsize=20000)
    overflow = []

    def enqueue(item):
        try:
            inbox.put_nowait(item)
        except queue.Full:
            if not overflow:
                overflow.append(True)

    control = RecordingController(writer)
    observer = MacInputObserver(window['pid'],
                                lambda event: enqueue(('event', event)),
                                lambda action: enqueue(('control', (action, time.monotonic_ns()))))
    source = MacFrameSource(window['windowID'], fps=fps)

    def drain():
        while True:
            if overflow:
                raise RuntimeError('Input event queue overflow; labels would be incomplete')
            try:
                kind, value = inbox.get_nowait()
            except queue.Empty:
                if overflow:
                    raise RuntimeError('Input event queue overflow; labels would be incomplete')
                return
            if kind == 'event':
                control.event(value)
            else:
                control.command(*value)

    try:
        observer.start()
        source.start()
        deadline = time.monotonic() + max_seconds
        print('被动记录器已就绪；请切到鸣潮。Ctrl+Option+1 开始/暂停；+2 成功；+3 失败；+0 结束。', flush=True)
        while not control.stopped and time.monotonic() < deadline:
            observer.check_health()
            source.check_health()
            focused = observer.check_focus()
            drain()
            if control.pending and focused:
                control.maybe_start(observer.snapshot(), focused)
            sample = source.read(timeout=0.05)
            # A focus/control event received while read() waited must take
            # precedence over persisting that frame, even if it was captured earlier.
            focused = observer.check_focus()
            drain()
            if sample is not None and focused:
                control.frame(sample)
            elif sample is None:
                # Encoding a newly received observation may be slow on first
                # use. Only a read with no new frame is evidence of a stall;
                # the exporter independently rejects large saved-frame gaps.
                control.check_stall()
        reason = 'user_stop' if control.stopped else 'time_limit'
        control.finish('interrupted', reason=reason)
        return reason
    finally:
        try:
            observer.close()
        finally:
            source.close()
