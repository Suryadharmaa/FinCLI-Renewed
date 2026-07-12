"""Authentication and command policy for the local web interface."""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque

from fincli.app.storage.secrets import read_secrets, save_secret

WEB_TOKEN_KEY = "FINCLI_WEB_TOKEN"
SENSITIVE_PREFIXES = (
    "/trading live",
    "/secrets",
    "/security purge",
    "/security lockdown",
    "/provider key",
    "/trading broker",
    "/web stop",
    "/web restart",
    "/web token rotate",
    "/web config set",
)


def get_or_create_token() -> str:
    token = read_secrets().get(WEB_TOKEN_KEY, "")
    if not token:
        token = secrets.token_urlsafe(32)
        save_secret(WEB_TOKEN_KEY, token)
    return token


def rotate_token() -> str:
    token = secrets.token_urlsafe(32)
    save_secret(WEB_TOKEN_KEY, token)
    return token


def token_matches(candidate: str | None) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, get_or_create_token())


def command_requires_confirmation(command: str) -> bool:
    normalized = command.strip().lower()
    return any(normalized.startswith(prefix) for prefix in SENSITIVE_PREFIXES)


class LocalRateLimiter:
    def __init__(self, limit: int = 90, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        queue = self._requests[key]
        while queue and now - queue[0] > self.window_seconds:
            queue.popleft()
        if len(queue) >= self.limit:
            return False
        queue.append(now)
        return True
