import math
import re
import sys
import time
from datetime import datetime, timedelta
from typing import List

import numpy as np

from ok import BaseTask, Logger, find_boxes_by_name, og, find_color_rectangles, mask_white
from ok import CannotFindException
import cv2

from src.Labels import Labels
from src.scene.WWScene import WWScene

logger = Logger.get_logger(__name__)
number_re = re.compile(r'(\d+)')
stamina_re = re.compile(r'(\d+)/(\d+)')
LOGIN_TEXTS = ["登录", re.compile('Log', re.IGNORECASE), '登入']
LOGIN_CLICK_SETTLE_TIME = 4  # seconds; keep below AutoLoginTask trigger_interval (5) so triggers don't overlap
f_white_color = {
    'r': (235, 255),  # Red range
    'g': (235, 255),  # Green range
    'b': (235, 255)  # Blue range
}
processed_feature = False
WIDE_MODE_UI_SCALE = 0.75
TEAM_UI_VARIANCE = 0.03
MAIN_WORLD_PROBE_TIMEOUT = 3
MAIN_WORLD_SETTLE_TIME = 0.25
MAIN_MAX_BACK_ATTEMPTS = 3
GUIDEBOOK_MENU_POSITION = (0.759, 0.05)
# Exclude the crossed-swords icon, which OCR can merge into the page title.
GUIDEBOOK_TITLE_BOX = (0.052, 0.0, 0.30, 0.15)
GUIDEBOOK_TITLE_TEXT = [
    re.compile(r'^索拉指南$'),
    re.compile(r'^活[跃躍]行[迹跡]$'),
    re.compile(r'^漂泊日志$'),
    re.compile(r'^漂泊日誌$'),
    re.compile(r'^周期挑战$'),
    re.compile(r'^週期挑戰$'),
    re.compile(r'^素材获取$'),
    re.compile(r'^素材獲取$'),
    re.compile(r'^(Guidebook|Activity|Milestones|Material Acquisition)$', re.IGNORECASE),
]
MATERIALS_GUIDE_POSITION = (0.039, 0.427)
MATERIALS_TITLE_BOX = (0.052, 0.00, 0.18, 0.10)
MATERIALS_TITLE_TEXT = [
    re.compile(r'^素材获取$'),
    re.compile(r'^素材獲取$'),
    re.compile(r'^Material Acquisition$', re.IGNORECASE),
]
MATERIAL_TARGET_BOX = (0.095, 0.095, 0.345, 0.205)
MATERIAL_TARGET_AVATAR_BOX = (0.102, 0.137, 0.141, 0.190)
MATERIAL_LOCATION_ACTION_BOX = (0.825, 0.185, 0.960, 0.885)
MATERIAL_LOCATION_NAME_X = (0.405, 0.760)
MATERIAL_TARGET_MARKER_X = (0.360, 0.379)
MATERIAL_DROP_PREVIEW_X = (0.695, 0.830)
MATERIAL_DROP_ICON_X = (
    (0.695, 0.748),
    (0.751, 0.806),
    (0.809, 0.830),
)
MATERIAL_LOCATION_SCROLL_X = 0.973
MATERIAL_LOCATION_SCROLL_ANCHORS = (0.195, 0.34, 0.49, 0.64, 0.79, 0.875)
MATERIAL_LOCATION_SCROLL_PROBE = (0.88, 0.72)
MATERIAL_LOCATION_SCROLL_RESET_STEP = 2
MATERIAL_LOCATION_SCROLL_RESET_ATTEMPTS = 24
MATERIAL_LOCATION_SCROLL_STEP = -2
MATERIAL_LOCATION_SCROLL_MAX_PAGES = 12
MATERIAL_LOCATION_ACTION_X = 0.895
MATERIAL_LOCATION_ACTION_TEXT = [
    re.compile(r'^前往$'),
    re.compile(r'^直接挑战$'),
    re.compile(r'^直接挑戰$'),
    re.compile(r'^(Go|Challenge)$', re.IGNORECASE),
]
MATERIAL_LOCATION_DIRECT_TEXT = ('直接挑战', '直接挑戰', 'challenge')
MATERIAL_LOCATION_UI_TEXT = (
    '筛选',
    '篩選',
    '培养目标',
    '培養目標',
    '素材获取',
    '素材獲取',
    '武器培养',
    '武器培養',
    '角色培养',
    '角色培養',
    '声骸培养',
    '聲骸培養',
    'filter',
    'developmenttarget',
    'materialacquisition',
)
SOLO_CHALLENGE_BOX = (0.79, 0.84, 0.98, 0.98)
SOLO_CHALLENGE_TEXT = [
    re.compile(r'^单人挑战$'),
    re.compile(r'^單人挑戰$'),
    re.compile(r'^(Solo Challenge|Challenge)$', re.IGNORECASE),
]
START_CHALLENGE_BOX = (0.75, 0.84, 0.98, 0.98)
START_CHALLENGE_TEXT = [
    re.compile(r'^开始挑战$'),
    re.compile(r'^開始挑戰$'),
    re.compile(r'^开启挑战$'),
    re.compile(r'^開啟挑戰$'),
    re.compile(r'^Start Challenge$', re.IGNORECASE),
]


