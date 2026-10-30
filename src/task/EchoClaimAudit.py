"""Shared identity and ledger receipt for one durable Echo claim guard."""
import hashlib


SPENDING_COUNTERS = ('waveplates_spent', 'claim_units', 'reserve_waveplates_used', 'solvents_used')


def echo_claim_id(raw_pending):
    return 'echo:' + hashlib.sha256(raw_pending).hexdigest()


def ledger_spending(data):
    return {key: data[key] for key in SPENDING_COUNTERS}
