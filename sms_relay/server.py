"""SMS webhook: the phone POSTs each incoming SMS here; the 6-digit code is
extracted and persisted to data/latest_sms.json for the checker.

Senders (see docs/sms.md):
  - iPhone Shortcuts automation  -> POST {"text": "<sms>"}
  - Android SMS-forwarder app    -> POST JSON with the text under "text"
    (or "message"/"body"/"msg"), or the raw SMS text as the body

Run:  python -m sms_relay.server   (listens on 0.0.0.0:SMS_WEBHOOK_PORT)
Auth: SMS_WEBHOOK_TOKEN must match ?token=... in the URL or an X-Token header.
Debug: GET /health -> ok
"""

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from checker import config

HOST = "0.0.0.0"
CODE_RE = re.compile(r"\b(\d{6})\b")
TEXT_KEYS = ("text", "message", "body", "msg")


def store(raw_text: str) -> dict:
    """Persist the code if the text has one. Texts without a code are NOT
    stored, so an unrelated SMS can't wipe a fresh code."""
    match = CODE_RE.search(raw_text or "")
    record = {
        "received_at": time.time(),
        "code": match.group(1) if match else None,
    }
    if record["code"]:
        config.SMS_FILE.parent.mkdir(exist_ok=True)
        config.SMS_FILE.write_text(json.dumps(record, indent=2))
    return record


def _extract_text(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw  # plain-text body
    if isinstance(payload, dict):
        for key in TEXT_KEYS:
            if isinstance(payload.get(key), str):
                return payload[key]
    return raw


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, query: dict) -> bool:
        token = config.SMS_WEBHOOK_TOKEN
        if not token:
            return True
        given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
        return given == token

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path != "/sms":
            return self._reply(404, {"error": "unknown path"})
        if not self._authorized(parse_qs(url.query)):
            return self._reply(403, {"error": "bad token"})
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        record = store(_extract_text(raw))
        print(f"[sms_relay] received sms, code={'yes' if record['code'] else 'no'}")
        self._reply(200, {"ok": True, "code_found": bool(record["code"])})

    def do_GET(self):
        if urlsplit(self.path).path == "/health":
            return self._reply(200, {"ok": True})
        self._reply(404, {"error": "unknown path"})

    def log_message(self, *args):  # quieter default logging
        pass


def main():
    if not config.SMS_WEBHOOK_TOKEN:
        print("[sms_relay] WARNING: SMS_WEBHOOK_TOKEN is empty — anyone on your network can post codes")
    server = ThreadingHTTPServer((HOST, config.SMS_WEBHOOK_PORT), Handler)
    print(f"[sms_relay] listening on http://{HOST}:{config.SMS_WEBHOOK_PORT}  (POST /sms)")
    print(f"[sms_relay] codes are written to {config.SMS_FILE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
