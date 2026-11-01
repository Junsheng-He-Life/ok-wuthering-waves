import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.TeamMaterialScanTask import TeamMaterialScanTask, scan_target_names
from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.TeamMaterialTargets import registered_target_name, resolve_material_targets


class TestTeamMaterialScanTask(unittest.TestCase):
    def team(self, names=('char_aemeath', 'char_denia', 'char_chisa')):
        return [SimpleNamespace(char_name=name, confidence=.95)
                for name in names]

    def test_live_detonation_team_is_supported(self):
        self.assertEqual(['爱弥斯', '达妮娅', '千咲'], scan_target_names(self.team()))

    def test_stale_configured_slot_names_stop_instead_of_farming_wrong_targets(self):
        settings = {TeamMaterialTask.TARGET_NAMES_CONFIG: '千咲,爱弥斯,达妮娅'}
        with self.assertRaisesRegex(RuntimeError, '1号位识别为 爱弥斯，设置为 千咲'):
            scan_target_names(self.team(), settings)

    def test_matching_configured_names_are_accepted(self):
        settings = {TeamMaterialTask.TARGET_NAMES_CONFIG: '爱弥斯， 达妮娅， 千咲'}
        self.assertEqual(['爱弥斯', '达妮娅', '千咲'], scan_target_names(self.team(), settings))

    def test_blank_setting_tracks_reordered_slots(self):
        chars = self.team(('char_chisa', 'char_aemeath', 'char_denia'))
        self.assertEqual(['千咲', '爱弥斯', '达妮娅'], scan_target_names(chars, {}))

    def test_another_registered_party_uses_shipped_chinese_names(self):
        chars = self.team(('char_jinhsi', 'char_zhezhi', 'char_verina'))
        self.assertEqual(['今汐', '折枝', '维里奈'], scan_target_names(chars, {}))

    def test_old_local_party_names_remain_supported(self):
        chars = self.team(('yangyang_sp', 'char_phrolova', 'char_suisui'))
        self.assertEqual(['秧秧·玄翎', '弗洛洛', '穗穗'], scan_target_names(chars))

    def test_alternate_templates_resolve_to_same_character(self):
        chars = self.team(('char_chisa2', 'char_denia_macos_1280', 'char_jinhsi2'))
        self.assertEqual(['千咲', '达妮娅', '今汐'], scan_target_names(chars))

    def test_explicit_target_bypasses_obsolete_party_names(self):
        self.assertEqual(['心'], scan_target_names(self.team(), {
            TeamMaterialTask.TARGET_NAMES_CONFIG: 'obsolete invalid list'}, single_target=' 心 '))

    def test_duplicate_alias_identities_stop(self):
        chars = self.team(('char_chisa', 'char_chisa2', 'char_denia'))
        with self.assertRaisesRegex(RuntimeError, '重复'):
            scan_target_names(chars)

    def test_two_person_party_stops(self):
        with self.assertRaisesRegex(RuntimeError, '三个'):
            scan_target_names(self.team()[:2])

    def test_missing_translation_stops_instead_of_guessing(self):
        catalog = SimpleNamespace(gettext=lambda name: name)
        with patch('src.task.TeamMaterialTargets._chinese_catalog', return_value=catalog):
            with self.assertRaisesRegex(RuntimeError, '中文培养目标名'):
                registered_target_name('char_jinhsi')

    def test_unrecognized_portrait_cannot_select_material_targets(self):
        chars = self.team()
        chars[1].confidence = .79
        with self.assertRaisesRegex(RuntimeError, '2号位'):
            scan_target_names(chars)

    def test_explicit_target_still_requires_live_party(self):
        for confidence in (.79, float('nan'), float('inf'), None):
            with self.subTest(confidence=confidence):
                chars = self.team()
                chars[1].confidence = confidence
                with self.assertRaisesRegex(RuntimeError, '2号位'):
                    resolve_material_targets(chars, single_target='心')

    def test_unknown_character_stops_even_for_explicit_target(self):
        chars = self.team(('char_unknown', 'char_denia', 'char_chisa'))
        with self.assertRaisesRegex(RuntimeError, '1号位'):
            resolve_material_targets(chars, single_target='心')

    def test_scan_explicit_target_does_not_parse_old_slot_setting_first(self):
        task = SimpleNamespace(
            return_to_world=Mock(), in_realm=Mock(return_value=False), load_chars=Mock(return_value=True),
            chars=self.team(), executor=SimpleNamespace(onetime_tasks=[]), expected_target='心',
            open_materials_book=Mock(), ensure_cultivation_target=Mock(),
            ocr=Mock(return_value=[]), width=1920, height=1080, save_run_report=Mock())
        TeamMaterialScanTask.run(task)
        task.ensure_cultivation_target.assert_called_once_with('心')
        self.assertEqual('catalog_completed', task.result['status'])

    def test_failed_live_read_cannot_reuse_previous_party(self):
        for result in (None, False):
            with self.subTest(result=result):
                task = SimpleNamespace(
                    return_to_world=Mock(), in_realm=Mock(return_value=False),
                    load_chars=Mock(return_value=result), chars=self.team(),
                    open_materials_book=Mock(), ensure_cultivation_target=Mock(),
                    save_run_report=Mock())
                with self.assertRaisesRegex(RuntimeError, '本次队伍读取未成功'):
                    TeamMaterialScanTask.run(task)
                task.open_materials_book.assert_not_called()
                task.ensure_cultivation_target.assert_not_called()
                self.assertEqual('stopped', task.result['status'])

    def test_planner_rejects_stale_names_before_scanning(self):
        task = SimpleNamespace(
            assert_no_pending_refill=Mock(), focus_material_menu=Mock(),
            return_to_world=Mock(), load_chars=Mock(return_value=True), chars=self.team(), target_override='',
            SINGLE_TARGET_CONFIG=TeamMaterialTask.SINGLE_TARGET_CONFIG,
            TARGET_NAMES_CONFIG=TeamMaterialTask.TARGET_NAMES_CONFIG,
            config={TeamMaterialTask.TARGET_NAMES_CONFIG: '秧秧·玄翎,弗洛洛,穗穗'},
            state_path=SimpleNamespace(exists=lambda: False),
            scan_required_jobs=Mock())
        task.resolve_plan_targets = lambda target: TeamMaterialTask.resolve_plan_targets(task, target)
        with self.assertRaisesRegex(RuntimeError, '培养目标与当前队伍不一致'):
            TeamMaterialTask.run_material_plan(task)
        task.scan_required_jobs.assert_not_called()
