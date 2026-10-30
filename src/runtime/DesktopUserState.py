"""Read desktop setup state and explicitly initialize a genuinely new installation.

Inspection never constructs a device or rewrites existing user state. Initialization
shares the game controller lease so a running task cannot race ledger creation.
"""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import uuid

from src.runtime.MacSession import MacSession
from src.task.MaterialActivity import MaterialActivity, _atomic_json


LEDGER = Path('configs/macos-desktop/team-material-activity.json')
INSTALL = Path('configs/macos-desktop/desktop-install.json')
COUNTERS = ('waveplates_spent', 'claim_units', 'solvents_used',
            'reserve_waveplates_used', 'elapsed_seconds')
PENDING = ('logs/echo-claim-pending.json', 'logs/refill-use-pending.json',
           'logs/solvent-use-pending.json')
PROGRESS = ('configs/macos-desktop/team-material-needs-progress.json',
            'configs/macos-desktop/team-material-progress.json',
            'configs/macos-desktop/echo-progress.json')


def read_json_record(path, limit=2_000_000):
    """Return a bounded JSON object and a public error code, without exceptions."""
    path = Path(path)
    if not path.exists():
        return None, None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            return None, 'unreadable'
        value = json.loads(path.read_text(encoding='utf-8'))
        return (value, None) if isinstance(value, dict) else (None, 'invalid')
    except (OSError, ValueError, UnicodeError):
        return None, 'invalid'


def pending_records(root):
    """Existing guards block even when malformed; malformed progress also blocks."""
    root = Path(root)
    records = []
    for relative in PENDING:
        path = root / relative
        if path.exists() or path.is_symlink():
            data, error = read_json_record(path)
            records.append((relative, data or {}, error))
    for relative in PROGRESS:
        data, error = read_json_record(root / relative)
        budget = (data or {}).get('budget', {})
        pending = ((data or {}).get('claim_pending') or
                   (isinstance(budget, dict) and budget.get('claim_pending')))
        if error or pending:
            records.append((relative, data or {}, error))
    return records


def _history_exists(root):
    exact = (*PROGRESS, 'logs/material-latest.json', 'logs/echo-latest.json',
             'logs/team-material-latest.json', 'logs/material-status/activity.json')
    if any((root / name).exists() or (root / name).is_symlink() for name in exact):
        return True
    # Legacy/reconciled records are evidence that this is not a blank install.
    for folder, patterns in ((root / 'logs', ('*pending*.json', '*reconciled*.json',
                                            'echo-*.json', 'material-*.json', 'team-material-*.json')),
                             (root / 'logs/reconciled', ('*.json',)),
                             (root / 'configs/macos-desktop', ('*activity*', '*progress*'))):
        if folder.is_dir() and any(next(folder.glob(pattern), None) is not None for pattern in patterns):
            return True
    return False


def _ledger_snapshot(root):
    candidates = []
    for path in (root / LEDGER, root / LEDGER.with_suffix('.json.backup')):
        data, error = read_json_record(path)
        if (error or not data or not path.resolve().is_relative_to(root)
                or any(type(data.get(key)) is not int or data[key] < 0 for key in COUNTERS)
                or type(data.get('ledger_revision', 0)) is not int
                or data.get('ledger_revision', 0) < 0
                or type(data.get('history_verified', True)) is not bool):
            continue
        candidates.append(data)
    if not candidates:
        return {'history_verified': False, **dict.fromkeys((*COUNTERS, 'ledger_revision'), 0)}
    selected = max(candidates, key=lambda row: row.get('ledger_revision', 0)).copy()
    selected.update({key: max(row[key] for row in candidates) for key in COUNTERS})
    return selected


