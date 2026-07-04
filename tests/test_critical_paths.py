"""Integration tests for critical system paths: provider fallback, circuit breaker,
cache, secrets, database migration, and export round-trips."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from time import time
from typing import TYPE_CHECKING

from fincli.app.modules.exporter import export_rows
from fincli.app.providers.market.base import (
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderStatus,
    Quote,
)
from fincli.app.providers.reliability import STATUS_CIRCUIT_OPEN, STATUS_UNAVAILABLE
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache
from fincli.app.storage.secrets import clear_secrets, read_secrets, save_secret
from fincli.app.utils.errors import ConfigError, ProviderError

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Stub providers for fallback and circuit breaker tests
# ---------------------------------------------------------------------------


class AlwaysFailProvider:
    """Provider that always raises on quote()."""

    name = "always-fail"
    realtime = False

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        raise ProviderError("simulated provider failure")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return []

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status=STATUS_UNAVAILABLE, message="always fails")


class AlwaysWorkProvider:
    """Provider that always succeeds on quote()."""

    name = "always-work"
    realtime = False

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        return Quote(
            symbol=symbol.upper(),
            price=100.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime.now(UTC),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime.now(UTC), 100, 102, 99, 101, 1_000)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


class CountingFailProvider:
    """Provider that fails every call, tracking call count."""

    name = "counting-fail"
    realtime = False

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        raise ProviderError("HTTP 429 rate limit")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return []

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status=STATUS_UNAVAILABLE, message="failing")


class CountingWorkProvider:
    """Provider that succeeds every call, tracking call count."""

    name = "counting-work"
    realtime = False

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        return Quote(
            symbol=symbol.upper(),
            price=50.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime.now(UTC),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return []

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


# ---------------------------------------------------------------------------
# Provider fallback chain tests
# ---------------------------------------------------------------------------


def test_provider_fallback_primary_fails_secondary_succeeds() -> None:
    """When the primary provider fails, the service falls back to the secondary."""
    primary = AlwaysFailProvider()
    secondary = AlwaysWorkProvider()
    service = MarketDataService([primary, secondary])

    quote = service.run(service.quote("AAPL"))

    assert quote.provider == "always-work"
    assert quote.price == 100.0
    assert primary.calls == 1
    assert secondary.calls == 1


def test_provider_fallback_primary_succeeds_secondary_not_called() -> None:
    """When the primary succeeds, the secondary is never invoked."""
    primary = AlwaysWorkProvider()
    secondary = AlwaysWorkProvider()
    secondary.name = "secondary"
    service = MarketDataService([primary, secondary])

    quote = service.run(service.quote("AAPL"))

    assert quote.provider == "always-work"
    assert primary.calls == 1
    assert secondary.calls == 0


def test_provider_fallback_all_fail_raises_provider_error() -> None:
    """When all providers fail, a ProviderError is raised."""
    first = AlwaysFailProvider()
    first.name = "fail-1"
    second = AlwaysFailProvider()
    second.name = "fail-2"
    service = MarketDataService([first, second])

    try:
        service.run(service.quote("AAPL"))
        raise AssertionError("Should have raised ProviderError")
    except ProviderError:
        pass

    assert first.calls == 1
    assert second.calls == 1
    assert len(service.last_errors) == 2


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_threshold_failures() -> None:
    """After N consecutive failures, the circuit opens and the provider is skipped."""
    failing = CountingFailProvider()
    working = CountingWorkProvider()
    service = MarketDataService(
        [failing, working],
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    # First two calls: failing provider fails twice, working catches
    service.run(service.quote("AAPL"))
    service.run(service.quote("MSFT"))

    # Third call: circuit is open, failing is skipped
    quote = service.run(service.quote("NVDA"))

    assert quote.provider == "counting-work"
    assert failing.calls == 2
    metric = service.provider_metrics_snapshot()["counting-fail"]
    assert metric.circuit_open is True


def test_circuit_breaker_records_circuit_open_status_in_results() -> None:
    """When a circuit is open, the provider result records STATUS_CIRCUIT_OPEN."""
    failing = CountingFailProvider()
    working = CountingWorkProvider()
    service = MarketDataService(
        [failing, working],
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    service.run(service.quote("AAPL"))
    service.run(service.quote("MSFT"))
    service.run(service.quote("NVDA"))

    circuit_results = [r for r in service.provider_results if r.status == STATUS_CIRCUIT_OPEN]
    assert len(circuit_results) >= 1
    assert circuit_results[0].provider == "counting-fail"


def test_circuit_breaker_cooldown_allows_half_open_retry() -> None:
    """After the cooldown period, the circuit transitions to half-open and retries."""
    failing = CountingFailProvider()
    working = CountingWorkProvider()
    service = MarketDataService(
        [failing, working],
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=0,  # instant cooldown
    )

    # Trigger circuit open
    service.run(service.quote("AAPL"))
    service.run(service.quote("MSFT"))
    assert service.provider_metrics_snapshot()["counting-fail"].circuit_open is True

    # With 0 cooldown, next call should attempt the failing provider again (half-open)
    service.run(service.quote("NVDA"))

    # The failing provider was called again because cooldown expired
    assert failing.calls == 3


def test_circuit_breaker_resets_on_success() -> None:
    """A successful call resets the consecutive failure count."""
    working = CountingWorkProvider()
    service = MarketDataService(
        [working],
        circuit_breaker_failure_threshold=3,
        circuit_breaker_cooldown_seconds=60,
    )

    service.run(service.quote("AAPL"))
    metric = service.provider_metrics_snapshot()["counting-work"]
    assert metric.consecutive_failures == 0
    assert metric.circuit_open is False


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


def test_cache_set_and_get(tmp_path: Path) -> None:
    """Data stored in cache can be retrieved with the same key."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    cache.set("quote", "AAPL|providers=test", {"symbol": "AAPL", "price": 150.0}, ttl_seconds=300)

    result = cache.get("quote", "AAPL|providers=test")
    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["price"] == 150.0


