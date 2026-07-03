"""Security utilities for FinCLI (v1.0.0).

Provides input validation, secret redaction, rate limiting, and path safety.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from fincli.app.utils.errors import CommandError, SecurityError

# ---------------------------------------------------------------------------
# Secret patterns for redaction
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),           # OpenAI/OpenRouter
    re.compile(r"\bghp_[A-Za-z0-9_]{16,}"),            # GitHub
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),            # Google
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),          # GitLab
    re.compile(r"\bxoxb-[A-Za-z0-9-]{10,}"),            # Slack
    re.compile(r"\bAKIA[A-Z0-9]{16}"),                   # AWS
    re.compile(r"\b[A-Za-z0-9+/]{40}={0,2}"),           # Generic base64 (conservative)
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S{12,}"),  # Key=value
]


# ---------------------------------------------------------------------------
# Input Validator
# ---------------------------------------------------------------------------

# Blocked characters for symbols (shell metacharacters, injection attempts)
SYMBOL_BLOCKED = set(";|&$`\\\"'(){}[]!#~<>")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9\.\-\_\=\^]{1,20}$")

# Path traversal patterns
PATH_TRAVERSAL = {"..", "~", "~root", "~admin"}


class SecurityValidator:
    """Validates and sanitizes user inputs."""

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        """Validate and normalize a market symbol."""
        normalized = symbol.strip().upper()
        if not normalized:
            raise CommandError("Symbol cannot be empty.")
        if len(normalized) > 20:
            raise CommandError("Symbol too long (max 20 characters).")
        if any(char in SYMBOL_BLOCKED for char in normalized):
            raise CommandError(
                "Symbol contains invalid characters.",
                "Use letters, numbers, dots, dashes, underscores, or caret.",
            )
        if not SYMBOL_PATTERN.match(normalized):
            raise CommandError(
                f"Invalid symbol format: {symbol}",
                "Examples: AAPL, BTC-USD, EURUSD=X",
            )
        return normalized

    @staticmethod
    def validate_path(path: str | Path, allowed_dirs: list[Path] | None = None) -> Path:
        """Validate a file path, blocking traversal attacks."""
        try:
            resolved = Path(path).expanduser().resolve()
        except (ValueError, OSError) as exc:
            raise CommandError(f"Invalid path: {path}") from exc

        # Check for traversal in the original path components
        path_str = str(path).replace("\\", "/")
        parts = PurePosixPath(path_str).parts
        for part in parts:
            if part in PATH_TRAVERSAL:
                raise SecurityError(
                    "Path traversal detected.",
                    f"Path contains disallowed '{part}'.",
                )

        # Block absolute paths outside allowed directories
        if allowed_dirs:
            allowed = False
            for allowed_dir in allowed_dirs:
                try:
                    resolved.relative_to(allowed_dir.resolve())
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                raise SecurityError(
                    "Path is outside allowed directories.",
                    f"Path must be inside: {', '.join(str(d) for d in allowed_dirs)}",
                )

        return resolved

    @staticmethod
    def validate_number(value: str, name: str = "value", positive: bool = True) -> float:
        """Safely parse a number."""
        try:
            result = float(value)
        except (ValueError, TypeError) as exc:
            raise CommandError(f"{name} must be a number: {value}") from exc
        if positive and result <= 0:
            raise CommandError(f"{name} must be greater than 0.")
        if result != result:  # NaN check
            raise CommandError(f"{name} cannot be NaN.")
        return result

    @staticmethod
    def validate_api_key(key: str) -> str:
        """Validate API key format."""
        stripped = key.strip()
        if not stripped:
            raise CommandError("API key cannot be empty.")
        if len(stripped) < 8:
            raise CommandError("API key too short (min 8 characters).")
        if len(stripped) > 256:
            raise CommandError("API key too long (max 256 characters).")
        # Block obvious non-key values
        if stripped.lower() in {"test", "xxx", "placeholder", "example", "none", "null", "undefined"}:
            raise CommandError("API key cannot be a placeholder.")
        return stripped

    @staticmethod
    def sanitize_input(value: str, max_length: int = 1000) -> str:
        """Sanitize general user input."""
        if len(value) > max_length:
            raise CommandError(f"Input too long (max {max_length} characters).")
        # Strip control characters except newline/tab
        cleaned = "".join(
            char for char in value
            if char in "\n\t" or (ord(char) >= 32 and ord(char) != 127)
        )
        return cleaned.strip()


# ---------------------------------------------------------------------------
# Secret Redactor
# ---------------------------------------------------------------------------

class SecretRedactor:
    """Redacts sensitive information from strings."""

    @staticmethod
    def redact(text: str) -> str:
        """Redact any detected secrets in text."""
        result = text
        for pattern in SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result

    @staticmethod
    def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
        """Redact secrets from dictionary values."""
        redacted = {}
        for key, value in data.items():
            if isinstance(value, str):
                redacted[key] = SecretRedactor.redact(value)
            elif isinstance(value, dict):
                redacted[key] = SecretRedactor.redact_dict(value)
            else:
                redacted[key] = value
        return redacted


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_requests: int
    window_seconds: float
    cooldown_seconds: float = 0.0


# Default rate limits per command group
DEFAULT_RATE_LIMITS: dict[str, RateLimitConfig] = {
    "ai": RateLimitConfig(max_requests=20, window_seconds=60, cooldown_seconds=30),
    "research": RateLimitConfig(max_requests=15, window_seconds=60, cooldown_seconds=30),
    "web": RateLimitConfig(max_requests=10, window_seconds=60, cooldown_seconds=60),
    "market": RateLimitConfig(max_requests=30, window_seconds=60),
    "default": RateLimitConfig(max_requests=100, window_seconds=60, cooldown_seconds=10),
}


class RateLimiter:
    """Per-command and global rate limiting."""

    def __init__(self, config: dict[str, RateLimitConfig] | None = None) -> None:
        self._config = config or DEFAULT_RATE_LIMITS
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._cooldowns: dict[str, float] = {}

    def check(self, command_group: str) -> None:
        """Check if command is rate limited. Raises SecurityError if blocked."""
        now = time.time()
        config = self._config.get(command_group, self._config.get("default", RateLimitConfig(max_requests=100, window_seconds=60)))

        # Check cooldown
        if command_group in self._cooldowns:
            cooldown_end = self._cooldowns[command_group]
            if now < cooldown_end:
                remaining = int(cooldown_end - now)
                raise SecurityError(
                    f"Rate limit reached for {command_group}.",
                    f"Wait {remaining} seconds before trying again.",
                )
            else:
                del self._cooldowns[command_group]

        # Clean old entries
        cutoff = now - config.window_seconds
        self._requests[command_group] = [
            t for t in self._requests[command_group] if t > cutoff
        ]

        # Check limit
        if len(self._requests[command_group]) >= config.max_requests:
            if config.cooldown_seconds > 0:
                self._cooldowns[command_group] = now + config.cooldown_seconds
            raise SecurityError(
                f"Rate limit reached for {command_group}.",
                f"Max {config.max_requests} requests per {config.window_seconds:.0f}s. "
                f"Cooldown: {config.cooldown_seconds:.0f}s.",
            )

        # Record request
        self._requests[command_group].append(now)

    def reset(self) -> None:
        """Reset all rate limits."""
        self._requests.clear()
        self._cooldowns.clear()


# ---------------------------------------------------------------------------
# Path Safety
# ---------------------------------------------------------------------------

def safe_path(target: str | Path, allowed_dirs: list[Path] | None = None) -> Path:
    """Validate and return a safe path, blocking traversal attacks."""
    return SecurityValidator.validate_path(target, allowed_dirs)


# ---------------------------------------------------------------------------
# Security Error (imported from errors.py)
# ---------------------------------------------------------------------------
