# Setup playbook (for the coding agent)

Work through the phases in order. Each phase ends with a check; don't move on
until it passes. Steps marked **HUMAN** are for the person: explain exactly
what to tap or type, wait until they say it's done, then verify it yourself.
Talk to the person in their language (usually Russian).

The doctor is the source of truth for what's missing:

```bash
python3 -m checker.doctor          # before the venv exists
.venv/bin/python -m checker.doctor # afterwards
```

## Phase 0 — Talk first

Tell the person, in a few sentences, what will happen: an Android emulator
with the ЦОН app runs on their Mac and checks for free slots every 10–20
minutes; alerts come to Telegram; booking happens only when they press the
button (default). Then confirm they have:

- a **Mac with Apple Silicon** (M1 or newer), ~15 GB free, and that it can stay
  **plugged in and awake** while checking runs (days or weeks);
- a **номер заявки**: from the ЦОН / eGov service «Первичное получение ВУ»
  (they get it after submitting the application; it's on the application
  status page). Without it booking is impossible — stop here if they don't
  have one;
- their **phone number registered in the БМГ** (база мобильных граждан),
  which receives the SMS codes, and whether the phone is an **iPhone or
  Android**;
- **Telegram**.

Ask which booking mode they want and explain that a booking can't be
cancelled: `button` (recommended: alert + «Забронировать» button), `auto`
(books the earliest slot at least N hours away without asking), `alert`
(alert only, they book on their phone).

## Phase 1 — Toolchain

```bash
./scripts/setup_env.sh
```

Installs Java 21, Python 3.13, Node, Android SDK + emulator + the `tson` AVD,
Appium 3 with the uiautomator2 driver, and the project venv. First run
downloads ~5 GB and takes 10–30 minutes; warn the person. If Homebrew is
missing, the person installs it from https://brew.sh (HUMAN: it asks for the
Mac password).

Check: doctor shows the "Mac and toolchain" section all green.

## Phase 2 — Emulator

```bash
./scripts/start_emulator.sh
```

A window with an Android phone appears. First boot takes a few minutes.

Check: `adb devices` lists `emulator-5554` as `device`.

## Phase 3 — Install the ЦОН app

The app is `kz.gov4c.citizen` («ЦОН», by GOVERNMENT FOR CITIZENS).

**HUMAN:** download the APK (or XAPK) on the Mac, e.g. from APKPure
(search «ЦОН kz.gov4c.citizen») or RuStore, and tell you where the file is
(usually `~/Downloads`). Play Store inside the emulator only works if their
Google account's country is Kazakhstan, so the APK is simpler.

Then you install it:

```bash
source scripts/_env.sh
adb install -r ~/Downloads/<file>.apk
# XAPK / split APKs: unzip into an empty temp folder, then
# adb install-multiple <folder>/*.apk
```

Check: doctor shows «ЦОН app installed».

## Phase 4 — Log in (HUMAN)

In the emulator window the person opens the ЦОН app and logs in as usual:
ИИН + phone number + SMS code, then creates the 4-digit **код доступа**
(passcode). The Mac keyboard works in the emulator. Ask them to remember the
passcode; it goes into `.env`.

Check: `./scripts/dump_ui.sh`, then look for `content-desc="СпецЦОН"` in the
newest `data/ui_*.xml`, or view the screenshot.

## Phase 5 — Create .env

```bash
cp .env.example .env
```

Fill `TSON_APPLICATION_NUMBER`, `TSON_APP_PIN`, `BOOKING_MODE` (from phase
0). The person may type values into `.env` themselves (`open -e .env`) or
give them to you; either way, never echo them back.

Optional, recommended: **automatic re-login**. The app session expires about
every 7 days; with `TSON_IIN` and `TSON_PHONE` (`+77XXXXXXXXX`) set, the
checker logs in again by itself. Explain that these stay only in `.env` on
this Mac, and let the person decide.

## Phase 6 — Telegram

