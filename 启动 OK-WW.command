#!/bin/bash
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
source "$APP_DIR/scripts/desktop_runtime.sh"
if prepare_desktop_runtime "$APP_DIR"; then
  :
else
  runtime_status=$?
  desktop_pause_on_error
  exit "$runtime_status"
fi
echo '正在打开 OK-WW 鸣潮助手。首次使用请完成面板中的设置。'
echo '面板不会自动开始游戏任务。使用说明：docs/beta-user-guide.md。'
"$DESKTOP_PYTHON" scripts/macos_app.py || {
  app_status=$?
  echo '程序未正常退出，请查看上方错误与 logs/ok-ww.log。'
  desktop_pause_on_error
  exit "$app_status"
}
