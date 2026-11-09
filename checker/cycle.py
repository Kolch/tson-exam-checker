"""Self-contained check cycle — the unit launchd runs and forgets.

Modes (argv[1], default "gate"):
  gate      periodic entry (every 2 min): exit fast unless a check is due
            per data/next_run.json; if due — run one cycle, schedule next.
  calendar  midnight entries (23:59 -> sleep to 23:59:50; 00:05 -> now).
  force     run one cycle immediately (manual run / verifying a fix).

A cycle = ensure emulator booted -> ensure Appium -> start the SMS source ->
one full check -> schedule next -> exit. On failure: deterministic heal
(restart Appium + reboot emulator) and one retry; if that fails too -> one
loud Telegram alert asking the human to run their coding agent (Claude Code
/ Codex) on docs/troubleshooting.md, silent log lines afterwards.
"""

import fcntl
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta

from checker import config, notify

STATE = config.DATA_DIR / "next_run.json"
LOCK_FILE = config.DATA_DIR / "cycle.lock"
LOGGED_OUT_FLAG = config.DATA_DIR / "logged_out.json"
SMS_SILENCE_FLAG = config.DATA_DIR / "sms_silence.json"
WRONG_APP_FLAG = config.DATA_DIR / "wrong_application.json"
BROKEN_FLAG = config.DATA_DIR / "broken.json"
PY = str(config.PROJECT_ROOT / ".venv" / "bin" / "python")

# booking outcomes after which checking stops until /start (see booking.py)
PAUSE_OUTCOMES = ("booked", "button_booked", "uncertain", "unparsed")


def log(msg: str) -> None:
    print(f"[cycle {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- schedule state -----------------------------------------------------------


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(**kw) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(kw, indent=2))


