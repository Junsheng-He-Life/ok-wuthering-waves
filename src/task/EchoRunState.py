"""Durable echo checkpoints and the existing shared resource ledger."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from src.task.MaterialActivity import MaterialActivity, _atomic_json
from src.task.EchoClaimAudit import echo_claim_id, ledger_spending


class EchoRunState:
    echo_pending_path = Path('logs/echo-claim-pending.json')
    echo_state_path = Path('configs/macos-desktop/echo-progress.json')
    activity_path = Path('configs/macos-desktop/team-material-activity.json')
    material_state_path = Path('configs/macos-desktop/team-material-needs-progress.json')

    def assert_echo_start_safe(self):
        self.assert_no_pending_refill()
        if self.echo_pending_path.exists():
            raise RuntimeError('上次声骸领奖结果未核对；禁止重复消费')
        if self.material_state_path.exists():
            state = json.loads(self.material_state_path.read_text())
            if state.get('claim_pending'):
                raise RuntimeError('材料队列有待核对领奖；先核对原结算')

    def begin_echo_activity(self):
        self._activity = MaterialActivity(self.activity_path)
        self._echo_started = time.monotonic()
        self._echo_elapsed_saved = 0
        self._echo_paused = 0
        self._echo_pause_started = None
        self._echo_cursor = dict(claimed=0, spent=0, solvents_used=0, reserve_used=0)

    def update_activity(self):
        if getattr(self, '_activity', None) is None:
            return
        budget = self._run_budget
        cursor = self._echo_cursor
        paused = self._echo_paused
        if self._echo_pause_started is not None:
            paused += time.monotonic() - self._echo_pause_started
        elapsed = int(max(0, time.monotonic() - self._echo_started - paused))
        self._activity.add_elapsed(max(0, elapsed - self._echo_elapsed_saved), self.plan_job)
        self._echo_elapsed_saved = elapsed
        before, after = getattr(self, '_last_claim_stamina', (None, None))
        self._activity.add_spending(
            waveplates=budget.spent - cursor['spent'], claims=budget.claimed - cursor['claimed'],
            solvents=budget.solvents_used - cursor['solvents_used'],
            reserve=budget.reserve_used - cursor['reserve_used'], job=self.plan_job,
            stamina_before=before, stamina_after=after)
        # The in-memory ledger already contains these deltas. Advance before
        # saving so a failed disk write followed by final cleanup cannot add
        # the same confirmed spend a second time.
        cursor.update({key: getattr(budget, key) for key in cursor})
        self._activity.save(status=self.result['status'], current_job=self.plan_job)

    def checkpoint_claim(self):
        # The guard is written before the claim click and removed only after
        # its result (or an explicit rejection) and ledger have been saved.
        if self._run_budget.claim_pending:
            record = {
                'stage': self.exact_stage, 'mode': self.echo_mode,
                'budget': asdict(self._run_budget),
                'claim_observation': getattr(self, '_claim_observation_context', None)}
            _atomic_json(self.echo_pending_path, record)
        elif self.echo_pending_path.exists():
            raw_pending = self.echo_pending_path.read_bytes()
            pending = json.loads(raw_pending)
            previous = pending.get('budget', {})
            context = pending.get('claim_observation') or {}
            before, after = getattr(self, '_last_claim_stamina', (None, None))
            cost = self._run_budget.spent - previous.get('spent', self._run_budget.spent)
            units = self._run_budget.claimed - previous.get('claimed', self._run_budget.claimed)
            if (cost > 0 and units > 0 and context.get('stamina_before') == before
                    and isinstance(after, int) and before - after in (cost, cost - 1)):
                # This receipt is committed atomically with ledger counters. A
                # restart after ledger save but before guard deletion can prove
                # that the claim was already counted, rather than counting twice.
                self._activity.data.setdefault('claim_transactions', {})[echo_claim_id(raw_pending)] = {
                    'waveplates': cost, 'claims': units,
                    'stamina_before': before, 'stamina_after': after}
        self.update_activity()
        if self._run_budget.claim_pending:
            record['ledger_baseline'] = {
                **ledger_spending(self._activity.data),
                'ledger_revision': self._activity.data.get('ledger_revision', 0)}
            record['ledger_cursor'] = self._echo_cursor.copy()
            _atomic_json(self.echo_pending_path, record)
        self.save_echo_progress()
        if not self._run_budget.claim_pending:
            self.echo_pending_path.unlink(missing_ok=True)

    def save_echo_progress(self):
        self.result['budget'] = asdict(self._run_budget)
        _atomic_json(self.echo_state_path, self.result)

    def save_run_report(self):
        self.save_echo_progress()
        _atomic_json(Path('logs/echo-latest.json'), self.result)
        _atomic_json(Path('logs') / f'echo-{time.time_ns()}.json', self.result)

    def pause(self):
        if getattr(self, '_activity', None) is not None and self._echo_pause_started is None:
            self._echo_pause_started = time.monotonic()
        return super().pause()

    def unpause(self):
        if getattr(self, '_echo_pause_started', None) is not None:
            self._echo_paused += time.monotonic() - self._echo_pause_started
            self._echo_pause_started = None
        return super().unpause()
