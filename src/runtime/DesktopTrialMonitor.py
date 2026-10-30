"""Read task progress and relay pause/stop without a second capture session."""
from dataclasses import asdict, is_dataclass
import json
import signal
import threading
import time


def snapshot(task, executor):
    result = getattr(task, 'result', None) or {}
    info = dict(getattr(task, 'info', {}) or {})
    budget = getattr(task, '_run_budget', None) or getattr(task, 'shared_budget', None)
    paused = bool(getattr(executor, 'paused', False) or getattr(task, 'paused', False))
    data = {'stage': result.get('current_stage') or info.get('流程阶段') or '正在检查游戏',
            'detail': info.get('阶段说明') or '', 'paused': paused,
            'control_ready': getattr(executor, 'current_task', None) is task}
    if is_dataclass(budget):
        data['budget'] = asdict(budget)
    if result.get('preflight'):
        data['preflight'] = result['preflight']
    return data


class DesktopTrialMonitor:
    def __init__(self, app, task, timeout, expired, release):
        self.app, self.task = app, task
        self.timeout, self.expired, self.release = timeout, expired, release
        self.done = threading.Event()
        self.active_seconds = 0.0
        self.previous_handlers = {}
        self.control_request = None

    def pause(self, *_):
        if self.app.exit_event.is_set() or getattr(self.app.task_executor, 'current_task', None) is not self.task:
            return
        try:
            if not getattr(self.task, 'paused', False):
                self.task.pause()
            self.app.task_executor.pause()
            self.task.held_attack_interrupted = True
            print('DESKTOP_CONTROL', json.dumps({'paused': True, 'control_ready': True}), flush=True)
        except Exception:
            # A task may finish between the identity check and pause(task).
            # Never let a UI pause request turn successful completion into failure.
            print('DESKTOP_CONTROL', json.dumps({'control_ready': False}), flush=True)
        finally:
            self.release(self.app)

    def resume(self, *_):
        if not self.app.exit_event.is_set() and getattr(self.app.task_executor, 'current_task', None) is self.task:
            try:
                self.task.unpause()
                print('DESKTOP_CONTROL', json.dumps({'paused': False, 'control_ready': True}), flush=True)
            except Exception:
                print('DESKTOP_CONTROL', json.dumps({'control_ready': False}), flush=True)

    def request_pause(self, *_):
        self.control_request = 'pause'

    def request_resume(self, *_):
        self.control_request = 'resume'

    def start(self):
        for sig, callback in ((signal.SIGUSR1, self.request_pause), (signal.SIGUSR2, self.request_resume)):
            self.previous_handlers[sig] = signal.signal(sig, callback)
        self.thread = threading.Thread(target=self._watch, name='DesktopProgress', daemon=True)
        self.thread.start()

    def _watch(self):
        previous = time.monotonic()
        last_published = previous - 1
        while not self.done.wait(.2):
            requested, self.control_request = self.control_request, None
            if requested:
                (self.pause if requested == 'pause' else self.resume)()
            now = time.monotonic()
            data = snapshot(self.task, self.app.task_executor)
            if not data['paused']:
                self.active_seconds += now - previous
            previous = now
            data['active_seconds'] = round(self.active_seconds)
            if now - last_published >= 1:
                print('DESKTOP_PROGRESS', json.dumps(data, ensure_ascii=False, default=str), flush=True)
                last_published = now
            if self.timeout and self.active_seconds >= self.timeout:
                self.expired.set()
                self.app.exit_event.set()
                self.release(self.app)
                return

    def close(self):
        self.done.set()
        if hasattr(self, 'thread'):
            self.thread.join(timeout=2)
        for sig, previous in self.previous_handlers.items():
            signal.signal(sig, previous)
