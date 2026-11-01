"""Select saved party numbers through fresh menu anchors and verify live members."""
import re
import time
from pathlib import Path

import cv2
from ok import Box

from src.task.CultivationTargetUI import viewport
from src.task.DesktopPreflightTask import require_safe_world, observe_members, trusted_members
from src.task.MaterialImageOCR import read_enlarged_region


def find_number_image(frame, number):
    template = cv2.imread(str(Path(__file__).resolve().parents[2] / 'assets/preset-team-digits' / f'{number:02}.png'), 0)
    if template is None:
        return None
    height, width = frame.shape[:2]
    scale = width / 1920
    template = cv2.resize(template, None, fx=scale, fy=scale)
    left, top = round(width*.015), round(height*.09)
    region = cv2.cvtColor(frame[top:round(height*.87), left:round(width*.075)], cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(scores)
    scores[max(0, point[1]-template.shape[0]):point[1]+template.shape[0], :] = -1
    second = cv2.minMaxLoc(scores)[1]
    if score < .93 or score-second < .07 or top+point[1] < .14*height:
        return None
    return Box(left+point[0], top+point[1], template.shape[1], template.shape[0], score, f'{number:02}')


def parse_team_numbers(value):
    parts = str(value).replace('，', ',').split(',')
    if not parts or any(not re.fullmatch(r'\s*(?:[1-9]|10)\s*', s) for s in parts):
        raise ValueError('队伍编号须为1–10，以逗号分隔')
    numbers = tuple(int(s) for s in parts)
    if len(numbers) != len(set(numbers)):
        raise ValueError('队伍编号不能重复')
    return numbers


class PresetTeamUI:
    def __init__(self, task):
        self.task = task

    def anchor(self, pattern, region=(0, 0, 1, 1), timeout=4):
        box = self.task.menu_text(pattern, region, timeout=timeout, viewport=True)
        if not box:
            raise RuntimeError(f'编队页面未确认：{pattern}')
        return box

    def select(self, number):
        if number not in range(1, 11):
            raise ValueError('编队编号无效')
        task = self.task
        task.assert_no_pending_refill()
        if task.menu_text('编队队伍名称', (.2, .25, .8, .4), timeout=.3, viewport=True):
            task.click_box(self.anchor('取消', (.22, .57, .46, .69)), after_sleep=.7)
        if task.menu_text('快速编队', (.55, .8, .8, .97), timeout=.3, viewport=True):
            task.send_key('esc', after_sleep=1)
        task.return_to_world()
        require_safe_world(task)
        task.send_key('esc', after_sleep=1)
        self.anchor('终端', (0, 0, .25, .15))
        task.click_box(self.anchor('编队'), after_sleep=2)
        self.anchor('快速编队', (.55, .8, .8, .97))
        # Scroll only the saved-number strip. Never click party member cards.
        # This list scrolls in small animated increments and opens near the
        # active preset; allow enough bounded steps to reach either endpoint.
        for attempt in range(32):
            task.next_frame()
            title = task.menu_text(rf'.*队伍0?{number}[^0-9]*', (0, 0, .25, .12), timeout=.3, viewport=True)
            if title:
                break
            # Exclude the decorative strokes left of the two-digit label;
            # otherwise the font's 0 is often recognized as ')'.
            candidates = [b for b in read_enlarged_region(task, viewport(task, 50/1920, .09, 125/1920, .87))
                          if b.y >= .14*task.height and b.y+b.height < .87*task.height
                          and re.fullmatch(r'0?[1-9]|10', re.sub(r'\s+', '', b.name))]
            wanted = [b for b in candidates if int(re.sub(r'\s+', '', b.name)) == number]
            if not wanted:
                image_match = find_number_image(task.frame, number)
                if image_match:
                    wanted = [image_match]
            task.log_info(f'保存队伍编号识别：请求={number}，候选={[(b.name, round(b.confidence, 3)) for b in candidates]}，匹配={wanted}')
            if len(wanted) == 1:
                task.click_box(wanted[0], after_sleep=2)
                self.anchor(rf'.*队伍0?{number}[^0-9]*', (0, 0, .25, .12))
                break
            values = [int(re.sub(r'\s+', '', b.name)) for b in candidates]
            if not values:
                raise RuntimeError('保存队伍编号未识别；没有按猜测位置点击')
            direction = 3 if number < min(values) else -3
            task.scroll_relative(.045, .45, direction)
            task.sleep(.8)
        else:
            raise RuntimeError(f'未找到保存队伍{number}')
        self.anchor(rf'.*队伍0?{number}[^0-9]*', (0, 0, .25, .12))
        path = Path('logs/cross-team') / f'{time.time_ns()}-team-{number}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), task.frame)
        active = task.menu_text('已出战', (.76, .84, .98, .97), timeout=.5, viewport=True)
        if active:
            task.send_key('esc', after_sleep=1)
        else:
            task.click_box(self.anchor('出战', (.76, .84, .98, .97)), after_sleep=2)
        if not task.wait_until(task.in_team_and_world, time_out=10, raise_if_not_found=False):
            raise RuntimeError(f'队伍{number}出战后未返回大世界')
        members = []
        for attempt in range(3):
            task.sleep(1)
            require_safe_world(task)
            members = observe_members(task)
            if trusted_members(members):
                break
            task.log_info(f'队伍{number}退出菜单后头像未稳定，第{attempt + 1}次：{members}')
            if attempt == 1:
                # The active portrait's white selection halo can obscure an
                # otherwise registered template. Switch only to an already
                # recognized member in the safe overworld, then read all three
                # again; never substitute an old identity or lower the threshold.
                active = task.in_team()[1]
                if 0 <= active < len(members) and not members[active]['registered']:
                    known = [m for m in members if m['registered'] and m['confidence'] >= .8]
                    if known:
                        require_safe_world(task)
                        task.send_key(str(known[0]['slot']), after_sleep=1)
        else:
            raise RuntimeError(f'队伍{number}三人身份未完整识别')
        return {'number': number, 'members': members, 'evidence': str(path)}
