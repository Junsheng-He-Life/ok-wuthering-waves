"""Exercise the desktop-to-runner boundary without creating a game device."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from src.runtime.DesktopJobs import DesktopRequest, action_arguments, result_summary, read_json
from src.ui.DesktopProcess import DesktopProcess
from src.ui.DesktopHotkey import DesktopHotkey
from PySide6.QtCore import QObject, QProcess, QRect, Signal
from PySide6.QtWidgets import QBoxLayout
import signal
import time
import json
from src.runtime.DesktopTrialMonitor import DesktopTrialMonitor, snapshot
from src.runtime.DesktopUserState import initialize_new_install
from src.ui.DesktopWindow import DesktopWindow


class TestDesktopPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def window(self, preview=True):
        window = DesktopWindow(self.root, preview=preview)
        self.addCleanup(window.deleteLater)
        return window

    def test_absorb_only_zeros_all_spending_arguments(self):
        args = DesktopRequest(stage='玄幽东岳无音区', claim_rewards=False,
                              solvents=6, reserve=240).arguments(42)
        for name in ('--max-stamina', '--reserve-limit', '--solvent-limit'):
            self.assertEqual('0', args[args.index(name) + 1])
        self.assertEqual('42', args[args.index('--solvent-total') + 1])
        self.assertIn('--echo-no-claim', args)
        self.assertIn('--desktop-preflight', args)

    def test_this_run_solvent_cap_adds_verified_history_exactly_once(self):
        args = DesktopRequest(stage='玄幽东岳无音区', solvents=2).arguments(152)
        self.assertEqual('154', args[args.index('--solvent-total') + 1])
        self.assertEqual('2', args[args.index('--solvent-limit') + 1])

    def test_invalid_requests_never_produce_process_arguments(self):
        for request in (DesktopRequest(), DesktopRequest(kind='other'),
                        DesktopRequest(stage='x', solvents=-1),
                        DesktopRequest(stage='x', claims=True),
                        DesktopRequest(stage='x', waveplates=0),
                        DesktopRequest(kind='materials', claim_rewards=False)):
            with self.subTest(request=request), self.assertRaises(ValueError):
                request.arguments()

    def test_preflight_preserves_selected_mode_and_route(self):
        args = action_arguments('preflight', 'boss', '哀声鸷')
        self.assertEqual('boss', args[args.index('--desktop-preflight-mode') + 1])
        self.assertEqual('哀声鸷', args[args.index('--stage') + 1])

    def test_preview_has_no_files_or_controller(self):
        with patch('src.ui.DesktopProcess.DesktopProcess.start') as start:
            window = self.window()
            window.show_message = Mock()
            window.start_farming()
            start.assert_not_called()
        self.assertEqual([], list(self.root.iterdir()))

    def test_start_controls_remain_visible_at_minimum_window_size(self):
        window = self.window()
        window.show()
        for width, height in ((920, 600), (1000, 640), (1220, 680), (1220, 900), (1600, 900)):
            with self.subTest(size=(width, height)):
                window.resize(width, height)
                self.app.processEvents()
                self.assertEqual((width, height), (window.width(), window.height()))
                for index in range(4):
                    window.show_page(index)
                    self.app.processEvents()
                    scroll = window.stack.currentWidget()
                    self.assertEqual(0, scroll.horizontalScrollBar().maximum())
                window.show_page(0)
                for running in (False, True):
                    window.set_running(running)
                    self.app.processEvents()
                    controls = (window.run_page.pause, window.run_page.stop) if running else (window.run_page.start,)
                    for control in controls:
                        position = control.mapTo(window, control.rect().bottomRight())
                        self.assertLess(position.y(), window.height())
                        self.assertLess(position.x(), window.width())
                        self.assertTrue(control.isVisible())
        window.set_running(False)
        window.close()

    def test_small_screen_fit_and_monitor_move_keep_window_reachable(self):
        window = self.window()
        for area in (QRect(0, 24, 1280, 672), QRect(-1280, 24, 1280, 672), QRect(0, 24, 1440, 852)):
            with self.subTest(area=area):
                window.resize(1220, 900)
                window.fit_to_screen(SimpleNamespace(availableGeometry=lambda: area))
                self.assertTrue(area.contains(window.frameGeometry()))
                self.assertLessEqual(window.height(), area.height() - 48)

    def test_narrow_window_stacks_cards_and_wide_window_restores_columns(self):
        window = self.window()
        window.show()
        for width, direction in ((920, QBoxLayout.TopToBottom), (1220, QBoxLayout.LeftToRight),
                                 (1000, QBoxLayout.TopToBottom)):
            window.resize(width, 640)
            self.app.processEvents()
            self.assertEqual(direction, window.run_page.columns.direction())
        window.close()

    def test_removed_screen_and_deleted_window_cancel_pending_layout_work(self):
        import shiboken6

        class Screen(QObject):
            availableGeometryChanged = Signal(QRect)

            def availableGeometry(self):
                if not shiboken6.isValid(self):
                    raise RuntimeError('Screen was removed')
                return QRect(0, 24, 1280, 672)

        window = DesktopWindow(self.root, preview=True)
        old, new = Screen(), Screen()
        window._screen_changed(old)
        shiboken6.delete(old)
        window._screen_changed(new)
        shiboken6.delete(new)
        window._fit_current_screen()
        with patch.object(window, 'fit_to_screen') as fit:
            shiboken6.delete(window)
            self.app.processEvents()
            fit.assert_not_called()

    def test_screen_fit_preserves_maximized_and_fullscreen_window_states(self):
        window = self.window()
        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 24, 1280, 672))
        for show, check in ((window.showMaximized, window.isMaximized),
                            (window.showFullScreen, window.isFullScreen)):
            show()
            self.app.processEvents()
            window.fit_to_screen(screen)
            self.assertTrue(check())
        window.close()

    def test_first_use_requires_explicit_initialization(self):
        window = self.window(preview=False)
        self.assertFalse(window.run_page.start.isEnabled())
        self.assertTrue(window.settings_page.initialize.isVisibleTo(window.settings_page))
        window.settings_page.new_account.setChecked(True)
        window.initialize_account()
        self.assertTrue(window.state['can_run'])
        self.assertTrue(window.run_page.start.isEnabled())

    def test_pending_blocks_farming_but_allows_read_only_observation(self):
        initialize_new_install(self.root, confirmed=True)
        pending = self.root / 'logs/echo-claim-pending.json'
        pending.write_text('{}')
        window = self.window(preview=False)
        with patch.object(window, 'begin') as begin:
            window.start_farming()
            begin.assert_not_called()
            window.run_action('observe')
            self.assertEqual('observe', begin.call_args.args[1])
        self.assertTrue(pending.exists())

    def test_click_start_uses_current_budget_and_fresh_preflight(self):
        initialize_new_install(self.root, confirmed=True)
        window = self.window(preview=False)
        window.run_page.stage.clear()
        window.run_page.stage.addItem('玄幽东岳无音区', '玄幽东岳无音区')
        with patch.object(window, 'begin') as begin:
            window.start_farming()
            args = begin.call_args.args[0]
            self.assertIn('--desktop-session', args)
            self.assertIn('--desktop-preflight', args)
            self.assertEqual('0', args[args.index('--solvent-limit') + 1])

    def test_failed_preflight_is_not_presented_as_success(self):
        result = result_summary({'status': 'preflight_blocked', 'preflight': {'issues': ['等级不足']}})
        self.assertEqual('队伍检查未通过', result['title'])
        self.assertEqual('等级不足', result['message'])

    def test_wrong_json_type_cannot_crash_the_panel(self):
        path = self.root / 'configs/macos-desktop/desktop-panel.json'
        path.parent.mkdir(parents=True)
        path.write_text('[]')
        self.assertEqual({}, read_json(path, {}))
        self.window(preview=False)

    def test_unknown_failure_status_is_never_presented_as_completed(self):
        self.assertNotEqual('检查已完成', result_summary({'status': 'failed'})['title'])

    def test_geometry_stop_reaches_panel_and_preserves_confirmed_spending(self):
        from scripts.ultrawide_trial import final_result
        message = '游戏窗口、显示器或缩放已改变，本轮已停止。请重新检查队伍后再开始。'
        capture = SimpleNamespace(geometry_error=message)
        for original in (None, {'status': 'completed', 'budget': {'spent': 120, 'claimed': 2}}):
            result = final_result(original, capture, interrupted=True)
            summary = result_summary(result)
            self.assertEqual('stopped', result['status'])
            self.assertEqual(message, summary['message'])
            self.assertEqual(120 if original else 0, summary['spent'])

    def test_startup_resolution_error_reaches_panel_without_task_result(self):
        from scripts.ultrawide_trial import final_result
        message = '当前游戏画面 1024×768；最低要求 1280×720。'
        result = final_result(None, None, execution_error=message)
        self.assertEqual('stopped', result['status'])
        self.assertEqual(message, result_summary(result)['message'])

    def test_stop_during_process_start_never_signals_pid_zero(self):
        controller = DesktopProcess(self.root)
        controller.process = SimpleNamespace(state=lambda: QProcess.Starting, processId=lambda: 0)
        with patch('os.kill') as kill:
            controller.stop()
            kill.assert_not_called()
            controller.process.processId = lambda: 12345
            controller._started()
            kill.assert_called_once_with(12345, signal.SIGINT)

    def test_signal_race_with_process_exit_is_harmless(self):
        controller = DesktopProcess(self.root)
        controller.process = SimpleNamespace(processId=lambda: 12345)
        with patch('os.kill', side_effect=ProcessLookupError):
            self.assertFalse(controller._send_signal(signal.SIGINT))

    def test_utf8_progress_split_between_reads_preserves_chinese(self):
        controller = DesktopProcess(self.root)
        received = []
        controller.changed.connect(received.append)
        raw = ('DESKTOP_PROGRESS ' + json.dumps({'stage': '正在领奖'}, ensure_ascii=False) + '\n').encode()
        offset = raw.index('在'.encode()) + 1
        chunks = iter((raw[:offset], raw[offset:]))
        controller.process = SimpleNamespace(readAllStandardOutput=lambda: next(chunks))
        controller._read()
        controller._read()
        self.assertEqual('正在领奖', received[0]['stage'])

    def test_real_child_process_pause_resume_stop_protocol_without_game(self):
        script = self.root / 'scripts/ultrawide_trial.py'
        script.parent.mkdir()
        script.write_text('''import json,signal,time
def emit(prefix, value):
 print(prefix, json.dumps(value), flush=True)
signal.signal(signal.SIGUSR1, lambda *_: emit('DESKTOP_CONTROL', {'paused':True,'control_ready':True}))
signal.signal(signal.SIGUSR2, lambda *_: emit('DESKTOP_CONTROL', {'paused':False,'control_ready':True}))
def stop(*_):
 emit('TRIAL_RESULT', {'status':'interrupted','budget':{'spent':0,'claimed':0}})
 raise SystemExit(0)
signal.signal(signal.SIGINT,stop)
emit('DESKTOP_PROGRESS', {'stage':'offline fake task','paused':False,'control_ready':True})
while True: time.sleep(.02)
''')
        controller = DesktopProcess(self.root)
        completed = []
        controller.completed.connect(completed.append)

        def wait_for(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(predicate())

        try:
            controller.start([], 'offline_protocol_test')
            wait_for(lambda: controller.control_ready)
            controller.pause_or_resume()
            wait_for(lambda: controller.paused)
            controller.pause_or_resume()
            wait_for(lambda: not controller.paused)
            controller.stop()
            wait_for(lambda: bool(completed))
            self.assertEqual('interrupted', completed[0]['status'])
            self.assertEqual(0, completed[0]['budget']['spent'])
        finally:
            if controller.running:
                controller.process.kill()
                controller.process.waitForFinished(2000)

    def test_pause_releases_inputs_and_resume_does_not_create_new_task(self):
        executor = SimpleNamespace(paused=False, pause=Mock())
        task = SimpleNamespace(paused=False, pause=Mock(), unpause=Mock(), result={}, info={})
        executor.current_task = task
        app = SimpleNamespace(task_executor=executor, exit_event=Mock(is_set=Mock(return_value=False)))
        release = Mock()
        monitor = DesktopTrialMonitor(app, task, 600, Mock(), release)
        with patch('builtins.print'):
            monitor.pause()
            monitor.resume()
        task.pause.assert_called_once()
        task.unpause.assert_called_once()
        release.assert_called_once_with(app)
        self.assertTrue(task.held_attack_interrupted)

    def test_pause_at_task_boundary_never_calls_a_stale_task(self):
        task = SimpleNamespace(paused=False, pause=Mock(), unpause=Mock(), result={}, info={})
        executor = SimpleNamespace(paused=False, current_task=None, pause=Mock())
        app = SimpleNamespace(task_executor=executor, exit_event=Mock(is_set=Mock(return_value=False)))
        monitor = DesktopTrialMonitor(app, task, 600, Mock(), Mock())
        monitor.pause()
        monitor.resume()
        task.pause.assert_not_called()
        task.unpause.assert_not_called()
        self.assertFalse(snapshot(task, executor)['control_ready'])

    def test_progress_respects_task_pause_even_when_executor_is_not_paused(self):
        task = SimpleNamespace(result={}, info={}, paused=True)
        self.assertTrue(snapshot(task, SimpleNamespace(paused=False))['paused'])

    def test_pause_hotkey_ignores_other_keys_and_repeat(self):
        hotkey = DesktopHotkey()
        hotkey.key = 'f9'
        requests = []
        hotkey.toggled.connect(lambda: requests.append('toggle'))
        for key in ('a', 'r', 'f9', 'f9'):
            hotkey._press(key)
        self.assertEqual(['toggle'], requests)
        hotkey._release('f9')
        hotkey._press('f9')
        self.assertEqual(['toggle', 'toggle'], requests)
        hotkey.listener = Mock()
        listener = hotkey.listener
        hotkey.disable()
        listener.stop.assert_called_once()
        self.assertIsNone(hotkey.listener)

    def test_no_permission_does_not_start_hotkey_listener(self):
        import sys
        hotkey = DesktopHotkey()
        with patch.dict(sys.modules, {'Quartz': SimpleNamespace(AXIsProcessTrusted=lambda: False)}):
            self.assertFalse(hotkey.enable())
        self.assertIsNone(hotkey.listener)


if __name__ == '__main__':
    unittest.main()
