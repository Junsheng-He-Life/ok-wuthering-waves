"""Fresh guidebook scans for explicitly selected cultivation categories."""
from src.runtime.CharacterCatalog import names_for_party
from src.runtime.CultivationPolicy import cultivation_kinds, recommended_echo_locations
from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.CultivationEchoUI import CultivationEchoUI


class CultivationScope(CultivationEchoUI):
    # Reuse the established target selection, scrolling and count reader.
    select_material_target_with_recovery = TeamMaterialTask.select_material_target_with_recovery
    reset_material_list_top = TeamMaterialTask.reset_material_list_top

    def scope_names(self):
        from src.runtime.DesktopJobs import targets
        self.return_to_world()
        if self.in_realm():
            raise RuntimeError('请先返回并治疗，退出副本后读取培养目标。')
        self.load_chars()
        current = names_for_party(self.chars)
        self.result['team'] = [str(getattr(c.char_name, 'value', c.char_name)) for c in self.chars]
        explicit = targets(getattr(self, 'cultivation_targets', ''))
        return explicit or current

    def selected_material_jobs(self, names):
        selected = [kind for kind in self.selected_kinds if kind != '声骸']
        if not selected:
            return []
        # Do not let personal historical completion/audit policies replace the
        # freshly observed needs, or add a category outside this request.
        jobs = TeamMaterialTask.scan_required_jobs(
            self, names, selected_kinds=selected, shared_plan=False)
        if any(job['kind'] == '目标待核对' for job in jobs):
            raise RuntimeError('培养目标未核对成功；停止所选项目。')
        return jobs

    def echo_recommendations(self, name):
        self.return_to_world()
        self.open_materials_book()
        self.select_material_target_with_recovery(name)
        sonata = self.read_target_sonata(name)
        self.select_sonata_filter(name, sonata)
        self.result.setdefault('recommended_sonatas', {})[name] = sonata
        if not self.cultivation_target_verified(name):
            raise RuntimeError('读取声骸推荐前培养目标发生变化。')
        def record_page(visible, indexed):
            # Persist this controller's existing frame and observations, so a
            # missing recommendation can be audited without another capture.
            from pathlib import Path
            import time
            import cv2
            folder = Path('logs/cultivation-echo-scan')
            folder.mkdir(parents=True, exist_ok=True)
            evidence = folder / f'{time.time_ns()}.png'
            if not cv2.imwrite(str(evidence), self.frame):
                raise RuntimeError('声骸推荐核对截图保存失败。')
            self.result.setdefault('echo_scan_observations', []).append({
                'target': name, 'evidence': str(evidence),
                'rows': [{key: value for key, value in row.items() if key != 'action_box'}
                         for row in visible]})
        catalog = self.build_material_page_dictionary('wuyin', force=True, visible_selector=record_page)
        if not self.cultivation_target_verified(name):
            raise RuntimeError('读取声骸推荐后培养目标未确认。')
        return recommended_echo_locations(catalog['locations'], verified_set=sonata)

    def scan_scope(self, names):
        self.selected_kinds = cultivation_kinds(self.cultivation_selection)
        self.result.update(targets=names, selected_kinds=list(self.selected_kinds))
        jobs = self.selected_material_jobs(names)
        if '声骸' in self.selected_kinds:
            for name in names:
                rows = self.echo_recommendations(name)
                self.result.setdefault('echo_recommendations', {})[name] = [
                    {key: value for key, value in row.items() if key != 'action_box'}
                    for row in rows]
                if not rows:
                    jobs.append({'target': name, 'kind': '声骸', 'cost': 60,
                                 'deferred_reason': '未读到重复确认的角色合鸣套装对应关卡；不替换为其他关卡。'})
                    continue
                selected = self.order_material_locations(rows)[0]
                jobs.append({'target': name, 'kind': '声骸', 'cost': 60,
                             'route': {'category': 'wuyin', 'fallback_stage_name': selected['name']}})
        self.result['catalog'] = jobs
        self.return_to_world()
        return jobs
