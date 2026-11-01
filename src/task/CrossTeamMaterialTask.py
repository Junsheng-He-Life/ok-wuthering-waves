"""A single controller and spending budget for a set of saved-party targets."""
import json
import time
from datetime import datetime
from pathlib import Path

import cv2

from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.PresetTeamUI import PresetTeamUI, parse_team_numbers
from src.task.DesktopPreflightTask import observe_members, trusted_members, collect_team_readiness
from src.task.MaterialActivity import _atomic_json
from src.task.MaterialIdentity import aggregate_named_materials


class CrossTeamMaterialTask(TeamMaterialTask):
    target_teams = '1,2,3,4,5'
    combat_teams = '2,4,5'
    cross_scan_only = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '跨队材料计划'
        self.description = '核对保存队伍，按材料图标和名称合并缺口，只用允许队伍战斗。'

    def record_event(self, kind, **fields):
        row = {'at': datetime.now().astimezone().isoformat(timespec='seconds'), 'kind': kind, **fields}
        self.cross_report.setdefault('events', []).append(row)
        _atomic_json(Path('logs/cross-team-latest.json'), self.cross_report)
        with (self.cross_log / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        snapshot = Path('logs/material-status/named-live.json')
        if kind in ('error', 'finished') and snapshot.exists():
            data = json.loads(snapshot.read_text())
            data['status'] = 'stopped' if kind == 'error' else fields['result'].get('status', 'ended')
            data['error'] = fields.get('error', '')
            _atomic_json(snapshot, data)

    def prepare_teams(self):
        requested, allowed = parse_team_numbers(self.target_teams), parse_team_numbers(self.combat_teams)
        self.cross_log = Path('logs/cross-team') / str(time.time_ns())
        self.cross_log.mkdir(parents=True, exist_ok=True)
        self.cross_report = {'target_teams': list(requested), 'combat_teams': list(allowed), 'teams': [], 'events': []}
        self.record_event('started')
        self.assert_no_pending_refill()
        previous = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if previous.get('claim_pending'):
            raise RuntimeError('上次领奖结果未确认；禁止切换队伍或重新刷取')
        self.publish_named_snapshot([], [f'队伍{n}成员待核验' for n in requested], complete=False)
        selector = PresetTeamUI(self)
        targets = []
        for number in requested:
            self.info_set('流程阶段', '读取保存队伍')
            self.info_set('阶段说明', f'读取队伍 {number}；扫描期间不战斗')
            team = selector.select(number)
            from src.task.TeamMaterialTargets import registered_target_name
            for member in team['members']:
                # A combat identity without a cultivation label is not a valid
                # material target. Do not feed internal template IDs to the UI.
                member['name'] = registered_target_name(member['character'])
            self.cross_report['teams'].append(team)
            targets.extend(member['name'] for member in team['members'])
            self.record_event('team_observed', team=team)
        self.requested_material_targets = self.select_material_targets(targets)
        self.cross_report['targets'] = self.requested_material_targets
        self.record_event('targets_selected', targets=self.requested_material_targets)
        # Prefer the most recently validated high-level party, but never leave
        # the explicit allow-list. Other allowed parties remain fallback options.
        for number in sorted(allowed, reverse=True):
            team = self.cross_report['teams'][-1] if number == requested[-1] else selector.select(number)
            self.desktop_preflight_mode = 'materials'
            if self.cross_scan_only:
                self.selected_combat_team = number
                self.expected_combat_members = [m['character'] for m in team['members']]
                self.cross_report['selected_combat_team'] = number
                self.record_event('scan_party_selected', number=number)
                return
            readiness = collect_team_readiness(self)
            self.record_event('combat_candidate', number=number, preflight=readiness)
            if readiness['can_start']:
                self.selected_combat_team = number
                self.expected_combat_members = [m['character'] for m in team['members']]
                self.cross_report['selected_combat_team'] = number
                return
        raise RuntimeError('允许的战斗队伍均未通过当前身份、等级或生命值检查')

    def select_material_targets(self, observed):
        target = str(self.target_override or '').strip()
        if target and target not in observed:
            raise RuntimeError(f'单角色目标 {target} 不在本次核验的目标队伍中')
        return [target] if target else list(dict.fromkeys(observed))

    def resolve_plan_targets(self, target):
        if target and self.requested_material_targets != [target]:
            raise RuntimeError('单角色目标与已核验的扫描范围不一致')
        self.verify_plan_party()
        return self.requested_material_targets

    def verify_plan_party(self):
        if self.selected_combat_team not in parse_team_numbers(self.combat_teams):
            raise RuntimeError('当前战斗队伍不在允许列表内')
        self.return_to_world()
        members = observe_members(self)
        if not trusted_members(members) or [m['character'] for m in members] != self.expected_combat_members:
            raise RuntimeError('当前战斗成员与已核验的允许队伍不同；停止进入副本')

    def scan_required_jobs(self, names):
        from src.task.NamedMaterialScan import NamedMaterialScanner
        from src.task.SharedMaterialPlanner import apply_shared_material_plan
        scanner = NamedMaterialScanner(self)
        self._named_refresh_mode = 'full'
        self._named_refresh_running = False
        self._named_refreshed_targets = list(names)
        self._targeted_refreshes = 0
        jobs = []
        # Publish unknown entries immediately; a partial scan must not display
        # yesterday's inventory for unvisited targets.
        self.publish_named_snapshot([], names, complete=False)
        for index, name in enumerate(names):
            self.info_set('流程阶段', '扫描材料图标与名称')
            self.info_set('阶段说明', f'{index + 1}/{len(names)} · {name}')
            jobs.extend(scanner.scan(name))
            self.publish_named_snapshot(jobs, names, complete=index == len(names)-1)
        jobs = apply_shared_material_plan(jobs)
        priority = {'武器/技能': 0, '角色经验': 1, '武器经验': 2, '贝币': 3, '突破': 4, '周本': 5}
        return sorted(jobs, key=lambda job: (bool(job.get('deferred_reason')), priority.get(job['kind'], 6),
                                            tuple(job.get('material_names') or []), job['target']))

    def refresh_after_claim(self, jobs, names):
        from src.task.NamedMaterialRefresh import refresh_targets, merge_inventory_refresh, FullMaterialRefreshRequired
        from src.task.NamedMaterialScan import NamedMaterialScanner
        from src.task.MaterialTileVision import MaterialPageReadError
        from src.task.SharedMaterialPlanner import apply_shared_material_plan
        coverage = refresh_targets(jobs, self.plan_job)
        if coverage is None or getattr(self, '_targeted_refreshes', 0) >= 2:
            return self.scan_required_jobs(names)
        targets, required = coverage
        self._named_refresh_mode = 'targeted'
        self._named_refreshed_targets = targets
        self._named_refresh_running = True
        self.publish_named_snapshot(jobs, names, complete=True)
        try:
            scanner = NamedMaterialScanner(self)
            fresh = []
            for index, target in enumerate(targets):
                self.set_workflow_stage('刷新库存', f'{index+1}/{len(targets)} · {target}')
                fresh.extend(scanner.scan(target))
            merged = merge_inventory_refresh(jobs, fresh, targets, required)
        except (FullMaterialRefreshRequired, MaterialPageReadError) as exc:
            self.record_event('full_refresh_fallback', error=str(exc))
            return self.scan_required_jobs(names)
        self._targeted_refreshes = getattr(self, '_targeted_refreshes', 0)+1
        self._named_refresh_running = False
        self._named_refresh_mode = 'targeted'
        self._named_refreshed_targets = targets
        apply_shared_material_plan(merged)
        self.publish_named_snapshot(merged, names, complete=True)
        self.record_event('inventory_refreshed', targets=targets, material_names=sorted(required))
        return merged

    def publish_named_snapshot(self, jobs, names, complete):
        materials, unknown = aggregate_named_materials(jobs)
        missing_targets = set(names) - {j['target'] for j in jobs}
        unknown.extend({'target': n, 'reason': '尚未扫描'} for n in names if n in missing_targets)
        _atomic_json(Path('logs/material-status/named-live.json'), {
            'schema': 1, 'observed_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'targets': list(names), 'target_teams': list(parse_team_numbers(self.target_teams)),
            'combat_teams': list(parse_team_numbers(self.combat_teams)),
            'selected_combat_team': getattr(self, 'selected_combat_team', None),
            'scan_complete': complete,
            'status': 'refreshing' if getattr(self, '_named_refresh_running', False) else ('ready' if complete else 'scanning'),
            'refresh_mode': getattr(self, '_named_refresh_mode', 'full'),
            'refreshed_targets': getattr(self, '_named_refreshed_targets', list(names)),
            'materials': materials, 'unknown': unknown,
            'jobs': jobs, 'source': 'live_icon_and_item_detail'})

    def preflight_material_job(self):
        # Verify the current material images again before using the legacy
        # category's navigation button; an old row ordinal is not identity.
        from src.task.NamedMaterialScan import NamedMaterialScanner
        self.reset_material_list_top()
        current, _ = NamedMaterialScanner(self).page(self.expected_target)
        wanted = tuple(self.plan_job.get('material_names') or [])
        matching = [j for j in current if tuple(j.get('material_names') or []) == wanted]
        if not wanted or len(matching) != 1:
            raise RuntimeError('入场前材料图标与名称未唯一匹配')
        if matching[0]['kind'] != self.plan_job['kind'] or matching[0]['repeat'] != self.plan_job['repeat']:
            raise RuntimeError('材料所在位置改变；需要重新扫描后再导航')
        # Entry always uses this page's real counts, including incidental
        # drops not covered by the previous reward refresh.
        from src.task.NamedMaterialRefresh import sync_observed_inventory
        from src.task.SharedMaterialPlanner import apply_shared_material_plan
        from src.task.CultivationTargetUI import NoCurrentMaterialNeed
        if [n for _, n in matching[0]['material_counts']] != [n for _, n in self.plan_job['material_counts']]:
            raise RuntimeError('培养需求改变；需要完整重扫后再入场')
        queued = self.progress['jobs']
        updated = apply_shared_material_plan(sync_observed_inventory(queued, current, wanted))
        for old, new in zip(queued, updated):
            old.clear()
            old.update(new)
        self.write_progress()
        if self.plan_job['satisfied']:
            raise NoCurrentMaterialNeed('入场前实名材料库存已满足全部共享需求')
        return super().preflight_material_job()

    def run_material_plan(self):
        try:
            self.prepare_teams()
            self.config[self.SINGLE_TARGET_CONFIG] = ''
            self.config[self.TARGET_NAMES_CONFIG] = ''
            if self.cross_scan_only:
                jobs = self.scan_required_jobs(self.requested_material_targets)
                self.return_to_world()
                self.result.update(status='catalog_completed', targets=self.requested_material_targets, jobs=jobs)
            else:
                # prepare_teams already performs the same fresh desktop check.
                self.desktop_preflight_required = False
                super().run_material_plan()
                if getattr(self, '_targeted_refreshes', 0):
                    # A terminal summary must not call a partially refreshed
                    # bag complete. This check is read-only even at zero budget.
                    self.set_workflow_stage('刷新库存', '本轮结束，完整核对所有目标')
                    fresh = self.scan_required_jobs(self.requested_material_targets)
                    from src.task.MaterialIdentity import refresh_named_jobs
                    from src.task.SharedMaterialPlanner import apply_shared_material_plan
                    refresh_named_jobs(self.progress['jobs'], fresh)
                    apply_shared_material_plan(self.progress['jobs'])
                    self.progress['observed_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
                    self.write_progress()
                materials, unknown = aggregate_named_materials(self.progress['jobs'])
                remaining = [r for r in materials if r['raw_missing'] is None or r['raw_missing'] > 0]
                self.result['remaining_materials'] = remaining
                self.result['unidentified_materials'] = unknown
                if remaining or unknown:
                    if self.result['status'] in ('plan_completed', 'available_materials_ready'):
                        self.result['status'] = 'materials_remaining'
            self.record_event('finished', result=self.result)
        except BaseException as exc:
            if hasattr(self, 'cross_report'):
                evidence = self.cross_log / f'{time.time_ns()}-error.png'
                try:
                    cv2.imwrite(str(evidence), self.frame)
                except Exception:
                    pass
                self.record_event('error', error=str(exc), image=str(evidence))
            raise