def next_regular(now: datetime) -> datetime:
    """Random CHECK_MIN..CHECK_MAX min ahead, avoiding the 23:55-00:12 window
    (the calendar agent owns midnight: 23:59:50 and 00:05 runs)."""
    cand = now + timedelta(
        seconds=random.uniform(config.CHECK_MIN_MIN * 60, config.CHECK_MAX_MIN * 60)
    )
    if (cand.hour == 23 and cand.minute >= 55) or (cand.hour == 0 and cand.minute < 12):
        midnight = (cand + timedelta(hours=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cand = midnight + timedelta(minutes=12 + random.uniform(0, 4))
    return cand


def is_due(mode: str) -> bool:
    st = read_state()
    if st.get("paused"):
        log(f"paused ({st.get('reason', '?')}) — /start in Telegram or delete {STATE} to resume")
        return False
    if mode in ("calendar", "force"):
        return True
    run_at = st.get("run_at", 0)
    if time.time() < run_at:
        log(f"not due yet (next at {datetime.fromtimestamp(run_at):%H:%M:%S})")
        return False
    return True


# --- stack management ----------------------------------------------------------


def _adb(*args, timeout=15) -> str:
    r = subprocess.run(
        [config.ADB, *args], capture_output=True, text=True, timeout=timeout
    )
    return r.stdout.strip()


def emulator_ready() -> bool:
    try:
        return _adb("shell", "getprop", "sys.boot_completed") == "1"
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_emulator() -> None:
    if emulator_ready():
        return
    log("emulator not running — booting headless…")
    subprocess.Popen(
        [config.EMULATOR_BIN, "-avd", config.AVD, "-dns-server", "8.8.8.8,1.1.1.1",
         "-no-window", "-gpu", "swiftshader_indirect", "-no-boot-anim", "-no-audio"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    deadline = time.time() + 300
    while time.time() < deadline:
        if emulator_ready():
            log("emulator booted")
            time.sleep(5)  # let services settle
            return
        time.sleep(3)
    raise RuntimeError("emulator did not boot within 300s")


def appium_ready() -> bool:
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "3", f"{config.APPIUM_SERVER}/status"],
            capture_output=True, text=True, timeout=6,
        )
        return '"ready":true' in r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_appium() -> None:
    if appium_ready():
        return
    log("appium not running — starting…")
    with open(config.DATA_DIR / "appium.log", "a") as fh:
        subprocess.Popen(
            ["/bin/bash", str(config.PROJECT_ROOT / "scripts" / "start_appium.sh")],
            stdout=fh, stderr=subprocess.STDOUT, start_new_session=True,
        )
    deadline = time.time() + 60
    while time.time() < deadline:
        if appium_ready():
            log("appium ready")
            return
        time.sleep(2)
    raise RuntimeError("appium did not become ready within 60s")


def kill_appium() -> None:
    subprocess.run(["pkill", "-f", "appium"], check=False)
    time.sleep(2)


def ensure_chatdb_readable() -> None:
    import sqlite3

    db = os.path.expanduser("~/Library/Messages/chat.db")
    try:
        sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("SELECT 1")
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "chat.db unreadable — grant Full Disk Access to the Python binary "
            f"({os.path.realpath(PY)}) in System Settings → Privacy & Security"
        ) from exc


def start_sms_source() -> subprocess.Popen | None:
    """Run the configured SMS relay for the duration of one cycle."""
    if config.SMS_SOURCE == "chatdb":
        ensure_chatdb_readable()
        module = "sms_relay.chatdb_watcher"
    elif config.SMS_SOURCE == "webhook":
        module = "sms_relay.server"
    else:
        return None
    with open(config.DATA_DIR / "sms_relay.log", "a") as fh:
        return subprocess.Popen(
            [PY, "-u", "-m", module], cwd=config.PROJECT_ROOT,
            stdout=fh, stderr=subprocess.STDOUT,
        )


# --- the check itself -----------------------------------------------------------


def run_check() -> None:
    from checker import session

    relay = start_sms_source()
    driver = None
    try:
        driver = session.make_driver()
        available, details, screenshot = session.run_one_check(driver)
        log(f"check done: available={available} — {details}")
        if available:
            from checker import booking

            outcome = booking.handle_slots(driver, screenshot)
            log(f"booking outcome: {outcome}")
            if outcome in PAUSE_OUTCOMES:
                write_state(paused=True, reason=outcome, found_at=time.time())
                return  # leave the app as is: it shows the evidence
        try:
            driver.terminate_app(session.APP)
        except Exception:  # noqa: BLE001
            pass
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
        if relay is not None:
            relay.terminate()


def deterministic_heal() -> None:
    """Bounce Appium AND reboot the guest OS. The reboot is not optional:
    after ~a week of emulator uptime Android's accessibility manager serves a
    STALE node tree (screen fine, a11y frozen on an old screen), and only a
    guest reboot clears it."""
    log("heal: restarting appium + rebooting emulator (clears stale a11y tree)")
    kill_appium()
    if emulator_ready():
        subprocess.run([config.ADB, "reboot"], check=False, timeout=15)
        time.sleep(15)  # let it go down before polling boot_completed
    deadline = time.time() + 240
    while time.time() < deadline:
        if emulator_ready():
            break
        time.sleep(3)
    else:
        log("heal: guest reboot didn't come back — cold restart")
        subprocess.run([config.ADB, "emu", "kill"], check=False, timeout=15)
        time.sleep(5)
    ensure_emulator()
    ensure_appium()


def auto_login() -> None:
    """The login sheet is on screen (LoggedOutError was just raised) —
    re-login with the credentials from .env (flow.login drives adb
    coordinates; the SMS arrives through the relay)."""
    from checker import flow, session

    log("attempting automatic re-login…")
    notify.log("🔑 сессия ЦОН истекла — выполняю автоматический вход…")
    relay = start_sms_source()
    driver = None
    try:
        driver = session.make_driver()
        flow.login(driver)
        notify.log("✅ автологин успешен — продолжаю проверки")
        LOGGED_OUT_FLAG.unlink(missing_ok=True)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
        if relay is not None:
            relay.terminate()


def _alert_once(flag, loud: str, quiet: str, err: str) -> None:
    """Loud Telegram the first time an incident starts, silent log after."""
    if flag.exists():
        notify.log(quiet)
        return
    flag.write_text(json.dumps({"at": time.time(), "error": err}))
    notify.telegram(loud)


def alert_sms_silence(err: str) -> None:
    """External SMS outage (carrier/gov4c) — retry on schedule, no healing."""
    log(f"sms silence ({err}) — will keep retrying on schedule")
    _alert_once(
        SMS_SILENCE_FLAG,
        "⚠️ SMS-коды от ЦОН не доходят (сбой оператора/госуслуг или пересылки SMS). "
        "Продолжаю проверки по расписанию; сообщу, когда доставка вернётся.",
        "❌ SMS-коды всё ещё не приходят", err,
    )


def alert_wrong_application(err: str) -> None:
    """Шаг 1 rejected the заявка. A valid заявка can be rejected during a
    gov-side outage, and the rejection happens BEFORE the SMS request, so
    retries are free: keep checking on schedule."""
    log(f"заявка rejected ({err}) — will keep retrying on schedule")
    _alert_once(
        WRONG_APP_FLAG,
        f"⚠️ ЦОН пишет «возможно некорректный ИИН/номер заявки» ({err[:100]}). "
        "Проверь номер заявки в .env и что вошёл под своим ИИН. Если всё верно — "
        "это сбой на стороне госуслуг: продолжаю проверки, сообщу, когда пройдёт.",
        f"❌ заявка всё ещё отклоняется ({err[:80]})", err,
    )


def alert_logged_out(err: str) -> None:
    """Session expired and auto-login failed or is not configured."""
    log(f"logged out, no automatic re-login ({err})")
    _alert_once(
        LOGGED_OUT_FLAG,
        "🚨 ЦОН-чекер: приложение разлогинилось (сессия живёт ~7 дней), "
        f"автоматический вход не сработал ({err[:150]}).\n"
        "Нужен ручной вход: открой Claude Code или Codex в папке проекта и скажи "
        "«ЦОН разлогинился, помоги войти» (см. docs/troubleshooting.md). "
        "После входа проверки продолжатся сами.",
        "❌ ЦОН всё ещё разлогинен — нужен ручной вход", err,
    )


def alert_broken(err: str) -> None:
    """The check fails even after a stack restart — a human (with their
    coding agent) has to look. Loud once; silent until it recovers."""
    _alert_once(
        BROKEN_FLAG,
        f"⚠️ ЦОН-чекер сломался: проверка падает даже после перезапуска ({err[:150]}).\n"
        "Открой Claude Code или Codex в папке проекта и скажи «чекер сломался, "
        "почини по docs/troubleshooting.md». Проверки продолжаются по расписанию.",
        f"❌ проверка всё ещё падает: {err[:100]}", err,
    )


def mark_healthy() -> None:
    """A check fully succeeded — clear incident flags, announce recovery."""
    for flag, text in (
        (SMS_SILENCE_FLAG, "✅ SMS-коды снова доходят — проверки в норме."),
        (WRONG_APP_FLAG, "✅ Заявка снова проходит — проверки в норме."),
        (BROKEN_FLAG, "✅ Чекер снова работает — проверки в норме."),
        (LOGGED_OUT_FLAG, "✅ Вход восстановлен — проверки в норме."),
    ):
        if flag.exists():
            flag.unlink(missing_ok=True)
            notify.telegram(text)


# --- entry -----------------------------------------------------------------------


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "gate"
    config.augment_path()
    config.DATA_DIR.mkdir(exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another cycle is already running — exiting")
        return
    if not is_due(mode):
        return
    if config.SMS_SOURCE == "manual":
        log("SMS_SOURCE=manual cannot run unattended — use chatdb or webhook "
            "(or run checker.validate_path by hand)")
        return

    now = datetime.now()
    if mode == "calendar" and now.hour == 23:
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        target = midnight - timedelta(seconds=config.MIDNIGHT_LEAD_SEC)
        wait = (target - now).total_seconds()
        if wait > 0:
            log(f"midnight run — sleeping {wait:.0f}s to start at {target:%H:%M:%S}")
            time.sleep(wait)

    log(f"=== cycle start (mode={mode}) ===")
    # lazy imports: gate mode must exit fast
    from checker.flow import LoggedOutError, SmsSilenceError, WrongApplicationError

    def login_and_recheck() -> None:
        """LoggedOutError path: re-login automatically, then rerun the check."""
        try:
            auto_login()
            run_check()
            mark_healthy()
            log("check succeeded after auto-login")
        except Exception as exc:  # noqa: BLE001
            alert_logged_out(f"{type(exc).__name__}: {exc}")

    try:
        ensure_emulator()
        ensure_appium()
        run_check()
        mark_healthy()
    except WrongApplicationError as exc:
        alert_wrong_application(str(exc))
    except SmsSilenceError as exc:
        alert_sms_silence(str(exc))
    except LoggedOutError:
        login_and_recheck()
    except Exception as exc:  # noqa: BLE001
        # str(), not repr(): selenium exceptions keep their message out of
        # repr, which shows a useless bare "TimeoutException()".
        err = f"{type(exc).__name__}: {exc}".strip()
        snap = config.DATA_DIR / f"fail_{int(time.time())}.png"
        try:  # capture what was actually on screen at failure time
            with open(snap, "wb") as fh:
                subprocess.run([config.ADB, "exec-out", "screencap", "-p"],
                               stdout=fh, timeout=15, check=False)
            log(f"failure screenshot: {snap}")
        except Exception:  # noqa: BLE001
            pass
        log(f"check failed: {err} — deterministic heal + retry")
        notify.log(f"❌ проверка не удалась: {err[:120]} — перезапускаю и пробую снова")
        try:
            deterministic_heal()
            run_check()
            mark_healthy()
            log("retry succeeded after heal")
        except LoggedOutError:
            login_and_recheck()
        except WrongApplicationError as exc2:
            alert_wrong_application(str(exc2))
        except SmsSilenceError as exc2:
            alert_sms_silence(str(exc2))
        except Exception as exc2:  # noqa: BLE001
            err2 = f"{type(exc2).__name__}: {exc2}".strip()
            log(f"retry failed too: {err2}")
            alert_broken(f"{err} | after restart: {err2}")

    if not read_state().get("paused"):
        nxt = next_regular(datetime.now())
        write_state(run_at=nxt.timestamp(), kind="regular", set_at=time.time())
        log(f"next regular check at {nxt:%H:%M:%S}")
    log("=== cycle end ===")


if __name__ == "__main__":
    main()
