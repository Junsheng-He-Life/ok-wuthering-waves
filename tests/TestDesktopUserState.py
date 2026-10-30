"""First-use setup must never reset an existing or interrupted installation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from src.runtime.DesktopUserState import (INSTALL, LEDGER, initialize_new_install,
                                         inspect_user_state)
from src.runtime.DesktopRecovery import export_diagnostics, inspect_recovery
from src.runtime.MacSession import MacSession
from src.task.MaterialActivity import MaterialActivity


class TestDesktopUserState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return path

    def test_inspection_is_read_only_and_first_use_requires_confirmation(self):
        self.assertTrue(inspect_user_state(self.root)['can_initialize'])
        self.assertEqual([], list(self.root.iterdir()))
        with self.assertRaises(ValueError):
            initialize_new_install(self.root)
        self.assertFalse((self.root / LEDGER).exists())

    def test_explicit_fresh_install_has_zero_allowances_and_verified_local_ledger(self):
        state = initialize_new_install(self.root, confirmed=True)
        self.assertEqual('ready', state['status'])
        self.assertEqual({'reserve': 0, 'solvents': 0, 'solvent_total': 0}, state['default_limits'])
        activity = MaterialActivity(self.root / LEDGER)
        self.assertEqual(0, activity.data['solvents_used'])
        self.assertTrue(activity.data['history_verified'])
        self.assertEqual(0, activity.solvent_allowance(0, 0))
        self.assertEqual(2, activity.solvent_allowance(2, 2))

    def test_existing_spend_cannot_be_reset_by_wizard(self):
        initialize_new_install(self.root, confirmed=True)
        activity = MaterialActivity(self.root / LEDGER)
        activity.add_spending(waveplates=120, solvents=2, claims=2)
        activity.save()
        before = (self.root / LEDGER).read_bytes()
        with self.assertRaises(RuntimeError):
            initialize_new_install(self.root, confirmed=True)
        self.assertEqual(before, (self.root / LEDGER).read_bytes())
        self.assertEqual(2, inspect_user_state(self.root)['ledger']['solvents_used'])

    def test_deleted_ledger_with_install_marker_is_not_fresh(self):
        initialize_new_install(self.root, confirmed=True)
        (self.root / LEDGER).unlink()
        (self.root / LEDGER.with_suffix('.json.backup')).unlink()
        state = inspect_user_state(self.root)
        self.assertEqual('history_unknown', state['status'])
        self.assertFalse(state['can_initialize'])
        self.assertFalse(state['can_use_solvents'])

    def test_corrupt_ledger_and_old_progress_block_first_use(self):
        for name, data in ((LEDGER, {'bad': True}),
                           ('configs/macos-desktop/team-material-progress.json', {'done': True})):
            with self.subTest(name=name):
                self.write(name, data)
                self.assertFalse(inspect_user_state(self.root)['can_initialize'])

    def test_archived_run_without_latest_report_is_still_history(self):
        self.write('logs/echo-1793362375000000000.json', {'status': 'completed'})
        self.assertFalse(inspect_user_state(self.root)['can_initialize'])
        self.assertEqual('history_unknown', inspect_user_state(self.root)['status'])

    def test_bad_or_empty_pending_is_never_ignored(self):
        path = self.write('logs/echo-claim-pending.json', {})
        path.write_text('broken')
        state = inspect_user_state(self.root)
        self.assertEqual('pending', state['status'])
        self.assertFalse(state['can_run'])
        self.assertEqual(1, state['pending_count'])
        self.assertEqual('invalid', inspect_recovery(self.root)['items'][0]['read_error'])

    def test_marker_left_after_interrupted_initialization_blocks_reset(self):
        with patch.object(MaterialActivity, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                initialize_new_install(self.root, confirmed=True)
        self.assertTrue((self.root / INSTALL).exists())
        self.assertEqual('history_unknown', inspect_user_state(self.root)['status'])
        self.assertFalse(inspect_user_state(self.root)['can_initialize'])

    def test_controller_lock_blocks_an_independent_initializer(self):
        lease = MacSession(self.root).acquire()
        try:
            with self.assertRaises(RuntimeError):
                initialize_new_install(self.root, confirmed=True)
            self.assertEqual('ready', initialize_new_install(self.root, confirmed=True, lease=lease)['status'])
            self.assertFalse(lease.handle.closed)
        finally:
            lease.close()

    def test_wrong_workspace_lease_is_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            lease = MacSession(other).acquire()
            try:
                with self.assertRaises(RuntimeError):
                    initialize_new_install(self.root, confirmed=True, lease=lease)
            finally:
                lease.close()

    def test_backup_keeps_existing_total_when_primary_is_invalid(self):
        initialize_new_install(self.root, confirmed=True)
        activity = MaterialActivity(self.root / LEDGER)
        activity.add_spending(solvents=7)
        activity.save()
        (self.root / LEDGER).write_text('broken')
        state = inspect_user_state(self.root)
        self.assertEqual('ready', state['status'])
        self.assertEqual(7, state['ledger']['solvents_used'])
        self.assertFalse(state['can_initialize'])

    def test_symlinked_state_directory_cannot_initialize_outside_root(self):
        with tempfile.TemporaryDirectory() as other:
            (self.root / 'configs').symlink_to(other, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                initialize_new_install(self.root, confirmed=True)
            self.assertEqual([], list(Path(other).iterdir()))

    def test_diagnostics_exports_only_selected_sanitized_text_and_keeps_guard(self):
        self.write('logs/echo-claim-pending.json', {'stage': '玄幽东岳无音区',
                   'claim_observation': {'stamina_before': 140, 'expected_cost': 120},
                   'budget': {'claim_pending': True}, 'account': 'MyPrivateName'})
        self.write('logs/echo-latest.json', {'status': 'stopped',
                   'error': 'UID:123456789 /Users/privateuser/work/token.json email@example.com',
                   'inventory_text': ['MyPrivateName', '123456789'], 'token': 'hidden-secret'})
        (self.root / 'logs/private.log').write_text('Do not export raw logs')
        destination = self.root / 'diagnostics.zip'
        export_diagnostics(self.root, destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(4, len(archive.namelist()))
            text = '\n'.join(archive.read(name).decode() for name in archive.namelist())
        for private in ('123456789', 'privateuser', 'email@example.com', 'hidden-secret', 'MyPrivateName', 'Do not export raw logs'):
            self.assertNotIn(private, text)
        self.assertTrue((self.root / 'logs/echo-claim-pending.json').exists())
        with self.assertRaises(FileExistsError):
            export_diagnostics(self.root, destination)


if __name__ == '__main__':
    unittest.main()
