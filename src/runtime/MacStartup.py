"""Settle the game's foreground Space before creating a capture stream."""
import sys
import threading
import time


def stabilize_window(window, *, clock=time.monotonic, sleep=time.sleep):
    if not window.bring_to_front():
        raise RuntimeError('无法将游戏置于前台；尚未启动采集或输入。')
    deadline = clock() + 10
    previous, stable_since = None, clock()
    while clock() < deadline:
        window.do_update_window_size()
        signature = window.capture_target_signature
        if signature != previous or not window.is_foreground():
            if signature != previous:
                print('GAME_WINDOW_SETTLING', signature, window.is_foreground(), flush=True)
            previous, stable_since = signature, clock()
        elif clock() - stable_since >= 2:
            return signature
        sleep(.25)
    raise RuntimeError(f'游戏窗口尚未稳定；尚未启动采集或输入。窗口={previous}，前台={window.is_foreground()}')


def prepare_game_window(config):
    if sys.platform != 'darwin':
        return
    from ok.platform.macos.window import MacWindow
    from Foundation import NSDate, NSRunLoop
    def settle_events(delay):
        # NSWorkspace's frontmost/Space notifications need a main run loop even
        # before the headless controller creates its QApplication.
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(delay))
    options = config.get('macos', {})
    window = MacWindow(threading.Event(), bundle_id=options.get('bundle_id'),
                       title=options.get('title'), owner_name=options.get('owner_name'))
    try:
        signature = stabilize_window(window, sleep=settle_events)
        print('GAME_WINDOW_READY', signature, flush=True)
    finally:
        window.stop()
