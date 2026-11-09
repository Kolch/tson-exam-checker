# The booking flow in the ЦОН app

Reference screenshots in [screens/](screens/) were taken on an iPhone; the
checker drives the Android version of the same app, so positions differ but
texts match. The app is Flutter: on Android every text is exposed as
`content-desc`, and all selectors are the Russian strings in
`checker/flow.py`.

| # | Screen | What the checker does |
|---|---|---|
| 0 | Passcode «Введите код доступа» (may appear on start or after tapping СпецЦОН) | types `TSON_APP_PIN` on the digit keys |
| 1 | Home ([1-home](screens/1-home.png)) | taps the **СпецЦОН** card |
| 2 | «Услуги СпецЦОН» ([2-services](screens/2-services.png)) | taps **«Запись на экзамен по теории»** (scrolls if needed) |
| 3 | Info sheet ([3-info-sheet](screens/3-info-sheet.png)) | ticks «Подтверждаю…» by tapping the left edge of the row (the row also holds a link), then **«Записаться»** |
| 4 | Шаг 1 из 4 ([4-step1-application](screens/4-step1-application.png)) | types the номер заявки, taps **«Продолжить»**; this sends the SMS |
| 5 | Шаг 2 из 4 ([5-step2-sms](screens/5-step2-sms.png)) | taps the first of 6 boxes, types the code via `adb shell input text` (Appium keys don't reach these boxes) |
| 6 | Шаг 3 из 4 ([6-step3-date](screens/6-step3-date.png)) | region and office are pre-filled from the application; taps **«Дата»** |
| 7 | Date sheet «Выберите дату регистрации» ([7-no-slots](screens/7-no-slots.png)) | **«Все записи на этот месяц уже заняты»** = no slots. Otherwise dates are chips like «1 сентября 2026» |
| 8 | Time sheet (same title) | time chips like «09:00», then **«Выбрать»** |
| 9 | Шаг 4 из 4 «Проверьте данные» | shows ИИН, date, time, office → **«Подтвердить»** |
| 10 | Dialog «Забронировать?» | **«Далее»** |
| 11 | «Бронирование успешно!» | done. The booking **cannot be cancelled** |

Steps 9–11 were observed on a real booking (no screenshot kept: they show
personal data).

## Behaviour that shaped the code

- **The date sheet is cached within a session.** Reopening «Дата» shows stale
  data, so every check restarts the app and walks the whole flow: one check
  = one SMS code.
- **New dates often open at midnight**, hence the extra runs at 23:59:50 and
  00:05.
- **Шаг 3 expires** by itself after ~8–30 minutes; irrelevant for checks
  (each one is fresh), relevant for the «Забронировать» button: if the
  session died while waiting, the checker walks the flow again (new SMS).
- **Login session expires ~7 days** after logging in: the app shows «Вход в
  ЦОН». With `TSON_IIN`/`TSON_PHONE` set, `flow.login` logs in again by
  coordinates (the accessibility tree is stale on that screen), types the
  phone digit by digit (the input mask drops fast typing), and handles the
  passcode re-creation screens.
- **A valid заявка is sometimes rejected** («Возможно вы зашли по
  некорректному ИИН…») during outages on the government side; the checker
  alerts once and keeps checking.
