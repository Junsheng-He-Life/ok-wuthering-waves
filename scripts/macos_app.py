"""Launch the local macOS GUI without Codex or a network service."""
import os
import signal
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
from src.runtime.MacSession import MacSession, prepare_desktop_config, release_inputs


def main():
    lease = MacSession(root).acquire()
    app = None
    try:
        from config import config
        from ok import OK
        app = OK(prepare_desktop_config(root, config))
        from PySide6.QtCore import QTimer
        # Give Python regular dispatch opportunities while Qt owns the loop,
        # including Ctrl-C from the independent Terminal launcher.
        signal_pump = QTimer()
        signal_pump.timeout.connect(lambda: None)
        signal_pump.start(250)
        from ok.gui.Communicate import communicate
        def paused(is_paused):
            if is_paused:
                release_inputs(app)
                task = getattr(app.task_executor, 'current_task', None)
                if task:
                    task.held_attack_interrupted = True
        communicate.executor_paused.connect(paused)
        def stop(*_):
            app.exit_event.set()
            release_inputs(app)
            app.quit()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        app.start()
    finally:
        if app:
            app.exit_event.set()
            release_inputs(app)
            app.quit()
            capture = getattr(getattr(app, 'device_manager', None), 'capture_method', None)
            if capture:
                capture.close()
        lease.close()


if __name__ == '__main__':
    main()
