"""Run only selected per-character categories through the existing controller."""
from pathlib import Path
from dataclasses import asdict
import time

from src.task.CultivationScope import CultivationScope
from src.task.CultivationTargetUI import NoCurrentMaterialNeed
from src.task.EchoFarmTask import EchoFarmTask
from src.task.MaterialActivity import _atomic_json, configured_solvent_total
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.TeamMaterialEntry import MapRouteSkipped


class CultivationTask(CultivationScope, EchoFarmTask):
    echo_mode = 'tacet'
    cultivation_selection = ('声骸',)
    cultivation_targets = ''
    collect_material_echoes = False
    echo_state_path = Path('configs/macos-desktop/cultivation-progress.json')

    def configure_scope(self):
        self.claim_enabled = bool(self.config.get('战后领奖', False))
        self.result['claim_enabled'] = self.claim_enabled
        self._echo_battle_limit = int(self.config['本次战斗上限'])
        if not 1 <= self._echo_battle_limit <= 100:
            raise ValueError('本次战斗上限须为1–100。')
        self._run_budget = MaterialRunBudget(
            int(self.config['本次最多领奖']),
            int(self.config['本次波片上限']) if self.claim_enabled else 0,
            int(self.config['本次储备上限']) if self.claim_enabled else 0, 0,
            max_solvents=self._activity.solvent_allowance(
                self.config['本次溶剂上限'], configured_solvent_total(self.config))
                if self.claim_enabled else 0)
        self.config['每批连续挑战场数'] = 1

    def navigate_echo(self):
        # Recheck the selected character's recommendation on every entry; an
        # earlier catalog or another character's marked row cannot authorize it.
        self.heal_at_beacon()
        rows = self.echo_recommendations(self.expected_target)
        rows = [row for row in rows if row['name'] == self.exact_stage]
        if not rows:
            raise RuntimeError('所选声骸关卡不在当前角色的合鸣套装筛选结果中；停止。')
        if not self.enter_material_location(self.order_material_locations(rows)[0]):
            raise RuntimeError('角色声骸推荐入口未确认。')

    def fresh_material_job(self, queued):
        self.return_to_world()
        observed = self.selected_material_jobs([queued['target']])
        return next((job for job in observed if job['kind'] == queued['kind']
                     and job.get('repeat', 0) == queued.get('repeat', 0)), None)

    def execute_job(self, job):
        self.plan_job = job
        self.expected_target = job['target']
        self.exact_stage = job['route']['fallback_stage_name']
        self._run_budget.claim_cost = job['cost']
        self._plan_boss = job['kind'] in ('突破', '周本')
        # Existing practice entry accepts the non-spending low-waveplate
        # notice; existing material settlement is used only with explicit claims.
        self.phase = 'loop' if self.claim_enabled else 'practice'
        if job['kind'] == '声骸':
            self.set_workflow_stage('声骸导航', f'{self.expected_target} / {self.exact_stage}')
            self.navigate_echo()
            self.set_workflow_stage('战斗')
            self.fight_verified_domain()
            self.result['battles'].append(self.rotation_events)
            if not self.claim_enabled:
                self.dismiss_unclaimed_reward_dialog()
            self.set_workflow_stage('搜索声骸')
            self.search_echo()
            if self.claim_enabled:
                self.set_workflow_stage('领奖')
                self.claim_one_reward(self._run_budget)
            self.set_workflow_stage('返回与治疗')
            self.leave_echo_encounter()
            self.heal_at_beacon()
        else:
            self.run_material_workflow(self._run_budget)
            if self.result['status'] not in ('job_completed', 'practice_completed_no_claim', 'stopped_after_current'):
                raise RuntimeError(self.result.get('error') or '所选材料任务未完成；停止队列。')
        self.update_activity()
        self.save_echo_progress()

    def run_scope_queue(self, jobs):
        self.result['jobs'] = []
        while len(self.result['battles']) < self._echo_battle_limit:
            previous = len(self.result['battles'])
            for queued in jobs:
                if getattr(self, 'stop_after_current', False):
                    self.result['status'] = 'stopped_after_current'
                    return
                if len(self.result['battles']) >= self._echo_battle_limit:
                    return
                if queued['kind'] not in self.selected_kinds:
                    raise RuntimeError('队列含未勾选的培养项目；停止。')
                if queued.get('deferred_reason') or queued.get('satisfied'):
                    continue
                job = queued if queued['kind'] == '声骸' else self.fresh_material_job(queued)
                if not job or job.get('satisfied') or job.get('deferred_reason'):
                    self.result['jobs'].append({'job': job or queued, 'status': 'skipped_no_actionable_need'})
                    continue
                if job['kind'] == '周本' and job['target'] not in ('心', '卜灵'):
                    self.result['jobs'].append({'job': job, 'status': 'deferred_unsupported_weekly'})
                    continue
                self._run_budget.claim_cost = job['cost']
                if self.claim_enabled and not self._run_budget.can_claim():
                    continue
                try:
                    self.execute_job(job)
                except NoCurrentMaterialNeed as exc:
                    self.result['jobs'].append({'job': job, 'status': 'skipped_no_current_need', 'reason': str(exc)})
                    continue
                except MapRouteSkipped:
                    raise RuntimeError('所选项目需要尚未启用的地图路线；停止。')
                self.result['jobs'].append({'job': job, 'status': 'completed'})
                # Refresh after a claim before publishing an updated inventory.
                if self.claim_enabled and job['kind'] != '声骸':
                    self.result.setdefault('refreshed_needs', {})[job['target']] = self.selected_material_jobs([job['target']])
                self.result['status'] = 'running'
            if len(self.result['battles']) == previous:
                return

    def run(self):
        self._activity = None
        self._scope_guard_passed = False
        self.plan_job = None
        self.result = {'status': 'running', 'phase': self.phase, 'battles': []}
        self._run_budget = MaterialRunBudget(1, 0, 0, 0)
        try:
            self.assert_echo_start_safe()
            self._scope_guard_passed = True
            names = self.scope_names()
            jobs = self.scan_scope(names)
            if self.phase == 'cultivation-catalog':
                self.result['status'] = 'catalog_no_spending'
                return
            self.begin_echo_activity()
            self.configure_scope()
            before = self.inspect_echo_inventory('before') if '声骸' in self.selected_kinds else None
            self.run_scope_queue(jobs)
            if before:
                after = self.inspect_echo_inventory('after')
                if before['count'] is not None and after['count'] is not None:
                    self.result['inventory_added'] = after['count'] - before['count']
                    self.result['inventory_verified'] = after['count'] >= before['count']
            stopped = getattr(self, 'stop_after_current', False)
            self.result['status'] = ('stopped_after_current' if stopped else
                                     'completed' if self.result['battles'] else 'no_actionable_selected_jobs')
            self.set_workflow_stage('完成')
        except BaseException as exc:
            self.result.update(status='stopped', error=str(exc), failure_stage=self.result.get('current_stage', '初始化'))
            raise
        finally:
            self._verified_battle = self._in_combat = False
            try:
                self.mouse_up()
                for key in ('w', 'a', 's', 'd', 'shift'):
                    self.send_key_up(key)
            finally:
                self._stop_combat_debug_frame_recorder(log_result=False)
                self.update_activity()
                self.save_run_report()

    def save_run_report(self):
        self.result['budget'] = asdict(self._run_budget)
        # A failed startup must not overwrite an earlier pending checkpoint.
        if self._scope_guard_passed:
            self.save_echo_progress()
        _atomic_json(Path('logs/cultivation-latest.json'), self.result)
        _atomic_json(Path('logs') / f'cultivation-{time.time_ns()}.json', self.result)
