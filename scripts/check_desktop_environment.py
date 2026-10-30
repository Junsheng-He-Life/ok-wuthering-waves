"""Check local desktop prerequisites without importing or starting game control.

Only the standard library is imported. Package specs locate dependencies without
executing them; permissions, GUI startup and native helper execution are outside
this offline check. A successful check is not a live-game compatibility claim.
"""
import argparse
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import sys


DEPENDENCIES = {
    'PySide6': 'PySide6', 'qfluentwidgets': 'PySide6-Fluent-Widgets',
    'numpy': 'numpy', 'cv2': 'opencv-python', 'onnxocr': 'onnxocr-ppocrv5',
    'onnxruntime': 'onnxruntime', 'opencc': 'OpenCC', 'pynput': 'pynput',
    'psutil': 'psutil', 'requests': 'requests', 'Quartz': 'pyobjc-framework-Quartz',
    'pyappify': 'pyappify', 'PIL': 'Pillow', 'shiboken6': 'shiboken6',
    'qframelesswindow': 'PySideSix-Frameless-Window', 'darkdetect': 'darkdetect',
    'shapely': 'shapely', 'pyclipper': 'pyclipper', 'typing_extensions': 'typing-extensions',
}
PROJECT_FILES = (
    'config.py', 'scripts/macos_app.py', 'src/runtime/MacSession.py',
    'profiles/macos-native-screen.json', 'assets/coco_annotations.json',
    'i18n/zh_CN/LC_MESSAGES/ok.mo',
    'requirements-macos.lock.txt',
)
FRAMEWORK_FILES = (
    'ok/__init__.py', 'ok/platform/macos/native_helper.swift',
    'ok/device/capture_methods/macos.py', 'ok/device/interaction_methods/macos.py',
)


def inspect_environment(root):
    """Return errors and resolved modules; do not import application modules."""
    root = Path(root).resolve()
    framework = root.parent / 'ok-script'
    errors, modules = [], {}
    if sys.platform != 'darwin':
        errors.append('此独立桌面入口需要 macOS；Windows 请使用 README 中对应的入口。')
    else:
        if platform.machine() != 'arm64':
            errors.append('当前内测包需要 Apple Silicon Mac（arm64）。')
        version = platform.mac_ver()[0]
        if not version or not version.split('.')[0].isdigit() or int(version.split('.')[0]) < 14:
            errors.append('当前锁定依赖需要 macOS 14 或更新版本；尚未完成其他系统的实机验收。')
    if sys.version_info[:2] != (3, 13):
        errors.append('当前内测包需要 Python 3.13 创建的专用 .venv。')
    if sys.prefix == sys.base_prefix:
        errors.append('当前解释器不是虚拟环境；请使用项目 .venv 或相邻 ok-script/.venv313。')
    for base, paths in ((root, PROJECT_FILES), (framework, FRAMEWORK_FILES)):
        for relative in paths:
            if not (base / relative).is_file():
                errors.append(f'缺少文件：{base / relative}；请恢复完整的两个相邻项目。')
    spec = PathFinder.find_spec('ok', sys.path)
    expected = framework / 'ok/__init__.py'
    if spec is None or not spec.origin or Path(spec.origin).resolve() != expected:
        errors.append(f'ok 模块未指向配套框架：{expected}；请从项目的 .command 入口运行。')
    else:
        modules['ok'] = spec.origin
    missing = []
    for module, package in DEPENDENCIES.items():
        spec = PathFinder.find_spec(module, sys.path)
        if spec is None:
            missing.append(package)
        else:
            modules[module] = spec.origin or '(namespace package)'
    if missing:
        errors.append('缺少依赖：' + '、'.join(missing))
        errors.append('在所选环境安装本版本的锁定依赖；对应命令：'
                      + shlex.join([sys.executable, '-m', 'pip', 'install', '--no-deps', '-r', str(root / 'requirements-macos.lock.txt')]))
        if 'pyobjc-framework-Quartz' in missing:
            errors.append('Quartz 依赖安装命令：' + shlex.join(
                [sys.executable, '-m', 'pip', 'install', 'pyobjc-framework-Quartz']))
    annotations = root / 'assets/coco_annotations.json'
    if annotations.is_file():
        try:
            data = json.loads(annotations.read_text(encoding='utf-8'))
            missing_images = sorted({row['file_name'] for row in data['images']
                                     if not (annotations.parent / row['file_name']).is_file()})
            if missing_images:
                errors.append(f'缺少 {len(missing_images)} 张模板图像，例如 {missing_images[0]}；请恢复 assets 目录。')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f'模板索引无法读取：{exc}；请恢复 assets/coco_annotations.json。')
    helper = os.environ.get('OK_MACOS_HELPER', '')
    if helper:
        if not Path(helper).is_file() or not os.access(helper, os.X_OK):
            errors.append('OK_MACOS_HELPER 未指向可执行文件；请修正该设置。')
    elif not shutil.which('swiftc'):
        errors.append('未找到 Swift 编译器；请按 README 安装 Xcode Command Line Tools。')
    return errors, modules


def main(argv=None):
    parser = argparse.ArgumentParser(description='离线环境诊断：不启动游戏、不采集、不发输入。')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    print(f'离线环境诊断 | Python {sys.version.split()[0]} | {sys.executable}')
    errors, modules = inspect_environment(args.root)
    for name, path in modules.items():
        print(f'  {name}: {path}')
    if errors:
        for error in errors:
            print(f'需要处理：{error}', file=sys.stderr)
        print('环境检查未通过，未启动桌面控制器。', file=sys.stderr)
        return 1
    print('离线文件与模块路径检查通过；未执行依赖导入。权限、输入与实际游戏兼容性需要另行验收。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
