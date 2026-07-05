from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


class FailingProvider:
    name = "failing"

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError("primary failed")


class WorkingProvider:
    name = "working"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 88.0, "USD", self.name, datetime(2026, 6, 5), "delayed")


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_market_data_service_falls_back_to_next_provider() -> None:
    service = MarketDataService([FailingProvider(), WorkingProvider()])

    quote = service.run(service.quote("AAPL"))

    assert quote.provider == "working"
    assert quote.price == 88.0


def test_provider_use_updates_config_and_runtime_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    config = ConfigManager(tmp_path / "config.json")
    router = CommandRouter(config=config, db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider use finnhub")

    assert result.status == "ready"
    assert config.settings.market_provider == "finnhub"
    assert router.market_provider.name == "finnhub"


def test_provider_priority_updates_config_and_runtime_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    config = ConfigManager(tmp_path / "config.json")
    router = CommandRouter(config=config, db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider priority finnhub,yfinance")

    assert result.status == "ready"
    assert config.settings.market_provider_priority == ["finnhub", "yfinance"]
    assert [provider.name for provider in router.market_service.providers] == ["finnhub", "yfinance"]


def test_provider_use_updates_config_and_runtime_polygon_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    config = ConfigManager(tmp_path / "config.json")
    router = CommandRouter(config=config, db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider use polygon")

    assert result.status == "ready"
    assert config.settings.market_provider == "polygon"
    assert router.market_provider.name == "polygon"


def test_provider_priority_accepts_polygon_chain(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    config = ConfigManager(tmp_path / "config.json")
    router = CommandRouter(config=config, db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider priority polygon,yfinance")

    assert result.status == "ready"
    assert config.settings.market_provider_priority == ["polygon", "yfinance"]
    assert [provider.name for provider in router.market_service.providers] == ["polygon", "yfinance"]


def test_provider_key_status_masks_and_lists_market_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "abc123456789")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider key status")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "FINNHUB_API_KEY" in output
    assert "POLYGON_API_KEY" in output
    assert "IEX_CLOUD_API_KEY" in output
    assert "abc1...6789" in output
    assert "abc123456789" not in output


def test_provider_test_can_target_named_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider test finnhub AAPL")

    assert result.status in {"ready", "error"}
    # The command must parse as targeted provider test, not as symbol "finnhub".
    assert "Format:" not in render_text(result.renderable)
