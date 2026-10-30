"""Per-run limits; a pending claim cannot be retried after uncertain input."""
from dataclasses import dataclass


@dataclass
class MaterialRunBudget:
    max_runs: int = 2
    max_stamina: int = 80
    max_reserve: int = 60
    max_retries: int = 1
    claimed: int = 0
    spent: int = 0
    reserve_used: int = 0
    retries: int = 0
    claim_pending: bool = False
    claim_cost: int = 40
    claim_multiplier: int = 1
    max_solvents: int = 0
    solvents_used: int = 0

    def __post_init__(self):
        if not ((self.max_runs == -1 or 1 <= self.max_runs <= 100) and (self.max_stamina == -1 or 0 <= self.max_stamina <= 4000)
                and (self.max_reserve == -1 or 0 <= self.max_reserve <= 240) and 0 <= self.max_retries <= 3
                and (self.max_solvents == -1 or 0 <= self.max_solvents <= 133) and self.claim_cost in (40, 60)):
            raise ValueError('invalid material run limits')

    def can_claim(self, multiplier=1):
        return (multiplier in (1, 2) and not self.claim_pending
                and (self.max_runs == -1 or self.claimed + multiplier <= self.max_runs)
                and (self.max_stamina == -1 or self.spent + self.claim_cost * multiplier <= self.max_stamina))

    def begin_claim(self, multiplier=1):
        if not self.can_claim(multiplier):
            raise RuntimeError('reward limit reached or previous claim uncertain')
        self.claim_multiplier = multiplier
        self.claim_pending = True

    def cancel_rejected_claim(self):
        """Caller must positively identify the insufficient-waveplate panel."""
        if not self.claim_pending:
            raise RuntimeError("no pending rejected claim")
        self.claim_pending = False

    def finish_claim(self, before, after):
        cost = self.claim_cost * self.claim_multiplier
        # One natural regeneration tick can overlap settlement.
        if not self.claim_pending or before - after not in (cost - 1, cost):
            raise RuntimeError('reward stamina delta uncertain; never retry claim')
        self.claimed += self.claim_multiplier
        self.spent += cost
        self.claim_pending = False

    def record_refill(self, amount):
        if amount <= 0 or (self.max_reserve != -1 and self.reserve_used + amount > self.max_reserve):
            raise RuntimeError('reserve refill limit exceeded')
        # Reserve the allowance BEFORE input, even if the outcome is uncertain.
        self.reserve_used += amount

    def record_solvent(self):
        if self.max_solvents != -1 and self.solvents_used >= self.max_solvents:
            raise RuntimeError('solvent allowance exhausted')
        self.solvents_used += 1

    def retry(self):
        if self.claim_pending or self.retries >= self.max_retries:
            raise RuntimeError('recovery limit reached; stop')
        self.retries += 1
