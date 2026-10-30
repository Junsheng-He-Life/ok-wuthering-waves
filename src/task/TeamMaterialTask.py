"""Desktop queue with shared spending limits and durable claim checkpoints."""
import json
import time
from pathlib import Path

from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.MaterialActivity import SOLVENT_TOTAL_CONFIG, SOLVENT_TOTAL_DESCRIPTION, configured_solvent_total
from src.task.TeamMaterialPlan import TEAM_NAMES, ROLE_KINDS, SHARED_KINDS, build_team_plan, plan_fingerprint
from src.task.TeamMaterialEntry import TeamMaterialEntry
from src.task.TeamMaterialEntry import MapRouteSkipped
from src.task.CultivationTargetUI import NoCurrentMaterialNeed


class TeamMaterialTask(TeamMaterialEntry, SafeMaterialTask):
    desktop_preflight_required = False
    desktop_allow_experimental = False
    target_override = ''
    skip_map_routes = False
    state_path = Path('configs/macos-desktop/team-material-needs-progress.json')
    activity_path = Path('configs/macos-desktop/team-material-activity.json')
    TARGET_NAMES_CONFIG = '队伍培养目标名称（按1、2、3号位）'
    SINGLE_TARGET_CONFIG = '单个培养目标（留空则按全队）'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '全角色材料计划'
        self.description = '识别当前三人队伍并读取培养需求；目标留空时自动跟随队伍，旧名单不匹配时停止。'
        self.support_schedule_task = False
        self.default_config = {'本次最多领奖': 2, '本次波片上限': 80, '本次储备上限': 0,
                               '本次溶剂上限': 0, SOLVENT_TOTAL_CONFIG: 0,
                               self.SINGLE_TARGET_CONFIG: '',
                               '持续轮刷': False,
                               self.TARGET_NAMES_CONFIG: '',
                               '重置已完成进度': False, '结算批次策略': '效率优先',
                               '每个材料恢复次数': 1, '导航恢复次数': 2, '每批连续挑战场数': 2}
        self.config_description = {'每批连续挑战场数': '效率优先时每批1–3场，双倍每场计2份；批末返回，持续轮刷下一轮重查需求，可能少量多刷。',
                                   '每个材料恢复次数': '普通材料战斗失败后治疗并重试同一材料，最多0–3次；Boss仍按专属策略限制。',
                                   '导航恢复次数': '菜单或前往失败后回到培养页面，最多0–3次。',
                                   '本次波片上限': '本次所有角色和材料共享的领奖额度；补充体力另受储备和溶剂上限约束，不花星声。',
                                   self.SINGLE_TARGET_CONFIG: '填写游戏内培养目标名，例如心。当前战斗队伍保持不变，只为此角色刷材料。',
                                   '持续轮刷': '每轮重新读取实际材料缺口，直到材料足够或本次资源额度耗尽。',
                                   '本次溶剂上限': '默认0；与本任务配置的累计剩余额度取较小值。-1表示本次可用全部剩余额度；历史账本未知时禁止使用。',
                                   SOLVENT_TOTAL_CONFIG: SOLVENT_TOTAL_DESCRIPTION,
                                   self.TARGET_NAMES_CONFIG: '留空时按实际识别的三人自动选择；填写时须与当前1、2、3号位完全对应，换队后旧名单不匹配会停止。替其他角色刷材料请使用单个培养目标。',
                                   '重置已完成进度': '重新生成一轮材料计划；不允许清除未确认的领奖。'}
        for kind, _, _ in ROLE_KINDS:
            self.default_config[f'{kind}每人次数'] = 1
            for name in TEAM_NAMES.values():
                key = f'{name}{kind}关卡'
                self.default_config[key] = '旋雾之森' if name == '弗洛洛' and kind == '武器/技能' else ''
                self.config_description[key] = '留空时只接受游戏中培养目标标记的关卡；无法匹配会停止。可填写已核对的完整关卡名。'
        for kind in SHARED_KINDS:
            self.default_config[f'{kind}次数'] = 1
            self.default_config[f'{kind}关卡'] = ''
            self.config_description[f'{kind}关卡'] = '可填写游戏中的完整关卡名；留空时按材料名称唯一匹配。'

    def select_material_target_with_recovery(self, name):
        for attempt in range(3):
            try:
                self.focus_material_menu()
                self.ensure_cultivation_target(name)
                return
            except RuntimeError:
                if attempt == 2:
                    raise
                self.log_info(f'cultivation selection retry {attempt + 1}/2: {name}')
                self.return_to_world()
                self.open_materials_book()

    def reset_material_list_top(self):
        """Drag the observed scrollbar thumb to the top; track clicks only page up."""
        import numpy as np
        if self.menu_text(r'^所需材料$', (.35,.12,.65,.20), timeout=.4, viewport=True):
            return
        self.next_frame()
        sx = round(self.width*.974)
        ys = np.flatnonzero(np.min(self.frame[round(self.height*.13):round(self.height*.88), sx], axis=1)>170)
        if len(ys) > 80:
            center = (int(ys[0])+int(ys[-1]))/2 + round(self.height*.13)
            self.move(sx, center)
            self.sleep(.4)
            import sys
            if sys.platform == 'darwin':
                import Quartz
                interaction = self.executor.interaction
                x0,y0 = interaction.capture.get_abs_cords(sx, center)
                x1,y1 = interaction.capture.get_abs_cords(sx, self.height*.13)
                Quartz.CGAssociateMouseAndMouseCursorPosition(True)
                Quartz.CGWarpMouseCursorPosition((x0,y0))
                time.sleep(.2)
                for step in range(17):
                    point = (x0+(x1-x0)*step/16, y0+(y1-y0)*step/16)
                    kind = Quartz.kCGEventLeftMouseDown if step==0 else Quartz.kCGEventLeftMouseDragged
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None,kind,point,Quartz.kCGMouseButtonLeft))
                    time.sleep(.04)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None,Quartz.kCGEventLeftMouseUp,(x1,y1),Quartz.kCGMouseButtonLeft))
            else:
                self.swipe(sx, center, sx, self.height*.13, duration=.8)
            self.sleep(.8)
            self.next_frame()

    def scan_required_jobs(self, names):
        from src.task.CultivationTargetUI import viewport, required_jobs, supplement_weekly_counts
        jobs = []
        self.open_materials_book()
        for name in names:
            try:
                self.select_material_target_with_recovery(name)
            except RuntimeError as exc:
                jobs.append({"target": name, "kind": "目标待核对", "cost": 40,
                             "repeat": 0, "route": {"category": "ningsu", "fallback_stage_name": ""},
                             "material_counts": [], "satisfied": False,
                             "deferred_reason": f"角色选择三次未确认：{exc}"})
                self.return_to_world()
                self.open_materials_book()
                continue
            self.reset_material_list_top()
            for attempt in range(3):
                boxes = self.ocr(box=viewport(self, .25, .15, .99, .90), target_height=self.height*3)
                boxes = supplement_weekly_counts(self, boxes)
                observed = required_jobs(boxes, name, self.width)
                if not any(j['kind'] == '周本' and not j['material_counts'] for j in observed):
                    break
                self.log_info('weekly count scan: ' + str([
                    (b.name, b.x, b.y, b.width, b.height) for b in boxes
                    if b.name == '技能升级材料' or '/' in b.name or '／' in b.name]))
                if attempt < 2:
                    self.sleep(.3)
                    self.next_frame()
            if not observed:
                raise RuntimeError(f'{name}的所需材料未识别；不生成空计划')
            history_path = Path('logs/material-status/last-observed-jobs.json')
            history = json.loads(history_path.read_text()) if history_path.exists() else []
            records = {(j['target'], j['kind'], j.get('repeat', 0)): j for j in history}
            for row in observed:
                if row.get('material_counts'):
                    records[(row['target'], row['kind'], row.get('repeat', 0))] = row
            history_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = history_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(list(records.values()), ensure_ascii=False))
            temporary.replace(history_path)
            jobs.extend(observed)
            self.log_info(f'cultivation needs {name}: {observed}')
        from src.task.SharedMaterialPlanner import apply_shared_material_plan
        return apply_shared_material_plan(jobs)

    def refresh_changed_targets(self, jobs, targets):
        """Read only farmed targets; retain verified needs for unchanged roles."""
        from src.task.SharedMaterialPlanner import apply_shared_material_plan
        targets = set(targets)
        refreshed = self.scan_required_jobs([n for n in dict.fromkeys(j['target'] for j in jobs)
                                            if n in targets])
        # A failed selector must not replace a previously verified material row.
        failed = {j['target'] for j in refreshed if j['kind'] == '目标待核对'}
        if failed:
            raise RuntimeError('本轮角色头像未确认：' + '、'.join(sorted(failed)))
        merged = [j for j in jobs if j['target'] not in targets] + refreshed
        return apply_shared_material_plan(merged)

    def write_progress(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.progress, ensure_ascii=False, indent=2))
        temporary.replace(self.state_path)
        from src.task.MaterialNeedsReport import write_needs_report
        from dataclasses import asdict
        budget = getattr(self, 'shared_budget', None)
        activity = self.update_activity(publish_report=False) if hasattr(self, '_activity') else None
        write_needs_report(self.progress, 'running', asdict(budget) if budget else None,
                           activity=activity)

    @staticmethod
    def parse_target_names(value):
        from src.task.TeamMaterialTargets import parse_target_names
        return parse_target_names(value)

    def begin_activity(self):
        from src.task.MaterialActivity import MaterialActivity
        self._activity = MaterialActivity(self.activity_path)
        self._activity_started = time.monotonic()
        self._activity_paused_seconds = 0.0
        self._activity_pause_started = None
        self._activity_elapsed_saved = 0
        self._activity_job_started = self._activity_started
        self._activity_job_elapsed_saved = 0
        self._activity_job_paused_seconds = 0.0
        self._activity_job_pause_started = None
        self._activity_job = None
        self._activity_budget_cursor = {'claimed': 0, 'spent': 0, 'solvents_used': 0, 'reserve_used': 0}
        self._activity_claim_job_seconds = 0
        self._activity_current_status = '运行中'
        self._activity.data['runs_started'] = int(self._activity.data.get('runs_started', 0)) + 1
        if int(self._activity.data.get('solvents_used', 0)) >= configured_solvent_total(self.config):
            self._activity_current_status = '溶剂授权额度已用完'
        self.info_set('材料轮刷', '初始化；检查队伍与培养目标')
        self.info_set('功能范围', '普通材料、已适配Boss及部分周本；野外采集、后台输入尚未支持')
        self.update_activity()

    def update_activity(self, status=None, publish_report=True):
        activity = getattr(self, '_activity', None)
        if activity is None:
            return None
        if status is not None:
            self._activity_current_status = status
        now = time.monotonic()
        paused = self._activity_paused_seconds
        if self._activity_pause_started is not None:
            paused += now - self._activity_pause_started
        run_elapsed = int(max(0, now - self._activity_started - paused))
        elapsed_delta = max(0, run_elapsed - self._activity_elapsed_saved)
        self._activity_elapsed_saved = run_elapsed
        activity.add_elapsed(elapsed_delta, self._activity_job)

        budget = getattr(self, 'shared_budget', None)
        claim_delta = spend_delta = solvent_delta = reserve_delta = 0
        before = after = None
        if budget is not None:
            cursor = self._activity_budget_cursor
            claim_delta = max(0, budget.claimed - cursor['claimed'])
            spend_delta = max(0, budget.spent - cursor['spent'])
            solvent_delta = max(0, budget.solvents_used - cursor['solvents_used'])
            reserve_delta = max(0, budget.reserve_used - cursor['reserve_used'])
            cursor.update(claimed=budget.claimed, spent=budget.spent,
                          solvents_used=budget.solvents_used, reserve_used=budget.reserve_used)
            if claim_delta:
                before, after = getattr(self, '_last_claim_stamina', (None, None))
        job_elapsed = self._current_job_elapsed(now)
        if self._activity_job:
            self._activity_job_elapsed_saved = int(job_elapsed)
        activity.add_spending(waveplates=spend_delta, claims=claim_delta,
                              solvents=solvent_delta, reserve=reserve_delta,
                              job=self._activity_job if claim_delta else None,
                              active_seconds=max(0, int(job_elapsed) - self._activity_claim_job_seconds),
                              stamina_before=before, stamina_after=after)
        if claim_delta:
            self._activity_claim_job_seconds = int(job_elapsed)

        current = self._activity_job or {}
        stage = current.get('resolved_stage') or current.get('route', {}).get('fallback_stage_name', '')
        current_text = ' / '.join(x for x in (current.get('target'), current.get('kind'), stage) if x) or '扫描培养目标'
        self.info_set('材料轮刷', self._activity_current_status)
        self.info_set('当前培养材料', current_text)
        self.info_set('累计活跃用时', self._duration(activity.data.get('elapsed_seconds', 0) + run_elapsed - self._activity_elapsed_saved))
        self.info_set('已入账波片消耗', f"{activity.data.get('waveplates_spent', 0)}")
        self.info_set('累计备用结晶提取', f"{activity.data.get('reserve_waveplates_used', 0)}")
        self.info_set('累计领取次数', f"{activity.data.get('claim_units', 0)}")
        self.info_set('累计结晶溶剂', f"{activity.data.get('solvents_used', 0)}")
        self.info_set('溶剂剩余额度', str(activity.solvent_allowance(-1, configured_solvent_total(self.config)))
                      if activity.data.get('history_verified') else '历史账本待核对，禁止使用')
        counts = current.get('material_counts', [])
        if counts:
            self.info_set('当前持有/需求', ' · '.join(f'{owned}/{needed}' for owned, needed in counts))
        if claim_delta:
            self.info_set('最近领取', f"{current.get('target', '未知')} · {current.get('kind', '未知')} ×{claim_delta}，{spend_delta}波片")
        data = activity.save(status=self._activity_current_status, current_job=current or None)
        if publish_report and getattr(self, 'progress', None):
            from dataclasses import asdict
            from src.task.MaterialNeedsReport import write_needs_report
            budget = getattr(self, 'shared_budget', None)
            write_needs_report(self.progress, self._activity_current_status,
                               asdict(budget) if budget else None, activity=data)
        return data

    @staticmethod
    def _duration(seconds):
        from src.task.MaterialActivity import format_duration
        return format_duration(seconds)

    def _current_job_elapsed(self, now=None):
        now = time.monotonic() if now is None else now
        paused = getattr(self, '_activity_job_paused_seconds', 0.0)
        pause_started = getattr(self, '_activity_job_pause_started', None)
        if pause_started is not None:
            paused += now - pause_started
        return max(0.0, now - getattr(self, '_activity_job_started', now) - paused)

    def run(self):
        self.result = {'status': 'running', 'phase': self.phase}
        self.begin_activity()
        try:
            if self.phase == 'claim':
                self.resume_completed_reward()
            else:
                self.run_material_plan()
        except BaseException as exc:
            self.result.update(status='stopped', error=str(exc))
            self.update_activity(status='已停止')
            raise
        status = '已完成' if getattr(self, 'result', {}).get('status') == 'plan_completed' else '已暂停'
        self.update_activity(status=status)

    def resume_completed_reward(self):
        """Resume a saved, unspent reward without rerunning its battle."""
        self.assert_no_pending_refill()
        self.progress = json.loads(self.state_path.read_text())
        if self.progress.get('claim_pending'):
            raise RuntimeError('上次领奖结果不明；禁止重复领取')
        self.job_index = self.progress.get('workflow', {}).get('job_index')
        if not isinstance(self.job_index, int):
            raise RuntimeError('缺少已完成战斗对应的材料检查点')
        self.plan_job = self.progress['jobs'][self.job_index]
        target = self.target_override or self.config.get(self.SINGLE_TARGET_CONFIG, '')
        if not target or self.plan_job['target'] != target:
            raise RuntimeError('领奖检查点与指定培养目标不符')
        self.shared_budget = MaterialRunBudget(
            int(self.config['本次最多领奖']), int(self.config['本次波片上限']),
            int(self.config['本次储备上限']), 0, claim_cost=self.plan_job['cost'],
            max_solvents=self._activity.solvent_allowance(
                self.config.get('本次溶剂上限', 0), configured_solvent_total(self.config)))
        self._activity_job = self.plan_job
        self.result = {'status': 'running', 'phase': 'claim', 'battles': []}
        self._job_claimed_at_start = 0
        try:
            self.focus_material_menu()
            self.restore_reward_dialog()
            self.send_key('esc', after_sleep=.5)
            if not self.in_realm() or not self.find_treasure_icon():
                raise RuntimeError('已完成副本及奖励标记未确认；不消费')
            self.claim_one_reward(self.shared_budget)
            self.leave_verified_domain()
            self.heal_at_beacon()
            self.result['status'] = 'claimed_and_healed'
        except BaseException as exc:
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            from dataclasses import asdict
            self.result['budget'] = asdict(self.shared_budget)
            # The GUI reuses this task instance. Flush with this run's cursor
            # before releasing its budget; a later begin_activity() starts a
            # fresh cursor and must not account for this settlement again.
            # Pending claims remain in the durable progress file.
            self.update_activity()
            self.plan_job = self.shared_budget = None
            self.save_run_report()

    def pause(self):
        now = time.monotonic()
        if hasattr(self, '_activity_started') and self._activity_pause_started is None:
            self._activity_pause_started = now
        if (getattr(self, '_activity_job', None)
                and getattr(self, '_activity_job_pause_started', None) is None):
            self._activity_job_pause_started = now
        return super().pause()

    def unpause(self):
        if (hasattr(self, '_activity_started') and self._activity_pause_started is not None):
            self._activity_paused_seconds += time.monotonic() - self._activity_pause_started
            self._activity_pause_started = None
        if getattr(self, '_activity_job_pause_started', None) is not None:
            self._activity_job_paused_seconds += time.monotonic() - self._activity_job_pause_started
            self._activity_job_pause_started = None
        return super().unpause()

    def complete_job(self, index):
        done = set(self.progress.setdefault('completed_jobs',
                    list(range(self.progress['next_job']))))
        done.add(index)
        self.progress.get('failed_jobs', {}).pop(str(index), None)
        self.progress['completed_jobs'] = sorted(done)
        cursor = 0
        while cursor in done:
            cursor += 1
        self.progress['next_job'] = cursor
        self.write_progress()

    def pending_job_indices(self, jobs):
        done = set(self.progress.get('completed_jobs',
                   range(self.progress['next_job'])))
        failed = self.progress.get('failed_jobs', {})
        # Give unattempted materials a turn before retrying a known failure.
        pending = [i for i in range(len(jobs)) if i not in done]
        return sorted(pending, key=lambda i: (str(i) in failed, i))

    def record_recovered_failure(self, index, report):
        if (report.get('status') != 'job_failed_recovered'
                or not report.get('recovered') or self.shared_budget.claim_pending):
            raise RuntimeError('不能跳过未经确认恢复或领奖结果不明的任务')
        self.progress.setdefault('failed_jobs', {})[str(index)] = {
            'reason': report.get('error', ''), 'recovered': True}
        self.write_progress()

    def checkpoint_claim(self):
        self.progress['claim_pending'] = self.shared_budget.claim_pending
        self.progress['current_job'] = self.plan_job
        self._last_claim_stamina = getattr(self, '_last_claim_stamina', (None, None))
        if (not self.shared_budget.claim_pending and self.shared_budget.claimed >
                getattr(self, '_job_claimed_at_start', 0)):
            # Settlement is confirmed before leaving/healing; a recovery error
            # must not make a future launch repeat this already claimed job.
            self.complete_job(self.job_index)
        self.write_progress()

    def run_material_plan(self):
        self.assert_no_pending_refill()
        previous = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if previous.get('claim_pending'):
            raise RuntimeError('上次领奖结果未确认；禁止自动重复领取')
        if getattr(self, 'desktop_preflight_required', False):
            from src.task.DesktopPreflightTask import require_desktop_preflight
            require_desktop_preflight(self)
        self.focus_material_menu()
        self.return_to_world()
        if not self.load_chars():
            raise RuntimeError('本次队伍未识别；禁止沿用上次队伍，保留材料检查点')
        from src.task.TeamMaterialTargets import resolve_material_targets
        target = str(self.target_override or self.config.get(self.SINGLE_TARGET_CONFIG, '')).strip()
        names = resolve_material_targets(self.chars, self.config.get(self.TARGET_NAMES_CONFIG, ''), target)
        roster = [str(c.char_name) for c in self.chars]
        self.info_set('已识别队伍', '、'.join(roster))
        self.info_set('培养目标对应', f'当前队伍为 {target} 刷材料' if target else
                      '；'.join(f'{i + 1}号位 {roster[i]} → {names[i]}' for i in range(3)))
        # A checkpoint protects unsettled spending; it is not live inventory.
        # Between launches the player may change party, weapon or cultivation
        # goals, or spend shared materials on any character, not just the last
        # one farmed. Preserve the old file until every requested scan returns.
        jobs = self.scan_required_jobs(names)
        if not jobs or {job['target'] for job in jobs} != set(names):
            raise RuntimeError('本次培养目标材料扫描不完整；保留旧检查点，禁止使用旧库存')
        from datetime import datetime
        self.progress = {'plan_id': plan_fingerprint(jobs), 'next_job': 0,
                         'claim_pending': False, 'jobs': jobs, 'roster': roster,
                         'targets': names, 'completed_jobs': [],
                         'observed_at': datetime.now().astimezone().isoformat(timespec='seconds')}
        self.config['重置已完成进度'] = False
        self.write_progress()
        self.shared_budget = MaterialRunBudget(int(self.config['本次最多领奖']),
                                               int(self.config['本次波片上限']),
                                               int(self.config['本次储备上限']), 1,
                                               max_solvents=self._activity.solvent_allowance(
                                                   self.config.get('本次溶剂上限', 0),
                                                   configured_solvent_total(self.config)))
        self.config['每批连续挑战场数'] = 1
        reports = []
        consecutive_failures = 0
        failure = None
        available_done = False
        try:
            while True:
                round_report_start = len(reports)
                claims_before = self.shared_budget.claimed
                changed_targets = set()
                for index in self.pending_job_indices(jobs):
                    if index in self.progress.get('completed_jobs', []):
                        continue
                    self.job_index = index
                    job = jobs[index]
                    self.update_activity()
                    self._activity_job = job
                    self._activity_job_started = time.monotonic()
                    self._activity_job_elapsed_saved = 0
                    self._activity_job_paused_seconds = 0.0
                    self._activity_job_pause_started = None
                    self._activity_claim_job_seconds = 0
                    self.info_set('当前培养材料', f"{job['target']} / {job['kind']}")
                    self.info_set('当前持有/需求', ' · '.join(
                        f'{owned}/{needed}' for owned, needed in job.get('material_counts', [])) or '材料数量未识别')
                    self.update_activity()
                    if job.get('satisfied'):
                        self.complete_job(index)
                        reports.append({'status': 'materials_sufficient', 'job': job})
                        continue
                    if (job.get('deferred_reason') or
                            (job['kind'] == '周本' and job['target'] not in ('心', '卜灵'))):
                        reports.append({'status': 'deferred_unsupported', 'job': job,
                                        'reason': job.get('deferred_reason', '周本适配尚未验证，保留待办并继续其他材料')})
                        self.log_info(f"deferred weekly job {index}: {job['target']}")
                        continue
                    self.shared_budget.claim_cost = job['cost']
                    self.shared_budget.max_retries = max(0, min(3, int(self.config.get('每个材料恢复次数', 1))))
                    if job['kind'] in ('突破', '周本'):
                        # Mechanic-heavy bosses need review after a timeout;
                        # recovery returns to safety without repeating blindly.
                        self.shared_budget.max_retries = 0
                    if not self.shared_budget.can_claim():
                        break
                    self.plan_job = job
                    self.expected_target = job['target']
                    self.exact_stage = job['route']['fallback_stage_name']
                    self.info_set('队伍计划', f"{index + 1}/{len(jobs)} {job['target']} · {job['kind']}")
                    job_claims_before = self.shared_budget.claimed
                    try:
                        SafeMaterialTask.run(self)
                    except NoCurrentMaterialNeed as exc:
                        self.result.update(status='skipped_no_current_need', reason=str(exc))
                    except MapRouteSkipped as exc:
                        self.result.update(status='deferred_map_route', reason=str(exc))
                        self.return_to_world()
                    except Exception:
                        reports.append(dict(self.result))
                        raise
                    if self.shared_budget.claimed > job_claims_before:
                        changed_targets.add(job['target'])
                        self.return_to_world()
                        # Every claim can change a bag shared by several
                        # targets. Re-observe all requested targets before
                        # comparing stock; old peers are not simultaneous data.
                        fresh = self.scan_required_jobs(names)
                        if any(r['kind'] == '目标待核对' for r in fresh):
                            raise RuntimeError('领奖后库存核对失败，不发布旧库存')
                        if {r['target'] for r in fresh} != set(names):
                            raise RuntimeError('领奖后材料扫描不完整，不发布旧库存')
                        by_key = {(r['target'], r['kind'], r.get('repeat', 0)): r for r in fresh}
                        for queued in jobs:
                            observed = by_key.get((queued['target'], queued['kind'], queued.get('repeat', 0)))
                            if observed is not None:
                                queued.clear()
                                queued.update(observed)
                            else:
                                queued.update(satisfied=True, completion_reason='培养页已无此需求')
                        from src.task.SharedMaterialPlanner import apply_shared_material_plan
                        apply_shared_material_plan(jobs)
                        self.progress['jobs'] = jobs
                        self.progress['observed_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
                        self.write_progress()
                    reports.append(dict(self.result))
                    if self.result['status'] == 'deferred_map_route':
                        continue
                    if self.result['status'] == 'job_failed_recovered':
                        self.record_recovered_failure(index, self.result)
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            raise RuntimeError('连续三场失败，已恢复；停止无效轮刷并保留诊断')
                        self.log_info(f'job {index} recovered; continuing next material')
                        continue
                    if self.result['status'] not in ('job_completed', 'skipped_no_current_need'):
                        break
                    consecutive_failures = 0
                    self.complete_job(index)
                if not self.config.get('持续轮刷') or not self.shared_budget.can_claim():
                    break
                if self.shared_budget.claimed == claims_before:
                    blocked_statuses = {'deferred_map_route', 'deferred_unsupported',
                                        'materials_sufficient', 'skipped_no_current_need'}
                    if all(r.get('status') in blocked_statuses for r in reports[round_report_start:]):
                        available_done = True
                        break
                    if any(r.get('status') == 'job_failed_recovered' for r in reports[round_report_start:]):
                        self.log_info('恢复已完成；继续重试未领奖的材料任务')
                        continue
                    raise RuntimeError('本轮没有成功领奖，剩余任务失败或尚未适配；保留进度，避免无效无限重试')
                # Refresh actual cultivation rows after each productive round.
                # Keep the same budget and pending-claim protection across rounds.
                self.return_to_world()
                if not changed_targets:
                    raise RuntimeError('领奖已增加但角色未记录；停止，避免刷新错误库存')
                jobs = apply_shared_material_plan(jobs)
                self.progress = {'plan_id': plan_fingerprint(jobs), 'next_job': 0,
                                 'claim_pending': False, 'jobs': jobs, 'completed_jobs': [],
                                 'roster': roster, 'targets': names,
                                 'observed_at': datetime.now().astimezone().isoformat(timespec='seconds')}
                self.write_progress()
        except Exception as exc:
            failure = str(exc)
            raise
        finally:
            from dataclasses import asdict
            preflight = (self.result or {}).get('preflight')
            self.result = {'status': ('available_materials_ready' if available_done else
                                      'plan_completed' if self.progress['next_job'] >= len(jobs) else 'plan_paused'),
                           'next_job': self.progress['next_job'], 'total_jobs': len(jobs),
                           'jobs': reports, 'budget': asdict(self.shared_budget)}
            if preflight is not None:
                self.result['preflight'] = preflight
            if failure:
                self.result.update(status='stopped', error=failure)
            self.save_run_report()
            self.plan_job = self.shared_budget = None
