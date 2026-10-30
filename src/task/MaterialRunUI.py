"""Verified menu actions used by the bounded material workflow."""
import re
import time
import cv2
from src.task.MaterialSettlement import MaterialSettlement
from src.task.MaterialRefillUI import MaterialRefillUI
from src.task.MaterialRewardUI import MaterialRewardUI
from src.task.MaterialEntryUI import MaterialEntryUI


class MaterialRunUI(MaterialEntryUI, MaterialRefillUI, MaterialRewardUI, MaterialSettlement):
    def return_to_world(self):
        self.focus_material_menu()
        for _ in range(5):
            if self.in_team_and_world():
                return
            detail = self.menu_text(r'点击空白区域关闭', (.30,.85,.72,.96), timeout=.3)
            if detail:
                self.click(self.width*.70,self.height*.92,after_sleep=.4)
                continue
            warning = self.read_material_entry_warning()
            if warning:
                self.focus_material_menu()
                warning = self.read_material_entry_warning()
                if not warning:
                    raise RuntimeError('入场提示变化，未发送取消')
                self.click_box(warning[0], after_sleep=.5)
                continue
            known = self.wait_guidebook_page(time_out=.5) or self.menu_text(
                r'补充结晶波片|兑换结晶波片|探索度.*|选择培养目标|属性详情|纯化|合成', (0, 0, .75, .3), timeout=.5)
            known = known or self.menu_text(r'兑换结晶波片|补充结晶波片', (.2, .1, .75, .3), timeout=1)
            known = known or self.menu_text(r'素材获取|材料获取|终端|Terminal', (0, 0, .2, .15), timeout=.5)
            known = known or self.menu_text(r'定序诸理之律', (0, 0, .23, .15), timeout=.5)
            known = known or self.menu_text(r'静心座', (.68, 0, .95, .15), timeout=.5)
            known = known or self.menu_text(
                r'单人挑战|开启挑战', (.70, .85, 1, 1), timeout=.5)
            if not known:
                cv2.imwrite('logs/unknown-menu.png', self.frame)
                self.log_info(f'unknown menu title OCR: {self.ocr(0, 0, .3, .15)}')
                break
            self.send_key('esc', after_sleep=1)
        self.ensure_main(time_out=15)

    def focus_material_menu(self):
        window = getattr(self.executor.interaction, 'mac_window', None)
        if window is not None:
            if not window.bring_to_front():
                raise RuntimeError('游戏无法取得前台，未发送菜单操作')
            self.sleep(.6)
            window.do_update_window_size()
            if not window.is_foreground():
                raise RuntimeError('游戏前台未确认，未发送菜单操作')

    def menu_text(self, pattern, region=(0, 0, 1, 1), timeout=4, viewport=False):
        expression = re.compile(pattern)
        def find():
            if viewport:
                from src.task.CultivationTargetUI import viewport as view_box
                boxes = self.ocr(box=view_box(self, *region))
            else:
                boxes = self.ocr(*region)
            matches = [b for b in boxes
                       if expression.fullmatch(re.sub(r'\s+', '', b.name).translate(str.maketrans('兌換', '兑换')))]
            return matches[0] if len(matches) == 1 else None
        return self.wait_until(find, time_out=timeout, raise_if_not_found=False)

    def menu_click(self, pattern, region=(0, 0, 1, 1), timeout=4):
        box = self.menu_text(pattern, region, timeout)
        if not box:
            raise RuntimeError(f'menu action not uniquely verified: {pattern}')
        self.click_box(box, after_sleep=.6)

    def read_current_hp(self):
        box = self.box_of_screen(.44, .9528, .56, .9667, hcenter=True)
        # The small HP line touches the crop edge. Padding lets the text
        # detector see a complete line; returned boxes are never clicked.
        frame = getattr(self, 'frame', None)
        self._hp_observation_frame = frame.copy() if frame is not None else None
        readings = self.ocr(box=box, threshold=.85, frame=self._hp_observation_frame,
                            frame_processor=self.pad_hp_text)
        self._hp_observation = {'monotonic': time.monotonic(),
                                'raw': [item.name for item in readings], 'parsed': None,
                                'capture_sequence': getattr(getattr(getattr(self, '_executor', None), 'method', None), '_delivered_frame_sequence', None),
                                'crop': {key: getattr(box, key, None) for key in ('x', 'y', 'width', 'height')}}
        known_totals = getattr(self, '_known_hp_totals', set())
        portrait_checked, active_bar = False, None

        def portrait_ratio():
            nonlocal portrait_checked, active_bar
            if not portrait_checked:
                portrait_checked = True
                team_reader = getattr(self, 'in_team', None)
                if self._hp_observation_frame is not None and callable(team_reader):
                    from src.combat.PortraitHealth import portrait_health
                    team, slot, *_ = team_reader()
                    bars = portrait_health(self._hp_observation_frame)
                    self._hp_observation.update(team_verified=team, slot_at_decision=slot,
                                                portrait_ratios=bars)
                    if team and 0 <= slot < len(bars):
                        active_bar = bars[slot]
            return active_bar

        def repair_supported(current, total):
            if not 0 <= current <= total or total <= 0:
                return False
            if total in known_totals:
                return True
            # Equal digits on both sides of a damaged separator alone are not
            # enough: the current slot's bar in this same saved frame must agree.
            bar = portrait_ratio()
            return current == total and bar is not None and bar >= .98

        for item in readings:
            raw = re.sub(r'\s+', '', item.name)
            match = re.fullmatch(r'([0-9]{1,6})[/／|]([0-9]{3,6})[.．。]?', raw)
            if match and len(match[2]) == 6 and int(match[2]) not in known_totals:
                current, total = map(int, match.groups())
                bar = portrait_ratio()
                if total <= 0 or bar is None or abs(current / total - bar) > .05:
                    # OCR can retain a slash and also prefix the denominator
                    # with its mistaken "1"/"7". Do not learn that inflated max.
                    suffix = int(match[2][1:])
                    match = ((current, suffix) if match[2][0] in '17'
                             and repair_supported(current, suffix) else None)
            if not match and raw.isdecimal() and 7 <= len(raw) <= 13:
                # At this HUD size OCR can turn the slash into a 1 or 7.
                # Require a known maximum or independently corroborated equal
                # full-HP digits; never replace a low numerator with the max.
                candidates = [(int(raw[:split]), int(raw[split + 1:]))
                              for split in range(1, min(7, len(raw) - 2))
                              if raw[split] in '17'
                              and repair_supported(int(raw[:split]), int(raw[split + 1:]))]
                if len(candidates) == 1:
                    match = candidates[0]
            if match:
                current, total = match if isinstance(match, tuple) else map(int, match.groups())
                if 0 <= current <= total and total > 0:
                    self._known_hp_totals = known_totals | {total}
                    self._hp_observation['parsed'] = [current, total]
                    if isinstance(match, tuple):
                        self._hp_observation['repaired_separator'] = True
                    return current, total
        self.log_info(f'HP OCR unreadable: {[b.name for b in readings]}')
        return None

    @staticmethod
    def pad_hp_text(image):
        # Framework target_height only downsamples; explicitly enlarge the
        # 14–20 px HUD text before detection. No coordinate result is used.
        scale = max(1, 60 / image.shape[0])
        image = cv2.resize(image, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_CUBIC)
        return cv2.copyMakeBorder(image, 25, 25, 30, 30,
                                  cv2.BORDER_CONSTANT, value=(245, 245, 245))

    def heal_at_beacon(self, *, force_teleport=False, verify_before=True):
        """Teleport through a verified beacon and confirm all three members' HP.

        ``force_teleport`` prevents a healthy team from skipping the retreat.
        ``verify_before=False`` requires the world HUD immediately and avoids
        menu recovery, login handling and party switches before opening the map.
        The caller owns foreground/fresh-frame guards and the recovery budget.
        Health verification after teleport is required in every mode.
        """
        if self.in_realm():
            raise RuntimeError('must leave domain before healing')
        if verify_before:
            self.ensure_main()
            if self.verify_team_health() and not force_teleport:
                self.log_info('all three members already healthy; no teleport needed')
                return
        elif not self.in_team_and_world():
            raise RuntimeError('world HUD required before direct beacon recovery')
        self.send_key('m', after_sleep=1)
        point = self.stable_map_waypoint()
        if not point:
            raise RuntimeError('no verified waypoint visible on map')
        cv2.imwrite('logs/healing-waypoint-before-click.png', self.frame)
        self.log_info(f'healing waypoint: {point}')
        self.click_box(point, after_sleep=.7)
        self.next_frame()
        cv2.imwrite('logs/healing-waypoint-after-click.png', self.frame)
        if not self.menu_text(r'快速旅行|FastTravel', (.65, .7, 1, 1), timeout=1):
            self.menu_click(r'小型信标|中枢信标|共鸣信标|共鸣枢纽|ResonanceBeacon|ResonanceNexus', (.45, .1, 1, .85))
        self.menu_click(r'快速旅行|FastTravel', (.65, .7, 1, 1))
        self.wait_in_team_and_world(time_out=60)
        self.sleep(2)
        if not self.verify_team_health():
            raise RuntimeError('team healing not verified after teleport')

    def verify_team_health(self):
        health = []
        for key in ('1', '2', '3'):
            self.send_key(key, after_sleep=.8)
            if not self.wait_until(lambda: self.in_team()[1] == int(key) - 1,
                                   post_action=lambda: self.send_key(key, after_sleep=.2),
                                   time_out=4, raise_if_not_found=False):
                # A dead member can open an item revival overlay. Dismiss only
                # that known overlay, then use the beacon instead of repeatedly
                # trying to switch to a member who cannot take the field.
                if self.menu_text(r'选择复苏物品', timeout=.5):
                    self.send_key('esc', after_sleep=.5)
                    if self.menu_text(r'选择复苏物品', timeout=.5):
                        raise RuntimeError('复苏窗口未关闭；不使用复苏物品')
                if not self.in_team_and_world():
                    raise RuntimeError(f'healing slot switch not verified: {key}; world HUD missing')
                self.log_info(f'slot {key} unavailable in verified world; beacon recovery required')
                return False
            self.next_frame()
            hp = self.wait_until(self.read_current_hp, time_out=3, raise_if_not_found=False)
            if not hp or hp[0] < hp[1] * .98:
                self.log_info(f'healing needed or HP unreadable for slot {key}: {hp}')
                return False
            health.append(hp)
        self.log_info(f'healed all team members: {health}')
        return True

    def stable_map_waypoint(self):
        previous, stationary_since = None, 0
        def settled():
            nonlocal previous, stationary_since
            candidates = []
            # This beacon shape differs from the older map's COCO templates.
            # Prefer its complete icon over a coincidental outline match.
            point = self.live_map_beacon(self.frame)
            if point:
                candidates.append(point)
            for name in ('map_way_point', 'map_way_point_big'):
                if point:
                    break
                candidates.extend(self.find_feature(name,
                    box=self.box_of_screen(.05, .1, .95, .92, hcenter=True),
                    threshold=.75, limit=20))
            candidates = [p for p in candidates if self.waypoint_has_active_color(self.frame, p)]
            point = max(candidates, key=lambda p: p.confidence, default=None)
            now = time.monotonic()
            if not point:
                previous = None
                return None
            same = (previous and point.name == previous.name
                    and abs(point.x - previous.x) <= 3
                    and abs(point.y - previous.y) <= 3)
            if not same:
                stationary_since = now
            previous = point
            return point if same and now - stationary_since >= .4 else None
        return self.wait_until(settled, time_out=5, raise_if_not_found=False)

    @staticmethod
    def live_map_beacon(frame):
        from pathlib import Path
        from ok import Box
        image_dir = Path(__file__).resolve().parents[2] / 'assets/images'
        height, width = frame.shape[:2]
        scale = height / 1080
        x, y = round(width*.05), round(height*.1)
        # Include complete lower-map icons; retain the original score/color gates.
        region = frame[y:round(height*.92), x:round(width*.95)]
        candidates = []
        for kind in ('beacon', 'nexus'):
            template = cv2.imread(str(image_dir / f'map-{kind}-huanglong-1920.png'))
            if template is None:
                continue
            template = cv2.resize(template, None, fx=scale, fy=scale)
            if any(a < b for a, b in zip(region.shape[:2], template.shape[:2])):
                continue
            scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(scores)
            if score < .82:
                continue
            point = Box(location[0]+x, location[1]+y, template.shape[1], template.shape[0],
                        confidence=score, name=f'map_{kind}_huanglong')
            if MaterialRunUI.waypoint_has_active_color(frame, point):
                candidates.append(point)
        return max(candidates, key=lambda point: point.confidence, default=None)

    @staticmethod
    def waypoint_has_active_color(frame, point):
        """Reject beige map markers that resemble a beacon's outline."""
        crop = frame[max(0, int(point.y)):int(point.y + point.height),
                     max(0, int(point.x)):int(point.x + point.width)]
        if not crop.size:
            return False
        b, g, r = cv2.split(crop.astype('int16'))
        cyan = (b > 130) & (g > 110) & (b-r > 35) & (g-r > 15)
        return float(cyan.mean()) >= .035

    def leave_verified_domain(self):
        self._verified_battle = self._in_combat = False
        # Revival overlays hide the party HUD used by in_realm(). Dismiss
        # the verified overlay before checking domain state, without using items.
        if self.menu_text(r'选择复苏物品', timeout=.5):
            self.send_key('esc', after_sleep=.7)
            if self.menu_text(r'选择复苏物品', timeout=.5):
                raise RuntimeError('复苏物品窗口未关闭；不点击物品确认')
        if self.menu_text(r'确认离开|ConfirmLeave', (.2, .2, .8, .75), timeout=.5):
            self.menu_click(r'确认|Confirm', (.5, .5, .8, .8))
        elif self.menu_text(r'退出副本|ExitDomain', (.2, .7, .7, 1), timeout=1):
            # Settlement labels appear before the exit button accepts input.
            # Retry only this verified non-spending exit while it remains.
            for _ in range(3):
                self.sleep(1)
                button = self.menu_text(r'退出副本|ExitDomain', (.2, .7, .7, 1), timeout=.5)
                if not button:
                    break
                self.click_box(button, after_sleep=1)
        elif self.in_realm() or (getattr(self, '_plan_boss', False)
                                 and self.in_team()[0] and self.find_treasure_icon()):
            if self.find_one('revive_confirm_hcenter_vcenter', threshold=.8):
                self.close_revive_popup()
            self.send_key('esc', after_sleep=.7)
            if not self.menu_text(r'确认离开|ConfirmLeave', (.2, .2, .8, .75)):
                raise RuntimeError('leave-domain dialog not verified')
            self.menu_click(r'确认|Confirm', (.5, .5, .8, .8))
        # The party HUD can remain visible before the loading screen starts.
        # Require the overworld icon, rather than accepting that stale HUD.
        def overworld_verified():
            earth = self.find_world_earth_icon()
            return bool(earth and self.in_team()[0] and not self.in_realm())
        # Live boss exits can spend over a minute on the loading screen.
        if not self.wait_until(overworld_verified, time_out=120, raise_if_not_found=False):
            cv2.imwrite('logs/overworld-verification-failed.png', self.frame)
            raise RuntimeError('返回大世界未确认；不继续刷取或领奖')
        self.sleep(1)
        if self.in_realm():
            raise RuntimeError('domain exit not verified')
