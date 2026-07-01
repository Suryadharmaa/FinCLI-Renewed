"""Portfolio Risk v2 analytics."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from fincli.app.modules.user_profile import UserProfile


@dataclass(frozen=True, slots=True)
class AssetClassExposure:
    asset_class: str
    market_value: float
    weight: float
    count: int


@dataclass(frozen=True, slots=True)
class CurrencyExposure:
    currency: str
    market_value: float
    weight: float
    count: int


@dataclass(frozen=True, slots=True)
class ConcentrationRisk:
    top_symbol: str
    top_weight: float
    level: str
    note: str


@dataclass(frozen=True, slots=True)
class PortfolioHealth:
    score: int
    label: str
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssetClassWarning:
    asset_class: str
    weight: float
    cap: float
    level: str
    note: str


@dataclass(frozen=True, slots=True)
class RiskBudget:
    profile_gameplay: str
    equity: float
    currency: str
    risk_per_trade: float
    max_portfolio_risk: float
    note: str


@dataclass(frozen=True, slots=True)
class ValueAtRisk:
    """Value at Risk estimate."""
    historical_var_95: float  # 95% confidence VaR
    historical_var_99: float  # 99% confidence VaR
    parametric_var_95: float  # Parametric (Gaussian) VaR at 95%
    parametric_var_99: float  # Parametric (Gaussian) VaR at 99%
    note: str


@dataclass(frozen=True, slots=True)
class PortfolioRiskReport:
    total_cost_basis: float
    total_market_value: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    exposure_by_asset_class: dict[str, AssetClassExposure]
    currency_exposure: dict[str, CurrencyExposure]
    concentration: ConcentrationRisk
    health: PortfolioHealth
    drawdown_estimate: float
    asset_class_warnings: tuple[AssetClassWarning, ...]
    risk_budget: RiskBudget
    value_at_risk: ValueAtRisk | None = None


def build_portfolio_risk(
    positions: list[dict[str, object]],
    market_values: dict[str, tuple[float | None, float | None, float | None]],
    realized_pnl: float,
    profile: UserProfile | None = None,
) -> PortfolioRiskReport:
    """Build exposure, concentration, PnL, and health score from positions."""
    total_cost_basis = 0.0
    total_market_value = 0.0
    unrealized_pnl = 0.0
    exposure_values: dict[str, float] = {}
    exposure_counts: dict[str, int] = {}
    currency_values: dict[str, float] = {}
    currency_counts: dict[str, int] = {}
    symbol_values: dict[str, float] = {}
    missing_prices = 0

    for row in positions:
        symbol = str(row["symbol"]).upper()
        quantity = float(row["quantity"])
        average_price = float(row["average_price"])
        cost_basis = quantity * average_price
        total_cost_basis += cost_basis

        current_price, pnl, _pnl_percent = market_values.get(symbol, (None, None, None))
        if current_price is None:
            missing_prices += 1
            market_value = cost_basis
        else:
            market_value = quantity * current_price
        total_market_value += market_value
        if pnl is not None:
            unrealized_pnl += pnl

        asset_class = classify_asset_class(symbol)
        exposure_values[asset_class] = exposure_values.get(asset_class, 0.0) + market_value
        exposure_counts[asset_class] = exposure_counts.get(asset_class, 0) + 1
        currency = str(row.get("currency", "USD")).upper()
        currency_values[currency] = currency_values.get(currency, 0.0) + market_value
        currency_counts[currency] = currency_counts.get(currency, 0) + 1
        symbol_values[symbol] = market_value

    exposure_by_asset_class = {
        asset_class: AssetClassExposure(
            asset_class=asset_class,
            market_value=value,
            weight=_weight(value, total_market_value),
            count=exposure_counts.get(asset_class, 0),
        )
        for asset_class, value in sorted(exposure_values.items())
    }
    currency_exposure = {
        currency: CurrencyExposure(
            currency=currency,
            market_value=value,
            weight=_weight(value, total_market_value),
            count=currency_counts.get(currency, 0),
        )
        for currency, value in sorted(currency_values.items())
    }
    concentration = _concentration(symbol_values, total_market_value)
    total_pnl = realized_pnl + unrealized_pnl
    drawdown_estimate = _drawdown_estimate(unrealized_pnl, total_cost_basis)
    warnings = _asset_class_warnings(exposure_by_asset_class)
    risk_budget = _risk_budget(profile)
    health = _health_score(
        positions_count=len(positions),
        top_weight=concentration.top_weight,
        missing_prices=missing_prices,
        total_pnl=total_pnl,
        total_cost_basis=total_cost_basis,
        asset_class_count=len(exposure_by_asset_class),
        drawdown_estimate=drawdown_estimate,
        warning_count=len(warnings),
    )
    var = calculate_var(market_values, total_market_value)
    return PortfolioRiskReport(
        total_cost_basis=total_cost_basis,
        total_market_value=total_market_value,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        exposure_by_asset_class=exposure_by_asset_class,
        currency_exposure=currency_exposure,
        concentration=concentration,
        health=health,
        drawdown_estimate=drawdown_estimate,
        asset_class_warnings=warnings,
        risk_budget=risk_budget,
        value_at_risk=var,
    )


def classify_asset_class(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized.endswith("-USD") or normalized.endswith("USDT") or normalized in {"BTC", "ETH", "SOL", "BNB"}:
        return "crypto"
    if normalized.endswith("=X") or len(normalized) == 6 and normalized.isalpha():
        return "forex"
    if normalized.startswith("^") or normalized in {"SPX", "NASDAQ", "DJI", "DAX", "NIKKEI", "HSI"}:
        return "index"
    if normalized.endswith("=F") or normalized in {"XAUUSD", "XAGUSD", "WTI", "BRENT", "GOLD", "SILVER"}:
        return "commodity"
    if normalized.endswith(".JK") or normalized.endswith(".L") or normalized.endswith(".TO") or normalized.isalpha():
        return "equity"
    return "other"


def _concentration(symbol_values: dict[str, float], total_market_value: float) -> ConcentrationRisk:
    if not symbol_values or total_market_value <= 0:
        return ConcentrationRisk("-", 0.0, "empty", "No market value available.")
    top_symbol, top_value = max(symbol_values.items(), key=lambda item: item[1])
    top_weight = _weight(top_value, total_market_value)
    if top_weight >= 60:
        level = "high"
        note = "Top position dominates portfolio."
    elif top_weight >= 35:
        level = "medium"
        note = "Top position needs monitoring."
    else:
        level = "healthy"
        note = "No single position dominates."
    return ConcentrationRisk(top_symbol, top_weight, level, note)


def _health_score(
    positions_count: int,
    top_weight: float,
    missing_prices: int,
    total_pnl: float,
    total_cost_basis: float,
    asset_class_count: int,
    drawdown_estimate: float,
    warning_count: int,
) -> PortfolioHealth:
    score = 100
    notes: list[str] = []
    if positions_count == 0:
        return PortfolioHealth(0, "empty", ("No positions.",))
    if positions_count < 3:
        score -= 15
        notes.append("few positions")
    if asset_class_count < 2:
        score -= 10
        notes.append("single asset class")
    if top_weight >= 60:
        score -= 25
        notes.append("high concentration")
    elif top_weight >= 35:
        score -= 10
        notes.append("medium concentration")
    if missing_prices:
        score -= min(30, missing_prices * 10)
        notes.append(f"{missing_prices} missing price(s)")
    if warning_count:
        score -= min(20, warning_count * 8)
        notes.append(f"{warning_count} asset-class cap warning(s)")
    if drawdown_estimate <= -25:
        score -= 15
        notes.append("deep drawdown estimate")
    pnl_ratio = (total_pnl / total_cost_basis * 100) if total_cost_basis else 0.0
    if pnl_ratio <= -20:
        score -= 20
        notes.append("large drawdown")
    elif pnl_ratio < 0:
        score -= 8
        notes.append("negative total PnL")

    score = max(0, min(100, score))
    if score >= 80:
        label = "healthy"
    elif score >= 60:
        label = "watch"
    elif score >= 40:
        label = "caution"
    else:
        label = "high risk"
    return PortfolioHealth(score, label, tuple(notes) or ("balanced baseline",))


def _weight(value: float, total: float) -> float:
    return (value / total * 100) if total else 0.0


def _drawdown_estimate(unrealized_pnl: float, total_cost_basis: float) -> float:
    if total_cost_basis <= 0:
        return 0.0
    return min(0.0, unrealized_pnl / total_cost_basis * 100)


def _asset_class_warnings(exposures: dict[str, AssetClassExposure]) -> tuple[AssetClassWarning, ...]:
    caps = {"crypto": 25.0, "forex": 40.0, "commodity": 35.0, "index": 50.0, "equity": 70.0, "other": 25.0}
    warnings: list[AssetClassWarning] = []
    for exposure in exposures.values():
        cap = caps.get(exposure.asset_class, 25.0)
        if exposure.weight > cap:
            warnings.append(
                AssetClassWarning(
                    asset_class=exposure.asset_class,
                    weight=exposure.weight,
                    cap=cap,
                    level="high" if exposure.weight >= cap + 20 else "watch",
                    note=f"{exposure.asset_class} exposure {exposure.weight:.2f}% exceeds cap {cap:.2f}%.",
                )
            )
    return tuple(warnings)


def _risk_budget(profile: UserProfile | None) -> RiskBudget:
    if profile is None:
        return RiskBudget("unprofiled", 0.0, "USD", 0.0, 0.0, "Run /profile set to enable risk budget.")
    gameplay = profile.gameplay
    if gameplay == "Scalper":
        per_trade_pct = 1.0
        max_portfolio_pct = 5.0
    elif gameplay == "Intra day":
        per_trade_pct = 1.25
        max_portfolio_pct = 7.5
    elif gameplay == "Day trade":
        per_trade_pct = 1.5
        max_portfolio_pct = 10.0
    else:
        per_trade_pct = 2.0
        max_portfolio_pct = 12.0
    return RiskBudget(
        profile_gameplay=gameplay,
        equity=profile.equity,
        currency=profile.currency,
        risk_per_trade=profile.equity * per_trade_pct / 100,
        max_portfolio_risk=profile.equity * max_portfolio_pct / 100,
        note=f"{per_trade_pct:.2f}% per trade, {max_portfolio_pct:.2f}% max portfolio risk budget.",
    )


def calculate_var(
    market_values: dict[str, tuple[float | None, float | None, float | None]],
    total_market_value: float,
    daily_returns: list[float] | None = None,
) -> ValueAtRisk:
    """Calculate Value at Risk (VaR) using historical and parametric methods.

    Args:
        market_values: Dict of symbol -> (current_price, pnl, pnl_percent)
        total_market_value: Total portfolio market value
        daily_returns: Optional list of daily returns. If None, estimates from position PnL.

    Returns:
        ValueAtRisk with historical and parametric estimates at 95% and 99% confidence.
    """
    if total_market_value <= 0:
        return ValueAtRisk(0.0, 0.0, 0.0, 0.0, "No market value for VaR calculation.")

    # Estimate returns from position PnL if daily returns not provided
    if daily_returns is None:
        returns = []
        for _symbol, (_price, pnl, pnl_pct) in market_values.items():
            if pnl_pct is not None:
                returns.append(pnl_pct / 100)
        if not returns:
            return ValueAtRisk(0.0, 0.0, 0.0, 0.0, "No return data for VaR calculation.")
    else:
        returns = daily_returns

    # Sort returns for historical VaR
    sorted_returns = sorted(returns)
    n = len(sorted_returns)

    # Historical VaR (percentile method)
    var_95_idx = max(0, int(n * 0.05) - 1)
    var_99_idx = max(0, int(n * 0.01) - 1)
    hist_var_95 = abs(sorted_returns[var_95_idx]) * total_market_value
    hist_var_99 = abs(sorted_returns[var_99_idx]) * total_market_value

    # Parametric VaR (Gaussian assumption)
    mean_return = sum(returns) / n
    variance = sum((r - mean_return) ** 2 for r in returns) / n
    std_return = sqrt(variance)

    # Z-scores for confidence levels
    z_95 = 1.645  # 95% confidence
    z_99 = 2.326  # 99% confidence

    param_var_95 = (z_95 * std_return - mean_return) * total_market_value
    param_var_99 = (z_99 * std_return - mean_return) * total_market_value

    # Ensure non-negative
    param_var_95 = max(0.0, param_var_95)
    param_var_99 = max(0.0, param_var_99)

    note = f"Based on {n} position(s). Historical uses percentile method; parametric assumes normal distribution."

    return ValueAtRisk(
        historical_var_95=hist_var_95,
        historical_var_99=hist_var_99,
        parametric_var_95=param_var_95,
        parametric_var_99=param_var_99,
        note=note,
    )


def calculate_correlation_matrix(
    symbols: list[str],
    price_history: dict[str, list[float]],
) -> dict[str, dict[str, float]]:
    """Calculate pairwise correlation matrix between symbols.

    Args:
        symbols: List of symbol names
        price_history: Dict of symbol -> list of historical prices

    Returns:
        Nested dict: correlation_matrix[symbol_a][symbol_b] = correlation coefficient
    """
    returns: dict[str, list[float]] = {}
    for symbol in symbols:
        prices = price_history.get(symbol, [])
        if len(prices) < 2:
            returns[symbol] = []
            continue
        symbol_returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                symbol_returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
        returns[symbol] = symbol_returns

    # Find minimum length for alignment
    min_len = min((len(r) for r in returns.values() if r), default=0)
    if min_len < 2:
        return {s1: {s2: 0.0 for s2 in symbols} for s1 in symbols}

    # Truncate all returns to same length
    for symbol in symbols:
        if returns[symbol]:
            returns[symbol] = returns[symbol][:min_len]

    # Calculate correlations
    result: dict[str, dict[str, float]] = {}
    for s1 in symbols:
        result[s1] = {}
        for s2 in symbols:
            if s1 == s2:
                result[s1][s2] = 1.0
            elif not returns[s1] or not returns[s2]:
                result[s1][s2] = 0.0
            else:
                result[s1][s2] = _pearson_correlation(returns[s1], returns[s2])

    return result


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Calculate Pearson correlation coefficient between two lists."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0

    x = x[:n]
    y = y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    denom_x = sqrt(sum((xi - mean_x) ** 2 for xi in x))
    denom_y = sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if denom_x == 0 or denom_y == 0:
        return 0.0

    return numerator / (denom_x * denom_y)
