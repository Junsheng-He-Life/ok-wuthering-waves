"""Open the native GUI without connecting to the game until a user action."""
import argparse
import fcntl
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--page',choices=('run','history','settings'),default='run')
    args=parser.parse_args()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication,QMessageBox
    from src.ui.DesktopWindow import DesktopWindow
    app=QApplication(sys.argv[:1]);app.setApplicationName('OK-WW 鸣潮助手')
    lock=None
    try:
        if not args.preview:
            path=ROOT/'logs/desktop-ui.lock';path.parent.mkdir(parents=True,exist_ok=True)
            lock=path.open('a+')
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                QMessageBox.information(None,'窗口已打开','请使用已有的OK-WW窗口。');return 1
        window=DesktopWindow(ROOT,preview=bool(args.preview))
        window.tabs.setCurrentIndex(('run','history','settings').index(args.page));window.show()
        if args.preview:
            def render():
                args.preview.parent.mkdir(parents=True,exist_ok=True)
                app.exit(0 if window.grab().save(str(args.preview)) else 1)
            QTimer.singleShot(200,render)
        return app.exec()
    finally:
        if lock:lock.close()


if __name__=='__main__':raise SystemExit(main())
