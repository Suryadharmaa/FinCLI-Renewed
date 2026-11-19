from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date

import httpx
import pytest

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.reports import write_market_report
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import (
    Candle,
    FundamentalSnapshot,
    ProviderCapability,
    ProviderStatus,
    Quote,
    fundamentals_provenance,
)
from fincli.app.providers.market.equibles_provider import EquiblesProvider, build_snapshot, revenue_growth
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.reliability import (
    STATUS_AUTH_FAILED,
    STATUS_EMPTY_DATA,
    STATUS_ENTITLEMENT_MISSING,
    STATUS_NETWORK_ERROR,
    STATUS_PARTIAL_DATA,
    STATUS_RATE_LIMITED,
    classify_provider_error,
)
from fincli.app.research.engine import ResearchEngine
from fincli.app.services.market_data import MarketDataService, _fundamentals_from_payload, _fundamentals_to_payload
from fincli.app.services.market_overview import build_market_overview
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.tui.market_provider_selector import priority_presets, recommended_provider_priority
from fincli.app.utils.errors import DataUnavailableError, ProviderError, RateLimitError

# Trimmed from live responses (AAPL, 2026-11-19).
TODAY = date(2026, 11, 19)
AAPL_PROFILE = {"ticker": "AAPL", "currency": "USD", "sector": "Technology", "industry": "Consumer Electronics"}


def _row(period: str, value: float, period_end: str, comparable: bool = True) -> dict:
    return {
        "fiscalPeriod": period,
        "value": value,
        "periodEnd": period_end,
        "filedDate": "2026-11-03",
        "form": "10-K",
        "isComparableAnnual": comparable,
    }


AAPL_REVENUE = {
    "ticker": "AAPL",
    "concept": "revenue",
    "unit": "USD",
    "annual": [
        _row("FY2024", 391035000000.0, "2024-09-28"),
        _row("FY2025", 416161000000.0, "2025-09-27"),
        _row("FY2026", 478834000000.0, "2026-09-26"),
    ],
}
AAPL_EPS = {
    "ticker": "AAPL",
    "concept": "eps-diluted",
    "unit": "USD/shares",
    "annual": [
        _row("FY2024", 6.08, "2024-09-28"),
        _row("FY2025", 7.46, "2025-09-27"),
        _row("FY2026", 8.98, "2026-09-26"),
    ],
}


