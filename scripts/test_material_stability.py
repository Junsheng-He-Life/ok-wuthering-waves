"""Run material regressions with recorded images and simulated input only.

Run with the launcher's Python 3.13 environment. No game controller is started;
the test suite uses fake input backends and saved screenshots. The fingerprint
identifies the project/framework Python sources used for this particular run.
"""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import contextmanager


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT.parent / 'ok-script'
MODULES = (
    'TestCombatCadence', 'TestMaterialWorkflow', 'TestMaterialSettlement',
    'TestMaterialRunSafety', 'TestTeamMaterialPlan', 'TestTeamMaterialScanTask',
    'TestRewardOpening', 'TestDomainProgress', 'TestMaterialBossHealing',
    'TestDetonationTeam', 'TestCombatCheck', 'TestMaterialBossProfiles',
    'TestMacSession', 'TestMacViewport', 'TestWaveplateReading',
    'TestMaterialEntryUI', 'TestMaterialActivity', 'TestMaterialBeaconRecovery',
    'TestDomainLocationFallback', 'TestMaterialNeedsReport', 'TestBattleEvidence',
    'TestPortraitHealth', 'TestSuisuiRotation', 'TestSuisuiHud',
    'TestEchoFarmTask', 'TestEchoFailureRecovery', 'TestEchoCombatPolicy', 'TestEchoSkillOpportunities',
    'TestEchoAlternateTeamSkills',
    'TestXinRotation', 'TestXinRecognition', 'TestJinhsiEchoGuards', 'TestDetonationEchoState',
    'TestCartethyiaEchoGuards', 'TestAlternateHealerRescue', 'TestEchoIntroSupport',
    'TestCombatSwitch', 'TestRecordedConcertoRings',
    'TestMenuPendingInspection', 'TestRewardResultObservation',
    'TestTeamCombatAdaptation', 'TestBossLiberationRetry', 'TestEchoCooldownReading',
    'TestXuanlingEchoReadiness',
    'TestMaterialPlanRefresh', 'TestCultivationAvatarCache',
    'TestOriginalCombatEntry', 'TestSharedMaterialPlanner',
    'TestDesktopEnvironment', 'TestMaterialTestIsolation',
    'TestMaterialAuthorization', 'TestSharedMaterialInventory',
    'TestMaterialQueueSnapshot', 'TestMaterialActivityRestart',
    'TestDesktopPreflight', 'TestDesktopUserState', 'TestDesktopClaimReconciliation',
    'TestDesktopPanel',
)


@contextmanager
def isolated_test_workspace(root=ROOT):
    """Keep test configuration, caches and generated logs outside user state.

    Inputs remain available at their original relative paths. In particular,
    the framework's UI configuration still uses ``configs/ui_config.json``
    directly, so changing Config.config_folder alone would not isolate it.
    """
    original_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='okww-material-tests-') as folder:
        workspace = Path(folder)
        for name in ('assets', 'tests', 'ok_templates', 'i18n'):
            source = root / name
            if source.exists():
                (workspace / name).symlink_to(source, target_is_directory=True)
        (workspace / 'configs').mkdir()
        (workspace / 'logs').mkdir()
        os.chdir(workspace)
        try:
            from ok.util.config import Config
            from config import config
            old_folder = Config.config_folder
            old_config_folder = config.get('config_folder')
            # TaskTestCase installs ImageCaptureMethod/DoNothingInteraction
            # after OK(config) construction. Disable real device constructors
            # before that construction, not just before task execution.
            device_keys = ('macos', 'windows', 'adb', 'browser')
            old_devices = {key: config[key] for key in device_keys if key in config}
            for key in device_keys:
                config.pop(key, None)
            Config.config_folder = config['config_folder'] = str(workspace / 'configs')
            try:
                yield workspace
            finally:
                for key in device_keys:
                    config.pop(key, None)
                config.update(old_devices)
                Config.config_folder = old_folder
                if old_config_folder is None:
                    config.pop('config_folder', None)
                else:
                    config['config_folder'] = old_config_folder
        finally:
            os.chdir(original_directory)


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.path[:0] = [str(ROOT), str(FRAMEWORK)]
    digest = hashlib.sha256()
    paths = [ROOT / 'config.py', *sorted((ROOT / 'src').rglob('*.py')),
             *sorted((FRAMEWORK / 'ok').rglob('*.py'))]
    for path in paths:
        digest.update(str(path.relative_to(ROOT.parent)).encode())
        digest.update(path.read_bytes())
    print(f'Python: {sys.executable} ({sys.version.split()[0]})', flush=True)
    print(f'Project/framework source SHA256: {digest.hexdigest()}', flush=True)
    with isolated_test_workspace() as workspace:
        print(f'Isolated test workspace: {workspace}', flush=True)
        result = unittest.main(module=None, exit=False,
                               argv=[sys.argv[0], *('tests.' + name for name in MODULES)])
    raise SystemExit(not result.result.wasSuccessful())


if __name__ == '__main__':
    main()
