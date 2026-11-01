"""Read complete cultivation lists using verified material icons as identity."""
import re
import time
import json
from datetime import datetime
from pathlib import Path

import cv2

from src.task.CultivationTargetUI import viewport, required_jobs
from src.task.MaterialIdentity import MaterialIconLibrary, popup_identity, named_job_key
from src.task.MaterialImageOCR import read_enlarged_region
from src.task.MaterialTileVision import MaterialPageReadError, material_tiles, counters_for_row, verify_material_rows


LABELS = {'武器/技能': '武器与技能素材', '突破': '共鸣者突破材料',
          '周本': '技能升级材料', '角色经验': '共鸣者经验材料',
          '武器经验': '武器经验材料', '贝币': '贝币', '采集': '突破材料'}


def row_counters(boxes, row, width):
    return sorted((b for b in boxes if .55*width < b.x < .87*width
                   and -.012*width < b.y-row.y < .040*width
                   and re.fullmatch(r'\d{1,7}[/／]\d{1,7}', re.sub(r'\s+', '', b.name))), key=lambda b: b.x)


class NamedMaterialScanner:
    def __init__(self, task):
        self.task = task
        self.library = MaterialIconLibrary(geometry_version='tile-v1')
        self.folder = Path('logs/named-material-scans') / str(time.time_ns())
        self.folder.mkdir(parents=True, exist_ok=True)

    def identify(self, target, counter, frame):
        task = self.task
        tile = getattr(counter, 'material_tile', None)
        if tile is None:
            raise MaterialPageReadError('材料卡片边框未确认；禁止根据文字位置猜测图标')
        x, y = tile.x+tile.width/2, tile.y+tile.height*.4
        icon = tile.icon(frame)
        match = self.library.match(icon)
        if match:
            return match
        # A missed small name glyph in one frame is not proof of a target
        # change. Require a fresh positive reading before any detail click.
        if not task.wait_until(lambda: task.material_target_matches(target),
                               time_out=3, raise_if_not_found=False):
            observation = getattr(task, '_material_target_observation', {})
            raise MaterialPageReadError(f'读取图标前培养目标未确认；重读后仍不匹配：{observation}')
        task.click(x, y, name='核对材料图标详情', after_sleep=.6)
        task.next_frame()
        evidence = self.folder / f'{time.time_ns()}-detail.png'
        cv2.imwrite(str(evidence), task.frame)
        if not task.menu_text('点击空白区域关闭', (.25, .8, .8, .98), timeout=2, viewport=True):
            raise MaterialPageReadError('材料图标未打开物品详情；停止猜测点击')
        readings = []
        for _ in range(2):
            task.next_frame()
            rows = read_enlarged_region(task, viewport(task, .37, .135, .64, .187), contrast=True)
            rows += read_enlarged_region(task, viewport(task, .37, .33, .53, .39), contrast=True)
            try:
                readings.append(popup_identity(rows, task.height))
            except RuntimeError as exc:
                raise MaterialPageReadError(str(exc)) from exc
            task.sleep(.2)
        if readings[0] != readings[1]:
            raise MaterialPageReadError('材料名称或库存两帧不一致')
        name, inventory = readings[0]
        expected = int(re.split(r'[/／]', re.sub(r'\s+', '', counter.name))[0])
        if inventory != expected:
            raise MaterialPageReadError(f'{name}详情库存{inventory}与培养页{expected}不一致')
        task.click(task.width*.70, task.height*.92, name='关闭已核对材料详情', after_sleep=.4)
        if not task.wait_until(lambda: task.material_target_matches(target), time_out=3, raise_if_not_found=False):
            raise MaterialPageReadError('材料详情关闭后目标未确认')
        self.library.remember(name, icon, evidence)
        return name

    def page(self, target):
        for attempt in range(3):
            try:
                return self.read_page(target)
            except MaterialPageReadError as exc:
                evidence = self.folder / f'{time.time_ns()}-page-error.png'
                cv2.imwrite(str(evidence), self.task.frame)
                event = {'target': target, 'attempt': attempt+1, 'error': str(exc), 'image': str(evidence)}
                with (self.folder/'errors.jsonl').open('a') as stream:
                    stream.write(json.dumps(event, ensure_ascii=False)+'\n')
                self.task.log_info(f'材料页重读：{event}')
                if attempt == 2:
                    raise
                # Close only a positively identified detail popup. Do not
                # reopen menus, change the target or scroll on a failed read.
                if self.task.menu_text('点击空白区域关闭', (.25, .8, .8, .98), timeout=.5, viewport=True):
                    self.task.click(self.task.width*.70, self.task.height*.92,
                                    name='关闭待重读材料详情', after_sleep=.4)
                self.task.sleep(.3)

    def read_page(self, target):
        task = self.task
        task.next_frame()
        if not task.wait_until(lambda: task.material_target_matches(target),
                               time_out=3, raise_if_not_found=False):
            raise MaterialPageReadError(f'读取材料页前目标未确认：{getattr(task, "_material_target_observation", {})}')
        image = task.frame.copy()
        cv2.imwrite(str(self.folder / f'{time.time_ns()}-list.png'), image)
        # Large row headings use native pixels; small fractions are enlarged
        # separately from each image-detected card in the same frozen frame.
        boxes = task.ocr(box=viewport(task, .25, .15, .99, .94), frame=image)
        boxes = [b for b in boxes if not re.fullmatch(r'\d*[/／]\d+', re.sub(r'\s+', '', b.name))]
        tiles = material_tiles(image)
        boxes = verify_material_rows(task, boxes, tiles, LABELS.values(), image)
        for row in list(boxes):
            if row.name.strip() in LABELS.values() and .25*task.width < row.x < .65*task.width:
                boxes.extend(counters_for_row(task, row, tiles, image))
        jobs = required_jobs(boxes, target, task.width)
        # Flowers/overworld breakthrough items are displayed separately from bosses.
        for row in boxes:
            if row.name.strip() == '突破材料' and .25*task.width < row.x < .65*task.width:
                counters = row_counters(boxes, row, task.width)
                jobs.append({'target': target, 'kind': '采集', 'cost': 40, 'repeat': 0,
                             'route': {'category': '', 'fallback_stage_name': ''},
                             'material_counts': [list(map(int, re.split(r'[/／]', re.sub(r'\s+', '', b.name)))) for b in counters],
                             'satisfied': False, 'deferred_reason': '野外采集路线尚未适配'})
        for job in jobs:
            rows = sorted((b for b in boxes if b.name.strip() == LABELS[job['kind']]
                           and .25*task.width < b.x < .65*task.width), key=lambda b: b.y)
            row = rows[job.get('repeat', 0)]
            counters = row_counters(boxes, row, task.width)
            if not counters:
                job['deferred_reason'] = '材料数量待识别，未确认完成'
                continue
            job['material_counts'] = [list(map(int, re.split(r'[/／]', re.sub(r'\s+', '', b.name)))) for b in counters]
            job['material_names'] = [self.identify(target, counter, image) for counter in counters]
            job['identity_source'] = 'verified_icon'
            job['observed_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
            job['satisfied'] = all(a >= b for a, b in job['material_counts'])
        complete = any(b.name.strip() == '声骸培养' for b in boxes)
        if not jobs and not complete:
            raise MaterialPageReadError('材料页未识别到需求或列表末尾')
        return jobs, complete

    def scan(self, target):
        task = self.task
        task.open_materials_book()
        task.select_material_target_with_recovery(target)
        task.reset_material_list_top()
        collected = {}
        complete = False
        for page_index in range(16):
            jobs, complete = self.page(target)
            for job in jobs:
                key = named_job_key(job)
                if key in collected:
                    old = collected[key]
                    if old['material_counts'] != job['material_counts']:
                        raise RuntimeError(f'{target}的同名材料在翻页时读数冲突')
                    continue
                # The first domain row remains an internal navigation anchor.
                # Every queued item and refresh is keyed by verified names.
                job['repeat'] = sum(j['kind'] == job['kind'] for j in collected.values())
                if job['kind'] == '武器/技能' and job['repeat'] > 0:
                    job['deferred_reason'] = '野外素材采集适配尚未完成'
                collected[key] = job
            if complete:
                break
            # A four-line native scroll moves only a small fraction of a card
            # in this list. Keep overlap while advancing enough to reach long
            # cultivation plans; completion still requires the footer anchor.
            task.scroll_relative(.93, .70, -24)
            task.sleep(1)
        if not complete or not collected:
            raise RuntimeError(f'{target}材料列表未完整扫描到底部，未将未读项目视为完成')
        return list(collected.values())
