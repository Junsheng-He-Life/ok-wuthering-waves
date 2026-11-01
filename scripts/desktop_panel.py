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
    parser.add_argument('--target-teams', default='')
    parser.add_argument('--combat-teams', default='')
    parser.add_argument('--material-waveplates', type=int, default=240)
    parser.add_argument('--material-claims', type=int, default=6)
    parser.add_argument('--material-experimental', action='store_true')
    parser.add_argument('--start-materials', action='store_true', help='Explicitly start the supplied saved-party material request')
    args = parser.parse_args(argv)
    if args.target_teams or args.combat_teams or args.start_materials:
        from src.runtime.DesktopJobs import DesktopRequest
        try:
            DesktopRequest(kind='materials', target_teams=args.target_teams, combat_teams=args.combat_teams,
                           waveplates=args.material_waveplates, claims=args.material_claims).validate()
            if not args.target_teams or not args.combat_teams:
                raise ValueError('必须同时提供目标队伍与战斗队伍')
            if args.start_materials and args.preview:
                raise ValueError('预览模式不能开始刷取')
        except ValueError as exc:
            parser.error(str(exc))
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
        if args.target_teams:
            run = window.run_page
            run.kind_buttons['materials'].setChecked(True)
            window.on_kind_changed('materials')
            run.cross_team.setChecked(True)
            run.target_teams.setText(args.target_teams)
            run.combat_teams.setText(args.combat_teams)
            run.waveplates.setValue(args.material_waveplates)
            run.claims.setValue(args.material_claims)
            run.experimental.setChecked(args.material_experimental)
        if args.preview_size:
            window.resize(*args.preview_size)
        window.show_page(('run', 'history', 'recovery', 'settings').index(args.page))
        window.show()
        if args.start_materials:
            def start_materials():
                window.open_material_display()
                QTimer.singleShot(2000, window.start_farming)
            QTimer.singleShot(250, start_materials)
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
