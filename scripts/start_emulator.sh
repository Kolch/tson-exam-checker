#!/usr/bin/env bash
# Boot the AVD: with a window by default (setup, manual login), or
# --headless for unattended runs (the daemon boots it headless by itself).
set -euo pipefail
# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

if [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
  echo "An emulator is already running: $(adb devices | sed -n 2p)"
  echo "If it's the headless one and you need a window: adb emu kill && $0"
  exit 0
fi

# -dns-server: bypass the host resolver — VPN split-DNS can break sign-in.
FLAGS="-dns-server 8.8.8.8,1.1.1.1"
if [[ "${1:-}" == "--headless" ]]; then
  FLAGS="$FLAGS -no-window -gpu swiftshader_indirect -no-boot-anim -no-audio"
fi

# shellcheck disable=SC2086  # FLAGS is a word list on purpose (bash 3.2: no empty arrays under set -u)
nohup emulator -avd "$TSON_AVD" $FLAGS >/dev/null 2>&1 &

echo "Waiting for boot to complete (first boot can take a few minutes)…"
# shellcheck disable=SC2016  # evaluated by the emulator's shell, not ours
adb wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 1; done'
echo "Emulator ready: $(adb devices | sed -n 2p)"
