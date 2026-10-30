#!/bin/bash
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
INSTALL_PYTHON="$(command -v python3.13 || true)"
if [ -z "$INSTALL_PYTHON" ]; then
  for candidate in /opt/homebrew/bin/python3.13 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 /usr/local/bin/python3.13; do
    if [ -x "$candidate" ]; then INSTALL_PYTHON="$candidate"; break; fi
  done
fi
if [ -z "$INSTALL_PYTHON" ]; then
  echo '请先安装 Python 3.13，并安装 Xcode Command Line Tools（xcode-select --install）。'
  echo '准备好后，再双击本安装入口。'
  if [ -t 0 ]; then read -r -p '按回车关闭…' _; fi
  exit 1
fi
status=0
"$INSTALL_PYTHON" scripts/bootstrap_macos.py "$@" || status=$?
if [ -t 0 ]; then read -r -p '按回车关闭…' _; fi
exit "$status"
