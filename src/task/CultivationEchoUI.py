"""Read the live cultivation Sonata name and verify the guidebook filter."""
from pathlib import Path
import re
import time

import cv2
from src.task.CultivationTargetUI import viewport


def sonata_name_from_boxes(boxes, width, height):
    """Associate a set name with its own Echo cultivation atlas row."""
    labels = [b for b in boxes if b.name.strip() == '声骸培养']
    atlas = [b for b in boxes if b.name.strip() == '合鸣图鉴']
    if len(labels) != 1 or len(atlas) != 1 or atlas[0].y <= labels[0].y:
        raise RuntimeError('当前角色的声骸培养/合鸣图鉴行未唯一确认。')
    names = [b.name.strip() for b in boxes
             if .37*width < b.x < .80*width
             and abs(b.y-atlas[0].y) < .025*height
             and re.fullmatch(r'[\u4e00-\u9fff·・]{3,24}', b.name.strip())
             and b.name.strip() not in ('合鸣图鉴', '切换方案', '声骸培养')]
    if len(names) != 1:
        raise RuntimeError('声骸培养的合鸣套装名称未唯一确认。')
    return names[0]


class CultivationEchoUI:
    def cultivation_target_verified(self, name):
        """Bound transient single-glyph OCR misses without accepting a mismatch."""
        def verified():
            self.next_frame()
            return self.material_target_matches(name)
        return bool(self.wait_until(verified, time_out=4, raise_if_not_found=False))

    def verify_selected_sonata(self, name, sonata):
        # Selecting a radio item can leave the dropdown open. Click only the
        # observed non-spending section heading outside it, then re-read both
        # role and filter on fresh frames; Escape could leave the whole book.
        heading = self.menu_text(r'^合鸣套装筛选$', (.35, .16, .60, .25), timeout=1)
        if not heading:
            return False
        self.click_box(heading, after_sleep=.4)
        def verified():
            self.next_frame()
            return self.material_target_matches(name) and self.menu_text(
                re.escape(sonata), (.73, .16, .96, .25), timeout=.3)
        return bool(self.wait_until(verified, time_out=3, raise_if_not_found=False))

    def save_echo_observation(self, label, **detail):
        folder = Path('logs/cultivation-echo-scan')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{time.time_ns()}-{label}.png'
        if not cv2.imwrite(str(path), self.frame):
            raise RuntimeError('声骸培养核对截图保存失败。')
        self.result.setdefault('sonata_checks', []).append({'kind': label, 'evidence': str(path), **detail})

    def read_target_sonata(self, name):
        title = self.menu_text(r'^培养目标$', (.13, .10, .31, .19), timeout=2)
        if not title:
            raise RuntimeError('培养目标卡片未确认。')
        self.click_box(title, after_sleep=.8)
        for attempt in range(6):
            self.next_frame()
            boxes = self.ocr(box=viewport(self, .25, .14, .99, .94), target_height=self.height*2)
            self.save_echo_observation('cultivation', target=name, text=[b.name for b in boxes])
            try:
                result = sonata_name_from_boxes(boxes, self.width, self.height)
            except RuntimeError:
                if attempt == 5:
                    raise
                self.scroll_relative(.93, .70, -12)
                self.sleep(.8)
            else:
                if not self.cultivation_target_verified(name):
                    raise RuntimeError('读取合鸣套装后培养角色发生变化。')
                return result

    def select_sonata_filter(self, name, sonata):
        self.open_boss_book('wuyin')
        selected = self.menu_text(re.escape(sonata), (.73, .16, .96, .25), timeout=1)
        if selected:
            verified = self.verify_selected_sonata(name, sonata)
            self.save_echo_observation('filter-result', target=name, sonata=sonata,
                                       text=[sonata], verified=verified)
            if not verified:
                raise RuntimeError('合鸣筛选结果或培养目标未核对；未进入关卡。')
            return
        header = self.menu_text(r'合鸣筛选[/／].+|[\u4e00-\u9fff·・]{3,24}', (.73, .16, .96, .25), timeout=3)
        if not header:
            raise RuntimeError('无音区合鸣筛选入口未确认。')
        self.click_box(header, after_sleep=.7)
        option = None
        for attempt in range(16):
            self.next_frame()
            words = [b.name for b in self.ocr(.73, .25, .97, .80)]
            self.save_echo_observation('filter-open', target=name, sonata=sonata, text=words)
            option = self.menu_text(re.escape(sonata), (.73, .25, .97, .80), timeout=.5)
            if option:
                break
            self.scroll_relative(.90, .60, -12)
            self.sleep(.7)
        if not option:
            raise RuntimeError(f'合鸣筛选中未核对到当前角色的{sonata}；未进入关卡。')
        self.click_box(option, after_sleep=.5)
        verified = self.verify_selected_sonata(name, sonata)
        self.save_echo_observation('filter-result', target=name, sonata=sonata,
                                   text=[b.name for b in self.ocr(0, 0, 1, 1)], verified=bool(verified))
        if not verified:
            raise RuntimeError('合鸣筛选结果或培养目标未核对；未进入关卡。')
