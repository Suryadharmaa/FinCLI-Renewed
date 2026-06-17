from __future__ import annotations

from datetime import UTC, datetime

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.reliability import STATUS_UNAVAILABLE
from fincli.app.services.market_data import MarketDataService
from fincli.app.utils.errors import ProviderError


def test_market_service_opens_circuit_after_repeated_provider_failures() -> None:
    failing = CountingFailProvider()
    working = CountingWorkProvider()
    service = MarketDataService(
        [failing, working],
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    service.run(service.quote("AAPL"))
    service.run(service.quote("MSFT"))
    quote = service.run(service.quote("NVDA"))

    assert quote.provider == "working"
    assert failing.calls == 2
    assert working.calls == 3
    assert service.provider_metrics_snapshot()["failing"].circuit_open is True
    assert service.provider_results[-2].provider == "failing"
    assert service.provider_results[-2].status == "circuit_open"


def test_market_service_resets_provider_failure_streak_after_success() -> None:
    flaky = FlakyProvider()
    working = CountingWorkProvider()
    service = MarketDataService(
        [flaky, working],
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )

    first = service.run(service.quote("AAPL"))
    second = service.run(service.quote("MSFT"))

    assert first.provider == "working"
    assert second.provider == "flaky"
    metric = service.provider_metrics_snapshot()["flaky"]
    assert metric.consecutive_failures == 0
    assert metric.circuit_open is False


class CountingFailProvider:
    name = "failing"
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


class CountingWorkProvider(CountingFailProvider):
    name = "working"

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        return Quote(symbol=symbol, price=10.0, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")


class FlakyProvider(CountingFailProvider):
    name = "flaky"

    async def quote(self, symbol: str) -> Quote:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("temporary network error")
        return Quote(symbol=symbol, price=11.0, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")
