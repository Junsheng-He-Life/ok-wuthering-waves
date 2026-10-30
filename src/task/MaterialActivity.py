"""Persist material farming time, spending, and per-target claim history."""
import json
import os
from datetime import datetime
from pathlib import Path


SOLVENT_TOTAL_CONFIG = '累计溶剂授权上限'
SOLVENT_TOTAL_DESCRIPTION = '默认0；填写本账号允许累计使用的总数（包含账本已用数量），不是新增额度。历史账本未知时仍禁止使用；材料与声骸共用已用数量。'


def configured_solvent_total(settings):
    """No personal authorization is inherited from the source distribution."""
    value = settings.get(SOLVENT_TOTAL_CONFIG, 0)
    if type(value) is not int or value < 0:
        raise ValueError('累计溶剂授权上限须为非负整数；0表示不授权')
    return value


def _now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class MaterialActivity:
    """Cumulative ledger, independent of the current run's spending caps."""

    def __init__(self, path='logs/material-status/activity.json'):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + '.backup')
        candidates = []
        for candidate in (self.path, self.backup_path):
            try:
                data = json.loads(candidate.read_text(encoding='utf-8'))
                counters = ('solvents_used', 'waveplates_spent', 'claim_units',
                            'reserve_waveplates_used', 'elapsed_seconds')
                if not isinstance(data, dict) or any(
                        type(data.get(key)) is not int or data[key] < 0 for key in counters):
                    continue
                revision = data.get('ledger_revision', 0)
                if type(revision) is not int or revision < 0:
                    continue
                if type(data.get('history_verified', True)) is not bool:
                    continue
                candidates.append(data)
            except (OSError, ValueError):
                continue
        if candidates:
            # Both snapshots contain cumulative counters. Select the newest
            # revision and never restore a smaller spending counter from a
            # partially written pair. Legacy schema-1 ledgers remain valid.
            self.data = max(candidates, key=lambda d: d.get('ledger_revision', 0))
            for key in counters:
                self.data[key] = max(d[key] for d in candidates)
            self.data.setdefault('history_verified', True)
        else:
            # A missing ledger is not evidence of unused authorization. Starting
            # from a hard-coded historical balance used to reopen spent quota.
            self.data = {
                'schema': 2, 'created_at': _now(), 'updated_at': _now(),
                'elapsed_seconds': 0, 'waveplates_spent': 0, 'claim_units': 0,
                'solvents_used': 0, 'reserve_waveplates_used': 0,
                'history_verified': False, 'materials': {}, 'events': [],
                'baseline_note': '历史账本缺失或损坏；当前统计仅含新记录，溶剂额度锁定，需恢复已核对的历史账本。',
            }

    def solvent_allowance(self, requested, total):
        """Resolve -1 to the remaining cumulative allowance, never infinity."""
        requested, total = int(requested), int(total)
        if requested < -1 or total < 0:
            raise ValueError('invalid solvent authorization')
        if not self.data.get('history_verified', False):
            return 0
        remaining = max(0, total - self.data['solvents_used'])
        return remaining if requested == -1 else min(requested, remaining)

    def add_elapsed(self, seconds, job=None):
        seconds = int(max(0, seconds))
        self.data['elapsed_seconds'] = int(self.data.get('elapsed_seconds', 0) + seconds)
        if seconds and job:
            target, kind = job.get('target', '未知角色'), job.get('kind', '未知材料')
            key = f'{target}｜{kind}'
            totals = self.data.setdefault('materials', {}).setdefault(key, {
                'target': target, 'kind': kind, 'stage': '',
                'claim_units': 0, 'waveplates_spent': 0, 'active_seconds': 0,
            })
            totals['active_seconds'] = int(totals.get('active_seconds') or 0) + seconds

    def add_spending(self, *, waveplates=0, claims=0, solvents=0, reserve=0,
                     job=None, active_seconds=0, stamina_before=None, stamina_after=None):
        waveplates, claims = max(0, int(waveplates)), max(0, int(claims))
        solvents, reserve = max(0, int(solvents)), max(0, int(reserve))
        self.data['waveplates_spent'] = int(self.data.get('waveplates_spent', 0)) + waveplates
        self.data['claim_units'] = int(self.data.get('claim_units', 0)) + claims
        self.data['solvents_used'] = int(self.data.get('solvents_used', 0)) + solvents
        self.data['reserve_waveplates_used'] = int(self.data.get('reserve_waveplates_used', 0)) + reserve
        if claims and job:
            target = job.get('target', '未知角色')
            kind = job.get('kind', '未知材料')
            stage = job.get('resolved_stage') or job.get('route', {}).get('fallback_stage_name', '')
            key = f'{target}｜{kind}'
            totals = self.data.setdefault('materials', {}).setdefault(key, {
                'target': target, 'kind': kind, 'stage': stage,
                'claim_units': 0, 'waveplates_spent': 0, 'active_seconds': 0,
            })
            totals['stage'] = stage or totals.get('stage', '')
            totals['claim_units'] += claims
            totals['waveplates_spent'] += waveplates
            self.data.setdefault('events', []).append({
                'at': _now(), 'target': target, 'kind': kind, 'stage': stage,
                'claim_units': claims, 'waveplates_spent': waveplates,
                'active_seconds': int(max(0, active_seconds)),
                'stamina_before': stamina_before, 'stamina_after': stamina_after,
            })
            self.data['events'] = self.data['events'][-100:]

    def save(self, status=None, current_job=None):
        self.data['updated_at'] = _now()
        if status is not None:
            self.data['status'] = status
        self.data['current_job'] = current_job
        self.data['ledger_revision'] = int(self.data.get('ledger_revision', 0)) + 1
        # Write the recovery copy first so it cannot lag a successful main save.
        _atomic_json(self.backup_path, self.data)
        _atomic_json(self.path, self.data)
        return self.data


def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}小时{minutes}分'
    if minutes:
        return f'{minutes}分{secs}秒'
    return f'{secs}秒'
