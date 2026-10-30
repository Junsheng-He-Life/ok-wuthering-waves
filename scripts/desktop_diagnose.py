"""Desktop-readable diagnostics, with explicit opt-in for native permissions."""
import argparse
import json
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--permissions', action='store_true')
    args = parser.parse_args()
    # Pause is inapplicable to a short diagnostic; never accept default SIGUSR termination.
    signal.signal(signal.SIGUSR1, lambda *_: None)
    signal.signal(signal.SIGUSR2, lambda *_: None)
    try:
        from scripts.check_desktop_environment import inspect_environment
        errors, _modules = inspect_environment(ROOT)
        message = '运行环境检查通过。'
        permissions = None
        if args.permissions and not errors:
            from src.runtime.MacSession import MacSession
            from ok.platform.macos.helper import MacOSHelper
            lease = MacSession(ROOT).acquire()
            try:
                permissions = MacOSHelper().permissions(prompt=True)
            finally:
                lease.close()
            message += '\n系统权限：' + '；'.join(f'{key}：{"已允许" if value else "未允许"}' for key, value in permissions.items())
        elif not args.permissions and not errors:
            message += '\n尚未读取系统权限或连接游戏。'
        result = {'status': 'diagnosed' if not errors else 'stopped',
                  'message': '\n'.join(errors) if errors else message, 'permissions': permissions}
    except Exception as error:
        result = {'status': 'stopped', 'error': str(error)}
    print('TRIAL_RESULT', json.dumps(result, ensure_ascii=False), flush=True)
    return int(result['status'] == 'stopped')


if __name__ == '__main__':
    raise SystemExit(main())
