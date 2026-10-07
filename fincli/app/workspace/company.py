"""Company financial statements, aligned peer metrics and explicit-assumption DCF."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from fincli.app.workspace.models import Instrument, finite, now_iso, result

FIELDS = {
    "revenue": ("income", "Total Revenue"),
    "net_income": ("income", "Net Income"),
    "operating_income": ("income", "Operating Income"),
    "equity": ("balance", "Stockholders Equity"),
    "debt": ("balance", "Total Debt"),
    "cash": ("balance", "Cash And Cash Equivalents"),
    "free_cash_flow": ("cashflow", "Free Cash Flow"),
    "pretax": ("income", "Pretax Income"),
    "tax": ("income", "Tax Provision"),
}


def ratios(statements: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, float | None]] = {}
    for key, (section, label) in FIELDS.items():
        values[key] = {r["period"]: r["values"].get(label) for r in statements.get(section, [])}
    currencies = {r["period"]: r.get("currency") for r in statements.get("income", [])}
    rows = []
    periods = sorted(values["revenue"], reverse=True)
    for index, period in enumerate(periods):
        v = {k: by_period.get(period) for k, by_period in values.items()}
        rev = v["revenue"]
        prior = values["revenue"].get(periods[index + 1]) if index + 1 < len(periods) else None
        equity = v["equity"]
        previous_equity = values["equity"].get(periods[index + 1]) if index + 1 < len(periods) else None
        average_equity = (equity + previous_equity) / 2 if equity is not None and previous_equity is not None else None
        previous = periods[index + 1] if index + 1 < len(periods) else None

        def invested(p):
            e, d, c = (values[k].get(p) for k in ("equity", "debt", "cash"))
            return e + d - c if e is not None and d is not None and c is not None else None

        current_capital, prior_capital = invested(period), invested(previous)
        average_capital = (
            (current_capital + prior_capital) / 2 if current_capital is not None and prior_capital is not None else None
        )
        tax_rate = v["tax"] / v["pretax"] if v["tax"] is not None and v["pretax"] and v["pretax"] > 0 else None
        roic = (
            v["operating_income"] * (1 - tax_rate) / average_capital * 100
            if v["operating_income"] is not None
            and tax_rate is not None
            and 0 <= tax_rate <= 1
            and average_capital
            and average_capital > 0
            else None
        )
        rows.append(
            {
                "period": period,
                "kind": "calculated_from_actuals",
                "currency": currencies.get(period),
                "revenue_growth": (rev / prior - 1) * 100 if rev is not None and prior and prior > 0 else None,
                "net_margin": v["net_income"] / rev * 100 if v["net_income"] is not None and rev and rev > 0 else None,
                "operating_margin": v["operating_income"] / rev * 100
                if v["operating_income"] is not None and rev and rev > 0
                else None,
                "debt_to_equity": v["debt"] / equity if v["debt"] is not None and equity and equity > 0 else None,
                "roe": v["net_income"] / average_equity * 100
                if v["net_income"] is not None and average_equity and average_equity > 0
                else None,
                "roic": roic,
                "free_cash_flow": v["free_cash_flow"],
            }
        )
    return rows


class CompanyService:
    def __init__(self, timeout: float = 15, loader=None):
        self.timeout = timeout
        self.loader = loader or self._load
        self._slots = asyncio.Semaphore(3)

    async def get(self, symbol: str) -> dict[str, Any]:
        instrument = Instrument.parse(symbol)
        async with self._slots:
            try:
                data = await asyncio.wait_for(asyncio.to_thread(self.loader, instrument.provider_symbol), self.timeout)
            except Exception as exc:  # provider boundaries may raise library-specific errors
                return result(
                    "company",
                    {
                        "instrument": instrument,
                        "statements": {},
                        "ratios": [],
                        "missing": ["financials", "events", "profile"],
                    },
                    symbol=instrument.symbol,
                    source="yfinance",
                    warnings=[f"Company data unavailable ({type(exc).__name__})."],
                    status="partial",
                )
        return result(
            "company",
            data,
            symbol=instrument.symbol,
            source="yfinance",
            warnings=data.get("warnings", []),
            status="partial" if data.get("missing") else "ok",
        )

    @staticmethod
    def _load(symbol: str) -> dict[str, Any]:
        from fincli.app.providers.market.yfinance_provider import YFinanceProvider

        ticker = YFinanceProvider()._ticker(symbol)
        info = ticker.info or {}
        currency = str(info.get("financialCurrency") or info.get("currency") or "")
        statements: dict[str, list[dict[str, Any]]] = {}
        warnings = []
        for name, attr in (("income", "income_stmt"), ("balance", "balance_sheet"), ("cashflow", "cashflow")):
            try:
                frame = getattr(ticker, attr)
                statements[name] = (
                    [
                        {
                            "period": str(column.date()) if hasattr(column, "date") else str(column),
                            "kind": "actual",
                            "currency": currency,
                            "unit": "currency units",
                            "values": {str(label): finite(frame.loc[label, column]) for label in frame.index},
                        }
                        for column in sorted(frame.columns, reverse=True)[:5]
                    ]
                    if frame is not None
                    else []
                )
            except Exception:  # noqa: BLE001 - one unavailable statement must not discard the others
                statements[name] = []
                warnings.append(f"{name} statement unavailable.")
        missing = [name for name, rows in statements.items() if not rows]
        missing.append("consensus_estimates")
        events = []
        try:
            calendar = ticker.calendar
            if isinstance(calendar, dict):
                events = [
                    {"event": str(k), "value": str(v), "kind": "provider-reported"}
                    for k, v in calendar.items()
                    if "Earnings" in k or "Dividend" in k
                ]
        except Exception:  # noqa: BLE001
            missing.append("calendar")
        return {
            "instrument": {
                "symbol": symbol,
                "exchange": info.get("exchange", ""),
                "currency": info.get("currency", ""),
                "asset_class": info.get("quoteType", "unknown"),
            },
            "profile": {
                k: info.get(k)
                for k in (
                    "longName",
                    "longBusinessSummary",
                    "sector",
                    "industry",
                    "marketCap",
                    "trailingPE",
                    "sharesOutstanding",
                    "totalCash",
                    "totalDebt",
                )
            },
            "statements": statements,
            "ratios": ratios(statements),
            "events": events,
            "missing": missing,
            "as_of": now_iso(),
            "financial_currency": currency,
            "warnings": warnings,
            "ratio_method": "Annual actuals. ROE uses average equity; ROIC uses EBIT times (1 - effective tax rate), divided by average equity + debt - cash. Missing inputs are withheld.",
            "source_url": f"https://finance.yahoo.com/quote/{ticker.ticker}/financials/",
        }

    async def peers(self, symbols: list[str]) -> dict[str, Any]:
        if not isinstance(symbols, list) or not 2 <= len(symbols) <= 8 or any(not isinstance(s, str) for s in symbols):
            raise ValueError("Compare 2-8 companies.")
        companies = await asyncio.gather(*(self.get(s) for s in symbols))
        common: set[str] | None = None
        for company in companies:
            periods = {r["period"] for r in company["data"]["ratios"]}
            common = periods if common is None else common & periods
        period = max(common) if common else None
        rows = [
            {
                "symbol": c["symbol"],
                "financial_currency": c["data"].get("financial_currency"),
                "metrics": next((r for r in c["data"]["ratios"] if r["period"] == period), None),
            }
            for c in companies
        ]
        return result(
            "peers",
            {"period": period, "rows": rows},
            source="yfinance",
            status="ok" if period else "partial",
            warnings=[] if period else ["No common fiscal period; comparison withheld. Choose aligned companies."],
        )


def dcf(
    fcf: float,
    growth: float,
    discount: float,
    terminal: float,
    years: int = 5,
    cash: float = 0,
    debt: float = 0,
    shares: float | None = None,
) -> dict[str, Any]:
    inputs = [fcf, growth, discount, terminal, cash, debt]
    if any(finite(x) is None for x in inputs) or shares is not None and (finite(shares) is None or shares <= 0):
        raise ValueError("DCF inputs must be finite; shares must be positive.")
    if (
        fcf <= 0
        or not isinstance(years, int)
        or isinstance(years, bool)
        or not 1 <= years <= 20
        or not -1 < growth <= 1
        or not 0 < discount <= 1
        or not -1 < terminal < discount
        or cash < 0
        or debt < 0
    ):
        raise ValueError(
            "Require positive FCF, 1-20 years, discount > terminal growth, and nonnegative cash/debt. Rates are decimals."
        )

    def calculate(g, d):
        forecasts = [fcf * (1 + g) ** year for year in range(1, years + 1)]
        enterprise = (
            sum(v / (1 + d) ** year for year, v in enumerate(forecasts, 1))
            + forecasts[-1] * (1 + terminal) / (d - terminal) / (1 + d) ** years
        )
        if not math.isfinite(enterprise) or not math.isfinite(enterprise + cash - debt):
            raise ValueError("DCF assumptions overflow.")
        if shares and not math.isfinite((enterprise + cash - debt) / shares):
            raise ValueError("DCF per-share value overflow.")
        return {
            "enterprise_value": enterprise,
            "equity_value": enterprise + cash - debt,
            "per_share": (enterprise + cash - debt) / shares if shares else None,
            "cashflows": forecasts,
        }

    base = calculate(growth, discount)
    if any(not math.isfinite(v) for v in base["cashflows"]):
        raise ValueError("DCF assumptions overflow.")
    sensitivity = [
        {"growth": g, "discount": d, **calculate(g, d)}
        for g in (growth - 0.01, growth, growth + 0.01)
        for d in (discount - 0.01, discount, discount + 0.01)
        if g > -1 and d > terminal and d > 0
    ]
    return result(
        "valuation",
        {
            "assumptions": {
                "unlevered_fcf": fcf,
                "growth": growth,
                "discount": discount,
                "terminal_growth": terminal,
                "years": years,
                "cash": cash,
                "debt": debt,
                "shares": shares,
            },
            **base,
            "sensitivity": sensitivity,
        },
        warnings=[
            "User-supplied unlevered FCF model; not a provider estimate. Match all monetary inputs and shares to the same currency/date."
        ],
    )
