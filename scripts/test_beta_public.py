"""Run the published synthetic beta regressions without a game or private images."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT.parent / 'ok-script'
APP_MODULES = (
    'TestDesktopPanel', 'TestDesktopUserState', 'TestDesktopClaimReconciliation',
    'TestDesktopPreflight', 'TestBetaPackage', 'TestDesktopEnvironment',
    'TestMacSession', 'TestMacViewport', 'TestMacWindowSelection', 'TestUltrawide',
)
BACKEND_MODULES = ('test_macos_geometry.py', 'test_start_controller_errors.py',
                   'test_macos_backend.py')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--app-only', action='store_true')
    mode.add_argument('--backend-only', action='store_true')
    args = parser.parse_args(argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(FRAMEWORK)]
    print('Public beta subset: synthetic observations and fake input only.', flush=True)
    print('Private screenshot regressions and live-game acceptance are excluded.', flush=True)
    print(f'Application: {ROOT}\nFramework: {FRAMEWORK}', flush=True)
    successful = True
    if not args.backend_only:
        # This context creates temporary configs/logs and removes every real
        # device constructor before application configuration is used by tests.
        from scripts.test_material_stability import isolated_test_workspace
        with isolated_test_workspace(ROOT):
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromNames(['tests.' + name for name in APP_MODULES])
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            successful = result.wasSuccessful()
            print(f'Public application subset: {result.testsRun} tests, '
                  f'{len(result.skipped)} skipped.', flush=True)
    if not args.app_only:
        paths = [FRAMEWORK / 'tests' / name for name in BACKEND_MODULES]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            print('Missing matching framework tests: ' + ', '.join(missing), file=sys.stderr)
            return 1
        # A fresh process avoids the application's macOS viewport patch affecting
        # generic framework tests. Its logs and pytest state live only in tmp.
        with tempfile.TemporaryDirectory(prefix='okww-public-backend-') as folder:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(FRAMEWORK), str(ROOT))))
            command = [sys.executable, '-m', 'pytest', *(str(path) for path in paths),
                       '-q', '-o', 'addopts=', '-k', 'not native_helper_builds_and_reports_boolean_permissions',
                       '-p', 'no:cacheprovider']
            completed = subprocess.run(command, cwd=folder, env=env, check=False)
            successful = completed.returncode == 0 and successful
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
