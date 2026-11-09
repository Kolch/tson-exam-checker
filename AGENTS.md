# tson-exam-checker — instructions for coding agents

You are a coding agent (Claude Code, Codex, or similar) in this repository.
The person you are helping wants an automatic checker for free slots on the
**theory driving exam** in the Kazakhstan **ЦОН** app (`kz.gov4c.citizen`):
slots appear rarely and are gone within minutes.

## What the person probably wants from you

- **"Set it up" / "настрой"** → follow [docs/SETUP.md](docs/SETUP.md) phase by
  phase. Do everything you can yourself; stop only for the steps marked
  HUMAN. After each phase run the doctor and fix what it reports.
- **"It's broken" / Telegram says the checker is broken / logged out** →
  [docs/troubleshooting.md](docs/troubleshooting.md).
- **"Pause / resume / uninstall"** → Telegram `/stop` `/start`, or
  `./scripts/install_daemon.sh remove`.

Talk to the person in their language (usually Russian), briefly and
concretely. Many users are not developers: explain what you are about to do
and why, one step at a time, and never assume they know Terminal.

## How it works

1. **Android emulator + ЦОН app.** The app is mobile-only, so it runs in an
   Android emulator (AVD `tson`, Pixel 7, android-35 Play Store arm64 image)
   on the person's Mac, logged in once by the person.
2. **Checker** (`checker/`, Python + Appium 3 / UiAutomator2). One check =
   restart the app → PIN → СпецЦОН → «Запись на экзамен по теории» → номер
   заявки → SMS code → Шаг 3 → open the date sheet. «Все записи на этот месяц
   уже заняты» = no slots. The app caches the date sheet within a session,
   so every check is a full fresh flow and costs one SMS code.
3. **SMS relay** (`sms_relay/`). Шаг 2 needs the 6-digit code sent to the
   person's phone. `chatdb` (iPhone → Mac Messages) or `webhook` (the phone
   POSTs SMS to the Mac) writes `data/latest_sms.json`. See
   [docs/sms.md](docs/sms.md).
4. **Daemon** (`checker/cycle.py` via launchd, `scripts/install_daemon.sh`).
   Every 2 min a gate decides whether a check is due (random
   `CHECK_MIN_MIN`–`CHECK_MAX_MIN`), plus a precise run at 23:59:50 and 00:05.
   Each cycle boots the emulator/Appium if needed, runs one check, exits.
5. **Booking** (`checker/booking.py`, `BOOKING_MODE`): `button` (default,
   Telegram «Забронировать» button), `auto`, or `alert`. Шаг 4 is confirmed
   deterministically in `flow.confirm_booking`.
6. **Telegram** (`checker/notify.py`, `checker/ctlbot.py`): loud alerts for
   slots and incidents, a silent log of checks, and `/status` `/stop`
   `/start` `/check` commands.

The app is **Flutter**: all visible text is in `content-desc`, `text` is
empty. All selectors match Russian strings copied verbatim from the app;
they live as constants in `checker/flow.py`.

## Layout

- `checker/config.py` — every setting, read from `.env` (template:
  `.env.example`)
- `checker/flow.py` — screen-by-screen navigation and all UI strings
- `checker/session.py` — Appium session + one full check
- `checker/booking.py` — what to do when slots appear
- `checker/cycle.py` — the unattended cycle (launchd entry point)
- `checker/ctlbot.py` — Telegram control bot
- `checker/doctor.py` — preflight checks
- `checker/validate_path.py` — first real run in the foreground
- `sms_relay/` — `chatdb_watcher.py`, `server.py` (webhook)
- `scripts/` — `setup_env.sh`, `start_emulator.sh`, `start_appium.sh`,
  `dump_ui.sh`, `install_daemon.sh`; `_env.sh` is shared by all of them
- `docs/` — setup, SMS, flow, troubleshooting, decisions; `docs/screens/`
  holds reference screenshots of the real flow
- `data/` — runtime state, logs and screenshots (gitignored)

## Rules

- **Secrets.** `.env` holds the номер заявки, PIN, ИИН, phone number,
  Telegram token and webhook token. Never print, paste, log or commit its
  contents; read a single value only when a step needs it. If the person
  pastes a secret into the chat, write it into `.env` and don't repeat it.
- **Personal data.** Never commit `data/` or any screenshot taken on the
  person's emulator (they can show the ИИН and name).
- **Bookings are final.** Never book or press «Подтвердить» yourself outside
  the configured `BOOKING_MODE`, and never change `BOOKING_MODE` without the
  person saying so.
- **Be polite to the service.** Don't set `CHECK_MIN_MIN` below 5: every
  check sends a real SMS, and this is a government service.
- **HUMAN-only steps** (you cannot and should not do them): downloading the
  APK, logging into the app, setting the passcode, creating the Telegram bot,
  enabling SMS forwarding on the phone, granting Full Disk Access, changing
  sleep settings, entering the номер заявки.
- **Changing selectors.** Before editing a string in `checker/flow.py`,
  capture the real screen with `./scripts/dump_ui.sh` and copy the
  `content-desc` exactly (watch «ё», casing, non-breaking spaces).
- Telegram messages and other user-facing strings are in Russian.
- Record design decisions in [docs/DECISIONS.md](docs/DECISIONS.md).

## Commands

```bash
./scripts/setup_env.sh                          # toolchain, SDK, AVD, Appium, venv
.venv/bin/python -m checker.doctor              # what's missing (exit 0 = ready)
./scripts/start_emulator.sh [--headless]        # boot the emulator
./scripts/start_appium.sh                       # Appium on :4723
.venv/bin/python -m checker.validate_path       # one real check in the foreground
.venv/bin/python -m checker.cycle force         # one daemon cycle now
./scripts/install_daemon.sh [remove]            # unattended mode on/off
./scripts/dump_ui.sh                            # UI tree + screenshot into data/
tail -f data/cycle.log                          # daemon log
```
