"""Application error types."""

from __future__ import annotations

from dataclasses import dataclass


class FinCLIError(Exception):
    """Base error for user-facing FinCLI failures."""

    help_text: str | None = None

    def __init__(self, message: str, help_text: str | None = None) -> None:
        super().__init__(message)
        self.help_text = help_text


class ConfigError(FinCLIError):
    """Raised when configuration cannot be loaded or saved."""


class StorageError(FinCLIError):
    """Raised when local storage fails."""


class CommandError(FinCLIError):
    """Raised when a command is invalid or incomplete."""


class ProviderError(FinCLIError):
    """Raised when an external provider fails."""


class RateLimitError(ProviderError):
    """Raised when a provider is rate-limited."""


class SecurityError(FinCLIError):
    """Raised when a security violation is detected."""
    pass


def classify_error(exc: BaseException) -> str:
    """Classify an error into a category for diagnostics.

    Returns: "provider", "user_input", "network", "security", "storage", "internal"
    """
    if isinstance(exc, ProviderError):
        return "provider"
    if isinstance(exc, RateLimitError):
        return "network"
    if isinstance(exc, CommandError):
        return "user_input"
    if isinstance(exc, SecurityError):
        return "security"
    if isinstance(exc, (ConfigError, StorageError)):
        return "storage"
    text = str(exc).lower()
    if any(kw in text for kw in ("timeout", "connection", "network", "dns", "http")):
        return "network"
    if any(kw in text for kw in ("permission", "denied", "forbidden", "unauthorized")):
        return "security"
    return "internal"


@dataclass(frozen=True, slots=True)
class CrashContext:
    """Sanitized diagnostic context for crash reports. No secrets included."""

    error_type: str
    error_category: str
    message: str
    command: str
    python_version: str
    platform: str
    version: str

    def format(self) -> str:
        return (
            f"Error Type    : {self.error_type}\n"
            f"Category      : {self.error_category}\n"
            f"Message       : {self.message}\n"
            f"Command       : {self.command}\n"
            f"Python        : {self.python_version}\n"
            f"Platform      : {self.platform}\n"
            f"FinCLI Version: {self.version}"
        )