def test_cache_returns_none_for_missing_key(tmp_path: Path) -> None:
    """A cache miss returns None."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    result = cache.get("quote", "nonexistent")
    assert result is None


def test_cache_ttl_expiry(tmp_path: Path) -> None:
    """Expired entries return None and are pruned."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    # Insert with a TTL of 1 second
    cache.set("quote", "TTL_TEST", {"symbol": "TTL_TEST", "price": 99.0}, ttl_seconds=1)

    # Manually expire the entry by setting expires_at to the past
    db.execute(
        "UPDATE market_cache SET expires_at = ? WHERE namespace = ? AND cache_key = ?",
        (time() - 1, "quote", "TTL_TEST"),
    )

    result = cache.get("quote", "TTL_TEST")
    assert result is None


def test_cache_overwrite_on_same_key(tmp_path: Path) -> None:
    """Writing to the same key overwrites the previous value."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    cache.set("quote", "OVW", {"price": 100}, ttl_seconds=300)
    cache.set("quote", "OVW", {"price": 200}, ttl_seconds=300)

    result = cache.get("quote", "OVW")
    assert result is not None
    assert result["price"] == 200


def test_cache_clear_namespace(tmp_path: Path) -> None:
    """Clearing a namespace removes only entries in that namespace."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    cache.set("quote", "A", {"a": 1}, ttl_seconds=300)
    cache.set("history", "B", {"b": 2}, ttl_seconds=300)

    removed = cache.clear("quote")
    assert removed == 1
    assert cache.get("quote", "A") is None
    assert cache.get("history", "B") is not None


def test_cache_prune_expired(tmp_path: Path) -> None:
    """prune_expired removes all expired entries."""
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)

    cache.set("quote", "PRUNE", {"x": 1}, ttl_seconds=1)
    db.execute(
        "UPDATE market_cache SET expires_at = ? WHERE namespace = ? AND cache_key = ?",
        (time() - 10, "quote", "PRUNE"),
    )

    pruned = cache.prune_expired()
    assert pruned == 1
    assert cache.get("quote", "PRUNE") is None


# ---------------------------------------------------------------------------
# Secrets storage tests
# ---------------------------------------------------------------------------


def test_secrets_save_read_clear(tmp_path: Path) -> None:
    """Full lifecycle: save, read back, clear, verify empty."""
    secrets_file = tmp_path / "secrets.env"

    save_secret("TEST_API_KEY", "super_secret_value_123", path=secrets_file)

    secrets = read_secrets(path=secrets_file)
    assert "TEST_API_KEY" in secrets
    assert secrets["TEST_API_KEY"] == "super_secret_value_123"

    count = clear_secrets(path=secrets_file)
    assert count == 1

    secrets_after = read_secrets(path=secrets_file)
    assert "TEST_API_KEY" not in secrets_after
    assert len(secrets_after) == 0


