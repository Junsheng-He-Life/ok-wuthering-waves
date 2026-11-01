"""Exercise disk-following and scrollback without capture or game input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from src.ui.LiveRunLog import LiveRunLog, LogTail


class TestLiveRunLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_incremental_unicode_truncation_and_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'run.log'; tail=LogTail()
            data='技能确认\n'.encode()
            path.write_bytes(data[:2])
            self.assertEqual((True,''),tail.read(path))
            with path.open('ab') as stream: stream.write(data[2:])
            self.assertEqual((False,'技能确认\n'),tail.read(path))
            self.assertEqual((False,''),tail.read(path))
            path.write_text('新\n')
            self.assertEqual((True,'新\n'),tail.read(path))
            replacement=path.with_suffix('.new'); replacement.write_text('另一场\n')
            replacement.replace(path)
            self.assertEqual((True,'另一场\n'),tail.read(path))

    def test_initial_large_log_reads_bounded_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'run.log'
            path.write_text('旧行\n'*20000+'最后一行\n')
            tail=LogTail(); reset,text=tail.read(path,limit=1024)
            self.assertTrue(reset); self.assertLessEqual(len(text.encode()),1024)
            self.assertTrue(text.endswith('最后一行\n'))
            self.assertNotIn('\ufffd',text)

    def test_scroll_up_stays_put_and_latest_resumes_following(self):
        widget=LiveRunLog('.',poll=False)
        try:
            widget.resize(600,240); widget.show(); self.app.processEvents()
            widget.append(''.join(f'技能 {i}\n' for i in range(100)))
            self.app.processEvents()
            bar=widget.text.verticalScrollBar()
            self.assertEqual(bar.maximum(),bar.value())
            bar.setValue(15); widget.append('追加\n')
            self.assertEqual(15,bar.value())
            widget.latest.click(); widget.append('又一条\n')
            self.assertEqual(bar.maximum(),bar.value())
            widget.append('行\n'*6000)
            self.assertLessEqual(widget.text.document().blockCount(),5000)
        finally: widget.close()

    def test_follow_new_file_and_append_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); logs=root/'logs/desktop-runs'; logs.mkdir(parents=True)
            widget=LiveRunLog(root,poll=False)
            try:
                first=logs/'1.log'; first.write_text('开始\n'); widget.refresh(); widget.refresh()
                self.assertEqual(1,widget.text.toPlainText().count('开始'))
                second=logs/'2.log'; second.write_text('下一场\n')
                os.utime(second,ns=(first.stat().st_mtime_ns+1000,first.stat().st_mtime_ns+1000))
                widget.refresh()
                self.assertEqual(second,widget.source)
                with second.open('a') as stream: stream.write('实时追加\n')
                widget.refresh()
                self.assertIn('实时追加',widget.text.toPlainText())
            finally: widget.close()
