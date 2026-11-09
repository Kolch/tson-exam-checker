"""Preflight: checks every piece the checker needs and says what to do next.

Run:  .venv/bin/python -m checker.doctor                  (python3 works before the venv exists)
      .venv/bin/python -m checker.doctor --telegram-test  also sends a test message
      .venv/bin/python -m checker.doctor --webhook-url    prints the phone's webhook URL (contains the token)
Exit code 0 = nothing required is missing. Never prints secrets from .env.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

FAILS: list[str] = []


def report(ok: bool | None, name: str, hint: str = "") -> None:
    """ok=True green, None warning (optional / not yet), False required+missing."""
    mark = {True: "✅", None: "⚠️ ", False: "❌"}[ok]
    print(f"{mark} {name}")
    if hint and ok is not True:
        print(f"     → {hint}")
    if ok is False:
        FAILS.append(name)


def sh(*cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def section(title: str) -> None:
    print(f"\n— {title}")


try:
    from checker import config
except ValueError as exc:  # e.g. a malformed date in .env
    sys.exit(f"❌ .env has an invalid value: {exc}")

config.augment_path()
ROOT = config.PROJECT_ROOT
VENV_PY = ROOT / ".venv" / "bin" / "python"


def check_toolchain() -> None:
    section("Mac and toolchain")
    report(platform.system() == "Darwin" and platform.machine() == "arm64",
           "macOS on Apple Silicon", "this project only supports Apple Silicon Macs (M1 or newer)")
    report(shutil.which("brew") is not None, "Homebrew", "install it from https://brew.sh")
    java = sh("/usr/libexec/java_home", "-F", "-v", "21")[0] == 0 or \
        Path("/opt/homebrew/opt/openjdk@21").exists()
    report(java, "Java 21", "./scripts/setup_env.sh")
    rc, out = sh("node", "--version")
    m = re.match(r"v(\d+)\.(\d+)", out)
    report(rc == 0 and m is not None and (int(m[1]), int(m[2])) >= (20, 19),
           f"Node ≥ 20.19 ({out or 'missing'})", "./scripts/setup_env.sh (or brew upgrade node)")
    report(shutil.which("appium") is not None, "Appium", "./scripts/setup_env.sh")
    rc, out = sh("appium", "driver", "list", "--installed")
    report("uiautomator2" in out, "Appium uiautomator2 driver", "appium driver install uiautomator2")
    report(Path(config.ADB).exists(), "Android platform-tools (adb)", "./scripts/setup_env.sh")
    report(Path(config.EMULATOR_BIN).exists(), "Android emulator", "./scripts/setup_env.sh")
    rc, out = sh(config.EMULATOR_BIN, "-list-avds")
    report(config.AVD in out.split(), f"AVD '{config.AVD}'", "./scripts/setup_env.sh")
    venv_ok = VENV_PY.exists() and sh(str(VENV_PY), "-c", "import appium")[0] == 0
    report(venv_ok, "Python venv with Appium client", "./scripts/setup_env.sh")


def check_env() -> None:
    section(".env settings")
    if not config.ENV_FILE.exists():
        report(False, ".env exists", "cp .env.example .env, then fill it in (see docs/SETUP.md)")
        return
    report(True, ".env exists")
    report(config.APPLICATION_NUMBER.isdigit(), "TSON_APPLICATION_NUMBER (номер заявки)",
           "digits only; from the «Первичное получение ВУ» service")
    report(bool(re.fullmatch(r"\d{4,6}", config.APP_PIN)), "TSON_APP_PIN (код доступа)",
           "the passcode you set in the app after logging in")
    report(bool(re.fullmatch(r"\d+:[\w-]{30,}", config.TELEGRAM_BOT_TOKEN)), "TELEGRAM_BOT_TOKEN",
           "create a bot with @BotFather")
    report(bool(re.fullmatch(r"-?\d+", config.TELEGRAM_CHAT_ID)), "TELEGRAM_CHAT_ID",
           "send /start to your bot, then read chat.id from getUpdates (docs/SETUP.md)")
    report(config.BOOKING_MODE in ("button", "auto", "alert"), f"BOOKING_MODE={config.BOOKING_MODE}",
           "one of: button, auto, alert")
    relogin = bool(re.fullmatch(r"\d{12}", config.IIN)) and bool(re.fullmatch(r"\+?7\d{10}", config.PHONE))
    report(True if relogin else None, "auto re-login (TSON_IIN + TSON_PHONE)",
           "optional: without it you log in by hand every ~7 days when the session expires")


def _chatdb_check() -> None:
    import sqlite3

    db = Path.home() / "Library" / "Messages" / "chat.db"
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        (last,) = conn.execute(
            "SELECT MAX(date) FROM message WHERE is_from_me = 0 AND service = 'SMS'"
        ).fetchone()
    except sqlite3.OperationalError:
        report(False, "chat.db readable (Full Disk Access)",
               "System Settings → Privacy & Security → Full Disk Access → add your terminal app, restart it")
        return
    report(True, "chat.db readable (Full Disk Access)")
    recent = last is not None and (time.time() - (last / 1e9 + 978307200)) < 14 * 86400
    report(True if recent else None, "SMS from the iPhone reach this Mac",
           "iPhone: Settings → Apps → Messages → Text Message Forwarding → enable this Mac; "
           "then send yourself an SMS from another phone")
    real = os.path.realpath(VENV_PY)
    m = re.match(r"(.*/Python\.framework/Versions/[^/]+)/", real)
    target = f"{m[1]}/Resources/Python.app" if m else real
    print(f"     ℹ️  the daemon reads chat.db as {target} — it needs Full Disk Access too")


def check_sms(show_url: bool) -> None:
    section(f"SMS codes (SMS_SOURCE={config.SMS_SOURCE})")
    if config.SMS_SOURCE == "chatdb":
        _chatdb_check()
    elif config.SMS_SOURCE == "webhook":
        report(bool(config.SMS_WEBHOOK_TOKEN), "SMS_WEBHOOK_TOKEN set",
               "generate one: openssl rand -hex 16")
        ip = sh("ipconfig", "getifaddr", "en0")[1] or sh("ipconfig", "getifaddr", "en1")[1] or "<mac-ip>"
        url = f"http://{ip}:{config.SMS_WEBHOOK_PORT}/sms?token="
        shown = config.SMS_WEBHOOK_TOKEN if show_url else "<SMS_WEBHOOK_TOKEN>"
        print(f"     ℹ️  phone posts SMS to {url}{shown}   (docs/sms.md)")
    elif config.SMS_SOURCE == "manual":
        report(None, "SMS_SOURCE=manual", "fine for checker.validate_path; the daemon needs chatdb or webhook")
    else:
        report(False, f"SMS_SOURCE={config.SMS_SOURCE}", "one of: chatdb, webhook, manual")


def check_telegram(send_test: bool) -> None:
    section("Telegram")
    if not config.TELEGRAM_BOT_TOKEN:
        report(False, "bot token", "see .env settings above")
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getMe"
        me = json.loads(urllib.request.urlopen(url, timeout=15).read())["result"]
        report(True, f"bot @{me['username']} reachable")
    except Exception as exc:  # noqa: BLE001
        report(False, "bot token works", f"Telegram rejected it or is unreachable ({type(exc).__name__})")
        return
    if send_test:
        from checker import notify

        notify.telegram("✅ Тестовое сообщение от ЦОН-чекера — уведомления работают.")
        print("     ℹ️  test message sent — check Telegram")


def check_device() -> None:
    section("Emulator, app, Appium")
    rc, out = sh(config.ADB, "shell", "getprop", "sys.boot_completed", timeout=10)
    if out.strip() != "1":
        report(None, "emulator running", "./scripts/start_emulator.sh (the daemon boots it by itself)")
        return
    report(True, "emulator running")
    rc, out = sh(config.ADB, "shell", "pm", "list", "packages", config.APP_PACKAGE)
    report(config.APP_PACKAGE in out, f"ЦОН app installed ({config.APP_PACKAGE})",
           "install the APK: docs/SETUP.md, phase 3")
    rc, out = sh("curl", "-s", "--max-time", "3", f"{config.APPIUM_SERVER}/status")
    report(True if '"ready":true' in out else None, "Appium server",
           "./scripts/start_appium.sh (the daemon starts it by itself)")


def check_daemon() -> None:
    section("Unattended mode")
    rc, out = sh("pmset", "-g")
    m = re.search(r"^\s*sleep\s+(\d+)", out, re.M)
    report(True if m and m[1] == "0" else None, "Mac doesn't fall asleep",
           "System Settings → Battery (or Energy) → on power adapter, prevent automatic sleeping; "
           "keep the Mac plugged in — checks don't run while it sleeps")
    agents = Path.home() / "Library" / "LaunchAgents"
    installed = all((agents / f"{l}.plist").exists()
                    for l in ("kz.tson.checker.gate", "kz.tson.checker.midnight", "kz.tson.ctlbot"))
    report(True if installed else None, "daemon installed", "./scripts/install_daemon.sh (last setup step)")
    state = config.DATA_DIR / "next_run.json"
    if state.exists():
        st = json.loads(state.read_text())
        if st.get("paused"):
            print(f"     ℹ️  checks are PAUSED ({st.get('reason')}) — /start in Telegram resumes")


def main() -> None:
    check_toolchain()
    check_env()
    check_sms(show_url="--webhook-url" in sys.argv)
    check_telegram(send_test="--telegram-test" in sys.argv)
    check_device()
    check_daemon()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} required item(s) missing: {', '.join(FAILS)}")
        sys.exit(1)
    print("✅ everything required is in place")


if __name__ == "__main__":
    main()
