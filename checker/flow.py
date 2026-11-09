"""Navigation through the ЦОН app, screen by screen (see docs/booking-flow.md).

The app is Flutter: all visible text is exposed via the accessibility bridge
as `content-desc` (the `text` attribute is empty), so every selector here
matches on description, not text. Verified against a live UI dump 2026-07-29.
"""

import re
import subprocess
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from checker import config, notify, sms

# --- Russian UI strings as exposed in content-desc ---
DESC_SPETSTSON_CARD = "СпецЦОН"
DESC_SERVICES_TITLE = "Услуги СпецЦОН"
DESC_THEORY_SERVICE = "Запись на экзамен по теории"
DESC_BOOK_BUTTON = "Записаться"
DESC_CONSENT_CHECKBOX = "Подтверждаю"
DESC_APP_NUMBER_HINT = "Введите номер заявки"
DESC_CONTINUE = "Продолжить"
DESC_DATE_FIELD = "Выберите дату"
DESC_DATE_SHEET_TITLE = "Выберите дату регистрации"
DESC_NO_SLOTS = "Все записи на этот месяц уже заняты"
DESC_SHEET_OVERLAY = "Маска"  # tappable overlay behind the bottom sheet
DESC_LOGIN_SCREEN = "Вход в ЦОН"


class LoggedOutError(Exception):
    """The app dropped to the «Вход в ЦОН» login sheet: the server session
    expired (observed live 2026-08-05, exactly 7 days after login). Only a
    manual re-login (ИИН + телефон + SMS) fixes this — no point in healing."""


class SmsSilenceError(Exception):
    """No SMS code arrived through the relay NOR the manual window. External
    (carrier/gov4c outage or rate-limit) — healing the local stack is
    pointless; just retry on the normal schedule."""


class WrongApplicationError(Exception):
    """Шаг 1 rejected the номер заявки for the logged-in ИИН (red text
    «Возможно вы зашли по некорректному ИИН…», seen live 2026-08-05 after
    re-login under a different account). Retrying is pointless — the
    credentials/заявка pairing in .env must be fixed by the human."""


DESC_WRONG_APPLICATION = "Возможно вы зашли по некорректному ИИН"


def _desc_selector(desc: str) -> str:
    return f'new UiSelector().descriptionContains("{desc}")'


def _by_desc(driver, desc, timeout=15):
    try:
        return WebDriverWait(driver, timeout).until(
            lambda d: d.find_element(AppiumBy.ANDROID_UIAUTOMATOR, _desc_selector(desc))
        )
    except TimeoutException as exc:
        raise TimeoutException(f"element with desc {desc!r} not found in {timeout}s") from exc


def _desc_present(driver, desc) -> bool:
    try:
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, _desc_selector(desc))
        return True
    except NoSuchElementException:
        return False


def _scroll_to_desc(driver, desc):
    selector = (
        "new UiScrollable(new UiSelector().scrollable(true))"
        f'.scrollIntoView(new UiSelector().descriptionContains("{desc}"))'
    )
    return driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)


DESC_PIN_SCREEN = "Введите код доступа"


def maybe_enter_pin(driver) -> bool:
    """If a passcode screen is up (enter, create, or repeat variant — all
    contain «код доступа»), type the PIN. Returns True if it was."""
    if not config.APP_PIN:
        return False
    # enter, create (exact wording seen live 2026-08-05), and repeat variants
    on_pin_screen = any(
        _desc_present(driver, d)
        for d in (DESC_PIN_SCREEN, "Создайте код доступа", "Придумайте код доступа",
                  "Повторите код доступа")
    )
    if not on_pin_screen:
        return False
    print("[flow] код доступа screen — entering PIN")
    for digit in config.APP_PIN:
        driver.find_element(
            AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().description("{digit}")'
        ).click()
    time.sleep(2)
    return True


def _click_until(driver, click_desc: str, expect_descs: list[str], attempts: int = 4) -> None:
    """Click `click_desc` and wait until ANY of `expect_descs` appears; retry
    if the tap didn't land (common while Flutter screens are still animating).
    Handles the passcode screen if the tap triggers it."""
    for attempt in range(1, attempts + 1):
        _by_desc(driver, click_desc).click()
        deadline = time.time() + 6
        while time.time() < deadline:
            if _desc_present(driver, DESC_LOGIN_SCREEN):
                raise LoggedOutError(
                    f"clicked {click_desc!r} and got the «Вход в ЦОН» login "
                    "screen — app session expired, manual re-login required"
                )
            if maybe_enter_pin(driver):
                deadline = time.time() + 10  # give it time to land after unlock
            if any(_desc_present(driver, d) for d in expect_descs):
                return
            time.sleep(0.5)
        # the click may have navigated somewhere the PIN already unlocked;
        # if the click target is gone AND an expectation shows later, we're fine
        if not _desc_present(driver, click_desc):
            raise TimeoutException(
                f"clicked {click_desc!r} and left the screen, but none of "
                f"{expect_descs!r} appeared — selectors for the next screen are wrong"
            )
        print(f"[flow] tap on {click_desc!r} didn't navigate (attempt {attempt}) — retrying")
    raise TimeoutException(f"never reached any of {expect_descs!r} after clicking {click_desc!r}")


