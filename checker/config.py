"""Configuration loaded from environment / .env (see .env.example)."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv() -> None:
    """Minimal .env reader: KEY=value, '#' comments (whole-line or after
    whitespace), optional surrounding quotes. Real env vars win."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = re.sub(r"\s+#.*$", "", value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, "").strip() or default


def _date(key: str) -> date | None:
    value = _get(key)
    return date.fromisoformat(value) if value else None


# --- ЦОН flow ---
APPLICATION_NUMBER = _get("TSON_APPLICATION_NUMBER")
APP_PIN = _get("TSON_APP_PIN")
# Optional re-login credentials (auto-login on session expiry; see flow.login)
IIN = _get("TSON_IIN")
PHONE = _get("TSON_PHONE")
APP_PACKAGE = _get("TSON_APP_PACKAGE", "kz.gov4c.citizen")

# --- Android SDK / emulator / Appium ---
ANDROID_HOME = _get("ANDROID_HOME", "/opt/homebrew/share/android-commandlinetools")
ADB = _get("ADB", f"{ANDROID_HOME}/platform-tools/adb")
EMULATOR_BIN = f"{ANDROID_HOME}/emulator/emulator"
AVD = _get("TSON_AVD", "tson")
APPIUM_SERVER = _get("APPIUM_SERVER", "http://127.0.0.1:4723")

# --- schedule ---
# The app CACHES the date sheet within a session, so every real check is a
# fresh flow (kill app -> navigate -> SMS -> read) and costs one SMS code.
# Random interval between checks, plus a precise midnight check that starts
# MIDNIGHT_LEAD_SEC before 00:00 and a follow-up at 00:05 (launchd calendar).
CHECK_MIN_MIN = float(_get("CHECK_MIN_MIN", "10"))
CHECK_MAX_MIN = float(_get("CHECK_MAX_MIN", "20"))
MIDNIGHT_LEAD_SEC = float(_get("MIDNIGHT_LEAD_SEC", "10"))

# --- SMS codes ---
# chatdb  — iPhone Text Message Forwarding -> Mac Messages -> chat.db watcher
# webhook — the phone POSTs each SMS to sms_relay.server (iPhone Shortcut or
#           an Android SMS-forwarder app)
# manual  — a human types the code into the emulator (foreground runs only)
SMS_SOURCE = _get("SMS_SOURCE", "chatdb")
SMS_MODE = "manual" if SMS_SOURCE == "manual" else "relay"
SMS_FILE = DATA_DIR / "latest_sms.json"
SMS_WEBHOOK_PORT = int(_get("SMS_WEBHOOK_PORT", "8777"))
SMS_WEBHOOK_TOKEN = _get("SMS_WEBHOOK_TOKEN")
# Carrier delivery of gov4c codes can lag ~15 min and then flush a batch, so
# wait long enough to ride that out; a stale code typed after the flush is
# handled by the retype loop in flow.py.
SMS_WAIT_TIMEOUT_SEC = int(_get("SMS_WAIT_TIMEOUT_SEC", "900"))

# --- notifications ---
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# --- booking policy (see checker/booking.py) ---
# button — alert with a Telegram «Book» button; books only when pressed
# auto   — books the earliest slot at least MIN_LEAD_H away without asking
#          (nearer slots still get the button)
# alert  — alert only; the human books on their phone
BOOKING_MODE = _get("BOOKING_MODE", "button")
MIN_LEAD_H = float(_get("TSON_MIN_LEAD_H", "24"))
# Optional blackout: never book these dates (inclusive).
BLACKOUT_FROM = _date("TSON_BLACKOUT_FROM")
BLACKOUT_TO = _date("TSON_BLACKOUT_TO")
# How long the «Book» button stays live (the cycle waits for the press).
BUTTON_WAIT_MIN = float(_get("TSON_BUTTON_WAIT_MIN", "45"))


def augment_path() -> None:
    """launchd starts jobs with a bare PATH (/usr/bin:/bin:...); everything we
    spawn (appium, node, adb, emulator) lives elsewhere."""
    extra = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        f"{ANDROID_HOME}/platform-tools",
        f"{ANDROID_HOME}/emulator",
    ]
    current = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    os.environ["PATH"] = ":".join(extra + [current])
