"""Spending limits survive restart, missing files, and interrupted snapshot saves."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.task.MaterialActivity import MaterialActivity, _atomic_json
from src.task.MaterialRunBudget import MaterialRunBudget


class TestMaterialActivity(unittest.TestCase):
    def legacy(self, path, used=33):
        path.write_text(json.dumps({'schema': 1, 'solvents_used': used,
            'waveplates_spent': 940, 'claim_units': 23,
            'reserve_waveplates_used': 164, 'elapsed_seconds': 7020,
            'events': [], 'materials': {}}))
        return MaterialActivity(path)

    def test_minus_one_means_seventeen_remaining_not_unlimited(self):
        with tempfile.TemporaryDirectory() as folder:
            activity = self.legacy(Path(folder) / 'ledger.json')
            budget = MaterialRunBudget(max_solvents=activity.solvent_allowance(-1, 50))
            self.assertEqual(17, budget.max_solvents)
            for _ in range(17):
                budget.record_solvent()
            with self.assertRaises(RuntimeError):
                budget.record_solvent()
            self.assertEqual(2, activity.solvent_allowance(2, 50))
            self.assertEqual(17, activity.solvent_allowance(50, 50))

    def test_missing_history_stays_locked_after_save_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            activity = MaterialActivity(path)
            activity.add_spending(waveplates=80, claims=2)
            activity.save()
            activity = MaterialActivity(path)
            self.assertEqual(80, activity.data['waveplates_spent'])
            self.assertEqual(0, activity.solvent_allowance(-1, 50))
            self.assertFalse(activity.data['history_verified'])

    def test_missing_or_corrupt_main_recovers_latest_spending(self):
        for corrupt in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'ledger.json'
                activity = self.legacy(path)
                activity.add_spending(solvents=1)
                activity.save()
                path.write_text('{broken') if corrupt else path.unlink()
                restored = MaterialActivity(path)
                self.assertEqual(34, restored.data['solvents_used'])
                self.assertEqual(16, restored.solvent_allowance(-1, 50))

    def test_failure_between_backup_and_main_cannot_reopen_allowance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            activity = self.legacy(path)
            activity.add_spending(solvents=1)
            def write(destination, data):
                if destination == path:
                    raise OSError('interrupted before main write')
                _atomic_json(destination, data)
            with patch('src.task.MaterialActivity._atomic_json', side_effect=write):
                with self.assertRaises(OSError):
                    activity.save()
            self.assertEqual(16, MaterialActivity(path).solvent_allowance(-1, 50))

    def test_exhausted_or_invalid_history_never_grants_allowance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.json'
            for used in (50, 51):
                self.assertEqual(0, self.legacy(path, used).solvent_allowance(-1, 50))
            for used in (-1, '33', True):
                self.assertEqual(0, self.legacy(path, used).solvent_allowance(-1, 50))