1. **HUMAN:** in Telegram open @BotFather → `/newbot` → any name and a
   username ending in `bot` → BotFather replies with a token. Put it into
   `TELEGRAM_BOT_TOKEN` (the person pastes it into `.env`, or gives it to
   you).
2. **HUMAN:** open the new bot and press **Start** (send `/start`).
3. You read the chat id and put it into `TELEGRAM_CHAT_ID`:

   ```bash
   T=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)
   curl -s "https://api.telegram.org/bot$T/getUpdates" | python3 -c \
     'import json,sys; r=json.load(sys.stdin)["result"]; print(r[-1]["message"]["chat"]["id"] if r else "send /start to the bot first")'
   ```

Check: `.venv/bin/python -m checker.doctor --telegram-test`; the person
confirms the test message arrived.

## Phase 7 — SMS codes

Read [sms.md](sms.md) and pick the path with the person:

- **iPhone → `SMS_SOURCE=chatdb`** (most reliable). HUMAN: enable Text
  Message Forwarding to this Mac; grant Full Disk Access to the terminal app
  (and later to the venv Python, the doctor prints its path).
- **Android → `SMS_SOURCE=webhook`**. You generate `SMS_WEBHOOK_TOKEN`
  (`openssl rand -hex 16`) and get the URL from
  `.venv/bin/python -m checker.doctor --webhook-url`. HUMAN: installs an
  SMS-forwarder app and enters that URL. macOS may ask to allow incoming
  connections for Python: allow.
- iPhone without Messages forwarding → `webhook` with a Shortcuts
  automation (less reliable).

Check: doctor's SMS section is green. For `webhook`, also start
`.venv/bin/python -m sms_relay.server` in the background and ask the person
to send an SMS containing `123456` to their phone from another phone. Then
`data/latest_sms.json` should show the code. Delete that file afterwards.

## Phase 8 — First real check

Close nothing: the emulator stays running. Then:

```bash
./scripts/start_appium.sh &            # or in a second terminal
.venv/bin/python -m checker.validate_path
```

This walks the real flow once (one real SMS code) and never books. Expect
`RESULT: slots_available=False — no slots (marker present)` (or `True` if
slots happen to be open). If it fails:

- read the error and [troubleshooting.md](troubleshooting.md);
- if a screen's texts changed (app update), capture it with
  `./scripts/dump_ui.sh` and fix the constants in `checker/flow.py`;
- if the SMS never arrives, re-check phase 7, or run with `--manual` and let
  the person type the code into the emulator window.

## Phase 9 — Unattended mode

1. **HUMAN:** keep the Mac plugged in and stop it from sleeping: System
   Settings → Battery (or Energy) → on power adapter, prevent automatic
   sleeping when the display is off. The display may turn off; the Mac must
   not sleep.
2. `chatdb` only, **HUMAN:** grant Full Disk Access to the Python path the
   doctor prints (System Settings → Privacy & Security → Full Disk Access →
   `+` → Cmd+Shift+G → paste the path).
3. Stop the foreground Appium (`pkill -f appium`), then install the daemon:

   ```bash
   ./scripts/install_daemon.sh
   ```

The emulator can stay open with its window or be closed; the daemon boots
it headless when needed.

Check: within ~5 minutes `data/cycle.log` shows `check done:` and the
person's Telegram gets a silent log line; `/status` in the bot answers.
Doctor is fully green.

## Phase 10 — Hand-off

Tell the person, briefly:

- alerts: 🚨 means slots (press the button to book), ⚠️/❌ means something
  needs attention, silent lines are the normal check log;
- Telegram commands: `/status`, `/stop`, `/start`, `/check`;
- the Mac must stay plugged in and awake; checking pauses after a booking;
- if something breaks: open Claude Code or Codex in this folder and say
  «чекер сломался»;
- to remove everything: `./scripts/install_daemon.sh remove`, then delete the
  folder and the AVD (`avdmanager delete avd -n tson`).
