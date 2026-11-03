#!/bin/bash
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
source "$APP_DIR/scripts/desktop_runtime.sh"
status=0
prepare_desktop_runtime "$APP_DIR" || status=$?
if [ "$status" -ne 0 ]; then desktop_pause_on_error; exit "$status"; fi
echo '打开独立GUI；未点击开始前不会操作游戏。出错后在“记录与问题报告”导出诊断包。'
"$DESKTOP_PYTHON" scripts/desktop_panel.py "$@" || {
  status=$?
  echo '窗口未正常退出，请查看终端错误并运行环境诊断。'
  desktop_pause_on_error
  exit "$status"
}
