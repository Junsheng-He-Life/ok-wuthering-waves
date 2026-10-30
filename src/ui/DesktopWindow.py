"""A task-oriented desktop shell over the established game workflow."""
from datetime import datetime
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame,
    QHBoxLayout, QListWidgetItem, QMainWindow, QMessageBox, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget)

from src.runtime.DesktopJobs import DesktopRequest, action_arguments, read_json, result_summary
from src.ui.DesktopPages import HistoryPage, RecoveryPage, RunPage, SettingsPage
from src.ui.DesktopProcess import DesktopProcess
from src.ui.DesktopHotkey import DesktopHotkey
from src.ui.DesktopStyle import STYLE, button, label


class DesktopWindow(QMainWindow):
    def __init__(self, root, preview=False):
        super().__init__()
        self.root, self.preview = Path(root), preview
        self.state = {}
        self.observation = None
        self.close_when_stopped = False
        self._screen = None
        self._screen_connected = False
        self._compact = None
        self._screen_fit_timer = QTimer(self)
        self._screen_fit_timer.setSingleShot(True)
        self._screen_fit_timer.timeout.connect(self._fit_current_screen)
        self.setWindowTitle('OK-WW · 鸣潮助手')
        self.resize(1220, 900)
        self.setMinimumSize(920, 600)
        self.setStyleSheet(STYLE)
        outer = QWidget()
        outer.setObjectName('appRoot')
        self.setCentralWidget(outer)
        base = QHBoxLayout(outer)
        base.setContentsMargins(0, 0, 0, 0)
        base.setSpacing(0)
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(200)
        nav = QVBoxLayout(sidebar)
        self.nav_layout = nav
        nav.setContentsMargins(20, 34, 20, 24)
        nav.setSpacing(7)
        nav.addWidget(label('OK-WW', 'brand'))
        nav.addWidget(label('鸣潮 · macOS 内测版'))
        release = read_json(self.root.parent / 'release-manifest.json', {})
        nav.addWidget(label(release.get('version', '开发工作区')))
        nav.addSpacing(36)
        self.navigation = QButtonGroup(self)
        self.nav_buttons = []
        for index, text in enumerate(('开始刷取', '运行记录', '异常与恢复', '首次设置')):
            control = button(text)
            control.setCheckable(True)
            self.navigation.addButton(control, index)
            self.nav_buttons.append(control)
            nav.addWidget(control)
        nav.addStretch(1)
        nav.addWidget(label('每一轮，都有明确边界。', wrap=True))
        nav.addSpacing(8)
        nav.addWidget(label('前台运行 · 随时可暂停', wrap=True))
        base.addWidget(sidebar)
        workspace = QVBoxLayout()
        self.workspace_layout = workspace
        workspace.setContentsMargins(30, 26, 30, 24)
        workspace.setSpacing(20)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = label('开始刷取', 'title')
        self.page_subtitle = label('选好目标和额度，确认队伍后开始。', 'subtitle', True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        self.status_chip = label('尚未启动', 'statusChip')
        header.addWidget(self.status_chip, 0, Qt.AlignTop)
        workspace.addLayout(header)
        self.stack = QStackedWidget()
        self.run_page = RunPage()
        self.history_page = HistoryPage()
        self.recovery_page = RecoveryPage()
        self.settings_page = SettingsPage()
        for page in (self.run_page, self.history_page, self.recovery_page, self.settings_page):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        workspace.addWidget(self.stack, 1)
        workspace.addWidget(self.run_page.progress_card)
        base.addLayout(workspace, 1)
        self.navigation.idClicked.connect(self.show_page)
        self.nav_buttons[0].setChecked(True)
        self.controller = DesktopProcess(self.root, self)
        self.hotkey = DesktopHotkey(self)
        self.hotkey.toggled.connect(self.controller.pause_or_resume)
        self.controller.changed.connect(self.on_progress)
        self.controller.completed.connect(self.on_completed)
        self._connect_actions()
        self.load_preferences()
        self.update_budget()
        if preview:
            self.populate_preview()
        else:
            self.refresh_local_state()
            self.fit_to_screen(QApplication.primaryScreen(), initial=True)
        self.update_responsive_layout()

    def update_responsive_layout(self):
        compact = self.width() < 1120
        if compact == self._compact:
            return
        self._compact = compact
        self.sidebar.setFixedWidth(176 if compact else 200)
        self.nav_layout.setContentsMargins(14 if compact else 20, 26, 14 if compact else 20, 20)
        margin = 20 if compact else 30
        self.workspace_layout.setContentsMargins(margin, 20 if compact else 26, margin, 20 if compact else 24)
        self.workspace_layout.setSpacing(14 if compact else 20)
        self.run_page.set_compact(compact)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'run_page'):
            self.update_responsive_layout()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.preview and not self._screen_connected:
            handle = self.windowHandle()
            if handle:
                handle.screenChanged.connect(self._screen_changed)
                self._screen_connected = True
                self._screen_changed(handle.screen())

    def _screen_changed(self, screen):
        if self._screen is not None:
            try:
                self._screen.availableGeometryChanged.disconnect(self._available_geometry_changed)
            except (RuntimeError, TypeError):
                # A disconnected monitor's QScreen may already have been destroyed by Qt.
                pass
        self._screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self._available_geometry_changed)
            self._screen_fit_timer.start(0)

    def _fit_current_screen(self):
        self.fit_to_screen(self._screen)

    def _available_geometry_changed(self, _geometry):
        self.fit_to_screen(self._screen)

    def fit_to_screen(self, screen, initial=False):
        if screen is None or self.isMaximized() or self.isFullScreen():
            # The window manager fits these states; resize/move would restore a normal window.
            return
        try:
            area = screen.availableGeometry()
        except RuntimeError:
            return  # Wait for Qt to provide the replacement screen after disconnection.
        # Qt uses logical pixels here, including when the monitor has Retina scaling.
        # Reserve room for the title bar and a small desktop margin.
        width = min(1220 if initial else self.width(), max(self.minimumWidth(), area.width() - 32))
        height = min(900 if initial else self.height(), max(self.minimumHeight(), area.height() - 48))
        self.resize(width, height)
        frame = self.frameGeometry()
        x = area.x() + (area.width() - frame.width()) // 2 if initial else frame.x()
        y = area.y() + (area.height() - frame.height()) // 2 if initial else frame.y()
        x = max(area.left(), min(x, area.right() - frame.width() + 1))
        y = max(area.top(), min(y, area.bottom() - frame.height() + 1))
        self.move(x, y)

    def _connect_actions(self):
        run, settings, recovery = self.run_page, self.settings_page, self.recovery_page
        run.kind_changed.connect(self.on_kind_changed)
        run.catalog.clicked.connect(lambda: self.run_action('catalog'))
        run.preflight.clicked.connect(lambda: self.run_action('preflight'))
        run.start.clicked.connect(self.start_farming)
        run.pause.clicked.connect(self.controller.pause_or_resume)
        run.stop.clicked.connect(self.controller.stop)
        run.notice_button.clicked.connect(self.open_attention)
        for control in (run.waveplates, run.claims, run.solvents, run.reserve):
            control.valueChanged.connect(self.update_budget)
        run.claim_rewards.toggled.connect(self.update_budget)
        run.refill.toggled.connect(self.update_budget)
        settings.initialize.clicked.connect(self.initialize_account)
        settings.diagnose.clicked.connect(lambda: self.run_diagnosis(False))
        settings.permissions.clicked.connect(lambda: self.run_diagnosis(True))
        recovery.observe.clicked.connect(lambda: self.run_action('observe'))
        recovery.recover.clicked.connect(lambda: self.run_action('recover'))
        recovery.reconcile.clicked.connect(self.reconcile_claim)
        recovery.export.clicked.connect(self.export_diagnostics)
        self.history_page.runs.currentItemChanged.connect(self.show_history_detail)

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        self.run_page.progress_card.setVisible(index == 0)
        self.nav_buttons[index].setChecked(True)
        titles = [('开始刷取', '选好目标和额度，确认队伍后开始。'),
                  ('运行记录', '查看每轮结果，以及已经核对的资源消耗。'),
                  ('异常与恢复', '了解停止原因，核对结果，再继续下一轮。'),
                  ('首次设置', '让这台电脑和当前账号做好准备。')]
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])

    def open_attention(self):
        self.show_page(2 if self.state.get('pending_count') else 3)

    def load_preferences(self):
        if self.preview:
            return
        prefs = read_json(self.root / 'configs/macos-desktop/desktop-panel.json', {})
        # Refills always start disabled; this panel never inherits another task's permission.
        kind = prefs.get('kind', 'tacet')
        if kind in self.run_page.kind_buttons:
            self.run_page.kind_buttons[kind].setChecked(True)
            self.on_kind_changed(kind)

    def save_preferences(self):
        if self.preview:
            return
        path = self.root / 'configs/macos-desktop/desktop-panel.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'kind': self.run_page.kind}, ensure_ascii=False) + '\n')

    def on_kind_changed(self, kind):
        run = self.run_page
        run.stage.clear()
        run.stage.addItem('跟随当前三人培养目标' if kind == 'materials' else '先读取游戏中的关卡列表', '')
        run.stage.setEnabled(kind != 'materials')
        run.catalog.setText('扫描材料需求' if kind == 'materials' else '读取关卡')
        run.claim_rewards.setChecked(True)
        run.claim_rewards.setEnabled(kind != 'materials')
        run.waveplates.setValue(80 if kind == 'materials' else 120)
        run.task_note.setText('扫描和开刷都会重新读取实际三人及培养需求。' if kind == 'materials'
                              else '关卡列表从当前账号读取。开始前会重新检查实际队伍。')
        self.save_preferences()

    def update_budget(self, *_):
        run = self.run_page
        claim = run.claim_rewards.isChecked()
        run.waveplates.setEnabled(claim)
        run.refill.setEnabled(claim)
        use = claim and run.refill.isChecked()
        run.refill_fields.setVisible(use)
        run.budget_note.setText('双倍领取计 2 份。达到任一额度即结束本轮。' if claim
                               else '只搜索和吸收地面声骸，不领取波片奖励；份数上限作为战斗场数上限。')
        run.allowance_summary.setText(
            f'本轮最多使用 {run.solvents.value()} 个溶剂、{run.reserve.value()} 储备波片。'
            if use else '本轮不使用溶剂或储备波片。')

    def refresh_local_state(self):
        from src.runtime.DesktopUserState import inspect_user_state
        from src.runtime.DesktopRecovery import inspect_recovery
        self.state = inspect_user_state(self.root)
        settings = self.settings_page
        settings.account_title.setText(self.state['title'])
        settings.account_detail.setText(self.state['message'])
        ledger = self.state.get('ledger') or {}
        settings.ledger.setText(f"已记录：{ledger.get('waveplates_spent', 0)} 波片 · {ledger.get('solvents_used', 0)} 个溶剂")
        initialize = self.state.get('can_initialize', False)
        settings.new_account.setVisible(initialize)
        settings.initialize.setVisible(initialize)
        recovery = inspect_recovery(self.root)
        self.recovery_model = recovery
        self.recovery_page.title.setText(recovery['title'])
        self.recovery_page.detail.setText(recovery['message'])
        descriptions = []
        for item in recovery.get('items', []):
            descriptions.append(f"{item.get('title', item.get('kind', '待核对'))}\n"
                                f"关卡：{item.get('stage') or '待确认'}\n"
                                f"操作前波片：{item.get('before') if item.get('before') is not None else '待确认'}　"
                                f"预期消耗：{item.get('expected_cost') if item.get('expected_cost') is not None else '待确认'}\n"
                                f"{item.get('next_action', '')}")
        echo_pending = any(item.get('kind') == 'echo_claim' for item in recovery.get('items', []))
        self.recovery_page.reconcile.setEnabled(bool(self.observation and echo_pending))
        if recovery.get('items') and not echo_pending:
            descriptions.append('此类材料或补给记录暂不支持界面自动核对。请保留现场并导出诊断，由维护者核对；不要删除记录。')
        self.recovery_page.items.setPlainText('\n\n'.join(descriptions) or '当前没有待核对事项。')
        needs_attention = not self.state.get('can_run', False) or bool(self.state.get('pending_count'))
        self.run_page.notice.setVisible(needs_attention)
        self.run_page.notice_text.setText(self.state['message'])
        self.run_page.notice_button.setText('查看待核对事项' if self.state.get('pending_count') else '前往设置')
        self.run_page.start.setEnabled(self.state.get('can_run', False) and not self.controller.running)
        self.refresh_history()

    def _guard_action(self, action):
        if self.preview:
            self.show_message('界面预览', '预览模式不会连接游戏、保存配置或执行任务。')
            return False
        if self.controller.running:
            self.show_message('已有任务运行', '请先结束当前任务，再执行其他操作。')
            return False
        self.refresh_local_state()
        if action not in ('observe', 'diagnose') and not self.state.get('can_run', False):
            self.open_attention()
            return False
        return True

    def run_action(self, action):
        if not self._guard_action(action):
            return
        args = action_arguments(action, self.run_page.kind, self.run_page.stage.currentData() or '')
        if action == 'preflight' and self.run_page.experimental.isChecked():
            args += ['--desktop-experimental']
        self.begin(args, action)

    def start_farming(self):
        if not self._guard_action('farm'):
            return
        run = self.run_page
        use = run.refill.isChecked() and run.claim_rewards.isChecked()
        request = DesktopRequest(kind=run.kind, stage=run.stage.currentData() or '',
            claims=run.claims.value(), waveplates=run.waveplates.value(),
            solvents=run.solvents.value() if use else 0, reserve=run.reserve.value() if use else 0,
            claim_rewards=run.claim_rewards.isChecked(), experimental=run.experimental.isChecked())
        try:
            if request.solvents and not self.state.get('can_use_solvents'):
                raise ValueError('资源历史尚未核对，暂不能使用溶剂。请查看“首次设置”。')
            args = request.arguments((self.state.get('ledger') or {}).get('solvents_used', 0))
            self.begin(args, 'farm')
        except (ValueError, RuntimeError) as error:
            self.show_message('还不能开始', str(error))

    def begin(self, arguments, action, runner='ultrawide_trial.py'):
        try:
            self.observation = None
            self.recovery_page.reconcile.setEnabled(False)
            self.controller.start(arguments, action, runner=runner)
            self.set_running(True)
            self.show_page(0)
        except (OSError, RuntimeError) as error:
            self.show_message('无法启动', str(error))

    def set_running(self, active):
        run = self.run_page
        run.start.setVisible(not active)
        run.pause.setVisible(active)
        run.stop.setVisible(active)
        run.progress_bar.setRange(0, 0 if active else 1)
        for control in [run.catalog, run.preflight, run.stage, run.experimental,
                        *run.kind_buttons.values(), run.claim_rewards, run.waveplates,
                        run.claims, run.refill, run.solvents, run.reserve, self.settings_page.initialize,
                        self.settings_page.permissions, self.settings_page.diagnose,
                        self.recovery_page.observe, self.recovery_page.recover, self.recovery_page.export]:
            control.setEnabled(not active)
        run.pause.setEnabled(False)
        run.stop.setEnabled(active)
        if not active:
            run.pause.setText('暂停')
            run.progress_bar.setValue(0)
            run.stage.setEnabled(run.kind != 'materials')
            run.claim_rewards.setEnabled(run.kind != 'materials')
            self.update_budget()

    def on_progress(self, value):
        run = self.run_page
        run.pause.setEnabled(bool(value.get('control_ready', self.controller.control_ready)))
        if not self.preview and value.get('control_ready'):
            available = self.hotkey.enable()
            run.pause.setToolTip('F9 暂停 / 继续；如被系统占用，可尝试 Fn + F9。' if available else
                                 '全局快捷键尚未启用，请使用此按钮暂停。')
        paused = value.get('paused', self.controller.paused)
        self.status_chip.setText('已暂停' if paused else '任务运行中')
        run.pause.setText('继续' if paused else '暂停')
        if 'stage' in value:
            run.progress_title.setText(value['stage'] or '正在执行')
        if 'detail' in value:
            run.progress_detail.setText(value['detail'] or '请保持游戏位于前台。')
        if paused:
            run.progress_title.setText('已暂停')
            run.progress_detail.setText('按键已释放。点击继续后会返回游戏。')
        budget = value.get('budget')
        if budget:
            run.spend.setText(f"波片 {budget.get('spent', 0)}   ·   奖励 {budget.get('claimed', 0)} 份   ·   溶剂 {budget.get('solvents_used', 0)}")
        if value.get('preflight'):
            self.render_team(value['preflight'])

    def render_team(self, data):
        for index, (name, level) in enumerate(self.run_page.team_rows):
            members = data.get('members', [])
            member = members[index] if index < len(members) else {}
            name.setText(member.get('name') or member.get('character') or '未能识别')
            level.setText(f"Lv. {member['level']}" if member.get('level') is not None else '等级待确认')
        ready = data.get('can_start', False)
        world = data.get('world_level')
        self.run_page.team_status.setText(('检查通过' if ready else '需要检查') + (f' · 索拉 {world} 阶' if world else ''))
        notes = [*data.get('issues', []), *data.get('warnings', [])]
        self.run_page.team_note.setText('\n'.join(str(n) for n in notes) or '身份与等级已核对；武器、声骸和实战表现仍以当前账号为准。')

    def on_completed(self, result):
        self.hotkey.disable()
        self.set_running(False)
        summary = result_summary(result)
        self.status_chip.setText('本轮结束' if result.get('status') == 'completed' else '等待下一步')
        self.run_page.progress_title.setText(summary['title'])
        self.run_page.progress_detail.setText(summary['message'] or '结果已保存，可在“运行记录”查看。')
        self.run_page.spend.setText(f"波片 {summary['spent']}   ·   奖励 {summary['claimed']} 份   ·   溶剂 {summary['solvents']}")
        if result.get('preflight'):
            self.render_team(result['preflight'])
        if result.get('desktop_action') == 'catalog' and self.run_page.kind != 'materials':
            locations = result.get('locations') or []
            names = list(dict.fromkeys(row.get('name') or row.get('stage') or '' for row in locations))
            names = [name for name in names if name]
            if names:
                self.run_page.stage.clear()
                for name in names:
                    self.run_page.stage.addItem(name, name)
        if result.get('desktop_action') == 'observe' and result.get('status') == 'menu_observed':
            source = self.root / 'logs/menu-latest.json'
            archive = self.controller.log_path.with_suffix('.observation.json')
            if source.is_file():
                archive.write_bytes(source.read_bytes())
                self.observation = archive
                self.show_page(2)
        if result.get('desktop_action') == 'diagnose':
            self.settings_page.environment_text.setText(result.get('message') or result.get('error') or '检查已结束。')
            self.show_page(3)
        self.refresh_local_state()
        if self.close_when_stopped:
            self.close()

    def initialize_account(self):
        if self.preview or not self.settings_page.new_account.isChecked():
            return
        from src.runtime.DesktopUserState import initialize_new_install
        try:
            initialize_new_install(self.root, confirmed=True)
            self.refresh_local_state()
        except (ValueError, RuntimeError, OSError) as error:
            self.show_message('无法建立新记录', str(error))

    def run_diagnosis(self, permissions):
        if self._guard_action('diagnose'):
            self.begin(['--permissions'] if permissions else [], 'diagnose', runner='desktop_diagnose.py')

    def reconcile_claim(self):
        if not self.observation or self.controller.running or self.preview:
            return
        from src.runtime.DesktopRecovery import reconcile_echo_claim
        try:
            result = reconcile_echo_claim(self.root, [self.observation])
            self.show_message(result.get('title', '核对结果'), result.get('message', str(result)))
            self.refresh_local_state()
        except (ValueError, RuntimeError, OSError) as error:
            self.show_message('仍需核对', str(error))

    def export_diagnostics(self):
        if self.preview or self.controller.running:
            return
        destination, _ = QFileDialog.getSaveFileName(self, '保存诊断包', 'OK-WW-诊断.zip', 'ZIP (*.zip)')
        if not destination:
            return
        from src.runtime.DesktopRecovery import export_diagnostics
        try:
            export_diagnostics(self.root, destination)
            self.show_message('诊断包已保存', '可将此文件提供给维护者排查问题。')
        except (ValueError, RuntimeError, OSError) as error:
            self.show_message('无法导出', str(error))

    def refresh_history(self):
        history = self.history_page
        history.runs.clear()
        folder = self.root / 'logs/desktop-runs'
        for path in sorted(folder.glob('*.json'), reverse=True)[:50]:
            if path.name.endswith('.observation.json'):
                continue
            result = read_json(path, {})
            summary = result_summary(result)
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime('%m月%d日 %H:%M')
            item = QListWidgetItem(f"{when}   {result.get('stage') or summary['title']}\n"
                                  f"{summary['title']}    ·    {summary['spent']} 波片    ·    {summary['claimed']} 份奖励")
            item.setData(Qt.UserRole, result)
            history.runs.addItem(item)
        if not history.runs.count():
            history.runs.addItem('还没有运行记录。完成首次检查或刷取后，结果会显示在这里。')

    def show_history_detail(self, item, _previous):
        result = item.data(Qt.UserRole) if item else None
        if not result:
            self.history_page.details.clear()
            return
        summary = result_summary(result)
        text = f"{summary['title']}\n{summary['message']}\n\n实际消耗：{summary['spent']} 波片\n溶剂：{summary['solvents']} 个\n储备波片：{summary['reserve']}\n"
        if result.get('inventory_checks'):
            text += '\n声骸奖励与背包计数分别记录；未逐堆核对总件数。'
        self.history_page.details.setPlainText(text)

    def populate_preview(self):
        self.status_chip.setText('界面预览 · 不连接游戏')
        self.state = {'can_run': True, 'can_use_solvents': True}
        self.run_page.notice.hide()
        self.run_page.stage.clear()
        self.run_page.stage.addItem('玄幽东岳无音区', '玄幽东岳无音区')
        self.render_team({'members': [{'name': '秧秧·玄翎', 'level': 90}, {'name': '弗洛洛', 'level': 80}, {'name': '穗穗', 'level': 80}],
                          'world_level': 8, 'can_start': True, 'warnings': ['示例数据。实际运行时重新读取当前队伍。']})
        self.settings_page.account_title.setText('资源记录已建立')
        self.settings_page.account_detail.setText('示例状态。每次刷取都使用本轮明确设置的额度。')
        self.settings_page.environment_text.setText('示例：运行环境可用。权限状态以实际检查结果为准。')
        self.settings_page.new_account.hide()
        self.settings_page.initialize.hide()
        self.recovery_page.items.setPlainText('当前没有待核对事项。')
        for title in ('23:12   玄幽东岳无音区\n已完成    ·    120 波片    ·    2 份奖励',
                      '22:59   玄幽东岳无音区\n结果已核对    ·    120 波片    ·    2 份奖励'):
            self.history_page.runs.addItem(title)

    def show_message(self, title, message):
        QMessageBox.information(self, title, message)

    def closeEvent(self, event):
        if self.controller.running:
            self.close_when_stopped = True
            self.controller.stop()
            event.ignore()
        else:
            self.hotkey.disable()
            event.accept()
