"""Exercise launch selection with fake interpreters; never launch the GUI."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'desktop_environment_check', ROOT / 'scripts/check_desktop_environment.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class TestDesktopRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='okww launcher ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'game with spaces'
        (self.root / 'scripts').mkdir(parents=True)
        for name in ('启动 OK-WW.command', '诊断 OK-WW.command', 'scripts/desktop_runtime.sh'):
            shutil.copyfile(ROOT / name, self.root / name)
        self.record = self.base / 'invocations.txt'

    def runtime(self, sibling=False, doctor_status=0, app_status=0):
        path = ((self.base / 'ok-script/.venv313/bin/python') if sibling
                else self.root / '.venv/bin/python')
        path.parent.mkdir(parents=True)
        path.write_text('#!/bin/bash\n'
                        'printf "%s|%s|%s\\n" "$0" "$PWD" "$*" >> "$TASK_TEST_RECORD"\n'
                        f'case "$1" in *check_desktop_environment.py) exit {doctor_status};; esac\n'
                        f'exit {app_status}\n')
        path.chmod(0o755)
        return path

    def run_command(self, command='启动 OK-WW.command'):
        env = dict(os.environ, TASK_TEST_RECORD=str(self.record))
        return subprocess.run(['bash', str(self.root / command)], cwd=self.base,
                              env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=5)

    def test_sibling_runtime_has_priority(self):
        sibling = self.runtime(sibling=True)
        self.runtime()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.record.read_text().splitlines()
        self.assertEqual(2, len(calls))
        self.assertTrue(all(Path(line.split('|')[0]).resolve() == sibling.resolve() for line in calls))

    def test_project_venv_works_from_other_directory_with_spaces(self):
        local = self.runtime()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.record.read_text().splitlines()
        self.assertEqual(2, len(calls))
        self.assertTrue(all(line.startswith(f'{local}|{self.root}|') for line in calls))
        self.assertIn('check_desktop_environment.py', calls[0])
        self.assertIn('scripts/macos_app.py', calls[1])

    def test_missing_runtime_does_not_try_global_python(self):
        result = self.run_command()
        self.assertEqual(1, result.returncode)
        self.assertIn('不会调用系统 Python', result.stderr)
        self.assertFalse(self.record.exists())

    def test_failed_doctor_never_launches_gui_or_switches_runtime(self):
        self.runtime(sibling=True, doctor_status=17)
        self.runtime()
        result = self.run_command()
        self.assertEqual(17, result.returncode)
        calls = self.record.read_text().splitlines()
        self.assertEqual(1, len(calls))
        self.assertNotIn('macos_app.py', calls[0])

    def test_application_exit_code_is_preserved(self):
        self.runtime(app_status=23)
        result = self.run_command()
        self.assertEqual(23, result.returncode)
        self.assertIn('程序未正常退出', result.stdout)

    def test_standalone_diagnosis_never_launches_gui(self):
        self.runtime()
        result = self.run_command('诊断 OK-WW.command')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.record.read_text().splitlines()))


class TestOfflineDoctor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='okww doctor ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.framework = self.base / 'game', self.base / 'ok-script'
        for base, names in ((self.root, doctor.PROJECT_FILES), (self.framework, doctor.FRAMEWORK_FILES)):
            for name in names:
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('raise AssertionError("application code must never run")')
        (self.root / 'assets/coco_annotations.json').write_text(json.dumps({'images': []}))
        self.unsafe = self.base / 'test_dependency_never_import'
        self.unsafe.mkdir()
        (self.unsafe / '__init__.py').write_text('raise AssertionError("dependency was imported")')
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        for target, value in ((doctor.sys, {'platform': 'darwin', 'prefix': '/fake/venv',
                                          'base_prefix': '/fake/base',
                                          'path': [str(self.framework), str(self.base)]}),
                              (doctor, {'DEPENDENCIES': {'test_dependency_never_import': 'test-package'}})):
            for name, setting in value.items():
                self.context.enter_context(patch.object(target, name, setting))
        self.context.enter_context(patch.object(doctor.shutil, 'which', return_value='/usr/bin/swiftc'))
        self.context.enter_context(patch.object(doctor.platform, 'machine', return_value='arm64'))
        self.context.enter_context(patch.object(doctor.platform, 'mac_ver', return_value=('14.0', ('', '', ''), 'arm64')))
        self.context.enter_context(patch.object(doctor.sys, 'version_info', (3, 13, 0)))
        self.context.enter_context(patch.dict(os.environ, {'OK_MACOS_HELPER': ''}))

    def test_valid_environment_checks_paths_without_importing_packages(self):
        errors, modules = doctor.inspect_environment(self.root)
        self.assertEqual([], errors)
        self.assertEqual(str(self.framework / 'ok/__init__.py'), modules['ok'])
        self.assertNotIn('test_dependency_never_import', sys.modules)

    def test_missing_dependency_has_install_guidance(self):
        shutil.rmtree(self.unsafe)
        errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('缺少依赖：test-package' in error for error in errors))
        self.assertTrue(any('requirements-macos.lock.txt' in error for error in errors))

    def test_unsupported_host_is_rejected_before_runtime_use(self):
        with patch.object(doctor.platform, 'mac_ver', return_value=('13.6', ('', '', ''), 'arm64')):
            errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('macOS 14' in error for error in errors))
        with patch.object(doctor.platform, 'machine', return_value='x86_64'):
            errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('Apple Silicon' in error for error in errors))
        with patch.object(doctor.sys, 'version_info', (3, 12, 9)):
            errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('Python 3.13' in error for error in errors))

    def test_wrong_framework_origin_is_rejected(self):
        with patch.object(doctor.sys, 'path', [str(self.base)]):
            errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('ok 模块未指向配套框架' in error for error in errors))

    def test_missing_template_is_reported(self):
        (self.root / 'assets/coco_annotations.json').write_text(
            json.dumps({'images': [{'file_name': 'missing.png'}]}))
        errors, _ = doctor.inspect_environment(self.root)
        self.assertTrue(any('缺少 1 张模板图像' in error for error in errors))

    def test_missing_source_and_invalid_index_return_error_exit(self):
        (self.root / 'scripts/macos_app.py').unlink()
        (self.root / 'assets/coco_annotations.json').write_text('{')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            status = doctor.main(['--root', str(self.root)])
        self.assertEqual(1, status)
        self.assertIn('缺少文件', stderr.getvalue())
        self.assertIn('模板索引无法读取', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