def _transport(routes: dict[str, httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        response = routes.get(request.url.path)
        return response if response is not None else httpx.Response(404, json={"error": {"message": "Not found."}})

    return httpx.MockTransport(handler)


def _provider(routes: dict[str, httpx.Response], seen: list[httpx.Request], **kwargs) -> EquiblesProvider:
    return EquiblesProvider(
        api_key="eq_test_secret",
        client=httpx.AsyncClient(transport=_transport(routes, seen)),
        today=lambda: TODAY,
        **kwargs,
    )


AAPL_ROUTES = {
    "/v1/stocks/AAPL": httpx.Response(200, json=AAPL_PROFILE),
    "/v1/stocks/AAPL/financial-facts/revenue": httpx.Response(200, json=AAPL_REVENUE),
    "/v1/stocks/AAPL/financial-facts/eps-diluted": httpx.Response(200, json=AAPL_EPS),
}


def test_snapshot_takes_the_latest_fiscal_year_with_its_period_and_filing_date() -> None:
    seen: list[httpx.Request] = []
    snapshot = asyncio.run(_provider(AAPL_ROUTES, seen).fundamentals("aapl"))

    assert snapshot.symbol == "AAPL"
    assert snapshot.provider == "equibles"
    assert snapshot.currency == "USD"
    assert snapshot.revenue == 478834000000.0
    assert snapshot.eps == 8.98
    assert (snapshot.sector, snapshot.industry) == ("Technology", "Consumer Electronics")
    assert (snapshot.fiscal_period, snapshot.period_end, snapshot.filed_date) == ("FY2026", "2026-09-26", "2026-11-03")
    assert snapshot.revenue_growth == pytest.approx((478834 / 416161 - 1) * 100)
    assert (snapshot.market_cap, snapshot.pe_ratio, snapshot.beta) == (None, None, None)
    assert {request.headers["Authorization"] for request in seen} == {"Bearer eq_test_secret"}
    assert all("eq_test_secret" not in str(request.url) for request in seen)


def test_revenue_growth_matches_fiscal_years_by_label_not_position() -> None:
    rows = [_row("FY2023", 100.0, "2023-09-30"), _row("FY2025", 130.0, "2025-09-27")]
    assert revenue_growth(rows) is None, "FY2024 is missing, so FY2023 is not the prior year"

    rows.insert(1, _row("FY2024", 120.0, "2024-09-28"))
    assert revenue_growth(rows) == pytest.approx((130 / 120 - 1) * 100)

    assert revenue_growth([_row("FY2024", 0.0, "2024-09-28"), _row("FY2025", 10.0, "2025-09-27")]) is None
    assert revenue_growth([_row("FY2024", -5.0, "2024-09-28"), _row("FY2025", 10.0, "2025-09-27")]) is None
    assert revenue_growth([]) is None


def test_a_short_transition_year_is_never_the_latest_year_or_a_comparison_base() -> None:
    revenue = {
        "unit": "USD",
        "annual": [
            _row("FY2024", 100.0, "2024-12-31"),
            _row("FY2025", 40.0, "2025-06-30", comparable=False),
        ],
    }
    snapshot = build_snapshot("XYZ", {}, revenue, None, today=TODAY)
    assert (snapshot.revenue, snapshot.fiscal_period) == (100.0, "FY2024")
    assert snapshot.revenue_growth is None


def test_eps_is_dropped_when_its_year_or_currency_differs_from_revenue() -> None:
    other_year = {"unit": "USD/shares", "annual": [_row("FY2025", 7.46, "2025-09-27")]}
    assert build_snapshot("AAPL", AAPL_PROFILE, AAPL_REVENUE, other_year, today=TODAY).eps is None

    other_currency = {"unit": "TWD/shares", "annual": [_row("FY2026", 8.98, "2026-09-26")]}
    assert build_snapshot("AAPL", AAPL_PROFILE, AAPL_REVENUE, other_currency, today=TODAY).eps is None


def test_a_foreign_filer_reports_in_its_own_currency() -> None:
    revenue = {"unit": "TWD", "annual": [_row("FY2025", 3809054300000.0, "2025-12-31")]}
    eps = {"unit": "TWD/shares", "annual": [_row("FY2025", 66.25, "2025-12-31")]}
    snapshot = build_snapshot("TSM", {"currency": "USD", "sector": "Technology"}, revenue, eps, today=TODAY)
    assert (snapshot.currency, snapshot.eps) == ("TWD", 66.25)


def test_newer_eps_anchors_the_year_and_the_lagging_revenue_is_left_empty() -> None:
    lagging_revenue = {"unit": "USD", "annual": [_row("FY2021", 90.0, "2021-12-31"), _row("FY2022", 100.0, "2022-12-31")]}
    eps = {"unit": "USD/shares", "annual": [_row("FY2025", 3.5, "2025-12-31")]}
    snapshot = build_snapshot("XYZ", {}, lagging_revenue, eps, today=TODAY)
    assert (snapshot.fiscal_period, snapshot.eps, snapshot.currency) == ("FY2025", 3.5, "USD")
    assert (snapshot.revenue, snapshot.revenue_growth) == (None, None)


def test_figures_from_a_year_that_ended_over_two_years_ago_are_not_shown_as_current() -> None:
    snapshot = build_snapshot("AAPL", AAPL_PROFILE, AAPL_REVENUE, AAPL_EPS, today=date(2028, 12, 1))
    assert (snapshot.revenue, snapshot.eps, snapshot.revenue_growth, snapshot.fiscal_period) == (None, None, None, None)
    assert snapshot.sector == "Technology"


def test_an_unlisted_symbol_is_unavailable_data_asked_once_per_window() -> None:
    seen: list[httpx.Request] = []
    provider = _provider({}, seen)
    for _ in range(2):
        with pytest.raises(DataUnavailableError) as caught:
            asyncio.run(provider.fundamentals("EURUSD=X"))
        assert classify_provider_error(caught.value) == STATUS_EMPTY_DATA
    assert len(seen) == 1
    assert classify_provider_error(DataUnavailableError("Unlisted.")) == STATUS_EMPTY_DATA


def test_an_unlisted_symbol_is_reported_unavailable_and_never_opens_the_circuit() -> None:
    seen: list[httpx.Request] = []
    equibles = _provider({}, seen, cache_ttl_seconds=0)
    service = MarketDataService([_FundamentalsSource("upstream", None), equibles], circuit_breaker_failure_threshold=1)

    for _ in range(2):
        with pytest.raises(ProviderError):
            asyncio.run(service.fundamentals("EURUSD=X"))

    assert len(seen) == 2
    assert not service.provider_metrics["equibles"].circuit_open
    assert [r.status for r in service.recent_results(10) if r.provider == "equibles"] == [STATUS_EMPTY_DATA] * 2


def test_a_concept_the_company_does_not_report_leaves_that_field_empty() -> None:
    seen: list[httpx.Request] = []
    routes = {"/v1/stocks/AAPL": AAPL_ROUTES["/v1/stocks/AAPL"], "/v1/stocks/AAPL/financial-facts/eps-diluted": AAPL_ROUTES["/v1/stocks/AAPL/financial-facts/eps-diluted"]}
    snapshot = asyncio.run(_provider(routes, seen).fundamentals("AAPL"))
    assert snapshot.revenue is None
    assert (snapshot.eps, snapshot.fiscal_period, snapshot.sector) == (8.98, "FY2026", "Technology")


def test_a_snapshot_is_reused_within_the_cache_window() -> None:
    seen: list[httpx.Request] = []
    now = [0.0]
    provider = _provider(AAPL_ROUTES, seen, clock=lambda: now[0], cache_ttl_seconds=60)

    asyncio.run(provider.fundamentals("AAPL"))
    asyncio.run(provider.fundamentals("AAPL"))
    assert len(seen) == 3

    now[0] = 61.0
    asyncio.run(provider.fundamentals("AAPL"))
    assert len(seen) == 6


@pytest.mark.parametrize(
    ("response", "error_type", "status"),
    [
        (httpx.Response(401, json={"error": {"message": "Invalid API key."}}), ProviderError, STATUS_AUTH_FAILED),
        (httpx.Response(403, json={"error": {"message": "Requires the Pro plan."}}), ProviderError, STATUS_ENTITLEMENT_MISSING),
        (
            httpx.Response(
                429,
                headers={"X-RateLimit-Reset": "2026-11-20T00:00:00Z"},
                json={"error": {"message": "Daily call limit exceeded: 100 of 100."}},
            ),
            RateLimitError,
            STATUS_RATE_LIMITED,
        ),
        (httpx.Response(503, text="upstream down"), ProviderError, STATUS_NETWORK_ERROR),
    ],
)
def test_http_failures_map_to_the_reliability_statuses(response, error_type, status) -> None:
    seen: list[httpx.Request] = []
    provider = _provider({"/v1/stocks/AAPL": response}, seen)
    with pytest.raises(error_type) as caught:
        asyncio.run(provider.fundamentals("AAPL"))
    assert classify_provider_error(caught.value) == status
    assert "eq_test_secret" not in str(caught.value)


def test_a_rate_limit_says_when_requests_resume() -> None:
    seen: list[httpx.Request] = []
    response = httpx.Response(429, headers={"X-RateLimit-Reset": "2026-11-20T00:00:00Z"}, json={})
    with pytest.raises(RateLimitError, match="Resets at 2026-11-20T00:00:00Z"):
        asyncio.run(_provider({"/v1/stocks/AAPL": response}, seen).fundamentals("AAPL"))


def test_a_timeout_is_a_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = EquiblesProvider(api_key="eq_test_secret", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.fundamentals("AAPL"))
    assert classify_provider_error(caught.value) == STATUS_NETWORK_ERROR


def test_without_a_key_nothing_is_sent_and_the_status_is_auth_failed() -> None:
    seen: list[httpx.Request] = []
    provider = EquiblesProvider(api_key=None, client=httpx.AsyncClient(transport=_transport(AAPL_ROUTES, seen)))
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.fundamentals("AAPL"))
    assert classify_provider_error(caught.value) == STATUS_AUTH_FAILED
    assert seen == []
    assert asyncio.run(provider.status()).status == "no_key"


class _QuoteProvider:
    name = "fullstack"
    realtime = False

    async def quote(self, symbol: str) -> Quote:
        from datetime import UTC, datetime

        return Quote(symbol=symbol, price=10.0, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d"):
        return []

    async def news(self, symbol: str, limit: int = 5):
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise ProviderError("fundamentals unavailable")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="")

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(self.name, False, ("quote", "history", "news", "fundamentals"), ("stock",))


class _SpyEquibles(EquiblesProvider):
    def __init__(self) -> None:
        super().__init__(api_key="eq_test_secret")
        self.calls: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        self.calls.append("quote")
        return await super().quote(symbol)

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d"):
        self.calls.append("history")
        return await super().history(symbol, period, interval)

    async def news(self, symbol: str, limit: int = 5):
        self.calls.append("news")
        return await super().news(symbol, limit)

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        self.calls.append("fundamentals")
        return build_snapshot(symbol, AAPL_PROFILE, AAPL_REVENUE, AAPL_EPS, today=TODAY)


def test_the_service_never_routes_quotes_history_or_news_to_a_fundamentals_only_provider() -> None:
    equibles = _SpyEquibles()
    service = MarketDataService([equibles, _QuoteProvider()], circuit_breaker_failure_threshold=1)

    for _ in range(3):
        assert asyncio.run(service.quote("AAPL")).price == 10.0
        asyncio.run(service.history("AAPL"))
        asyncio.run(service.news("AAPL"))
    snapshot = asyncio.run(service.fundamentals("AAPL"))

    assert equibles.calls == ["fundamentals"]
    assert snapshot.provider == "equibles"
    assert service.primary_provider.name == "fullstack"
    assert not service.provider_metrics["equibles"].circuit_open
    assert any(r.provider == "equibles" and r.status == STATUS_PARTIAL_DATA for r in service.recent_results(20))


class _FundamentalsSource(_QuoteProvider):
    """A full provider whose fundamentals answer is a given snapshot or error."""

    def __init__(self, name: str, snapshot: FundamentalSnapshot | None = None) -> None:
        self.name = name
        self.snapshot = snapshot
        self.calls = 0

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        self.calls += 1
        if self.snapshot is None:
            raise ProviderError("fundamentals unavailable")
        return self.snapshot


COMPLETE = FundamentalSnapshot(
    symbol="AAPL", provider="upstream", currency="USD", market_cap=3.9e12, pe_ratio=34.0, eps=7.5, revenue=4.2e11,
    sector="Technology", industry="Consumer Electronics",
)


@pytest.mark.parametrize(
    ("upstream", "winner"),
    [
        (COMPLETE, "upstream"),  # complete: returned before Equibles is asked
        (None, "equibles"),  # failed: Equibles' partial snapshot is the answer
        (replace(COMPLETE, pe_ratio=None), "upstream"),  # partial, scores 80 against Equibles' 45
        (replace(COMPLETE, pe_ratio=None, eps=None, revenue=None, sector=None), "equibles"),  # partial, scores 25
        (replace(COMPLETE, market_cap=None, pe_ratio=None), "upstream"),  # same score as Equibles: the earlier one stays
    ],
)
def test_equibles_is_a_fundamentals_fallback_and_snapshots_are_never_combined(upstream, winner) -> None:
    first = _FundamentalsSource("upstream", upstream)
    equibles = _SpyEquibles()
    service = MarketDataService([first, equibles])

    snapshot = asyncio.run(service.fundamentals("AAPL"))

    assert equibles.calls == ([] if upstream is COMPLETE else ["fundamentals"])
    expected = upstream if winner == "upstream" else build_snapshot("AAPL", AAPL_PROFILE, AAPL_REVENUE, AAPL_EPS, today=TODAY)
    assert snapshot == expected


def test_fallback_figures_are_labelled_with_their_source_currency_and_filing_period() -> None:
    label = fundamentals_provenance(build_snapshot("TSM", {}, TSM_REVENUE, TSM_EPS, today=TODAY))
    assert label.startswith(TSM_LABEL + " (period end 2025-12-31")
    assert fundamentals_provenance(COMPLETE) == "Source=upstream; Currency=USD"


TSM_REVENUE = {"unit": "TWD", "annual": [_row("FY2025", 3.8e12, "2025-12-31")]}
TSM_EPS = {"unit": "TWD/shares", "annual": [_row("FY2025", 65.47, "2025-12-31")]}
TSM_LABEL = "Source=equibles; Currency=TWD; EPS/Revenue as reported for FY2025"


class _CandleStack(_QuoteProvider):
    """Quotes, candles and news in USD; its fundamentals fail, so the chain falls back to Equibles."""

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        from datetime import datetime

        return [Candle(datetime(2026, 1, 1 + i % 28), 100 + i, 102 + i, 99 + i, 101 + i, 1_000) for i in range(80)]


class _TsmEquibles(_SpyEquibles):
    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return build_snapshot(symbol, {}, TSM_REVENUE, TSM_EPS, today=TODAY)


class _CaptureAI:
    name = "capture"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.prompts.append(request.prompt)
        return AIResponse(provider=self.name, model=request.model, content="ok")


def test_research_labels_fallback_fundamentals_in_the_brief_and_the_ai_prompt() -> None:
    ai = _CaptureAI()
    engine = ResearchEngine(MarketDataService([_CandleStack(), _TsmEquibles()]), ai_provider=ai)

    brief = asyncio.run(engine.build("TSM", mode="report"))

    assert any(TSM_LABEL in point for point in brief.decision_points if point.startswith("Fundamentals:"))
    assert TSM_LABEL in ai.prompts[-1]


def test_market_reports_label_fallback_fundamentals(tmp_path) -> None:
    overview = asyncio.run(build_market_overview("TSM", MarketDataService([_CandleStack(), _TsmEquibles()])))

    payload = json.loads(write_market_report(overview, "json", tmp_path / "report.json").read_text(encoding="utf-8"))
    markdown = write_market_report(overview, "md", tmp_path / "report.md").read_text(encoding="utf-8")

    fundamentals = payload["fundamentals"]
    assert (fundamentals["provider"], fundamentals["currency"], fundamentals["fiscal_period"]) == ("equibles", "TWD", "FY2025")
    assert (fundamentals["period_end"], fundamentals["filed_date"]) == ("2025-12-31", "2026-11-03")
    assert f"- Source: {TSM_LABEL}" in markdown


def test_provider_compare_lists_a_fundamentals_only_provider_as_not_supported(tmp_path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    equibles = _SpyEquibles()
    router.market_service = MarketDataService([_QuoteProvider(), equibles])

    table = router.route("/provider compare AAPL").renderable
    rows = {provider: status for provider, status in zip(table.columns[0]._cells, table.columns[3]._cells, strict=True)}

    assert equibles.calls == []
    assert "not supported" in rows["equibles"]
    assert "delayed" in rows["fullstack"]


def test_the_cache_round_trip_keeps_the_filing_provenance() -> None:
    snapshot = build_snapshot("AAPL", AAPL_PROFILE, AAPL_REVENUE, AAPL_EPS, today=TODAY)
    assert _fundamentals_from_payload(_fundamentals_to_payload(snapshot)) == snapshot
    legacy = replace(snapshot, fiscal_period=None, period_end=None, filed_date=None, revenue_growth=None)
    payload = _fundamentals_to_payload(legacy)
    for key in ("fiscal_period", "period_end", "filed_date", "revenue_growth"):
        payload.pop(key)
    assert _fundamentals_from_payload(payload) == legacy


def test_equibles_is_appended_to_the_current_chain_and_never_leads_it() -> None:
    assert recommended_provider_priority("equibles", ["finnhub", "yfinance"]) == ("finnhub", "yfinance", "equibles")
    assert recommended_provider_priority("equibles", ["finnhub"]) == ("finnhub", "yfinance", "equibles")
    assert recommended_provider_priority("equibles") == ("yfinance", "equibles")
    assert recommended_provider_priority("finnhub", ["polygon"])[0] == "finnhub"
    minimal = next(preset for preset in priority_presets("equibles") if preset.label == "Primary + yfinance")
    assert minimal.providers == ("yfinance", "equibles")


def test_changing_the_primary_provider_or_preset_keeps_equibles_last() -> None:
    current = ["finnhub", "yfinance", "equibles"]
    assert recommended_provider_priority("twelvedata", current)[-1] == "equibles"
    assert recommended_provider_priority("yfinance", current) == ("yfinance", "equibles")
    presets = priority_presets("finnhub", current)
    for preset in presets:
        assert preset.providers[-1] == "equibles" and preset.providers.count("equibles") == 1, preset.label
    yfinance_only = next(preset for preset in presets if preset.label == "YFinance only")
    assert yfinance_only.providers == ("yfinance", "equibles")
    assert "no API key required" not in yfinance_only.description
    untouched = next(preset for preset in priority_presets("finnhub", ["finnhub", "yfinance"]) if preset.label == "YFinance only")
    assert untouched.providers == ("yfinance",)


@pytest.mark.parametrize("command", ["/provider use twelvedata", "/news_model twelvedata", "/news_model key twelvedata test-td"])
def test_choosing_another_primary_provider_keeps_equibles_last(tmp_path, monkeypatch, command) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    for key in ("EQUIBLES_API_KEY", "FINNHUB_API_KEY", "TWELVE_DATA_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/provider priority finnhub,equibles,yfinance")

    assert router.route(command).status == "ready"
    assert router.config.settings.market_provider_priority == ["twelvedata", "finnhub", "yfinance", "equibles"]


@pytest.mark.parametrize(
    ("command", "chain"),
    [
        ("/provider priority equibles", ["yfinance", "equibles"]),
        ("/provider priority equibles,finnhub", ["finnhub", "equibles"]),
    ],
)
def test_an_explicit_priority_always_keeps_a_quote_provider_first(tmp_path, monkeypatch, command, chain) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    for key in ("EQUIBLES_API_KEY", "FINNHUB_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    assert router.route(command).status == "ready"

    assert router.config.settings.market_provider_priority == chain
    assert router.config.settings.market_provider == chain[0]
    assert router.market_service.primary_provider.name == chain[0]


def test_a_chain_of_only_fundamentals_providers_gains_yfinance_for_quotes(monkeypatch) -> None:
    monkeypatch.setenv("EQUIBLES_API_KEY", "test-key")
    names = [provider.name for provider in MarketProviderManager().create_many(["equibles"])]
    assert names == ["yfinance", "equibles"]


def test_an_explicit_priority_list_removes_equibles_until_it_is_added_again(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    for key in ("EQUIBLES_API_KEY", "FINNHUB_API_KEY", "TWELVE_DATA_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/provider priority finnhub,yfinance,equibles")
    router.route("/provider priority finnhub,yfinance")
    router.route("/provider use twelvedata")
    assert router.config.settings.market_provider_priority == ["twelvedata", "finnhub", "yfinance"]


@pytest.mark.parametrize("command", ["/news_model equibles", "/provider use equibles"])
def test_selecting_equibles_appends_it_without_changing_the_active_providers(tmp_path, monkeypatch, command) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    monkeypatch.setenv("EQUIBLES_API_KEY", "eq_test_secret")
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/provider priority finnhub,yfinance")
    news_before = router.config.settings.news_provider

    result = router.route(command)

    assert result.status == "ready"
    assert router.config.settings.market_provider_priority == ["finnhub", "yfinance", "equibles"]
    assert router.config.settings.market_provider == "finnhub"
    assert router.config.settings.news_provider == news_before


def test_saving_an_equibles_key_keeps_the_active_market_and_news_providers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    monkeypatch.delenv("EQUIBLES_API_KEY", raising=False)
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/provider priority finnhub,yfinance")
    news_before = router.config.settings.news_provider

    result = router.route("/news_model key equibles eq_test_secret")

    assert result.status == "ready"
    assert router.config.settings.market_provider_priority == ["finnhub", "yfinance", "equibles"]
    assert router.config.settings.news_provider == news_before
    assert router.market_service.primary_provider.name == "finnhub"
    assert "eq_test_secret" not in str(result.renderable)
