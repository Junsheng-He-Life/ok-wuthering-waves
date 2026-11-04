"""Packaged upgrades must preserve accounting and reject broken payloads."""
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts.bundled_entry import acquire, sync_sources
from scripts.build_macos_app import relocate


class TestBundledApp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.payload, self.workspace = self.base / 'payload', self.base / 'user data'
        self.payload.mkdir(); self.workspace.mkdir()
        self.files = {}

    def source(self, relative, content):
        path = self.payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        self.files[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (self.payload / 'release-manifest.json').write_text(json.dumps(
            {'files': self.files, 'snapshot_sha256': 'test snapshot', 'build_number': 3}))

    def test_update_retains_ledger_pending_claim_and_config(self):
        self.source('ok-wuthering-waves/src/run.py', 'new code')
        records = {'logs/material-status/activity.json': 'ledger317',
                   'logs/echo-claim-pending.json': 'unresolved claim',
                   'configs/macos-desktop/options.json': 'user options'}
        for relative, content in records.items():
            path = self.workspace / 'ok-wuthering-waves' / relative
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        sync_sources(self.payload, self.workspace)
        self.source('ok-wuthering-waves/src/run.py', 'updated code')
        sync_sources(self.payload, self.workspace)
        self.assertEqual('updated code', (self.workspace / 'ok-wuthering-waves/src/run.py').read_text())
        for relative, content in records.items():
            self.assertEqual(content, (self.workspace / 'ok-wuthering-waves' / relative).read_text())

    def test_tamper_fails_before_changing_any_source(self):
        self.source('ok-script/ok/engine.py', 'correct')
        (self.payload / 'ok-script/ok/engine.py').write_text('tampered')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            sync_sources(self.payload, self.workspace)
        self.assertFalse((self.workspace / 'ok-script').exists())

    def test_manifest_cannot_replace_user_state_or_leave_workspace(self):
        for relative in ('ok-wuthering-waves/logs/activity.json', '../outside.py'):
            with self.subTest(relative=relative):
                self.files.clear(); self.source(relative, 'blocked')
                with self.assertRaises(ValueError):
                    sync_sources(self.payload, self.workspace)

    def test_existing_controller_lock_blocks_second_opener(self):
        path = self.workspace / 'logs/macos-controller.lock'
        with acquire(path):
            with self.assertRaisesRegex(RuntimeError, '正在运行'):
                acquire(path)

    def test_manifest_cannot_delete_old_state(self):
        self.source('ok-script/ok/engine.py', 'correct')
        (self.workspace / 'keep.json').write_text('keep')
        (self.workspace / '.bundled-source.json').write_text(json.dumps(
            {'files': ['keep.json', '../outside.py', 'ok-wuthering-waves/logs/claim.json']}))
        sync_sources(self.payload, self.workspace)
        self.assertEqual('keep', (self.workspace / 'keep.json').read_text())

    def test_symlinked_code_destination_is_rejected(self):
        self.source('ok-script/ok/engine.py', 'correct')
        outside = self.base / 'external'; outside.mkdir()
        (self.workspace / 'ok-script').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            sync_sources(self.payload, self.workspace)
        self.assertEqual([], list(outside.iterdir()))

    def test_vendor_library_id_is_rewritten_without_becoming_a_dependency(self):
        path = Path('/package/lib/example.dylib')
        def command(*args):
            if args[0] == 'lipo': return 'arm64\n'
            if args[:2] == ('otool', '-D'): return f'{path}:\n/DLC/example.dylib\n'
            if args[:2] == ('otool', '-L'):
                return f'{path}:\n\t/DLC/example.dylib (compatibility version 1.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
            return ''
        with patch('scripts.build_macos_app.run', side_effect=command) as runner:
            relocate(path, Path('/original/Python'), Path('/package'))
        runner.assert_any_call('install_name_tool', '-id', '@loader_path/example.dylib', path)

    def test_unbundled_external_library_is_still_rejected(self):
        def command(*args):
            if args[0] == 'lipo': return 'arm64\n'
            if args[:2] == ('otool', '-D'): return 'plugin:\n'
            return 'plugin:\n\t/usr/local/opt/database/lib.dylib (compatibility version 1.0.0)\n'
        with patch('scripts.build_macos_app.run', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'External binary dependency'):
                relocate(Path('/package/plugin'), Path('/original/Python'), Path('/package'))

    def test_newer_system_binary_is_rejected_even_when_wheel_tag_claims_compatibility(self):
        def command(*args):
            if args[0] == 'lipo': return 'arm64\n'
            if args[:2] == ('otool', '-l'): return 'cmd LC_BUILD_VERSION\nminos 26.0\n'
            return ''
        with patch('scripts.build_macos_app.run', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'above 14.0'):
                relocate(Path('/package/plugin'), Path('/original/Python'), Path('/package'))


if __name__ == '__main__':
    unittest.main()
