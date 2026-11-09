"""Alerting via Telegram only: loud for slots and incidents, silent for the
running check log."""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

from checker import config


def telegram(message: str, photo: Path | None = None, silent: bool = False) -> None:
    """Send a Telegram message. silent=True delivers without a push sound —
    used for the check log; only slot alerts are loud."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print(f"[notify] telegram not configured; message was: {message}")
        return
    base = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
    try:
        if photo and photo.exists():
            args = ["curl", "-s", "--max-time", "20", f"{base}/sendPhoto",
                    "-F", f"chat_id={config.TELEGRAM_CHAT_ID}",
                    "-F", f"caption={message}",
                    "-F", f"photo=@{photo}"]
            if silent:
                args += ["-F", "disable_notification=true"]
            subprocess.run(args, check=False, capture_output=True)
        else:
            payload = json.dumps(
                {"chat_id": config.TELEGRAM_CHAT_ID, "text": message,
                 "disable_notification": silent}
            ).encode()
            req = urllib.request.Request(
                f"{base}/sendMessage", data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
    except OSError as exc:
        print(f"[notify] telegram failed: {exc}")


def log(message: str) -> None:
    """Silent check log — no push sound, just history in the chat."""
    telegram(message, silent=True)


def sms_needed() -> None:
    """Relay had no code; human fallback. Console only — if the check then
    fails, the error log covers it."""
    print("[notify] SMS-код не пришёл вовремя — жду ручной ввод 3 минуты")
