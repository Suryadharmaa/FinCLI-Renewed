import asyncio
from datetime import date
import io
from pathlib import Path

import httpx
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.economic_calendar import EconomicCalendarService, PublicEconomicCalendarService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def render_text(renderable) -> str:
    console = Console(record=True, width=180, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def test_calendar_command_no_longer_returns_phase_two_stub(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "empty-secrets.env")
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/calendar")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Phase 2 Module" not in output
    assert "Central bank rate decisions" in output
    assert "fallback" in output


def test_calendar_command_supports_date_country_and_impact_filters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "empty-secrets.env")
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/calendar 2026-06-05 2026-06-12 country=GLOBAL impact=high")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "2026-06-05 to 2026-06-12" in output
    assert "Inflation releases" in output
    assert "GDP, PMI" not in output


def test_economic_calendar_service_parses_finnhub_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/calendar/economic"
        assert request.url.params["from"] == "2026-06-05"
        assert request.url.params["to"] == "2026-06-06"
        return httpx.Response(
            200,
            json={
                "economicCalendar": [
                    {
                        "event": "Nonfarm Payrolls",
                        "country": "US",
                        "impact": "high",
                        "time": "2026-06-05T12:30:00+00:00",
                        "actual": "210K",
                        "estimate": "190K",
                        "prev": "175K",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = EconomicCalendarService(api_key="test-key", base_url="https://finnhub.io/api/v1", client=client)

    events = asyncio.run(service.events(date(2026, 6, 5), date(2026, 6, 6)))

    assert len(events) == 1
    assert events[0].event == "Nonfarm Payrolls"
    assert events[0].country == "US"
    assert events[0].actual == "210K"


def test_public_economic_calendar_service_parses_forex_factory_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ff_calendar_thisweek.json"
        return httpx.Response(
            200,
            json=[
                {
                    "title": "CPI m/m",
                    "country": "USD",
                    "date": "2026-06-05T12:30:00+00:00",
                    "impact": "High",
                    "forecast": "0.2%",
                    "previous": "0.3%",
                }
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = PublicEconomicCalendarService(base_url="https://nfs.faireconomy.media", client=client)

    events = asyncio.run(service.events(date(2026, 6, 5), date(2026, 6, 6)))

    assert len(events) == 1
    assert events[0].event == "CPI m/m"
    assert events[0].country == "USD"
    assert events[0].impact == "high"
    assert events[0].estimate == "0.2%"


def test_public_economic_calendar_service_falls_back_to_second_source_after_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nfs.faireconomy.media" and request.url.path.endswith(".json"):
            return httpx.Response(429, json={"error": "rate limit"})
        assert request.url.host == "nfs.faireconomy.media"
        return httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="windows-1252"?>
            <weeklyevents><event>
              <title>Fed Interest Rate Decision</title>
              <country>USD</country>
              <date>06-05-2026</date>
              <time>2:00pm</time>
              <impact>High</impact>
              <forecast>4.50%</forecast>
              <previous>4.50%</previous>
            </event></weeklyevents>""",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = PublicEconomicCalendarService(client=client)

    events = asyncio.run(service.events(date(2026, 6, 5), date(2026, 6, 6)))

    assert len(events) == 1
    assert events[0].event == "Fed Interest Rate Decision"
    assert events[0].country == "USD"
    assert events[0].impact == "high"


def test_public_economic_calendar_service_uses_fred_when_forex_factory_is_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nfs.faireconomy.media":
            return httpx.Response(429, text="rate limited")
        assert request.url.host == "fred.stlouisfed.org"
        return httpx.Response(
            200,
            text="""
            <table><tbody>
              <tr class="odd"><td colspan="2">
                <span style="font-weight: bold;">Saturday June 13, 2026</span>
              </td></tr>
              <tr>
                <td nowrap style="width:5%; text-align:right">N/A</td>
                <td text-align="left"><a href="/release?rid=101">FOMC Press Release</a></td>
              </tr>
              <tr>
                <td nowrap style="width:5%; text-align:right">7:00 pm</td>
                <td text-align="left"><a href="/release?rid=441">Coinbase Cryptocurrencies</a></td>
              </tr>
            </tbody></table>
            """,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = PublicEconomicCalendarService(client=client)

    events = asyncio.run(service.events(date(2026, 6, 13), date(2026, 6, 20)))

    assert len(events) == 2
    assert events[0].event == "FOMC Press Release"
    assert events[0].country == "US"
    assert events[0].impact == "high"
