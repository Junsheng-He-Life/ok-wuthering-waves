"""Bounded, read-only recovery summaries and text-only diagnostic exports."""
from datetime import datetime
import json
from pathlib import Path
import platform
import re
import zipfile

from src.runtime.DesktopUserState import inspect_user_state, pending_records, read_json_record
from src.runtime.DesktopClaimReconciliation import reconcile_echo_claim


LABELS = {'logs/echo-claim-pending.json': ('echo_claim', '声骸领奖待核对'),
          'logs/refill-use-pending.json': ('refill', '补充波片待核对'),
          'logs/solvent-use-pending.json': ('solvent', '溶剂使用待核对')}
REPORTS = ('logs/echo-latest.json', 'logs/material-latest.json',
           'configs/macos-desktop/echo-progress.json',
           'configs/macos-desktop/team-material-needs-progress.json')
PUBLIC_BUDGET = ('claimed', 'spent', 'reserve_used', 'solvents_used', 'claim_pending',
                 'claim_cost', 'claim_multiplier', 'max_runs', 'max_stamina')


def redact_text(value):
    """Remove common account/path identifiers from selected diagnostic text."""
    text = str(value)[:4000]
    text = re.sub(r'(?i)(?:https?://|file://)\S+', '[链接已隐藏]', text)
    text = re.sub(r'(?<!\w)(?:/[A-Za-z0-9_.~ -]+){2,}(?:\.[A-Za-z0-9]+)?', '[路径已隐藏]', text)
    text = re.sub(r'\b[A-Za-z]:\\[^\s\n]+', '[路径已隐藏]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已隐藏]', text)
    text = re.sub(r'(?i)(特征码|uid|account(?:_id)?|token|secret|api[_-]?key|password)\s*[:：=]\s*\S+',
                  r'\1：[已隐藏]', text)
    return re.sub(r'(?<!\d)\d{8,}(?!\d)', '[标识已隐藏]', text)


def _number(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else None


def _safe_evidence(root, record):
    evidence = []

    def visit(value, depth=0):
        if depth > 6 or len(evidence) >= 16:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('image', 'evidence') and isinstance(item, str):
                    path = root / item
                    if (not Path(item).is_absolute() and path.is_file() and not path.is_symlink()
                            and path.resolve().is_relative_to(root / 'logs')):
                        relative = path.relative_to(root).as_posix()
                        if relative not in evidence:
                            evidence.append(relative)
                elif isinstance(item, (list, dict)):
                    visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:50]:
                visit(item, depth + 1)

    visit(record)
    return evidence


def _report_summary(root, relative):
    record, error = read_json_record(root / relative)
    if record is None:
        return None
    budget = record.get('budget', {})
    budget = budget if isinstance(budget, dict) else {}
    times = record.get('stage_seconds', {})
    times = times if isinstance(times, dict) else {}
    return {'source_file': relative, 'status': redact_text(record.get('status', '未知')),
            'stage': redact_text(record.get('stage') or record.get('current_stage') or ''),
            'failure_stage': redact_text(record.get('failure_stage', '')),
            'message': redact_text(record.get('error', '')),
            'budget': {key: budget[key] for key in PUBLIC_BUDGET
                       if type(budget.get(key)) in (int, bool)},
            'stage_seconds': {redact_text(key): round(value, 2) for key, value in times.items()
                              if type(value) in (int, float) and 0 <= value < 10_000_000},
            'evidence': _safe_evidence(root, record)}


def inspect_recovery(root):
    """Explain saved pending guards without clicking or clearing any of them."""
    root = Path(root).resolve()
    reports = [row for relative in REPORTS if (row := _report_summary(root, relative))]
    items = []
    for relative, record, error in pending_records(root):
        kind, title = LABELS.get(relative, ('material_claim', '材料任务记录待核对'))
        context = record.get('claim_observation', {})
        context = context if isinstance(context, dict) else {}
        budget = record.get('budget', {})
        budget = budget if isinstance(budget, dict) else {}
        before = _number(context.get('stamina_before', record.get('before')))
        after = _number(context.get('stamina_after', record.get('after')))
        expected = _number(context.get('expected_cost'))
        if expected is None:
            cost, multiplier = _number(budget.get('claim_cost')), _number(budget.get('claim_multiplier'))
            expected = cost * multiplier if cost is not None and multiplier is not None else None
        evidence = _safe_evidence(root, record)
        if kind == 'echo_claim':
            for report in reports:
                if report['source_file'] in ('logs/echo-latest.json', 'configs/macos-desktop/echo-progress.json'):
                    evidence.extend(item for item in report['evidence'] if item not in evidence)
        items.append({'kind': kind, 'title': title, 'stage': redact_text(record.get('stage', '')),
                      'before': before, 'after': after, 'expected_cost': expected,
                      'source_file': relative, 'evidence': evidence[:16], 'read_error': error,
                      'next_action': ('记录无法读取，请保留文件并导出诊断。' if error else
                                      '保留游戏中的原结算页面，先读取当前结果；不要再次点击领取或补给。')})
    return {'status': 'pending' if items else 'clear',
            'title': '需要核对上次结果' if items else '没有待核对消费',
            'message': ('已暂停新一轮消费，原记录会保留到核对完成。' if items else
                        '可查看最近任务结果；不会把历史截图当作当前游戏状态。'),
            'items': items, 'latest_runs': reports, 'can_export': True}


def export_diagnostics(root, destination):
    """Export selected, sanitized summaries only; never copy images or raw logs."""
    root, destination = Path(root).resolve(), Path(destination)
    state, recovery = inspect_user_state(root), inspect_recovery(root)
    # Paths remain useful in the local UI; omit arbitrary filenames from exports.
    for item in recovery['items']:
        item['evidence_count'] = len(item.pop('evidence'))
    for item in recovery['latest_runs']:
        item['evidence_count'] = len(item.pop('evidence'))
    manifest = {'schema': 1, 'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                'platform': platform.system(), 'architecture': platform.machine(),
                'python': platform.python_version(),
                'contains_screenshots': False, 'contains_raw_logs': False,
                'scope': 'Selected status and resource counters; no account files or raw screenshots.'}
    release, _error = read_json_record(root.parent / 'release-manifest.json')
    if release:
        manifest['version'] = redact_text(release.get('version', ''))
        manifest['snapshot_sha256'] = redact_text(release.get('snapshot_sha256', ''))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, data in (('manifest.json', manifest), ('user-state.json', state),
                               ('recovery.json', recovery)):
            archive.writestr(filename, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        archive.writestr('说明.txt', '本诊断包只含筛选后的状态与资源计数，不含原始日志、截图、账号配置或按键配置。\n'
                          '待核对记录仍保留在原安装中；导出不会解除消费保护。\n')
    return {'status': 'exported', 'path': str(destination.resolve()),
            'files': ['manifest.json', 'user-state.json', 'recovery.json', '说明.txt'],
            'message': '诊断包已导出，不含原始截图或账号配置。'}
