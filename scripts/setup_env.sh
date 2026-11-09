#!/usr/bin/env bash
# One-time environment setup for macOS on Apple Silicon (Homebrew required):
# Java 21, Node, Python 3.13, Android SDK + emulator + AVD, Appium 3 with the
# uiautomator2 driver, and the project venv. Safe to re-run: skips what exists.
# The first run downloads ~5 GB and takes 10–30 min.
set -euo pipefail

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "This project needs macOS on Apple Silicon (M1 or newer)." >&2
  exit 1
fi
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh" >&2; exit 1; }

API_IMAGE="system-images;android-35;google_apis_playstore;arm64-v8a"

echo "==> Homebrew packages: Java 21, Python 3.13, Node, Android command-line tools"
for formula in openjdk@21 python@3.13; do
  brew list --formula "$formula" >/dev/null 2>&1 || brew install "$formula"
done
command -v node >/dev/null || brew install node
brew list --cask android-commandlinetools >/dev/null 2>&1 || brew install --cask android-commandlinetools

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"
[ -n "$JAVA_HOME" ] || { echo "Java 21 not found after install" >&2; exit 1; }

echo "==> Accepting Android SDK licenses"
# `yes` dies with SIGPIPE when sdkmanager exits; don't let pipefail kill us.
(yes || true) | sdkmanager --licenses >/dev/null

echo "==> Android SDK: platform-tools, emulator, android-35 + Play Store arm64 image"
sdkmanager --install "platform-tools" "emulator" "platforms;android-35" "$API_IMAGE"

if ! avdmanager list avd | grep -q "Name: $TSON_AVD\$"; then
  echo "==> Creating AVD '$TSON_AVD' (Pixel 7 profile)"
  echo no | avdmanager create avd -n "$TSON_AVD" -k "$API_IMAGE" -d pixel_7
  CONFIG="$HOME/.android/avd/${TSON_AVD}.avd/config.ini"
  # Play images are resource-hungry
  if grep -q '^hw.ramSize' "$CONFIG"; then
    sed -i '' 's/^hw.ramSize.*/hw.ramSize=4096/' "$CONFIG"
  else
    echo "hw.ramSize=4096" >> "$CONFIG"
  fi
  grep -q '^disk.dataPartition.size' "$CONFIG" || echo "disk.dataPartition.size=8G" >> "$CONFIG"
  # CLI-created AVDs default to hw.keyboard=no, which ignores the host keyboard
  sed -i '' 's/^hw.keyboard=no/hw.keyboard=yes/' "$CONFIG"
else
  echo "==> AVD '$TSON_AVD' already exists"
fi

echo "==> Appium 3 + uiautomator2 driver"
command -v appium >/dev/null || npm install -g appium
appium driver list --installed 2>&1 | grep -q uiautomator2 || appium driver install uiautomator2

echo "==> Python venv + dependencies"
PY313="$(brew --prefix python@3.13)/bin/python3.13"
[ -d "$PROJECT_ROOT/.venv" ] || "$PY313" -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/pip" install -q -r "$PROJECT_ROOT/requirements.txt"

echo "==> Checking uiautomator2 driver requirements"
appium driver doctor uiautomator2 || true

cat <<EOF

Done. Next:
  .venv/bin/python -m checker.doctor     # what is still missing
  ./scripts/start_emulator.sh            # boot the emulator with a window
EOF
