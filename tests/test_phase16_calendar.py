import asyncio
from datetime import date
import io
from pathlib import Path

import httpx
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.economic_calendar import EconomicCalendarService
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
