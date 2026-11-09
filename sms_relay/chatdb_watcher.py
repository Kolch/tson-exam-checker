"""SMS_SOURCE=chatdb: poll the macOS Messages database for the code (iPhone
owners — the most reliable path, see docs/sms.md).

Requires: iPhone Settings -> Apps -> Messages -> Text Message Forwarding ->
enable this Mac, AND Full Disk Access for the terminal/python running this
(System Settings -> Privacy & Security -> Full Disk Access).

Run:  python -m sms_relay.chatdb_watcher
Writes the same data/latest_sms.json the checker reads, so it is
interchangeable with the webhook server.py.
"""

import re
import sqlite3
import time
from pathlib import Path

from sms_relay.server import store  # reuse code extraction + persistence

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
POLL_SEC = 2
APPLE_EPOCH_OFFSET = 978307200  # 2001-01-01 in unix time

# Only react to messages that look like a verification code. Adjust the filter
# once the real ЦОН sender/text is known (e.g. sender id or a keyword).
CODE_RE = re.compile(r"\b\d{6}\b")


def _decode_attributed_body(blob: bytes) -> str:
    """Newer macOS often leaves message.text NULL and stores the content in the
    attributedBody typedstream blob. Crude but effective: pull printable runs."""
    if not blob:
        return ""
    marker = blob.find(b"NSString")
    chunk = blob[marker:] if marker != -1 else blob
    # Lossy decode is fine: we only need the 6-digit code to survive.
    return chunk.decode("utf-8", errors="ignore")


def _fetch_since(conn: sqlite3.Connection, last_date_ns: int):
    query = """
        SELECT m.date, m.text, m.attributedBody, h.id AS sender
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.is_from_me = 0 AND m.date > ?
        ORDER BY m.date ASC
    """
    return conn.execute(query, (last_date_ns,)).fetchall()


def main() -> None:
    if not CHAT_DB.exists():
        raise SystemExit(f"{CHAT_DB} not found — is Messages set up on this Mac?")
    try:
        conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"Cannot open chat.db ({exc}). Grant Full Disk Access to your "
            "terminal app and restart it."
        ) from exc

    last_date_ns = int((time.time() - APPLE_EPOCH_OFFSET) * 1_000_000_000)
    print(f"[chatdb] watching {CHAT_DB} for incoming 6-digit codes…")
    while True:
        for date_ns, text, attributed, sender in _fetch_since(conn, last_date_ns):
            last_date_ns = max(last_date_ns, date_ns)
            body = text or _decode_attributed_body(attributed)
            if CODE_RE.search(body or ""):
                record = store(body)
                print(f"[chatdb] code received from {sender} (stored: {bool(record['code'])})")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
