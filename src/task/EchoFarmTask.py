"""Bounded Boss/Tacet echo farming using the desktop material controller."""
import re
import time

from src.combat.MaterialBossProfiles import resolve_boss_profile
from src.combat.EchoCombatPolicy import EchoCombatPolicy
from src.task.CharacterMaterialTask import CharacterMaterialTask
from src.task.EchoPickupUI import EchoPickupUI
from src.task.EchoRunState import EchoRunState
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.MaterialActivity import SOLVENT_TOTAL_CONFIG, SOLVENT_TOTAL_DESCRIPTION, configured_solvent_total
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.TeamMaterialEntry import TeamMaterialEntry
from src.task.VerifiedDomainCombat import DomainBattleFailed


class EchoFarmTask(EchoCombatPolicy, EchoRunState, EchoPickupUI, TeamMaterialEntry, SafeMaterialTask):
    FAILURE_RECOVERY_SECONDS = 240
    echo_mode = 'boss'
    phase = 'echo'
    echo_stage_override = ''
    record_hud = True
    desktop_preflight_required = False
    desktop_allow_experimental = False

    def _echo_recovery_stop_reason(self):
        from src.task.DomainTask import manual_domain_exit_override_active
        if getattr(self, '_manual_exit_requested', False) or manual_domain_exit_override_active():
            return 'manual exit requested'
        executor = getattr(self, '_executor', None)
        if executor is None or not getattr(self, '_enabled', False):
            return 'controller stopped or unavailable'
        if getattr(self, '_paused', False) or getattr(executor, 'paused', False):
            return 'controller paused'
        event = getattr(executor, 'exit_event', None)
        if event is not None and event.is_set():
            return 'controller exit requested'
        return None

    def next_frame(self):
        if getattr(self, '_echo_failure_recovery_active', False):
            reason = self._echo_recovery_stop_reason()
            if reason:
                raise RuntimeError(reason)
            if time.monotonic() >= self._echo_failure_recovery_deadline:
                raise RuntimeError('Echo failure recovery reached its time limit')
        return super().next_frame()

    def recover_failed_echo_battle(self):
        """Retreat once after a verified fight failure, without replaying rewards."""
        from src.task.DomainTask import domain_leave_confirmation_visible
        recovery = {'status': 'skipped', 'attempted': False}
        self.result['failure_recovery'] = recovery
        started = time.monotonic()
        try:
            reason = self._echo_recovery_stop_reason()
            if reason:
                recovery['reason'] = reason
                return
            if self._run_budget.claim_pending:
                recovery['reason'] = 'reward consumption pending verification'
                return
            try:
                self.assert_echo_start_safe()
            except Exception as exc:
                recovery['reason'] = f'pending-state safety check: {exc}'
                return
            # The battle's finally block has stopped attack input and saved its
            # trigger. Use a new frame before deciding which exit is permitted.
            self.next_frame()
            if domain_leave_confirmation_visible(self):
                recovery['reason'] = 'player leave confirmation visible'
                return
            realm = bool(self.in_realm())
            team = bool(self.in_team()[0])
            world = bool(team and self.find_world_earth_icon() and not realm)
            revive = bool(self.menu_text(r'选择复苏物品', timeout=.5))
            if not (world or (team and realm) or revive):
                recovery['reason'] = 'unknown page; no recovery input issued'
                return
            reason = self._echo_recovery_stop_reason()
            if reason:
                recovery['reason'] = reason
                return
            self._echo_failure_recovery_deadline = started + self.FAILURE_RECOVERY_SECONDS
            self._echo_failure_recovery_active = True
            self._verified_battle = self._in_combat = self.in_liberation = False
            self._boss_healing = self._boss_acquiring = False
            recovery.update(status='running', attempted=True, steps=[])
            self.set_workflow_stage('失败退场治疗', '只退场回血，不重试战斗或消费')
            if not world:
                self.leave_verified_domain()
                recovery['steps'].append('left_domain')
            self.next_frame()
            self.return_to_world()
            self.next_frame()
            if not (self.in_team()[0] and self.find_world_earth_icon() and not self.in_realm()):
                raise RuntimeError('world HUD lost after exit; no healing input issued')
            if not world and not self.check_health_bar() and not self.boss_target_locked():
                # Instance exits can restore the entire team. Verify that
                # before opening a map where no local beacon may be visible.
                recovery['healing_mode'] = 'post_exit_health_check'
                self.heal_at_beacon()
            else:
                # An original world encounter may still be dangerous. Avoid
                # cycling wounded members until a forced retreat has finished.
                recovery['healing_mode'] = 'forced_world_retreat'
                self.heal_at_beacon(force_teleport=True, verify_before=False)
            recovery.update(status='healed', healed=True)
            recovery['steps'].append('team_health_verified')
        except Exception as exc:
            recovery.update(status='failed', error=str(exc))
        finally:
            self._echo_failure_recovery_active = False
            recovery['seconds'] = round(time.monotonic() - started, 2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.support_schedule_task = False
        self.group_name = 'Echo'
        self.name = 'Boss 声骸与材料（限额领奖）' if self.echo_mode == 'boss' else '无音区声骸（限额领奖）'
        self.description = '按完整关卡名刷取，复用当前队伍战斗、治疗和控制锁；未知页面停止。'
        self.default_config = {'声骸关卡': '', '本次战斗上限': 2, '战后领奖': True,
                               '本次最多领奖': 2, '本次波片上限': 120,
                               '本次储备上限': 0, '本次溶剂上限': 0, SOLVENT_TOTAL_CONFIG: 0}
        self.config_description = {
            '声骸关卡': '填写指南列表中的完整关卡名；不按序号或培养头像替换目标。',
            '本次战斗上限': '1–100场，还受领奖份数和波片上限约束。',
            '战后领奖': '默认开启：战斗胜利并搜索声骸后，按额度领取材料奖励；关闭可只吸收。'}
        self.config_description.update({
            '本次最多领奖': '每份须在游戏内核对60波片；双倍计2份。',
            '本次波片上限': '本次所有战斗总消费上限，默认120。',
            '本次储备上限': '默认0；仅使用明确配置的额度。',
            '本次溶剂上限': '默认0；受本任务累计授权上限与共享材料账本已用数量约束。',
            SOLVENT_TOTAL_CONFIG: SOLVENT_TOTAL_DESCRIPTION})

    def configure_echo_run(self):
        settings = self.config
        stage = str(self.echo_stage_override or settings.get('声骸关卡', '')).strip()
        if not stage:
            raise ValueError('请先填写完整声骸关卡名，或运行 echo-catalog 扫描')
        if self.echo_mode not in ('boss', 'tacet'):
            raise ValueError('unknown echo mode')
        self.exact_stage = stage
        self.result['stage'] = stage
        self.claim_enabled = bool(settings.get('战后领奖', True))
        self.result['claim_enabled'] = self.claim_enabled
        self._echo_battle_limit = int(settings['本次战斗上限'])
        if not 1 <= self._echo_battle_limit <= 100:
            raise ValueError('本次战斗上限须为1–100')
        self._plan_boss = self.echo_mode == 'boss'
        self.plan_job = {'target': stage, 'kind': 'Boss声骸' if self._plan_boss else '无音区声骸',
                         'resolved_stage': stage,
                         'route': {'category': 'qiangdi' if self._plan_boss else 'wuyin',
                                   'fallback_stage_name': stage}}
        if self._plan_boss:
            profile = resolve_boss_profile(stage)
            if not profile or not profile.supported:
                raise ValueError('该 Boss 尚无已适配的战斗策略；未进入游戏刷取')
            self._material_boss_source = {'boss_key': profile.key}
        if not self.claim_enabled:
            # Ignore even stale saved spending options in absorption-only mode.
            self._run_budget = MaterialRunBudget(1, 0, 0, 0, max_solvents=0)
        else:
            if any(int(settings[key]) < 0 for key in (
                    '本次最多领奖', '本次波片上限', '本次储备上限', '本次溶剂上限')):
                raise ValueError('声骸任务必须使用有限的非负资源上限')
            self._run_budget = MaterialRunBudget(
                int(settings['本次最多领奖']), int(settings['本次波片上限']),
                int(settings['本次储备上限']), 0, claim_cost=60,
                max_solvents=self._activity.solvent_allowance(
                    settings['本次溶剂上限'], configured_solvent_total(settings)))

    def catalog_echoes(self):
        self.return_to_world()
        self.open_materials_book()
        category = 'qiangdi' if self.echo_mode == 'boss' else 'wuyin'
        self.open_boss_book(category)
        catalog = self.build_material_page_dictionary(category, force=True)
        self.result['locations'] = [{k: v for k, v in row.items() if k != 'action_box'}
                                    for row in catalog['locations']]
        self.result['status'] = 'catalog_no_spending'
        self.return_to_world()

    def inspect_echo_inventory(self, label='inspect'):
        import cv2
        from pathlib import Path
        # Exclude the crossed-swords sidebar icon: OCR can prefix it as X.
        if not self.menu_text(r'(武器|声骸)(\d+[/／]\d+)?', (.05, 0, .2, .15), timeout=.5):
            self.return_to_world()
            self.send_key(self.key_config.get('Bag Key', 'b'), after_sleep=1)
        if self.menu_text(r'武器(\d+[/／]\d+)?', (.05, 0, .2, .15), timeout=2):
            # Observed native bag sidebar: the Echo icon is below Weapons.
            self.click_relative(.039, .30, after_sleep=.8)
        if not self.menu_text(r'声骸(\d+[/／]\d+)?', (.05, 0, .2, .15), timeout=2):
            cv2.imwrite('logs/echo-inventory-unrecognized.png', self.frame)
            self.log_info('unrecognized bag header: ' + repr([b.name for b in self.ocr(0, 0, .3, .2)]))
            raise RuntimeError('声骸背包标题未确认；停止只读检查')
        self.next_frame()
        words = [b.name for b in self.ocr(0, 0, 1, 1)]
        header = ''.join(b.name for b in self.ocr(.05, 0, .2, .15))
        match = re.fullmatch(r'声骸(\d+)[/／](\d+)', re.sub(r'\s+', '', header))
        evidence = Path('logs') / f'echo-inventory-{label}-{time.time_ns()}.png'
        cv2.imwrite(str(evidence), self.frame)
        cv2.imwrite('logs/echo-inventory.png', self.frame)
        # Echoes can stack; the displayed header does not verify total item quantity.
        check = {'label': label, 'text': words, 'count': int(match[1]) if match else None,
                 'capacity': int(match[2]) if match else None, 'evidence': str(evidence),
                 'count_scope': 'bag_header_displayed_count_unit_unverified'}
        self.result.setdefault('inventory_checks', []).append(check)
        self.result.update(inventory_count_scope=check['count_scope'],
                           inventory_quantity_verified=False)
        if self.phase == 'echo-inventory':
            self.result.update(status='inventory_inspected_no_spending', inventory_text=words)
        self.send_key('esc', after_sleep=.6)
        return check

    def navigate_echo(self):
        self.return_to_world()
        self.heal_at_beacon()
        self.open_materials_book()
        # Exact name matching and fresh action-box lookup come from the same
        # entry path as materials; no legacy serial-number fallback is used.
        if not CharacterMaterialTask.enter_character_material_domain(self, self.plan_job['route']):
            raise RuntimeError('指定声骸关卡不可用；未替换目标')

    def finish_domain_destination(self, is_team_page):
        if is_team_page:
            return self.start_material_team_verified()
        if not self.wait_until(self.click_traval_button, time_out=10, raise_if_not_found=False):
            return False
        def arrived():
            if self.in_team()[0]:
                return True
            button = self.menu_text(r'开启挑战|StartChallenge', (.72, .85, .98, 1), timeout=.2)
            return self.start_material_team_verified() if button else False
        if not self.wait_until(arrived, time_out=120, raise_if_not_found=False):
            raise RuntimeError('声骸关卡传送后队伍界面未确认')
        self.sleep(2)
        return True

    def prepare_verified_battle(self):
        # Tacet arenas may start immediately after travel, like world bosses.
        start = [re.compile(r'开始挑战|开启挑战|Start Challenge')]
        for _ in range(32):
            if self.in_team()[0] and self.original_combat_detected():
                return False
            if self.find_f_with_text(target_text=start):
                return True
            if not self.in_team()[0]:
                self.fail_battle('声骸入口队伍界面丢失；停止移动')
            self.send_key('w', down_time=.2, after_sleep=.1)
            self.next_frame()
        self.fail_battle('声骸战斗或开始挑战提示未确认；停止移动')

    def claim_one_reward(self, budget):
        if not self.claim_enabled:
            raise RuntimeError('只吸收模式禁止波片领奖')
        return super().claim_one_reward(budget)

    def refill_at_reward(self, *args, **kwargs):
        if not self.claim_enabled:
            raise RuntimeError('只吸收模式禁止补给')
        return super().refill_at_reward(*args, **kwargs)

    def in_combat(self, target=False):
        if (self._verified_battle and time.monotonic() >= self._battle_hard_deadline):
            self.fail_battle('声骸战斗达到总时限；停止战斗输入')
        return super().in_combat(target=target)

    def leave_echo_encounter(self):
        # World bosses leave an unclaimed reward marker in the overworld.
        # Do not mistake that marker for an instanced-domain exit dialog.
        settled = self.menu_text(r'挑战成功|ChallengeCompleted|ChallengeSuccess',
                                 (.2, .1, .8, .4), timeout=.5)
        if not settled and self.find_world_earth_icon() and self.in_team()[0] and not self.in_realm():
            return
        self.leave_verified_domain()

    def run_echo_queue(self):
        budget = self._run_budget
        self.return_to_world()
        if not self.load_chars():
            raise RuntimeError('当前三人队伍读取失败；不沿用旧队伍，停止声骸任务')
        if len(self.chars) != 3 or any(not c or c.char_name == 'unknown' or c.confidence < .8
                                       for c in self.chars):
            raise RuntimeError('当前三人队伍未完整识别；停止声骸任务')
        self.result['team'] = [c.char_name for c in self.chars]
        for _ in range(self._echo_battle_limit):
            if self.claim_enabled and not budget.can_claim():
                break
            self.set_workflow_stage('声骸导航', self.exact_stage)
            self.navigate_echo()
            self.set_workflow_stage('战斗')
            try:
                self.fight_verified_domain()
            except DomainBattleFailed:
                self._echo_failed_during_battle = True
                raise
            self.result['battles'].append(self.rotation_events)
            self.set_workflow_stage('搜索声骸')
            self.search_echo()
            if self.claim_enabled:
                self.set_workflow_stage('领奖')
                self.claim_one_reward(budget)
            self.set_workflow_stage('返回与治疗')
            self.leave_echo_encounter()
            self.heal_at_beacon()
            self.update_activity()
            self.save_echo_progress()
        self.result['status'] = 'completed'
        self.set_workflow_stage('完成')

    def run(self):
        self._activity = None
        self._echo_failed_during_battle = False
        self._echo_failure_recovery_active = False
        self.result = {'status': 'running', 'phase': self.phase, 'mode': self.echo_mode, 'battles': []}
        self._run_budget = MaterialRunBudget(1, 0, 0, 0)
        try:
            self.assert_echo_start_safe()
            if self.phase in ('echo-catalog', 'settlement-catalog'):
                self.catalog_echoes()
                return
            if self.phase == 'echo-inventory':
                self.inspect_echo_inventory()
                return
            if self.phase in ('settlement-enter', 'settlement-travel'):
                self.run_settlement_trial()
                return
            if self.phase == 'settlement-test':
                self.run_settlement_session()
                return
            if getattr(self, 'desktop_preflight_required', False):
                from src.task.DesktopPreflightTask import require_desktop_preflight
                require_desktop_preflight(self)
            self.begin_echo_activity()
            self.configure_echo_run()
            before = self.inspect_echo_inventory('before')
            self.run_echo_queue()
            after = self.inspect_echo_inventory('after')
            if before['count'] is not None and after['count'] is not None:
                delta = after['count'] - before['count']
                # Keep legacy aliases; none establishes the header's unit or stack totals.
                self.result['inventory_header_count_delta'] = delta
                self.result['inventory_added'] = delta
                self.result['inventory_verified'] = after['count'] >= before['count']
        except BaseException as exc:
            self.result.update(status='stopped', error=str(exc),
                               failure_stage=self.result.get('current_stage', '初始化'))
            if (isinstance(exc, DomainBattleFailed) and self.phase == 'echo'
                    and self._echo_failed_during_battle):
                self.recover_failed_echo_battle()
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


class BossEchoTask(EchoFarmTask):
    echo_mode = 'boss'


class TacetEchoTask(EchoFarmTask):
    echo_mode = 'tacet'
