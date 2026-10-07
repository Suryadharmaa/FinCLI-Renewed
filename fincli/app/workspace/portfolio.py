"""Currency-aware marked-to-market attribution, explicit shocks and rebalance previews."""

from __future__ import annotations

from typing import Any

from fincli.app.workspace.models import finite, result


def portfolio_intelligence(
    positions: list[dict[str, Any]],
    prices: dict[str, Any],
    base_currency: str = "USD",
    fx: dict[str, Any] | None = None,
    entry_fx: dict[str, Any] | None = None,
    shock: float = 0,
    fx_shock: float = 0,
    fee_bps: float = 0,
) -> dict[str, Any]:
    if not -1 <= shock <= 5 or not -1 <= fx_shock <= 5 or not 0 <= fee_bps <= 10000:
        raise ValueError("Price/FX shocks must be -100% to +500%; fees 0-10000 bps.")
    if (
        not isinstance(prices, dict)
        or fx is not None
        and not isinstance(fx, dict)
        or entry_fx is not None
        and not isinstance(entry_fx, dict)
    ):
        raise ValueError("Prices and FX rates must be JSON objects.")
    if not base_currency.isalpha() or not 3 <= len(base_currency) <= 8:
        raise ValueError("Provide a base currency code, e.g. USD or IDR.")
    base_currency = base_currency.upper()
    fx, entry_fx = fx or {}, entry_fx or {}
    missing: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for p in positions:
        symbol, currency = str(p["symbol"]), str(p.get("currency") or "").upper()
        quantity, cost, price = finite(p["quantity"]), finite(p["average_price"]), finite(prices.get(symbol))
        current_rate = 1.0 if currency == base_currency else finite(fx.get(currency))
        original_rate = 1.0 if currency == base_currency else finite(entry_fx.get(currency))
        if (
            quantity is None
            or quantity < 0
            or cost is None
            or cost < 0
            or price is None
            or price < 0
            or current_rate is None
            or current_rate <= 0
        ):
            missing.append({"symbol": symbol, "reason": "missing/invalid price, position or FX conversion"})
            continue
        value = quantity * price * current_rate
        if finite(value) is None or finite(quantity * cost * current_rate) is None:
            missing.append({"symbol": symbol, "reason": "position valuation overflow"})
            continue
        pnl = quantity * (price - cost)
        row: dict[str, Any] = {
            "symbol": symbol,
            "currency": currency,
            "quantity": quantity,
            "price": price,
            "cost_price": cost,
            "fx_to_base": current_rate,
            "market_value": value,
            "local_unrealized_pnl": pnl,
            "base_unrealized_pnl": quantity * (price * current_rate - cost * original_rate)
            if original_rate and original_rate > 0
            else None,
            "price_contribution": quantity * (price - cost) * original_rate
            if original_rate and original_rate > 0
            else None,
            "fx_contribution": quantity * price * (current_rate - original_rate)
            if original_rate and original_rate > 0
            else None,
            "stressed_value": value * (1 + shock) * (1 + (fx_shock if currency != base_currency else 0)),
        }
        rows.append(row)
    total = sum(r["market_value"] for r in rows)
    for row in rows:
        row["weight_pct"] = row["market_value"] / total * 100 if total else 0
    # Equal weight across valued positions only; withheld when valuation is incomplete.
    rebalance: list[dict[str, Any]] = []
    if not missing and rows and total:
        target = total / len(rows)
        for row in rows:
            delta = target - row["market_value"]
            rebalance.append(
                {
                    "symbol": row["symbol"],
                    "target_weight_pct": 100 / len(rows),
                    "delta_base": delta,
                    "quantity_delta": delta / row["price"] / row["fx_to_base"] if row["price"] > 0 else None,
                }
            )
    turnover = sum(abs(r["delta_base"]) for r in rebalance)
    complete_attribution = not missing and all(r["base_unrealized_pnl"] is not None for r in rows)
    return result(
        "portfolio_intelligence",
        {
            "base_currency": base_currency,
            "positions": rows,
            "unvalued": missing,
            "valued_total": total,
            "total_value": total if not missing else None,
            "unrealized_pnl": sum(r["base_unrealized_pnl"] for r in rows) if complete_attribution else None,
            "scenario": {
                "price_shock": shock,
                "fx_shock": fx_shock,
                "stressed_valued_total": sum(r["stressed_value"] for r in rows),
                "delta": sum(r["stressed_value"] for r in rows) - total,
                "method": "uniform hypothetical shock, not a forecast",
            },
            "rebalance_preview": rebalance,
            "gross_turnover": turnover,
            "estimated_fees": turnover * fee_bps / 10000,
            "attribution_method": "unrealized since average cost; price at entry FX plus FX at current price; excludes dividends, cash flows and realized trades",
        },
        status="partial" if missing or not complete_attribution else "ok",
        warnings=["Incomplete positions/FX: portfolio total and rebalance withheld."]
        if missing
        else ["Entry FX missing: affected historical PnL attribution withheld."]
        if not complete_attribution
        else [],
    )


def compare_fixed_holdings(
    positions, histories, benchmark_symbol, benchmark_currency, base_currency="USD", start_fx=None, end_fx=None
):
    """Compare the same intersected close dates using fixed current holdings, not realized performance."""
    base_currency = base_currency.upper()
    start_fx, end_fx = start_fx or {}, end_fx or {}
    symbols = [p["symbol"] for p in positions] + [benchmark_symbol]
    dates = None
    for symbol in symbols:
        valid = {d for d, value in histories.get(symbol, {}).items() if finite(value) is not None and float(value) > 0}
        dates = valid if dates is None else dates & valid
    method = "Fixed current quantities on common close dates; excludes trades, cash flows and separately accounted dividends. Provider-adjusted price returns in the same base currency; adjustment conventions may incorporate splits/dividends. FX rates must match window endpoints."
    if not positions or not dates or len(dates) < 2:
        return {
            "status": "partial",
            "method": method,
            "reason": "At least two shared close dates and valued holdings are required.",
        }
    first, last = min(dates), max(dates)

    def rates(currency):
        if currency.upper() == base_currency:
            return 1.0, 1.0
        return finite(start_fx.get(currency.upper())), finite(end_fx.get(currency.upper()))

    start_value, end_value = 0.0, 0.0
    for p in positions:
        a, b = rates(p.get("currency") or "")
        quantity = finite(p["quantity"])
        if a is None or b is None or a <= 0 or b <= 0 or quantity is None or quantity < 0:
            return {
                "status": "partial",
                "method": method,
                "reason": "Window endpoint FX/quantity missing; comparison withheld.",
            }
        start_value += quantity * histories[p["symbol"]][first] * a
        end_value += quantity * histories[p["symbol"]][last] * b
    a, b = rates(benchmark_currency or "")
    if not start_value or a is None or b is None or a <= 0 or b <= 0:
        return {
            "status": "partial",
            "method": method,
            "reason": "Benchmark currency/FX or initial portfolio value unavailable.",
        }
    portfolio_return = (end_value / start_value - 1) * 100
    benchmark_return = (histories[benchmark_symbol][last] * b / (histories[benchmark_symbol][first] * a) - 1) * 100
    return {
        "status": "ok",
        "start": first,
        "end": last,
        "base_currency": base_currency,
        "benchmark": benchmark_symbol,
        "portfolio_return_pct": portfolio_return,
        "benchmark_return_pct": benchmark_return,
        "excess_return_pp": portfolio_return - benchmark_return,
        "method": method,
    }
