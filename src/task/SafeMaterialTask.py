"""A bounded material workflow with verified settlement and team recovery."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from src.combat.XuanlingTeam import XuanlingTeam
from src.combat.DetonationTeam import DetonationTeam
from src.task.CharacterMaterialTask import (CharacterMaterialTask, USE_CURRENT_TARGET,
                                           CULTIVATION_TARGET, FALLBACK_STAGE_NAME)
from src.task.MaterialRunBudget import MaterialRunBudget
from src.task.MaterialRunUI import MaterialRunUI
from src.task.MaterialWorkflow import MaterialWorkflow
from src.task.VerifiedDomainCombat import VerifiedDomainCombat, DomainBattleFailed


class SafeMaterialTask(MaterialWorkflow, DetonationTeam, XuanlingTeam, VerifiedDomainCombat, MaterialRunUI, CharacterMaterialTask):
    expected_target = ''
    exact_stage = ''
    run_limit = None
    reserve_limit = None
    phase = 'loop'
    result = None
    shared_budget = None
    plan_job = None

    def next_frame(self):
        # macOS sends game input only to the foreground app. A chat or system
        # notification can take focus mid-combo while capture keeps showing the
        # boss, making every skill press look like a combat failure.
        if getattr(self, '_verified_battle', False):
            interaction = getattr(getattr(self, 'executor', None), 'interaction', None)
            window = getattr(interaction, 'mac_window', None)
            if window is not None and not window.is_foreground():
                self.mouse_up()
                self.held_attack_interrupted = True
                if not window.bring_to_front():
                    raise DomainBattleFailed('战斗中游戏失去前台且无法恢复')
                self.log_info('Battle focus restored before next input')
        return super().next_frame()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = 'Bounded Character Materials'
        self.description = 'Stage recovery, verified reward multipliers and in-place waveplate refills.'
        self.default_config.update({'Maximum runs': 2, 'Maximum reserve waveplates': 0,
                                    'Maximum recovery attempts': 1,
                                    CULTIVATION_TARGET: '弗洛洛', FALLBACK_STAGE_NAME: '旋雾之森'})
        self.config_description.update({
            'Maximum runs': 'Single claims per run (1–20); each costs exactly 40 waveplates.',
            'Maximum reserve waveplates': 'Verified reserve allowance (0–240), refilled in place during settlement.',
            'Maximum recovery attempts': 'Leave, heal at a beacon, then retry at most 0–3 times.',
            FALLBACK_STAGE_NAME: 'Required exact stage name; no substitute stage is allowed.',
            CULTIVATION_TARGET: 'Required exact current in-game cultivation target; stops if it changed.',
        })

    def run(self):
        self.result = {'status': 'running', 'phase': self.phase, 'battles': []}
        settings = getattr(self, 'config', {})
        runs = self.run_limit if self.run_limit is not None else int(settings.get('Maximum runs', 2))
        reserve = self.reserve_limit if self.reserve_limit is not None else int(settings.get('Maximum reserve waveplates', 0))
        no_claim = self.phase not in ('loop', 'claim')
        budget = self.shared_budget or MaterialRunBudget(runs, 0 if no_claim else runs * 40,
                                   0 if no_claim else reserve,
                                   int(settings.get('Maximum recovery attempts', 1)))
        if self.phase == 'claim' and getattr(self, '_plan_boss', False):
            budget.claim_cost = 60
            budget.max_stamina = runs * 60
        self.expected_target = self.expected_target or settings.get(CULTIVATION_TARGET, '')
        self.exact_stage = self.exact_stage or settings.get(FALLBACK_STAGE_NAME, '')
        self._run_budget = budget
        try:
            if self.phase != 'solvent-reconcile':
                self.assert_no_pending_refill()
            if self.phase == 'stamina-read':
                self.result.update(status='read_only', stamina=self.get_stamina())
                return
            if self.phase == 'menu-return':
                self.return_to_world()
                self.result.update(status='world_verified')
                return
            if self.phase == 'weekly-inspect':
                import cv2
                from src.task.CultivationTargetUI import material_action, viewport
                self.return_to_world()
                self.open_materials_book()
                self.ensure_cultivation_target(self.expected_target)
                from src.task.TeamMaterialTask import TeamMaterialTask
                TeamMaterialTask.reset_material_list_top(self)
                rows = self.ocr(box=viewport(self, .25, .14, .99, .90))
                action = material_action(rows, '周本', self.width, self.height)
                self.click_box(action, after_sleep=1)
                self.next_frame()
                cv2.imwrite('logs/weekly-entry-before-level.png', self.frame)
                self.log_info('weekly destination OCR: ' + repr([b.name for b in self.ocr(0, 0, 1, 1)]))
                level = self.menu_text(r'推荐等级90', (0, .5, .3, .65), timeout=3)
                if not level:
                    raise RuntimeError('周本推荐等级90未确认')
                self.click_box(level, after_sleep=.5)
                self.next_frame()
                cv2.imwrite('logs/weekly-entry-inspect.png', self.frame)
                self.result.update(status='inspected', text=[b.name for b in self.ocr(0, 0, 1, 1)])
                self.return_to_world()
                return
            if self.phase == 'recipe-audit':
                import cv2
                import re
                import json
                from pathlib import Path
                from src.task.CultivationTargetUI import viewport
                self.focus_material_menu()
                if not self.menu_text(r'纯化', (0,0,.2,.12), timeout=2):
                    raise RuntimeError('纯化配方页未确认')
                records = []
                entries = [('改造镣环', r'改造镣环')] if self.exact_stage == 'ring-recipe' else [
                    ('柔板涡流',r'柔板涡流'), ('中频啸叫声核',r'中频啸叫.*'),
                    ('中频呓语声核',r'中频[呓吃]语.*'), ('断续的弦线',r'断续的弦线')]
                for name, pattern in entries:
                    boxes = self.ocr(box=viewport(self, .08,.10,.45,.88))
                    candidates = [b for b in boxes if re.fullmatch(pattern,b.name)]
                    if len(candidates)!=1:
                        records.append({'name':name,'error':'配方格未唯一识别'}); continue
                    self.click_box(candidates[0], after_sleep=.6)
                    words = [b.name for b in self.ocr(box=viewport(self,.60,.08,.99,.9))]
                    records.append({'name':name,'text':words})
                    cv2.imwrite(f'logs/recipe-{name}.png',self.frame)
                    if self.exact_stage == 'ring-recipe':
                        self.click(self.width*.958,self.height*.27,after_sleep=.6)
                        records.append({'name':'特制镣环','text':[b.name for b in self.ocr(box=viewport(self,.60,.08,.99,.9))]})
                        cv2.imwrite('logs/recipe-特制镣环.png',self.frame)
                Path('logs/ring-crafting-recipes.json' if self.exact_stage == 'ring-recipe' else 'logs/crafting-recipes-audit.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
                self.result.update(status='recipes_inspected',recipes=records)
                return
            if self.phase == 'synthesis-recipe-inspect':
                import cv2
                import re
                from src.task.CultivationTargetUI import viewport
                self.return_to_world()
                self.open_materials_book()
                self.ensure_cultivation_target(self.expected_target)
                if self.exact_stage == 'ring-recipe':
                    from src.task.TeamMaterialTask import TeamMaterialTask
                    TeamMaterialTask.reset_material_list_top(self)
                counters = self.ocr(box=viewport(self, .55, .15, .82, .90), target_height=self.height*3)
                denominator = 13 if self.exact_stage == 'ring-recipe' else 15
                candidates = [b for b in counters if re.fullmatch(r'\d+[/／]'+str(denominator), b.name)]
                if not candidates:
                    raise RuntimeError('今汐蓝色材料计数未找到，未打开合成')
                badge = min(candidates, key=lambda b: b.x)
                self.click(badge.x + badge.width/2, badge.y-self.height*.025, after_sleep=.5)
                button = self.menu_text(r'合成[-－—]?纯化', (.35,.2,.68,.9), timeout=3, viewport=True)
                if not button:
                    raise RuntimeError('合成-纯化来源未确认')
                self.click_box(button, after_sleep=1)
                self.next_frame()
                if self.exact_stage == 'ring-recipe':
                    import json
                    from pathlib import Path
                    button = self.menu_text(r'基准镣环',(.08,.1,.45,.88),timeout=3,viewport=True)
                    if not button:
                        raise RuntimeError('基准镣环配方未找到')
                    self.click_box(button,after_sleep=.6)
                    records=[]
                    for i in range(3):
                        self.next_frame()
                        cv2.imwrite(f'logs/ring-recipe-{i}.png',self.frame)
                        records.append([b.name for b in self.ocr(box=viewport(self,.63,.08,.98,.70),target_height=self.height*2)])
                        if i<2:
                            self.click(self.width*.958,self.height*.27,after_sleep=.6)
                    Path('logs/material-status/ring-recipes.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
                cv2.imwrite('logs/synthesis-recipe-inspect.png', self.frame)
                self.result.update(status='recipe_inspected', text=[b.name for b in self.ocr(0,0,1,1)])
                return
            if self.phase == 'synthesis-inspect':
                import cv2
                self.return_to_world()
                self.open_materials_book()
                self.ensure_cultivation_target(self.expected_target)
                button = self.menu_text(r'可补齐', (.85, .17, .99, .24), timeout=3)
                if not button:
                    raise RuntimeError('第一行材料补齐入口未确认')
                self.click_box(button, after_sleep=1)
                self.next_frame()
                cv2.imwrite('logs/synthesis-inspect.png', self.frame)
                self.result.update(status='inspected', text=[b.name for b in self.ocr(0, 0, 1, 1)])
                return
            if self.phase == 'cultivation-inspect':
                import cv2
                self.focus_material_menu()
                button = self.menu_text(r'培养方案', (.7, 0, .9, .12), timeout=3)
                if not button:
                    raise RuntimeError('角色培养方案入口未确认')
                self.click_box(button, after_sleep=2)
                self.next_frame()
                cv2.imwrite('logs/cultivation-inspect.png', self.frame)
                self.result.update(status='inspected', text=[b.name for b in self.ocr(0, 0, 1, 1)])
                return
            if self.phase == 'hud-diagnostic':
                import cv2
                from src.combat.PortraitHealth import portrait_health
                self.next_frame()
                self.result.update(
                    status='read_only',
                    team=self.in_team(),
                    portraits=portrait_health(self.frame),
                    hp=self.read_current_hp(),
                    team_text_matches={name: bool(self.find_one(name, threshold=.8,
                        horizontal_variance=.08, vertical_variance=.08))
                        for name in ('char_1_text', 'char_2_text', 'char_3_text')},
                )
                cv2.imwrite('logs/hud-diagnostic.png', self.frame)
                return
            if self.phase == 'solvent-reconcile':
                self.result.update(status='solvent_reconciled', stamina=self.reconcile_solvent())
                return
            if self.phase == 'refill-inspect':
                self.return_to_world()
                self.send_key('m', after_sleep=1)
                self.get_stamina()
                self.click_relative(.839, .059, after_sleep=.5)
                if not self.menu_text(r'补充结晶波片', (.2, .1, .75, .3)):
                    raise RuntimeError('refill menu missing')
                self.focus_material_menu()
                self.click(self.width_of_screen(1) * .497, self.height_of_screen(1) * .44, after_sleep=1)
                import cv2
                self.next_frame()
                cv2.imwrite('logs/refill-inspect.png', self.frame)
                self.result['menu'] = [b.name for b in self.ocr(0, 0, 1, 1)]
                self.result['status'] = 'inspected'
                return
            if self.phase == 'claim':
                self.focus_material_menu()
                if self.reward_dialog_visible(timeout=1):
                    self.send_key('esc', after_sleep=.6)
                if not self.wait_until(lambda: (self.in_realm() or
                        getattr(self, '_plan_boss', False) and self.in_team()[0])
                        and self.find_treasure_icon(),
                                       time_out=5, raise_if_not_found=False):
                    import cv2
                    cv2.imwrite('logs/claim-verification-failed.png', self.frame)
                    raise RuntimeError('completed domain reward not verified')
                self.claim_one_reward(budget)
                self.leave_verified_domain()
                self.heal_at_beacon()
                self.result['status'] = 'claimed_and_healed'
                return
            if self.phase == 'recover':
                self.focus_material_menu()
                # Recovery may be started from the cultivation page after a
                # failed plan. Only invoke domain exit when no known menu is
                # open; domain exit otherwise waits for a world that cannot
                # appear while the menu remains on screen.
                if not self.menu_text(r'素材获取|材料获取|终端|Terminal',
                                      (0, 0, .2, .15), timeout=.5):
                    self.leave_verified_domain()
            if self.phase in ('team', 'heal', 'recover'):
                self.return_to_world()
            if self.phase == 'team':
                self.load_chars()
                self.result['team'] = [{'name': c.char_name, 'confidence': c.confidence} for c in self.chars if c]
                self.result['current_hp'] = self.read_current_hp()
                if self.get_current_char().char_name == 'char_suisui':
                    self.result['suisui_features'] = {
                        name: float(box.confidence) if (box := self.find_one(name, threshold=.75)) else None
                        for name in ('suisui_e1', 'suisui_forte2', 'suisui_forte3')}
                if len(self.result['team']) != 3 or any(c['name'] == 'unknown' for c in self.result['team']):
                    raise RuntimeError('team not fully recognized')
                self.result['status'] = 'team_verified'
                return
            if self.phase in ('heal', 'recover'):
                self.heal_at_beacon()
                self.result['status'] = 'healed'
                return
            self.run_material_workflow(budget)
        except Exception as exc:
            if getattr(self, '_workflow_stage', None):
                self.result['failure_stage'] = self._workflow_stage
                if getattr(self, '_executor', None) is not None:
                    self.info_set('停止阶段', self._workflow_stage)
                    self.info_set('停止原因', str(exc))
                    self.info_set('消费待核对', '是，禁止重复消费' if budget.claim_pending
                                  or self.refill_pending_path.exists() else '否')
                self.set_workflow_stage('已停止', str(exc))
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            self.result['budget'] = asdict(budget)
            self._verified_battle = self._in_combat = False
            try:
                self.mouse_up()
                for key in ('w', 'a', 's', 'd', 'shift'):
                    self.send_key_up(key)
            finally:
                # Executor cancellation can reject even a key-up operation.
                # The launcher also releases inputs directly through the backend.
                self._stop_combat_debug_frame_recorder(log_result=False)
                self.save_run_report()

    def save_run_report(self):
        folder = Path(__file__).resolve().parents[2] / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        report = json.dumps(self.result, ensure_ascii=False, indent=2) + '\n'
        (folder / 'material-latest.json').write_text(report)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        (folder / f'material-{stamp}.json').write_text(report)