def test_secrets_save_multiple_keys(tmp_path: Path) -> None:
    """Multiple secrets can be saved and read independently."""
    secrets_file = tmp_path / "secrets.env"

    save_secret("KEY_A", "value_a", path=secrets_file)
    save_secret("KEY_B", "value_b", path=secrets_file)

    secrets = read_secrets(path=secrets_file)
    assert secrets["KEY_A"] == "value_a"
    assert secrets["KEY_B"] == "value_b"
    assert len(secrets) == 2


def test_secrets_overwrite_existing_key(tmp_path: Path) -> None:
    """Saving the same key again overwrites the previous value."""
    secrets_file = tmp_path / "secrets.env"

    save_secret("OVERWRITE_KEY", "old_value", path=secrets_file)
    save_secret("OVERWRITE_KEY", "new_value", path=secrets_file)

    secrets = read_secrets(path=secrets_file)
    assert secrets["OVERWRITE_KEY"] == "new_value"
    assert len(secrets) == 1


def test_secrets_empty_value_raises_config_error(tmp_path: Path) -> None:
    """Saving an empty value raises ConfigError."""
    secrets_file = tmp_path / "secrets.env"

    try:
        save_secret("EMPTY_KEY", "   ", path=secrets_file)
        raise AssertionError("Should have raised ConfigError")
    except ConfigError:
        pass


def test_secrets_read_nonexistent_file(tmp_path: Path) -> None:
    """Reading from a nonexistent file returns an empty dict."""
    secrets = read_secrets(path=tmp_path / "nonexistent.env")
    assert secrets == {}


def test_secrets_set_in_environment(tmp_path: Path) -> None:
    """Saving a secret also sets it in the current process environment."""
    secrets_file = tmp_path / "secrets.env"
    env_key = "FINCLI_TEST_SECRET_IN_ENV"

    # Clean up first
    os.environ.pop(env_key, None)

    save_secret(env_key, "env_test_value", path=secrets_file)

    assert os.environ.get(env_key) == "env_test_value"

    # Cleanup
    os.environ.pop(env_key, None)


# ---------------------------------------------------------------------------
# Database migration tests
# ---------------------------------------------------------------------------


def test_db_migration_preserves_legacy_profile_data(tmp_path: Path) -> None:
    """Migrating from a legacy user_profile schema preserves existing data."""
    db_path = tmp_path / "migration_test.db"

    # Create a database with the old schema (equity_amount, experience_years columns)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            equity_amount REAL NOT NULL,
            equity_currency TEXT NOT NULL,
            leverage TEXT NOT NULL,
            experience_years REAL NOT NULL,
            gameplay TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO user_profile (id, name, equity_amount, equity_currency, leverage, experience_years, gameplay)
        VALUES (1, 'LegacyUser', 5000.0, 'INR', '1:2', 3.5, 'swing')
        """
    )
    conn.commit()
    conn.close()

    # Opening with FinCLIDatabase triggers migration
    db = FinCLIDatabase(db_path)
    rows = db.query("SELECT * FROM user_profile WHERE id = 1")

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "LegacyUser"
    assert float(row["equity"]) == 5000.0
    assert row["currency"] == "INR"
    assert row["leverage"] == "1:2"
    assert float(row["years_in_investment"]) == 3.5
    # "swing" normalizes to "Swing/Investor"
    assert row["gameplay"] == "Swing/Investor"


def test_db_migration_handles_missing_gameplay(tmp_path: Path) -> None:
    """Legacy schema without gameplay column gets classified by equity."""
    db_path = tmp_path / "migration_no_gameplay.db"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            equity REAL NOT NULL,
            currency TEXT NOT NULL,
            leverage TEXT NOT NULL,
            years_in_investment REAL NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment)
        VALUES (1, 'NoGameplayUser', 300.0, 'USD', '1:1', 1.0)
        """
    )
    conn.commit()
    conn.close()

    db = FinCLIDatabase(db_path)
    rows = db.query("SELECT * FROM user_profile WHERE id = 1")

    assert len(rows) == 1
    # 300 <= 400 => Scalper
    assert rows[0]["gameplay"] == "Scalper"


def test_db_initialize_creates_all_tables(tmp_path: Path) -> None:
    """FinCLIDatabase.initialize() creates all expected tables."""
    db = FinCLIDatabase(tmp_path / "full_init.db")

    tables = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    table_names = {str(row["name"]) for row in tables}

    expected = {
        "watchlist",
        "portfolio_positions",
        "journal_entries",
        "portfolio_transactions",
        "market_cache",
        "sessions",
        "session_events",
        "alerts",
        "user_profile",
        "provider_metrics",
        "paper_orders",
        "order_audit_log",
        "kill_switch",
        "portfolio_snapshots",
        "alert_history",
    }
    assert expected.issubset(table_names)


