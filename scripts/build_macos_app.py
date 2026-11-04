"""Build a relocatable arm64 App with CPython, locked wheels and native helper.

The builder performs ad-hoc signing; Apple Developer ID notarization is separate.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def run(*command):
    try:
        return subprocess.check_output([str(x) for x in command], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'{command[0]} failed:\n{error.output}') from error


def copy_runtime(runtime):
    base = Path(sys.base_prefix)
    if sys.version_info[:2] != (3, 13) or not (base / 'Python').is_file():
        raise RuntimeError('Build with the tested python.org framework Python 3.13 virtualenv.')
    runtime.mkdir(parents=True)
    (runtime / 'bin').mkdir()
    # Use the actual interpreter, avoiding bin's framework launcher stub.
    shutil.copy2(base / 'Resources/Python.app/Contents/MacOS/Python', runtime / 'bin/python3.13')
    shutil.copy2(base / 'Python', runtime / 'Python')
    shutil.copytree(base / 'lib', runtime / 'lib', symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', 'site-packages', 'test', 'tests',
                                                  'idlelib', 'tkinter', 'turtledemo', 'config-3.13-darwin',
                                                  '_tkinter*', 'pkgconfig', '*.a'))
    site = runtime / 'lib/python3.13/site-packages'
    site.mkdir()
    distributions = []
    for line in (ROOT / 'requirements-macos.lock.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, version = line.split('==')
        distribution = metadata.distribution(name)
        if distribution.version != version:
            raise ValueError(f'Locked runtime mismatch: {name} {distribution.version} != {version}')
        distributions.append({'name': name, 'version': version})
        for relative in distribution.files or ():
            if '..' in relative.parts or '__pycache__' in relative.parts or str(relative).endswith('.pyc'):
                continue
            # These optional Qt database drivers require external Homebrew
            # databases. OK-WW does not use Qt SQL or ODBC connections.
            if 'sqldrivers' in relative.parts:
                continue
            source, target = Path(distribution.locate_file(relative)), site / relative
            if source.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target, follow_symlinks=True)
    (runtime / 'okww-runtime.json').write_text(json.dumps(distributions, indent=2))
    shutil.copy2(base / 'lib/python3.13/LICENSE.txt', runtime / 'Python-LICENSE.txt')
    return base


def macho_files(root):
    for path in root.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                if stream.read(4) in MACHO:
                    yield path


def apply_wheels(runtime, wheels):
    """Overlay explicitly supplied, same-version rebuilt wheels for this App."""
    locked = dict(line.split('==') for line in (ROOT / 'requirements-macos.lock.txt').read_text().splitlines()
                  if line and not line.startswith('#'))
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    locked = {normalize(k): v for k, v in locked.items()}
    records = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError(f'Wheel metadata is ambiguous: {wheel}')
            info = BytesParser().parsebytes(archive.read(names[0]))
            if locked.get(normalize(info['Name'])) != info['Version']:
                raise ValueError(f'Wheel does not match locked dependency: {wheel}')
            site = runtime / 'lib/python3.13/site-packages'
            for item in archive.infolist():
                path = Path(item.filename)
                if path.is_absolute() or '..' in path.parts or any(part.endswith('.data') for part in path.parts):
                    raise ValueError(f'Unsupported wheel path: {item.filename}')
                if not item.is_dir():
                    target = site / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
                    mode = item.external_attr >> 16 & 0o777
                    if mode:
                        target.chmod(mode)
        records.append({'file': wheel.name, 'name': info['Name'], 'version': info['Version'],
                        'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()})
    (runtime / 'wheel-overrides.json').write_text(json.dumps(records, indent=2))


def relocate(path, original, runtime):
    architectures = run('lipo', '-archs', path).strip().split()
    if 'arm64' not in architectures:
        raise ValueError(f'Runtime binary has no arm64 slice: {path}')
    if len(architectures) > 1:
        thin = path.with_name(path.name + '.arm64')
        run('lipo', path, '-thin', 'arm64', '-output', thin)
        thin.replace(path)
    load_commands = run('otool', '-l', path)
    for version in re.findall(r'\bminos\s+(\d+(?:\.\d+)+)', load_commands):
        minimum = tuple(map(int, version.split('.')))
        minimum += (0,) * (3 - len(minimum))
        if minimum > (14, 0, 0):
            raise ValueError(f'Binary requires macOS {version}, above 14.0: {path}')
    ids = [line.strip() for line in run('otool', '-D', path).splitlines()[1:]
           if not line.endswith(':')]
    dependencies = [line.strip().split(' (compatibility')[0] for line in run('otool', '-L', path).splitlines()
                    if line.startswith('\t')]
    changes = []
    for dependency in dependencies:
        if dependency in ids:
            continue
        if dependency.startswith(str(original) + '/'):
            target = runtime / Path(dependency).relative_to(original)
            if not target.exists():
                raise ValueError(f'Missing relocated dependency: {dependency} in {path}')
            changes.extend(['-change', dependency, '@loader_path/' + os.path.relpath(target, path.parent)])
        elif dependency.startswith('/') and not dependency.startswith(('/usr/lib/', '/System/Library/')):
            raise ValueError(f'External binary dependency in {path}: {dependency}')
    if ids and ids[0].startswith('/'):
        changes.extend(['-id', '@loader_path/' + path.name])
    if changes:
        run('install_name_tool', *changes, path)


def build(source, output, version, wheels=()):
    from scripts.bootstrap_macos import verify_bundle
    verify_bundle(source / 'ok-wuthering-waves')
    if output.exists():
        raise FileExistsError(output)
    contents = output / 'Contents'
    resources, macos = contents / 'Resources', contents / 'MacOS'
    macos.mkdir(parents=True)
    resources.mkdir()
    shutil.copytree(source, resources / 'payload')
    shutil.copy2(ROOT / 'scripts/bundled_entry.py', resources / 'bundled_entry.py')
    runtime = resources / 'runtime'
    print('Copying locked runtime', flush=True)
    base = copy_runtime(runtime)
    apply_wheels(runtime, wheels)
    from PIL import Image
    with Image.open(ROOT / 'icons/icon.png') as icon:
        icon.convert('RGBA').save(resources / 'AppIcon.icns', format='ICNS')
    launcher = macos / 'OK-WW'
    run('clang', '-arch', 'arm64', '-mmacosx-version-min=14.0', '-framework', 'Cocoa',
        ROOT / 'scripts/bundled_launcher.m', '-o', launcher)
    helper = resources / 'ok-macos-helper'
    run('swiftc', '-O', '-parse-as-library', '-target', 'arm64-apple-macos14.0',
        '-module-cache-path', output.parent / 'swift-module-cache',
        source / 'ok-script/ok/platform/macos/native_helper.swift', '-o', helper,
        '-framework', 'AppKit', '-framework', 'ApplicationServices', '-framework', 'CoreMedia',
        '-framework', 'CoreVideo', '-framework', 'ScreenCaptureKit')
    plist = {'CFBundleIdentifier': 'life.junsheng.okww', 'CFBundleName': 'OK-WW 鸣潮助手',
             'CFBundleDisplayName': 'OK-WW 鸣潮助手', 'CFBundleExecutable': 'OK-WW',
             'CFBundleIconFile': 'AppIcon.icns', 'CFBundlePackageType': 'APPL',
             'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '3',
             'LSMinimumSystemVersion': '14.0', 'LSArchitecturePriority': ['arm64'],
             'NSHighResolutionCapable': True,
             'NSHumanReadableCopyright': 'OK-WW macOS fork; upstream licenses bundled.',
             'NSScreenCaptureUsageDescription': '读取鸣潮游戏画面以识别任务状态。',
             'NSAccessibilityUsageDescription': '通过既有控制器向鸣潮游戏发送按键和点击。'}
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(plist, stream)
    seal_bundle(source, output, version, base)


def seal_bundle(source, output, version, base):
    """Relocate and seal a fully copied runtime and compiled launcher/helper."""
    contents = output / 'Contents'
    resources = contents / 'Resources'
    runtime = resources / 'runtime'
    binaries = list(macho_files(contents))
    print(f'Relocating and signing {len(binaries)} binaries', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: relocate(p, base, runtime), binaries))
    # Finish all binary edits before sealing anything. Signing a bundle's main
    # executable can seal its enclosing bundle, so sign those only in the
    # ordered nested-bundle pass below (and the final top-level App pass).
    ordinary = [p for p in binaries if not (p.parent.name == 'MacOS' and p.parent.parent.name == 'Contents')]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: run('codesign', '--force', '--sign', '-', p), ordinary))
    nested = sorted((p for p in contents.rglob('*') if p.is_dir() and p.suffix in ('.framework', '.app', '.bundle')),
                    key=lambda p: len(p.parts), reverse=True)
    for path in nested:
        run('codesign', '--force', '--sign', '-', path)
    (resources / 'build-info.json').write_text(json.dumps({'version': version, 'architecture': 'arm64',
        'signing': 'ad-hoc; not notarized', 'source_snapshot_sha256': json.loads(
            (source / 'release-manifest.json').read_text())['snapshot_sha256'],
        'python': sys.version, 'native_binaries': len(binaries)}, indent=2))
    run('codesign', '--force', '--sign', '-', output)
    run('codesign', '--verify', '--deep', '--strict', output)
    print(output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', default='0.1.0-beta.3')
    parser.add_argument('--wheel', action='append', type=Path, default=[],
                        help='Same-version rebuilt wheel, e.g. OpenCC with deployment target 14.0')
    args = parser.parse_args()
    build(args.source.resolve(), args.output.resolve(), args.version, args.wheel)
