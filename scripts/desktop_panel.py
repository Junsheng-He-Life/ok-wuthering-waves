"""Launch the focused UI; preview mode never constructs a game controller."""
import argparse
import fcntl
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', type=Path, help='Render an offline UI screenshot and exit')
    parser.add_argument('--page', choices=('run', 'history', 'recovery', 'settings'), default='run')
    parser.add_argument('--preview-size', nargs=2, type=int, metavar=('WIDTH', 'HEIGHT'),
                        help='Offline preview size in logical pixels')
    args = parser.parse_args(argv)
    if args.preview_size and (not args.preview or args.preview_size[0] < 920 or args.preview_size[1] < 600):
        parser.error('--preview-size requires --preview and a size of at least 920 600')
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
    from src.ui.DesktopWindow import DesktopWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName('OK-WW 鸣潮助手')
    app.setFont(QFont('PingFang SC', 13))
    lock = None
    if not args.preview:
        path = ROOT / 'logs/desktop-ui.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.open('a+')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            QMessageBox.information(None, '面板已经打开', '请使用已有的 OK-WW 窗口。')
            lock.close()
            return 1
    try:
        window = DesktopWindow(ROOT, preview=bool(args.preview))
        if args.preview_size:
            window.resize(*args.preview_size)
        window.show_page(('run', 'history', 'recovery', 'settings').index(args.page))
        window.show()
        if args.preview:
            def render():
                args.preview.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.preview)):
                    app.exit(1)
                else:
                    app.quit()
            QTimer.singleShot(150, render)
        return app.exec()
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
