"""Reconcile one saved Echo receipt from two fresh, input-free observations.

No number is supplied by the user, no game input is sent, and no ambiguous guard
is cleared. The normal runner and this recovery path share a durable ledger ID.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from src.runtime.DesktopUserState import (LEDGER, _controller_lease, inspect_user_state,
                                         pending_records, read_json_record)
from src.task.EchoClaimAudit import echo_claim_id, ledger_spending
from src.task.MaterialActivity import MaterialActivity, _atomic_json
from src.task.MaterialRunBudget import MaterialRunBudget


PENDING = Path('logs/echo-claim-pending.json')
CHECKPOINT = Path('configs/macos-desktop/echo-progress.json')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _local_record(root, relative):
    path = root / relative
    _require(not path.is_symlink()
             and path.resolve().is_relative_to(root), '核对文件必须来自当前安装。')
    record, error = read_json_record(path)
    _require(record is not None and error is None, '核对记录无法完整读取。')
    return path, record


def _fresh_observations(root, paths, started_ns):
    _require(isinstance(paths, (list, tuple)) and 1 <= len(paths) <= 4, '请先读取当前结算页面。')
    samples = {}
    now = time.time_ns()
    for relative in paths:
        path, report = _local_record(root, relative)
        _require(path.resolve().is_relative_to(root / 'logs'), '观察记录必须来自本安装的日志目录。')
        steps = report.get('steps', [])
        _require(report.get('phase') == 'menu-step' and report.get('status') == 'menu_observed'
                 and isinstance(steps, list) and steps
                 and all(isinstance(step, dict) and step.get('action') == 'inspect' and step.get('status') == 'menu_observed'
                                   for step in steps), '只能使用成功的只读页面观察。')
        rows = report.get('observations', [])
        _require(isinstance(rows, list), '页面观察数据不完整。')
        for observation in rows[:16]:
            if not isinstance(observation, dict):
                continue
            image_relative = observation.get('image', '')
            image = root / image_relative
            match = re.fullmatch(r'(\d+)-.*\.png', image.name)
            if not match:
                continue
            captured = int(match[1])
            if not (started_ns <= captured <= now and now - captured <= 90_000_000_000):
                continue
            _require(not Path(image_relative).is_absolute() and image.is_file() and not image.is_symlink()
                     and image.resolve().is_relative_to(root / 'logs/menu-inspection')
                     and image.stat().st_size <= 20_000_000,
                     '观察截图不属于本次菜单检查。')
            with image.open('rb') as stream:
                _require(stream.read(8) == b'\x89PNG\r\n\x1a\n', '观察截图不完整。')
            words = [re.sub(r'\s+', '', row.get('text', '')) for row in observation.get('text', [])
                     if isinstance(row, dict) and isinstance(row.get('text'), str)]
            remaining = {int(found[1]) for word in words if (found := re.fullmatch(r'剩余(\d+)', word))}
            if '挑战成功' not in words or len(remaining) != 1:
                continue
            value = remaining.pop()
            if 0 <= value <= 240:
                samples[image_relative] = {'image': image_relative, 'observed_ns': captured,
                                           'stamina_after': value, 'source_file': str(path.relative_to(root)),
                                           'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
    ordered = sorted(samples.values(), key=lambda row: row['observed_ns'])
    _require(len(ordered) >= 2, '需要两张新鲜截图同时确认“挑战成功”和剩余波片。请保留结算页并重新读取。')
    first, last = ordered[-2:]
    _require(last['observed_ns'] - first['observed_ns'] >= 250_000_000,
             '两次观察间隔过短，请重新读取结算。')
    _require(first['stamina_after'] == last['stamina_after'], '两次剩余波片不一致，请等待页面稳定后重新读取。')
    return [first, last]


def reconcile_echo_claim(root, observation_paths, lease=None):
    """Finish durable bookkeeping when saved evidence proves the pending claim.

    A caller-owned acquired MacSession may be passed by the desktop application.
    Otherwise this operation obtains the normal lease itself. Any failed check
    returns ``pending`` and leaves the original guard untouched.
    """
    root = Path(root).resolve()
    try:
        with _controller_lease(root, lease):
            return _reconcile_locked(root, observation_paths)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        return {'status': 'pending', 'title': '暂时无法自动核对',
                'message': str(exc), 'next_action': '保留原结算页和记录；可重新读取页面或导出诊断。',
                'claim_pending': (root / PENDING).exists()}


def _reconcile_locked(root, observation_paths):
    if not (root / PENDING).exists():
        return {'status': 'no_pending', 'message': '没有需要核对的声骸领奖记录。', 'claim_pending': False}
    pending_path, pending = _local_record(root, PENDING)
    raw = pending_path.read_bytes()
    identity = echo_claim_id(raw)
    _require(pending.get('mode') in ('boss', 'tacet') and isinstance(pending.get('stage'), str)
             and bool(pending['stage'].strip()), '原声骸关卡或模式无效。')
    _require(not any(relative != PENDING.as_posix() and not relative.endswith('echo-progress.json')
                     for relative, _, _ in pending_records(root)), '另有补给或材料消费待核对，不能合并处理。')
    context, baseline = pending.get('claim_observation'), pending.get('ledger_baseline')
    _require(isinstance(context, dict) and isinstance(baseline, dict),
             '此旧记录缺少消费前或账本基线证据，不能自动补记。')
    started, before, expected = (context.get(key) for key in ('started_ns', 'stamina_before', 'expected_cost'))
    _require(type(started) is int and started > 0 and type(before) is int and 0 <= before <= 240
             and type(expected) is int and expected in (60, 120), '消费前记录不完整，不能自动补记。')
    values = pending.get('budget', {})
    _require(isinstance(values, dict) and values.get('claim_pending') is True
             and all(type(value) is (bool if key == 'claim_pending' else int) for key, value in values.items()),
             '原奖励预算无效。')
    budget = MaterialRunBudget(**values)
    _require(budget.claim_cost == 60 and budget.claim_multiplier in (1, 2)
             and budget.claim_cost * budget.claim_multiplier == expected, '奖励倍率或消费额不一致。')
    cursor = pending.get('ledger_cursor', {})
    _require(isinstance(cursor, dict) and all(cursor.get(key) == values.get(key)
                                            for key in ('claimed', 'spent', 'solvents_used', 'reserve_used')),
             '消费前记账位置无法确认。')
    observations = _fresh_observations(root, observation_paths, started)
    after = observations[-1]['stamina_after']
    budget.finish_claim(before, after)
    finished = asdict(budget)
    _require(budget.spent <= budget.max_stamina and budget.claimed <= budget.max_runs,
             '核对结果超出原任务额度。')
    checkpoint_path, checkpoint = _local_record(root, CHECKPOINT)
    _require(checkpoint.get('stage') == pending.get('stage') and checkpoint.get('mode') == pending.get('mode')
             and checkpoint.get('budget') in (values, finished), '当前任务检查点与原领奖记录不一致。')
    state = inspect_user_state(root)
    _require(state['ledger'] and all(type(baseline.get(key)) is int and baseline[key] >= 0
                                   for key in (*ledger_spending(state['ledger']), 'ledger_revision')),
             '账本基线无法读取。')
    for path in (root / LEDGER, root / LEDGER.with_suffix('.json.backup')):
        _require(not path.is_symlink() and path.resolve().is_relative_to(root), '账本路径需要恢复。')
    activity = MaterialActivity(root / LEDGER)
    _require(activity.data.get('history_verified') is True, '历史资源账本尚未确认。')
    current = ledger_spending(activity.data)
    base = {key: baseline[key] for key in current}
    target = {**base, 'waveplates_spent': base['waveplates_spent'] + expected,
              'claim_units': base['claim_units'] + budget.claim_multiplier}
    transactions = activity.data.get('claim_transactions', {})
    _require(isinstance(transactions, dict), '已记账标记无法读取，请保留账本。')
    receipt = transactions.get(identity)
    if receipt is not None:
        _require(isinstance(receipt, dict) and receipt.get('waveplates') == expected
                 and receipt.get('claims') == budget.claim_multiplier and receipt.get('stamina_before') == before
                 and type(receipt.get('stamina_after')) is int
                 and before - receipt['stamina_after'] in (expected, expected - 1)
                 and current == target, '已记账标记与当前总额不一致，保留原记录。')
    else:
        _require(current == base and checkpoint.get('budget') == values,
                 '账本已发生变化且没有本笔确认标记，不能判断是否已记账；保留原记录。')
    _require(activity.data.get('ledger_revision', 0) >= baseline['ledger_revision'], '账本版本早于消费前记录。')
    folder = root / 'logs/reconciled'
    folder.mkdir(parents=True, exist_ok=True)
    name = identity.split(':')[1]
    audit_path, archive = folder / f'echo-{name}.audit.json', folder / f'echo-{name}.pending.json'
    audit = {'schema': 1, 'claim_id': identity, 'stage': pending.get('stage'), 'mode': pending.get('mode'),
             'stamina_before': before, 'stamina_after': after, 'waveplates': expected,
             'claims': budget.claim_multiplier, 'ledger_before': current, 'ledger_target': target,
             'observations': observations, 'status': 'evidence_verified'}
    _atomic_json(audit_path, audit)
    if receipt is None:
        activity.data.setdefault('claim_transactions', {})[identity] = {
            'waveplates': expected, 'claims': budget.claim_multiplier,
            'stamina_before': before, 'stamina_after': after}
        activity.add_spending(waveplates=expected, claims=budget.claim_multiplier,
                              job={'target': pending['stage'], 'kind': '声骸领奖核对',
                                   'resolved_stage': pending['stage']}, stamina_before=before, stamina_after=after)
        activity.save(status='claim_reconciled')
    checkpoint.update(status='claim_reconciled', current_stage='领奖已核对', budget=finished,
                      claim_reconciliation={'claim_id': identity, 'audit': str(audit_path.relative_to(root)),
                                            'health_verified': False, 'return_verified': False})
    _atomic_json(checkpoint_path, checkpoint)
    _atomic_json(root / 'logs/echo-latest.json', checkpoint)
    audit['status'] = 'ledger_and_checkpoint_saved'
    _atomic_json(audit_path, audit)
    _require(not archive.exists() or archive.read_bytes() == raw, '归档位置已有不同记录。')
    pending_path.replace(archive)
    audit['status'] = 'reconciled'
    try:
        _atomic_json(audit_path, audit)
    except OSError:
        # The ledger, checkpoint, audit evidence and archived guard are already
        # durable. A cosmetic final audit status cannot undo that committed result.
        pass
    return {'status': 'claim_reconciled', 'title': '这笔领奖已核对',
            'message': f'已确认消耗{expected}波片，奖励计数{budget.claim_multiplier}份。补给未重复记账。',
            'next_action': '领取结果已确认；返回大世界并检查队伍状态后再开始下一轮。',
            'claim_pending': False, 'waveplates': expected, 'claims': budget.claim_multiplier,
            'already_accounted': receipt is not None, 'audit': str(audit_path.relative_to(root))}
