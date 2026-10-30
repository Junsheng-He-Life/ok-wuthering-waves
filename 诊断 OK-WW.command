#!/bin/bash
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
source "$APP_DIR/scripts/desktop_runtime.sh"
if prepare_desktop_runtime "$APP_DIR"; then
  diagnostic_status=0
else
  diagnostic_status=$?
fi
desktop_pause_on_error
exit "$diagnostic_status"
