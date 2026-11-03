"""Public regressions use synthetic state and fake input, never a live game."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from src.char.Mornye import Mornye
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.runtime.DesktopJobs import DesktopRequest
from src.runtime.DesktopRecovery import export_diagnostics
from src.task.SafeMaterialTask import SafeMaterialTask
from src.ui.DesktopWindow import DesktopWindow


class TestReleaseWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_no_claim_overrides_every_saved_spending_option(self):
        for kind in ('boss','tacet','material_stage'):
            args=DesktopRequest(kind=kind,stage='example',target='穗穗' if kind=='material_stage' else '',
                                waveplates=1000,reserve=240,solvents=30).arguments(188)
            self.assertIn('--echo-no-claim',args)
            for flag in ('--max-stamina','--reserve-limit','--solvent-limit'):
                self.assertEqual('0',args[args.index(flag)+1])
            self.assertEqual('188',args[args.index('--solvent-total')+1])

    def test_material_stage_shares_durable_echo_ledger_runner(self):
        args=DesktopRequest(kind='material_stage',stage='静灭云渊',target='穗穗',claim_rewards=True,waveplates=40).arguments()
        self.assertEqual('echo',args[args.index('--phase')+1])
        self.assertEqual('material',args[args.index('--echo-mode')+1])

    def test_current_targets_cannot_reuse_old_saved_party(self):
        args=DesktopRequest(kind='materials',claim_rewards=True,waveplates=80).arguments()
        self.assertIn('--current-team-targets',args)
        self.assertNotIn('--targets',args)

    def test_gui_uses_choices_and_never_edits_stage_or_role_names(self):
        with tempfile.TemporaryDirectory() as directory:
            window=DesktopWindow(directory,preview=True)
            self.addCleanup(window.close)
            self.assertFalse(window.stage.isEditable())
            self.assertFalse(window.claim.isChecked())
            self.assertTrue(all(not c.isEditable() for c in window.role_selectors))
            window.kind.setCurrentIndex(window.kind.findData('material_stage'))
            self.assertEqual('single',window.target_scope.currentData())
            with self.assertRaises(ValueError):window.target_names()
            role=window.role_selectors[0];role.setCurrentIndex(role.findData('穗穗'))
            self.assertEqual('穗穗',window.target_names())
            with patch.object(window.controller,'start') as start,patch.object(window,'message'):
                window.start_run()
            start.assert_not_called()
            self.assertFalse(list(Path(directory).rglob('*')))

    def test_material_entry_delegates_to_label_verified_start(self):
        task=SafeMaterialTask.__new__(SafeMaterialTask)
        with patch('src.task.TeamMaterialEntry.TeamMaterialEntry.start_material_team_verified',return_value=True) as start:
            self.assertTrue(task.finish_domain_destination(True))
        start.assert_called_once_with(task)

    def test_recovery_from_unentered_team_screen_uses_menu_return_before_healing(self):
        task=SafeMaterialTask.__new__(SafeMaterialTask)
        task.phase='recover';task.config={};task.run_limit=1;task.reserve_limit=0
        task.expected_target='穗穗';task.exact_stage='静灭云渊'
        for name in ('assert_no_pending_refill','focus_material_menu','return_to_world',
                     'leave_verified_domain','heal_at_beacon','mouse_up','send_key_up',
                     '_stop_combat_debug_frame_recorder','save_run_report'):
            setattr(task,name,Mock())
        task.menu_text=Mock(side_effect=[object(),True])
        task.run()
        self.assertEqual('healed',task.result['status'])
        task.leave_verified_domain.assert_not_called();task.heal_at_beacon.assert_called_once()

    def test_fixed_material_budget_is_40_and_keeps_shared_no_claim_guards(self):
        from src.task.EchoFarmTask import MaterialStageTask
        task=MaterialStageTask.__new__(MaterialStageTask)
        task.echo_stage_override='静灭云渊';task.result={}
        task._activity=SimpleNamespace(solvent_allowance=Mock(return_value=0))
        task.config={'战后领奖':True,'本次战斗上限':1,'本次最多领奖':2,
                     '本次波片上限':40,'本次储备上限':0,'本次溶剂上限':0}
        task.configure_echo_run()
        self.assertEqual('ningsu',task.plan_job['route']['category'])
        self.assertEqual(40,task._run_budget.claim_cost)
        self.assertTrue(task._run_budget.can_claim())
        self.assertFalse(task._run_budget.can_claim(2))
        task.config['战后领奖']=False;task.config['本次溶剂上限']=30
        task.configure_echo_run();self.assertEqual(0,task._run_budget.max_solvents)

    def test_desktop_recording_limit_preserves_unrelated_historical_frames(self):
        import numpy as np
        from src.task.CharacterMaterialTask import CharacterMaterialTask
        with tempfile.TemporaryDirectory() as directory:
            original=Path.cwd();os.chdir(directory)
            try:
                old=Path('logs/character_material_combat_frames/history.jpg')
                old.parent.mkdir(parents=True);old.write_bytes(b'preserve')
                task=CharacterMaterialTask.__new__(CharacterMaterialTask)
                task._executor=SimpleNamespace(nullable_frame=lambda:np.zeros((8,8,3),dtype=np.uint8))
                task.record_hud=True;task.desktop_recording_id='synthetic';task.result={};task._combat_debug_frame_count=0
                for _ in range(601):task._capture_combat_debug_frame()
                self.assertEqual(600,len(list(Path(task.result['recording_dir']).glob('*.jpg'))))
                self.assertEqual(b'preserve',old.read_bytes())
            finally:os.chdir(original)

    def test_mornye_unconfirmed_e_leaves_normal_attack_available_and_backs_off(self):
        char=Mornye.__new__(Mornye);char.resonance_available=Mock(return_value=True)
        char.send_resonance_key=Mock();char.task=SimpleNamespace(next_frame=Mock())
        char.has_cd=Mock(return_value=False);char.record_resonance_use=Mock();char.logger=Mock()
        with patch('src.char.Mornye.time.monotonic',return_value=20):
            self.assertFalse(char.cast_resonance_if_ready())
            self.assertFalse(char.cast_resonance_if_ready())
        char.send_resonance_key.assert_called_once();char.record_resonance_use.assert_not_called()

    def test_airborne_target_hud_does_not_disable_health_guard_or_force_relock(self):
        task=MaterialBossGuard();task._plan_boss=True;task._boss_guard_at=0;task._boss_target_missing_at=1
        task.get_current_char=Mock(return_value=SimpleNamespace(char_name='char_moning',on_air=lambda:True))
        task.check_material_boss_health=Mock();task.acquire_material_boss=Mock();task.boss_target_locked=Mock(return_value=False)
        task.guard_material_boss()
        task.check_material_boss_health.assert_called_once();task.acquire_material_boss.assert_not_called()
        self.assertIsNone(task._boss_target_missing_at)

    def test_missing_enemy_bar_does_not_skip_player_health_during_acquisition(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        task=MaterialBossGuard();task.mouse_up=Mock();task.next_frame=Mock();task.in_team=Mock(return_value=(True,0))
        task.find_treasure_icon=Mock(return_value=False);task.check_health_bar=Mock(return_value=False)
        task.check_material_boss_health=Mock(side_effect=DomainBattleFailed('low health'))
        task.send_key=Mock()
        with self.assertRaisesRegex(DomainBattleFailed,'low health'):task.acquire_material_boss()
        task.check_material_boss_health.assert_called_once();task.send_key.assert_not_called()

    def test_report_preserves_stack_but_removes_identifiers_and_raw_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'logs/desktop-runs';folder.mkdir(parents=True)
            (folder/'1.json').write_text(json.dumps({'status':'stopped','error':'ValueError: test UID:123456789',
                                                   'inventory_text':['PRIVATE_NAME']}))
            (folder/'1.log').write_text('Traceback\n/Users/private-person/app.py\nValueError: failure token=abc-secret user@example.com\nTRIAL_RESULT {"inventory":"PRIVATE_NAME"}\n')
            (root/'logs/echo-claim-pending.json').write_text('{}')
            destination=root/'report.zip';export_diagnostics(root,destination)
            with zipfile.ZipFile(destination) as archive:
                contents='\n'.join(archive.read(n).decode() for n in archive.namelist())
                self.assertIn('run-1-tail.txt',archive.namelist())
            for secret in ('private-person','abc-secret','user@example.com','123456789','PRIVATE_NAME'):
                self.assertNotIn(secret,contents)
            self.assertIn('Traceback',contents);self.assertIn('ValueError',contents)
            self.assertTrue((root/'logs/echo-claim-pending.json').exists())


if __name__=='__main__':unittest.main()
