"""Material stages and bounded recovery edges, without replaying spending inputs."""
import time
from src.task.CultivationTargetUI import NoCurrentMaterialNeed
from src.task.TeamMaterialEntry import MapRouteSkipped
from src.task.MaterialRefillUI import MaterialResourceLimit, RefillOutcomeUncertain
from src.task.VerifiedDomainCombat import DomainBattleFailed


class MaterialWorkflow:
    def set_workflow_stage(self, stage, detail=''):
        previous = getattr(self, '_workflow_stage', None)
        now = time.monotonic()
        if previous:
            seconds = round(now - self._workflow_stage_at, 2)
            totals = self.result.setdefault('stage_seconds', {})
            totals[previous] = round(totals.get(previous, 0) + seconds, 2)
        self._workflow_stage, self._workflow_stage_at = stage, now
        self.result['current_stage'] = stage
        self.log_info(f'material stage: {stage}; {detail}')
        if getattr(self, '_executor', None) is not None:
            self.info_set('流程阶段', stage)
            self.info_set('阶段说明', detail or '正常执行')
            self.info_set('本任务阶段用时', ' · '.join(
                f'{key} {value:.0f}秒' for key, value in self.result.get('stage_seconds', {}).items()))
        if getattr(self, 'progress', None) is not None:
            self.progress['workflow'] = {'stage': stage, 'detail': detail,
                                         'job_index': getattr(self, 'job_index', None),
                                         'stage_seconds': dict(self.result.get('stage_seconds', {}))}
            self.write_progress()

    def stage_can_retry(self, budget):
        from pathlib import Path
        return (not budget.claim_pending
                and not self.refill_pending_path.exists()
                and not Path('logs/solvent-use-pending.json').exists())

    def run_recoverable_stage(self, stage, action, budget, recover=None, retries=2):
        for attempt in range(retries + 1):
            self.set_workflow_stage(stage, f'尝试{attempt+1}/{retries+1}')
            try:
                return action()
            except (NoCurrentMaterialNeed, MapRouteSkipped, MaterialResourceLimit, RefillOutcomeUncertain):
                raise
            except RuntimeError as exc:
                if attempt >= retries or not self.stage_can_retry(budget):
                    raise
                self.result.setdefault('recoveries', []).append(
                    {'stage': stage, 'attempt': attempt+1, 'error': str(exc)})
                self.set_workflow_stage('恢复', f'{stage}失败：{exc}')
                self.focus_material_menu()
                if recover:
                    recover()

    def reset_material_navigation(self):
        if self.in_realm():
            self.leave_verified_domain()
        self.return_to_world()

    def navigate_material(self):
        self.open_materials_book()
        target = self.ensure_cultivation_target(self.expected_target if self.plan_job else 'Use current in-game target')
        if self._normalize_material_text(target) != self._normalize_material_text(self.expected_target):
            raise RuntimeError('cultivation target changed; stop')
        preflight = getattr(self, 'preflight_material_job', None)
        if preflight:
            preflight()
        route = dict(self.plan_job['route']) if self.plan_job else self.resolve_material_route(
            getattr(self, 'config', {}), actual_target_name=target)
        route['fallback_stage_name'] = self.exact_stage
        if not self.enter_character_material_domain(route):
            raise RuntimeError('exact material stage unavailable')

    def recover_material_battle(self):
        budget = getattr(self, '_run_budget', None)
        if (getattr(self, '_plan_boss', False) and self.material_victory_visible()
                and budget is not None and budget.claimed == getattr(self, '_job_claimed_at_start', 0)):
            raise RuntimeError('已出现领取奖励目标但尚未结算；保留副本现场，禁止恢复流程退出')
        self.leave_verified_domain()
        self.heal_at_beacon()

    def run_material_workflow(self, budget):
        self._job_claimed_at_start = budget.claimed
        self._workflow_stage = None
        self.run_recoverable_stage('导航恢复', self.return_to_world, budget,
                                   recover=self.focus_material_menu)
        self.run_recoverable_stage('队伍治疗', self.heal_at_beacon, budget,
                                   recover=self.reset_material_navigation, retries=1)
        if not self.expected_target or (not self.exact_stage and not self.plan_job):
            raise RuntimeError('an exact verified target and stage are required')
        battle_retries = 0
        while self.phase == 'practice' or budget.can_claim():
            try:
                self.run_recoverable_stage('材料导航', self.navigate_material, budget,
                                           recover=self.reset_material_navigation,
                                           retries=max(0, min(3, int(getattr(self, 'config', {}).get('导航恢复次数', 2)))))
            except (NoCurrentMaterialNeed, MapRouteSkipped, MaterialResourceLimit, RefillOutcomeUncertain):
                raise
            except RuntimeError as exc:
                if not self.plan_job or not self.stage_can_retry(budget):
                    raise
                self.run_recoverable_stage('导航返回', self.reset_material_navigation, budget,
                                           recover=self.focus_material_menu, retries=1)
                self.run_recoverable_stage('队伍治疗', self.heal_at_beacon, budget,
                                           recover=self.focus_material_menu, retries=1)
                self.result.update(status='job_failed_recovered', error=str(exc), recovered=True)
                self.set_workflow_stage('任务待重试', str(exc))
                return
            batch_battles = 0
            battle_failed = False
            while True:
                self.set_workflow_stage('战斗')
                try:
                    self.fight_verified_domain()
                except DomainBattleFailed as exc:
                    self.result.setdefault('recoveries', []).append(
                        {'stage': '战斗', 'attempt': battle_retries+1, 'error': str(exc)})
                    self.run_recoverable_stage('战斗恢复', self.recover_material_battle, budget,
                                               recover=self.focus_material_menu, retries=1)
                    if battle_retries >= budget.max_retries:
                        if self.plan_job:
                            self.result.update(status='job_failed_recovered', error=str(exc), recovered=True)
                            self.set_workflow_stage('任务待重试', str(exc))
                            return
                        raise RuntimeError('recovery limit reached; stop') from exc
                    battle_retries += 1
                    budget.retries += 1
                    battle_failed = True
                    break
                self.result['battles'].append(self.rotation_events)
                if getattr(self, '_plan_boss', False):
                    self.set_workflow_stage('搜索声骸')
                    absorbed, multiple = self.yolo_find_echo(
                        turn=True, use_color=False, time_out=25, threshold=.5)
                    if not absorbed:
                        absorbed, extra = self.yolo_find_echo(
                            turn=True, use_color=True, time_out=20, threshold=.45)
                        multiple = multiple or extra
                    self.result.setdefault('echo_searches', []).append(
                        {'absorbed': bool(absorbed), 'multiple_seen': bool(multiple)})
                    self.log_info(f'战后声骸搜索：已吸收={bool(absorbed)}')
                if self.phase == 'practice':
                    self.run_recoverable_stage('返回', self.recover_material_battle, budget,
                                               recover=self.focus_material_menu, retries=1)
                    self.result['status'] = 'practice_completed_no_claim'
                    self.set_workflow_stage('完成')
                    return
                remaining = self.run_recoverable_stage('领奖', lambda: self.claim_one_reward(budget),
                                                       budget, recover=self.restore_reward_dialog, retries=2)
                batch_battles += 1
                self.set_workflow_stage('结算')
                if not self.try_repeat_material(budget, remaining, batch_battles):
                    break
            if battle_failed:
                continue
            # A failure after confirmed settlement retries only return/healing.
            self.run_recoverable_stage('返回', self.recover_material_battle, budget,
                                       recover=self.focus_material_menu, retries=1)
            if self.plan_job:
                self.result['status'] = 'job_completed'
                self.set_workflow_stage('完成')
                return
        self.result['status'] = 'completed'
        self.set_workflow_stage('完成')
