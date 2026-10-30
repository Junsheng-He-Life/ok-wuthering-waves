"""Create an auditable two-repository beta from current files, not only Git HEAD."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    from scripts.beta_assets import export_recognition_assets, sha256
except ModuleNotFoundError:
    from beta_assets import export_recognition_assets, sha256


APP_FILES = (
    'config.py', 'version.py', 'requirements-macos.lock.txt', 'README.md', 'README_en.md', 'UPSTREAM.md',
    '启动 OK-WW.command', '诊断 OK-WW.command', '安装 OK-WW.command',
    'profiles/macos-native-screen.json',
    'scripts/macos_app.py', 'scripts/macos_probe.py',
    'scripts/check_desktop_environment.py', 'scripts/desktop_runtime.sh',
    'scripts/desktop_panel.py', 'scripts/desktop_diagnose.py',
    'scripts/ultrawide_trial.py', 'scripts/bootstrap_macos.py',
    'assets/echo_model/echo.onnx', 'assets/images/leviathan-reward-orb-1920.png',
    'assets/images/map-beacon-huanglong-1920.png', 'assets/images/map-nexus-huanglong-1920.png',
    'docs/beta-user-guide.md', 'docs/beta-release-2026-10-30.md', 'docs/development.md',
    'docs/images/desktop-main.png', 'docs/images/desktop-small.png',
)
APP_TREES = {'src': {'.py'}, 'icons': {'.png', '.ico', '.svg'}, 'i18n': {'.mo'}}
FRAMEWORK_SUFFIXES = {'.py', '.swift', '.qm', '.qss', '.qrc', '.svg', '.png', '.ico'}
BLOCKED_PARTS = {'.git', '.venv', '.venv313', '__pycache__', 'configs', 'logs', 'data', 'runs'}


def git_metadata(root):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    return {'base_commit': git('rev-parse', 'HEAD'),
            'working_tree_dirty': bool(git('status', '--porcelain')),
            'source': 'current working files; manifest hashes include uncommitted changes'}


def copy_file(source_root, relative, target_root, source_hashes):
    source = source_root / relative
    if any(part in BLOCKED_PARTS for part in relative.parts) or source.is_symlink():
        raise ValueError(f'Blocked release path: {relative}')
    if not source.resolve().is_relative_to(source_root.resolve()):
        raise ValueError(f'Release path leaves repository: {relative}')
    destination = target_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    destination.write_bytes(data)
    shutil.copystat(source, destination)
    source_hashes[f'{target_root.name}/{relative.as_posix()}'] = hashlib.sha256(data).hexdigest()


def export_sources(app, framework, stage):
    source_hashes = {}
    app_target, framework_target = stage / 'ok-wuthering-waves', stage / 'ok-script'
    for relative in APP_FILES:
        path = Path(relative)
        if not (app / path).is_file():
            if relative == 'version.py':
                continue
            raise FileNotFoundError(app / path)
        copy_file(app, path, app_target, source_hashes)
    for tree, suffixes in APP_TREES.items():
        for source in sorted((app / tree).rglob('*')):
            if source.is_file() and source.suffix in suffixes and '__pycache__' not in source.parts:
                copy_file(app, source.relative_to(app), app_target, source_hashes)
    for root, target in ((app, app_target), (framework, framework_target)):
        for source in sorted(root.glob('LICENSE*')):
            if source.is_file():
                copy_file(root, source.relative_to(root), target, source_hashes)
    for name in ('setup.py', 'VERSION', 'MANIFEST.in', 'README.md'):
        copy_file(framework, Path(name), framework_target, source_hashes)
    for source in sorted((framework / 'ok').rglob('*')):
        if source.is_file() and source.suffix in FRAMEWORK_SUFFIXES and '__pycache__' not in source.parts:
            copy_file(framework, source.relative_to(framework), framework_target, source_hashes)
    # Whole-image consumers use these small icon crops; full captures are omitted.
    from PIL import Image
    for name in ('leviathan-reward-orb-1920.png', 'map-beacon-huanglong-1920.png', 'map-nexus-huanglong-1920.png'):
        with Image.open(app / 'assets/images' / name) as crop:
            if max(crop.size) > 256:
                raise ValueError(f'{name} is no longer a small recognition crop; review required')
    evidence = export_recognition_assets(app / 'assets', app_target / 'assets')
    source_hashes['ok-wuthering-waves/assets/coco_annotations.json'] = sha256(app / 'assets/coco_annotations.json')
    source_hashes.update({'ok-wuthering-waves/' + row['path']: row['source_sha256'] for row in evidence})
    return source_hashes, evidence


def write_entrypoints(stage, version):
    readme = f'''OK-WW macOS 内测版 {version}

本项目基于 ok-oldking/ok-wuthering-waves（OK-WW）二次开发，是非官方 macOS 派生版本。
上游：https://github.com/ok-oldking/ok-wuthering-waves
配套框架基于 https://github.com/ok-oldking/ok-script；原始 LICENSE.txt 随两个项目保留。
项目关系与改动范围见 ok-wuthering-waves/UPSTREAM.md；安装教程见 ok-wuthering-waves/docs/beta-user-guide.md。

支持范围：Apple Silicon Mac、macOS 14或更新版本、简体中文游戏界面、游戏保持前台。
当前验证环境为 macOS 26.5.2 / Python 3.13；其他系统版本需内测验证。

1. 安装 Python 3.13 与 Xcode Command Line Tools。
2. 双击「安装与检查.command」，下载本版本锁定的依赖并做离线诊断。
3. 双击「启动.command」，按界面完成权限、账号和任务设置。
4. 先检查队伍，再做一场限额测试。暂停/停止使用界面控件或配置的快捷键。

两个项目目录必须保留相邻关系。不要从其他人的目录复制 configs、logs 或 .venv。
升级请解压到新目录并保留旧版。目前不提供自动账号迁移；有旧账本或待核对消费时先请维护者协助，不要删文件解锁。
这是内测源码包，不是经过签名、公证的 .app，也不代表任意队伍/关卡均已验收。
release-manifest.json 记录配套源码与文件哈希，不包含个人账号配置。
'''
    (stage / '先读我.txt').write_text(readme)
    for output, target in (('安装与检查.command', '安装 OK-WW.command'), ('启动.command', '启动 OK-WW.command'), ('环境诊断.command', '诊断 OK-WW.command')):
        path = stage / output
        path.write_text('#!/bin/bash\nset -e\nBUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
                        f'exec bash "$BUNDLE_DIR/ok-wuthering-waves/{target}" "$@"\n')
        path.chmod(0o755)


def build(app, framework, destination, version, archive=True):
    app, framework, destination = Path(app).resolve(), Path(framework).resolve(), Path(destination).resolve()
    if destination.exists() or destination.with_suffix('.zip').exists():
        raise FileExistsError('输出已存在；请选择新版本目录，不覆盖现有发布包。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.okww-beta-', dir=destination.parent) as temporary:
        stage = Path(temporary) / destination.name
        stage.mkdir()
        sources, templates = export_sources(app, framework, stage)
        for relative, expected in sources.items():
            repository, path = relative.split('/', 1)
            source_root = app if repository == 'ok-wuthering-waves' else framework
            if sha256(source_root / path) != expected:
                raise RuntimeError(f'源码在导出期间变化，请待编辑结束后重试：{relative}')
        write_entrypoints(stage, version)
        files = {p.relative_to(stage).as_posix(): {'sha256': sha256(p), 'bytes': p.stat().st_size}
                 for p in sorted(stage.rglob('*')) if p.is_file()}
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        manifest = {'schema': 1, 'version': version,
                    'built_at_utc': datetime.now(timezone.utc).isoformat(),
                    'target': 'macOS 14+ arm64, CPython 3.13', 'build_host_macos': platform.mac_ver()[0],
                    'repositories': {'ok-wuthering-waves': git_metadata(app), 'ok-script': git_metadata(framework)},
                    'snapshot_sha256': digest, 'files': files, 'source_file_sha256': sources,
                    'template_export': templates,
                    'exclusions': ['personal configs/logs', 'virtual environments', 'Git history',
                                   'test screenshots', 'unannotated capture pixels', 'PNG private metadata'],
                    'validation_scope': 'source/file/ROI checks; no claim of another-machine live-game acceptance'}
        (stage / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        stage.rename(destination)
    if archive:
        with zipfile.ZipFile(destination.with_suffix('.zip'), 'w', zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(destination.rglob('*')):
                if path.is_file():
                    zipped.write(path, path.relative_to(destination.parent))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='白名单导出两个配套源码仓库，不复制个人配置。')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--no-archive', action='store_true')
    args = parser.parse_args(argv)
    app = Path(__file__).resolve().parents[1]
    manifest = build(app, app.parent / 'ok-script', args.output, args.version, not args.no_archive)
    print(json.dumps({'output': str(args.output.resolve()), 'files': len(manifest['files']),
                      'snapshot_sha256': manifest['snapshot_sha256'],
                      'template_images_verified': len(manifest['template_export'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