class BaseWWTask(BaseTask):
    map_zoomed = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monthly_card_config = self.get_global_config('Monthly Card Config')
        self.char_config = self.get_global_config('Character Config')
        self.key_config = self.get_global_config('Game Hotkey')  # 游戏热键配置
        self.next_monthly_card_start = 0
        self.scene: WWScene | None = None
        self._material_page_dictionary = {}

    @property
    def logged_in(self):
        return og.my_app.logged_in

    @logged_in.setter
    def logged_in(self, value):
        og.my_app.logged_in = value

    def is_open_world_auto_combat(self):
        from src.task.AutoCombatTask import AutoCombatTask
        from src.task.TacetTask import TacetTask
        from src.task.DailyTask import DailyTask
        if isinstance(self, AutoCombatTask):
            if not self.in_realm():
                return True
        elif isinstance(self, (TacetTask, DailyTask)):
            return True
        return False

    def zoom_map(self, esc=True):
        if not self.map_zoomed:
            self.log_info('zoom map to max')
            self.map_zoomed = True
            self.send_key('m', after_sleep=1)
            self.click_relative(0.94, 0.33, after_sleep=0.5)
            if esc:
                self.send_key('esc', after_sleep=1)

    def validate(self, key, value):
        message = self.validate_config(key, value)
        if message:
            return False, message
        else:
            return True, None

    def absorb_echo_text(self, ignore_config=False):
        if self.game_lang == 'zh_CN' or self.game_lang == 'en_US' or self.game_lang == 'zh_TW':
            return re.compile(r'(吸收|Absorb)')
        else:
            return None

    @property
    def absorb_echo_feature(self):
        return self.get_feature_by_lang('absorb')

    def get_feature_by_lang(self, feature):
        lang_feature = feature + '_' + self.game_lang
        if self.feature_exists(lang_feature):
            return lang_feature
        else:
            return None

    def set_check_monthly_card(self, next_day=False):
        if self.monthly_card_config.get('Check Monthly Card'):
            now = datetime.now()
            hour = self.monthly_card_config.get('Monthly Card Time')
            # Calculate the next 4 o'clock in the morning
            next_four_am = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if now >= next_four_am or next_day:
                next_four_am += timedelta(days=1)
            next_monthly_card_start_date_time = next_four_am - timedelta(seconds=30)
            # Subtract 1 minute from the next 4 o'clock in the morning
            self.next_monthly_card_start = next_monthly_card_start_date_time.timestamp()
            logger.info('set next monthly card start time to {}'.format(next_monthly_card_start_date_time))
        else:
            self.next_monthly_card_start = 0

    @property
    def f_search_box(self):
        f_search_box = self.get_box_by_name('pick_up_f_hcenter_vcenter')
        horizontal_margin = f_search_box.width * 3
        f_search_box = f_search_box.copy(x_offset=-horizontal_margin,
                                         width_offset=horizontal_margin * 2,
                                         height_offset=f_search_box.height * 6.5,
                                         y_offset=-f_search_box.height * 5,
                                         name='search_dialog')
        return f_search_box

    def find_f_with_claim_text(self):
        return self.find_f_with_text(target_text=[re.compile('领取|領取|Claim', re.IGNORECASE)])

    def find_f_with_text(self, target_text=None):
        f = self.find_one(Labels.pick_up_f_hcenter_vcenter, box=self.f_search_box, threshold=0.8)
        if not f:
            return None
        if not target_text:
            return f

        start = time.time()
        percent = 0.0
        while time.time() - start < 1:
            percent = self.calculate_color_percentage(f_white_color, f)
            if percent > 0.5:
                break
            self.next_frame()
            self.log_debug(f'f white color percent: {percent} wait')
        if percent < 0.5:
            return None

        if target_text:
            search_text_box = f.copy(x_offset=f.width * 5.2, width_offset=f.width * 6, height_offset=4.5 * f.height,
                                     y_offset=-0.8 * f.height, name='search_text_box')
            text = self.ocr(box=search_text_box, match=target_text)
            logger.debug(f'found f with text {text}, target_text {target_text}')
            if text:
                if text[0].y > search_text_box.y + f.height * 1:
                    logger.debug(f'found f with text {text} below, target_text {target_text}')
                    self.scroll_relative(0.5, 0.5, 1)
                return f
        else:
            return f

    def has_target(self):
        return False

    def walk_to_yolo_echo(self, time_out=8, update_function=None, echo_threshold=0.5):
        last_direction = None
        start = time.time()
        no_echo_start = 0
        while time.time() - start < time_out:
            self.next_frame()
            if self.pick_f():
                self.log_debug('pick echo success')
                self._stop_last_direction(last_direction)
                return True
            if self.in_combat():
                self.log_debug('pick echo has_target return fail')
                self._stop_last_direction(last_direction)
                return False
            echos = self.find_echos(threshold=echo_threshold)
            if not echos:
                if no_echo_start == 0:
                    no_echo_start = time.time()
                elif time.time() - no_echo_start > 3:
                    self.log_debug(f'walk front to_echo, no echos found, break')
                    break
                next_direction = 'w'
            else:
                no_echo_start = 0
                echo = echos[0]
                center_distance = echo.center()[0] - self.width_of_screen(0.5)
                threshold = 0.05 if not last_direction else 0.15
                if abs(center_distance) < self.height_of_screen(threshold):
                    if echo.y + echo.height > self.height_of_screen(0.65):
                        next_direction = 's'
                    else:
                        next_direction = 'w'
                elif center_distance > 0:
                    next_direction = 'd'
                else:
                    next_direction = 'a'
            last_direction = self._walk_direction(last_direction, next_direction)
            if update_function is not None:
                update_function()
        self._stop_last_direction(last_direction)

    def _walk_direction(self, last_direction, next_direction):
        if next_direction != last_direction:
            self._stop_last_direction(last_direction)
            if next_direction:
                self.send_key_down(next_direction)
        return next_direction

    def _stop_last_direction(self, last_direction):
        if last_direction:
            self.send_key_up(last_direction)
            self.sleep(0.01)
        return None

    def walk_to_box(self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07,
                    use_hook=False):
        start = time.time()
        while time.time() - start < time_out:
            if ended := self.do_walk_to_box(find_function, time_out=time_out - (time.time() - start),
                                            end_condition=end_condition, y_offset=y_offset,
                                            x_threshold=x_threshold, use_hook=use_hook):
                return ended

    def do_walk_to_box(self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07,
                       use_hook=False):
        if find_function:
            self.wait_until(lambda: (not end_condition or end_condition()) or find_function(), raise_if_not_found=True,
                            time_out=time_out)
        last_direction = None
        start = time.time()
        ended = False
        running = False
        last_target = None
        centered = False
        while time.time() - start < time_out:
            self.next_frame()
            if end_condition:
                ended = end_condition()
                if ended:
                    logger.info(f'do_walk_to_box ended {ended}')
                    break
            treasure_icon = find_function()
            if isinstance(treasure_icon, list):
                if len(treasure_icon) > 0:
                    treasure_icon = treasure_icon[0]
                else:
                    treasure_icon = None
            if treasure_icon:
                last_target = treasure_icon
            if last_target is None:
                next_direction = self.opposite_direction(last_direction)
                self.log_info('find_function not found, change to opposite direction')
            else:
                x, y = last_target.center()
                y = max(0, y - self.height_of_screen(y_offset))
                x_abs = abs(x - self.width_of_screen(0.5))
                threshold = 0.04 if not last_direction else x_threshold
                centered = centered or x_abs <= self.width_of_screen(threshold)
                if not centered:
                    if x > self.width_of_screen(0.5):
                        next_direction = 'd'
                    else:
                        next_direction = 'a'
                else:
                    if last_direction == 's':
                        center = 0.45
                    elif last_direction == 'w':
                        center = 0.6
                    else:
                        center = 0.5
                    if y > self.height_of_screen(center):
                        next_direction = 's'
                    else:
                        next_direction = 'w'
            if next_direction != last_direction:
                if last_direction:
                    self.send_key_up(last_direction)
                    self.sleep(0.001)
                last_direction = next_direction
                if next_direction:
                    self.send_key_down(next_direction)
            if running:
                if not self.find_one('on_the_wall', threshold=0.7):
                    self.log_info('not on the wall, stop running')
                    self.mouse_up(key='right')
            else:
                if next_direction == 'w' and self.find_one('on_the_wall', threshold=0.7):
                    self.log_info('on the wall, start running')
                    running = True
                    self.mouse_down(key='right')
                    self.sleep(0.1)
            if use_hook and next_direction == 'w':
                if self.find_one('tool_teleport', 0.75):
                    self.send_key(self.key_config['Tool Key'])
                    self.sleep(3)
                    continue
        if last_direction:
            self.send_key_up(last_direction)
            self.sleep(0.001)
        if running:
            self.send_key_up(self.key_config.get('Dodge Key'))
        if not end_condition:
            return last_direction is not None
        else:
            return ended

    def opposite_direction(self, direction):
        if direction == 'w':
            return 's'
        elif direction == 's':
            return 'w'
        elif direction == 'a':
            return 'd'
        elif direction == 'd':
            return 'a'
        else:
            return 'w'

    def get_direction(self, location_x, location_y, screen_width, screen_height, centered, current_direction):
        """
        Determines the direction ('w', 'a', 's', 'd') closest to the screen center.
        Args:
            location_x: The x-coordinate of the point.
            location_y: The y-coordinate of the point.
            screen_width: The width of the screen.
            screen_height: The height of the screen.
        Returns:
            A string "w", "a", "s", or "d".
        """
        if screen_width <= 0 or screen_height <= 0:
            # Handle invalid dimensions, default based on horizontal position
            return "a" if location_x < screen_width / 2 else "d"
        center_x = screen_width / 2
        center_y = screen_height / 2
        # Calculate vector from point towards the center
        delta_x = center_x - location_x
        delta_y = center_y - location_y
        # Determine dominant direction based on vector magnitude
        direction = None
        if (abs(delta_x) > abs(delta_y) or (not current_direction and abs(delta_x) > 0.05 * screen_height)
                or abs(delta_x) > 0.15 * screen_height):
            # More horizontal movement needed
            return "a" if delta_x > 0 else "d"

            # More vertical movement needed (or equal)
        return "w" if delta_y > 0 else "s"

    def find_treasure_icon(self):
        from ok.feature.Box import Box
        # This marker moves in the 3D viewport; it is not a 16:9 HUD anchor.
        # box_of_screen would omit the rightmost 880 px at 3440x1440.
        width, height = self.width_of_screen(1), self.height_of_screen(1)
        viewport = Box(round(.03 * width), round(.1 * height),
                       round(.94 * width), round(.71 * height))
        return self.find_one('treasure_icon', box=viewport, threshold=0.8,
                             target_height=720)

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=False, down_time=0.01, after_sleep=0,
              key="left"):
        if x == -1 and y == -1:
            x = self.width_of_screen(0.5)
            y = self.height_of_screen(0.5)
            move = False
            # Coordinates are resolved here, before the native backend can
            # distinguish an attack from a menu click. Preserve a reliable
            # press duration through this facade instead of resetting it.
            if sys.platform == 'darwin':
                down_time = max(down_time, .08)
        else:
            down_time = 0.2
        return super().click(x, y, move_back, name, interval, move=move, down_time=down_time, after_sleep=after_sleep,
                             key=key)

    def check_for_monthly_card(self):
        if self.should_check_monthly_card():
            start = time.time()
            logger.info(f'check_for_monthly_card start check')
            if self.in_combat():
                logger.info(f'check_for_monthly_card in combat return')
                return time.time() - start
            if self.in_team_and_world():
                logger.info(f'check_for_monthly_card in team send sleep until monthly card popup')
                monthly_card = self.wait_until(self.handle_monthly_card, time_out=120, raise_if_not_found=False)
                logger.info(f'wait monthly card end {monthly_card}')
                cost = time.time() - start
                return cost
        return 0

    def in_realm(self):
        return not bool(getattr(self, 'treat_as_not_in_realm', False)) and self.find_one('illusive_realm_exit',
                                                                                         threshold=0.7,
                                                                                         frame_processor=convert_bw) and self.in_team() and not self.find_one(
            'world_earth_icon', threshold=0.55,
            frame_processor=convert_bw)

    def in_world(self):
        return self.find_world_earth_icon() and self.in_team()[0] and not self.find_one('illusive_realm_exit',
                                                                                                  threshold=0.7,
                                                                                                  frame_processor=convert_bw)

    def find_world_earth_icon(self):
        earth = self.find_one('world_earth_icon', threshold=.55,
                              horizontal_variance=.02, vertical_variance=.02,
                              frame_processor=convert_bw)
        if not earth:
            # macOS stream resampling softens the old 3840 reference below
            # threshold. Use the observed 1920 icon rather than lowering it.
            earth = self.find_one('macos_world_earth_1920', threshold=.8,
                                  horizontal_variance=.005, vertical_variance=.005)
        return earth

    def in_illusive_realm(self):
        return self.find_one('new_realm_4') and self.in_realm() and self.find_one('illusive_realm_menu', threshold=0.6)

    def walk_until_f(self, direction='w', time_out=1, raise_if_not_found=True, backward_time=0, target_text=None,
                     check_combat=False, running=False):
        logger.info(f'walk_until_f direction {direction} target_text: {target_text}')
        if not self.find_f_with_text(target_text=target_text):
            # 视角朝前
            self.middle_click(after_sleep=0.2)
            if backward_time > 0:
                if self.send_key_and_wait_f('s', raise_if_not_found, backward_time, target_text=target_text,
                                            running=running, check_combat=check_combat):
                    logger.info('walk backward found f')
                    return True
            if self.send_key_and_wait_f(direction, raise_if_not_found, time_out, target_text=target_text,
                                        running=running, check_combat=check_combat):
                logger.info('walk forward found f')
                return True
            return False
        else:
            return True

    def get_stamina(self):
        from src.task.WaveplateReading import parse_waveplates
        last = []
        def read_pair():
            nonlocal last
            last = self.ocr(.35, 0, .92, .10, threshold=.5) or []
            result = parse_waveplates(last, self.width)
            if result[0] < 0:
                # Anchor the reserve crop to the observed current badge. A
                # fixed crop can include part of the current balance itself.
                fractions = [b for b in last if re.fullmatch(
                    r'[0-9]{1,4}[/／]240[+＋]?', re.sub(r'\s+', '', b.name))]
                if len(fractions) == 1:
                    from ok import Box
                    badge = fractions[0]
                    field = Box(round(badge.x - self.width * .16), 0,
                                round(self.width * .14), round(self.height * .10))
                    readings = self.ocr(box=field, threshold=.5,
                        frame_processor=lambda im: cv2.copyMakeBorder(
                            cv2.resize(im, None, fx=3, fy=3), 20, 20, 20, 20,
                            cv2.BORDER_REPLICATE)) or []
                    values = [re.sub(r'\s+', '', b.name) for b in readings]
                    values = [v for v in values if re.fullmatch(r'[0-9]{1,4}', v)]
                    if len(values) == 1:
                        result = parse_waveplates([badge, Box(
                            round(badge.x - self.width * .10), 0, 20, 20,
                            name=values[0])], self.width)
            return result if result[0] >= 0 else None
        result = self.wait_until(read_pair, time_out=4, raise_if_not_found=False)
        if not result:
            self.log_info(f'waveplate OCR rejected: {[(b.name,b.x,b.width) for b in last]} screen={self.width}')
            self.screenshot('stamina_error')
            return -1, -1, -1
        current, back_up, total = result
        self.info_set('current_stamina', current)
        self.info_set('back_up_stamina', back_up)
        return current, back_up, total

    def use_stamina(self, once=60, must_use=0):
        self.sleep(1)
        current, back_up, total = self.get_stamina()
        y = 0.62
        if current >= once * 2:
            used = once * 2
            x = 0.67
            logger.info(f"当前体力大于等于双倍, {current} >= {once * 2}")
        elif must_use > once and total >= once * 2:
            used = once * 2
            x = 0.67
            logger.info(f"当前加备用大于日常剩余所需, 使用双倍, {must_use} >= {once} and {total} >= {once * 2}")
        else:
            used = once
            x = 0.32
            logger.info(f"使用单倍体力")
        self.click(x, y, after_sleep=1)
        if self.wait_feature('gem_add_stamina', horizontal_variance=0.4, vertical_variance=0.05,
                             time_out=2, settle_time=0.5):  # 看是否需要使用备用体力
            self.click(0.70, 0.71, after_sleep=1)  # 点击确认
            self.click(0.70, 0.71, after_sleep=1)
            self.back(after_sleep=1)
            self.click(x, y, after_sleep=1)

        current -= used
        must_use -= used
        total -= used
        if total < once:
            logger.info(f"current stamina: {current} not enough to continue")
            can_continue = False
        elif must_use <= 0 and current < once:
            can_continue = False
            logger.info(f"current stamina: {current} must_use completed, no need to use back_up")
        else:
            can_continue = True
        return can_continue, used

    def send_key_and_wait_f(self, direction, raise_if_not_found, time_out, running=False, target_text=None,
                            check_combat=False):
        if time_out <= 0:
            return
        self.send_key_down(direction)
        if running:
            self.sleep(0.1)
            self.mouse_down(key='right')
        f_found = self.wait_until(
            lambda: self.find_f_with_text(target_text=target_text) or (check_combat and self.in_combat()),
            time_out=time_out,
            raise_if_not_found=False)
        self.send_key_up(direction)
        if running:
            self.sleep(0.1)
            self.mouse_up(key='right')
        if not f_found:
            if raise_if_not_found:
                raise CannotFindException('cant find the f to enter')
            else:
                logger.warning(f"can't find the f to enter")
                return False
        return f_found

    def run_until(self, condiction, direction, time_out, raise_if_not_found=False, running=False, target=False,
                  post_walk=0):
        if time_out <= 0:
            return
        self.send_key_down(direction)
        if running:
            self.sleep(0.1)
            logger.debug(f'run_until condiction {condiction} direction {direction}')
            self.mouse_down(key='right')
        start = time.time()
        result = None
        while time.time() - start < time_out:
            if result := condiction():
                break
            if target:
                self.middle_click(interval=0.5)
            self.sleep(0.02)
        if result and post_walk:
            self.sleep(post_walk)
        self.send_key_up(direction)
        if running:
            self.sleep(0.1)
            self.mouse_up(key='right')

        if raise_if_not_found and not result:
            raise Exception('wait condition failed while walking')
        return result

    def is_moving(self):
        return False

    def handle_claim_button(self):
        while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
            self.sleep(0.5)
            self.send_key('esc')
            self.sleep(0.5)
            logger.info(f"handle_claim_button found a claim reward")
            return True

    def has_claim_stamina(self):
        return not self.in_team()[0] and self.find_one('claim_stamina_sign')

    def has_claim(self):
        return not self.in_team()[0] and self.find_one('claim_cancel_button_hcenter_vcenter', horizontal_variance=0.05,
                                                       vertical_variance=0.1, threshold=0.8)

    def test_absorb(self):
        # self.set_image('tests/images/absorb.png')
        image = cv2.imread('tests/images/absorb.png')
        result = self.executor.ocr_lib(image, use_det=True, use_cls=False, use_rec=True)
        self.logger.info(f'ocr_result {result}')

    def find_echos(self, threshold=0.3):
        """
        Main function to load ONNX model, perform inference, draw bounding boxes, and display the output image.

        Args:
            onnx_model (str): Path to the ONNX model.
            input_image (ndarray): Path to the input image.

        Returns:
            list: List of dictionaries containing detection information such as class_id, class_name, confidence, etc.
        """
        # Load the ONNX model
        ret = og.my_app.yolo_detect(self.frame, threshold=threshold, label=0)

        for box in ret:
            box.y += box.height * 1 / 3
            box.height = 1
        self.draw_boxes("echo", ret)
        return ret

    def yolo_find_all(self, threshold=0.3):
        """
        Main function to load ONNX model, perform inference, draw bounding boxes, and display the output image.

        Args:
            onnx_model (str): Path to the ONNX model.
            input_image (ndarray): Path to the input image.

        Returns:
            list: List of dictionaries containing detection information such as class_id, class_name, confidence, etc.
        """
        # Load the ONNX model
        boxes = og.my_app.yolo_detect(self.frame, threshold=threshold, label=-1)
        ret = sorted(boxes, key=lambda detection: detection.confidence, reverse=True)
        return ret

    def pick_echo(self):
        if self.find_f_with_text(target_text=self.absorb_echo_text()):
            self.send_key('f')
            if not self.handle_claim_button():
                self.log_debug('found a echo picked')
                return True

    def pick_f(self, handle_claim=True):
        if self.find_one('pick_up_f_hcenter_vcenter', box=self.f_search_box, threshold=0.8):
            self.send_key('f', after_sleep=1)
            if not handle_claim:
                return True
            if not self.handle_claim_button():
                self.log_debug('found a echo picked')
                return True

    def is_pick_f(self):
        f = self.find_one('pick_up_f_hcenter_vcenter', box=self.f_search_box,
                          threshold=0.8)
        if not f:
            return False
        dialog_search = f.copy(x_offset=f.width * 3, width_offset=f.width * 1.8, height_offset=f.height * 2,
                               y_offset=-f.height,
                               name='search_dialog')
        dialog_3_dots = self.find_feature('dialog_3_dots', box=dialog_search,
                                          threshold=0.6)
        return bool(dialog_3_dots)

    def walk_to_treasure(self, send_f=True, raise_if_not_found=True):
        self.log_info('start walk_to_treasure')
        if not self.walk_to_box(self.find_treasure_icon, end_condition=self.find_f_with_claim_text):
            if not self.walk_to_box(self.find_treasure_icon, end_condition=self.find_f_with_text):
                raise Exception(f'can not walk to treasure!')
        if send_f:
            self.walk_until_f(time_out=2, backward_time=0, raise_if_not_found=raise_if_not_found)
        self.sleep(1)

    def yolo_find_echo(self, use_color=False, turn=True, update_function=None, time_out=8, threshold=0.5):
        max_echo_count = 0
        if self.pick_echo():
            self.sleep(0.5)
            return True, True
        front_box = self.box_of_screen(0.35, 0.35, 0.65, 0.53, hcenter=True)
        color_threshold = 0.02
        for i in range(4):
            if turn:
                self.center_camera()
            echos = self.find_echos(threshold=threshold)
            max_echo_count = max(max_echo_count, len(echos))
            self.log_debug(f'max_echo_count {max_echo_count}')
            if echos:
                self.log_info(f'yolo found echo {echos}')
                # return self.walk_to_box(self.find_echos, time_out=15, end_condition=self.pick_echo), max_echo_count > 1
                return self.walk_to_yolo_echo(update_function=update_function, time_out=time_out), max_echo_count > 1
            if use_color:
                color_percent = self.calculate_color_percentage(echo_color, front_box)
                self.log_debug(f'pick_echo color_percent:{color_percent}')
                if color_percent > color_threshold:
                    # if self.debug:
                    #     self.screenshot('echo_color_picked')
                    self.log_debug(f'found color_percent {color_percent} > {color_threshold}, walk now')
                    # return self.walk_to_box(self.find_echos, time_out=15, end_condition=self.pick_echo), max_echo_count > 1
                    return self.walk_to_yolo_echo(update_function=update_function), max_echo_count > 1
            if not turn and i == 0:
                return False, max_echo_count > 1
            self.send_key('a', down_time=0.05)
            self.sleep(0.5)

        self.center_camera()
        return False, max_echo_count > 1

    def center_camera(self):
        self.click(0.5, 0.5, down_time=0.2, key='middle')
        self.sleep(1)

    def turn_direction(self, direction):
        if direction != 'w':
            self.send_key(direction, down_time=0.05, after_sleep=0.5)
        self.center_camera()

    def walk_find_echo(self, backward_time=1, time_out=3):
        if self.walk_until_f(time_out=time_out, backward_time=backward_time, target_text=self.absorb_echo_text(),
                             raise_if_not_found=False, check_combat=True):  # find and pick echo
            logger.debug(f'farm echo found echo move forward walk_until_f to find echo')
            return self.pick_f()

    def incr_drop(self, dropped):
        if dropped:
            self.info['Echo Count'] = self.info.get('Echo Count', 0) + 1
            self.info['Echo per Hour'] = round(
                self.info.get('Echo Count', 0) / max(time.time() - self.start_time, 1) * 3600)

    def should_check_monthly_card(self):
        if self.next_monthly_card_start > 0:
            if 0 < time.time() - self.next_monthly_card_start < 120:
                return True
        return False

    def sleep(self, timeout):
        return super().sleep(timeout - self.check_for_monthly_card())

    def wait_in_team_and_world(self, time_out=10, raise_if_not_found=True, esc=False):
        if esc:
            try:
                return self.ensure_main(esc=True, time_out=time_out)
            except Exception:
                if raise_if_not_found:
                    raise
                return None
        success = self.wait_until(self.in_team_and_world, time_out=time_out, raise_if_not_found=raise_if_not_found,
                                  post_action=None)
        if success:
            self.sleep(0.1)
        return success

    def ensure_main(self, esc=True, time_out=30):
        self.info_set('current task', f'wait main esc={esc}')
        if not self.logged_in:
            time_out = 600
        interaction = getattr(getattr(self, 'executor', None), 'interaction', None)
        clickable = getattr(interaction, 'clickable', None)
        if callable(clickable) and not clickable():
            self.log_error('game window is not foreground; stop before sending input')
            raise Exception('Please keep the game window in the foreground!')

        start = time.time()
        back_attempts = 0
        max_back_attempts = 0 if sys.platform == 'darwin' else MAIN_MAX_BACK_ATTEMPTS
        while time.time() - start < time_out:
            remaining = time_out - (time.time() - start)
            found = self.wait_until(
                lambda: self.is_main(esc=False),
                time_out=max(0.1, min(MAIN_WORLD_PROBE_TIMEOUT, remaining)),
                settle_time=MAIN_WORLD_SETTLE_TIME,
                raise_if_not_found=False,
            )
            if found:
                self.sleep(0.5)
                self.info_set('current task', f'in main esc={esc}')
                return True

            if not esc or back_attempts >= max_back_attempts:
                break
            if callable(clickable) and not clickable():
                self.log_error('game window left foreground; stop before sending Esc')
                raise Exception('Please keep the game window in the foreground!')

            back_attempts += 1
            self.log_info(
                f'world not confirmed; close one menu layer '
                f'({back_attempts}/{max_back_attempts})'
            )
            self.back(after_sleep=2)

        if sys.platform == 'darwin' and esc:
            self.log_error(
                'world verification failed on macOS; no Esc was sent from an unknown page'
            )
        self.log_error(
            f'world verification failed after {back_attempts} guarded Esc attempt(s); stop task'
        )
        raise Exception('Please start in game world and in team!')

    def is_main(self, esc=True):
        if self.in_team_and_world():
            self.logged_in = True
            return True
        if self.wait_login():
            return False
        if self.handle_monthly_card():
            return False
        if esc:
            self.log_debug('is_main no longer sends Esc; ensure_main owns guarded retries')
        return False

    def wait_login(self):
        if not self.logged_in:
            if self.in_team_and_world():
                self.logged_in = True
                return True
            self.handle_monthly_card()
            if login_close := self.find_one('login_close', horizontal_variance=0.15, vertical_variance=0.1):
                self.click(login_close, after_sleep=1)
                self.log_info('关闭公告!')
                return False
            texts = self.ocr(log=self.debug)

            if login := self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7),
                                        match=LOGIN_TEXTS):
                if not self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match="+86"):
                    # the game may be auto logging in with saved credentials, wait and
                    # confirm the login button is still there before clicking (#1356)
                    self.sleep(LOGIN_CLICK_SETTLE_TIME)
                    texts = self.ocr(log=self.debug)
                    login = self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7),
                                            match=LOGIN_TEXTS)
                    if login and not self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7),
                                                     match="+86"):
                        self.click(login, after_sleep=1)
                        self.log_info('点击登录按钮!')
                return False
            if agree := self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match="同意"):
                self.log_debug(f'found agree {agree}')
                if self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.7), match=re.compile("隐私")):
                    self.click(agree, after_sleep=1)
                    self.log_info('点击同意按钮!')
                return False
            if self.find_boxes(texts, match=[re.compile("游戏即将重启"), re.compile('遊戲即將重啟')]):
                self.sleep(0.2)
                self.log_info('游戏更新成功, 游戏即将重启')
                self.click(self.find_boxes(texts, match=["确认", "確認"]), after_sleep=60)
                result = self.start_device()
                self.log_info(f'start_device end {result}')
                self.sleep(30)
                return False

            if start := self.find_boxes(texts, boundary='bottom_right', match=["开始游戏", re.compile("进入游戏")]):
                if not self.find_boxes(texts, boundary='bottom_right', match=LOGIN_TEXTS):
                    self.click(start)
                    self.log_info(f'点击开始游戏! {start}')
                    return False
            if switch_login := self.find_one(Labels.switch_account, vertical_variance=0.1, threshold=0.7):
                if boxes := self.find_boxes(texts, boundary=self.box_of_screen(0.37, 0.63, 0.63, 0.99)):
                    self.log_info(f'wait_login {switch_login} {boxes}')
                    self.click(0.503, 0.926, after_sleep=3)
                    return False

    def in_team_and_world(self):
        return self.in_team()[
            0]  # and self.find_one(f'gray_book_button', threshold=0.7, canny_lower=50, canny_higher=150)

    def get_angle_between(self, my_angle, angle):
        if my_angle > angle:
            to_turn = angle - my_angle
        else:
            to_turn = -(my_angle - angle)
        if to_turn > 180:
            to_turn -= 360
        elif to_turn < -180:
            to_turn += 360
        return to_turn

    def get_my_angle(self):
        return self.rotate_arrow_and_find()[0]

    def rotate_arrow_and_find(self):
        arrow_template = self.get_feature_by_name('arrow')
        original_mat = arrow_template.mat
        max_conf = 0
        max_angle = 0
        max_target = None
        max_mat = None
        (h, w) = arrow_template.mat.shape[:2]
        # self.log_debug(f'turn_east h:{h} w:{w}')
        center = (w // 2, h // 2)
        target_box = self.get_box_by_name('arrow')
        # if self.debug:
        #     self.screenshot('arrow_original', original_ mat)
        for angle in range(0, 360):
            # Rotate the template image
            rotation_matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)
            template = cv2.warpAffine(original_mat, rotation_matrix, (w, h))
            # mask = np.where(np.all(template == [0, 0, 0], axis=2), 0, 255).astype(np.uint8)

            target = self.find_one(box=target_box,
                                   template=template, threshold=0.01)
            # if self.debug and angle % 90 == 0:
            #     self.screenshot(f'arrow_rotated_{angle}', arrow_template.mat)
            if target and target.confidence > max_conf:
                max_conf = target.confidence
                max_angle = angle
                max_target = target
                # max_mat = template
        # arrow_template.mat = original_mat
        # arrow_template.mask = None
        # if self.debug and max_mat is not None:
        #     self.screenshot('max_mat',frame=max_mat)
        # self.log_debug(f'turn_east max_conf: {max_conf} {max_angle}')
        return max_angle, max_target

    def get_mini_map_turn_angle(self, feature, threshold=0.72, x_offset=0, y_offset=0):
        box = self.get_box_by_name('box_minimap')
        target = self.find_one(feature, box=box, threshold=threshold)
        if not target:
            self.log_info(f'Can not find {feature} on minimap')
            return None
        else:
            self.log_debug(f'found {box} on minimap')
        target.x += target.width * x_offset
        target.y += target.height * y_offset
        direction_angle = calculate_angle_clockwise(box, target)
        my_angle = self.get_my_angle()
        to_turn = self.get_angle_between(my_angle, direction_angle)
        self.log_info(f'angle: {my_angle}, to_turn: {to_turn}')
        return to_turn

    def _stop_movement(self, current_direction):
        """Releases keys and mouse to stop character movement."""
        if current_direction is not None:
            self.mouse_up(key='right')
            self.send_key_up(current_direction)

    def _navigate_based_on_angle(self, angle, current_direction, current_adjust):
        """
        Core navigation logic to adjust movement based on a target angle.
        This contains the shared logic from the original functions.

        Returns a tuple: (new_direction, new_adjust, should_continue)
        - new_direction: The updated movement direction ('w', 'a', 's', 'd').
        - new_adjust: The updated adjustment state.
        - should_continue: A boolean indicating if the calling loop should `continue`.
        """
        # 1. Handle minor adjustments if already moving forward
        if current_direction == 'w':
            if 10 <= angle <= 80:
                minor_adjust = 'd'
            elif -80 <= angle <= -10:
                minor_adjust = 'a'
            else:
                minor_adjust = None

            if minor_adjust:
                self.send_key_down(minor_adjust)
                self.sleep(0.1)
                self.middle_click(down_time=0.1)
                self.send_key_up(minor_adjust)
                self.sleep(0.01)
                # Tell the caller to continue to the next loop iteration
                return current_direction, current_adjust, True

        # 2. Clean up any previous adjustments
        if current_adjust:
            self.send_key_up(current_adjust)
            current_adjust = None

        # 3. Determine the major new direction based on the angle
        if -45 <= angle <= 45:
            new_direction = 'w'
        elif 45 < angle <= 135:
            new_direction = 'd'
        elif -135 < angle <= -45:
            new_direction = 'a'
        else:
            new_direction = 's'

        # 4. Change direction if needed
        if current_direction != new_direction:
            self.log_info(f'changed direction {angle} {current_direction} -> {new_direction}')
            if current_direction:
                self.mouse_up(key='right')
                self.send_key_up(current_direction)
                self.wait_until(self.in_combat, time_out=0.2)
            self.turn_direction(new_direction)
            self.send_key_down('w')
            self.wait_until(self.in_combat, time_out=0.2)
            self.mouse_down(key='right')
            current_direction = 'w'  # After turning, we always move forward
            self.wait_until(self.in_combat, time_out=1)

        return current_direction, current_adjust, False

    def in_team(self):
        c1 = self.find_one('char_1_text',
                           threshold=0.8,
                           horizontal_variance=TEAM_UI_VARIANCE,
                           vertical_variance=TEAM_UI_VARIANCE)
        c2 = self.find_one('char_2_text',
                           threshold=0.8,
                           horizontal_variance=TEAM_UI_VARIANCE,
                           vertical_variance=TEAM_UI_VARIANCE)
        c3 = self.find_one('char_3_text',
                           threshold=0.8,
                           horizontal_variance=TEAM_UI_VARIANCE,
                           vertical_variance=TEAM_UI_VARIANCE)
        arr = [c1, c2, c3]
        # logger.debug(f'in_team check {arr}')
        current = -1
        exist_count = 0
        for i in range(len(arr)):
            if arr[i] is None:
                if current == -1:
                    current = i
            else:
                exist_count += 1
        if exist_count == 2 or exist_count == 1:
            self.logged_in = True
            return True, current, exist_count + 1
        else:
            return False, -1, exist_count + 1

        # Function to check if a component forms a ring

    def find_monthly_card(self):
        return self.find_one('monthly_card', threshold=0.65, horizontal_variance=0.05, vertical_variance=0.05)

    def handle_monthly_card(self):
        monthly_card = self.find_monthly_card()
        # self.screenshot('monthly_card1')
        if monthly_card is not None:
            # self.screenshot('monthly_card1')
            self.log_info('monthly_card found click')
            self.click_relative(0.50, 0.89)
            self.sleep(2)
            # self.screenshot('monthly_card2')
            self.click_relative(0.50, 0.89)
            self.sleep(2)
            self.wait_until(self.in_team_and_world, time_out=10,
                            post_action=lambda: self.click_relative(0.50, 0.89, after_sleep=1))
            # self.screenshot('monthly_card3')
            self.set_check_monthly_card(next_day=True)
        # logger.debug(f'check_monthly_card {monthly_card}')
        return monthly_card is not None

    @property
    def game_lang(self):
        if '鸣潮' in self.hwnd_title or self.is_browser():
            return 'zh_CN'
        elif 'Wuthering' in self.hwnd_title:
            return 'en_US'
        elif '鳴潮' in self.hwnd_title:
            return 'zh_TW'
        return 'unknown_lang'

    def open_esc_menu(self):
        self.send_key_down('alt')
        self.sleep(0.05)
        self.click_relative(0.95, 0.04)
        self.send_key_up('alt')
        self.sleep(0.5)

    def open_boss_book(self, name, after_sleep=2):
        self.log_info(f'open_boss_book {name}')
        x = 0.24
        self.sleep(0.4)
        if name == 'ningsu':
            y = 0.4
        elif name == 'moni':
            y = 0.3
        elif name == 'qiangdi':
            y = 0.49
        elif name == 'wuyin':
            y = 0.73
        elif name == 'zhange':
            y = 0.61
        elif name == 'canxiang':
            y = 0.83
        elif name == 'mengyan':
            self.click_relative(0.356, 0.882, after_sleep=after_sleep)
            y = 0.86
        else:
            raise Exception(f'unknown_lang {name}')
        self.click_relative(x, y, after_sleep=after_sleep, name=name)

    def openF2Book(self, feature="gray_book_all_monsters"):
        if hasattr(self, 'reset_to_false'):
            self.reset_to_false('opening book')
        self.ensure_main()
        book_key = self.key_config.get('Guidebook Key', self.key_config.get('索拉指南', 'f2'))
        self.log_info(f'click {book_key} to open the book')
        if self.in_team_and_world():
            self.send_key(book_key, after_sleep=4)
            self.log_info(f'send {book_key} key to open')
        if self.in_team_and_world():
            self.log_info('send f2 key mouse key to open the book')
            self.send_key_down('alt')
            self.sleep(0.05)
            self.click_relative(*GUIDEBOOK_MENU_POSITION)
            self.sleep(0.02)
            self.send_key_up('alt')
            self.sleep(4)
        gray_book_boss = self.wait_book(feature)
        if not gray_book_boss:
            self.log_error("can't find gray_book_boss, make sure f2 is the hotkey for book", notify=True)
            raise Exception("can't find gray_book_boss, make sure f2 is the hotkey for book")
        self.sleep(2)
        self.click_box(gray_book_boss, after_sleep=1.5)
        return gray_book_boss

    def open_materials_book(self):
        """Open the current Material Acquisition page without old icon templates."""
        guidebook_page = self.wait_guidebook_page(time_out=0.8)
        if guidebook_page:
            self.log_info('reuse the open guidebook for material acquisition')
        else:
            self.ensure_main()
            book_key = self.key_config.get('Guidebook Key', self.key_config.get('索拉指南', 'f2'))
            if self.in_team_and_world():
                self.send_key(book_key, after_sleep=4)
            if self.in_team_and_world():
                self.send_key_down('alt')
                self.sleep(0.05)
                self.click_relative(*GUIDEBOOK_MENU_POSITION)
                self.sleep(0.02)
                self.send_key_up('alt')
                self.sleep(4)

            if not self.wait_guidebook_page(time_out=3):
                import cv2
                cv2.imwrite('logs/guidebook-verification-failed.png', self.frame)
                self.log_info(f'guidebook title OCR: {self.ocr(box=self.box_of_screen(*GUIDEBOOK_TITLE_BOX))}')
                self.log_error('guidebook verification failed; skip material page coordinate')
                raise Exception('guidebook verification failed')

        self.click_relative(*MATERIALS_GUIDE_POSITION, after_sleep=1)
        page = self.wait_ocr(
            *MATERIALS_TITLE_BOX,
            match=MATERIALS_TITLE_TEXT,
            time_out=3,
            settle_time=0.5,
            raise_if_not_found=False,
        )
        if page:
            return True
        self.log_error('material acquisition page verification failed; stop farming')
        self.ensure_main()
        raise Exception('material acquisition page verification failed')

    def wait_guidebook_page(self, time_out=3):
        """Verify a guidebook page by its top-left title, not legacy icons."""
        return self.wait_ocr(
            *GUIDEBOOK_TITLE_BOX,
            match=GUIDEBOOK_TITLE_TEXT,
            time_out=time_out,
            settle_time=0.3,
            raise_if_not_found=False,
        )

    def click_traval_button(self):
        for feature_name in ['fast_travel_custom', 'gray_teleport', 'remove_custom']:
            if self.find_one(feature_name, threshold=0.7):
                self.sleep(0.5)
                feature = self.find_one(feature_name, threshold=0.7)
                if not feature:
                    continue
                self.click(feature, after_sleep=1)
                if feature.name == 'fast_travel_custom':
                    if confirm := self.wait_feature(
                            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                            raise_if_not_found=False,
                            threshold=0.6,
                            time_out=2):
                        self.click(0.49, 0.55, after_sleep=0.5)  # 点击不再提醒
                        self.click(confirm, after_sleep=0.5)
                        self.click_confirm()
                if feature.name != 'remove_custom':
                    self.wait_click_skip_dialog_confirm()
                return True

    def click_confirm(self, timeout=1):
        self.wait_click_feature(
            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
            relative_x=-1, raise_if_not_found=False,
            threshold=0.6,
            time_out=1)

    def click_skip_dialog_confirm(self):
        skip_dialog_confirm = self.find_one(
            'skip_dialog_confirm',
            horizontal_variance=0.1,
            vertical_variance=0.1,
        )
        if not skip_dialog_confirm:
            return False

        skip_dialog_check = self.find_one(
            'skip_dialog_check',
            horizontal_variance=0.1,
            vertical_variance=0.1,
        )
        if not skip_dialog_check:
            check_feature = self.get_feature_by_name('skip_dialog_check')
            wide_check_template = cv2.resize(
                check_feature.mat,
                (0, 0),
                fx=WIDE_MODE_UI_SCALE,
                fy=WIDE_MODE_UI_SCALE,
                interpolation=cv2.INTER_AREA,
            )
            skip_dialog_check = self.find_one(
                'skip_dialog_check',
                box=self.box_of_screen(0.35, 0.45, 0.55, 0.65),
                template=wide_check_template,
            )
        if not skip_dialog_check:
            return False

        logger.info('confirm dialog exists, click confirm')
        self.sleep(0.5)
        self.click(skip_dialog_check)
        self.sleep(0.5)
        self.click(skip_dialog_confirm)
        self.sleep(0.2)
        return True

    def wait_click_skip_dialog_confirm(self, time_out=3):
        return self.wait_until(
            self.click_skip_dialog_confirm,
            time_out=time_out,
            raise_if_not_found=False,
        )

    def click_team_challenge(self):
        """Start a domain through either the old or current two-page flow."""
        entry_notice = getattr(self, 'handle_material_entry_notice', None)
        self._entry_warning_accepted = False
        if entry_notice:
            entry_notice(timeout=.5)
        if self.wait_click_feature(
                'team_start_challenge',
                raise_if_not_found=False,
                time_out=2,
                after_sleep=1):
            if entry_notice:
                entry_notice(timeout=1)
            return True

        challenge_boxes = self.wait_ocr(
            *SOLO_CHALLENGE_BOX,
            match=SOLO_CHALLENGE_TEXT,
            threshold=0.2,
            time_out=3,
            settle_time=0.4,
            raise_if_not_found=False,
        ) or []
        if challenge_boxes:
            challenge = max(challenge_boxes, key=lambda box: box.x)
            self.log_info(
                f'click solo challenge by OCR: {challenge.name}'
            )
            self.click_box(challenge, after_sleep=1)
            if entry_notice:
                entry_notice(timeout=2)
        else:
            self.screenshot('solo_challenge_not_found')
            raise RuntimeError(
                'solo challenge button was not found by template or OCR'
            )

        if self.wait_click_feature(
                'team_start_challenge',
                raise_if_not_found=False,
                time_out=10,
                after_sleep=1):
            self.log_info('click team-page start challenge by template')
            if entry_notice:
                entry_notice(timeout=1)
            return True

        start_boxes = self.wait_ocr(
            *START_CHALLENGE_BOX,
            match=START_CHALLENGE_TEXT,
            threshold=0.2,
            time_out=3,
            settle_time=0.4,
            raise_if_not_found=False,
        ) or []
        if start_boxes:
            start_button = max(start_boxes, key=lambda box: box.x)
            self.log_info(
                f'click team-page start challenge by OCR: '
                f'{start_button.name}'
            )
            self.click_box(start_button, after_sleep=1)
            if entry_notice:
                entry_notice(timeout=1)
            return True

        self.screenshot('team_start_challenge_not_found')
        raise RuntimeError(
            'team-page start challenge button was not found by template or OCR'
        )

    def wait_click_travel(self):
        self.wait_until(self.click_traval_button, raise_if_not_found=True, time_out=10)

    def enter_book_domain_target(self, serial_number, total_number, structure=None):
        """Enter a domain selected from the guidebook.

        Return ``False`` only when the selected map destination is still visibly
        unavailable after the travel click. Unknown transition states raise
        instead of being mistaken for a locked region.
        """
        is_team_page = self.click_on_book_target(serial_number, total_number, structure)
        return self.finish_domain_destination(is_team_page)

    def finish_domain_destination(self, is_team_page):
        """Finish entry after a guidebook location has been selected."""
        teleport_timeout = getattr(self, 'teleport_timeout', 120)
        if is_team_page:
            self.click_team_challenge()
            self.wait_in_team_and_world(time_out=teleport_timeout)
            return True

        travel_clicked = self.wait_until(
            self.click_traval_button,
            raise_if_not_found=False,
            time_out=10,
        )
        if not travel_clicked:
            self.log_info('selected domain has no usable travel button')
            return False

        team_button = self.wait_feature(
            'team_start_challenge',
            raise_if_not_found=False,
            time_out=15,
            threshold=0.7,
        )
        if team_button:
            self.click(team_button, after_sleep=1)
            entry_notice = getattr(self, 'handle_material_entry_notice', None)
            if entry_notice:
                self._entry_warning_accepted = False
                entry_notice(timeout=2)
            self.wait_in_team_and_world(time_out=teleport_timeout)
            return True

        # A disabled/unavailable destination remains on the same map panel.
        # Only that positively identified state is eligible for fallback.
        for feature_name in ['fast_travel_custom', 'gray_teleport', 'remove_custom']:
            if self.find_one(feature_name, threshold=0.7):
                self.log_info('selected domain is unavailable in the current region')
                return False

        raise RuntimeError('domain travel changed to an unknown page; stop before selecting another target')

    @staticmethod
    def _normalize_material_text(text):
        return re.sub(r'[\s·•:：_\-—]+', '', text or '').lower()

    @classmethod
    def _valid_material_location_name(cls, text):
        """Reject list chrome that OCR can mistake for a stage name."""
        normalized = cls._normalize_material_text(text)
        if len(normalized) < 3 or normalized.startswith('row-'):
            return False
        return not any(
            ui_text in normalized
            for ui_text in MATERIAL_LOCATION_UI_TEXT
        )

    def current_material_target_name(self):
        """Read the display name of the selected cultivation target."""
        target_boxes = self.ocr(
            box=self.box_of_screen(*MATERIAL_TARGET_BOX),
            threshold=0.2,
        ) or []
        ignored = {
            self._normalize_material_text(text)
            for text in ('培养目标', '培養目標', 'Development Target', 'UP', '当期')
        }
        name_left = next((box.x for box in target_boxes
                          if self._normalize_material_text(box.name) in
                          ('培养目标', '培養目標', 'developmenttarget')), None)
        target_parts = []
        for box in sorted(target_boxes, key=lambda item: (item.y, item.x)):
            normalized = self._normalize_material_text(box.name)
            if name_left is not None and box.x < name_left - 3:
                continue  # Exclude the small banner on the avatar, even if OCR reads only 期.
            if normalized and normalized not in ignored:
                target_parts.append(box.name.strip())
        if not target_parts:
            # A single small glyph such as 心 can be missed by text detection.
            # Read only the name line at higher resolution, excluding the avatar.
            name_boxes = self.ocr(
                box=self.box_of_screen(.142, .173, .302, .208),
                target_height=self.height * 3, threshold=.8,
            ) or []
            target_parts = [box.name.strip() for box in name_boxes
                            if self._normalize_material_text(box.name) not in ignored]
        return ' '.join(dict.fromkeys(target_parts))

    def current_material_target_key(self, category_name):
        """Read the currently selected cultivation target for cache isolation."""
        target_name = self.current_material_target_name()
        target_key = self._normalize_material_text(target_name) or 'current'
        return f'{category_name}:{target_key}:{self.width}x{self.height}'

    @staticmethod
    def _material_drop_fingerprint(image):
        """Build a compact perceptual fingerprint for the material icons."""
        if image is None or image.size == 0:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        bits = gray >= np.median(gray)
        return np.packbits(bits.reshape(-1)).tobytes().hex()

    @staticmethod
    def _material_avatar_histogram(image):
        if image is None or image.size == 0:
            return None
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        histogram = cv2.calcHist(
            [hsv],
            [0, 1],
            None,
            [24, 24],
            [0, 180, 0, 256],
        )
        return cv2.normalize(histogram, histogram)

    def _current_material_target_avatar_histogram(self):
        avatar_box = self.box_of_screen(
            *MATERIAL_TARGET_AVATAR_BOX,
            name='current_cultivation_target_avatar',
        )
        return self._material_avatar_histogram(
            avatar_box.crop_frame(self.frame)
        )

    def _material_row_visuals(self, row_y, target_avatar_histogram=None):
        """Read the target-avatar marker and material-drop icon preview.

        The first reward icon is the universal experience reward and is
        deliberately excluded from the fingerprint. Only the following
        weapon/skill material icons identify equivalent rows.
        """
        marker_box = self.box_of_screen(
            MATERIAL_TARGET_MARKER_X[0],
            max(0.185, row_y - 0.060),
            MATERIAL_TARGET_MARKER_X[1],
            max(0.20, row_y - 0.018),
            name='cultivation_target_row_marker',
        )
        marker = marker_box.crop_frame(self.frame)
        marker_saturation = 0.0
        avatar_similarity = 0.0
        if marker is not None and marker.size:
            hsv = cv2.cvtColor(marker, cv2.COLOR_BGR2HSV)
            saturated = (hsv[:, :, 1] >= 55) & (hsv[:, :, 2] >= 45)
            marker_saturation = float(np.mean(saturated))
            marker_histogram = self._material_avatar_histogram(marker)
            if (
                    marker_histogram is not None
                    and target_avatar_histogram is not None):
                avatar_similarity = max(
                    0.0,
                    float(cv2.compareHist(
                        target_avatar_histogram,
                        marker_histogram,
                        cv2.HISTCMP_CORREL,
                    )),
                )
        marker_score = marker_saturation * (0.5 + 0.5 * avatar_similarity)

        drop_box = self.box_of_screen(
            MATERIAL_DROP_PREVIEW_X[0],
            max(0.185, row_y - 0.055),
            MATERIAL_DROP_PREVIEW_X[1],
            min(0.885, row_y + 0.055),
            name='material_drop_preview_without_experience',
        )
        drop_preview = drop_box.crop_frame(self.frame)
        icon_fingerprints = []
        for icon_index, (from_x, to_x) in enumerate(MATERIAL_DROP_ICON_X):
            icon_box = self.box_of_screen(
                from_x,
                max(0.185, row_y - 0.055),
                to_x,
                min(0.885, row_y + 0.055),
                name=f'material_drop_icon_{icon_index + 1}',
            )
            fingerprint = self._material_drop_fingerprint(
                icon_box.crop_frame(self.frame)
            )
            if fingerprint:
                icon_fingerprints.append(fingerprint)
        return {
            'target_marker_score': marker_score,
            'target_marker_saturation': marker_saturation,
            'target_avatar_similarity': avatar_similarity,
            'is_target_row': (
                marker_saturation >= 0.08
                and avatar_similarity >= 0.10
            ),
            'drop_fingerprint': self._material_drop_fingerprint(drop_preview),
            'material_icon_fingerprints': tuple(icon_fingerprints),
        }

    def _visible_material_locations(self, scroll_anchor):
        """Read the visible right-hand location rows on Material Acquisition."""
        action_boxes = self.ocr(
            box=self.box_of_screen(*MATERIAL_LOCATION_ACTION_BOX),
            match=MATERIAL_LOCATION_ACTION_TEXT,
            threshold=0.2,
        ) or []
        screen_height = max(self.height_of_screen(1), 1)
        target_avatar_histogram = (
            self._current_material_target_avatar_histogram()
        )
        locations = []
        for row_index, action_box in enumerate(action_boxes):
            row_y = (action_box.y + action_box.height / 2) / screen_height
            name_boxes = self.ocr(
                box=self.box_of_screen(
                    MATERIAL_LOCATION_NAME_X[0],
                    max(0.185, row_y - 0.075),
                    MATERIAL_LOCATION_NAME_X[1],
                    max(0.20, row_y - 0.012),
                ),
                threshold=0.2,
            ) or []
            location_name = ''.join(
                box.name for box in sorted(name_boxes, key=lambda box: box.x)
            )
            normalized_name = self._normalize_material_text(location_name)
            if not self._valid_material_location_name(location_name):
                self.log_debug(
                    f'ignore non-stage material row OCR: '
                    f'{location_name or "<empty>"} ({action_box.name})'
                )
                continue
            normalized_action = self._normalize_material_text(action_box.name)
            is_direct = any(
                direct_text in normalized_action
                for direct_text in MATERIAL_LOCATION_DIRECT_TEXT
            )
            location = {
                'name': location_name or f'row-{row_index + 1}',
                'normalized_name': normalized_name or f'row-{row_index + 1}',
                'action': action_box.name,
                'is_direct': is_direct,
                'scroll_anchor': scroll_anchor,
                'row_y': row_y,
                'row_index': row_index,
                'action_box': action_box,
            }
            location.update(self._material_row_visuals(
                row_y,
                target_avatar_histogram=target_avatar_histogram,
            ))
            locations.append(location)
        return locations

    def build_material_page_dictionary(
            self,
            category_name,
            force=False,
            visible_selector=None):
        """Index the current target's scrollable regional location list.

        The cache key includes the current cultivation target and resolution,
        so character changes and layout changes build a separate entry.
        ``visible_selector`` may return a currently visible row to stop the
        scan before that row moves away.
        """
        target_key = self.current_material_target_key(category_name)
        if not force and target_key in self._material_page_dictionary:
            return self._material_page_dictionary[target_key]

        locations_by_name_and_action = {}
        anonymous_locations = []
        selected_visible_location = None
        for scroll_anchor in MATERIAL_LOCATION_SCROLL_ANCHORS:
            self.click_relative(
                MATERIAL_LOCATION_SCROLL_X,
                scroll_anchor,
                after_sleep=0.7,
            )
            visible_locations = self._visible_material_locations(scroll_anchor)
            for location in visible_locations:
                if location['normalized_name'].startswith('row-'):
                    anonymous_locations.append(location)
                    continue
                # Keep one direct and one indirect occurrence of the same
                # material name. Universal materials such as Resonator EXP
                # appear in several regions; collapsing only by name can
                # accidentally retain a locked "Go" row and discard an
                # available "Challenge" row.
                key = (
                    location['normalized_name'],
                    location['is_direct'],
                )
                previous = locations_by_name_and_action.get(key)
                if previous is None:
                    location['observation_count'] = 1
                    locations_by_name_and_action[key] = location
                else:
                    observation_count = (
                        previous.get('observation_count', 1) + 1
                    )
                    # The same row can be clipped at one scrollbar anchor.
                    # Retain the observation with the clearest avatar marker
                    # while recording how consistently OCR saw the identity.
                    if (
                            location.get('target_marker_score', 0)
                            > previous.get('target_marker_score', 0)):
                        location['observation_count'] = observation_count
                        locations_by_name_and_action[key] = location
                    else:
                        previous['observation_count'] = observation_count
            if visible_selector is not None:
                indexed_locations = list(
                    locations_by_name_and_action.values()
                )
                indexed_locations.extend(anonymous_locations)
                selected_visible_location = visible_selector(
                    visible_locations,
                    indexed_locations,
                )
                if selected_visible_location is not None:
                    break

        locations = list(locations_by_name_and_action.values())
        if not locations:
            locations = anonymous_locations
        locations.sort(key=lambda location: (
            location['scroll_anchor'],
            location['row_y'],
        ))
        catalog = {
            'target_key': target_key,
            'category': category_name,
            'locations': locations,
            'selected_visible_location': selected_visible_location,
        }
        self._material_page_dictionary[target_key] = catalog
        self.info_set('Material locations indexed', len(locations))
        self.log_info(
            f'indexed {len(locations)} material location(s) for {target_key}'
        )
        return catalog

    @staticmethod
    def order_material_locations(locations, preferred_index=0):
        """Prefer verified direct challenges, then preserve configured order."""
        if not locations:
            return []
        preferred_index = max(0, min(preferred_index, len(locations) - 1))
        rotated = locations[preferred_index:] + locations[:preferred_index]
        direct = [location for location in rotated if location['is_direct']]
        indirect = [location for location in rotated if not location['is_direct']]
        return direct + indirect

    def enter_visible_material_location(self, selected):
        """Click a verified material row that is still visible."""
        self.log_info(
            f"select material location {selected['name']} "
            f"({selected['action']})"
        )
        # Re-read the row immediately before input; an old row coordinate can
        # select a different material after scrolling or a UI layout change.
        visible = self._visible_material_locations(selected.get('scroll_anchor', 0))
        verified = self._exact_material_location(selected, visible)
        if verified is None or not verified.get('action_box'):
            raise RuntimeError('material row changed before click; stop')
        self.click_box(verified['action_box'], after_sleep=1)
        if selected.get('is_direct'):
            # "Direct Challenge" opens the domain-detail/team flow directly.
            # Its close-button template is not stable across capture backends,
            # so start the already-known challenge flow instead of waiting for
            # a map/team-page template to prove the transition.
            self.log_info(
                'direct material challenge selected; continue through '
                'solo/team challenge pages'
            )
            return self.finish_domain_destination(is_team_page=True)

        destination = self.wait_feature(
            ['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'],
            time_out=10,
            settle_time=0.5,
            raise_if_not_found=True,
        )
        return self.finish_domain_destination(destination.name == 'team_close')

    def enter_material_location(self, location):
        """Restore and click one indexed material location."""
        self.click_relative(
            MATERIAL_LOCATION_SCROLL_X,
            location['scroll_anchor'],
            after_sleep=0.7,
        )
        visible_locations = self._visible_material_locations(
            location['scroll_anchor']
        )
        selected = self._exact_material_location(location, visible_locations)
        if selected is None:
            selected = self._search_material_location_by_scrolling(location)
        if selected is None:
            raise RuntimeError(
                f"material location disappeared after exact scroll search: "
                f"{location['name']} ({location['action']})"
            )

        return self.enter_visible_material_location(selected)

    @staticmethod
    def _exact_material_location(location, visible_locations):
        """Match the indexed row without substituting a nearby material.

        A stage can occur in both locked and unlocked regions. The action type
        is therefore part of the identity: a saved ``直接挑战`` row must never
        be restored as a nearby ``前往`` row.
        """
        return next(
            (
                visible
                for visible in visible_locations
                if (
                    visible['normalized_name'] == location['normalized_name']
                    and visible['is_direct'] == location['is_direct']
                )
            ),
            None,
        )

    def _search_material_location_by_scrolling(self, location):
        """Reset the material list, then scan downward for one exact row."""
        self.log_info(
            f"restore missed {location['name']} ({location['action']}); "
            "scan the material list from top"
        )
        probe_x, probe_y = MATERIAL_LOCATION_SCROLL_PROBE
        for _ in range(MATERIAL_LOCATION_SCROLL_RESET_ATTEMPTS):
            self.scroll_relative(
                probe_x,
                probe_y,
                MATERIAL_LOCATION_SCROLL_RESET_STEP,
            )
            self.sleep(0.03)
        self.sleep(0.7)

        for page_index in range(MATERIAL_LOCATION_SCROLL_MAX_PAGES):
            visible_locations = self._visible_material_locations(page_index)
            visible_summary = ', '.join(
                f"{visible['name']} ({visible['action']})"
                for visible in visible_locations
            ) or 'none'
            self.log_info(
                f"material scroll page {page_index + 1}: {visible_summary}"
            )
            selected = self._exact_material_location(
                location,
                visible_locations,
            )
            if selected is not None:
                self.log_info(
                    f"restored exact material location {selected['name']} "
                    f"({selected['action']}) on scroll page {page_index + 1}"
                )
                return selected

            self.scroll_relative(
                probe_x,
                probe_y,
                MATERIAL_LOCATION_SCROLL_STEP,
            )
            self.sleep(0.7)

        self.log_error(
            f"exact material location not found after scrolling: "
            f"{location['name']} ({location['action']})"
        )
        return None

    def leave_unavailable_domain_page(self, max_back_attempts=3):
        """Return from a known unavailable map destination to the guidebook.

        The first Esc commonly closes only the selected teleport-point panel,
        leaving the full map open. Since this method is called only from a
        positively identified map destination, bounded additional Esc presses
        are safe and necessary.
        """
        for attempt in range(1, max_back_attempts + 1):
            self.back(after_sleep=1)
            if self.wait_guidebook_page(time_out=1.5):
                self.log_info(
                    f'returned from unavailable destination to guidebook '
                    f'after {attempt} back attempt(s)'
                )
                return True
            if self.in_team_and_world():
                self.log_info(
                    f'returned from unavailable destination to world '
                    f'after {attempt} back attempt(s)'
                )
                self.open_materials_book()
                return True
        self.log_error('could not safely return from the unavailable domain page')
        return False

    def wait_book(self, feature="gray_book_all_monsters", time_out=3):
        gray_book_boss = self.wait_until(
            lambda: self.find_one(feature, box='box_gray_book',
                                  threshold=0.3),
            time_out=time_out, settle_time=1)
        logger.info(f'found gray_book_boss {gray_book_boss}')
        # if self.debug:
        #     self.screenshot(feature)
        return gray_book_boss

    def check_main(self):
        if not self.in_team()[0]:
            self.click_relative(0, 0)
            self.send_key('esc')
            self.sleep(1)
            if not self.in_team()[0]:
                raise Exception('must be in game world and in teams')
        return True

    def _find_book_scroll_top(self):
        box = self.box_of_screen(0.969, 0.191, 0.978, 0.271, name="bar")
        self.draw_boxes(boxes=box, color="blue")
        min_width = self.width_of_screen(5 / 2560)
        min_height = self.height_of_screen(10 / 1440)
        boxes = find_color_rectangles(self.frame, book_bar_color, min_width, min_height, threshold=0.8, box=box)
        if not boxes:
            return 424 / 2160
        bar = boxes[0]
        self.draw_boxes(boxes=bar, color="red")
        bar_top = bar.y / self.height
        return bar_top

    def click_on_book_target(self, serial_number: int, total_number: int, structure: list[int] = None):
        def get_cross_count(structure, sn):
            current_sum = 0
            cross_count = 0
            for s in structure:
                current_sum += s
                if sn > current_sum:
                    cross_count += 1
                else:
                    break
            return cross_count

        self.sleep(0.5)
        bar_bottom = 0.8806
        bar_x = 0.9730
        separator = 0.01
        cross_count = 0
        container_max_rows = 4
        target_index = -1

        bar_top = self._find_book_scroll_top()

        if serial_number <= container_max_rows:
            target_index = serial_number - 1
        else:
            container_h = bar_bottom - bar_top
            if structure:
                cross_count = get_cross_count(structure, serial_number)
                cross_count += 1
                container_h -= len(structure) * separator
            item_h = container_h / total_number
            height = item_h * serial_number
            to_click_y = min(bar_top + height + cross_count * separator, bar_bottom)
            self.click(bar_x, to_click_y, after_sleep=1)
        btns = self.find_feature('boss_proceed', box=self.box_of_screen(0.9113, 0.229, 0.9613, 0.861), threshold=0.8)
        if not btns:
            raise Exception("can't find boss_proceed")
        if target_index > -1:
            target = btns[target_index]
        else:
            target = max(btns, key=lambda box: box.y)
        self.draw_boxes(boxes=target, color="red")
        self.click(target, after_sleep=1)
        feature = self.wait_feature(['fast_travel_custom', 'gray_teleport', 'remove_custom', 'team_close'], time_out=10,
                                    settle_time=0.5, raise_if_not_found=True)
        return feature.name == 'team_close'

    def change_time_to_night(self):
        logger.info('change time to night')
        self.send_key("esc")
        self.sleep(1)
        self.click_relative(0.71, 0.96)
        self.sleep(2)
        self.click_relative(0.19, 0.14)
        self.sleep(1)

        # 调整时间到晚上
        for _ in range(3):
            self.click_relative(0.82, 0.53)
            self.sleep(1)

        self.click_relative(0.52, 0.90)
        self.sleep(6)
        self.send_key("esc")
        self.sleep(1)
        self.send_key("esc")
        self.sleep(1)

    def jump(self, after_sleep=0.01):
        self.send_key(self.key_config.get('Jump Key'), after_sleep=after_sleep)


