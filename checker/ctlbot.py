"""Telegram control bot for the checker: /start /stop /restart /check /status.

Runs as its own launchd agent (kz.tson.ctlbot, KeepAlive) so it survives
everything and works even while the checker agents are unloaded. It is the
SINGLE getUpdates consumer for the bot token: it also relays the booking
«Book» button callback into data/book_pressed.json, which
booking._button_flow watches (two concurrent getUpdates pollers would 409).

Only messages from TELEGRAM_CHAT_ID are honored.
"""

import json
import os
import subprocess
import time
import urllib.request

from checker import config, cycle

OFFSET_FILE = config.DATA_DIR / "ctlbot_offset.json"
PID_FILE = config.DATA_DIR / "ctlbot.pid"
PRESSED_FILE = config.DATA_DIR / "book_pressed.json"
CHECKER_LABELS = ("kz.tson.checker.gate", "kz.tson.checker.midnight")
AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
UID = os.getuid()


def log(msg: str) -> None:
    print(f"[ctlbot {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def api(method: str, http_timeout: int = 60, **payload) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=http_timeout).read())
    except OSError as exc:
        log(f"api {method} failed: {exc}")
        return {}


def send(text: str) -> None:
    api("sendMessage", chat_id=config.TELEGRAM_CHAT_ID, text=text)


def _sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return (r.stdout + r.stderr).strip()


def agents_loaded() -> bool:
    out = _sh("launchctl", "list")
    return all(label in out for label in CHECKER_LABELS)


def do_stop() -> str:
    for label in CHECKER_LABELS:
        _sh("launchctl", "bootout", f"gui/{UID}/{label}")
    subprocess.run(["pkill", "-f", "checker.cycle"], check=False)
    return "🔴 Проверки остановлены (агенты выгружены, процессы убиты)."


def do_start() -> str:
    missing = [l for l in CHECKER_LABELS if not os.path.exists(f"{AGENTS_DIR}/{l}.plist")]
    if missing:
        return f"❌ Нет plist-файлов: {missing}. Запусти ./scripts/install_daemon.sh на Маке."
    for label in CHECKER_LABELS:
        _sh("launchctl", "bootstrap", f"gui/{UID}", f"{AGENTS_DIR}/{label}.plist")
    # clear a paused schedule so the next gate tick actually checks
    st = cycle.read_state()
    if st.get("paused"):
        cycle.STATE.unlink(missing_ok=True)
    _sh("launchctl", "kickstart", f"gui/{UID}/kz.tson.checker.gate")
    return "🟢 Проверки запущены — первая пойдёт прямо сейчас."


def status_text() -> str:
    lines = []
    lines.append(f"агенты: {'🟢 загружены' if agents_loaded() else '🔴 выгружены'}")
    st = cycle.read_state()
    if st.get("paused"):
        lines.append(f"расписание: ⏸ пауза ({st.get('reason', '?')})")
    elif st.get("run_at"):
        nxt = time.strftime("%H:%M:%S", time.localtime(st["run_at"]))
        lines.append(f"следующая проверка: {nxt}")
    else:
        lines.append("расписание: нет состояния (проверка на первом тике)")
    lines.append(f"эмулятор: {'🟢' if cycle.emulator_ready() else '🔴'}  "
                 f"appium: {'🟢' if cycle.appium_ready() else '🔴'}")
    for flag, name in ((cycle.LOGGED_OUT_FLAG, "разлогин"),
                       (cycle.WRONG_APP_FLAG, "заявка отклоняется"),
                       (cycle.SMS_SILENCE_FLAG, "SMS не доходят"),
                       (cycle.BROKEN_FLAG, "проверка падает")):
        if flag.exists():
            lines.append(f"⚠️ активный инцидент: {name}")
    try:
        tail = (config.DATA_DIR / "cycle.log").read_text().splitlines()[-3:]
        lines.append("последние строки лога:")
        lines.extend(f"  {l}" for l in tail)
    except OSError:
        pass
    return "\n".join(lines)


HELP = (
    "/start — запустить проверки\n"
    "/stop — остановить проверки\n"
    "/restart — перезапустить (стоп + старт)\n"
    "/check — внеплановая проверка сейчас\n"
    "/status — состояние системы\n"
    "/help — это сообщение"
)


def handle(text: str) -> None:
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    if cmd == "/start":
        send(do_start())
    elif cmd == "/stop":
        send(do_stop())
    elif cmd == "/restart":
        do_stop()
        time.sleep(2)
        send("♻️ " + do_start())
    elif cmd == "/check":
        if not agents_loaded():
            send("Агенты выгружены — сначала /start.")
        else:
            cycle.STATE.unlink(missing_ok=True)
            _sh("launchctl", "kickstart", f"gui/{UID}/kz.tson.checker.gate")
            send("🔎 Внеплановая проверка запущена.")
    elif cmd == "/status":
        send(status_text())
    elif cmd == "/help":
        send(HELP)
    # anything else: stay silent (don't spam on random texts)


def main() -> None:
    config.augment_path()
    config.DATA_DIR.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        offset = json.loads(OFFSET_FILE.read_text())["offset"]
    except (OSError, ValueError, KeyError):
        offset = None
    log(f"control bot up (pid {os.getpid()})")
    while True:
        resp = api("getUpdates", http_timeout=60, offset=offset, timeout=50,
                   allowed_updates=["message", "callback_query"])
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            OFFSET_FILE.write_text(json.dumps({"offset": offset}))
            cq = upd.get("callback_query")
            if cq:
                api("answerCallbackQuery", callback_query_id=cq["id"], text="Принято")
                PRESSED_FILE.write_text(
                    json.dumps({"at": time.time(), "data": cq.get("data", "")})
                )
                log(f"relayed callback: {cq.get('data')}")
                continue
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                continue
            text = msg.get("text", "")
            log(f"command: {text}")
            try:
                handle(text)
            except Exception as exc:  # noqa: BLE001 — the bot must not die
                log(f"handler error: {exc!r}")
                send(f"❌ ошибка: {str(exc)[:150]}")
        if not resp:
            time.sleep(10)  # telegram unreachable — don't spin


if __name__ == "__main__":
    main()
