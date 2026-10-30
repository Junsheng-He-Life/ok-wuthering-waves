"""Keep game control in one existing runner process, outside the Qt UI thread."""
import json
import codecs
import os
from pathlib import Path
import signal
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


class DesktopProcess(QObject):
    changed = Signal(dict)
    completed = Signal(dict)
    line = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.started.connect(self._started)
        self.process.errorOccurred.connect(self._error)
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.result = None
        self.log = None
        self.action = ''
        self.paused = False
        self.stopping = False
        self._delivered = False
        self.control_ready = False

    @property
    def running(self):
        return self.process.state() != QProcess.NotRunning

    def start(self, arguments, action, runner='ultrawide_trial.py'):
        if self.running:
            raise RuntimeError('已有任务运行，请先暂停或结束。')
        if runner not in ('ultrawide_trial.py', 'desktop_diagnose.py'):
            raise ValueError('未知任务入口')
        self.action, self.buffer, self.result = action, '', None
        self.decoder.reset()
        self.paused = self.stopping = self._delivered = False
        self.control_ready = False
        folder = self.root / 'logs' / 'desktop-runs'
        folder.mkdir(parents=True, exist_ok=True)
        self.log_path = folder / f'{time.time_ns()}.log'
        self.log = self.log_path.open('w', encoding='utf-8')
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONPATH', os.pathsep.join((str(self.root.parent / 'ok-script'), str(self.root))))
        env.insert('PYTHONUNBUFFERED', '1')
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(self.root))
        self.changed.emit({'stage': '正在连接游戏', 'detail': '启动后会切换到游戏窗口。', 'paused': False})
        self.process.start(sys.executable, ['-u', str(self.root / 'scripts' / runner), *arguments])

    def pause_or_resume(self):
        if not self.running or self.stopping or not self.control_ready:
            return
        sig = signal.SIGUSR2 if self.paused else signal.SIGUSR1
        self._send_signal(sig)

    def stop(self):
        if self.running and not self.stopping:
            self.stopping = True
            self.changed.emit({'stage': '正在安全停止', 'detail': '释放按键并保存消费记录，请稍候。'})
            self._send_signal(signal.SIGINT)

    def _send_signal(self, sig):
        pid = int(self.process.processId())
        if pid <= 0:
            return False
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return False
        return True

    def _started(self):
        # QProcess reports PID 0 while Starting; never signal that process group.
        if self.stopping:
            self._send_signal(signal.SIGINT)

    def _read(self):
        text = self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        if self.log:
            self.log.write(text)
            self.log.flush()
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            self._parse(line)

    def _parse(self, line):
        self.line.emit(line)
        for prefix in ('DESKTOP_PROGRESS ', 'DESKTOP_CONTROL ', 'TRIAL_RESULT '):
            if not line.startswith(prefix):
                continue
            try:
                value = json.loads(line[len(prefix):])
            except ValueError:
                return
            if prefix == 'TRIAL_RESULT ':
                self.result = value
            else:
                if 'control_ready' in value:
                    self.control_ready = bool(value['control_ready'])
                if 'paused' in value:
                    self.paused = bool(value['paused'])
                self.changed.emit(value)
            return

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self.result = {'status': 'not_started', 'error': '任务进程无法启动，请运行环境诊断。'}
            self._finished(-1, QProcess.CrashExit)

    def _finished(self, code, _status):
        if self._delivered:
            return
        self._read()
        if self.buffer:
            self._parse(self.buffer)
            self.buffer = ''
        self._delivered = True
        if self.log:
            self.log.close()
            self.log = None
        result = dict(self.result or {'status': 'interrupted' if self.stopping else 'stopped',
                                     'error': '已请求结束任务；请核对消费记录。' if self.stopping else
                                              '未收到完整任务结果，请查看异常与诊断。'})
        result.update(desktop_action=self.action, process_exit=code,
                      desktop_log=str(self.log_path.relative_to(self.root)))
        if code != 0 and result.get('status') == 'completed':
            result.update(status='stopped', error='任务报告已完成，但进程退出异常，请核对记录。')
        path = self.log_path.with_suffix('.json')
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.completed.emit(result)
