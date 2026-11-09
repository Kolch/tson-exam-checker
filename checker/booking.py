"""Slot decision engine (BOOKING_MODE, see .env.example).

Called with the date sheet OPEN and the no-slots marker gone:
- blackout dates (TSON_BLACKOUT_FROM/TO) are never booked;
- every other date's times are read to build the slot inventory;
- button (default): the earliest slot is offered with a Telegram «Book»
  button and booked only if pressed within TSON_BUTTON_WAIT_MIN;
- auto: the earliest slot at least TSON_MIN_LEAD_H away is booked at once;
  if none qualifies, the nearest one is offered with the button;
- alert: a loud alert with the list; the human books on their phone.
Alerts are re-sent only when the set of slots changes (data/slots_seen.json).

Booking = pick date + time -> «Продолжить» -> flow.confirm_booking (Шаг 4).
A confirmed booking cannot be cancelled, so nothing is booked unless the
mode allows it.
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta

from checker import config, flow, notify, session

SEEN_FILE = config.DATA_DIR / "slots_seen.json"


def _tg(method: str, payload: dict) -> dict:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return {}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=40).read())
    except OSError as exc:
        print(f"[booking] telegram {method} failed: {exc}")
        return {}


def in_blackout(d) -> bool:
    lo = config.BLACKOUT_FROM or config.BLACKOUT_TO
    hi = config.BLACKOUT_TO or config.BLACKOUT_FROM
    return lo is not None and lo <= d <= hi


def _slot_dt(d, t: str) -> datetime:
    h, m = t.split(":")
    return datetime(d.year, d.month, d.day, int(h), int(m))


def _fmt(d, t: str) -> str:
    return f"{d:%d.%m.%Y} {t}"


def _listing(slots) -> str:
    by_date: dict = {}
    for d, _, t in slots:
        by_date.setdefault(d, []).append(t)
    lines = [f"• {d:%d.%m.%Y}: {', '.join(ts)}" for d, ts in sorted(by_date.items())]
    if len(lines) > 10:
        lines = lines[:10] + [f"… и ещё {len(lines) - 10} дат"]
    return "\n".join(lines)


def _seen() -> str:
    try:
        return SEEN_FILE.read_text()
    except OSError:
        return ""


def _snap(driver, name: str):
    path = config.DATA_DIR / f"{name}_{int(time.time())}.png"
    try:
        driver.get_screenshot_as_file(str(path))
        return path
    except Exception:  # noqa: BLE001
        return None


def handle_slots(driver, screenshot) -> str:
    """Returns the outcome: booked | button_booked | uncertain | alerted |
    button_expired | blackout | unchanged | unparsed | no_times | error.
    cycle.py pauses checking on booked / button_booked / uncertain / unparsed."""
    now = datetime.now()
    dates = flow.read_available_dates(driver)  # [(date, chip_desc)] ascending
    if not dates:
        notify.telegram(
            "🚨 ЦОН: маркер «нет слотов» пропал, но даты не распознаны — возможно, "
            "приложение обновилось. Срочно проверь запись в приложении ЦОН на телефоне. "
            "Проверки на паузе; /start — возобновить.", photo=screenshot,
        )
        return "unparsed"

    print(f"[booking] available dates: {[d.isoformat() for d, _ in dates]}")
    eligible = [(d, desc) for d, desc in dates if not in_blackout(d)]
    slots = []  # [(date, chip_desc, time)] ascending
    for d, desc in eligible:
        flow.pick_date(driver, desc)
        times = flow.open_time_sheet_and_read(driver)
        if config.BOOKING_MODE == "auto":
            for t in times:
                if _slot_dt(d, t) - now >= timedelta(hours=config.MIN_LEAD_H):
                    flow.pick_time(driver, t)
                    return _book(driver, d, t, screenshot)
        slots += [(d, desc, t) for t in times]
        flow.close_any_sheet(driver)
        flow.reopen_date_sheet(driver, desc)

    signature = json.dumps(
        {"dates": [d.isoformat() for d, _ in dates],
         "slots": [f"{d.isoformat()} {t}" for d, _, t in slots]},
        sort_keys=True,
    )
    if signature == _seen():
        print("[booking] slots unchanged since last alert — staying quiet")
        notify.log("👀 слоты без изменений с прошлого сообщения")
        return "unchanged"
    SEEN_FILE.write_text(signature)

    if not eligible:
        notify.telegram(
            "ℹ️ Слоты есть, но все даты в твоём чёрном списке: "
            f"{', '.join(f'{d:%d.%m}' for d, _ in dates)}. Не бронирую, проверяю дальше.",
            photo=screenshot,
        )
        return "blackout"
    if not slots:
        notify.telegram("ℹ️ Даты открыты, но свободного времени нет. Проверяю дальше.",
                        photo=screenshot)
        return "no_times"

    listing = _listing(slots)
    if config.BOOKING_MODE == "alert":
        notify.telegram(
            f"🚨 ЦОН: ПОЯВИЛИСЬ СЛОТЫ НА ТЕОРИЮ!\n{listing}\n\n"
            "Бронируй прямо сейчас в приложении ЦОН на телефоне — слоты разбирают за минуты.",
            photo=screenshot,
        )
        return "alerted"
    return _button_flow(driver, slots[0], screenshot, listing)


def _book(driver, d, t: str, screenshot) -> str:
    """Date + time already selected on Шаг 3 -> «Продолжить» -> Шаг 4."""
    slot = _fmt(d, t)
    notify.telegram(f"🚨 Бронирую слот {slot}…", photo=screenshot)
    flow.tap_continue(driver)
    try:
        flow.confirm_booking(driver)
    except Exception as exc:  # noqa: BLE001
        notify.telegram(
            f"❌ Не смог подтвердить бронь {slot} автоматически ({str(exc)[:120]}).\n"
            "Срочно открой приложение ЦОН на телефоне: проверь, есть ли бронь, и если "
            "нет — забронируй вручную. Проверки на паузе; /start — возобновить.",
            photo=_snap(driver, "book_fail"),
        )
        return "uncertain"
    notify.telegram(
        f"✅ ЗАБРОНИРОВАНО: {slot}.\nОтменить бронь нельзя. Проверки остановлены.",
        photo=_snap(driver, "booked"),
    )
    return "booked"


def _button_flow(driver, first, screenshot, listing: str) -> str:
    d, desc, t = first
    slot = _fmt(d, t)
    _tg("sendMessage", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": (f"🚨 ЦОН: ПОЯВИЛИСЬ СЛОТЫ НА ТЕОРИЮ!\n{listing}\n\n"
                 f"Забронировать ближайший ({slot})? Нажми кнопку в течение "
                 f"{config.BUTTON_WAIT_MIN:g} мин. Отменить бронь потом нельзя."),
        "reply_markup": {"inline_keyboard": [[{"text": f"✅ Забронировать {slot}",
                                               "callback_data": "tson_book"}]]},
    })
    notify.telegram(f"Слоты: {slot} и др.", photo=screenshot, silent=True)

    # Wait for the press. If the control bot is alive it owns getUpdates and
    # relays the callback to a file; otherwise poll directly.
    sent_at = time.time()
    deadline = sent_at + config.BUTTON_WAIT_MIN * 60
    print(f"[booking] waiting {config.BUTTON_WAIT_MIN:g} min for the Book button…")
    if _ctlbot_alive():
        pressed = config.DATA_DIR / "book_pressed.json"
        while time.time() < deadline:
            try:
                rec = json.loads(pressed.read_text())
                if rec.get("data") == "tson_book" and rec.get("at", 0) > sent_at:
                    return _button_book(driver, d, desc, t, screenshot)
            except (OSError, ValueError):
                pass
            time.sleep(2)
    else:
        offset = None
        while time.time() < deadline:
            resp = _tg("getUpdates", {"timeout": 25, "offset": offset,
                                      "allowed_updates": ["callback_query"]})
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if cq and cq.get("data") == "tson_book":
                    _tg("answerCallbackQuery",
                        {"callback_query_id": cq["id"], "text": "Бронирую…"})
                    return _button_book(driver, d, desc, t, screenshot)
            if not resp:
                time.sleep(5)  # telegram unreachable — don't spin
    notify.log(f"⏳ окно кнопки истекло — слот {slot} не бронирую")
    return "button_expired"


def _ctlbot_alive() -> bool:
    try:
        pid = int((config.DATA_DIR / "ctlbot.pid").read_text())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _button_book(driver, d, desc, t, screenshot) -> str:
    """Try the still-open session first; fall back to a fresh flow (new SMS)."""
    try:
        flow.close_any_sheet(driver)
        flow.reopen_date_sheet(driver, desc)
        flow.pick_date(driver, desc)
        times = flow.open_time_sheet_and_read(driver)
        if t not in times:
            raise RuntimeError(f"время {t} исчезло, осталось: {times}")
        flow.pick_time(driver, t)
    except Exception as exc:  # noqa: BLE001
        print(f"[booking] same-session selection failed ({exc!r}) — fresh flow")
        notify.log("сессия истекла — захожу заново (новый SMS-код)")
        try:
            available, _, shot = session.run_one_check(driver)
            if not available:
                notify.telegram(f"😞 Пока заходил заново, слоты пропали ({_fmt(d, t)}).")
                return "error"
            dates = dict(flow.read_available_dates(driver))
            if d not in dates:
                notify.telegram(f"😞 Дата {d:%d.%m.%Y} уже занята. Доступно: "
                                f"{', '.join(f'{x:%d.%m}' for x in dates)}.")
                return "error"
            flow.pick_date(driver, dates[d])
            times = flow.open_time_sheet_and_read(driver)
            if not times:
                notify.telegram(f"😞 На {d:%d.%m.%Y} не осталось времени.")
                return "error"
            t = t if t in times else times[0]
            flow.pick_time(driver, t)
            screenshot = shot or screenshot
        except Exception as exc2:  # noqa: BLE001
            notify.telegram(f"❌ Не смог выбрать слот по кнопке: {str(exc2)[:150]} — "
                            "забронируй в приложении на телефоне.")
            return "error"
    outcome = _book(driver, d, t, screenshot)
    return "button_booked" if outcome == "booked" else outcome
