# Getting SMS codes to the checker

Every check walks the booking flow, and Шаг 2 asks for a fresh 6-digit code
that ЦОН sends by SMS to the person's phone. Whatever the source, the code
ends up in `data/latest_sms.json`, and `checker/sms.py` takes the first code
that arrived **after** the request (stale codes are never reused).

| Phone | `SMS_SOURCE` | How | Reliability |
|---|---|---|---|
| iPhone | `chatdb` | Text Message Forwarding → Mac Messages → `sms_relay/chatdb_watcher.py` reads `~/Library/Messages/chat.db` | best |
| Android | `webhook` | SMS-forwarder app → `POST http://<mac>:8777/sms?token=…` → `sms_relay/server.py` | good |
| iPhone | `webhook` | Shortcuts automation → same webhook | flaky when the phone is locked |
| any | `manual` | the person types the code into the emulator window | first test run only |

The daemon starts the right relay for each check by itself; you never need
to keep one running.

## iPhone: Text Message Forwarding (`chatdb`)

1. iPhone and Mac on the same Apple Account, iMessage on.
2. iPhone: **Settings → Apps → Messages → Text Message Forwarding** → enable
   this Mac.
3. Mac: **System Settings → Privacy & Security → Full Disk Access** → add the
   terminal app you run commands from (restart it), and the venv Python that
   the daemon uses: the doctor prints its exact path (for Homebrew Python it
   is a `Python.app` inside the framework; use `+`, then Cmd+Shift+G to paste
   the path).
4. Check: `.venv/bin/python -m checker.doctor` → «chat.db readable» and «SMS
   from the iPhone reach this Mac» are green (the second one needs at least
   one SMS received in the last two weeks).

The Mac must be awake when the code arrives; the daemon keeps it awake
during a check.

## Android: SMS-forwarder app (`webhook`)

1. In `.env`: `SMS_SOURCE=webhook`, `SMS_WEBHOOK_TOKEN=$(openssl rand -hex 16)`.
2. `.venv/bin/python -m checker.doctor --webhook-url` prints the URL, e.g.
   `http://192.168.1.23:8777/sms?token=…`.
3. On the phone install an app that forwards incoming SMS to a URL (for
   example the open-source «Incoming SMS to URL forwarder», Google Play /
   F-Droid). Add a rule: any sender (or the ЦОН sender once you know it),
   URL = the one from step 2, method POST, JSON body with the SMS text in a
   `text` field (`{"text":"%text%"}` in that app). Disable battery
   optimisation for the app so Android doesn't kill it.
4. The phone and the Mac must be on the same Wi-Fi, or both on Tailscale (use
   the Mac's Tailscale IP in the URL) if the phone leaves home.
5. The server accepts the text as JSON (`text`, `message`, `body` or `msg`) or
   as a plain body, and the token as `?token=` or an `X-Token` header.
6. Check: run `.venv/bin/python -m sms_relay.server`, send an SMS with
   `123456` to the phone from another phone, and `data/latest_sms.json`
   shows the code. Locally: `curl -X POST "localhost:8777/sms?token=…" -d '{"text":"код 123456"}'`.

macOS asks once whether Python may accept incoming connections: allow.

## iPhone: Shortcuts automation (`webhook`)

Use this only if Messages forwarding isn't possible.

1. Same `.env` and URL as for Android.
2. iPhone → Shortcuts → **Automation → + → Message**: «Message Contains» a
   stable phrase from the ЦОН SMS (not the code; look at one real SMS first),
   **Run Immediately**.
3. Action **Get Contents of URL**: the URL from the doctor, method POST,
   request body JSON, field `text` = Shortcut Input → Content.

Known issue: some iOS versions silently skip automations while the phone is
locked, and the Shortcut fails silently when the Mac is unreachable.

## Notes

- Any 6-digit number in an incoming SMS is taken as a candidate code. A wrong
  one is harmless: the app rejects it and the checker waits for a newer code
  (up to 3 tries).
- Carrier delivery of these codes sometimes lags ~15 minutes and then several
  arrive at once; the retry logic in `checker/flow.py` handles it.
- The relay stores only the code and its arrival time, not the SMS text.
