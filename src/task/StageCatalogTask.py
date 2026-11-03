"""Enumerate combat entries through the existing guidebook without entering."""
import json
from pathlib import Path
import time

from src.task.SafeMaterialTask import SafeMaterialTask


class StageCatalogTask(SafeMaterialTask):
    categories = ('moni', 'ningsu', 'qiangdi', 'zhange', 'wuyin', 'canxiang')
    catalog_path = Path('logs/stage-catalog-latest.json')

    def capture_catalog_page(self, visible, indexed):
        import cv2
        folder = Path('logs/stage-catalog') / self._catalog_stamp
        folder.mkdir(parents=True, exist_ok=True)
        name = f'{self._catalog_category}-{len(self.result["pages"]):03d}.png'
        if not cv2.imwrite(str(folder/name), self.frame):
            raise RuntimeError('关卡清单截图保存失败')
        self.result['pages'].append({'category': self._catalog_category,
                                     'image': str(folder/name)})

    def run(self):
        self.result = {'status': 'running', 'phase': 'stage-catalog',
                       'spending': 0, 'catalogs': {}, 'pages': []}
        self._catalog_stamp = str(time.time_ns())
        try:
            self.assert_no_pending_refill()
            if Path('logs/echo-claim-pending.json').exists():
                raise RuntimeError('声骸领奖待核对，先处理原结算')
            state = Path('configs/macos-desktop/team-material-needs-progress.json')
            if state.exists() and json.loads(state.read_text()).get('claim_pending'):
                raise RuntimeError('材料领奖待核对，先处理原结算')
            self.return_to_world()
            self.load_chars()
            if len(self.chars) != 3 or any(not c or c.confidence < .8 or c.char_name == 'unknown'
                                           for c in self.chars):
                raise RuntimeError('三人队伍未完整识别，未扫描关卡')
            self.result['team'] = [str(c.char_name) for c in self.chars]
            for category in self.categories:
                self._catalog_category = category
                self.open_materials_book()
                self.open_boss_book(category)
                catalog = self.build_material_page_dictionary(
                    category, force=True, visible_selector=self.capture_catalog_page)
                self.result['catalogs'][category] = [
                    {k:v for k,v in row.items() if k != 'action_box'}
                    for row in catalog['locations']]
                self.return_to_world()
                self.catalog_path.write_text(json.dumps(self.result,ensure_ascii=False,indent=2)+'\n')
            self.result['status'] = 'catalog_completed_no_spending'
        except BaseException as exc:
            self.result.update(status='stopped',error=str(exc))
            raise
        finally:
            self.catalog_path.write_text(json.dumps(self.result,ensure_ascii=False,indent=2)+'\n')
