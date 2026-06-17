"""Macro data service with offline-first fallback rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from typing import Any, Awaitable
import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx

from fincli.app.utils.errors import ProviderError, RateLimitError


@dataclass(frozen=True, slots=True)
class MacroIndicator:
    name: str
    region: str
    value: str
    period: str
    source: str
    note: str


class MacroDataService:
    """Return macro context from free fallback datasets.

    v0.4.0 keeps this deterministic/offline so /macro remains usable without API keys.
    Provider-backed DBnomics/FRED/World Bank adapters can hydrate this shape later.
    """

    def indicators(self, query: str = "") -> list[MacroIndicator]:
        normalized = query.strip().lower()
        rows = _fallback_rows()
        if not normalized:
            return rows
        filtered = [
            row
            for row in rows
            if normalized in row.region.lower()
            or normalized in row.name.lower()
            or normalized in row.note.lower()
        ]
        return filtered or rows[:5]

    def alpha_vantage_indicator(self, indicator: str, region: str = "us") -> list[MacroIndicator]:
        service = AlphaVantageEconomicService(api_key=os.getenv("ALPHA_VANTAGE_API_KEY"))
        return service.run(service.indicator(indicator, region))


class AlphaVantageEconomicService:
    """Fetch no-frills US macro indicators from Alpha Vantage economic endpoints."""

    FUNCTIONS = {
        "cpi": ("CPI", "monthly", "CPI"),
        "inflation": ("INFLATION", "annual", "Inflation"),
        "unemployment": ("UNEMPLOYMENT", "monthly", "Unemployment"),
        "nfp": ("NONFARM_PAYROLL", "monthly", "Nonfarm Payroll"),
        "nonfarm_payroll": ("NONFARM_PAYROLL", "monthly", "Nonfarm Payroll"),
        "fed_funds": ("FEDERAL_FUNDS_RATE", "monthly", "Federal Funds Rate"),
        "federal_funds_rate": ("FEDERAL_FUNDS_RATE", "monthly", "Federal Funds Rate"),
        "gdp": ("REAL_GDP", "annual", "Real GDP"),
        "real_gdp": ("REAL_GDP", "annual", "Real GDP"),
        "gdp_per_capita": ("REAL_GDP_PER_CAPITA", "annual", "Real GDP Per Capita"),
        "real_gdp_per_capita": ("REAL_GDP_PER_CAPITA", "annual", "Real GDP Per Capita"),
    }

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://www.alphavantage.co/query",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url
        self._client = client

    async def indicator(self, indicator: str, region: str = "us") -> list[MacroIndicator]:
        normalized_region = region.strip().lower() or "us"
        if normalized_region not in {"us", "usa", "united states"}:
            raise ProviderError("Alpha Vantage macro endpoint FinCLI saat ini hanya mendukung region US.")
        if not self.api_key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY belum diatur.", "Gunakan /news_model key alphavantage <api_key>.")
        function, interval, label = self._function(indicator)

        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(
                self.base_url,
                params={"function": function, "interval": interval, "apikey": self.api_key},
            )
            if response.status_code == 429:
                raise RateLimitError("Alpha Vantage macro terkena rate limit.")
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Alpha Vantage macro timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Alpha Vantage macro gagal: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Response Alpha Vantage macro bukan JSON valid.") from exc
        finally:
            if close_client:
                await client.aclose()

        if isinstance(payload, dict) and ("Error Message" in payload or "Information" in payload or "Note" in payload):
            message = str(payload.get("Error Message") or payload.get("Information") or payload.get("Note"))
            raise ProviderError(f"Alpha Vantage macro gagal: {message}")
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ProviderError("Alpha Vantage macro tidak mengembalikan data.")
        result: list[MacroIndicator] = []
        for row in rows[:12]:
            if not isinstance(row, dict):
                continue
            period = str(row.get("date") or "-")
            value = str(row.get("value") or "-")
            result.append(
                MacroIndicator(
                    name=label,
                    region="United States",
                    value=value,
                    period=period,
                    source="Alpha Vantage",
                    note=f"function={function}; interval={interval}",
                )
            )
        return result

    def run(self, awaitable: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            return future.result()

    def _function(self, indicator: str) -> tuple[str, str, str]:
        normalized = indicator.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized not in self.FUNCTIONS:
            raise ProviderError("Macro indicator tidak dikenal.", "Gunakan /cpi us, /nfp us, /gdp us, /fed funds us.")
        return self.FUNCTIONS[normalized]


def _fallback_rows() -> list[MacroIndicator]:
    period = date.today().strftime("%Y")
    return [
        MacroIndicator("Policy Rate", "United States", "provider required", period, "Fallback", "Watch FRED/Fed data for rate path."),
        MacroIndicator("Inflation", "United States", "provider required", period, "Fallback", "CPI trend drives USD, yields, and risk assets."),
        MacroIndicator("GDP Growth", "World", "provider required", period, "Fallback", "Use World Bank/IMF for actual country values."),
        MacroIndicator("Policy Rate", "Indonesia", "provider required", period, "Fallback", "BI rate, USD strength, and capital flow affect IDR."),
        MacroIndicator("Inflation", "Indonesia", "provider required", period, "Fallback", "Inflation surprise can affect BI policy expectations."),
        MacroIndicator("PMI", "Euro Area", "provider required", period, "Fallback", "Growth momentum proxy for EUR and European equities."),
    ]