def ensure_home(driver, timeout: int = 25) -> None:
    """Get to the app home screen, entering the PIN if the lock screen shows."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # the login sheet covers home and owns the a11y tree — check it first
        if _desc_present(driver, DESC_LOGIN_SCREEN):
            raise LoggedOutError(
                "app opened on the «Вход в ЦОН» login screen — session "
                "expired, manual re-login required"
            )
        if _desc_present(driver, DESC_SPETSTSON_CARD):
            return
        maybe_enter_pin(driver)
        time.sleep(1)
    raise TimeoutException(f"home screen (СпецЦОН card) not reached in {timeout}s")


def _adb_shell(*args: str) -> None:
    subprocess.run([config.ADB, "shell", *args], check=False, timeout=20)


def _tap_scaled(driver, x: int, y: int) -> None:
    """adb tap at a point measured on the 1080x2400 Pixel 7 AVD, scaled to the
    actual screen (a no-op on the AVD that scripts/setup_env.sh creates)."""
    size = driver.get_window_size()
    sx, sy = size["width"] / 1080, size["height"] / 2400
    _adb_shell("input", "tap", str(round(x * sx)), str(round(y * sy)))


def login(driver) -> None:
    """Re-login on the «Вход в ЦОН» sheet. Validated live 2026-08-05.

    The a11y tree is often STALE on this screen (kept showing an old route),
    so everything is driven by adb coordinates (measured on 1080x2400):
      ИИН field (540,937) → phone field WITH KEYBOARD OPEN (540,1067) →
      checkbox (68,2000) KEYBOARD CLOSED → Войти (540,2185). The phone mask
      drops digits typed at full speed — type digit-by-digit with delays.
    The SMS code screen auto-focuses its first box: plain `input text` works.
    """
    if not (config.IIN and config.PHONE):
        raise RuntimeError("TSON_IIN / TSON_PHONE not set in .env — cannot re-login")
    print("[flow] LOGIN: filling ИИН + phone")
    _tap_scaled(driver, 540, 937)  # ИИН field
    time.sleep(1)
    _adb_shell("input", "text", config.IIN)
    time.sleep(1)
    _tap_scaled(driver, 540, 1067)  # phone field (keyboard open)
    time.sleep(1)
    for _ in range(16):  # clear any partial mask leftovers
        _adb_shell("input", "keyevent", "KEYCODE_DEL")
    phone_digits = config.PHONE.lstrip("+").removeprefix("7")  # mask wants 10 digits
    for digit in phone_digits:
        _adb_shell("input", "text", digit)
        time.sleep(0.3)
    _adb_shell("input", "keyevent", "KEYCODE_BACK")  # close keyboard
    time.sleep(1)

    for checkbox_y in (2000, 2063, 1937):  # layout shifts; retry ladder
        print(f"[flow] LOGIN: checkbox @y={checkbox_y} + Войти")
        _tap_scaled(driver, 68, checkbox_y)
        time.sleep(1)
        watermark = time.time()
        _tap_scaled(driver, 540, 2185)  # Войти
        try:
            code, _ = sms.wait_for_record(watermark, timeout=60)
        except TimeoutError:
            continue  # Войти was probably still disabled — try next y
        print(f"[flow] LOGIN: got sms code {code}")
        time.sleep(3)  # code screen renders; first box is auto-focused
        _adb_shell("input", "text", code)
        break
    else:
        raise RuntimeError("login SMS never arrived — Войти likely never enabled")

    # login verification is slow (~30-60s spinner) — wait for home
    deadline = time.time() + 120
    while time.time() < deadline:
        if _desc_present(driver, DESC_SPETSTSON_CARD):
            print("[flow] LOGIN: success — on home screen")
            return
        maybe_enter_pin(driver)  # in case a passcode setup screen appears
        time.sleep(3)
    raise RuntimeError("login: home screen did not appear within 120s after code")


def navigate_to_date_picker(driver, sms_mode: str = "relay") -> None:
    """Full path from the app home screen to Шаг 3. Needs one SMS code.

    sms_mode: "relay" — take the code from the SMS relay and type it;
              "manual" — the human types the code into the emulator, we just
              wait for Шаг 3 to appear.
    """
    print("[flow] step: home → СпецЦОН")
    _by_desc(driver, DESC_SPETSTSON_CARD, timeout=30)
    _click_until(
        driver,
        DESC_SPETSTSON_CARD,
        [DESC_SERVICES_TITLE, DESC_THEORY_SERVICE, "Заказ государственного"],
    )

    print("[flow] step: услуги → Запись на экзамен по теории")
    try:
        target = _by_desc(driver, DESC_THEORY_SERVICE, timeout=3)
    except TimeoutException:
        target = _scroll_to_desc(driver, DESC_THEORY_SERVICE)
    target.click()

    print("[flow] step: info sheet → чекбокс + Записаться")
    checkbox = _by_desc(driver, DESC_CONSENT_CHECKBOX)
    if checkbox.get_attribute("checked") != "true":
        # The a11y node spans the whole row incl. the «Правилами…» link, and a
        # center click hits the link (opens a browser). Tap the square on the
        # LEFT edge of the row instead.
        r = checkbox.rect
        x = r["x"] + min(r["height"], 80) // 2
        y = r["y"] + r["height"] // 2
        driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
        time.sleep(0.5)
        checkbox = _by_desc(driver, DESC_CONSENT_CHECKBOX)
        if checkbox.get_attribute("checked") != "true":
            raise TimeoutException("consent checkbox did not toggle")
    _by_desc(driver, DESC_BOOK_BUTTON).click()

    print("[flow] step: Шаг 1 — ввод номера заявки")
    field = WebDriverWait(driver, 15).until(
        lambda d: d.find_element(AppiumBy.CLASS_NAME, "android.widget.EditText")
    )
    field.click()
    field.send_keys(config.APPLICATION_NUMBER)
    requested_at = time.time()
    _by_desc(driver, DESC_CONTINUE).click()
    time.sleep(2)
    if _desc_present(driver, DESC_WRONG_APPLICATION):
        raise WrongApplicationError(
            f"заявка {config.APPLICATION_NUMBER} отклонена для текущего ИИН"
        )

    if sms_mode == "manual":
        print("[flow] step: Шаг 2 — ВВЕДИ SMS-КОД В ЭМУЛЯТОРЕ (жду до 3 минут)…")
        _by_desc(driver, DESC_DATE_FIELD, timeout=180)
    else:
        try:
            # Carrier delivery sometimes lags minutes and then flushes several
            # queued codes at once (seen live 2026-07-31), so the first code
            # newer than the request may be a stale one for an EXPIRED earlier
            # request. If the app rejects what we typed, wait for a strictly
            # newer code and retype.
            watermark = requested_at
            for attempt in range(3):
                code, received_at = sms.wait_for_record(watermark)
                print(f"[flow] step: Шаг 2 — got sms code {code} from relay")
                _type_sms_code(driver, code)
                try:
                    _by_desc(driver, DESC_DATE_FIELD, timeout=30)
                    break
                except TimeoutException:
                    if attempt == 2:
                        raise
                    print(f"[flow] code {code} rejected (stale?) — clearing boxes, waiting for a newer SMS")
                    _clear_sms_code(driver)
                    watermark = received_at
        except (TimeoutError, TimeoutException) as exc:
            # Relay failed — fall back to a human: alarm and wait.
            print(f"[flow] relay failed ({exc}) — falling back to manual entry")
            notify.sms_needed()
            try:
                _by_desc(driver, DESC_DATE_FIELD, timeout=180)
            except TimeoutException:
                raise SmsSilenceError(
                    "SMS code never arrived (relay wait "
                    f"{config.SMS_WAIT_TIMEOUT_SEC}s + manual 180s) — likely "
                    "carrier delaying gov4c codes, not a local failure"
                ) from exc
    print("[flow] on Шаг 3 (date/time selection)")


def _type_sms_code(driver, code: str) -> None:
    """Type the code into Шаг 2's six boxes.

    Verified live 2026-07-29: Appium send_keys AND press_keycode never reach
    the Flutter box widget. What works: tap the FIRST box to focus it, then
    inject the digits via `adb shell input text`. Box position is stable on
    the tson AVD (first box center ≈ 10.5% width, 32.8% height)."""
    size = driver.get_window_size()
    x = int(size["width"] * 0.105)
    y = int(size["height"] * 0.328)
    driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
    time.sleep(0.7)
    subprocess.run([config.ADB, "shell", "input", "text", code], check=False, timeout=15)
    time.sleep(0.5)


def _clear_sms_code(driver) -> None:
    """Erase a rejected code from Шаг 2's six boxes: focus the first box, then
    6× KEYCODE_DEL (67). Same adb-injection route as _type_sms_code — Appium
    key events never reach the Flutter widget."""
    size = driver.get_window_size()
    x = int(size["width"] * 0.105)
    y = int(size["height"] * 0.328)
    driver.execute_script("mobile: clickGesture", {"x": x, "y": y})
    time.sleep(0.7)
    for _ in range(6):
        subprocess.run([config.ADB, "shell", "input", "keyevent", "67"], check=False, timeout=15)
    time.sleep(0.5)


def check_slots(driver) -> tuple[bool, str, object]:
    """Open the date sheet (if not already open) and read it. Closes it when
    there are no slots; leaves it OPEN when there are.

    Returns (slots_available, details, screenshot_path_or_None).
    """
    config.DATA_DIR.mkdir(exist_ok=True)
    if not _desc_present(driver, DESC_DATE_SHEET_TITLE):
        _by_desc(driver, DESC_DATE_FIELD).click()
        _by_desc(driver, DESC_DATE_SHEET_TITLE)  # wait for the sheet
    time.sleep(2)  # let slot data load

    if _desc_present(driver, DESC_NO_SLOTS):
        available, details, png = False, "no slots (marker present)", None
    else:
        # Marker absent -> slots likely rendered. Capture evidence + extract
        # visible day numbers as positive confirmation.
        stamp = int(time.time())
        png = config.DATA_DIR / f"slots_{stamp}.png"
        driver.get_screenshot_as_file(str(png))
        src = driver.page_source
        (config.DATA_DIR / f"slots_{stamp}.xml").write_text(src)
        days = sorted(
            {int(d) for d in re.findall(r'content-desc="(\d{1,2})"', src) if 1 <= int(d) <= 31}
        )
        what = f"дни: {days}" if days else "дни не распознаны — смотри скриншот"
        available, details = True, f"marker absent, {what}"
        # Leave the sheet OPEN — checker/booking.py continues from here.
        return available, details, png

    _close_date_sheet(driver)
    return available, details, png


def _close_date_sheet(driver) -> None:
    """Tap the overlay behind the sheet (desc='Маска'); fall back to back key."""
    try:
        driver.find_element(
            AppiumBy.ANDROID_UIAUTOMATOR, _desc_selector(DESC_SHEET_OVERLAY)
        ).click()
    except NoSuchElementException:
        driver.back()
    # confirm it closed; one extra back if not
    time.sleep(1)
    if _desc_present(driver, DESC_DATE_SHEET_TITLE):
        driver.back()


def is_on_step3(driver) -> bool:
    """True if we're on Шаг 3 (in any state: empty fields, filled fields, or
    a sheet open on top)."""
    return (
        _desc_present(driver, "Шаг 3 из 4")
        or _desc_present(driver, DESC_DATE_FIELD)
        or _desc_present(driver, DESC_DATE_SHEET_TITLE)
    )


# --- date/time sheet parsing & selection (verified on live sheets 2026-07-30:
# both sheets share the title «Выберите дату регистрации»; dates are chips
# with desc «30 июля 2026», times are chips with desc «17:00») ---

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12,
}
DATE_CHIP_RE = re.compile(
    r"^(\d{1,2}) (января|февраля|марта|апреля|мая|июня|июля|августа|сентября"
    r"|октября|ноября|декабря) (\d{4})$"
)
TIME_CHIP_RE = re.compile(r"^\d{1,2}:\d{2}$")
DESC_TIME_FIELD = "Выберите время"
DESC_SELECT_BTN = "Выбрать"


def _sheet_descs(driver) -> list[str]:
    """content-desc values of nodes INSIDE the open bottom sheet. The sheet
    overlay is appended after the Шаг 3 scaffold in the tree, so everything
    after the title belongs to the sheet (this keeps the filled Дата field on
    Шаг 3 from being mistaken for an available-date chip)."""
    src = driver.page_source
    if DESC_DATE_SHEET_TITLE not in src:
        return []
    seg = src.split(DESC_DATE_SHEET_TITLE, 1)[1]
    return re.findall(r'content-desc="([^"]+)"', seg)


def read_available_dates(driver) -> list[tuple]:
    """Sheet must be open. Returns sorted [(datetime.date, chip_desc), …]."""
    import datetime as _dt

    out = {}
    for desc in _sheet_descs(driver):
        m = DATE_CHIP_RE.match(desc)
        if m:
            day, month, year = int(m.group(1)), MONTHS_RU[m.group(2)], int(m.group(3))
            out[_dt.date(year, month, day)] = desc
    return sorted(out.items())


def read_available_times(driver) -> list[str]:
    """Time sheet must be open. Returns times ascending, e.g. ['9:00','17:00']."""
    times = {t for t in _sheet_descs(driver) if TIME_CHIP_RE.match(t)}
    return sorted(times, key=lambda t: (int(t.split(":")[0]), int(t.split(":")[1])))


def _wait_sheet_closed(driver, timeout=10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _desc_present(driver, DESC_DATE_SHEET_TITLE):
            return
        time.sleep(0.5)
    raise TimeoutException("bottom sheet did not close")


def pick_date(driver, chip_desc: str) -> None:
    """In the open date sheet: tap the date chip, then «Выбрать»."""
    _by_desc(driver, chip_desc).click()
    time.sleep(0.5)
    _by_desc(driver, DESC_SELECT_BTN).click()
    _wait_sheet_closed(driver)


def open_time_sheet_and_read(driver) -> list[str]:
    """From Шаг 3 (date already picked): open the Время sheet, return times."""
    _by_desc(driver, DESC_TIME_FIELD).click()
    deadline = time.time() + 10
    while time.time() < deadline:
        times = read_available_times(driver)
        if times:
            return times
        time.sleep(0.5)
    return []


def pick_time(driver, t: str) -> None:
    """In the open time sheet: tap the exact time chip, then «Выбрать»."""
    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().description("{t}")'
    ).click()
    time.sleep(0.5)
    _by_desc(driver, DESC_SELECT_BTN).click()
    _wait_sheet_closed(driver)


def close_any_sheet(driver) -> None:
    if _desc_present(driver, DESC_DATE_SHEET_TITLE):
        _close_date_sheet(driver)


def reopen_date_sheet(driver, current_field_desc: str) -> None:
    """Re-open the date sheet from Шаг 3. If a date is already selected the
    field's desc is that date; otherwise it's the placeholder."""
    target = current_field_desc if _desc_present(driver, current_field_desc) else DESC_DATE_FIELD
    _by_desc(driver, target).click()
    _by_desc(driver, DESC_DATE_SHEET_TITLE, timeout=10)


def tap_continue(driver) -> None:
    _by_desc(driver, DESC_CONTINUE).click()


# --- Шаг 4 из 4: final confirmation. Path observed on a real booking
# (2026-08-05): «Проверьте данные» (ИИН, день, время, отдел) -> «Подтвердить»
# -> dialog «Забронировать?» -> «Далее» -> «Бронирование успешно!».
# The booking CANNOT be cancelled afterwards (in-app warning). ---

DESC_STEP4_TITLE = "Проверьте данные"
DESC_CONFIRM = "Подтвердить"
DESC_CONFIRM_DIALOG = "Забронировать?"
DESC_NEXT = "Далее"
DESC_BOOKED = "Бронирование успешно"


def _wait_any(driver, descs: list[str], timeout: float) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for d in descs:
            if _desc_present(driver, d):
                return d
        maybe_enter_pin(driver)
        time.sleep(0.5)
    return None


def confirm_booking(driver) -> None:
    """From Шаг 4 to the success screen. Each tap is retried only while its
    own screen is still showing (a Flutter tap that didn't land); the server
    round-trips get generous timeouts. Raises if success never shows."""
    if not _wait_any(driver, [DESC_STEP4_TITLE, DESC_CONFIRM], 20):
        raise TimeoutException("Шаг 4 «Проверьте данные» did not appear")

    for _ in range(3):
        _by_desc(driver, DESC_CONFIRM).click()
        seen = _wait_any(driver, [DESC_CONFIRM_DIALOG, DESC_BOOKED], 20)
        if seen:
            break
        if not _desc_present(driver, DESC_CONFIRM):
            raise TimeoutException("left Шаг 4 but neither «Забронировать?» nor success appeared")
    else:
        raise TimeoutException("«Подтвердить» never opened the confirmation dialog")

    if seen == DESC_CONFIRM_DIALOG:
        for _ in range(3):
            _by_desc(driver, DESC_NEXT).click()
            if _wait_any(driver, [DESC_BOOKED], 60):
                break
            if not _desc_present(driver, DESC_CONFIRM_DIALOG):
                raise TimeoutException("dialog closed but «Бронирование успешно» never appeared")
        else:
            raise TimeoutException("«Далее» never led to the success screen")
    print("[flow] Бронирование успешно!")
