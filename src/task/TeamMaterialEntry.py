"""Entry adapters for exact material rows, including direct boss challenges."""
import re


class MapRouteSkipped(RuntimeError):
    """The material leads to map travel, which this run may leave for later."""


class TeamMaterialEntry:
    def preflight_material_job(self):
        # Only cultivation-linked weekly entrances verified in game are enabled.
        if (self.plan_job and self.plan_job['kind'] == '周本'
                and self.plan_job['target'] not in ('心', '卜灵')):
            raise RuntimeError('周本适配尚未验证；在补充储备和进场前停止，保留本项进度')
        if self.plan_job:
            from src.task.CultivationTargetUI import material_action, viewport, required_jobs, NoCurrentMaterialNeed, supplement_weekly_counts
            if not self.material_target_matches(self.expected_target):
                raise RuntimeError('补充储备前培养目标校验失败')
            self.reset_material_list_top()
            for attempt in range(3):
                boxes = self.ocr(box=viewport(self, .25, .15, .99, .90), target_height=self.height*2)
                boxes = supplement_weekly_counts(self, boxes)
                material_action(boxes, self.plan_job['kind'], self.width, self.height)
                observed = [job for job in required_jobs(boxes, self.expected_target, self.width)
                            if job['kind'] == self.plan_job['kind'] and job['repeat'] == self.plan_job['repeat']]
                if len(observed) == 1 and observed[0].get('material_counts'):
                    break
                if attempt < 2:
                    self.sleep(.3)
                    self.next_frame()
            if len(observed) != 1 or not observed[0].get('material_counts'):
                raise RuntimeError('补充体力前材料数量未确认')
            if observed[0]['satisfied']:
                raise NoCurrentMaterialNeed('该材料当前持有量已达到培养需求')
            if self.plan_job['kind'] == '突破':
                self.inspect_boss_material(boxes)

    def inspect_boss_material(self, boxes):
        """Read the cultivation-linked item image before choosing a boss."""
        import cv2
        from src.task.CultivationTargetUI import material_action, viewport
        from src.combat.MaterialBossProfiles import resolve_boss_profile
        action = material_action(boxes, '突破', self.width, self.height)
        x, y = self.boss_material_tile(boxes, action, self.width, self.height)
        self.click(x, y, after_sleep=.5)
        try:
            def read_detail():
                found = self.ocr(box=viewport(self, .36, .12, .66, .85))
                text = ''.join(b.name for b in found)
                return found if '共鸣者突破材料' in text and '掉落物' in text else None
            detail = self.wait_until(read_detail, time_out=4, raise_if_not_found=False)
            if not detail:
                cv2.imwrite('logs/boss-material-detail-unverified.png', self.frame)
                raise RuntimeError('材料图像详情未确认；不进入 Boss')
            text = ''.join(b.name for b in detail)
            profile = resolve_boss_profile(text)
            if profile is None or not profile.supported:
                raise RuntimeError(f'材料掉落来源未唯一核对：{text}')
            title = next((b.name for b in sorted(detail, key=lambda b: b.y)
                          if b.name not in ('共鸣者突破材料',) and b.y < self.height * .19), '')
            self._material_boss_source = {'item': title, 'boss_key': profile.key,
                                          'detail': text}
            self.plan_job['material_source'] = dict(self._material_boss_source)
            cv2.imwrite('logs/verified-boss-material.png', self.frame)
            self.log_info(f'材料图像来源已核对：{title} → {profile.key}')
        finally:
            self.click(self.width * .70, self.height * .92, after_sleep=.3)
        if not self.wait_until(lambda: self.material_target_matches(self.expected_target),
                               time_out=3, raise_if_not_found=False):
            raise RuntimeError('材料详情关闭后培养目标未确认')

    @staticmethod
    def boss_material_tile(boxes, action, width, height):
        """Locate the single item above the count in the observed boss row."""
        row_y = action.y + action.height / 2
        counts = [b for b in boxes if re.fullmatch(r'\d+[/／]\d+', re.sub(r'\s+', '', b.name))
                  and width * .65 < b.x < action.x
                  and abs(b.y + b.height / 2 - row_y) < height * .055]
        if len(counts) != 1:
            raise RuntimeError('突破材料图标位置未唯一确认')
        count = counts[0]
        return count.x + count.width / 2, count.y - height * .025


    def enter_character_material_domain(self, route):
        kind = self.plan_job['kind']
        if kind in ('武器/技能', '突破', '周本', '角色经验', '武器经验', '贝币'):
            from src.task.CultivationTargetUI import material_action, viewport
            if not self.material_target_matches(self.expected_target):
                raise RuntimeError('前往材料前培养目标校验失败')
            boxes = self.ocr(box=viewport(self, .25, .15, .99, .90), target_height=self.height*2)
            action = material_action(boxes, kind, self.width, self.height)
            self.click_box(action, after_sleep=1)
            self._plan_boss = kind in ('突破', '周本')
            if kind == '周本':
                weekly = {'心': ('天演溯心', 'tianyansuxin'),
                          '卜灵': (r'战歌重奏[·・]烬夜天启', 'leviathan')}
                title, key = weekly[self.expected_target]
                if not self.menu_text(title, (.4, .04, 1, .35), timeout=3):
                    raise RuntimeError(f'{self.expected_target}的周本{title}入口未确认')
                self._material_boss_source = {'boss_key': key}
                level = self.menu_text(r'推荐等级90', (0, .5, .3, .65), timeout=3)
                if not level:
                    raise RuntimeError(f'{self.expected_target}的周本推荐等级90未确认')
                self.click_box(level, after_sleep=.5)
            solo = self.menu_text(r'单人挑战|SoloChallenge', (.7, .75, 1, 1), timeout=3)
            if solo:
                if kind == '周本':
                    # The weekly button is centered farther left than the
                    # generic guidebook Solo OCR region.
                    self.click_box(solo, after_sleep=1)
                return self.finish_domain_destination(True)
            destination = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'team_close'],
                                            time_out=5, raise_if_not_found=False)
            if not destination:
                raise RuntimeError('材料前往后的挑战或传送页面未确认')
            if (getattr(self, 'skip_map_routes', False) and kind not in ('突破', '周本')
                    and destination.name != 'team_close'):
                raise MapRouteSkipped(f'{kind}需要地图传送或跑图，按本次要求跳过')
            return self.finish_domain_destination(destination.name == 'team_close')
        self.open_boss_book(route['category'])
        catalog = self.build_material_page_dictionary(route['category'], force=True)
        locations = catalog['locations']
        stage = route.get('fallback_stage_name', '')
        if kind in ('角色经验', '武器经验', '贝币') and not stage:
            # Match resource names in the verified location row, never its
            # position. A changed label requires an explicit stage setting.
            labels = {'角色经验': r'共鸣者.*经验|共鸣.*训练|ResonatorEXP',
                      '武器经验': r'武器.*经验|武器.*训练|WeaponEXP',
                      '贝币': r'贝币|ShellCredit'}
            locations = [row for row in locations if re.search(labels[kind], row['name'], re.I)]
            if len(locations) != 1:
                raise RuntimeError(f'{kind}关卡未唯一匹配；请填写已核对的完整关卡名')
        else:
            locations = self.equivalent_material_locations(locations, stage)
        ordered = self.order_material_locations(locations)
        if not ordered:
            raise RuntimeError(f"{self.expected_target}的{kind}关卡未核对成功；请在全队计划中填写完整关卡名")
        selected = ordered[0]
        self.info_set('本次关卡', selected['name'])
        self.plan_job['resolved_stage'] = selected['name']
        self._plan_boss = kind in ('突破', '周本')
        return self.enter_material_location(selected)

    def finish_domain_destination(self, is_team_page):
        if is_team_page:
            return self.start_material_team_verified()
        if not getattr(self, '_plan_boss', False) or is_team_page:
            return super().finish_domain_destination(is_team_page)
        if not self.wait_until(self.click_traval_button, time_out=10, raise_if_not_found=False):
            return False
        if not self.wait_until(lambda: self.in_team()[0], time_out=60, raise_if_not_found=False):
            raise RuntimeError('Boss 传送后的队伍界面未确认')
        self.sleep(2)
        return True

    def start_material_team_verified(self):
        """Click the observed label center; retry only an unchanged team page."""
        self._entry_warning_accepted = False
        for attempt in range(3):
            self.focus_material_menu()
            button = self.menu_text(r'开启挑战|StartChallenge',
                                    (.72, .85, .98, 1), timeout=1)
            if button:
                self.click_box(button, after_sleep=1)
                self.log_info(f'verified team start label clicked: attempt {attempt + 1}')
            elif attempt == 0:
                self.click_team_challenge()
            else:
                raise RuntimeError('开启挑战后页面未确认；未重复点击未知页面')
            self.handle_material_entry_notice(timeout=2)
            if self.wait_until(self.in_team_and_world, time_out=15,
                               raise_if_not_found=False):
                self.log_info('team start transition verified: game HUD present')
                return True
            if not self.menu_text(r'开启挑战|StartChallenge',
                                  (.72, .85, .98, 1), timeout=1):
                # Loading can take longer; observe without another click.
                if self.wait_until(self.in_team_and_world, time_out=45,
                                   raise_if_not_found=False):
                    return True
                raise RuntimeError('开启挑战后未进入副本；加载状态超时，未重复点击')
            self.log_info('team page unchanged; reacquire button before retry')
        raise RuntimeError('开启挑战三次均未切换页面；保留入口诊断')

    def prepare_verified_battle(self):
        if not getattr(self, '_plan_boss', False):
            return super().prepare_verified_battle()
        # Some direct bosses start immediately; others expose a challenge F.
        start_text = [re.compile(r'开始挑战|开启挑战|进入.*|Start Challenge')]
        for _ in range(32):
            if self.in_team()[0] and self.check_health_bar():
                # Encounter detection only. VerifiedDomainCombat separately
                # acquires a target before starting character rotations.
                return False
            if self.find_f_with_text(target_text=start_text):
                return True
            if not self.in_team()[0]:
                from src.task.VerifiedDomainCombat import DomainBattleFailed
                self.fail_battle('Boss 入口队伍界面丢失，停止移动')
            self.send_key('w', down_time=.2, after_sleep=.1)
            self.next_frame()
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        self.fail_battle('Boss 战斗或挑战入口未确认，已停止移动')
