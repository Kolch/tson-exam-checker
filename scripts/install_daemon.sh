#!/usr/bin/env bash
# Install (or reinstall) the launchd agents that run the checker unattended:
#   kz.tson.checker.gate     — every 2 min; runs a check when one is due
#                              (random CHECK_MIN_MIN..CHECK_MAX_MIN schedule)
#   kz.tson.checker.midnight — 23:59 (starts the flow at 23:59:50) and 00:05
#   kz.tson.ctlbot           — always-on Telegram control bot
# Usage: ./scripts/install_daemon.sh          install/refresh + first check now
#        ./scripts/install_daemon.sh remove   uninstall all three
set -euo pipefail
# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"
PROJECT="$PROJECT_ROOT"
AGENTS="$HOME/Library/LaunchAgents"
UID_N=$(id -u)
LABELS="kz.tson.checker.gate kz.tson.checker.midnight kz.tson.ctlbot"

remove() {
  for label in $LABELS; do
    launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
  echo "agents removed"
}

if [[ "${1:-}" == "remove" ]]; then remove; exit 0; fi

[ -x "$PROJECT/.venv/bin/python" ] || { echo "No .venv — run ./scripts/setup_env.sh first" >&2; exit 1; }
[ -f "$PROJECT/.env" ] || { echo "No .env — cp .env.example .env and fill it in" >&2; exit 1; }
if [ "$(_env_get SMS_SOURCE)" = "manual" ]; then
  echo "SMS_SOURCE=manual can't run unattended — set chatdb or webhook (docs/sms.md)" >&2
  exit 1
fi

mkdir -p "$AGENTS" "$PROJECT/data"

make_plist() { # $1 label, $2 mode, $3 schedule-xml
  cat > "$AGENTS/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-dims</string>
    <string>$PROJECT/.venv/bin/python</string>
    <string>-u</string>
    <string>-m</string>
    <string>checker.cycle</string>
    <string>$2</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StandardOutPath</key><string>$PROJECT/data/cycle.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/cycle.log</string>
$3
</dict>
</plist>
EOF
}

make_plist kz.tson.checker.gate gate "  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>"

make_plist kz.tson.checker.midnight calendar "  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>59</integer></dict>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>5</integer></dict>
  </array>"

# control bot: always-on (KeepAlive), no caffeinate wrapper
cat > "$AGENTS/kz.tson.ctlbot.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>kz.tson.ctlbot</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT/.venv/bin/python</string>
    <string>-u</string>
    <string>-m</string>
    <string>checker.ctlbot</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StandardOutPath</key><string>$PROJECT/data/ctlbot.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/ctlbot.log</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
EOF

for label in $LABELS; do
  launchctl bootout "gui/$UID_N/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_N" "$AGENTS/$label.plist"
done

MIN="$(_env_get CHECK_MIN_MIN)"; MAX="$(_env_get CHECK_MAX_MIN)"
echo "installed. first check starts now, then every ${MIN:-10}–${MAX:-20} min; midnight run at 23:59:50 + 00:05."
echo "telegram: /status /stop /start /check"
echo "logs:     tail -f $PROJECT/data/cycle.log"
echo "remove:   ./scripts/install_daemon.sh remove"
