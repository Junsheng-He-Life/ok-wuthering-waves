#!/bin/bash
# Sourced by desktop commands. Never fall back to an unrelated system Python.

select_desktop_runtime() {
  local app_root="$1"
  local candidate
  for candidate in "$app_root/../ok-script/.venv313/bin/python" "$app_root/.venv/bin/python"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo '未找到独立运行环境。请按 README.md 创建项目 .venv 并安装依赖。' >&2
  echo '支持：相邻 ok-script/.venv313（优先），或本项目 .venv；不会调用系统 Python。' >&2
  return 1
}

prepare_desktop_runtime() {
  local app_root="$1"
  DESKTOP_PYTHON="$(select_desktop_runtime "$app_root")" || return $?
  export PYTHONPATH="$app_root/../ok-script:$app_root${PYTHONPATH:+:$PYTHONPATH}"
  "$DESKTOP_PYTHON" "$app_root/scripts/check_desktop_environment.py" --root "$app_root"
}

desktop_pause_on_error() {
  if [ -t 0 ]; then
    read -r -p '按回车关闭…' _
  fi
}
