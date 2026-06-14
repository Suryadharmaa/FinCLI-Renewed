"""Economic calendar fetching and fallback formatting data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import html as html_lib
import re
from typing import Any
import xml.etree.ElementTree as ET

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


class PublicEconomicCalendarService:
    """Fetch no-key public economic calendar data before static fallback."""

    def __init__(
        self,
        base_url: str = "https://nfs.faireconomy.media",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def events(self, start: date, end: date) -> list[EconomicEvent]:
        close_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "FinCLI/0.3.1 economic-calendar"},
        )
        errors: list[str] = []
        try:
            for source_name, fetcher in (
                ("forexfactory_json", self._fetch_forex_factory_json),
                ("forexfactory_xml", self._fetch_forex_factory_xml),
                ("fred_release_calendar", self._fetch_fred_release_calendar),
                ("tradingeconomics_guest", self._fetch_trading_economics_guest),
            ):
                try:
                    events = await fetcher(client, start, end)
                    if events:
                        return events
                    errors.append(f"{source_name}: empty")
                except ProviderError as exc:
                    errors.append(f"{source_name}: {exc}")
        finally:
            if close_client:
                await client.aclose()
        raise ProviderError("Semua public economic calendar fallback gagal: " + "; ".join(errors))

    async def _fetch_forex_factory_json(self, client: httpx.AsyncClient, start: date, end: date) -> list[EconomicEvent]:
        response = await _calendar_get(client, f"{self.base_url}/ff_calendar_thisweek.json", "ForexFactory public calendar")
        payload = _calendar_json(response, "ForexFactory public calendar")
        if not isinstance(payload, list):
            raise ProviderError("Response ForexFactory calendar tidak valid.")
        events = [_parse_public_event(item) for item in payload if isinstance(item, dict)]
        return [event for event in events if event.time is None or start <= event.time.date() <= end]

    async def _fetch_forex_factory_xml(self, client: httpx.AsyncClient, start: date, end: date) -> list[EconomicEvent]:
        response = await _calendar_get(client, f"{self.base_url}/ff_calendar_thisweek.xml", "ForexFactory XML calendar")
        events = _parse_forex_factory_xml(response.text)
        return [event for event in events if event.time is None or start <= event.time.date() <= end]

    async def _fetch_fred_release_calendar(
        self, client: httpx.AsyncClient, start: date, end: date
    ) -> list[EconomicEvent]:
        response = await _calendar_get(
            client,
            "https://fred.stlouisfed.org/releases/calendar",
            "FRED release calendar",
            params={"ob": "rd", "od": "asc", "vs": start.isoformat(), "ve": end.isoformat()},
        )
        events = _parse_fred_calendar_html(response.text)
        return [event for event in events if event.time is None or start <= event.time.date() <= end]

    async def _fetch_trading_economics_guest(
        self, client: httpx.AsyncClient, start: date, end: date
    ) -> list[EconomicEvent]:
        response = await _calendar_get(
            client,
            "https://api.tradingeconomics.com/calendar",
            "Trading Economics guest calendar",
            params={"c": "guest:guest", "f": "json"},
        )
        payload = _calendar_json(response, "Trading Economics guest calendar")
        if not isinstance(payload, list):
            raise ProviderError("Response Trading Economics calendar tidak valid.")
        events = [_parse_trading_economics_event(item) for item in payload if isinstance(item, dict)]
        return [event for event in events if event.time is None or start <= event.time.date() <= end]


async def _calendar_get(
    client: httpx.AsyncClient, url: str, label: str, params: dict[str, str] | None = None
) -> httpx.Response:
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{label} timeout.") from exc
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{label} gagal: HTTP {exc.response.status_code}.") from exc


def _calendar_json(response: httpx.Response, label: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"Response {label} bukan JSON valid.") from exc


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
        filtered = [
            event
            for event in filtered
            if event.country.lower() == normalized_country or event.country.lower() in {"global", "fincli"}
        ]
    if impact:
        normalized_impact = impact.lower()
        filtered = [event for event in filtered if event.impact.lower() == normalized_impact]
    return filtered


def calendar_summary(events: list[EconomicEvent]) -> dict[str, int]:
    summary = {"total": len(events), "high": 0, "medium": 0, "low": 0, "info": 0}
    for event in events:
        key = event.impact.lower()
        summary[key] = summary.get(key, 0) + 1
    return summary


def economic_event_rows(events: list[EconomicEvent]) -> list[dict[str, object]]:
    return [
        {
            "time": event.time.isoformat() if event.time else "",
            "country": event.country,
            "impact": event.impact,
            "event": event.event,
            "actual": calendar_actual_value(event),
            "estimate": calendar_estimate_value(event),
            "previous": calendar_previous_value(event),
            "unit": event.unit or "",
        }
        for event in events
    ]


def calendar_actual_value(event: EconomicEvent) -> str:
    if event.actual:
        return event.actual
    if event.unit == "event group":
        return "category"
    if event.unit == "fallback":
        return "window"
    if event.time and event.time > datetime.now(event.time.tzinfo):
        return "pending"
    return "not supplied"


def calendar_estimate_value(event: EconomicEvent) -> str:
    if event.estimate:
        return event.estimate
    if event.unit == "event group":
        return "monitor"
    if event.unit == "fallback":
        return "provider unavailable"
    return "not supplied by source"


def calendar_previous_value(event: EconomicEvent) -> str:
    if event.previous:
        return event.previous
    if event.unit == "event group":
        return "verify"
    if event.unit == "fallback":
        return "check provider"
    return event.unit or "not supplied by source"


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


def _parse_public_event(item: dict[str, Any]) -> EconomicEvent:
    return EconomicEvent(
        event=str(item.get("title") or item.get("event") or item.get("name") or "Untitled event"),
        country=str(item.get("country") or "N/A"),
        impact=_normalize_impact(item.get("impact")),
        time=_parse_time(item.get("date") or item.get("time")),
        actual=_optional_text(item.get("actual")),
        estimate=_optional_text(item.get("forecast") if "forecast" in item else item.get("estimate")),
        previous=_optional_text(item.get("previous") if "previous" in item else item.get("prev")),
        unit="public calendar",
    )


def _parse_forex_factory_xml(payload: str) -> list[EconomicEvent]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ProviderError("Response ForexFactory XML calendar tidak valid.") from exc

    events: list[EconomicEvent] = []
    for item in root.findall(".//event"):
        event_time = _parse_forex_factory_time(_child_text(item, "date"), _child_text(item, "time"))
        events.append(
            EconomicEvent(
                event=_child_text(item, "title") or "Untitled event",
                country=_child_text(item, "country") or "N/A",
                impact=_normalize_impact(_child_text(item, "impact")),
                time=event_time,
                actual=_optional_text(_child_text(item, "actual")),
                estimate=_optional_text(_child_text(item, "forecast")),
                previous=_optional_text(_child_text(item, "previous")),
                unit="public calendar",
            )
        )
    return events


def _parse_fred_calendar_html(payload: str) -> list[EconomicEvent]:
    tbody_match = re.search(r"<tbody>(?P<body>.*?)</tbody>", payload, re.IGNORECASE | re.DOTALL)
    if not tbody_match:
        raise ProviderError("Response FRED release calendar tidak valid.")

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_match.group("body"), flags=re.IGNORECASE | re.DOTALL)
    current_date: datetime | None = None
    events: list[EconomicEvent] = []
    for row in rows:
        date_match = re.search(
            r"<span[^>]*font-weight:\s*bold[^>]*>(?P<date>[^<]+)</span>",
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if date_match:
            current_date = _parse_fred_date(_clean_html(date_match.group("date")))
            continue

        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if current_date is None or len(cells) < 2:
            continue
        release_name = _clean_html(cells[1])
        if not release_name:
            continue
        event_time = _parse_fred_time(current_date, _clean_html(cells[0]))
        events.append(
            EconomicEvent(
                event=release_name,
                country="US",
                impact=_fred_release_impact(release_name),
                time=event_time,
                unit="fred release calendar",
            )
        )
    return events


def _parse_trading_economics_event(item: dict[str, Any]) -> EconomicEvent:
    return EconomicEvent(
        event=str(item.get("Event") or item.get("event") or item.get("Name") or "Untitled event"),
        country=_normalize_country(item.get("Country") or item.get("country")),
        impact=_normalize_importance(item.get("Importance") if "Importance" in item else item.get("importance")),
        time=_parse_time(item.get("Date") or item.get("date") or item.get("Time") or item.get("time")),
        actual=_optional_text(item.get("Actual") if "Actual" in item else item.get("actual")),
        estimate=_optional_text(item.get("Forecast") if "Forecast" in item else item.get("forecast")),
        previous=_optional_text(item.get("Previous") if "Previous" in item else item.get("previous")),
        unit="public calendar",
    )


def _normalize_country(value: object) -> str:
    text = str(value or "N/A").strip()
    mapping = {
        "united states": "US",
        "united kingdom": "GB",
        "euro area": "EU",
        "eurozone": "EU",
        "japan": "JP",
        "china": "CN",
        "canada": "CA",
        "australia": "AU",
        "new zealand": "NZ",
        "germany": "DE",
        "france": "FR",
        "switzerland": "CH",
    }
    return mapping.get(text.lower(), text)


def _normalize_importance(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"3", "high", "red"}:
        return "high"
    if text in {"2", "medium", "orange"}:
        return "medium"
    if text in {"1", "low", "yellow", "gray", "grey"}:
        return "low"
    return text or "N/A"


def _normalize_impact(value: object) -> str:
    normalized = str(value or "N/A").strip().lower()
    return {
        "red": "high",
        "orange": "medium",
        "yellow": "low",
        "gray": "low",
        "grey": "low",
    }.get(normalized, normalized)


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


def _parse_forex_factory_time(date_text: str | None, time_text: str | None) -> datetime | None:
    if not date_text:
        return None
    try:
        parsed_date = datetime.strptime(date_text.strip(), "%m-%d-%Y")
    except ValueError:
        return None

    normalized_time = (time_text or "").strip().lower().replace(" ", "")
    if not normalized_time or normalized_time in {"allday", "tentative"}:
        return parsed_date

    try:
        parsed_time = datetime.strptime(normalized_time, "%I:%M%p")
    except ValueError:
        return parsed_date
    return parsed_date.replace(hour=parsed_time.hour, minute=parsed_time.minute)


def _parse_fred_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%A %B %d, %Y")
    except ValueError:
        return None


def _parse_fred_time(base_date: datetime, value: str) -> datetime:
    normalized = value.strip().lower()
    if not normalized or normalized == "n/a":
        return base_date
    try:
        parsed = datetime.strptime(normalized.replace(" ", ""), "%I:%M%p")
    except ValueError:
        return base_date
    return base_date.replace(hour=parsed.hour, minute=parsed.minute)


def _fred_release_impact(name: str) -> str:
    text = name.lower()
    high_keywords = (
        "fomc",
        "consumer price index",
        "producer price index",
        "employment situation",
        "unemployment",
        "payroll",
        "gross domestic product",
        "gdp",
        "personal income and outlays",
        "retail sales",
        "industrial production",
        "federal funds",
    )
    medium_keywords = (
        "housing",
        "manufacturing",
        "trade",
        "consumer sentiment",
        "job openings",
        "claims",
        "treasury",
    )
    if any(keyword in text for keyword in high_keywords):
        return "high"
    if any(keyword in text for keyword in medium_keywords):
        return "medium"
    return "low"


def _child_text(item: ET.Element, tag: str) -> str | None:
    child = item.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _clean_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    collapsed = re.sub(r"\s+", " ", html_lib.unescape(no_tags))
    return collapsed.strip()


def _optional_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
