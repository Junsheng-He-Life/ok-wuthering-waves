"""Saved-result recovery must be evidence-bound and idempotent across crashes."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src.runtime.DesktopClaimReconciliation import reconcile_echo_claim
from src.runtime.DesktopUserState import LEDGER, initialize_new_install
from src.task.EchoRunState import EchoRunState
from src.task.MaterialActivity import MaterialActivity
from src.task.MaterialRunBudget import MaterialRunBudget


class TestDesktopClaimReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        initialize_new_install(self.root, confirmed=True)
        self.task = EchoRunState()
        self.task.echo_pending_path = self.root / 'logs/echo-claim-pending.json'
        self.task.echo_state_path = self.root / 'configs/macos-desktop/echo-progress.json'
        self.task.activity_path = self.root / LEDGER
        self.task.exact_stage = '玄幽东岳无音区'
        self.task.echo_mode = 'tacet'
        self.task.plan_job = {'target': self.task.exact_stage, 'kind': '无音区声骸',
                              'resolved_stage': self.task.exact_stage}
        self.task.result = {'status': 'stopped', 'stage': self.task.exact_stage, 'mode': 'tacet'}
        self.task._run_budget = MaterialRunBudget(max_runs=2, max_stamina=120, max_reserve=0,
                                                  claim_cost=60, max_solvents=2, solvents_used=2)
        self.task.begin_echo_activity()
        self.task._claim_observation_context = {'started_ns': time.time_ns() - 5_000_000_000,
                                                'stamina_before': 140, 'expected_cost': 120, 'multiplier': 2}
        self.task._run_budget.begin_claim(2)
        self.task.checkpoint_claim()
        self.observation = self.make_observation()

    def make_observation(self, after=20, second=None, action='inspect', age=0):
        folder = self.root / 'logs/menu-inspection'
        folder.mkdir(parents=True, exist_ok=True)
        observations = []
        now = time.time_ns() - age
        for index, value in enumerate((after, after if second is None else second)):
            stamp = now - (2 - index) * 1_000_000_000
            image = folder / f'{stamp}-{index}.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'offline test image')
            observations.append({'image': str(image.relative_to(self.root)),
                                 'text': [{'text': '挑战成功'}, {'text': f'剩余{value}'}]})
        record = {'phase': 'menu-step', 'status': 'menu_observed', 'action': action,
                  'steps': [{'action': action, 'status': 'menu_observed'}], 'observations': observations}
        path = self.root / 'logs/recovery-inspection.json'
        path.write_text(json.dumps(record, ensure_ascii=False))
        return str(path.relative_to(self.root))

    def run_reconciliation(self):
        return reconcile_echo_claim(self.root, [self.observation])

    def ledger(self):
        return MaterialActivity(self.root / LEDGER).data

    def test_two_fresh_frames_finish_claim_without_recounting_solvents(self):
        baseline = json.loads(self.task.echo_pending_path.read_text())['ledger_baseline']
        self.assertEqual(2, baseline['solvents_used'])
        result = self.run_reconciliation()
        self.assertEqual('claim_reconciled', result['status'], result)
        self.assertFalse(result['already_accounted'])
        self.assertEqual((120, 2, 2), tuple(self.ledger()[key] for key in ('waveplates_spent', 'claim_units', 'solvents_used')))
        self.assertFalse(self.task.echo_pending_path.exists())
        checkpoint = json.loads(self.task.echo_state_path.read_text())
        self.assertEqual('claim_reconciled', checkpoint['status'])
        self.assertFalse(checkpoint['claim_reconciliation']['health_verified'])
        self.assertEqual('no_pending', self.run_reconciliation()['status'])

    def test_one_natural_tick_is_accepted(self):
        self.observation = self.make_observation(after=21)
        self.assertEqual('claim_reconciled', self.run_reconciliation()['status'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])

    def test_old_pending_without_ledger_baseline_is_never_guessed(self):
        data = json.loads(self.task.echo_pending_path.read_text())
        data.pop('ledger_baseline')
        self.task.echo_pending_path.write_text(json.dumps(data))
        result = self.run_reconciliation()
        self.assertEqual('pending', result['status'])
        self.assertTrue(self.task.echo_pending_path.exists())
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_wrong_or_disagreeing_observations_keep_guard(self):
        for values in ((20, 21), (30, 30)):
            self.observation = self.make_observation(after=values[0], second=values[1])
            self.assertEqual('pending', self.run_reconciliation()['status'])
            self.assertTrue(self.task.echo_pending_path.exists())
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_old_screenshot_or_input_action_cannot_reconcile(self):
        self.observation = self.make_observation(age=120_000_000_000)
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.observation = self.make_observation(action='text')
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_one_image_repeated_is_not_two_independent_observations(self):
        path = self.root / self.observation
        data = json.loads(path.read_text())
        data['observations'][1] = data['observations'][0]
        path.write_text(json.dumps(data))
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_malformed_observation_structure_is_reported_without_mutation(self):
        path = self.root / self.observation
        for field, value in (('steps', ['bad']), ('observations', 'bad')):
            self.observation = self.make_observation()
            data = json.loads(path.read_text())
            data[field] = value
            path.write_text(json.dumps(data))
            self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertTrue(self.task.echo_pending_path.exists())
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_observation_outside_installation_cannot_authorize_accounting(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / 'observation.json'
            outside.write_bytes((self.root / self.observation).read_bytes())
            result = reconcile_echo_claim(self.root, [str(outside)])
            self.assertEqual('pending', result['status'])
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_other_pending_spend_cannot_be_folded_into_claim(self):
        (self.root / 'logs/refill-use-pending.json').write_text('{"before": 20, "amount": 120}')
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(0, self.ledger()['waveplates_spent'])

    def test_ledger_changed_without_unique_receipt_is_not_counted_again(self):
        activity = MaterialActivity(self.root / LEDGER)
        activity.add_spending(waveplates=120, claims=2)
        activity.save()
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])
        self.assertTrue(self.task.echo_pending_path.exists())

    def test_normal_runner_receipt_proves_counted_claim_after_checkpoint_crash(self):
        self.task._run_budget.finish_claim(140, 20)
        self.task._last_claim_stamina = (140, 20)
        with patch.object(self.task, 'save_echo_progress', side_effect=OSError('checkpoint interrupted')):
            with self.assertRaises(OSError):
                self.task.checkpoint_claim()
        self.assertEqual(120, self.ledger()['waveplates_spent'])
        self.assertTrue(self.task.echo_pending_path.exists())
        result = self.run_reconciliation()
        self.assertEqual('claim_reconciled', result['status'], result)
        self.assertTrue(result['already_accounted'])
        self.assertEqual((120, 2, 2), tuple(self.ledger()[key] for key in ('waveplates_spent', 'claim_units', 'solvents_used')))

    def test_recovery_crash_after_ledger_save_retries_idempotently(self):
        from src.runtime import DesktopClaimReconciliation as module
        original = module._atomic_json

        def fail_checkpoint(path, data):
            if path == self.task.echo_state_path:
                raise OSError('interrupted checkpoint')
            return original(path, data)

        with patch.object(module, '_atomic_json', side_effect=fail_checkpoint):
            result = self.run_reconciliation()
        self.assertEqual('pending', result['status'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])
        result = self.run_reconciliation()
        self.assertEqual('claim_reconciled', result['status'], result)
        self.assertTrue(result['already_accounted'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])

    def test_recovery_crash_after_checkpoint_before_archive_is_idempotent(self):
        original = Path.replace

        def fail_archive(path, destination):
            if path == self.task.echo_pending_path:
                raise OSError('archive interrupted')
            return original(path, destination)

        with patch.object(Path, 'replace', fail_archive):
            self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])
        result = self.run_reconciliation()
        self.assertEqual('claim_reconciled', result['status'], result)
        self.assertTrue(result['already_accounted'])
        self.assertEqual(120, self.ledger()['waveplates_spent'])

    def test_finished_checkpoint_without_receipt_is_ambiguous(self):
        self.task._run_budget.finish_claim(140, 20)
        self.task.save_echo_progress()
        self.assertEqual('pending', self.run_reconciliation()['status'])
        self.assertEqual(0, self.ledger()['waveplates_spent'])


if __name__ == '__main__':
    unittest.main()