book_bar_color = {
    "r": (190, 255),
    "g": (190, 255),
    "b": (190, 255),
}

echo_color = {
    'r': (200, 255),  # Red range
    'g': (150, 220),  # Green range
    'b': (130, 170)  # Blue range
}


def calculate_angle_clockwise(box1, box2):
    """
    Calculates angle (radians) from horizontal right to line (x1,y1)->(x2,y2).
    Positive clockwise, negative counter-clockwise.
    """
    x1, y1 = box1.center()
    x2, y2 = box2.center()
    dx = x2 - x1
    dy = y2 - y1
    # math.atan2(dy, dx) gives angle from positive x-axis, positive CCW.
    # Negate for positive CW convention.

    degree = math.degrees(math.atan2(dy, dx))
    if degree < 0:
        degree += 360
    return degree


lower_white = np.array([244, 244, 244], dtype=np.uint8)
lower_white_none_inclusive = np.array([240, 240, 240], dtype=np.uint8)
upper_white = np.array([255, 255, 255], dtype=np.uint8)
black = np.array([0, 0, 0], dtype=np.uint8)


def isolate_white_text_to_black(cv_image):
    """
    Converts pixels in the near-white range (244-255) to black,
    and all others to white.
    Args:
        cv_image: Input image (NumPy array, BGR).
    Returns:
        Black and white image (NumPy array), where matches are black.
    """
    match_mask = cv2.inRange(cv_image, black, lower_white_none_inclusive)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)

    return output_image


def convert_bw(cv_image):
    match_mask = cv2.inRange(cv_image, lower_white, upper_white)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)
    return output_image


lower_icon_white = np.array([210, 210, 210], dtype=np.uint8)
upper_icon_white = np.array([244, 244, 244], dtype=np.uint8)


def convert_dialog_icon(cv_image):
    match_mask = cv2.inRange(cv_image, lower_icon_white, upper_icon_white)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)
    return output_image


def binarize_for_matching(image, threshold=244):
    """
    Converts a colored image to a binary image based on a brightness threshold.

    The rule is: pixels with a value of 240-255 become pure white (255),
    and all other pixels become pure black (0).

    Args:
        image (np.array): The input BGR image from OpenCV.

    Returns:
        np.array: The resulting binary image (single channel, 8-bit).
    """
    # Convert the image to grayscale for a single brightness value per pixel.
    # This is more robust than checking individual R, G, B channels.

    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply the binary threshold.
    # Pixels > 239 will be set to 255 (white).
    # Pixels <= 239 will be set to 0 (black).
    # cv2.THRESH_BINARY is the type of thresholding we want.
    _, binary_image = cv2.threshold(gray_image, threshold, 255, cv2.THRESH_BINARY)
    return binary_image
