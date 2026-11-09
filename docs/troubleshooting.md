# Troubleshooting (for the coding agent)

Start with:

```bash
.venv/bin/python -m checker.doctor
tail -n 80 data/cycle.log
ls -t data/fail_*.png | head -3      # what the screen showed when a check failed
```

Then one real check in the foreground, with the scheduled job unable to
interfere (the cycle holds a lock):

```bash
.venv/bin/python -m checker.cycle force
```

`check done: available=…` in its output means healthy.

## Telegram says…

| Message | Meaning | Fix |
|---|---|---|
| 🚨 «приложение разлогинилось» | the ~7-day session expired and auto-login is off or failed | stop the headless emulator (`adb emu kill`), run `./scripts/start_emulator.sh`, the person logs in (ИИН, phone, SMS, passcode). Checks resume by themselves. Offer to set `TSON_IIN`/`TSON_PHONE` for auto-login |
| ⚠️ «SMS-коды не доходят» | no code within 15 min | external delays are common and recover by themselves. If it persists: phone forwarding still on? Full Disk Access for the venv Python (`chatdb`)? Phone app alive and same network (`webhook`)? |
| ⚠️ «некорректный ИИН/номер заявки» | Шаг 1 rejected the заявка | check `TSON_APPLICATION_NUMBER` and that the app is logged in as the right person; otherwise a government-side outage, which passes |
| ⚠️ «чекер сломался» | the check fails even after restarting Appium and rebooting the emulator | see below |
| 🚨 «даты не распознаны» | the no-slots text is gone but no date chips were parsed | likely an app update changed the date sheet; checks are paused. The person should look at the app on their phone right away |

## Common causes of "broken"

- **App update changed texts or screens.** Navigate to the failing screen in
  the emulator (start it with a window), run `./scripts/dump_ui.sh`, compare
  the `content-desc` values with the constants in `checker/flow.py`, fix
  them, and verify with `checker.cycle force`.
- **Stale accessibility tree.** After about a week of emulator uptime the
  a11y tree can freeze on an old screen; the cycle already reboots the guest
  once. If it persists: `adb emu kill`, then let the next cycle cold-boot.
- **Appium not starting.** `./scripts/start_appium.sh` in a terminal shows the
  error; `appium driver doctor uiautomator2` checks Java/Android variables.
- **Emulator doesn't boot.** Disk full? Run
  `"$ANDROID_HOME/emulator/emulator" -avd tson` in the foreground to see the
  error; the snapshot can be wiped with `-wipe-data` (the person must log in
  again).
- **Full Disk Access under launchd.** In `chatdb` mode the daemon's Python,
  not the terminal, reads `chat.db`; the doctor prints the path that needs
  access.
- **Mac slept.** launchd doesn't run jobs while the Mac sleeps; see SETUP
  phase 9.

## Resetting state

- `data/next_run.json` with `paused: true` stops checks (after a booking or
  an unclear slot screen). `/start` in Telegram or deleting the file resumes.
- `data/slots_seen.json` suppresses repeated alerts for the same slots;
  delete it to be alerted again.
- Incident flags `data/{logged_out,sms_silence,wrong_application,broken}.json`
  clear themselves after the next successful check.
