import secrets
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal

from .config import MAX_INPUT_ROWS
from .parsing import ImportErrorDetail, parse_import


def _workshop_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))


class Intake:
    def __init__(self):
        self.rows: dict[str, dict[str, str]] = {}
        self.attempts: deque[float] = deque()
        self.enabled = False
        self.code = _workshop_code()
        self.revision = 0
        self.expires_at = time.time() + 14400

    def snapshot(self):
        if time.time() >= self.expires_at:
            self.clear()
        return {
            "enabled": self.enabled,
            "join_code": self.code,
            "revision": self.revision,
            "expires_at": datetime.fromtimestamp(
                self.expires_at, timezone.utc
            ).isoformat(),
            "submissions": list(self.rows.values()),
        }

    def clear(self):
        self.rows.clear()
        self.enabled = False
        self.code = _workshop_code()
        self.expires_at = time.time() + 14400
        self.revision += 1

    def allow_attempt(self):
        now = time.monotonic()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 120:
            return False
        self.attempts.append(now)
        return True

    def submit(self, username: str, code: str, workshop: Literal["CW", "AIW"]):
        self.snapshot()
        if not self.enabled or not secrets.compare_digest(
            code.strip().upper().encode(), self.code.encode()
        ):
            raise PermissionError(
                "Collection is closed or the workshop code is incorrect."
            )
        entries = parse_import(
            source="lines",
            text=username,
            username_column=None,
            has_header=False,
            max_bytes=256,
            max_rows=1,
        )
        entry = entries[0]
        if entry.login is None or entry.status != "awaiting_resolution":
            raise ImportErrorDetail(entry.message or "Enter one valid GitHub username.")
        key = f"{workshop}:{entry.login.casefold()}"
        if key in self.rows:
            return
        if len(self.rows) >= MAX_INPUT_ROWS:
            raise OverflowError(
                "This workshop's submission inbox is full. Contact the organiser."
            )
        self.rows[key] = {
            "id": secrets.token_urlsafe(12),
            "username": entry.login,
            "workshop": workshop,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        self.revision += 1
