"""Application error types."""

from __future__ import annotations


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
