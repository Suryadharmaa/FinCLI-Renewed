"""Economic calendar fetching and fallback formatting data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from fincli.app.utils.errors import ProviderError, RateLimitError


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event: str
    country: str
    impact: str
    time: datetime | None
    actual: str | None = None
    estimate: str | None = None
    previous: str | None = None
    unit: str | None = None


class EconomicCalendarService:
    """Fetch economic calendar events with Finnhub support."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://finnhub.io/api/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def events(self, start: date, end: date) -> list[EconomicEvent]:
        if not self.api_key:
            raise ProviderError(
                "Economic calendar provider belum dikonfigurasi.",
                "Isi FINNHUB_API_KEY di .env untuk mengambil economic calendar aktual.",
            )

        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(
                f"{self.base_url}/calendar/economic",
                params={"from": start.isoformat(), "to": end.isoformat(), "token": self.api_key},
            )
            if response.status_code == 429:
                raise RateLimitError("Finnhub economic calendar terkena rate limit.")
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Finnhub economic calendar timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Finnhub economic calendar gagal: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Response economic calendar bukan JSON valid.") from exc
        finally:
            if close_client:
                await client.aclose()

        raw_events = payload.get("economicCalendar") if isinstance(payload, dict) else None
        if not isinstance(raw_events, list):
            raise ProviderError("Response Finnhub economic calendar tidak valid.")
        return [_parse_event(item) for item in raw_events if isinstance(item, dict)]


def default_calendar_window(mode: str | None = None) -> tuple[date, date]:
    today = date.today()
    if mode == "today":
        return today, today
    if mode == "week":
        return today, today + timedelta(days=7)
    return today, today + timedelta(days=7)


def fallback_events(start: date, end: date) -> list[EconomicEvent]:
    """Return non-date-specific event categories when no provider is configured."""

    return [
        EconomicEvent("Central bank rate decisions", "Global", "high", None, unit="event group"),
        EconomicEvent("Inflation releases: CPI/PCE", "Global", "high", None, unit="event group"),
        EconomicEvent("Labor market data: payrolls/unemployment", "Global", "high", None, unit="event group"),
        EconomicEvent("GDP, PMI, retail sales, consumer sentiment", "Global", "medium", None, unit="event group"),
        EconomicEvent(
            f"Provider window requested: {start.isoformat()} to {end.isoformat()}",
            "FinCLI",
            "info",
            None,
            unit="fallback",
        ),
    ]


def filter_events(events: list[EconomicEvent], country: str | None = None, impact: str | None = None) -> list[EconomicEvent]:
    filtered = events
    if country:
        normalized_country = country.lower()
        filtered = [event for event in filtered if event.country.lower() == normalized_country]
    if impact:
        normalized_impact = impact.lower()
        filtered = [event for event in filtered if event.impact.lower() == normalized_impact]
    return filtered


def _parse_event(item: dict[str, Any]) -> EconomicEvent:
    return EconomicEvent(
        event=str(item.get("event") or item.get("name") or "Untitled event"),
        country=str(item.get("country") or "N/A"),
        impact=str(item.get("impact") or "N/A").lower(),
        time=_parse_time(item.get("time")),
        actual=_optional_text(item.get("actual")),
        estimate=_optional_text(item.get("estimate")),
        previous=_optional_text(item.get("prev") if "prev" in item else item.get("previous")),
        unit=_optional_text(item.get("unit")),
    )


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
