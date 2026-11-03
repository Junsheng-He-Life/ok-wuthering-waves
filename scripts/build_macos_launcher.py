"""Build a Finder launcher for this checkout and its existing desktop runtime."""
import argparse
from pathlib import Path
import plistlib
import shlex


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = 'OK-WW 鸣潮助手'
BUNDLE_ID = 'life.junsheng.okww.launcher'


def build(output):
    """Write a local launcher; game data and resource ledgers stay in ROOT."""
    output = output.expanduser().absolute()
    contents = output / 'Contents'
    if output.exists():
        info_path = contents / 'Info.plist'
        if not info_path.is_file():
            raise ValueError(f'拒绝覆盖未知目录：{output}')
        with info_path.open('rb') as stream:
            if plistlib.load(stream).get('CFBundleIdentifier') != BUNDLE_ID:
                raise ValueError(f'拒绝覆盖其他应用：{output}')
    macos = contents / 'MacOS'
    resources = contents / 'Resources'
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    # Reuse the existing icon instead of introducing a separate visual identity.
    from PIL import Image
    with Image.open(ROOT / 'icons/icon.png') as image:
        image.convert('RGBA').save(resources / 'AppIcon.icns', format='ICNS')
    info = {
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleExecutable': 'okww-launcher',
        'CFBundleIconFile': 'AppIcon.icns',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True,
        'LSUIElement': True,
    }
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    launcher = macos / 'okww-launcher'
    launcher.write_text('''#!/bin/bash
set -u
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
project_root=PROJECT_ROOT
log_file="${TMPDIR:-/tmp}/okww-launcher-error.log"
# Terminal is the existing permission host for capture/input and Documents access.
# LaunchServices hands it the command without this new app reading project files.
/usr/bin/open -a Terminal "$project_root/启动 OK-WW.command" >"$log_file" 2>&1
launch_status=$?
if [ "$launch_status" -ne 0 ]; then
  /usr/bin/osascript - "$log_file" <<'APPLESCRIPT'
on run argv
  display alert "OK-WW 启动未完成" message ("请查看启动日志：" & item 1 of argv & "。若移动了项目目录，请重新安装应用启动器。") as warning buttons {"好"} default button "好"
end run
APPLESCRIPT
fi
exit "$launch_status"
'''.replace('PROJECT_ROOT', shlex.quote(str(ROOT))), encoding='utf-8')
    launcher.chmod(0o755)
    (resources / 'README.txt').write_text(
        f'本应用通过终端打开现有 pipeline 面板，不自动开始任务。\n'
        f'项目目录：{ROOT}\n'
        '移动项目目录后，请重新生成并安装启动器。\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'build' / f'{APP_NAME}.app')
    args = parser.parse_args()
    print(build(args.output))


if __name__ == '__main__':
    main()
