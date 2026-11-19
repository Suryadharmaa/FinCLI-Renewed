import json

import pytest
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager, FinCLISettings
from fincli.app.storage.database import FinCLIDatabase


def _text(renderable: object) -> str:
    console = Console(record=True, width=200)
    console.print(renderable)
    return " ".join(console.export_text().split())


def _router(tmp_path, monkeypatch, saved: dict | None = None) -> CommandRouter:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub")
    config_file = tmp_path / "config.json"
    if saved is not None:
        config_file.write_text(json.dumps(saved), encoding="utf-8")
    return CommandRouter(config=ConfigManager(config_file), db=FinCLIDatabase(tmp_path / "fincli.db"))


@pytest.mark.parametrize(
    ("saved", "chain"),
    [
        ({"market_provider": "iex", "market_provider_priority": ["iex", "finnhub", "yfinance"]}, ["finnhub", "yfinance"]),
        ({"market_provider": "iex", "market_provider_priority": ["iex"]}, ["yfinance"]),
        ({"market_provider": "finnhub", "market_provider_priority": ["finnhub", "Polygon", "unknown"]}, ["finnhub", "polygon"]),
        ({"market_provider": "finnhub", "market_provider_priority": ["finnhub", None]}, ["finnhub"]),
        ({"market_provider": "iex", "market_provider_priority": ["iex", "equibles"]}, ["yfinance", "equibles"]),
        ({"market_provider": "iex", "market_provider_priority": ["iex", "finnhub", "yfinance", "equibles"]}, ["finnhub", "yfinance", "equibles"]),
    ],
)
def test_a_saved_chain_naming_a_retired_or_unknown_provider_still_starts(tmp_path, monkeypatch, saved, chain) -> None:
    router = _router(tmp_path, monkeypatch, saved)

    assert router.config.settings.market_provider_priority == chain
    assert router.config.settings.market_provider == chain[0]
    assert [provider.name for provider in router.market_service.providers] == chain


@pytest.mark.parametrize(
    ("saved_news", "news_chain"),
    [
        (["iex_news", "iex", "google_news_rss"], ["google_news_rss"]),
        ([], FinCLISettings().news_provider_priority),
        (None, FinCLISettings().news_provider_priority),
    ],
)
def test_retired_iex_news_entries_leave_the_news_chain(tmp_path, monkeypatch, saved_news, news_chain) -> None:
    router = _router(tmp_path, monkeypatch, {"news_provider": "iex", "news_provider_priority": saved_news})

    assert router.config.settings.news_provider_priority == news_chain
    assert router.config.settings.news_provider == news_chain[0]


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("/provider use iex", "IEX Cloud shut down in August 2024"),
        ("/provider priority iex,finnhub", "IEX Cloud shut down in August 2024"),
        ("/provider priority finhub,yfinance", "Unknown market provider 'finhub'"),
    ],
)
def test_an_unavailable_provider_is_refused_before_it_is_saved(tmp_path, monkeypatch, command, message) -> None:
    router = _router(tmp_path, monkeypatch)
    router.route("/provider priority finnhub,yfinance")

    result = router.route(command)

    assert result.status == "error"
    assert message in _text(result.renderable)
    assert router.config.settings.market_provider_priority == ["finnhub", "yfinance"]
    restarted = _router(tmp_path, monkeypatch)
    assert [provider.name for provider in restarted.market_service.providers] == ["finnhub", "yfinance"]


def test_the_removal_notice_shows_until_a_provider_choice_is_saved(tmp_path, monkeypatch) -> None:
    router = _router(tmp_path, monkeypatch, {"market_provider": "iex", "market_provider_priority": ["iex", "finnhub", "yfinance"]})

    status = _text(router.route("/provider status").renderable)
    assert "IEX Cloud shut down in August 2024" in status and "/provider use" in status
    assert [provider.name for provider in router.market_service.providers] == ["finnhub", "yfinance"]
    again = _router(tmp_path, monkeypatch)
    assert any("IEX Cloud shut down" in notice for notice in again.config.notices)

    again.route("/provider priority finnhub,yfinance")

    assert "IEX Cloud shut down" not in _text(again.route("/provider status").renderable)
    restarted = _router(tmp_path, monkeypatch)
    assert restarted.config.notices == []
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["market_provider_priority"] == ["finnhub", "yfinance"]


def test_a_reload_still_reports_the_removal_notice(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"market_provider": "iex", "market_provider_priority": ["iex"]}), encoding="utf-8")
    config = ConfigManager(config_file)

    config.reload()

    assert any("IEX Cloud shut down in August 2024" in notice for notice in config.notices)
    assert config.settings.market_provider_priority == ["yfinance"]
