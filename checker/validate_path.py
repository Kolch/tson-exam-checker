"""First real run: walk the whole path once in the foreground and read the
date sheet. Uses the configured SMS source; with --manual you type the SMS
code into the (headed) emulator window yourself when Шаг 2 appears.

Prereqs: emulator booted, Appium up, app logged in, .env filled.
Run: .venv/bin/python -m checker.validate_path [--manual]
Costs one SMS code. Never books anything.
"""

import subprocess
import sys

from checker import config, flow, session


def main() -> None:
    if not config.APPLICATION_NUMBER:
        sys.exit("Set TSON_APPLICATION_NUMBER in .env first (cp .env.example .env)")
    manual = "--manual" in sys.argv or config.SMS_MODE == "manual"

    relay = None
    if not manual:
        module = {"chatdb": "sms_relay.chatdb_watcher", "webhook": "sms_relay.server"}[config.SMS_SOURCE]
        relay = subprocess.Popen([sys.executable, "-u", "-m", module], cwd=config.PROJECT_ROOT)
    driver = session.make_driver()
    try:
        print("[validate] (re)opening the app…")
        session.restart_app(driver)
        if manual:
            print("[validate] Шаг 2: type the SMS code into the emulator window yourself")
        flow.navigate_to_date_picker(driver, sms_mode="manual" if manual else "relay")
        print("[validate] running one slot check…")
        available, details, _ = flow.check_slots(driver)
        print(f"[validate] RESULT: slots_available={available} — {details}")
        print("[validate] path fully validated ✔ (nothing was booked)")
        driver.terminate_app(session.APP)
    finally:
        driver.quit()
        if relay:
            relay.terminate()


if __name__ == "__main__":
    main()
