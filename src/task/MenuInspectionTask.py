"""Bounded menu inspection with the normal controller lease and foreground guard.

Each click is selected by the operator from a saved frame and requires a
fresh page-title match. This adapter does not perform combat or claim rewards.
"""
import json
import math
from pathlib import Path
import re
import time

import cv2

from src.task.SafeMaterialTask import SafeMaterialTask


MENU_ACTIONS = ('inspect', 'terminal', 'text', 'point', 'back', 'scroll')


def validate_menu_steps(steps, require_expect=True):
    """Validate the entire queue before any menu input can be sent."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise ValueError('菜单步骤必须是包含 1–64 项的 JSON 数组')
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) - {
                'action', 'expect', 'target', 'point', 'after_expect', 'scroll'}:
            raise ValueError(f'菜单第 {index} 步包含未知字段或不是对象')
        action = step.get('action')
        if action not in MENU_ACTIONS:
            raise ValueError(f'菜单第 {index} 步动作无效')
        for key in ('expect', 'after_expect', 'target'):
            if not isinstance(step.get(key, ''), str):
                raise ValueError(f'菜单第 {index} 步 {key} 必须是文本')
        if (require_expect or action not in ('inspect', 'terminal')) and not step.get('expect', '').strip():
            raise ValueError(f'菜单第 {index} 步缺少可见 expect 锚点')
        for key in ('expect', 'after_expect'):
            if step.get(key):
                try:
                    re.compile(step[key])
                except re.error as exc:
                    raise ValueError(f'菜单第 {index} 步 {key} 正则无效：{exc}') from exc
        if action == 'text' and not step.get('target', '').strip():
            raise ValueError(f'菜单第 {index} 步缺少点击目标文本')
        if action in ('point', 'scroll'):
            point = step.get('point')
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or any(isinstance(x, bool) or not isinstance(x, (int, float))
                           or not math.isfinite(x) or not 0 <= x <= 1 for x in point)):
                raise ValueError(f'菜单第 {index} 步坐标必须位于当前截图内')
        if action == 'scroll':
            count = step.get('scroll')
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= abs(count) <= 12:
                raise ValueError(f'菜单第 {index} 步 scroll 必须为非零整数，绝对值不超过 12')
    return steps


class MenuInspectionTask(SafeMaterialTask):
    menu_action = 'inspect'
    menu_expect = ''
    menu_point = None
    menu_scroll = None
    menu_after_expect = ''
    menu_steps = None

    def save_menu_observation(self, label, refresh=True):
        if refresh:
            self.next_frame()
        path = Path('logs/menu-inspection') / f'{time.time_ns()}-{label}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = self.frame.copy()
        cv2.imwrite(str(path), frame)
        cv2.imwrite('logs/menu-latest.png', frame)
        rows = [dict(text=b.name, x=b.x, y=b.y, width=b.width, height=b.height)
                for b in self.ocr(0, 0, 1, 1, frame=frame)]
        record = {'label': label, 'image': str(path), 'size': list(frame.shape[:2]), 'text': rows}
        self.result.setdefault('observations', []).append(record)
        return record

    def wait_menu_anchor(self, pattern, timeout=3, settle_time=.3):
        expression = re.compile(pattern)

        def unique_anchor():
            matches = [box for box in self.ocr(0, 0, 1, 1, frame=self.frame)
                       if expression.fullmatch(re.sub(r'\s+', '', box.name).translate(
                           str.maketrans('兌換', '兑换')))]
            return matches[0] if len(matches) == 1 else None

        anchor = self.wait_until(unique_anchor, time_out=timeout, settle_time=settle_time,
                                 raise_if_not_found=False)
        if not anchor:
            raise RuntimeError(f'当前菜单锚点未唯一确认；停止后续输入：{pattern}')
        return anchor

    def execute_menu_step(self, step):
        action = step['action']
        if step.get('expect'):
            self.wait_menu_anchor(step['expect'])
        if action == 'terminal':
            if not self.in_team_and_world():
                raise RuntimeError('终端入口需要大世界队伍画面')
            self.send_key('esc')
        elif action == 'text':
            target = self.wait_menu_anchor(re.escape(step['target']))
            self.click_box(target)
        elif action in ('point', 'scroll'):
            # These are coordinates observed in the full saved viewport, not
            # coordinates on the framework's 16:9 template canvas.
            x, y = (self.width * step['point'][0], self.height * step['point'][1])
            if action == 'point':
                self.click(x, y, name='verified menu point')
            else:
                self.scroll(int(x), int(y), step['scroll'])
        elif action == 'back':
            self.send_key('esc')
        # Titles can render before the party/character transition accepts
        # input. Leave the native menu animation time to finish as well.
        self.sleep(2.5)
        if step.get('after_expect'):
            self.wait_menu_anchor(step['after_expect'], timeout=5, settle_time=.5)

    def run(self):
        self.result = {'status': 'running', 'phase': self.phase,
                       'action': 'batch' if self.menu_steps is not None else self.menu_action}
        try:
            batch = self.menu_steps is not None
            steps = validate_menu_steps(self.menu_steps if batch else [{
                'action': self.menu_action, 'expect': self.menu_expect,
                'target': self.expected_target, 'point': self.menu_point,
                'scroll': self.menu_scroll, 'after_expect': self.menu_after_expect}],
                require_expect=batch)
            self.result['steps'] = []
            # A pending spend must still permit observing its result. Only a
            # queue made entirely of input-free inspections may run here;
            # mixed queues and every menu action retain the spending guard.
            if any(step['action'] != 'inspect' for step in steps):
                self.assert_no_pending_refill()
            for index, step in enumerate(steps, 1):
                prefix = f'step-{index:02d}-' if batch else ''
                record = {'index': index, **step, 'status': 'running'}
                self.result['steps'].append(record)
                try:
                    self.focus_material_menu()
                    record['before'] = self.save_menu_observation(prefix + 'before')['image']
                    self.execute_menu_step(step)
                    # Keep the exact frame whose destination anchor passed.
                    record['after'] = self.save_menu_observation(
                        prefix + 'after', refresh=not bool(step.get('after_expect')))['image']
                    record['status'] = 'menu_observed'
                except BaseException as exc:
                    record.update(status='stopped', error=str(exc))
                    try:
                        record['after'] = self.save_menu_observation(prefix + 'after-failed')['image']
                    except BaseException:
                        pass  # Preserve the original failure, including cancellation.
                    raise
                self.save_menu_result()
            self.result['status'] = 'menu_observed'
        except BaseException as exc:
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            try:
                self.mouse_up()
            finally:
                self.save_menu_result()

    def save_menu_result(self):
        Path('logs/menu-latest.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2) + '\n')
