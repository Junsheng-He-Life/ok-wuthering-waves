"""Exercise real Qt subprocess/signals using a worker with no game imports."""
import os
from pathlib import Path
import tempfile
import time
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from src.ui.DesktopProcess import DesktopProcess

WORKER = '''import json,signal,sys,time
from pathlib import Path
def emit(data):print('DESKTOP_CONTROL '+json.dumps(data),flush=True)
def stop(*_):
 print('TRIAL_RESULT '+json.dumps({'status':'interrupted','message':'中文停止'}),flush=True)
 sys.exit(0)
signal.signal(signal.SIGUSR1,lambda *_:emit({'paused':True,'control_ready':True}))
signal.signal(signal.SIGUSR2,lambda *_:emit({'paused':False,'control_ready':True}))
signal.signal(signal.SIGINT,stop)
emit({'control_ready':True,'paused':False})
request=Path(sys.argv[sys.argv.index('--stop-request')+1])
while not request.exists():time.sleep(.01)
print('TRIAL_RESULT '+json.dumps({'status':'stopped_after_current','battles':[[]]}),flush=True)
'''


class TestDesktopProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(predicate(),'fake-worker protocol timed out')

    def worker(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        root=Path(folder.name);(root/'scripts').mkdir()
        (root/'scripts/ultrawide_trial.py').write_text(WORKER)
        process=DesktopProcess(root);results=[];process.completed.connect(results.append)
        self.addCleanup(lambda:process.process.kill() if process.running else None)
        process.start(['--desktop-session'],'test')
        self.wait(lambda:process.control_ready)
        return process,results

    def test_pause_resume_and_immediate_stop_keep_utf8_result(self):
        process,results=self.worker()
        process.pause_or_resume();self.wait(lambda:process.paused)
        process.pause_or_resume();self.wait(lambda:not process.paused)
        process.stop();self.wait(lambda:bool(results))
        self.assertEqual('interrupted',results[0]['status'])
        self.assertEqual('中文停止',results[0]['message'])
        self.assertFalse(process.running)

    def test_after_current_request_does_not_send_immediate_stop(self):
        process,results=self.worker();process.stop_after_current()
        self.wait(lambda:bool(results))
        self.assertEqual('stopped_after_current',results[0]['status'])
        self.assertFalse(process.stopping)
        self.assertTrue(process.log_path.with_suffix('.json').is_file())


if __name__=='__main__':unittest.main()
