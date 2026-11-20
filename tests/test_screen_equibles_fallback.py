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
from tests.test_command_smoke import SmokeAIProvider, SmokeMarketProvider
from tests.test_equibles_provider import AAPL_ROUTES, _provider
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


def _one_statement_year(period: str):
    """yfinance statements for a single fiscal year, so its own revenue growth is missing."""

    def loader(symbol):
        data = company_data(symbol)
        for rows in data["statements"].values():
            del rows[1:]
            rows[0]["period"] = period
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
    assert f"revenue_growth={row['metrics']['revenue_growth']} (Equibles FY2026, as filed) > 10.0" in console.export_text()
    assert len(seen) == 3

    book = load_workbook(io.BytesIO(router.workspace_service.excel_bytes(output["data"]["id"])))
    assert book["Screen"]["G1"].value == "Metric sources"
    assert '"fiscal_period": "FY2026"' in book["Screen"]["G2"].value


def test_a_growth_figure_for_another_fiscal_year_is_withheld(router):
    _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2025-09-30")
    row = router.workspace_service.screen(["AAPL"], "revenue_growth > 10%")["data"]["rows"][0]

    assert row["metrics"]["revenue_growth"] is None
    assert row["missing_fields"] == ["revenue_growth"] and not row["passed"]
    assert row["metric_sources"] == {}
    assert any("not the yfinance period 2025-09-30; withheld" in w for w in row["warnings"])


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
    first, second = router.workspace_service.screen(["AAPL", "MSFT"], "revenue_growth > 10%")["data"]["rows"]

    assert len(seen) == 1, "MSFT is not sent to Equibles after AAPL hit the daily limit"
    assert any("Equibles revenue growth unavailable for this run (RateLimitError" in w for w in first["warnings"])
    assert not any("Equibles" in w for w in second["warnings"])
    assert first["metrics"]["revenue_growth"] is None and second["metrics"]["revenue_growth"] is None


def test_a_symbol_equibles_does_not_list_is_skipped_quietly_and_the_next_one_is_still_asked(router):
    seen = _with_equibles(router)
    router.workspace_service.company.loader = _one_statement_year("2026-09-30")
    unlisted, aapl = router.workspace_service.screen(["XYZQ", "AAPL"], "revenue_growth > 10%")["data"]["rows"]

    assert unlisted["metric_sources"] == {} and not any("Equibles" in w for w in unlisted["warnings"])
    assert aapl["metrics"]["revenue_growth"] == pytest.approx(AAPL_FY2026_GROWTH)
    assert [r.url.path for r in seen][0] == "/v1/stocks/XYZQ"
