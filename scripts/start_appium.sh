#!/usr/bin/env bash
# Start the Appium server on the default port 4723 (the daemon does this by itself).
set -euo pipefail
# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

exec appium