def inspect_user_state(root):
    """Return UI-ready state without treating a missing old ledger as unused quota."""
    root = Path(root).resolve()
    ledger = _ledger_snapshot(root)
    pending = pending_records(root)
    marker, marker_error = read_json_record(root / INSTALL)
    marker_exists = (root / INSTALL).exists() or (root / INSTALL).is_symlink()
    ledger_exists = any(path.exists() or path.is_symlink() for path in (
        root / LEDGER, root / LEDGER.with_suffix('.json.backup')))
    is_new = not (pending or marker_exists or ledger_exists or _history_exists(root))
    verified = bool(ledger.get('history_verified', True))
    incomplete = bool(marker_exists and (marker_error or (marker or {}).get('status') != 'initialized'))
    if pending:
        status, title = 'pending', '有一笔结果需要核对'
        message = '已保留原始消费记录，新的刷取暂不开始。'
        action = '到“运行记录”查看原结算与补给记录；不要重复领取。'
    elif is_new:
        status, title = 'new', '欢迎使用 OK-WW'
        message = '这是一个没有运行记录的新安装。完成首次设置后即可开始检查队伍。'
        action = '确认首次使用，建立本安装的独立资源记录。补给额度默认关闭。'
    elif not verified or incomplete:
        status, title = 'history_unknown', '需要恢复资源记录'
        message = '检测到已有使用痕迹，但完整账本或初始化记录尚未确认。'
        action = '保留现有文件并导出诊断；恢复已核对的账本前不启用溶剂。'
    else:
        status, title = 'ready', '已准备好'
        message = '资源记录可读取，补给只按本次设置的额度使用。'
        action = '检查游戏窗口和当前队伍，然后选择任务。'
    return {
        'status': status, 'title': title, 'message': message, 'next_action': action,
        'can_initialize': is_new, 'can_run': status == 'ready',
        'can_use_solvents': verified and not pending and not incomplete,
        'pending_count': len(pending),
        'ledger': {key: ledger.get(key, 0) for key in (*COUNTERS, 'ledger_revision')},
        'default_limits': {'reserve': 0, 'solvents': 0, 'solvent_total': 0},
    }


@contextmanager
def _controller_lease(root, lease):
    if lease is not None:
        if (not isinstance(lease, MacSession) or lease.handle is None or lease.handle.closed
                or lease.path.resolve() != (root / 'logs/macos-controller.lock').resolve()):
            raise RuntimeError('初始化需要当前工作区的有效控制锁。')
        yield lease
        return
    owned = MacSession(root).acquire()
    try:
        yield owned
    finally:
        owned.close()


def initialize_new_install(root, confirmed=False, lease=None):
    """Create a zero ledger only after explicit first-use confirmation.

    The installation marker is written first. If a write fails, its presence
    prevents a later attempt from silently resetting partially created history.
    Pass the caller's acquired MacSession when the GUI already owns the lease.
    """
    if confirmed is not True:
        raise ValueError('请先确认这是本安装的首次使用。')
    root = Path(root).resolve()
    with _controller_lease(root, lease):
        if any(not (root / relative).resolve().is_relative_to(root) for relative in (INSTALL, LEDGER)):
            raise RuntimeError('首次设置目录不能指向安装目录之外。')
        if not inspect_user_state(root)['can_initialize']:
            raise RuntimeError('已有资源记录或运行历史，不能通过首次设置清零；请查看恢复说明。')
        path = root / INSTALL
        path.parent.mkdir(parents=True, exist_ok=True)
        marker = {'schema': 1, 'installation_id': str(uuid.uuid4()),
                  'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                  'status': 'initializing', 'default_refill_allowance': 0}
        with path.open('x', encoding='utf-8') as stream:
            json.dump(marker, stream, ensure_ascii=False, indent=2)
        activity = MaterialActivity(root / LEDGER)
        activity.data.update(history_verified=True,
                             baseline_note='用户确认的全新安装；本账本只统计此后本安装的消费。')
        activity.save(status='initialized')
        marker['status'] = 'initialized'
        _atomic_json(path, marker)
        return inspect_user_state(root)
