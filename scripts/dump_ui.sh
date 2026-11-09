#!/usr/bin/env bash
# Dump the current screen's UI tree + screenshot into data/ — the tool for
# fixing selectors after an app update (the app is Flutter: all visible text
# is in content-desc, text="" everywhere).
set -euo pipefail
# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

OUT_DIR="$PROJECT_ROOT/data"
mkdir -p "$OUT_DIR"
STAMP=$(date +%H%M%S)

adb exec-out uiautomator dump /dev/tty > "$OUT_DIR/ui_$STAMP.xml" 2>/dev/null \
  || { adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml "$OUT_DIR/ui_$STAMP.xml"; }
adb exec-out screencap -p > "$OUT_DIR/screen_$STAMP.png"

echo "Wrote $OUT_DIR/ui_$STAMP.xml and screen_$STAMP.png"
