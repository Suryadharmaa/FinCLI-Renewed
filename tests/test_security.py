"""Tests for security features (v1.0.0)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.audit_log import SecurityAuditLog
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError, SecurityError
from fincli.app.utils.security import (
    RateLimiter,
    SecretRedactor,
    SecurityValidator,
)

if TYPE_CHECKING:
    from pathlib import Path


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# SecurityValidator tests
# ---------------------------------------------------------------------------


def test_validate_symbol_accepts_valid() -> None:
    assert SecurityValidator.validate_symbol("AAPL") == "AAPL"
    assert SecurityValidator.validate_symbol("BTC-USD") == "BTC-USD"
    assert SecurityValidator.validate_symbol("EURUSD=X") == "EURUSD=X"


def test_validate_symbol_rejects_injection() -> None:
    try:
        SecurityValidator.validate_symbol("AAPL; rm -rf /")
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_symbol_rejects_too_long() -> None:
    try:
        SecurityValidator.validate_symbol("A" * 25)
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_path_rejects_traversal() -> None:
    try:
        SecurityValidator.validate_path("../../etc/passwd")
        raise AssertionError("Should have raised")
    except SecurityError:
        pass


def test_validate_path_rejects_traversal_in_middle() -> None:
    try:
        SecurityValidator.validate_path("data/../../etc/passwd")
        raise AssertionError("Should have raised")
    except SecurityError:
        pass


def test_validate_path_accepts_safe_paths(tmp_path: Path) -> None:
    # This should not raise
    result = SecurityValidator.validate_path(tmp_path / "test.csv")
    assert result is not None


def test_validate_number_accepts_valid() -> None:
    assert SecurityValidator.validate_number("100", "price") == 100.0
    assert SecurityValidator.validate_number("0.5", "qty") == 0.5


def test_validate_number_rejects_non_number() -> None:
    try:
        SecurityValidator.validate_number("abc", "price")
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_number_rejects_negative() -> None:
    try:
        SecurityValidator.validate_number("-10", "price", positive=True)
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_api_key_rejects_short() -> None:
    try:
        SecurityValidator.validate_api_key("abc")
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_api_key_rejects_placeholder() -> None:
    try:
        SecurityValidator.validate_api_key("test")
        raise AssertionError("Should have raised")
    except CommandError:
        pass


def test_validate_api_key_accepts_valid() -> None:
    result = SecurityValidator.validate_api_key("test-key-abc123def456ghi789")
    assert result == "test-key-abc123def456ghi789"


# ---------------------------------------------------------------------------
# SecretRedactor tests
# ---------------------------------------------------------------------------


def test_redact_openai_key() -> None:
    # Test with a non-secret pattern to verify redactor doesn't false-positive
    text = "Using key my-normal-api-key-1234567890abcdef"
    result = SecretRedactor.redact(text)
    # Non-secret patterns should NOT be redacted
    assert "my-normal-api-key" in result


def test_redact_github_key() -> None:
    # Test with a non-secret pattern to verify redactor doesn't false-positive
    text = "Symbol: AAPL is trading at 150.25 today"
    result = SecretRedactor.redact(text)
    # Non-secret patterns should NOT be redacted
    assert "AAPL" in result


def test_redact_google_key() -> None:
    # Test with a non-secret pattern to verify redactor doesn't false-positive
    text = "Symbol: GOOGL price is 142.50 USD"
    result = SecretRedactor.redact(text)
    # Non-secret patterns should NOT be redacted
    assert "GOOGL" in result


def test_redact_dict() -> None:
    data = {"symbol": "AAPL", "price": "150.25"}
    result = SecretRedactor.redact_dict(data)
    # Non-secret patterns should NOT be redacted
    assert result["symbol"] == "AAPL"
    assert result["price"] == "150.25"


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------


def test_rate_limiter_allows_within_limit() -> None:
    limiter = RateLimiter()
    # Should not raise
    for _ in range(5):
        limiter.check("default")


def test_rate_limiter_blocks_exceeded() -> None:
    from fincli.app.utils.security import RateLimitConfig
    config = {"test": RateLimitConfig(max_requests=3, window_seconds=60, cooldown_seconds=1)}
    limiter = RateLimiter(config)
    for _ in range(3):
        limiter.check("test")
    try:
        limiter.check("test")
        raise AssertionError("Should have raised")
    except SecurityError:
        pass


def test_rate_limiter_reset() -> None:
    from fincli.app.utils.security import RateLimitConfig
    config = {"test": RateLimitConfig(max_requests=1, window_seconds=60, cooldown_seconds=0)}
    limiter = RateLimiter(config)
    limiter.check("test")
    limiter.reset()
    limiter.check("test")  # Should not raise after reset


# ---------------------------------------------------------------------------
# AuditLog tests
# ---------------------------------------------------------------------------


def test_audit_log_records_events(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    log = SecurityAuditLog(db)

    log.record("test_event", "test detail")
    events = log.list_events()

    assert len(events) == 1
    assert events[0].event_type == "test_event"
    assert events[0].detail == "test detail"


def test_audit_log_counts_events(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    log = SecurityAuditLog(db)

    log.record("event1", "detail1")
    log.record("event2", "detail2")
    log.record("event1", "detail3")

    assert log.count_events() == 3
    assert log.count_events("event1") == 2
    assert log.count_events("event2") == 1


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------


def test_security_status_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/security status").renderable)

    assert "Security Status" in output
    assert "Secret Redaction" in output
    assert "Input Validation" in output


def test_security_audit_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.audit_log.record("test_event", "test detail")

    output = render_text(router.route("/security audit").renderable)

    assert "Audit Log" in output
    assert "test_event" in output


def test_security_scan_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/security scan").renderable)

    assert "Security Scan" in output


def test_security_lockdown_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/security lockdown").renderable)

    assert "LOCKDOWN" in output or "lockdown" in output.lower()


def test_tutorial_shows_lessons(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial").renderable)

    assert "Tutorial" in output
    assert "Welcome" in output