def test_db_watchlist_round_trip(tmp_path: Path) -> None:
    """Data written to watchlist can be read back."""
    db = FinCLIDatabase(tmp_path / "watchlist_test.db")

    db.execute("INSERT INTO watchlist (symbol, group_name) VALUES (?, ?)", ("AAPL", "tech"))
    db.execute("INSERT INTO watchlist (symbol, group_name) VALUES (?, ?)", ("MSFT", "tech"))

    rows = db.query("SELECT symbol, group_name FROM watchlist ORDER BY symbol")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[1]["symbol"] == "MSFT"


def test_db_paper_orders_migration_adds_stop_price(tmp_path: Path) -> None:
    """Opening a database without stop_price column triggers the migration."""
    db_path = tmp_path / "paper_migration.db"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE paper_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            side TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            order_type TEXT NOT NULL,
            price REAL,
            notional REAL DEFAULT 0,
            status TEXT NOT NULL,
            strategy TEXT DEFAULT 'manual',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO paper_orders (side, symbol, quantity, order_type, price, status)
        VALUES ('buy', 'AAPL', 10, 'limit', 150.0, 'filled')
        """
    )
    conn.commit()
    conn.close()

    db = FinCLIDatabase(db_path)

    # Verify stop_price column exists now
    columns = db.query("PRAGMA table_info(paper_orders)")
    col_names = {str(row["name"]) for row in columns}
    assert "stop_price" in col_names

    # Verify original data preserved
    rows = db.query("SELECT * FROM paper_orders WHERE symbol = 'AAPL'")
    assert len(rows) == 1
    assert rows[0]["side"] == "buy"
    assert float(rows[0]["quantity"]) == 10


# ---------------------------------------------------------------------------
# Export round-trip tests
# ---------------------------------------------------------------------------


def test_export_json_round_trip(tmp_path: Path) -> None:
    """Export to JSON, read back, verify data matches."""
    original = [
        {"symbol": "AAPL", "price": 150.25, "quantity": 10},
        {"symbol": "MSFT", "price": 300.50, "quantity": 5},
    ]

    path = export_rows(original, "json", tmp_path / "roundtrip.json")
    assert path.exists()

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert len(loaded) == 2
    assert loaded[0]["symbol"] == "AAPL"
    assert loaded[0]["price"] == 150.25
    assert loaded[1]["symbol"] == "MSFT"
    assert loaded[1]["quantity"] == 5


def test_export_csv_round_trip(tmp_path: Path) -> None:
    """Export to CSV, read back, verify data matches."""
    original = [
        {"symbol": "AAPL", "price": 150.25},
        {"symbol": "MSFT", "price": 300.50},
    ]

    path = export_rows(original, "csv", tmp_path / "roundtrip.csv")
    assert path.exists()

    content = path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 3  # header + 2 rows
    assert "AAPL" in lines[1]
    assert "MSFT" in lines[2]
    assert "150.25" in lines[1]
    assert "300.5" in lines[2]


def test_export_json_preserves_nested_data(tmp_path: Path) -> None:
    """JSON export preserves nested structures."""
    original = [
        {"symbol": "AAPL", "tags": ["tech", "large-cap"], "meta": {"exchange": "NASDAQ"}},
    ]

    path = export_rows(original, "json", tmp_path / "nested.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded[0]["tags"] == ["tech", "large-cap"]
    assert loaded[0]["meta"]["exchange"] == "NASDAQ"


def test_export_empty_rows(tmp_path: Path) -> None:
    """Exporting empty rows produces valid but empty output."""
    json_path = export_rows([], "json", tmp_path / "empty.json")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded == []

    csv_path = export_rows([], "csv", tmp_path / "empty.csv")
    assert csv_path.exists()


def test_export_all_batch(tmp_path: Path) -> None:
    """Batch export writes multiple files to a directory."""
    from fincli.app.modules.exporter import export_all

    portfolio = [{"symbol": "AAPL", "qty": 10}]
    journal = [{"instrument": "AAPL", "bias": "bullish"}]
    alerts = [{"symbol": "AAPL", "condition": "above", "target": 200}]
    trades = [{"side": "buy", "symbol": "AAPL", "qty": 1}]

    written = export_all(
        tmp_path / "batch",
        portfolio=portfolio,
        journal=journal,
        alerts=alerts,
        trades=trades,
        fmt="json",
    )

    assert len(written) == 4
    for path in written:
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) >= 1
