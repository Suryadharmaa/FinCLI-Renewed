from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.services.market_overview import build_market_overview
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.secrets import read_secrets, save_secret

if TYPE_CHECKING:
    from pathlib import Path


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))


class PartialProvider:
    name = "partial"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 10.0, "USD", self.name, datetime(2026, 6, 5, 12, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime(2026, 6, 1), 9, 10, 8, 10, 100)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise RuntimeError("not available")


def test_data_quality_reports_tier_freshness_and_missing_fields(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=PartialProvider(),
    )

    overview = router._run_async(build_market_overview("ABC", router.market_service, "1d"))

    assert overview.data_quality.tier == "weak"
    assert overview.data_quality.freshness == "delayed"
    assert "news" in overview.data_quality.missing_fields
    assert "fundamentals" in overview.data_quality.missing_fields
    assert "weak" in overview.data_quality.label


def test_market_overview_prints_data_quality_limitations(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=PartialProvider(),
    )

    result = router.route("/market ABC 1d")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Data Quality" in output
    assert "weak" in output
    assert "Missing" in output
    assert "news, fundamentals" in output


def test_secrets_status_and_clear_commands_do_not_expose_values(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", target)
    save_secret("GROQ_API_KEY", "secret-groq-value", path=target)
    router = make_router(tmp_path)

    status = router.route("/secrets status")
    clear = router.route("/secrets clear")

    status_text = render_text(status.renderable)
    clear_text = render_text(clear.renderable)
    assert status.status == "ready"
    assert "GROQ_API_KEY" in status_text
    assert "secret-groq-value" not in status_text
    assert clear.status == "ready"
    assert "secret-groq-value" not in clear_text
    assert read_secrets(target) == {}


def test_privacy_status_and_purge_clear_local_sensitive_state(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", target)
    save_secret("FINNHUB_API_KEY", "secret-finnhub-value", path=target)
    router = make_router(tmp_path)
    router.route("/config")
    router.market_cache.set("quote", "ABC", {"symbol": "ABC"}, 300)

    status = router.route("/security status")
    purge = router.route("/security purge")

    assert status.status == "ready"
    assert purge.status == "ready"
    assert read_secrets(target) == {}
    # History may contain the purge command itself, so check that pre-purge events are gone
    events = router.history.get_events(router.session_id)
    assert len(events) <= 1  # Only the purge command itself may remain
    assert router.market_cache.stats()["total"] == 0
    text = render_text(purge.renderable)
    assert "secret-finnhub-value" not in text
    assert "purged" in text.lower()
