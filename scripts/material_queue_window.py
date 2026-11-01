"""Read-only native material dashboard. Never sends input to the game."""
import argparse
import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QAction
from PySide6.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QFrame, QSystemTrayIcon, QMenu, QStyle, QSplitter)
from src.ui.LiveRunLog import LiveRunLog


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def icon_path(name):
    return ROOT / 'configs/macos-desktop/material-icons' / (hashlib.sha256(name.encode()).hexdigest()[:16] + '.png')


def snapshot_data():
    from src.task.MaterialQueueSnapshot import build_queue_snapshot
    audit = read_json('logs/material-audit-latest.json', {})
    progress = read_json('configs/macos-desktop/team-material-needs-progress.json', {})
    return (build_queue_snapshot(progress, audit),
            read_json('configs/macos-desktop/team-material-activity.json', {}))


class QueueWindow(QWidget):
    def __init__(self, floating=True, log_path=None):
        super().__init__()
        self.floating = floating
        self.setWindowTitle('OK-WW · 材料刷取队列')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setWindowFlags((Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
                            if floating else Qt.Window)
        self.setStyleSheet('''QWidget { background:#101923; color:#e8eef5; font-size:12px; }
            QLabel { background:transparent; } QFrame#card { background:#1b2937; border-radius:9px; }
            QScrollArea { border:0; } QScrollBar:vertical { width:7px; background:#17222d; }
            QScrollBar::handle:vertical { background:#526575; min-height:25px; }
        ''')
        self.resize(700, 720)
        self.setMinimumSize(380, 260)
        self.layout = QVBoxLayout(self)
        title = QLabel('剩余材料缺口')
        title.setStyleSheet('font-size:22px;font-weight:700;color:#81dfc5')
        self.layout.addWidget(title)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)
        note = QLabel('按材料图标与名称合并需求 · 共用库存只计一次 · 扫描中未读取的角色显示待核对')
        note.setWordWrap(True)
        note.setStyleSheet('color:#9aabba;font-size:11px')
        self.layout.addWidget(note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.scroll)
        self.run_log = LiveRunLog(ROOT, path=log_path)
        splitter.addWidget(self.run_log)
        splitter.setSizes([390, 210])
        self.layout.addWidget(splitter, 1)
        self.signature = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
        menu = QMenu()
        for title, callback in [('交互窗口（可滚动、移动）', self.interactive),
                                ('悬浮显示（鼠标穿透）', self.overlay),
                                ('退出进度窗口', QApplication.instance().quit)]:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('OK-WW 材料队列：右键切换交互/悬浮')
        self.tray.show()

    def interactive(self):
        self.floating = False
        self.setWindowFlags(Qt.Window)
        self.show()
        self.raise_()
        self.activateWindow()
        self.native_mouse_mode(False)

    def overlay(self):
        self.floating = True
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.show()
        self.native_mouse_mode(True)

    def native_mouse_mode(self, ignore):
        if sys.platform == 'darwin':
            from AppKit import NSApplication, NSWindowStyleMaskNonactivatingPanel
            for native in NSApplication.sharedApplication().windows():
                if str(native.title()) == self.windowTitle():
                    native.setIgnoresMouseEvents_(ignore)
                    if ignore:
                        native.setStyleMask_(native.styleMask() | NSWindowStyleMaskNonactivatingPanel)
                        native.setHidesOnDeactivate_(False)
                        native.setCollectionBehavior_(1 | 256)
                        native.setLevel_(25)
                        native.orderFrontRegardless()

    def refresh(self):
        named = read_json(ROOT / 'logs/material-status/named-live.json', {})
        if named.get('schema') == 1:
            self.render_named(named)
            return
        snapshot, activity = snapshot_data()
        roles = snapshot['roles']
        stamp = activity.get('updated_at', '尚未记录')
        current = activity.get('current_job', {})
        total = activity.get('claim_units', 0)
        current_label = f'{current.get("target", "等待扫描")} · {current.get("kind", "")}' if isinstance(current, dict) else str(current)
        self.status.setText(f'库存快照：{snapshot["observed_at"]}\n任务记录：{current_label}\n累计领取 {total} 份奖励 · 已用溶剂 {activity.get("solvents_used", 0)}\n领取记录更新：{stamp}\n经验 / 武器经验 / 贝币：{snapshot["resource_status"]}')
        signature = json.dumps(roles, ensure_ascii=False)
        if signature == self.signature:
            return
        self.signature = signature
        body = QWidget()
        layout = QVBoxLayout(body)
        columns = QHBoxLayout()
        layout.addLayout(columns)
        if not roles:
            layout.addWidget(QLabel('暂无培养目标库存快照，请先扫描当前队伍。'))
        for name, rows in roles.items():
            column = QVBoxLayout()
            columns.addLayout(column, 1)
            heading = QHBoxLayout()
            portrait = QLabel()
            path = ROOT / 'configs/macos-desktop/cultivation-avatars' / (hashlib.sha256(name.encode()).hexdigest()[:16]+'.png')
            if path.is_file():
                portrait.setPixmap(QPixmap(str(path)).scaled(40,40,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                heading.addWidget(portrait)
            label = QLabel(name)
            label.setToolTip(f'剩余 {len(rows)} 种材料')
            label.setStyleSheet('font-size:17px;font-weight:600')
            heading.addWidget(label,1)
            column.addLayout(heading)
            if not rows:
                column.addWidget(QLabel('本次已识别材料无缺口'))
            grid = QGridLayout()
            for index, row in enumerate(rows):
                stock = row['stock']
                owned = stock['inventory']
                need = row['required']
                missing = stock['missing']
                card = QFrame()
                card.setObjectName('card')
                line = QHBoxLayout(card)
                line.setContentsMargins(7,5,7,5)
                icon = QLabel()
                icon.setFixedSize(44,44)
                if icon_path(row['item_name']).is_file():
                    icon.setPixmap(QPixmap(str(icon_path(row['item_name']))).scaled(44,44,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                    line.addWidget(icon)
                text = QVBoxLayout()
                text.setSpacing(3)
                title = QLabel(row['item_name'])
                title.setWordWrap(True)
                text.addWidget(title)
                count = QLabel(f'库存 {owned if owned is not None else "待核对"} / 需求 {need if need is not None else "待核对"}')
                count.setStyleSheet('color:#aabccb;font-size:11px')
                result = QLabel('数量待核对' if missing is None else f'原始缺口 {missing}')
                result.setWordWrap(True)
                result.setStyleSheet('font-size:11px;color:' + ('#ffb787' if missing else '#81dfc5'))
                card.setToolTip(f'{row["item_name"]}\n{count.text()}\n{result.text()}\n{row["note"]}')
                badge = QLabel('?' if stock.get('needs_verification') else str(missing))
                badge.setStyleSheet('font-size:18px;font-weight:600;color:#ffb787')
                text.addWidget(badge)
                text.addWidget(count)
                line.addLayout(text,1)
                grid.addWidget(card,index,0)
            column.addLayout(grid)
            column.addStretch()
        footer = QLabel('周本按本周实际次数；跑图采集按设定跳过。')
        footer.setWordWrap(True)
        footer.setStyleSheet('color:#9aabba;font-size:11px')
        layout.addWidget(footer)
        self.scroll.setWidget(body)

    def render_named(self, data):
        materials = [r for r in data.get('materials', []) if r.get('raw_missing') is None or r['raw_missing'] > 0]
        unknown = data.get('unknown', [])
        state = ('已停止：' + data.get('error', '') if data.get('status') == 'stopped' else
                 '正在刷新库存' if data.get('status') == 'refreshing' else
                 '扫描已完成' if data.get('scan_complete') else '正在扫描，尚未读取的材料不推断完成')
        if data.get('refresh_mode') == 'targeted':
            state += f" · 本次刷新{len(data.get('refreshed_targets', []))}人，共享材料同步；其余保留上次读数"
        self.status.setText(f"{state}\n"
                            f"目标队伍：{','.join(map(str, data.get('target_teams', [])))} · 战斗队伍：{data.get('selected_combat_team') or '待核验'}\n"
                            f"快照更新：{data.get('observed_at', '待扫描')} · 尚缺 {len(materials)} 种")
        signature = json.dumps((materials, unknown), ensure_ascii=False)
        if signature == self.signature:
            return
        self.signature = signature
        body = QWidget()
        layout = QVBoxLayout(body)
        for item in materials:
            card = QFrame()
            card.setToolTip(f"库存核对时间：{item.get('inventory_observed_at') or '待核对'}")
            card.setObjectName('card')
            row = QHBoxLayout(card)
            icon = QLabel()
            icon.setFixedSize(64, 64)
            path = icon_path(item['item_name'])
            if path.is_file():
                icon.setPixmap(QPixmap(str(path)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                icon.setText('待识别')
            row.addWidget(icon)
            text = QVBoxLayout()
            title = QLabel(item['item_name'])
            title.setStyleSheet('font-size:17px;font-weight:600;color:#81dfc5')
            text.addWidget(title)
            missing = item.get('raw_missing')
            text.addWidget(QLabel(f"缺 {missing if missing is not None else '待核对'} · 库存 {item.get('inventory') if item.get('inventory') is not None else '待核对'} / 总需求 {item['required_total']}"))
            targets = QLabel(' · '.join(f'{name} {need}' for name, need in item.get('by_target', {}).items()))
            targets.setWordWrap(True)
            text.addWidget(targets)
            if item.get('notes'):
                notes = QLabel('；'.join(item['notes']))
                notes.setWordWrap(True)
                notes.setStyleSheet('color:#ffb787;font-size:11px')
                text.addWidget(notes)
            row.addLayout(text, 1)
            layout.addWidget(card)
        for item in unknown:
            label = QLabel(f"{item.get('target', '')}：{item.get('reason', '图标与名称待核对')}")
            label.setWordWrap(True)
            layout.addWidget(label)
        if not materials and not unknown:
            layout.addWidget(QLabel('本次已核验的材料无缺口'))
        layout.addStretch()
        self.scroll.setWidget(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot')
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--log', type=Path, help='Follow this run log instead of the most recently updated run')
    args = parser.parse_args()
    lock = None
    if not args.snapshot:
        lock = (ROOT / 'logs/material-dashboard.lock').open('a+')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
    app = QApplication(sys.argv[:1])
    if sys.platform == 'darwin' and not args.snapshot and not args.interactive:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    window = QueueWindow(not args.interactive, args.log)
    screen = app.primaryScreen().availableGeometry()
    window.move(screen.right()-window.width()-15, screen.top()+35)
    window.show()
    if sys.platform == 'darwin' and not args.snapshot:
        # Apply after Qt has finished configuring its native panel.
        QTimer.singleShot(750, lambda: window.native_mouse_mode(not args.interactive))
    if args.snapshot:
        app.processEvents()
        window.grab().save(args.snapshot)
        return
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
