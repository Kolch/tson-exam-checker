# Decisions

Newest first. One entry per decision: what, why, and what it costs.

## 2026-11-09 — First public version

- **Booking defaults to `button`.** A booking can't be cancelled, so by
  default nothing is booked without the person pressing «Забронировать» in
  Telegram. `auto` (earliest slot at least `TSON_MIN_LEAD_H` away) and
  `alert` remain settings. Cost: a slot can be lost while nobody presses.
- **Шаг 4 is confirmed by plain code** (`flow.confirm_booking`), from the path
  observed on a real booking: «Проверьте данные» → «Подтвердить» →
  «Забронировать?» → «Далее» → «Бронирование успешно!». If it fails, the
  person gets a loud alert to check and book on their phone; checks pause.
- **No unattended AI agent.** The private prototype spawned a coding agent
  with all permissions skipped to self-heal and to finish bookings. The
  public version doesn't: when a check keeps failing, the person gets one
  loud Telegram alert and runs Claude Code or Codex themselves on
  `docs/troubleshooting.md`. Cost: fixes wait for a human.
- **Agent-led setup.** `AGENTS.md` (read by Codex; `CLAUDE.md` imports it) +
  `docs/SETUP.md` playbook + `checker.doctor`. Steps that need a person
  (APK download, login, Telegram bot, phone settings, macOS permissions) are
  marked HUMAN.
- **macOS on Apple Silicon only.** launchd, `chat.db`, `caffeinate` and the
  arm64 Play Store emulator image are Mac-specific; Linux/Windows would need
  a different scheduler and SMS path.
- **Three SMS sources**: `chatdb` (iPhone via Messages forwarding), `webhook`
  (Android forwarder app or iPhone Shortcut, protected by
  `SMS_WEBHOOK_TOKEN`), `manual` (first test run only).
- **Default cadence 10–20 min**, plus 23:59:50 and 00:05. Each check costs
  one SMS from a government service; the prototype used 5–10 min.
- **Docs language**: README in Russian for people in Kazakhstan; agent docs
  and code in English; Telegram messages in Russian.
