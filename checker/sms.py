"""Read the verification code produced by sms_relay (same machine, via file)."""

import json
import time

from checker import config


def wait_for_record(after: float, timeout: float = config.SMS_WAIT_TIMEOUT_SEC) -> tuple[str, float]:
    """Block until a 6-digit code that arrived AFTER `after` shows up.

    Returns (code, received_at). `after` is the watermark: time.time() captured
    right before tapping «Продолжить», or — on a retype after a rejected code —
    the received_at of the code that was rejected. Carrier delivery can lag by
    many minutes and then flush several queued codes at once, so a code newer
    than the request is NOT necessarily the one the current request triggered.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if config.SMS_FILE.exists():
            record = json.loads(config.SMS_FILE.read_text())
            if record.get("code") and record["received_at"] > after:
                return record["code"], record["received_at"]
        time.sleep(1)
    raise TimeoutError(
        f"No SMS code arrived within {timeout}s via SMS_SOURCE={config.SMS_SOURCE} "
        "— see docs/sms.md (forwarding on the phone, relay running, Full Disk Access)."
    )


def wait_for_code(requested_at: float, timeout: float = config.SMS_WAIT_TIMEOUT_SEC) -> str:
    return wait_for_record(requested_at, timeout)[0]
