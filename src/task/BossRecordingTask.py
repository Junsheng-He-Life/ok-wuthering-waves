"""One diagnostic boss attempt, isolated from farming progress and spending."""
import time
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.TeamMaterialEntry import TeamMaterialEntry


class BossRecordingTask(TeamMaterialEntry, SafeMaterialTask):
    record_hud = True
    COMBAT_DEBUG_FRAME_HZ = 10

    def run(self):
        self.focus_material_menu()
        self.phase = 'practice'
        self.expected_target = '弗洛洛'
        self.plan_job = {'target': self.expected_target, 'kind': '突破', 'cost': 60,
                         'route': {'category': 'qiangdi', 'fallback_stage_name': ''}}
        self.COMBAT_DEBUG_FRAME_FOLDER = f'boss-recording-{time.time_ns()}'
        self.config['Maximum recovery attempts'] = 0
        self.log_info(f'DIAGNOSTIC_FRAMES logs/{self.COMBAT_DEBUG_FRAME_FOLDER}')
        try:
            super().run()
        finally:
            if self.result:
                self.result['recording_folder'] = f'logs/{self.COMBAT_DEBUG_FRAME_FOLDER}'
                self.save_run_report()
