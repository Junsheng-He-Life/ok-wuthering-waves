"""Export bounded, redacted evidence without clearing consumption guards."""
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import zipfile

from src.runtime.DesktopUserState import inspect_user_state, pending_records


def redact_text(value):
    text = str(value)
    text = re.sub(r'(?i)(?:https?://|file://)\S+', '[URL]', text)
    text = re.sub(r'(?:/Users/|/home/)[^\s\n"\']+', '[LOCAL_PATH]', text)
    text = re.sub(r'[A-Za-z]:\\[^\s\n"\']+', '[LOCAL_PATH]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)
    text = re.sub(r'(?i)(特征码|uid|account(?:_id)?|token|secret|api[_-]?key|password)["\s]*[:：=]["\s]*[^\s,}"\n]+', r'\1:[REDACTED]', text)
    return re.sub(r'(?<!\d)\d{8,}(?!\d)', '[ID]', text)


def inspect_recovery(root):
    items=[{'source_file':str(path),'read_error':error,'kind':'consumption_pending'}
           for path,_record,error in pending_records(Path(root))]
    return {'status':'pending' if items else 'clear','items':items,
            'message':'保留原结算，导出诊断，不要删除保护记录或重复领奖。' if items else '没有待核对消费。'}


def export_diagnostics(root, destination, note='', run_path=None):
    root = Path(root).resolve()
    folder = root/'logs/desktop-runs'
    paths = sorted(folder.glob('*.json'), key=lambda p:p.stat().st_mtime)[-5:]
    if run_path is not None:
        chosen = Path(run_path).resolve()
        if not chosen.is_relative_to(folder.resolve()) or chosen.is_symlink():
            raise ValueError('仅导出本安装中的运行记录。')
        paths = [chosen]
    records, logs = [], {}
    allowed = ('status','error','failure_stage','phase','stage','team','budget','stage_seconds',
               'process_exit','desktop_action','diagnostic_code','preflight')
    for index, path in enumerate(paths):
        if path.is_symlink() or path.stat().st_size > 4_000_000:
            continue
        try:
            row = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        records.append({key:row[key] for key in allowed if key in row})
        log = path.with_suffix('.log')
        if log.is_file() and not log.is_symlink():
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size-65536))
                tail = stream.read().decode('utf-8',errors='replace')
            # Result inventory/OCR dumps are unnecessary in a public report.
            logs[f'run-{index+1}-tail.txt'] = '\n'.join(line for line in tail.splitlines()[-160:]
                                                   if not line.startswith('TRIAL_RESULT '))
    versions = {}
    for name in ('PySide6','numpy','opencv-python','onnxruntime','onnxocr-ppocrv5'):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = 'missing'
    release = root.parent/'release-manifest.json'
    version = json.loads(release.read_text()).get('version') if release.is_file() else 'development'
    source = hashlib.sha256()
    for path in sorted((root/'src').rglob('*.py')):
        source.update(str(path.relative_to(root)).encode());source.update(path.read_bytes())
    pending = [{'record':str(path),'read_error':error} for path,_record,error in pending_records(root)]
    state = inspect_user_state(root)
    data = {'schema':2,'created_at':datetime.now().astimezone().isoformat(),
            'version':version,'source_sha256':source.hexdigest(),'platform':platform.platform(),
            'python':platform.python_version(),'dependencies':versions,
            'user_note':note[:8000],'runs':records,'pending':pending,
            'ledger':state.get('ledger'),'contains_screenshots':False,'contains_raw_logs':False,
            'contains_redacted_log_tails':True}
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.json',redact_text(json.dumps(data,ensure_ascii=False,indent=2)))
        for name,text in logs.items(): archive.writestr(name,redact_text(text))
        archive.writestr('提交说明.txt','在GitHub问题反馈中填写复现步骤、预期/实际结果和队伍，手动附上此ZIP。\n'
                          '不含截图、完整日志或账号配置；如需截图，请先遮住UID与账号名。\n'
                          '保留原安装和待核对消费记录，不要删除文件解锁或重复领奖。\n')
    return {'path':str(destination),'runs':len(records)}
