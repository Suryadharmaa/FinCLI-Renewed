from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.economic_calendar import EconomicEvent, _parse_event
from fincli.app.providers.market.finnhub_provider import FinnhubProvider
from fincli.app.services.macro_data import AlphaVantageEconomicService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.cli.commands import CommandRegistry


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_finnhub_provider_parses_insider_transactions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/stock/insider-transactions"
        assert request.url.params["symbol"] == "AAPL"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "symbol": "AAPL",
                        "name": "Jane Doe",
                        "transactionDate": "2026-06-10",
                        "transactionCode": "P",
                        "change": 1000,
                        "share": 5000,
                        "transactionPrice": 180.5,
                    }
                ]
            },
        )

    provider = FinnhubProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://finnhub.io"),
    )

    rows = provider.run(provider.insider_transactions("AAPL"))

    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["transaction_code"] == "P"
    assert rows[0]["transaction_price"] == 180.5


def test_finnhub_provider_parses_ipo_calendar() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/calendar/ipo"
        assert request.url.params["from"] == "2026-06-01"
        return httpx.Response(
            200,
            json={
                "ipoCalendar": [
                    {
                        "date": "2026-06-20",
                        "exchange": "NASDAQ",
                        "name": "Example IPO",
                        "symbol": "EXMP",
                        "price": "10-12",
                        "numberOfShares": 1000000,
                        "status": "expected",
                    }
                ]
            },
        )

    provider = FinnhubProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://finnhub.io"),
    )

    rows = provider.run(provider.ipo_calendar(date(2026, 6, 1), date(2026, 6, 30)))

    assert rows[0]["symbol"] == "EXMP"
    assert rows[0]["price"] == "10-12"


def test_calendar_event_parser_accepts_finnhub_forecast_actual_previous_fields() -> None:
    event = _parse_event(
        {
            "event": "Core CPI",
            "country": "US",
            "impact": "high",
            "time": "2026-06-17T12:30:00+00:00",
            "actual": "0.2%",
            "forecast": "0.3%",
            "previous": "0.1%",
        }
    )

    assert event.actual == "0.2%"
    assert event.estimate == "0.3%"
    assert event.previous == "0.1%"


def test_calendar_output_includes_prev_forecast_actual_columns() -> None:
    from fincli.app.cli.router import _format_calendar

    table = _format_calendar(
        [EconomicEvent("Core CPI", "US", "high", None, actual="0.2%", estimate="0.3%", previous="0.1%")],
        date(2026, 6, 1),
        date(2026, 6, 30),
        "finnhub",
        "test",
    )

    output = render_text(table)

    assert "Actual" in output
    assert "Forecast" in output
    assert "Prev" in output
    assert "0.2%" in output
    assert "0.3%" in output
    assert "0.1%" in output


def test_alpha_vantage_economic_service_fetches_cpi() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["function"] == "CPI"
        return httpx.Response(
            200,
            json={"name": "CPI", "interval": "monthly", "data": [{"date": "2026-05-01", "value": "313.2"}]},
        )

    service = AlphaVantageEconomicService(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.alphavantage.co"),
    )

    rows = service.run(service.indicator("cpi", "us"))

    assert rows[0].name == "CPI"
    assert rows[0].value == "313.2"
    assert rows[0].source == "Alpha Vantage"


def test_hidden_macro_alias_routes_without_registry_bloat(tmp_path: Path, monkeypatch) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    monkeypatch.setattr(
        router.macro_data,
        "alpha_vantage_indicator",
        lambda indicator, region: [router.macro_data.indicators("United States")[0]],
    )

    result = router.route("/cpi us")
    command_names = {command.name for command in CommandRegistry().all()}

    assert result.status == "ready"
    assert "/cpi" not in command_names
    assert "Macro Indicator" in render_text(result.renderable)


def test_hidden_macro_alias_returns_table_when_provider_fails(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.utils.errors import ProviderError

    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    def fail_indicator(indicator, region):
        raise ProviderError("Alpha Vantage rate limit.")

    monkeypatch.setattr(router.macro_data, "alpha_vantage_indicator", fail_indicator)

    result = router.route("/cpi us")
    output = render_text(result.renderable)

    assert result.status == "ready"
    assert "Macro Indicator" in output
    assert "unavailable" in output
    assert "Alpha Vantage rate limit" in output
