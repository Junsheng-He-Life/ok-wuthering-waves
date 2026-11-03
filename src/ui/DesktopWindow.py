"""Native GUI; all game operations run in the existing controller subprocess."""
import json
from pathlib import Path
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget)

from src.runtime.DesktopJobs import DesktopRequest, TASKS, action_arguments
from src.runtime.DesktopUserState import inspect_user_state, initialize_new_install
from src.runtime.DesktopRecovery import export_diagnostics
from src.ui.DesktopProcess import DesktopProcess
from src.ui.DesktopStyle import STYLE

ISSUES = 'https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues/new?template=macos-test.yml'


class DesktopWindow(QMainWindow):
    def __init__(self, root, preview=False):
        super().__init__()
        self.root, self.preview = Path(root), preview
        self.closing = False
        self.setWindowTitle('OK-WW 鸣潮助手 · 0.1.0-beta.2')
        self.setStyleSheet(STYLE)
        self.resize(1060, 780)
        self.setMinimumSize(840, 600)
        self.controller = DesktopProcess(root, self)
        self.controller.changed.connect(self.progress)
        self.controller.completed.connect(self.completed)
        self.controller.line.connect(self.log_line)
        body = QWidget(); self.setCentralWidget(body)
        layout = QVBoxLayout(body); layout.setContentsMargins(24,18,24,18)
        title = QLabel('选择任务，然后交给控制器'); title.setObjectName('title')
        layout.addWidget(title)
        layout.addWidget(QLabel('使用游戏当前出战队伍 · 不读取角色等级 · 打开面板不会操作游戏'))
        self.tabs = QTabWidget(); layout.addWidget(self.tabs,1)
        self.run_page = QWidget(); self.history_page = QWidget(); self.settings_page = QWidget()
        for name, page in [('开始刷取',self.run_page),('记录与问题报告',self.history_page),('安装与使用',self.settings_page)]:
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.tabs.addTab(scroll,name)
        self.build_run(); self.build_history(); self.build_settings()
        self.status = QLabel('尚未连接游戏');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.spend = QLabel('本轮消费：0');layout.addWidget(self.spend)
        controls = QHBoxLayout()
        self.start = self.button('开始',self.start_run,controls)
        self.pause = self.button('暂停 / 继续',self.controller.pause_or_resume,controls)
        self.after = self.button('打完本场停止',self.controller.stop_after_current,controls)
        self.stop = self.button('立即停止',self.controller.stop,controls)
        layout.addLayout(controls)
        self.pause.setEnabled(False);self.stop.setEnabled(False);self.after.setEnabled(False)
        self.kind_changed();self.refresh_state();self.refresh_history()

    @staticmethod
    def button(text, callback, layout):
        value=QPushButton(text);value.clicked.connect(callback);layout.addWidget(value);return value

    @staticmethod
    def spin(maximum, value=0, minimum=0):
        control=QSpinBox();control.setRange(minimum,maximum);control.setValue(value);return control

    def build_run(self):
        layout=QVBoxLayout(self.run_page);form=QFormLayout();layout.addLayout(form)
        self.kind=QComboBox()
        for key,name in TASKS.items():self.kind.addItem(name,key)
        self.stage=QComboBox()
        self.target_scope=QComboBox()
        for title,key in [('当前出战队伍三人','current'),('指定一名培养角色','single'),('指定三名培养角色','triple')]:
            self.target_scope.addItem(title,key)
        characters=json.loads((Path(__file__).resolve().parents[2]/'profiles/characters.json').read_text())
        self.character_names={row['id']:row['name'] for row in characters}
        self.target=QWidget();target_layout=QVBoxLayout(self.target);target_layout.setContentsMargins(0,0,0,0)
        target_layout.addWidget(self.target_scope)
        self.role_selectors=[]
        for index in range(3):
            selector=QComboBox();selector.addItem(f'选择培养角色 {index+1}','')
            for row in sorted(characters,key=lambda row:row['name']):selector.addItem(row['name'],row['name'])
            target_layout.addWidget(selector);self.role_selectors.append(selector)
        self.target_scope.currentIndexChanged.connect(self.target_scope_changed)
        self.claim=QCheckBox('领取波片奖励（默认关闭）')
        self.runs=self.spin(100,1,1);self.waveplates=self.spin(4000,120)
        self.reserve=self.spin(240);self.solvents=self.spin(133)
        for text,widget in [('任务类型',self.kind),('指定副本',self.stage),('培养角色',self.target),
                            ('领奖',self.claim),('最多场数 / 奖励份数',self.runs),('波片消费上限',self.waveplates),
                            ('储备波片上限',self.reserve),('溶剂使用上限（个）',self.solvents)]:form.addRow(text,widget)
        self.hint=QLabel();self.hint.setWordWrap(True);layout.addWidget(self.hint)
        note=QLabel('培养角色用于选择指南需求，不会改变出战队伍。要换战斗角色，请先在游戏里编队，再点“读取当前队伍”。\n'
                    '双倍领取算2份；任一额度用尽即停止。不领奖时，上面的数量是战斗场数，所有消费额度强制为0。')
        note.setWordWrap(True);layout.addWidget(note)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.catalog=self.button('读取关卡 / 材料需求',lambda:self.action('catalog'),actions)
        self.team_button=self.button('读取当前队伍',lambda:self.action('team'),actions)
        self.recover=self.button('返回并治疗',lambda:self.action('recover'),actions)
        self.team=QLabel('实际队伍：尚未读取');self.team.setWordWrap(True);layout.addWidget(self.team)
        self.live=QPlainTextEdit();self.live.setReadOnly(True);self.live.setMaximumBlockCount(250);layout.addWidget(self.live)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.claim.toggled.connect(self.budget_changed)

    def build_history(self):
        layout=QVBoxLayout(self.history_page)
        self.history=QListWidget();self.history.currentItemChanged.connect(self.history_selected);layout.addWidget(self.history)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail)
        self.report_note=QPlainTextEdit();self.report_note.setPlaceholderText('复现步骤、预期结果、实际表现；是否被其他窗口遮挡或手动操作。请勿填密码、UID或账号。')
        self.report_note.setMaximumHeight(100);layout.addWidget(self.report_note)
        row=QHBoxLayout();layout.addLayout(row)
        self.button('导出脱敏诊断包',self.export_report,row)
        self.button('复制报错摘要',self.copy_summary,row)
        self.button('打开GitHub反馈页',lambda:QDesktopServices.openUrl(QUrl(ISSUES)),row)
        self.button('打开本地日志',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root/'logs'))),row)
        note=QLabel('报错后先停止，保留原安装及待核对记录，不要删配置或重复领奖。诊断包包含版本、依赖、任务、错误栈和脱敏日志尾部；默认不含截图、完整日志或账号配置。\n'
                    '导出后在GitHub表单里手动附上ZIP；如需额外截图，请先遮住UID和账号名。')
        note.setWordWrap(True);layout.addWidget(note)

    def build_settings(self):
        layout=QVBoxLayout(self.settings_page)
        self.setup_state=QLabel();self.setup_state.setWordWrap(True);layout.addWidget(self.setup_state)
        self.new_account=QCheckBox('这是全新安装，确认没有需要保留的历史消费记录')
        layout.addWidget(self.new_account)
        self.initialize=self.button('建立本安装的空白账本',self.initialize_account,layout)
        self.button('离线环境诊断',lambda:self.diagnose(False),layout)
        self.button('检查并请求系统权限',lambda:self.diagnose(True),layout)
        guide=QLabel('1. 完整解压Release附件，保留两个项目目录相邻；安装Python 3.13与Xcode Command Line Tools。\n'
                    '2. 双击“安装与检查.command”。成功后双击“启动.command”。首次下载依赖需要网络。\n'
                    '3. 在系统设置允许实际运行程序（通常为Terminal）的屏幕录制、辅助功能权限，必要时重启程序。\n'
                    '4. 打开简体中文鸣潮，进入大世界，选好队伍；面板读取队伍和关卡后开始。游戏须保持前台。\n'
                    '5. 首次先关闭领奖测试1场。需要材料时再明确打开领奖并设置波片/储备/溶剂上限。\n'
                    '6. 暂停会释放按键，但不会暂停游戏里的敌人；关闭面板会先停止控制器。需要打完再停请用“打完本场停止”。\n\n'
                    '当前包面向Apple Silicon Mac、macOS 14+；1080p为主要实测环境，其他画面需单独验证。\n'
                    '周本、部分Boss、地区同名入口、野外聚落仍有未适配项；不表示所有角色或关卡稳定。')
        guide.setWordWrap(True);layout.addWidget(guide)
        self.button('打开完整教程',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root/'docs/beta-user-guide.md'))),layout)
        layout.addStretch()

    def kind_changed(self, *_):
        kind=self.kind.currentData();self.stage.clear();self.stage.setEnabled(kind!='materials')
        self.target.setEnabled(kind in ('materials','material_stage'))
        self.stage.addItem('请先点击“读取关卡 / 材料需求”','')
        if kind=='material_stage':self.target_scope.setCurrentIndex(1)
        self.target_scope.setEnabled(kind!='material_stage')
        self.target_scope_changed()
        self.hint.setText('从列表选择副本和一名培养角色；战斗使用游戏当前队伍。名单表示已适配角色，是否拥有由控制器在游戏中核对。' if kind=='material_stage' else
                          '选择当前三人或指定培养角色，扫描实际材料需求。此模式需要开启领奖；只测试请选择指定材料副本。' if kind=='materials' else
                          '从当前账号读取关卡列表。已有适配的Boss才能进入；未知策略会在控制器内停止。')
        self.budget_changed()

    def budget_changed(self, *_):
        for widget in (self.waveplates,self.reserve,self.solvents):widget.setEnabled(self.claim.isChecked())

    def target_scope_changed(self, *_):
        count={'current':0,'single':1,'triple':3}[self.target_scope.currentData()]
        for index,selector in enumerate(self.role_selectors):selector.setVisible(index<count)

    def target_names(self):
        count={'current':0,'single':1,'triple':3}[self.target_scope.currentData()]
        names=[selector.currentData() for selector in self.role_selectors[:count]]
        if any(not name for name in names):raise ValueError('请从列表选择完整的培养角色。')
        return ','.join(names)

    def refresh_state(self):
        self.state=inspect_user_state(self.root)
        self.setup_state.setText(self.state['title']+'\n'+self.state['message'])
        self.initialize.setEnabled(self.state.get('can_initialize',False))

    def guard(self):
        if self.preview:
            self.message('预览模式不连接游戏、不写配置。');return False
        if self.controller.running:
            self.message('已有任务在运行，请先停止。');return False
        return True

    def action(self, name):
        if not self.guard():return
        try:self.begin(action_arguments(name,self.kind.currentData(),self.target_names() if self.target.isEnabled() else ''),name)
        except (ValueError,RuntimeError) as error:self.message(str(error))

    def start_run(self):
        if not self.guard():return
        self.refresh_state()
        if not self.state.get('can_run'):
            self.message(self.state['message']);self.tabs.setCurrentIndex(2);return
        try:
            request=DesktopRequest(kind=self.kind.currentData(),stage=self.stage.currentData() or '',target=self.target_names() if self.target.isEnabled() else '',
                runs=self.runs.value(),waveplates=self.waveplates.value(),reserve=self.reserve.value(),
                solvents=self.solvents.value(),claim_rewards=self.claim.isChecked())
            if request.claim_rewards and request.solvents and not self.state.get('can_use_solvents'):
                raise ValueError('历史资源账本未核实，不能使用溶剂。')
            args=request.arguments((self.state.get('ledger') or {}).get('solvents_used',0))
            self.begin(args,'farm')
        except (ValueError,RuntimeError) as error:self.message(str(error))

    def begin(self,args,action,runner='ultrawide_trial.py'):
        self.controller.start(args,action,runner)
        self.run_page.setEnabled(False)
        for widget in (self.start,self.catalog,self.team_button,self.recover):widget.setEnabled(False)
        self.stop.setEnabled(True);self.after.setEnabled(runner=='ultrawide_trial.py')

    def progress(self,value):
        self.pause.setEnabled(self.controller.control_ready)
        self.status.setText(('已暂停' if value.get('paused') else value.get('stage','运行中'))+' · '+value.get('detail',''))
        budget=value.get('budget')
        if budget:self.spend.setText(f"本轮：{budget.get('spent',0)}波片 / {budget.get('claimed',0)}份 / {budget.get('solvents_used',0)}溶剂 / {budget.get('reserve_used',0)}储备")

    def log_line(self,line):
        if not line.startswith(('TRIAL_RESULT ','DESKTOP_PROGRESS ')):self.live.appendPlainText(line[-1500:])

    def completed(self,result):
        self.run_page.setEnabled(True)
        for widget in (self.start,self.catalog,self.team_button,self.recover):widget.setEnabled(True)
        self.pause.setEnabled(False);self.after.setEnabled(False);self.stop.setEnabled(False)
        self.status.setText(f"{result.get('status','未知')} · {result.get('error') or result.get('message') or '本轮结果已保存'}")
        if result.get('desktop_action')=='catalog':
            rows=result.get('locations',result.get('rows',[]))
            names=list(dict.fromkeys(r.get('name','') for r in rows if r.get('name')))
            if names:
                self.stage.clear()
                for name in names:self.stage.addItem(name,name)
            if result.get('catalog'):self.detail.setPlainText(json.dumps(result['catalog'],ensure_ascii=False,indent=2))
        if result.get('team'):
            ids=[str(c.get('name')) if isinstance(c,dict) else str(c) for c in result['team']]
            self.team.setText('实际队伍：'+' / '.join(self.character_names.get(key,key) for key in ids))
        self.refresh_state();self.refresh_history()
        if self.closing:self.close()

    def refresh_history(self):
        self.history.clear()
        for path in sorted((self.root/'logs/desktop-runs').glob('*.json'),reverse=True)[:100]:
            try:row=json.loads(path.read_text())
            except (OSError,ValueError):continue
            item=QListWidgetItem(f"{time.strftime('%m-%d %H:%M:%S',time.localtime(path.stat().st_mtime))} · {row.get('stage') or row.get('desktop_action','任务')} · {row.get('status','未知')}")
            item.setData(Qt.UserRole,str(path));self.history.addItem(item)
        if self.history.count():self.history.setCurrentRow(0)

    def history_selected(self,item,_old):
        if item:self.detail.setPlainText(Path(item.data(Qt.UserRole)).read_text())

    def export_report(self):
        if self.preview:return
        destination,_=QFileDialog.getSaveFileName(self,'保存脱敏诊断包',str(Path.home()/f'okww-report-{time.strftime("%Y%m%d-%H%M%S")}.zip'),'ZIP (*.zip)')
        if not destination:return
        try:
            item=self.history.currentItem()
            export_diagnostics(self.root,destination,self.report_note.toPlainText(),item.data(Qt.UserRole) if item else None)
            self.message('已导出。请在GitHub反馈表单手动附上ZIP；原记录和消费保护仍保留。')
        except (OSError,ValueError) as error:self.message(str(error))

    def copy_summary(self):
        from src.runtime.DesktopRecovery import redact_text
        QApplication.clipboard().setText(redact_text(self.detail.toPlainText())+'\n'+redact_text(self.report_note.toPlainText()))

    def initialize_account(self):
        if not self.guard():return
        try:initialize_new_install(self.root,confirmed=self.new_account.isChecked());self.refresh_state()
        except (OSError,ValueError,RuntimeError) as error:self.message(str(error))

    def diagnose(self,permissions):
        if self.guard():self.begin(['--permissions'] if permissions else [],'diagnose','desktop_diagnose.py')

    def message(self,text):QMessageBox.information(self,'OK-WW',text)

    def closeEvent(self,event):
        if self.controller.running:
            self.closing=True;self.controller.stop();event.ignore()
        else:event.accept()
