"""/screen takes Equibles' as-filed revenue growth only where yfinance has none, labelled, and never mixes fiscal years."""

from __future__ import annotations

import io

import httpx
import pytest
from openpyxl import load_workbook
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.workspace.commands import render_result
from fincli.app.workspace.company import ratios
from fincli.app.workspace.models import Instrument
from fincli.app.workspace.service import _may_be_a_stock
from tests.test_command_smoke import SmokeAIProvider, SmokeMarketProvider
from tests.test_equibles_provider import AAPL_EPS, AAPL_PROFILE, AAPL_REVENUE, AAPL_ROUTES, _provider
from tests.workspace_support import company_data

# AAPL's FY2026 (period end 2026-09-26) revenue growth in AAPL_ROUTES: 478,834 versus 416,161.
AAPL_FY2026_GROWTH = (478834 / 416161 - 1) * 100


@pytest.fixture
def router(tmp_path):
    instance = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "finance.db"),
        market_provider=SmokeMarketProvider(),
        ai_provider=SmokeAIProvider(),
    )
    instance.workspace_service.company.loader = company_data
    yield instance
    instance.shutdown()


def _with_equibles(router, routes=AAPL_ROUTES) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    router.market_service.providers.append(_provider(routes, seen))
    return seen


def _one_statement_year(period: str, currency: str = "USD", asset_class: str = "EQUITY"):
    """yfinance statements for a single fiscal year, so its own revenue growth is missing."""

    def loader(symbol):
        data = company_data(symbol)
        data["instrument"]["asset_class"] = asset_class
        for rows in data["statements"].values():
            del rows[1:]
            rows[0].update(period=period, currency=currency)
        data["ratios"] = ratios(data["statements"])
        return data

    return loader


def _no_statements(symbol):
    raise RuntimeError("Too Many Requests")


def test_a_yfinance_growth_figure_is_kept_and_equibles_is_not_asked(router):
    seen = _with_equibles(router)
    row = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")["data"]["rows"][0]
    assert row["metrics"]["revenue_growth"] == pytest.approx(20)
    assert row["metric_sources"] == {}
    assert seen == []


