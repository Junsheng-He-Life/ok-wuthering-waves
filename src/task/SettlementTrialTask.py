"""Supervised, non-spending tests for the guidebook's Echo settlements."""
from pathlib import Path
import time

import cv2

from src.task.EchoFarmTask import EchoFarmTask
from src.task.CharacterMaterialTask import CharacterMaterialTask
from src.task.SettlementOperator import SettlementOperator


class SettlementTrialTask(SettlementOperator, EchoFarmTask):
    echo_mode = 'settlement'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '残象聚落实机测试（不消费）'

    def save_settlement_view(self, label):
        folder = Path('logs/settlement-trial')
        folder.mkdir(parents=True, exist_ok=True)
        self.next_frame()
        path = folder / f'{time.time_ns()}-{label}.png'
        cv2.imwrite(str(path), self.frame)
        observation = {'label': label, 'image': str(path),
                       'text': [b.name for b in self.ocr(0, 0, 1, 1)]}
        self.result.setdefault('observations', []).append(observation)
        self.save_echo_progress()
        return observation

    def catalog_echoes(self):
        self.return_to_world()
        self.load_chars()
        if len(self.chars) != 3 or any(not c or c.char_name == 'unknown' or c.confidence < .8
                                       for c in self.chars):
            raise RuntimeError('聚落测试前当前队伍未完整识别')
        self.result['team'] = [c.char_name for c in self.chars]
        self.open_materials_book()
        self.open_boss_book('canxiang')
        def observe(visible, indexed):
            self.save_settlement_view('catalog')
            return None
        catalog = self.build_material_page_dictionary('canxiang', force=True, visible_selector=observe)
        self.result['locations'] = [{k: v for k, v in row.items() if k != 'action_box'}
                                    for row in catalog['locations']]
        self.result['status'] = 'settlement_catalog_no_spending'
        self.return_to_world()

    def run_settlement_trial(self):
        if not self.exact_stage or not self.exact_stage.endswith('残象聚落'):
            raise ValueError('聚落测试需要扫描得到的完整名称')
        self.claim_enabled = self._plan_boss = False
        if self.phase == 'settlement-travel':
            self.focus_material_menu()
            travel_notice = r'是否快速旅行至附近信标并追踪目标[？?]?'
            if not self.menu_text(travel_notice, (.25, .35, .75, .55), timeout=.5):
                if not self.menu_text(self.exact_stage, (.68, 0, 1, .15), timeout=2):
                    raise RuntimeError('聚落地图详情与指定名称不一致')
                self.menu_click(r'前往', (.82, .88, 1, 1), timeout=2)
                self.sleep(1)
            self.save_settlement_view('after-go')
            if (self.menu_text(travel_notice, (.25, .35, .75, .55), timeout=2)
                    and self.menu_text(r'提示', (.2, .25, .4, .4), timeout=.5)
                    and self.menu_text(r'取消', (.25, .55, .45, .7), timeout=.5)):
                self.menu_click(r'确认', (.55, .55, .75, .7), timeout=1)
                self.wait_in_team_and_world(time_out=120)
                self.save_settlement_view('arrival')
                self.result['status'] = 'settlement_arrived_no_spending'
                return
            travel = self.menu_text(r'快速旅行|FastTravel', (.65, .7, 1, 1), timeout=1)
            if travel:
                self.click_box(travel, after_sleep=1)
                self.wait_in_team_and_world(time_out=120)
                self.save_settlement_view('arrival')
            self.result['status'] = 'settlement_travel_observed'
            return
        self.return_to_world()
        self.heal_at_beacon()
        # Health verification ends on slot 3. Reacquire a settled frame after
        # switching back, rather than scanning the portrait transition.
        self.send_key('1', after_sleep=.8)
        self.next_frame()
        for attempt in range(3):
            self.load_chars()
            if len(self.chars) == 3 and all(c and c.char_name != 'unknown' and c.confidence >= .8
                                           for c in self.chars):
                break
            self.save_settlement_view(f'party-unverified-{attempt}')
            self.sleep(.6)
            self.next_frame()
        else:
            raise RuntimeError('聚落入场前队伍未完整识别')
        self.result['team'] = [c.char_name for c in self.chars]
        self.result['stage'] = self.exact_stage
        self.open_materials_book()
        if not CharacterMaterialTask.enter_character_material_domain(self, {
                'category': 'canxiang', 'fallback_stage_name': self.exact_stage}):
            raise RuntimeError('指定聚落入口不可用')
        self.result['status'] = 'settlement_destination_observed'

    def finish_domain_destination(self, is_team_page):
        self.save_settlement_view('destination')
        # First test observes the actual map/track page before attempting any
        # navigation. No domain-start or reward confirmation is reused here.
        if is_team_page:
            raise RuntimeError('聚落前往意外进入组队页；停止测试')
        return True
