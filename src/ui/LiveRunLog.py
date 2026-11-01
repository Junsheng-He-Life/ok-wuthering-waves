"""Read-only, bounded log tail; never creates a game device or controller."""
import codecs
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit


class LogTail:
    def __init__(self):
        self.identity = None
        self.offset = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def read(self, path, limit=65536):
        """Read at most one chunk per tick, retaining split UTF-8 characters."""
        with Path(path).open('rb') as stream:
            import os
            stat = os.fstat(stream.fileno())
            identity = (str(path), stat.st_dev, stat.st_ino)
            reset = identity != self.identity or stat.st_size < self.offset
            if reset:
                self.identity = identity
                self.decoder.reset()
                self.offset = max(0, stat.st_size - limit)
                stream.seek(self.offset)
                if self.offset:
                    stream.readline()  # Do not start midway through a UTF-8 line.
                    self.offset = stream.tell()
            stream.seek(self.offset)
            chunk = stream.read(limit)
            self.offset = stream.tell()
        return reset, self.decoder.decode(chunk)


class LiveRunLog(QWidget):
    def __init__(self, root, parent=None, *, poll=True, path=None):
        super().__init__(parent)
        self.root, self.path = Path(root), Path(path) if path else None
        self.tail = LogTail()
        self.source = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        self.title = QLabel('运行日志 · 等待日志文件')
        self.title.setWordWrap(True)
        self.latest = QPushButton('回到最新')
        heading.addWidget(self.title, 1)
        heading.addWidget(self.latest)
        layout.addLayout(heading)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setMaximumBlockCount(5000)
        self.text.setMinimumHeight(130)
        self.text.setPlaceholderText('运行后持续更新；向上翻阅时保留位置。完整日志保存在文件中。')
        layout.addWidget(self.text)
        self.latest.clicked.connect(self.follow_latest)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        if poll:
            self.timer.start(500)
            self.refresh()

    def follow_latest(self):
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append(self, text):
        bar = self.text.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 1
        previous = bar.value()
        blocks = self.text.document().blockCount()
        inserted = text.count('\n')
        cursor = QTextCursor(self.text.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        removed = max(0, blocks + inserted - self.text.document().blockCount())
        bar.setValue(bar.maximum() if follow else max(0, previous - removed))

    def refresh(self):
        try:
            path = self.path
            if path is None:
                files = list((self.root / 'logs/desktop-runs').glob('*.log'))
                path = max(files, key=lambda p: p.stat().st_mtime_ns) if files else None
            if path is None:
                return
            reset, text = self.tail.read(path)
            if reset:
                self.append(f'\n──── 日志文件：{path.name} ────\n')
            self.append(text)
            self.source = path
            self.title.setText(f'运行日志 · {path.name}')
            self.title.setToolTip(f'{path}\n显示最近5000行；自动读取最新更新的运行日志，不代表任务正在运行。')
        except OSError as exc:
            self.title.setText(f'日志暂不可读：{exc.strerror or type(exc).__name__}')
