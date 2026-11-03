"""Read the team's material locations without entering or claiming a challenge."""
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.TeamMaterialPlan import TEAM_NAMES


def scan_target_names(chars, settings=None):
    from src.char.CharFactory import char_names
    from src.task.TeamMaterialTask import TeamMaterialTask
    if len(chars) != 3 or any(not c or c.confidence < .8 or c.char_name not in char_names for c in chars):
        raise RuntimeError('队伍有角色未被已注册的角色模板识别')
    if settings is not None and settings.get(TeamMaterialTask.TARGET_NAMES_CONFIG, '').strip():
        return TeamMaterialTask.parse_target_names(settings.get(TeamMaterialTask.TARGET_NAMES_CONFIG, ''))
    from src.runtime.CharacterCatalog import names_for_party
    return names_for_party(chars)


class TeamMaterialScanTask(SafeMaterialTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '扫描全队材料（不消耗）'
        self.description = '核对队伍，读取三人培养目标右侧材料清单和周本次数；保存报告，不进入战斗。'
        self.default_config.clear()
        self.support_schedule_task = False

    def run(self):
        self.result = {'status': 'running', 'catalog': []}
        try:
            self.return_to_world()
            if self.in_realm():
                raise RuntimeError('请先使用返回并治疗，退出副本后扫描材料')
            self.load_chars()
            from src.task.TeamMaterialTask import TeamMaterialTask
            planner = next((task for task in self.executor.onetime_tasks
                            if isinstance(task, TeamMaterialTask)), None)
            names = scan_target_names(self.chars, planner.config if planner else None)
            if getattr(self, 'target_names_override', ''):
                names = TeamMaterialTask.parse_target_names(self.target_names_override)
            if self.expected_target:
                # A cultivation target may be unowned and need not be in the
                # combat party. An explicit scan target is verified against
                # the live cultivation card by ensure_cultivation_target().
                names = [self.expected_target]
            for name in names:
                self.open_materials_book()
                self.ensure_cultivation_target(name)
                from src.task.CultivationTargetUI import viewport
                rows = self.ocr(box=viewport(self, .25, .14, .99, .90))
                self.result['catalog'].append({'target': name, 'visible_materials': [b.name for b in rows],
                    'boxes': [{'name': b.name, 'x': b.x, 'y': b.y, 'width': b.width, 'height': b.height}
                              for b in rows]})
                self.save_run_report()
            self.return_to_world()
            self.result['status'] = 'catalog_completed'
        except Exception as exc:
            self.result.update(status='stopped', error=str(exc))
            raise
        finally:
            self.save_run_report()