def test_equibles_fills_a_missing_growth_figure_for_the_same_fiscal_year_and_labels_it(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    output = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")
    row = output["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert row["passed"] and row["missing_fields"] == []
    assert row["period"] == "2026-09-30", "the row keeps its yfinance period"
    source = row["metric_sources"]["revenue_growth"]
    assert (source["provider"], source["fiscal_period"], source["period_end"]) == ("equibles", "FY2026", "2026-09-26")
    assert (source["filed_date"], source["currency"], source["basis"]) == ("2026-11-03", "USD", "annual, as filed")
    assert any(w.startswith("revenue_growth from Equibles: FY2026") for w in row["warnings"])
    assert "Equibles" in output["provenance"]["source"]
    console = Console(width=400, record=True)
    console.print(render_result(output))
    label = f"revenue_growth={row['metrics']['revenue_growth']} (Equibles FY2026, USD, filed 2026-11-03) > 10.0"
    assert label in console.export_text()
    assert len(seen) == 3

    book = load_workbook(io.BytesIO(router.workspace_service.excel_bytes(output["data"]["id"])))
    assert book["Screen"]["G1"].value == "Metric sources"
    assert '"fiscal_period": "FY2026"' in book["Screen"]["G2"].value


def test_a_growth_figure_for_another_fiscal_year_is_withheld(router):
    _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2025-09-30")
    output = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")
    row = output["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] is None
    assert row["missing_fields"] == ["revenue_growth"] and not row["passed"]
    assert row["metric_sources"] == {}
    assert any("not the yfinance period 2025-09-30; withheld" in w for w in row["warnings"])
    assert any(w.startswith("AAPL: Equibles revenue growth is for FY2026") for w in output["warnings"])


def test_a_row_without_yfinance_statements_takes_the_equibles_fiscal_year(router):
    _with_equibles(router)
    router.workspace_service.company.loader = _no_statements
    row = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert row["period"] == "2026-09-26"
    assert row["metric_sources"]["revenue_growth"]["fiscal_period"] == "FY2026"
    assert row["metrics"].get("net_margin") is None, "only revenue growth comes from Equibles"


def test_equibles_is_not_asked_when_the_expression_does_not_use_revenue_growth(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    row = router.workspace_service.screen(["AAPL"], "net_margin > 5%")["data"]["rows"][0]
    assert row["metrics"]["revenue_growth"] is None and row["metric_sources"] == {}
    assert seen == []


def test_an_equibles_failure_is_reported_once_and_not_retried_in_the_same_run(router):
    seen = _with_equibles(
        router, {"/v1/stocks/AAPL": httpx.Response(429, json={"error": {"message": "Daily limit reached."}})}
    )
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    output = router.workspace_service.screen(["AAPL", "MSFT"], "revenue_growth > 10%")
    first, second = output["data"]["rows"]

    assert len(seen) == 1, "MSFT is not sent to Equibles after AAPL hit the daily limit"
    assert any("Equibles revenue growth unavailable for this run (RateLimitError" in w for w in first["warnings"])
    assert [w[:45] for w in output["warnings"]] == ["AAPL: Equibles revenue growth unavailable for"]
    assert not any("Equibles" in w for w in second["warnings"])
    assert first["metrics"]["revenue_growth"] is None and second["metrics"]["revenue_growth"] is None


def test_a_symbol_equibles_does_not_list_is_skipped_quietly_and_the_next_one_is_still_asked(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    unlisted, aapl = router.workspace_service.screen(["XYZQ", "AAPL"], "revenue_growth > 10%")["data"]["rows"]

    assert unlisted["metric_sources"] == {} and not any("Equibles" in w for w in unlisted["warnings"])
    assert aapl["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert [r.url.path for r in seen][0] == "/v1/stocks/XYZQ"


def test_a_growth_figure_in_another_currency_than_the_yfinance_statements_is_withheld(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30", currency="EUR")
    output = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")
    row = output["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] is None and row["metric_sources"] == {}
    assert output["warnings"] == ["AAPL: Equibles revenue growth is in USD, not the yfinance statements' EUR; withheld."]
    assert len(seen) == 3


def test_a_row_yfinance_identifies_as_an_etf_or_crypto_is_not_sent_to_equibles(router):
    seen = _with_equibles(router)
    for asset_class in ("ETF", "CRYPTOCURRENCY"):
        router.workspace_service.company.loader = _one_statement_year("2026-09-30", asset_class=asset_class)
        row = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")["data"]["rows"][0]
        assert row["metric_sources"] == {}
    assert seen == []


def test_an_exchange_prefixed_symbol_is_sent_to_equibles_as_its_ticker(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    row = router.workspace_service.screen(["NASDAQ:AAPL"], "revenue_growth > 10%")["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert seen[0].url.path == "/v1/stocks/AAPL"


@pytest.mark.parametrize("currency", ["", None])
def test_a_yfinance_period_without_a_currency_withholds_the_figure_without_asking_equibles(router, currency):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30", currency=currency)
    output = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")
    row = output["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] is None and row["metric_sources"] == {}
    assert output["warnings"] == [
        "AAPL: Equibles revenue growth withheld: the yfinance statements for 2026-09-30 carry no currency to match."
    ]
    assert seen == []


UNITLESS_ROUTES = {
    "/v1/stocks/AAPL": httpx.Response(200, json=AAPL_PROFILE),
    "/v1/stocks/AAPL/financial-facts/revenue": httpx.Response(
        200, json={key: value for key, value in AAPL_REVENUE.items() if key != "unit"}
    ),
    "/v1/stocks/AAPL/financial-facts/eps-diluted": httpx.Response(200, json=AAPL_EPS),
}


def test_revenue_figures_without_a_stated_currency_are_withheld_for_a_row_with_a_yfinance_period(router):
    _with_equibles(router, UNITLESS_ROUTES)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    output = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")

    assert output["data"]["rows"][0]["metrics"]["revenue_growth"] is None
    assert output["warnings"] == [
        "AAPL: Equibles revenue growth withheld: Equibles does not state the currency of its revenue figures, "
        "so it cannot be matched to the yfinance statements' USD."
    ]


def test_without_yfinance_statements_unitless_revenue_growth_is_filled_with_no_currency_in_its_label(router):
    _with_equibles(router, UNITLESS_ROUTES)
    router.workspace_service.company.loader = _no_statements
    row = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert row["metric_sources"]["revenue_growth"]["currency"] is None, "the listing-currency fallback is not shown as filed"


def test_without_yfinance_symbols_that_read_as_indices_currencies_metals_or_crypto_are_not_sent(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _no_statements
    symbols = ["^GSPC", "EURUSD", "XAUUSD", "BTC-USD", "DOGE-USD", "BTCUSD", "ETHUSDT", "BTC/USD"]
    rows = router.workspace_service.screen(symbols, "revenue_growth > 10%")["data"]["rows"]

    assert seen == [] and all(row["metric_sources"] == {} for row in rows)
    router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")
    assert [request.url.path for request in seen][0] == "/v1/stocks/AAPL", "a plain ticker is still asked"


def test_without_yfinance_a_ticker_that_is_also_an_alias_is_still_asked(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _no_statements
    router.workspace_service.screen(["GOLD", "DOW"], "revenue_growth > 10%")
    assert [request.url.path for request in seen] == ["/v1/stocks/GOLD", "/v1/stocks/DOW"], "Barrick Gold and Dow Inc."


def test_a_yfinance_equity_class_wins_over_a_symbol_that_reads_like_a_commodity(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    router.workspace_service.screen(["GOLD"], "revenue_growth > 10%")
    assert seen[0].url.path == "/v1/stocks/GOLD", "NYSE: GOLD is Barrick Gold"


def test_an_instrument_object_without_a_yfinance_class_is_judged_by_its_symbol_shape():
    assert not _may_be_a_stock(Instrument.parse("BTC-USD"), "BTC-USD")
    assert not _may_be_a_stock(Instrument(symbol="QQQ", asset_class="ETF"), "QQQ")
    assert _may_be_a_stock(Instrument.parse("BRK-B"), "BRK-B")
    assert _may_be_a_stock(Instrument.parse("NASDAQ:AAPL"), "NASDAQ:AAPL")
    assert _may_be_a_stock(Instrument.parse("GOLD"), "GOLD")
