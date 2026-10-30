"""Read the team's material locations without entering or claiming a challenge."""
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.TeamMaterialTargets import resolve_material_targets


def scan_target_names(chars, settings=None, single_target=''):
    from src.task.TeamMaterialTask import TeamMaterialTask
    configured = settings.get(TeamMaterialTask.TARGET_NAMES_CONFIG, '') if settings is not None else ''
    return resolve_material_targets(chars, configured, single_target)


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
            if not self.load_chars():
                raise RuntimeError('本次队伍读取未成功；禁止沿用上次角色，请回到大世界重新扫描')
            from src.task.TeamMaterialTask import TeamMaterialTask
            planner = next((task for task in self.executor.onetime_tasks
                            if isinstance(task, TeamMaterialTask)), None)
            # Explicit targets bypass obsolete slot settings, but never bypass
            # live party recognition. The cultivation card is verified below.
            names = scan_target_names(self.chars, planner.config if planner else None,
                                      self.expected_target)
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
