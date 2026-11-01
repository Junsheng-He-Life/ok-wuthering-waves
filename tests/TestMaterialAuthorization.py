"""Distribution defaults cannot inherit another player's solvent permission."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.task.MaterialActivity import MaterialActivity, SOLVENT_TOTAL_CONFIG, configured_solvent_total
from src.task.SafeMaterialTask import SafeMaterialTask
from src.task.TeamMaterialTask import TeamMaterialTask
from src.task.EchoFarmTask import BossEchoTask


class TestMaterialAuthorization(unittest.TestCase):
    def ledger(self, path, used):
        path.write_text(json.dumps({'schema': 2, 'history_verified': True,
            'solvents_used': used, 'waveplates_spent': 0, 'claim_units': 0,
            'reserve_waveplates_used': 0, 'elapsed_seconds': 0,
            'events': [], 'materials': {}}))
        return MaterialActivity(path)

    def test_new_task_defaults_do_not_grant_refills(self):
        with patch.object(SafeMaterialTask, '__init__', return_value=None):
            for cls in (TeamMaterialTask, BossEchoTask):
                task = cls()
                self.assertEqual(0, task.default_config['本次溶剂上限'])
                self.assertEqual(0, task.default_config['本次储备上限'])
                self.assertEqual(0, configured_solvent_total(task.default_config))

    def test_old_settings_do_not_inherit_a_source_code_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            activity = self.ledger(Path(folder) / 'activity.json', 138)
            self.assertEqual(0, activity.solvent_allowance(20, configured_solvent_total({})))
            settings = {SOLVENT_TOTAL_CONFIG: 183}
            self.assertEqual(45, activity.solvent_allowance(-1, configured_solvent_total(settings)))
            self.assertEqual(20, activity.solvent_allowance(20, configured_solvent_total(settings)))
            self.assertEqual(138, activity.data['solvents_used'])

    def test_invalid_or_unlimited_cumulative_caps_are_rejected(self):
        for value in (-1, True, '183', 1.5, float('inf'), None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configured_solvent_total({SOLVENT_TOTAL_CONFIG: value})

    def test_explicit_cap_does_not_bypass_missing_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            activity = MaterialActivity(Path(folder) / 'missing.json')
            self.assertEqual(0, activity.solvent_allowance(20, configured_solvent_total({SOLVENT_TOTAL_CONFIG: 183})))

    def test_echo_uses_configured_total_and_shared_consumption(self):
        with tempfile.TemporaryDirectory() as folder:
            task = BossEchoTask.__new__(BossEchoTask)
            task._activity = self.ledger(Path(folder) / 'activity.json', 7)
            task.result = {}
            task.config = {'声骸关卡': '哀声鸷', '本次战斗上限': 2,
                           '战后领奖': True, '本次最多领奖': 2, '本次波片上限': 120,
                           '本次储备上限': 0, '本次溶剂上限': 10, SOLVENT_TOTAL_CONFIG: 9}
            task.configure_echo_run()
            self.assertEqual(2, task._run_budget.max_solvents)


if __name__ == '__main__':
    unittest.main()
