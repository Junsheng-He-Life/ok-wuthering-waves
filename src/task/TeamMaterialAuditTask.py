"""Read named material requirements and global inventory without claiming."""
import json
import re
import time
from pathlib import Path

import cv2
from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.CultivationTargetUI import viewport


class TeamMaterialAuditTask(TeamMaterialTask):
    def run(self):
        if self.exact_stage == 'queue-review':
            return self.review_queue()
        self.result = {'status': 'running', 'items': [], 'targets': []}
        folder = Path('logs/material-audit') / str(time.time_ns())
        folder.mkdir(parents=True, exist_ok=True)
        self.result['folder'] = str(folder)
        if self.exact_stage == 'bottom' and Path('logs/material-audit-latest.json').exists():
            previous = json.loads(Path('logs/material-audit-latest.json').read_text())
            self.result['items'] = previous['items']
            self.result['previous_audit_folder'] = previous['folder']
        def save():
            (folder / 'audit.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2))
        try:
            self.assert_no_pending_refill()
            self.return_to_world()
            names = [self.expected_target] if self.expected_target else ['心', '卜灵', '今汐']
            for name in names:
                self.open_materials_book()
                self.select_material_target_with_recovery(name)
                if self.exact_stage == 'bottom':
                    self.click(self.width*.974, self.height*.85, name="材料列表滚动条下部", after_sleep=1)
                for page in range(1 if self.exact_stage == 'bottom' else 3):
                    self.sleep(.8)
                    self.next_frame()
                    cv2.imwrite(str(folder / f'{name}-{page}-list.png'), self.frame)
                    boxes = self.ocr(box=viewport(self, .25, .15, .99, .94), target_height=self.height*2)
                    self.result['targets'].append({'name': name, 'text': [b.name for b in boxes]})
                    # Small isolated single-item counters need a separate crop.
                    labels = [b for b in boxes if b.x < self.width*.6 and b.name.strip() in
                              ('武器与技能素材', '技能升级材料', '共鸣者突破材料', '突破材料')]
                    for label in labels:
                        crop = viewport(self, .55, max(.15, label.y/self.height+.015),
                                        .87, min(.94, label.y/self.height+.075))
                        extra = self.ocr(box=crop, target_height=self.height*3)
                        for candidate in extra:
                            if not any(abs(candidate.x-b.x)<18 and abs(candidate.y-b.y)<15
                                       and candidate.name==b.name for b in boxes):
                                boxes.append(candidate)
                    counts = []
                    for b in boxes:
                        m = re.fullmatch(r'(\d+)[/／](\d+)', re.sub(r'\s+', '', b.name))
                        if m and .55*self.width < b.x < .87*self.width:
                            counts.append((b, int(m[1]), int(m[2])))
                    for index, (box, owned, needed) in enumerate(counts):
                        if not self.material_target_matches(name):
                            raise RuntimeError('audit target changed before item inspection')
                        self.click(box.x + box.width/2, box.y - self.height*.025, after_sleep=.5)
                        detail = self.ocr(box=viewport(self, .35, .10, .68, .90), target_height=self.height*2)
                        words = [b.name for b in detail]
                        headers = [b for b in detail if b.y < self.height*.21
                                   and re.search(r'[\u4e00-\u9fff]', b.name)]
                        title = min(headers, key=lambda b: b.y).name if headers else ''
                        owned_detail = []
                        for word in words:
                            match = re.fullmatch(r'拥有[：:]?(\d+)', re.sub(r'\s+', '', word))
                            if match:
                                owned_detail.append(int(match[1]))
                        if not owned_detail:
                            match = re.search(r'拥有[：:]?(\d+)', re.sub(r'\s+', '', ''.join(words)))
                            if match:
                                owned_detail.append(int(match[1]))
                        row = {'target': name, 'item_name': title, 'required': needed,
                               'displayed_owned': owned,
                               'inventory': owned_detail[0] if len(owned_detail)==1 else None,
                               'detail_text': words, 'counter_position': [box.x, box.y]}
                        if not any(r['target']==name and r['item_name']==title and r['required']==needed
                                   for r in self.result['items']):
                            self.result['items'].append(row)
                        cv2.imwrite(str(folder / f'{name}-{page}-{index:02d}.png'), self.frame)
                        save()
                        self.click(self.width*.70, self.height*.92, after_sleep=.4)
                        if not self.wait_until(lambda: self.material_target_matches(name),
                                               time_out=3, raise_if_not_found=False):
                            raise RuntimeError('item detail did not close; audit paused without spending')
                    self.scroll_relative(.93, .70, -4)
                    self.sleep(1)
                self.scroll_relative(.93, .70, 100)
                self.sleep(.8)
            self.result['status'] = 'audit_completed'
            self.return_to_world()
        except Exception as exc:
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            save()
            Path('logs/material-audit-latest.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2))

    def review_queue(self):
        from src.task.CultivationTargetUI import required_jobs
        result = {'status': 'running', 'targets': []}
        folder = Path('logs/material-status/queue-review')
        folder.mkdir(parents=True, exist_ok=True)
        self.assert_no_pending_refill()
        self.return_to_world()
        for name in ['心', '卜灵', '今汐']:
            self.open_materials_book()
            self.select_material_target_with_recovery(name)
            target = {'name': name, 'pages': []}
            self.next_frame()
            import numpy as np
            sx = round(self.width*.974)
            ys = np.flatnonzero(np.min(self.frame[round(self.height*.13):round(self.height*.88),sx],axis=1)>170)
            if len(ys)>80:
                center = (int(ys[0])+int(ys[-1]))/2 + round(self.height*.13)
                self.move(sx, center)
                self.sleep(.4)
                self.executor.interaction.swipe(sx, center, sx, self.height*.13, .8)
                self.sleep(1)
            else:
                self.scroll_relative(.90,.45,100)
                self.sleep(1)
            for index, position in enumerate((.15, .55, .85, .85)):
                self.click(self.width*.974, self.height*position,
                           name='核对完整材料列表', after_sleep=.8)
                self.next_frame()
                path = folder / f'{name}-{index}.png'
                cv2.imwrite(str(path), self.frame)
                boxes = self.ocr(box=viewport(self, .25, .15, .99, .94), target_height=self.height*3)
                target['pages'].append({'image': str(path), 'text': [b.name for b in boxes],
                    'jobs': required_jobs(boxes, name, self.width)})
                audit_path = Path('logs/material-audit-latest.json')
                audit = json.loads(audit_path.read_text())
                known = {r['required'] for r in audit['items'] if r['target'] == name}
                for count in boxes:
                    match = re.fullmatch(r'(\d+)[/／](\d+)', re.sub(r'\s+', '', count.name))
                    if not match or not .55*self.width < count.x < .87*self.width:
                        continue
                    owned, needed = map(int, match.groups())
                    if needed in known:
                        continue
                    icon = self.frame[max(0, count.y-70):count.y+2,
                                      round(min((1145,1255,1366,1476), key=lambda x:abs(x-count.x-25)))-45:
                                      round(min((1145,1255,1366,1476), key=lambda x:abs(x-count.x-25)))+45].copy()
                    self.click(count.x+count.width/2, count.y-self.height*.025, after_sleep=.5)
                    detail = self.ocr(box=viewport(self,.35,.10,.68,.90), target_height=self.height*2)
                    headers = [b for b in detail if b.y < self.height*.21 and re.search(r'[\u4e00-\u9fff]',b.name)]
                    title = min(headers,key=lambda b:b.y).name if headers else ''
                    inventory = re.search(r'拥有[：:]?(\d+)', re.sub(r'\s+','',''.join(b.name for b in detail)))
                    if title and inventory:
                        row = dict(target=name,item_name=title,required=needed,inventory=int(inventory[1]),
                                   displayed_owned=owned,detail_text=[b.name for b in detail])
                        audit['items'].append(row)
                        import hashlib
                        icon_path = Path('configs/macos-desktop/material-icons')/(hashlib.sha256(title.encode()).hexdigest()[:16]+'.png')
                        cv2.imwrite(str(icon_path),icon)
                        audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2))
                        known.add(needed)
                    self.click(self.width*.70,self.height*.92,after_sleep=.4)
            result['targets'].append(target)
            (folder / 'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        from datetime import datetime
        result.update(status='completed', observed_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        (folder / 'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        self.return_to_world()
        self.result = result
