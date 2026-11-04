"""Start the packaged GUI, preserving one user's state across App upgrades."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys

RESOURCES = Path(__file__).resolve().parent
STATE_TREES = {'logs', 'configs', 'cache', 'data', 'runs', '.venv', '.git'}


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise RuntimeError('已有窗口或控制任务正在运行。请先结束任务并关闭旧窗口，再打开新版。')
    return stream


def sync_sources(payload, workspace):
    """Replace only manifest-listed code; never import, reset or copy user state."""
    manifest = json.loads((payload / 'release-manifest.json').read_text())
    expected = manifest['files']
    for relative, item in expected.items():
        path = Path(relative)
        if (path.is_absolute() or '..' in path.parts or
                any(part in STATE_TREES for part in path.parts)):
            raise ValueError(f'发布清单包含不允许的数据路径：{relative}')
        source = payload / path
        if source.is_symlink() or file_digest(source) != item['sha256']:
            raise ValueError(f'安装包文件校验失败：{relative}')
        target = workspace / path
        if not target.resolve().is_relative_to(workspace.resolve()):
            raise ValueError(f'安装位置包含外部符号链接：{relative}')
    marker = workspace / '.bundled-source.json'
    old = json.loads(marker.read_text()) if marker.exists() else {}
    # Old versions may be retained for recovery, but cannot silently downgrade
    # the stable workspace while a newer installation's state is present.
    if old.get('build_number', 0) > manifest.get('build_number', 3):
        raise RuntimeError('此数据目录已由更新版本使用，请打开更新版 App。')
    for relative in expected:
        source, target = payload / relative, workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or file_digest(target) != expected[relative]['sha256']:
            temporary = target.with_name(target.name + '.installing')
            shutil.copyfile(source, temporary)
            temporary.replace(target)
    # Historical manifest entries are untrusted metadata: only remove obsolete
    # source files in the two known code trees, never an arbitrary stored path.
    for relative in set(old.get('files', [])) - set(expected):
        path = Path(relative)
        if (len(path.parts) > 2 and path.parts[0] in ('ok-script', 'ok-wuthering-waves')
                and path.parts[1] in ('src', 'ok', 'scripts') and '..' not in path.parts):
            target = workspace / path
            if target.resolve().is_relative_to(workspace.resolve()) and target.is_file():
                target.unlink()
    shutil.copyfile(payload / 'release-manifest.json', workspace / 'release-manifest.json')
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'files': list(expected), 'build_number': manifest.get('build_number', 3),
                                     'snapshot_sha256': manifest['snapshot_sha256']}))
    temporary.replace(marker)


def start(workspace, self_test=False):
    root = workspace / 'ok-wuthering-waves'
    # Both locks are taken before replacing code. Existing pending claims and
    # account records stay in this same root, including after App replacement.
    with acquire(root / 'logs/desktop-ui.lock'), acquire(root / 'logs/macos-controller.lock'):
        sync_sources(RESOURCES / 'payload', workspace)
    os.chdir(root)
    sys.path[:0] = [str(root), str(workspace / 'ok-script')]
    os.environ['PYTHONPATH'] = os.pathsep.join(sys.path[:2])
    from scripts.check_desktop_environment import inspect_environment
    errors, _ = inspect_environment(root)
    if errors:
        raise RuntimeError('\n'.join(errors))
    if self_test:
        import subprocess
        report = workspace / 'app-preview.png'
        result = subprocess.run([sys.executable, str(root / 'scripts/desktop_panel.py'),
                                 '--preview', str(report)], check=False)
        if result.returncode:
            raise RuntimeError('独立 GUI 渲染失败')
        # Verify the same interpreter can import the native/OCR components in a
        # child process. No controller, permission query, capture or input starts.
        subprocess.run([sys.executable, '-c', 'import ssl, sqlite3, cv2, onnxruntime, onnxocr, Quartz; '
                        'from ok.platform.macos.helper import MacOSHelper; '
                        'assert MacOSHelper().executable.is_file(); print("bundled imports OK")'], check=True)
        print(json.dumps({'status': 'passed', 'python': sys.executable, 'prefix': sys.prefix,
                          'preview': str(report), 'root': str(root)}), flush=True)
        return 0
    sys.argv = [str(root / 'scripts/desktop_panel.py')]
    runpy.run_path(sys.argv[0], run_name='__main__')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', type=Path)
    args = parser.parse_args()
    workspace = args.self_test or Path.home() / 'Library/Application Support/OK-WW'
    workspace.mkdir(parents=True, exist_ok=True)
    # Self-test writes only to its explicit temporary workspace.
    if args.self_test:
        return start(workspace.resolve(), True)
    log = workspace / 'launcher.log'
    with log.open('a', buffering=1) as output:
        sys.stdout = sys.stderr = output
        try:
            return start(workspace)
        except Exception as error:
            import traceback
            traceback.print_exc()
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, 'OK-WW 启动未完成', f'{error}\n\n启动日志：{log}')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
