"""Install the beta's pinned runtime without importing game-control code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv


def package_root():
    return Path(__file__).resolve().parents[1]


def run(command, *, cwd, env=None):
    print(' → ' + ' '.join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, env=env, check=True)


def check_host():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('当前内测包仅支持 Apple Silicon Mac。')
    version = platform.mac_ver()[0]
    if not version or int(version.split('.')[0]) < 14:
        raise RuntimeError('当前锁定依赖需要 macOS 14 或更新版本；其他系统请勿安装此内测包。')
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError('安装需要 Python 3.13；请安装后重新运行。')
    if not shutil.which('swiftc'):
        raise RuntimeError('缺少 Xcode Command Line Tools；请先运行 xcode-select --install。')


def verify_bundle(root):
    """Check a release manifest when supplied; development checkouts also work."""
    manifest = root.parent / 'release-manifest.json'
    if not manifest.exists():
        return
    data = json.loads(manifest.read_text())
    for relative, expected in data['files'].items():
        path = root.parent / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.parent.resolve()):
            raise RuntimeError(f'发布包文件缺失或路径无效：{relative}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise RuntimeError(f'发布包文件已变化：{relative}。请重新解压原始内测包。')


def prepare_environment(root):
    target = root / '.venv'
    if target.exists():
        cfg = target / 'pyvenv.cfg'
        if not cfg.is_file() or target.is_symlink():
            raise RuntimeError('已有 .venv 不是有效虚拟环境；安装器不会覆盖它。')
        version = subprocess.check_output([str(target / 'bin/python'), '-c',
            'import sys; print(".".join(map(str,sys.version_info[:2])))'], text=True).strip()
        if version != '3.13':
            raise RuntimeError('已有 .venv 不是 Python 3.13；请保留它并在新的解压目录安装。')
    else:
        print('创建专用运行环境…', flush=True)
        venv.EnvBuilder(with_pip=True).create(target)
    return target / 'bin/python'


def main(argv=None):
    parser = argparse.ArgumentParser(description='安装内测版运行环境；不启动游戏、不修改账号配置。')
    parser.add_argument('--offline-wheels', type=Path, help='使用指定目录中的 wheel 文件，禁止联网')
    parser.add_argument('--verify-only', action='store_true', help='只核对发布文件和安装条件')
    args = parser.parse_args(argv)
    root = package_root()
    try:
        check_host()
        verify_bundle(root)
        if not (root.parent / 'ok-script/ok/__init__.py').is_file():
            raise RuntimeError('配套框架缺失；请保留解压后的两个项目目录。')
        if args.verify_only:
            print('安装条件和发布文件检查通过；未创建运行环境或修改配置。')
            return 0
        python = prepare_environment(root)
        install = [python, '-m', 'pip', 'install', '--disable-pip-version-check',
                   '--no-deps', '-r', root / 'requirements-macos.lock.txt']
        if args.offline_wheels:
            install += ['--no-index', '--find-links', args.offline_wheels.resolve()]
        else:
            print('将从 Python 包索引下载锁定版本依赖；不会上传游戏或账号数据。', flush=True)
        run(install, cwd=root)
        run([python, '-m', 'pip', 'check'], cwd=root)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root.parent / 'ok-script'), str(root)]))
        run([python, root / 'scripts/check_desktop_environment.py', '--root', root], cwd=root, env=env)
        print('安装完成。现在可以双击「启动 OK-WW.command」；首次启动再完成权限与账号设置。')
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'安装未完成：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
