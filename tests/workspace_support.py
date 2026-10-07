"""Offline company fixtures shared by registry and workspace tests."""

from datetime import UTC, datetime

from fincli.app.providers.market.base import Quote
from fincli.app.providers.market.yfinance_provider import YahooTable, YFinanceProvider
from fincli.app.workspace.company import ratios


def company_data(symbol):
    statements = {"income": [], "balance": [], "cashflow": []}
    for period, revenue in (("2025-12-31", 120), ("2024-12-31", 100)):
        for section, values in {
            "income": {
                "Total Revenue": revenue,
                "Net Income": 20,
                "Operating Income": 30,
                "Pretax Income": 25,
                "Tax Provision": 5,
            },
            "balance": {"Stockholders Equity": 100, "Total Debt": 50, "Cash And Cash Equivalents": 20},
            "cashflow": {"Free Cash Flow": 24},
        }.items():
            statements[section].append({"period": period, "currency": "USD", "kind": "actual", "values": values})
    return {
        "instrument": {"symbol": symbol},
        "statements": statements,
        "ratios": ratios(statements),
        "profile": {"longBusinessSummary": "Offline company fixture", "marketCap": 1000, "trailingPE": 12},
        "financial_currency": "USD",
        "events": [],
        "missing": ["consensus_estimates"],
    }


def configure_smoke(router, monkeypatch):
    router.workspace_service.company.loader = company_data

    async def yahoo(self, symbol, section="summary", **kwargs):
        return YahooTable(
            symbol, section, ["Metric", "Value"], [["Name", "Offline fixture"]], "https://finance.yahoo.com/"
        )

    monkeypatch.setattr(YFinanceProvider, "yahoo_table", yahoo)


def workspace_smoke_commands(router, directory):
    doc = directory / "research.txt"
    doc.write_text("Margin risk increased due to higher input costs.", encoding="utf-8")
    job = router.workspace_service.jobs.submit(lambda context: {"ok": True}, "smoke")
    return {
        "/workspace": "/workspace layouts",
        "/company": "/company AAPL",
        "/company peers": "/company peers AAPL MSFT",
        "/document list": "/document list",
        "/document import": f'/document import "{doc}" AAPL',
        "/document search": "/document search margin risk",
        "/workflow": "/workflow Analyze AAPL",
        "/screen": '/screen AAPL,MSFT --where "revenue_growth > 10%"',
        "/valuation": "/valuation 100 0.05 0.10 0.02",
        "/portfolio intelligence": "/portfolio intelligence",
        "/tv": "/tv capabilities",
        "/jobs": f"/jobs show {job['id']}",
    }


def mock_quote(symbol):
    return Quote(symbol, 150, "USD", "offline", datetime.now(UTC), "ok")
