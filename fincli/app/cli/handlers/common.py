"""Command parsing and routing."""

from __future__ import annotations

import getpass
import io
import logging
import os
import shlex
from datetime import UTC, date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from fincli.app.analysis.technical_debate import TechnicalDebate, format_debate
from fincli.app.analysis.technical_signal import TechnicalSignal, format_signal
from fincli.app.diagnostics.capabilities import capability_rows, capability_summary
from fincli.app.modules.economic_calendar import (
    EconomicEvent,
    calendar_summary,
    default_calendar_window,
)
from fincli.app.modules.session_history import relative_time
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.market.symbols import SymbolResolver
from fincli.app.providers.reliability import (
    STATUS_OK,
    STATUS_PARTIAL_DATA,
    STATUS_SCHEDULE_ONLY,
    STATUS_UNAVAILABLE,
)
from fincli.app.services.data_quality import DataQualityReport
from fincli.app.services.macro_data import MacroIndicator
from fincli.app.storage.secrets import read_secrets
from fincli.app.utils.errors import CommandError, FinCLIError
from fincli.app.utils.formatting import AIResponseView, semantic_text

if TYPE_CHECKING:
    from fincli.app.agents.registry import Agent
    from fincli.app.analysis.backtest import BacktestResult
    from fincli.app.analysis.indicators import TechnicalSummary
    from fincli.app.analysis.market_structure import MarketStructureSummary
    from fincli.app.analysis.multi_timeframe import MultiTimeframeAnalysis
    from fincli.app.connectors.catalog import Connector
    from fincli.app.connectors.news_connectors import (
        NewsConnectorSpec,
    )
    from fincli.app.modules.alerts import AlertCheckResult
    from fincli.app.modules.journal_analytics import JournalStats
    from fincli.app.modules.portfolio_risk import PortfolioRiskReport
    from fincli.app.modules.scanner import ScanResult
    from fincli.app.modules.trading import (
        BrokerCatalog,
        BrokerIntegration,
        PaperTradingEngine,
        RealtimeConnector,
        RealtimeConnectorCatalog,
    )
    from fincli.app.modules.user_profile import UserProfile
    from fincli.app.plugins.loader import PluginManifest
    from fincli.app.providers.ai.base import AIRequest, AIResponse
    from fincli.app.providers.market.base import (
        FundamentalSnapshot,
        NewsItem,
        ProviderEntitlement,
        Quote,
        SymbolSearchResult,
    )
    from fincli.app.providers.market.yfinance_provider import YahooTable
    from fincli.app.services.market_data import MarketDataService
    from fincli.app.services.market_overview import MarketOverview
    from fincli.app.services.news_aggregator import NewsDesk
    from fincli.app.services.web_research import (
        WebSearchResult,
    )

logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


def _format_theme_current(current: object, all_themes: list[object]) -> Table:
    table = Table(title="FinCLI Theme", expand=True, show_lines=False)
    table.add_column("Current", style="white", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_row(str(current.name), str(current.description))
    table.caption = "/theme <name> to change. /theme list for all."
    return table


def _format_theme_list(themes: list[object]) -> Table:
    table = Table(title="Available Themes", expand=True, show_lines=False)
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Preview", style="white")
    table.add_column("Description", style="dim")
    for idx, theme in enumerate(themes, 1):
        preview = f"[{theme.accent}]███[/{theme.accent}]"
        table.add_row(str(idx), theme.name, preview, theme.description)
    table.caption = "/theme <name> to change theme"
    return table


def _format_quote(quote: Quote) -> str:
    price = "N/A" if quote.price is None else f"{quote.price:,.4f}"
    return (
        f"Quote: {quote.symbol}\n"
        f"Price: {price} {quote.currency}\n"
        f"Provider: {quote.provider}\n"
        f"Status: {quote.status}\n"
        f"Timestamp: {quote.timestamp.isoformat(timespec='seconds')}\n"
        "Catatan: yfinance fallback biasanya delayed, bukan realtime."
    )


def _format_sessions(sessions: list[dict[str, object]], current_session_id: str) -> Table:
    table = Table(title="FinCLI Sessions", expand=True)
    table.add_column("Current", justify="center", width=7)
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Events", justify="right")
    table.add_column("Updated", style="dim")
    for session in sessions:
        session_id = str(session["id"])
        table.add_row(
            "*" if session_id == current_session_id else "",
            session_id,
            str(session["title"]),
            str(session["event_count"]),
            str(session["updated_at"]),
        )
    if not sessions:
        table.add_row("-", "-", "No sessions yet.", "0", "-")
    table.caption = "/history current | /history show <session_id> | /history delete <session_id>"
    return table


def _format_session_picker(
    sessions: list[dict[str, object]],
    current_session_id: str,
    summary_fn: Any,
) -> Table:
    """Session picker like Claude Code /resume — numbered list with relative time + summary."""
    table = Table(title="FinCLI Sessions", expand=True, show_lines=False)
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("When", style="cyan", no_wrap=True, width=12)
    table.add_column("Summary", style="white", min_width=30)
    table.add_column("Cmds", justify="right", width=5, style="dim")
    table.add_column("Session ID", style="dim", no_wrap=True)
    for idx, session in enumerate(sessions, 1):
        session_id = str(session["id"])
        marker = " ←" if session_id == current_session_id else ""
        ts = relative_time(str(session.get("updated_at", session.get("created_at", ""))))
        first_cmd = str(session.get("first_command", "") or "")[:45]
        summary = first_cmd if first_cmd else summary_fn(session_id)
        table.add_row(
            str(idx),
            ts,
            summary + marker,
            str(session["event_count"]),
            session_id,
        )
    if not sessions:
        table.add_row("-", "-", "No sessions yet.", "0", "-")
    table.caption = "/history resume <#|id> | /history show <id> | /history save <title> | /history delete <id>"
    return table


def _format_session_events(session: dict[str, object], events: list[dict[str, object]], current: bool = False) -> Table:
    marker = "current" if current else "saved"
    table = Table(title=f"Session {session['id']} ({marker}) - {session['title']}", expand=True)
    table.add_column("#", justify="right", width=4)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Status", style="cyan", no_wrap=True)
    table.add_column("Command", style="white")
    table.add_column("Output Preview", style="dim")
    for event in events:
        table.add_row(
            str(event["id"]),
            str(event["created_at"]),
            str(event["status"]),
            str(event["command"]),
            str(event["output_preview"] or "")[:180],
        )
    if not events:
        table.add_row("-", "-", "-", "No commands in this session yet.", "")
    table.caption = "/history sessions | /history save <title> | /history clear current"
    return table


def _render_history_preview(renderable: Any) -> str:
    if renderable is None:
        return ""
    if isinstance(renderable, str):
        return renderable[:1200]
    console = Console(width=100, record=True, force_terminal=False, file=io.StringIO())
    try:
        console.print(renderable)
        return console.export_text(clear=False).strip()[:1200]
    except (AttributeError, TypeError) as exc:
        logger.debug("Renderable export failed: %s", exc)
        return str(renderable)[:1200]


def _format_dashboard(
    provider_chain: list[str],
    watchlist_rows: list[dict[str, object]],
    portfolio_rows: list[dict[str, object]],
    journal_stats: JournalStats,
    realized_pnl: float,
    quote_getter: Any,
    portfolio_value_getter: Any,
    alerts_rows: list[dict[str, object]] | None = None,
) -> Table:
    table = Table(title="FinCLI Dashboard", expand=True)
    table.add_column("Area", style="cyan", no_wrap=True)
    table.add_column("Summary", style="white")
    table.add_column("Next Action", style="dim")

    table.add_row(
        "Provider Chain",
        ", ".join(provider_chain) if provider_chain else "N/A",
        "/provider status | /provider priority finnhub,yfinance",
    )

    watchlist_symbols = [str(row["symbol"]) for row in watchlist_rows]
    quote_bits: list[str] = []
    for symbol in watchlist_symbols[:4]:
        quote = quote_getter(symbol)
        quote_bits.append(f"{symbol} {_fmt(quote.price) if quote else 'N/A'}")
    table.add_row(
        "Watchlist",
        f"{len(watchlist_rows)} symbol(s)" + (f" | {', '.join(quote_bits)}" if quote_bits else ""),
        "/watchlist add AAPL | /scan watchlist trend=bullish",
    )

    market_value = 0.0
    unrealized = 0.0
    for row in portfolio_rows:
        current_price, pnl, _ = portfolio_value_getter(row)
        if current_price is not None:
            market_value += float(row["quantity"]) * current_price
        if pnl is not None:
            unrealized += pnl
    portfolio_summary = (
        f"{len(portfolio_rows)} position(s) | Market Value {_fmt(market_value)} | "
        f"Unrealized PnL {_fmt(unrealized)} | Realized PnL {_fmt(realized_pnl)}"
        if portfolio_rows
        else "No local portfolio positions"
    )
    table.add_row("Portfolio", portfolio_summary, "/tx add buy AAPL 10 185 | /portfolio performance")

    table.add_row(
        "Journal",
        (
            f"{journal_stats.total_entries} entries | Win Rate {_fmt_pct(journal_stats.win_rate)} | "
            f"Top {journal_stats.top_instrument}"
        ),
        "/journal stats | /journal review",
    )

    table.add_row(
        "Market",
        "Use /market for compact quote + technical + structure + news + fundamentals.",
        "/market AAPL 1d | /analyze AAPL 1d",
    )

    # Alerts section
    alerts = alerts_rows or []
    if alerts:
        alert_symbols = list({str(a.get("symbol", "")) for a in alerts})[:5]
        alert_summary = f"{len(alerts)} active alert(s) | {', '.join(alert_symbols)}"
    else:
        alert_summary = "No active alerts"
    table.add_row("Alerts", alert_summary, "/alert add AAPL above 200 | /alert check")

    if unrealized != 0 or realized_pnl != 0:
        table.add_row(
            "Risk Color",
            semantic_text(
                f"Total PnL {_fmt(realized_pnl + unrealized)} {'gain' if realized_pnl + unrealized >= 0 else 'loss'}"
            ),
            "green=positive | red=negative | yellow=caution",
        )
    return table


def _format_market_overview(overview: MarketOverview) -> Table:
    table = Table(title=f"Market Overview: {overview.symbol} | {overview.timeframe}", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_column("Context", style="dim")

    quality = overview.data_quality
    table.add_row(
        "Data Quality",
        semantic_text(quality.compact()),
        (
            f"quote={quality.quote}; ohlcv={quality.ohlcv}; news={quality.news}; "
            f"fundamentals={quality.fundamentals}; provider={quality.provider}; "
            f"Reliability={quality.reliability_status}; "
            f"Missing={', '.join(quality.missing_fields) if quality.missing_fields else 'none'}"
        ),
    )
    source_quality = overview.source_quality
    table.add_row(
        "Source Quality",
        semantic_text(source_quality.compact()),
        source_quality.detail,
    )
    table.add_row(
        "Quote",
        f"{_fmt(overview.quote.price)} {overview.quote.currency}",
        semantic_text(
            f"{overview.quote.provider} | {overview.quote.status} | {overview.quote.timestamp.isoformat(timespec='seconds')}"
        ),
    )
    table.add_row(
        "Technical",
        semantic_text(f"RSI {_fmt(overview.technical.rsi)} | Trend {overview.technical.trend_bias}"),
        f"MACD {_fmt(overview.technical.macd)} / Signal {_fmt(overview.technical.macd_signal)} | ATR {_fmt(overview.technical.atr)}",
    )
    table.add_row(
        "Key Levels",
        f"Support {_fmt(overview.technical.support)} | Resistance {_fmt(overview.technical.resistance)}",
        f"Bollinger {_fmt(overview.technical.bollinger_lower)} - {_fmt(overview.technical.bollinger_upper)}",
    )
    table.add_row(
        "Market Structure",
        semantic_text(f"{overview.structure.trend} | {overview.structure.latest_pattern}"),
        f"BOS={overview.structure.break_of_structure}; CHoCH={overview.structure.change_of_character}; Liquidity={overview.structure.liquidity_area}",
    )

    if overview.fundamentals is not None:
        table.add_row(
            "Fundamentals",
            f"P/E {_fmt(overview.fundamentals.pe_ratio)} | EPS {_fmt(overview.fundamentals.eps)}",
            f"Sector={overview.fundamentals.sector or 'N/A'}; Industry={overview.fundamentals.industry or 'N/A'}; Market Cap={_fmt(overview.fundamentals.market_cap)}",
        )
    else:
        table.add_row("Fundamentals", "N/A", "Provider did not return fundamentals.")

    if overview.news:
        latest_news = overview.news[0]
        table.add_row(
            "Latest News",
            latest_news.title,
            f"{latest_news.source} | {latest_news.published_at.isoformat(timespec='seconds') if latest_news.published_at else 'unknown time'}",
        )
    else:
        table.add_row("Latest News", "N/A", "Provider did not return recent news.")

    table.add_row("Disclaimer", "Informational only", "Bukan nasihat keuangan.")
    return table


def _format_portfolio_risk(report: PortfolioRiskReport) -> Table:
    table = Table(title="Portfolio Risk v3 | Portfolio Risk v2 compatible", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Metric", style="white", overflow="fold")
    table.add_column("Value", justify="right", overflow="fold")

    table.add_row("Health Score", report.health.label, f"{report.health.score}/100")
    table.add_row("Health Notes", ", ".join(report.health.notes), "")
    table.add_row("PnL Detail", "Cost Basis", _fmt(report.total_cost_basis))
    table.add_row("PnL Detail", "Market Value", _fmt(report.total_market_value))
    table.add_row("PnL Detail", "Realized PnL", semantic_text(_fmt(report.realized_pnl)))
    table.add_row("PnL Detail", "Unrealized PnL", semantic_text(_fmt(report.unrealized_pnl)))
    table.add_row("PnL Detail", "Total PnL", semantic_text(_fmt(report.total_pnl)))
    table.add_row("Drawdown Estimate", "Unrealized drawdown vs cost basis", f"{report.drawdown_estimate:.2f}%")
    table.add_row(
        "Risk Budget",
        f"{report.risk_budget.profile_gameplay} | {report.risk_budget.note}",
        f"{_fmt(report.risk_budget.risk_per_trade)} / {_fmt(report.risk_budget.max_portfolio_risk)} {report.risk_budget.currency}",
    )
    table.add_row(
        "Concentration Risk",
        f"{report.concentration.level}: {report.concentration.top_symbol}",
        f"{report.concentration.top_weight:.2f}%",
    )
    table.add_row("Concentration Risk", report.concentration.note, "")

    if report.exposure_by_asset_class:
        for exposure in report.exposure_by_asset_class.values():
            table.add_row(
                "Exposure by Asset Class",
                f"{exposure.asset_class} ({exposure.count} position(s))",
                f"{_fmt(exposure.market_value)} | {exposure.weight:.2f}%",
            )
    else:
        table.add_row("Exposure by Asset Class", "No positions", "-")
    if report.currency_exposure:
        for exposure in report.currency_exposure.values():
            table.add_row(
                "Currency Exposure",
                f"{exposure.currency} ({exposure.count} position(s))",
                f"{_fmt(exposure.market_value)} | {exposure.weight:.2f}%",
            )
    else:
        table.add_row("Currency Exposure", "No positions", "-")
    if report.asset_class_warnings:
        for warning in report.asset_class_warnings:
            table.add_row("Asset-Class Cap Warning", f"{warning.level}: {warning.note}", f"cap {warning.cap:.2f}%")
    else:
        table.add_row("Asset-Class Cap Warning", "none", "-")

    # VaR
    if report.value_at_risk:
        var = report.value_at_risk
        table.add_row("Value at Risk", "Historical 95%", semantic_text(_fmt(var.historical_var_95)))
        table.add_row("Value at Risk", "Historical 99%", semantic_text(_fmt(var.historical_var_99)))
        table.add_row("Value at Risk", "Parametric 95%", semantic_text(_fmt(var.parametric_var_95)))
        table.add_row("Value at Risk", "Parametric 99%", semantic_text(_fmt(var.parametric_var_99)))

    table.caption = "Portfolio Risk v3 is local analytics only. It is not financial advice."
    return table


def _format_correlation_matrix(symbols: list[str], matrix: dict[str, dict[str, float]]) -> Table:
    table = Table(title="Portfolio Correlation Matrix", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    for symbol in symbols:
        table.add_column(symbol, justify="right", no_wrap=True)

    for s1 in symbols:
        row = [s1]
        for s2 in symbols:
            corr = matrix.get(s1, {}).get(s2, 0.0)
            # Color code: green for low correlation, yellow for medium, red for high
            if abs(corr) < 0.3:
                style = "green"
            elif abs(corr) < 0.7:
                style = "yellow"
            else:
                style = "red"
            row.append(f"[{style}]{corr:.2f}[/]")
        table.add_row(*row)

    table.caption = (
        "Correlation ranges from -1 (inverse) to +1 (perfect). Low correlation (<0.3) = good diversification."
    )
    return table


def _format_portfolio_tax(by_symbol: dict[str, list[dict[str, object]]]) -> Table:
    table = Table(title="Portfolio Tax Report | Realized PnL Summary", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Buys", justify="right")
    table.add_column("Sells", justify="right")
    table.add_column("Total Bought", justify="right")
    table.add_column("Total Sold", justify="right")
    table.add_column("Realized PnL", justify="right")

    total_realized = 0.0
    for symbol in sorted(by_symbol.keys()):
        txs = by_symbol[symbol]
        buys = [t for t in txs if str(t["action"]).lower() == "buy"]
        sells = [t for t in txs if str(t["action"]).lower() == "sell"]
        total_bought = sum(float(t["quantity"]) * float(t["price"]) for t in buys)
        total_sold = sum(float(t["quantity"]) * float(t["price"]) for t in sells)
        realized = sum(float(t["realized_pnl"]) for t in txs)
        total_realized += realized

        table.add_row(
            symbol,
            str(len(buys)),
            str(len(sells)),
            _fmt(total_bought),
            _fmt(total_sold),
            semantic_text(_fmt(realized)),
        )

    table.add_row(
        "[bold]TOTAL[/]",
        str(sum(len([t for t in txs if str(t["action"]).lower() == "buy"]) for txs in by_symbol.values())),
        str(sum(len([t for t in txs if str(t["action"]).lower() == "sell"]) for txs in by_symbol.values())),
        "",
        "",
        f"[bold]{semantic_text(_fmt(total_realized))}[/]",
    )
    table.caption = "Tax report shows realized PnL per symbol. Consult a tax professional for actual filing."
    return table


def _format_technical(
    symbol: str,
    interval: str,
    summary: TechnicalSummary,
    signal: TechnicalSignal | None = None,
    ai_summary: str = "",
    debate: TechnicalDebate | None = None,
) -> str:
    signal_text = (
        format_signal(signal) if signal is not None else "Signal: CAUTION\nSignal Reasoning:\n- Signal unavailable."
    )
    debate_text = format_debate(debate) if debate is not None else "Technical Debate:\n- Debate unavailable."
    return (
        f"Technical Analysis: {symbol}\n"
        f"Timeframe: {interval}\n"
        f"Latest Close: {_fmt(summary.latest_close)}\n"
        f"Trend Bias: {summary.trend_bias}\n"
        f"SMA 5: {_fmt(summary.sma_fast)}\n"
        f"SMA 20: {_fmt(summary.sma_slow)}\n"
        f"EMA 12: {_fmt(summary.ema_fast)}\n"
        f"RSI 14: {_fmt(summary.rsi)}\n"
        f"MACD: {_fmt(summary.macd)} | Signal: {_fmt(summary.macd_signal)}\n"
        f"Bollinger: upper {_fmt(summary.bollinger_upper)} | lower {_fmt(summary.bollinger_lower)}\n"
        f"ATR 14: {_fmt(summary.atr)}\n"
        f"Support: {_fmt(summary.support)} | Resistance: {_fmt(summary.resistance)}\n"
        f"Volume Latest: {_fmt(summary.volume_latest)}\n"
        f"\n{signal_text}\n"
        f"\n{debate_text}\n"
        f"\n{ai_summary}\n"
        "Disclaimer: this analysis is informational only, not financial advice."
    )


def _format_structure(symbol: str, interval: str, structure: MarketStructureSummary) -> str:
    return (
        f"Market Structure: {symbol}\n"
        f"Timeframe: {interval}\n"
        f"Trend: {structure.trend}\n"
        f"Latest Pattern: {structure.latest_pattern}\n"
        f"Break of Structure: {structure.break_of_structure}\n"
        f"Change of Character: {structure.change_of_character}\n"
        f"Support: {_fmt(structure.support)}\n"
        f"Resistance: {_fmt(structure.resistance)}\n"
        f"Liquidity Area: {structure.liquidity_area or 'N/A'}\n"
        f"Risk Zone: {structure.risk_zone or 'N/A'}\n"
        "Disclaimer: this market structure is scenario-based, not financial advice."
    )


def _format_multi_timeframe(analysis: MultiTimeframeAnalysis) -> Table:
    table = Table(title=f"Multi-Timeframe Analysis: {analysis.symbol}", expand=True)
    table.add_column("Timeframe", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Candles", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Trend")
    table.add_column("Structure")
    table.add_column("RSI", justify="right")
    table.add_column("MACD", justify="right")
    table.add_column("Support / Resistance", overflow="fold")
    table.add_column("Note", overflow="fold")
    for frame in analysis.frames:
        table.add_row(
            frame.timeframe,
            frame.status,
            str(frame.candles),
            _fmt(frame.latest_close),
            semantic_text(frame.trend_bias),
            semantic_text(frame.structure_trend),
            _fmt(frame.rsi),
            _fmt(frame.macd),
            f"{_fmt(frame.support)} / {_fmt(frame.resistance)}",
            frame.note or "-",
        )
    table.caption = (
        f"Alignment: {analysis.alignment} | Bias: {analysis.bias} | Score: {analysis.score} | "
        f"Risk: {analysis.risk_note}"
    )
    return table


def _format_backtest(result: BacktestResult) -> Any:
    from fincli.app.tui.chart import render_equity_curve

    table = Table(title=f"Backtest: {result.symbol} | {result.strategy} | {result.interval}", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    # Performance
    table.add_row(
        "Total Return", semantic_text(f"{result.total_return_percent:+.2f}% (${result.total_return_absolute:+,.2f})")
    )
    table.add_row("Win Rate", f"{result.win_rate:.1f}%")
    table.add_row("Max Drawdown", semantic_text(f"{result.max_drawdown_percent:.2f}%"))
    table.add_row("Exposure", f"{result.exposure_percent:.1f}%")

    # Risk ratios
    table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    table.add_row("Sortino Ratio", f"{result.sortino_ratio:.2f}")
    table.add_row("Calmar Ratio", f"{result.calmar_ratio:.2f}")

    # Trade stats
    table.add_row("Trades", f"{result.total_trades} (W:{result.winning_trades} / L:{result.losing_trades})")
    table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
    table.add_row("Expectancy", f"{result.expectancy:.2f}%")
    table.add_row("Avg Win / Loss", f"{result.avg_win:+.2f}% / {result.avg_loss:+.2f}%")
    table.add_row("Largest Win / Loss", f"{result.largest_win:+.2f}% / {result.largest_loss:+.2f}%")
    table.add_row("Streaks", f"W:{result.consecutive_wins} / L:{result.consecutive_losses}")

    # Costs
    table.add_row("Total Fees", f"${result.total_fees:,.2f}")
    table.add_row("Fee Profile", result.fee_profile_used)
    table.add_row("Position Sizing", result.position_sizer_used)

    # Monte Carlo
    if result.monte_carlo:
        mc = result.monte_carlo
        table.add_row(
            "Monte Carlo",
            f"5th={mc.percentile_5:+.1f}% | 50th={mc.percentile_50:+.1f}% | 95th={mc.percentile_95:+.1f}%",
        )

    # Walk-forward
    if result.walk_forward:
        wf = result.walk_forward
        table.add_row(
            "Walk-Forward",
            f"IS={wf.in_sample.total_return_percent:+.1f}% | OOS={wf.out_of_sample.total_return_percent:+.1f}% | Overfit={wf.overfit_ratio:.2f}",
        )

    table.add_row("Notes", " ".join(result.notes))
    table.caption = (
        "Backtest includes fees/slippage/spread. Educational only — past performance does not guarantee future results."
    )

    # Build equity curve from trades
    if result.trades:
        equity_curve = []
        equity = result.initial_equity
        for trade in result.trades:
            equity += trade.pnl_absolute
            equity_curve.append(equity)
        equity_chart = render_equity_curve(equity_curve, result.initial_equity, title=f"Equity Curve: {result.symbol}")
        from rich.console import Group

        return Group(table, equity_chart)

    return table


def _format_backtest_compare(symbol: str, interval: str, strategies: list[str], results: list[Any]) -> Table:
    table = Table(title=f"Backtest Compare: {symbol} | {interval}", expand=True)
    table.add_column("Strategy", style="cyan", no_wrap=True)
    table.add_column("Return", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Max DD", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Profit Factor", justify="right")

    for strategy, result in zip(strategies, results, strict=False):
        if result is None:
            table.add_row(strategy, "error", "-", "-", "-", "-", "-")
        else:
            table.add_row(
                strategy,
                semantic_text(f"{result.total_return_percent:+.2f}%"),
                f"{result.win_rate:.1f}%",
                semantic_text(f"{result.max_drawdown_percent:.2f}%"),
                f"{result.sharpe_ratio:.2f}",
                f"{result.total_trades}",
                f"{result.profit_factor:.2f}",
            )

    table.caption = "Compare strategies on same data. Past performance does not guarantee future results."
    return table


def _format_alerts(rows: list[dict[str, object]]) -> Table:
    table = Table(title="Price Alerts", expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Status")
    table.add_column("Note", overflow="fold")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            str(row["id"]),
            str(row["symbol"]),
            str(row["condition"]),
            _fmt(float(row["target"])),
            semantic_text("active hold" if int(row["active"]) else f"triggered {row['triggered_at']}"),
            str(row["note"] or "-"),
            str(row["created_at"]),
        )
    if not rows:
        table.add_row("-", "-", "-", "-", "-", "No alerts. Use /alert add AAPL above 200.", "-")
    return table


def _format_alert_checks(results: list[AlertCheckResult]) -> Table:
    table = Table(title="Alert Check", expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Triggered", justify="center")
    table.add_column("Note", overflow="fold")
    for result in results:
        table.add_row(
            str(result.id),
            result.symbol,
            result.condition,
            _fmt(result.target),
            _fmt(result.current_price),
            semantic_text("YES breakout confirmed" if result.triggered else "no hold"),
            result.note or "-",
        )
    if not results:
        table.add_row("-", "-", "-", "-", "-", "-", "No active alerts.")
    return table


def _format_alert_history(entries: list[object]) -> Table:
    table = Table(title="Alert History", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Symbol", style="cyan")
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Time")
    for entry in entries:
        table.add_row(
            str(getattr(entry, "id", "-")),
            str(getattr(entry, "symbol", "-")),
            str(getattr(entry, "condition", "-")),
            _fmt(getattr(entry, "target", 0)),
            _fmt(getattr(entry, "actual_value", None)),
            str(getattr(entry, "created_at", "-")),
        )
    if not entries:
        table.add_row("-", "-", "-", "-", "-", "No alert history.")
    return table


def _format_portfolio_chart(snapshots: list[object], ratios: object) -> Table:
    table = Table(title="Portfolio Performance", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")

    if snapshots:
        latest = snapshots[0]
        oldest = snapshots[-1]
        total_return = (
            ((latest.total_value - oldest.total_value) / oldest.total_value * 100) if oldest.total_value > 0 else 0
        )
        table.add_row("Period", f"{len(snapshots)} snapshots")
        table.add_row("Latest Value", f"${latest.total_value:,.2f}")
        table.add_row("Period Return", f"{total_return:+.2f}%")

    table.add_row("Sharpe Ratio", f"{ratios.sharpe:.2f}")
    table.add_row("Sortino Ratio", f"{ratios.sortino:.2f}")
    table.add_row("Calmar Ratio", f"{ratios.calmar:.2f}")
    table.add_row("Annualized Return", f"{ratios.annualized_return:+.2f}%")
    table.add_row("Annualized Volatility", f"{ratios.annualized_volatility:.2f}%")
    table.add_row("Max Drawdown", f"{ratios.max_drawdown:.2f}%")
    table.caption = "Use /portfolio snapshot to save daily values for chart tracking."
    return table


def _format_whatif(result: object) -> Table:
    table = Table(title="What-If Analysis", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Action", str(getattr(result, "action", "-")))
    table.add_row("Symbol", str(getattr(result, "symbol", "-")))
    table.add_row("Current Weight", f"{getattr(result, 'current_weight', 0):.1f}%")
    table.add_row("New Weight", f"{getattr(result, 'new_weight', 0):.1f}%")
    table.add_row("Current Concentration", str(getattr(result, "current_concentration", "-")))
    table.add_row("New Concentration", str(getattr(result, "new_concentration", "-")))
    table.add_row("Note", str(getattr(result, "note", "-")))
    table.caption = "What-if analysis is informational, not financial advice."
    return table


def _format_benchmark(comparison: object) -> Table:
    table = Table(title=f"Benchmark: {getattr(comparison, 'benchmark_symbol', '?')}", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Portfolio Return", f"{getattr(comparison, 'portfolio_return', 0):+.2f}%")
    table.add_row("Benchmark Return", f"{getattr(comparison, 'benchmark_return', 0):+.2f}%")
    table.add_row("Alpha", f"{getattr(comparison, 'alpha', 0):+.2f}%")
    table.add_row("Beta", f"{getattr(comparison, 'beta', 0):.2f}")
    table.add_row("Correlation", f"{getattr(comparison, 'correlation', 0):.2f}")
    table.add_row("Period", f"{getattr(comparison, 'period_days', 0)} days")
    table.add_row("Note", str(getattr(comparison, "note", "-")))
    table.caption = "Benchmark comparison requires daily portfolio snapshots. Use /portfolio snapshot."
    return table


def _format_rebalance(positions: list[dict], trades: list[dict], total_value: float, target_pct: float) -> Table:
    """Format rebalance suggestions."""
    table = Table(title=f"Portfolio Rebalance (Equal-Weight {target_pct:.1f}%)", expand=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Current $", justify="right")
    table.add_column("Current %", justify="right")
    table.add_column("Target %", justify="right")
    table.add_column("Action", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Value", justify="right")

    for pos in positions:
        current_pct = (pos["market_value"] / total_value) * 100 if total_value > 0 else 0
        table.add_row(
            pos["symbol"],
            f"${pos['market_value']:,.2f}",
            f"{current_pct:.1f}%",
            f"{target_pct:.1f}%",
            "-",
            "-",
            "-",
        )

    if trades:
        table.add_row("", "", "", "", "", "", "")  # separator
        for trade in trades:
            style = "green" if trade["side"] == "buy" else "red"
            table.add_row(
                trade["symbol"],
                "",
                f"{trade['current_pct']:.1f}%",
                f"{trade['target_pct']:.1f}%",
                f"[{style}]{trade['side'].upper()}[/]",
                f"{trade['quantity']:.4f}",
                f"${trade['value']:,.2f}",
            )

    table.caption = f"Total portfolio value: ${total_value:,.2f}. Equal-weight target: {target_pct:.1f}% per position."
    return table


def _format_scan_results(
    results: list[ScanResult],
    filter_expression: str,
    interval: str,
    source: str = "watchlist",
    errors: list[str] | None = None,
) -> Table:
    table = Table(title=f"Scan {source.title()} | {filter_expression} | {interval}", expand=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Close", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("Trend")
    table.add_column("Support", justify="right")
    table.add_column("Resistance", justify="right")
    table.add_column("Reason")
    for result in results:
        table.add_row(
            result.symbol,
            _fmt(result.latest_close),
            _fmt(result.rsi),
            semantic_text(result.trend_bias),
            _fmt(result.support),
            _fmt(result.resistance),
            semantic_text(result.reason),
        )
    if not results:
        table.add_row("-", "-", "-", "-", "-", "-", "No matching symbols.")
    if errors:
        summary = f"{len(errors)} symbol(s) failed"
        if errors:
            summary += f": {errors[0][:50]}"
            if len(errors) > 1:
                summary += f" (+{len(errors) - 1} more)"
        table.add_row("-", "-", "-", "-", "-", "-", f"[yellow]{summary}[/]")
    return table


def _scan_result_rows(results: list[ScanResult]) -> list[dict[str, object]]:
    return [
        {
            "symbol": item.symbol,
            "latest_close": item.latest_close,
            "rsi": item.rsi,
            "trend_bias": item.trend_bias,
            "support": item.support,
            "resistance": item.resistance,
            "matched": item.matched,
            "reason": item.reason,
        }
        for item in results
    ]


def _parse_timeframes(value: str) -> tuple[str, ...]:
    frames = tuple(frame.strip().lower() for frame in value.split(",") if frame.strip())
    if not frames:
        raise CommandError("Invalid timeframe. Example: /mtf AAPL 1d,1h,15m")
    if len(frames) > 6:
        raise CommandError("Maximum 6 timeframes in one /mtf.")
    return frames


def _parse_news_lookback(args: list[str]) -> int | None:
    if not args:
        return None
    raw = args[0].strip().lower()
    if len(args) > 1 or not raw.endswith("d") or not raw[:-1].isdigit():
        raise CommandError("Format: /news <symbol> [1d-30d]")
    days = int(raw[:-1])
    if days < 1 or days > 30:
        raise CommandError("Lookback /news max 30d. Example: /news TSLA 7d")
    return days


def _extract_option_value(args: list[str], option: str) -> str | None:
    if option not in args:
        return None
    index = args.index(option)
    if len(args) <= index + 1:
        raise CommandError(f"Format opsi: {option} <value>")
    return args[index + 1]


def _parse_calendar_args(args: list[str]) -> tuple[date, date, str | None, str | None]:
    country: str | None = None
    impact: str | None = None
    positional: list[str] = []

    for arg in args:
        normalized = arg.lower()
        if normalized.startswith("country="):
            country = arg.split("=", 1)[1].upper()
        elif normalized.startswith("impact="):
            impact = arg.split("=", 1)[1].lower()
        elif normalized in {"high", "medium", "low"}:
            impact = normalized
        elif len(arg) in {2, 3} and arg.isalpha():
            country = arg.upper()
        else:
            positional.append(arg)

    if not positional:
        start, end = default_calendar_window("week")
    elif positional[0].lower() in {"today", "week"}:
        start, end = default_calendar_window(positional[0].lower())
    elif len(positional) >= 2:
        start = _parse_date_arg(positional[0])
        end = _parse_date_arg(positional[1])
    else:
        raise CommandError(
            "Format: /calendar [today|week|<from YYYY-MM-DD> <to YYYY-MM-DD>] [country=US] [impact=high]"
        )

    if end < start:
        raise CommandError("Calendar end date cannot be earlier than start date.")
    return start, end, country, impact


def _parse_date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError("Calendar date must be in YYYY-MM-DD format.") from exc


def _calendar_fallback_note(exc: FinCLIError, has_key: bool) -> str:
    if has_key:
        return (
            "FinCLI uses fallback event categories. "
            "Check API key, Finnhub entitlement/plan, or rate-limit for actual data."
        )
    return "FinCLI uses fallback event categories. Set FINNHUB_API_KEY for actual data."


def _calendar_static_fallback_note(provider_error: FinCLIError, public_error: FinCLIError | None) -> str:
    _ = provider_error, public_error
    return (
        "Using static macro fallback. Finnhub calendar endpoint is unavailable for the current key/plan "
        "or provider rate limit, and public calendar fallback is temporarily unavailable. "
        "Check /provider key status, Finnhub calendar entitlement, and try again later."
    )


def _format_calendar(events: list[EconomicEvent], start: date, end: date, source: str, note: str) -> Table:
    reliability = _calendar_reliability_status(events, source, note)
    quality = _calendar_data_quality(events, source, reliability)
    table = Table(
        title=f"Economic Calendar | {start.isoformat()} to {end.isoformat()} | {source} | {reliability}",
        expand=True,
    )
    table.add_column("Time", style="cyan", no_wrap=True, width=16, max_width=16)
    table.add_column("Country", no_wrap=True, width=7, max_width=7)
    table.add_column("Impact", no_wrap=True, width=6, max_width=6)
    table.add_column("Event", style="white", overflow="fold")
    table.add_column("Actual", justify="right", no_wrap=True, width=10, max_width=14)
    table.add_column("Forecast", justify="right", no_wrap=True, width=10, max_width=14)
    table.add_column("Prev", justify="right", no_wrap=True, width=10, max_width=14)

    for event in events:
        event_time = event.time.isoformat(timespec="minutes") if event.time else "TBA"
        table.add_row(
            event_time,
            event.country,
            event.impact,
            event.event,
            event.actual or "-",
            event.estimate or "-",
            event.previous or "-",
        )

    if not events:
        table.add_row("-", "-", "-", "No events match the filter.", "-", "-", "-")
    summary = calendar_summary(events)
    table.add_row(
        "Summary",
        source,
        "-",
        f"total={summary['total']}; high={summary.get('high', 0)}; medium={summary.get('medium', 0)}; "
        f"low={summary.get('low', 0)}; reliability={reliability}",
        "-",
        "-",
        "-",
    )
    table.add_row("Note", source, "-", note, "-", "-", "-")
    table.caption = f"Data Quality: {quality.compact()}"
    return table


def _calendar_reliability_status(events: list[EconomicEvent], source: str, note: str) -> str:
    normalized_source = source.lower()
    normalized_note = note.lower()
    if normalized_source == "finnhub" and events:
        return STATUS_OK
    if normalized_source == "fallback":
        return STATUS_SCHEDULE_ONLY
    if "static macro fallback" in normalized_note or "fallback kategori" in normalized_note:
        return STATUS_SCHEDULE_ONLY
    if events:
        return STATUS_PARTIAL_DATA
    return STATUS_UNAVAILABLE


def _calendar_data_quality(events: list[EconomicEvent], source: str, reliability: str) -> DataQualityReport:
    score = 70 if events else 20
    if reliability == STATUS_OK:
        score = 90
    elif reliability == STATUS_SCHEDULE_ONLY:
        score = 45 if events else 25
    missing = () if reliability == STATUS_OK else ("actual", "estimate", "previous")
    tier = "strong" if score >= 85 else "usable" if score >= 65 else "partial" if score >= 40 else "weak"
    return DataQualityReport(
        score=score,
        quote="not_applicable",
        ohlcv="not_applicable",
        news="not_applicable",
        fundamentals=f"{len(events)} calendar event(s)",
        provider=source,
        tier=tier,
        freshness="calendar_window",
        reliability_status=reliability,
        missing_fields=missing,
        label=f"{tier} | {reliability}",
    )


def _format_provider_list() -> Table:
    table = Table(title="Market Providers", expand=True)
    table.add_column("Name", style="cyan")
    table.add_column("Realtime")
    table.add_column("Status")
    table.add_column("Notes")
    for provider in MarketProviderManager().list_providers():
        table.add_row(provider.name, str(provider.realtime), provider.status, provider.notes)
    return table


def _format_provider_compare(symbol: str, results: list[dict[str, object]]) -> Table:
    table = Table(title=f"Provider Compare: {symbol}", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Currency", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Latency", justify="right")
    table.add_column("Error", overflow="fold")

    for r in results:
        price = r["price"]
        price_str = _fmt(float(price)) if price is not None else "-"
        latency = r["latency_ms"]
        latency_str = f"{latency:.0f}ms" if latency is not None else "-"
        error = r["error"] or "-"
        status = str(r["status"])
        style = "green" if status == "realtime" else "yellow" if status == "delayed" else "red"
        table.add_row(
            str(r["provider"]),
            price_str,
            str(r["currency"]),
            f"[{style}]{status}[/]",
            latency_str,
            str(error),
        )

    table.caption = "Compare providers for same symbol. Lower latency = better."
    return table


def _format_provider_entitlements(items: list[ProviderEntitlement]) -> Table:
    table = Table(title="Provider Entitlements and Data Labels", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Realtime Label", style="yellow", no_wrap=True)
    table.add_column("Asset Classes", overflow="fold")
    table.add_column("Capabilities", overflow="fold")
    table.add_column("Limitations", overflow="fold")
    for item in items:
        table.add_row(
            item.provider,
            item.status,
            item.realtime_label,
            ", ".join(item.asset_classes),
            ", ".join(item.capabilities),
            "; ".join(item.limitations),
        )
    return table


def _format_provider_capabilities(providers: list | None = None) -> Table:

    # Provider capability declarations
    cap_table = Table(title="Provider Capabilities", expand=True)
    cap_table.add_column("Provider", style="cyan", no_wrap=True)
    cap_table.add_column("Realtime", no_wrap=True)
    cap_table.add_column("Operations", overflow="fold")
    cap_table.add_column("Asset Classes", overflow="fold")
    cap_table.add_column("Rate Limit", overflow="fold")
    for provider in providers or []:
        if hasattr(provider, "capabilities"):
            cap = provider.capabilities()
            if cap is not None:
                cap_table.add_row(
                    cap.name,
                    "yes" if cap.realtime else "no",
                    ", ".join(cap.operations),
                    ", ".join(cap.asset_classes),
                    cap.rate_limit_note or "-",
                )

    # Command capability matrix
    cmd_table = Table(title="Command Capability Matrix", expand=True)
    cmd_table.add_column("Command", style="cyan", no_wrap=True)
    cmd_table.add_column("Provider-Dependent", no_wrap=True)
    cmd_table.add_column("Needs", overflow="fold")
    cmd_table.add_column("Note", overflow="fold")
    for capability in capability_rows():
        cmd_table.add_row(
            capability.command,
            "yes" if capability.provider_dependent else "no",
            ", ".join(capability.needs),
            capability.note,
        )
    cmd_table.caption = capability_summary()
    return Group(cap_table, cmd_table)


def _format_provider_key_status(manager: MarketProviderManager) -> Table:
    table = Table(title="Market Provider API Key Status", expand=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Source")
    for row in manager.key_status():
        table.add_row(row["provider"], row["key"], row["status"], row["source"])
    return table


def _format_secrets_status(secrets: dict[str, str]) -> Table:
    table = Table(title="Local Secrets Status", expand=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Source")
    for key in sorted(secrets):
        table.add_row(key, "set", "~/.fincli/secrets.env")
    if not secrets:
        table.add_row("-", "empty", "No local secrets stored.")
    table.caption = "Values are never printed. Use /secrets clear before publishing screenshots or sharing a machine."
    return table


def _format_secret_ages() -> Table:
    from fincli.app.storage.secrets import list_secret_ages

    ages = list_secret_ages()
    table = Table(title="Key Age", expand=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Age (days)", no_wrap=True)
    table.add_column("Status")
    if not ages:
        table.add_row("-", "-", "No secrets stored.")
        return table
    for key in sorted(ages):
        age = ages[key]
        if age is None:
            status = "unknown"
            age_str = "-"
        elif age > 90:
            status = "[red]⚠ Rotate recommended[/red]"
            age_str = str(age)
        elif age > 60:
            status = "[yellow]aging[/yellow]"
            age_str = str(age)
        else:
            status = "[green]ok[/green]"
            age_str = str(age)
        table.add_row(key, age_str, status)
    table.caption = "Keys older than 90 days should be rotated. Use /secrets rotate <KEY>."
    return table


def _format_security_status(router: object) -> Table:
    table = Table(title="🔒 Security Status", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail")

    secrets = read_secrets()
    table.add_row("Secrets Stored", str(len(secrets)), "API keys in ~/.fincli/secrets.env")
    table.add_row("Secret Redaction", "active", "All error messages are redacted before display")
    table.add_row("Input Validation", "active", "Symbols, paths, and numbers are validated")
    table.add_row("Rate Limiting", "active", "Per-command rate limits enforced")
    table.add_row("Audit Log", "active", f"{router.audit_log.count_events()} events recorded")
    table.add_row("Path Traversal Protection", "active", "File operations validate paths")
    table.add_row("File Permissions", "0o600", "Secrets file is owner-read-write only")
    from fincli.app.web.manager import WebServerManager

    web_status = WebServerManager(router.config).status()
    web_detail = f"{web_status['url']}; token auth {'required' if web_status['auth'] else 'disabled'}"
    table.add_row("Local Web Access", "running" if web_status["running"] else "stopped", web_detail)

    # Key age warnings
    from fincli.app.storage.secrets import list_secret_ages

    ages = list_secret_ages()
    stale_keys = [key for key, age in ages.items() if age is not None and age > 90]
    if stale_keys:
        table.add_row(
            "Key Rotation",
            "[red]⚠ warning[/red]",
            f"{len(stale_keys)} key(s) older than 90 days: {', '.join(stale_keys)}",
        )
    else:
        table.add_row("Key Rotation", "[green]ok[/green]", "All keys are fresh")

    table.caption = "Use /security audit to view audit log. Use /security lockdown for emergency secret wipe."
    return table


def _format_session_security(router: object) -> Table:
    """Format session security status."""
    table = Table(title="🔐 Session Security", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail")

    session_id = getattr(router, "session_id", "unknown")
    table.add_row("Session ID", str(session_id)[:12] + "...", "Current active session")
    table.add_row("Session History", "active", f"{len(router.history.get_events(session_id))} events recorded")
    table.add_row("Command Audit", "active", "All commands logged in session history")
    table.add_row("Secret Redaction", "active", "Sensitive data redacted from logs")

    # Broker connection security
    live_trading = getattr(router, "live_trading", None)
    if live_trading and live_trading.is_connected():
        table.add_row("Broker Connection", "active", f"Connected to {live_trading.broker_name} ({live_trading.mode})")
        table.add_row("Live Order Safety", "active", "--confirm flag required for live orders")
    else:
        table.add_row("Broker Connection", "inactive", "No live broker connected")

    table.caption = "Session data is stored locally. Use /security purge to clear session history."
    return table


def _format_audit_events(events: list[object]) -> Table:
    table = Table(title="🔐 Security Audit Log", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Event", style="cyan", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    table.add_column("Time", no_wrap=True)
    for event in events:
        table.add_row(
            str(getattr(event, "id", "-")),
            str(getattr(event, "event_type", "-")),
            str(getattr(event, "detail", ""))[:100],
            str(getattr(event, "created_at", "-")),
        )
    if not events:
        table.add_row("-", "-", "No audit events recorded.", "-")
    table.caption = "Audit log is immutable. Events are never modified or deleted."
    return table


def _format_security_scan(secrets: dict[str, str]) -> Table:
    table = Table(title="Security Scan", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    # 1. Secrets count
    if secrets:
        table.add_row("Local Secrets", "info", f"{len(secrets)} key(s) stored")
        masked = ", ".join(f"{k[:4]}...{k[-2:]}" if len(k) > 6 else k for k in sorted(secrets))
        table.add_row("Keys", "info", masked)
    else:
        table.add_row("Local Secrets", "ok", "None stored")

    # 2. Encryption check
    from fincli.app.storage.secrets import _MAGIC, SECRETS_FILE

    if SECRETS_FILE.exists():
        header = SECRETS_FILE.read_bytes()[: len(_MAGIC)]
        if header == _MAGIC:
            table.add_row("Encryption", "ok", "secrets.env encrypted at rest")
        else:
            table.add_row("Encryption", "warn", "secrets.env is plaintext — will encrypt on next save")
    else:
        table.add_row("Encryption", "ok", "No secrets file")

    # 3. Key file permission check
    from fincli.app.storage.secrets import _KEY_FILE

    if _KEY_FILE.exists():
        try:
            import stat

            mode = _KEY_FILE.stat().st_mode
            if mode & stat.S_IROTH:
                table.add_row("Key File", "warn", ".secrets_key is world-readable")
            else:
                table.add_row("Key File", "ok", ".secrets_key permissions OK")
        except OSError:
            table.add_row("Key File", "info", "Cannot check permissions")
    else:
        table.add_row("Key File", "ok", "No key file (will create on first save)")

    # 4. .gitignore check
    gitignore = Path(".gitignore")
    required_patterns = {"secrets.env", ".secrets_key", ".env"}
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        missing = [p for p in required_patterns if p not in content]
        if missing:
            table.add_row(".gitignore", "warn", f"Missing: {', '.join(missing)}")
        else:
            table.add_row(".gitignore", "ok", "All sensitive patterns covered")
    else:
        table.add_row(".gitignore", "warn", "No .gitignore found")

    # 5. Project file scan for leaked secrets
    try:
        from fincli.app.utils.security_scan import find_secret_issues

        issues = find_secret_issues(Path("."))
        if issues:
            table.add_row("Project Scan", "warn", f"{len(issues)} potential leak(s) found")
            for issue in issues[:5]:
                table.add_row(f"  {issue.kind}", "warn", f"{issue.path}: {issue.detail[:60]}")
            if len(issues) > 5:
                table.add_row("  ...", "info", f"+{len(issues) - 5} more. Run: python scripts/prepublish_check.py")
        else:
            table.add_row("Project Scan", "ok", "No leaked secrets in project files")
    except OSError as exc:
        table.add_row("Project Scan", "warn", f"Could not scan workspace: {exc}")

    # 6. .env file check
    env_files = list(Path(".").glob(".env*"))
    env_files = [f for f in env_files if f.name != ".env.example"]
    if env_files:
        table.add_row(".env Files", "warn", f"Found: {', '.join(f.name for f in env_files)}")
    else:
        table.add_row(".env Files", "ok", "None in project root")

    table.caption = "Use /security lockdown to emergency-clear all secrets."
    return table


def _format_circuit_status(service: MarketDataService) -> str:
    metrics = service.provider_metrics_snapshot()
    if not metrics:
        return "Circuit Breakers: no data"
    lines = ["Circuit Breakers:"]
    for name, metric in metrics.items():
        state = "OPEN" if metric.circuit_open else "closed"
        streak = metric.consecutive_failures
        lines.append(f"  {name}: {state} (failures={streak})")
    return "\n".join(lines)


def _format_provider_metrics(service: MarketDataService) -> Table:
    table = Table(title="Provider Metrics Dashboard", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Session Calls", justify="right")
    table.add_column("All-Time Calls", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Fallback Count", justify="right")
    table.add_column("Error Count", justify="right")
    table.add_column("Circuit", no_wrap=True)
    table.add_column("Failure Streak", justify="right")
    table.add_column("Last Status", no_wrap=True)

    metrics = service.provider_metrics_snapshot()
    persisted = service.metrics_store.snapshot() if getattr(service, "metrics_store", None) is not None else {}
    for provider in service.providers:
        name = provider.name
        metric = metrics.get(name)
        persisted_metric = persisted.get(name)
        if metric is None:
            table.add_row(
                name,
                "0",
                str(persisted_metric.calls if persisted_metric else 0),
                "0.00%",
                "0.00ms",
                "0",
                "0",
                "closed",
                "0",
                "not_called",
            )
            continue
        table.add_row(
            name,
            str(metric.calls),
            str(persisted_metric.calls if persisted_metric else metric.calls),
            f"{metric.success_rate:.2f}%",
            f"{metric.avg_latency_ms:.2f}ms",
            str(metric.fallbacks),
            str(metric.errors),
            "open" if metric.circuit_open else "closed",
            str(metric.consecutive_failures),
            metric.last_status,
        )
    table.caption = (
        f"Active provider: {service.primary_provider.name}. "
        "Session metrics reset per run; all-time calls persist in local SQLite."
    )

    # Per-operation breakdown
    if getattr(service, "metrics_store", None) is not None:
        op_metrics = service.metrics_store.all_operation_snapshots()
        if op_metrics:
            op_table = Table(title="Per-Operation Metrics (All-Time)", expand=True)
            op_table.add_column("Provider", style="cyan", no_wrap=True)
            op_table.add_column("Operation", style="white", no_wrap=True)
            op_table.add_column("Calls", justify="right")
            op_table.add_column("Success Rate", justify="right")
            op_table.add_column("Avg Latency", justify="right")
            op_table.add_column("Errors", justify="right")
            for op in op_metrics:
                op_table.add_row(
                    op.provider,
                    op.operation,
                    str(op.calls),
                    f"{op.success_rate:.1f}%",
                    f"{op.avg_latency_ms:.1f}ms",
                    str(op.errors),
                )
            from rich.console import Group

            table = Group(table, op_table)  # type: ignore[assignment]

    return table


def _format_provider_trust(service: MarketDataService) -> Table:
    summary = _provider_trust_summary(service)
    metrics = service.provider_metrics_snapshot()
    last_result = service.last_result
    provider_chain = ", ".join(provider.name for provider in service.providers)

    table = Table(title="Provider Trust", expand=True)
    table.add_column("Area", style="cyan", no_wrap=True)
    table.add_column("Label", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    table.add_row("Trust Level", summary["level"], summary["message"])
    table.add_row("AI Confidence Limit", f"{summary['confidence_cap']}%", summary["ai_action"])
    table.add_row("Provider Chain", "active", provider_chain or "no providers configured")
    table.add_row(
        "Cache", "enabled" if service.cache is not None else "runtime only", f"TTL {service.cache_ttl_seconds}s"
    )

    if last_result is None:
        table.add_row(
            "Last Result",
            "not enough data",
            "No provider calls recorded yet. Run /provider test AAPL or a market command to populate trust evidence.",
        )
    else:
        missing = ", ".join(last_result.missing_fields) if last_result.missing_fields else "none"
        table.add_row(
            "Last Result",
            _trust_status_label(last_result.status),
            (
                f"{last_result.provider}/{last_result.operation}; status={last_result.status}; "
                f"quality={last_result.data_quality}; realtime={last_result.realtime_label}; missing={missing}"
            ),
        )

    recent_errors = "; ".join(service.last_errors[-3:]) if service.last_errors else "none"
    table.add_row("Recent Errors", "clear" if recent_errors == "none" else "review", recent_errors)

    for provider in service.providers:
        name = provider.name
        metric = metrics.get(name)
        table.add_row(f"Provider: {name}", _metric_trust_label(metric), _format_provider_metric_detail(metric))

    reasons = (
        "; ".join(summary["reasons"]) if summary["reasons"] else "No reliability warnings from current session metrics."
    )
    table.add_row("Quality Notes", summary["level"], reasons)
    table.add_row("Suggested Action", summary["level"], summary["suggested_action"])
    table.caption = (
        "Trust summarizes provider runtime health, fallback/circuit state, and data completeness. "
        "It limits AI confidence; it is not investment advice."
    )
    return table


def _provider_trust_summary(service: MarketDataService) -> dict[str, Any]:
    metrics = service.provider_metrics_snapshot()
    last_result = service.last_result
    reasons: list[str] = []

    circuit_open = [name for name, metric in metrics.items() if metric.circuit_open]
    if circuit_open:
        reasons.append(f"circuit open: {', '.join(circuit_open)}")

    if last_result is None:
        reasons.append("no provider call evidence recorded in this session")
        return {
            "level": "Limited",
            "confidence_cap": 45,
            "ai_action": "caution-first analysis only until a quote/history check succeeds",
            "message": "Not enough data to prove provider reliability yet.",
            "suggested_action": "Run /provider test AAPL, then retry /provider trust.",
            "reasons": reasons,
        }

    critical_missing = {"quote", "ohlcv", "price"}
    if (
        circuit_open
        or last_result.status == STATUS_UNAVAILABLE
        or critical_missing.intersection(last_result.missing_fields)
    ):
        if critical_missing.intersection(last_result.missing_fields):
            reasons.append(f"critical field missing: {', '.join(last_result.missing_fields)}")
        if last_result.status == STATUS_UNAVAILABLE:
            reasons.append("last provider result is unavailable")
        return {
            "level": "Blocked",
            "confidence_cap": 20,
            "ai_action": "no directional signal; show caution and require verification",
            "message": "Critical market data is unavailable or the provider chain is blocked.",
            "suggested_action": "Reset the circuit if appropriate, rotate/check API keys, or switch provider before relying on output.",
            "reasons": reasons,
        }

    weak_metric_reasons = _provider_metric_reasons(metrics)
    reasons.extend(weak_metric_reasons)
    if last_result.status in {STATUS_PARTIAL_DATA, STATUS_SCHEDULE_ONLY}:
        reasons.append(f"last result status is {last_result.status}")

    total_calls = sum(metric.calls for metric in metrics.values())
    total_errors = sum(metric.errors for metric in metrics.values())
    total_fallbacks = sum(metric.fallbacks for metric in metrics.values())
    healthy_primary = total_calls > 0 and total_errors == 0 and total_fallbacks == 0 and last_result.status == STATUS_OK

    if healthy_primary and not weak_metric_reasons:
        return {
            "level": "Strong",
            "confidence_cap": 80,
            "ai_action": "normal scenario analysis allowed with normal verification",
            "message": "Provider chain is healthy for the latest recorded market call.",
            "suggested_action": "Proceed, but keep normal risk and source checks.",
            "reasons": reasons,
        }

    if last_result.status == STATUS_OK and len(weak_metric_reasons) <= 1:
        return {
            "level": "Usable",
            "confidence_cap": 60,
            "ai_action": "moderated scenario analysis; avoid overconfident conclusions",
            "message": "Latest data is usable, with minor reliability caveats.",
            "suggested_action": "Use output as a watchlist bias and confirm with a second source for decisions.",
            "reasons": reasons,
        }

    return {
        "level": "Limited",
        "confidence_cap": 45,
        "ai_action": "caution-first analysis; wait for confirmation before decisions",
        "message": "Provider reliability or data completeness is below the preferred release threshold.",
        "suggested_action": "Compare providers, check keys/entitlements, or retry after fallback health improves.",
        "reasons": reasons or ("provider data quality below preferred threshold",),
    }


def _provider_metric_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for name, metric in metrics.items():
        if metric.calls <= 0:
            continue
        if metric.errors >= 2:
            reasons.append(f"{name} returned {metric.errors} error(s)")
        if metric.fallbacks >= 2:
            reasons.append(f"{name} required {metric.fallbacks} fallback(s)")
        if metric.calls >= 2 and metric.success_rate < 50:
            reasons.append(f"{name} success rate is weak ({metric.success_rate:.1f}%)")
        if metric.consecutive_failures:
            reasons.append(f"{name} has {metric.consecutive_failures} consecutive failure(s)")
    return reasons


def _trust_status_label(status: str) -> str:
    if status == STATUS_OK:
        return "Strong"
    if status in {STATUS_PARTIAL_DATA, STATUS_SCHEDULE_ONLY}:
        return "Limited"
    if status == STATUS_UNAVAILABLE:
        return "Blocked"
    return "Usable"


def _metric_trust_label(metric: Any | None) -> str:
    if metric is None or metric.calls <= 0:
        return "not called"
    if metric.circuit_open:
        return "Blocked"
    if metric.errors >= 2 or metric.success_rate < 50:
        return "Limited"
    if metric.fallbacks > 0 or metric.errors > 0:
        return "Usable"
    return "Strong"


def _format_provider_metric_detail(metric: Any | None) -> str:
    if metric is None or metric.calls <= 0:
        return "No calls recorded yet."
    circuit = "open" if metric.circuit_open else "closed"
    return (
        f"calls={metric.calls}; success={metric.success_rate:.1f}%; "
        f"fallbacks={metric.fallbacks}; errors={metric.errors}; "
        f"latency={metric.avg_latency_ms:.1f}ms; circuit={circuit}; last={metric.last_status}"
    )


def _format_symbol_search(query: str, results: list[SymbolSearchResult]) -> Table:
    table = Table(title=f"Symbol Search: {query}", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Class", no_wrap=True)
    table.add_column("Exchange", no_wrap=True)
    table.add_column("Currency", no_wrap=True)
    table.add_column("Provider Symbols", overflow="fold")
    table.add_column("Notes", overflow="fold")
    for result in results:
        table.add_row(
            result.symbol,
            result.name,
            result.asset_class,
            result.exchange or "-",
            result.currency or "-",
            _provider_symbol_text(result.provider_symbols or {}),
            result.notes or "-",
        )
    if not results:
        table.add_row("-", "No local symbol match.", "-", "-", "-", "-", "Try /symbol resolve <symbol>.")
    table.caption = "Use /symbol resolve <symbol> to inspect provider-specific normalization for any symbol."
    return table


def _format_symbol_matrix(
    symbol: str,
    resolver: SymbolResolver | None = None,
    asset_class: str | None = None,
) -> Table:
    matrix = (resolver or SymbolResolver()).matrix(symbol)
    table = Table(title=f"Provider Symbol Normalization: {symbol}", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Normalized Symbol", style="white")
    table.add_column("Asset Class", no_wrap=True)
    table.add_column("Confidence", no_wrap=True)
    table.add_column("Original", style="dim")
    for provider, resolved in matrix.items():
        asset = asset_class or resolved.asset_class
        table.add_row(provider, resolved.symbol, asset, resolved.confidence, resolved.original)
    table.caption = (
        "Normalization does not guarantee provider entitlement. Check /provider entitlement and provider plan."
    )
    return table


def _provider_symbol_text(provider_symbols: dict[str, str]) -> str:
    return " | ".join(f"{provider}:{symbol}" for provider, symbol in provider_symbols.items())


def _market_provider_secret_keys(provider: str) -> tuple[str, ...]:
    return {
        "custom": ("MARKET_DATA_API_KEY", "MARKET_DATA_BASE_URL"),
        "finnhub": ("FINNHUB_API_KEY",),
        "twelvedata": ("TWELVE_DATA_API_KEY",),
        "alphavantage": ("ALPHA_VANTAGE_API_KEY",),
        "polygon": ("POLYGON_API_KEY",),
        "iex": ("IEX_CLOUD_API_KEY",),
    }.get(provider.lower(), ())


def _format_macro_dashboard(query: str, rows: list[MacroIndicator]) -> Table:
    table = Table(title=f"Macro Dashboard: {query.title()}", expand=True)
    table.add_column("Indicator", style="cyan", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_column("Period", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for row in rows:
        table.add_row(row.name, row.region, row.value, row.period, row.source, row.note)
    if not rows:
        table.add_row("-", "-", "-", "-", "Fallback", "No macro rows matched the query.")
    table.caption = "Fallback rows are connector-ready placeholders. Use provider keys later for exact values."
    return table


def _format_macro_indicator(indicator: str, region: str, rows: list[MacroIndicator]) -> Table:
    table = Table(title=f"Macro Indicator: {indicator.replace('_', ' ').title()} | {region.upper()}", expand=True)
    table.add_column("Period", style="cyan", no_wrap=True)
    table.add_column("Indicator", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_column("Source", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for row in rows:
        table.add_row(row.period, row.name, row.region, row.value, row.source, row.note)
    if not rows:
        table.add_row("-", indicator, region.upper(), "-", "Alpha Vantage", "No data returned.")
    table.caption = "Hidden macro alias. Verify releases with official sources."
    return table


def _format_trading_overview(
    realtime: RealtimeConnectorCatalog, brokers: BrokerCatalog, paper: PaperTradingEngine | None = None
) -> Table:
    kill_active = paper.is_kill_switch_active() if paper else False
    daily_pnl = paper.daily_pnl() if paper else 0.0
    table = Table(title="Trading Layer | Safe Execution Workspace", expand=True)
    table.add_column("Area", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    risk_status = "KILL SWITCH ACTIVE" if kill_active else "active"
    risk_style = "red" if kill_active else "green"
    table.add_row(
        "Risk Guard", f"[{risk_style}]{risk_status}[/]", f"Daily PnL: ${daily_pnl:,.2f}. Use /trading risk for details."
    )
    table.add_row(
        "Real-Time Trading",
        "configurable",
        f"{len(realtime.all())} realtime connector(s). Use /trading realtime or /trading stream.",
    )
    table.add_row(
        "Broker Integrations", "catalog", f"{len(brokers.all())} broker integration(s). Use /trading brokers."
    )
    table.add_row(
        "Paper Trading", "active", "Local paper orders with risk guard. Use /trading paper buy AAPL 1 market 100."
    )
    table.add_row("Audit Log", "active", "All orders logged. Use /trading audit.")
    table.add_row("Live Orders", "disabled", "No live broker orders are sent by FinCLI v1.0.0.")
    table.caption = "Trading features are simulation/catalog first. Configure broker adapters only after explicit live-trading safety work."
    return table


def _format_realtime_connectors(connectors: tuple[RealtimeConnector, ...]) -> Table:
    table = Table(title="Real-Time Connector Catalog", expand=True)
    table.add_column("Connector", style="cyan", no_wrap=True)
    table.add_column("Transport", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for connector in connectors:
        table.add_row(
            connector.name,
            connector.transport,
            ", ".join(connector.asset_classes),
            connector.status,
            connector.note,
        )
    return table


def _format_brokers(brokers: tuple[BrokerIntegration, ...]) -> Table:
    table = Table(title="Broker Integration Catalog", expand=True)
    table.add_column("Broker", style="cyan", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    table.add_column("Mode", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for broker in brokers:
        table.add_row(
            broker.name,
            broker.region,
            ", ".join(broker.asset_classes),
            broker.mode,
            broker.note,
        )
    table.caption = "Catalog entries are not live execution adapters yet unless explicitly marked and configured."
    return table


def _format_live_trading_help() -> Panel:
    return Panel(
        "Live Trading Commands:\n\n"
        "  /trading live status          — Broker connection status\n"
        "  /trading live connect <broker> [paper|live]  — Connect to broker\n"
        "  /trading live disconnect      — Disconnect\n"
        "  /trading live account         — Broker account info\n"
        "  /trading live positions       — Positions from broker\n"
        "  /trading live orders [status] — Order history\n"
        "  /trading live buy <symbol> <qty> [--confirm] [--price <p>]  — Buy order\n"
        "  /trading live sell <symbol> <qty> [--confirm] [--price <p>] — Sell order\n"
        "  /trading live cancel <id>     — Cancel order\n\n"
        "Safety:\n"
        "  • All orders require --confirm flag or interactive confirmation\n"
        "  • Risk guard active (same as paper trading)\n"
        "  • Kill switch blocks paper AND live orders\n"
        "  • All orders logged to audit log\n\n"
        "Supported Brokers: Alpaca (paper + live)\n"
        "API Keys: ALPACA_API_KEY, ALPACA_SECRET_KEY",
        title="Live Trading",
        border_style="cyan",
    )


def _format_live_status(live_trading) -> Panel:
    if live_trading.is_connected():
        status = f"Connected to {live_trading.broker_name} ({live_trading.mode} mode)"
        style = "green"
    else:
        status = "Not connected. Use /trading live connect <broker>"
        style = "yellow"
    return Panel(status, title="Live Trading Status", border_style=style)


def _format_connection_status(status) -> Panel:
    style = "green" if status.connected else "red"
    return Panel(status.message, title=f"Broker Connection ({status.broker})", border_style=style)


def _format_broker_account(account) -> Table:
    table = Table(title=f"Broker Account ({account.broker})", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Account ID", account.account_id)
    table.add_row("Cash", f"${account.cash:,.2f}")
    table.add_row("Portfolio Value", f"${account.portfolio_value:,.2f}")
    table.add_row("Buying Power", f"${account.buying_power:,.2f}")
    table.add_row("Equity", f"${account.equity:,.2f}")
    table.add_row("Currency", account.currency)
    return table


def _format_broker_positions(positions) -> Table:
    table = Table(title="Broker Positions", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Avg Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("Side", no_wrap=True)
    for pos in positions:
        pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
        table.add_row(
            pos.symbol,
            f"{pos.quantity:.4f}",
            f"${pos.avg_entry_price:,.2f}",
            f"${pos.current_price:,.2f}",
            f"${pos.market_value:,.2f}",
            f"[{pnl_style}]${pos.unrealized_pnl:,.2f}[/]",
            pos.side,
        )
    if not positions:
        table.add_row("-", "-", "-", "-", "-", "-", "-")
    return table


def _format_broker_orders(orders) -> Table:
    table = Table(title="Broker Orders", expand=True)
    table.add_column("Order ID", style="cyan", no_wrap=True)
    table.add_column("Symbol", no_wrap=True)
    table.add_column("Side", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Status", no_wrap=True)
    table.add_column("Created", no_wrap=True)
    for order in orders:
        table.add_row(
            order.broker_order_id[:12] + "...",
            order.symbol,
            order.side,
            order.order_type,
            f"{order.quantity:.4f}",
            f"${order.price:,.2f}" if order.price else "-",
            order.status,
            order.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    if not orders:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "-")
    return table


def _format_order_confirmation(conf) -> Panel:
    risk_style = "green" if conf.risk_check_passed else "red"
    risk_text = "PASSED" if conf.risk_check_passed else f"BLOCKED: {conf.risk_check_reason}"

    price_line = f"  Price       : ${conf.price:,.2f}\n" if conf.price else ""
    text = (
        f"⚠️  LIVE ORDER CONFIRMATION\n\n"
        f"  Symbol      : {conf.symbol}\n"
        f"  Side        : {conf.side.upper()}\n"
        f"  Quantity    : {conf.quantity}\n"
        f"  Order Type  : {conf.order_type}\n"
        f"{price_line}"
        f"  Est. Cost   : ${conf.estimated_cost:,.2f}\n\n"
        f"  Risk Check  : [{risk_style}]{risk_text}[/]\n"
        f"  Broker      : {conf.broker}\n"
        f"  Mode        : {conf.mode}\n\n"
        f"  Add --confirm flag to execute order:\n"
        f"  /trading live {conf.side} {conf.symbol} {conf.quantity} --confirm"
    )
    return Panel(text, title="Order Confirmation Required", border_style="yellow")


def _format_live_order_result(result) -> Table:
    table = Table(title="Live Order Result", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    return table


def _format_paper_order(order: dict[str, object]) -> Table:
    table = Table(title="Paper Trading Order", expand=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")
    for key in ("side", "symbol", "quantity", "order_type", "price", "notional", "status", "strategy"):
        table.add_row(key, str(order.get(key, "-")))
    table.caption = "Paper trading only. No broker/live order was sent."
    return table


def _format_paper_orders(orders: list[dict[str, object]]) -> Table:
    table = Table(title="Paper Trading Orders", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Side", no_wrap=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Type", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Notional", justify="right")
    table.add_column("Status", no_wrap=True)
    table.add_column("Created", no_wrap=True)
    for order in orders:
        table.add_row(
            str(order.get("id", "-")),
            str(order.get("side", "-")),
            str(order.get("symbol", "-")),
            _format_optional_number(order.get("quantity")),
            str(order.get("order_type", "-")),
            _format_optional_number(order.get("price")),
            _format_optional_number(order.get("notional")),
            str(order.get("status", "-")),
            str(order.get("created_at", "-")),
        )
    if not orders:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "empty", "-")
    table.caption = "Paper trading orders are stored locally in SQLite."
    return table


def _format_risk_status(paper: PaperTradingEngine) -> Table:
    table = Table(title="Trading Risk Guard", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Value")
    kill_active = paper.is_kill_switch_active()
    table.add_row("Kill Switch", "[red]ACTIVE[/]" if kill_active else "[green]inactive[/]")
    table.add_row("Daily PnL", f"${paper.daily_pnl():,.2f}")
    table.add_row("Max Position Size", f"{paper.risk_guard.max_position_pct:.0%} of equity")
    table.add_row("Daily Loss Limit", f"{paper.risk_guard.daily_loss_limit_pct:.0%} of equity")
    profile = paper.risk_guard._get_profile()
    if profile:
        table.add_row("Portfolio Equity", f"${float(profile['equity']):,.2f} {profile['currency']}")
    else:
        table.add_row("Portfolio Equity", "No profile set. Use /profile set ...")
    table.caption = "Risk guard checks run before every paper order."
    return table


def _format_audit_log(entries: list[dict[str, object]]) -> Table:
    table = Table(title="Order Audit Log", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Order ID", justify="right")
    table.add_column("Action", style="cyan", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    table.add_column("Time", no_wrap=True)
    for entry in entries:
        table.add_row(
            str(entry.get("id", "-")),
            str(entry.get("order_id", "-")),
            str(entry.get("action", "-")),
            str(entry.get("detail", "")),
            str(entry.get("created_at", "-")),
        )
    if not entries:
        table.add_row("-", "-", "-", "No audit entries.", "-")
    table.caption = "Audit log is immutable. Entries are never updated or deleted."
    return table


def _format_positions(positions: list[dict[str, object]]) -> Table:
    table = Table(title="Paper Trading Positions", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Net Qty", justify="right")
    table.add_column("Avg Price", justify="right")
    table.add_column("Buy Notional", justify="right")
    table.add_column("Sell Notional", justify="right")
    table.add_column("Realized PnL", justify="right")
    table.add_column("Orders", justify="right")
    for pos in positions:
        table.add_row(
            str(pos.get("symbol", "-")),
            _format_optional_number(pos.get("net_quantity")),
            _format_optional_number(pos.get("avg_price")),
            _format_optional_number(pos.get("buy_notional")),
            _format_optional_number(pos.get("sell_notional")),
            _format_optional_number(pos.get("realized_pnl")),
            str(pos.get("order_count", "-")),
        )
    if not positions:
        table.add_row("-", "-", "-", "-", "-", "-", "No positions. Use /trading paper buy ...")
    return table


def _format_broker_status(catalog: BrokerCatalog) -> Table:
    table = Table(title="Broker Adapter Status", expand=True)
    table.add_column("Broker", style="cyan", no_wrap=True)
    table.add_column("Mode", no_wrap=True)
    table.add_column("Status")
    for broker in catalog.all():
        status = (
            "ready"
            if broker.mode in {"paper_ready", "sandbox_ready"}
            else "stub"
            if broker.mode == "adapter_stub"
            else "requires gateway"
        )
        table.add_row(broker.name, broker.mode, status)
    table.caption = "Use /trading broker use <name> to activate a broker adapter."
    return table


def _format_stream_status(connectors: tuple[RealtimeConnector, ...]) -> Table:
    table = Table(title="Realtime Stream Status", expand=True)
    table.add_column("Connector", style="cyan", no_wrap=True)
    table.add_column("Transport", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    for connector in connectors:
        table.add_row(connector.name, connector.transport, connector.status, ", ".join(connector.asset_classes))
    table.caption = "Use /trading stream <connector> to view connection config."
    return table


def _macro_error_row(indicator: str, region: str, exc: FinCLIError) -> MacroIndicator:
    label = indicator.replace("_", " ").title()
    help_text = f" {exc.help_text}" if getattr(exc, "help_text", None) else ""
    return MacroIndicator(
        name=label,
        region=region.upper(),
        value="unavailable",
        period=date.today().isoformat(),
        source="Alpha Vantage",
        note=f"{exc}{help_text}",
    )


def _format_insider_transactions(symbol: str, rows: list[dict[str, object]]) -> Table:
    table = Table(title=f"Finnhub Insider Transactions: {symbol}", expand=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Code", no_wrap=True)
    table.add_column("Change", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Price", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("date") or "-"),
            str(row.get("name") or "-"),
            str(row.get("transaction_code") or "-"),
            _format_optional_number(row.get("change")),
            _format_optional_number(row.get("shares")),
            _format_optional_number(row.get("transaction_price")),
        )
    if not rows:
        table.add_row("-", "No insider transactions returned.", "-", "-", "-", "-")
    table.caption = "Finnhub endpoint availability depends on API key, plan, and symbol coverage."
    return table


def _format_ipo_calendar(rows: list[dict[str, object]], start: date, end: date) -> Table:
    table = Table(title=f"Finnhub IPO Calendar | {start.isoformat()} to {end.isoformat()}", expand=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Symbol", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Exchange", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Status", no_wrap=True)
    for row in rows:
        table.add_row(
            str(row.get("date") or "-"),
            str(row.get("symbol") or "-"),
            str(row.get("name") or "-"),
            str(row.get("exchange") or "-"),
            str(row.get("price") or "-"),
            _format_optional_number(row.get("shares")),
            str(row.get("status") or "-"),
        )
    if not rows:
        table.add_row("-", "-", "No IPOs returned for the selected window.", "-", "-", "-", "-")
    table.caption = "Finnhub endpoint availability depends on API key, plan, and date coverage."
    return table


def _format_optional_number(value: object) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _format_user_profile(profile: UserProfile | None) -> Table:
    table = Table(title="User Gameplay Profile", expand=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    if profile is None:
        table.add_row("Status", "Not configured")
        table.add_row("Setup", '/profile set "Nama" <equity> <currency> <leverage> <years>')
        table.add_row("Use", "Profile is used by /analyze for SL/TP and risk-context wording.")
        return table
    table.add_row("Name", profile.name)
    table.add_row("Equity", f"{profile.equity:g} {profile.currency}")
    table.add_row("Leverage", profile.leverage)
    table.add_row("Investment Years", f"{profile.years_in_investment:g}")
    table.add_row("Gameplay", profile.gameplay)
    table.add_row("Analyze Usage", "Used by /analyze to constrain Signal, SL, TP1, TP2, TP3, and Reason.")
    return table


def _format_agents(agents: list[Agent], label: str) -> Table:
    table = Table(title=f"FinCLI Agents: {label}", expand=True)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Framework", overflow="fold")
    table.add_column("Role", overflow="fold")
    for agent in agents:
        table.add_row(agent.slug, agent.name, agent.category, agent.framework, agent.role)
    if not agents:
        table.add_row("-", "-", "-", "-", "No agents matched.")
    return table


def _format_agent(agent: Agent) -> Panel:
    return Panel(
        "\n".join(
            [
                f"Name      : {agent.name}",
                f"Slug      : {agent.slug}",
                f"Category  : {agent.category}",
                f"Framework : {agent.framework}",
                f"Role      : {agent.role}",
                "",
                "Usage     : use as a thinking lens for /research and future multi-agent analysis.",
            ]
        ),
        title="FinCLI Agent",
        border_style="cyan",
    )


def _format_connectors(connectors: list[Connector], label: str) -> Table:
    table = Table(title=f"Connector Catalog: {label}", expand=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Access", no_wrap=True)
    table.add_column("Coverage", overflow="fold")
    for connector in connectors:
        table.add_row(connector.name, connector.category, connector.access, connector.coverage)
    if not connectors:
        table.add_row("-", "-", "-", "No connectors matched.")
    table.caption = "Catalog entries are roadmap-ready; active adapters depend on implementation and entitlement."
    return table


def _format_news_connectors(connectors: list[NewsConnectorSpec], label: str) -> Table:
    table = Table(title=f"News Connector Catalog: {label}", expand=True)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Access", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("API Key", no_wrap=True)
    table.add_column("Status", overflow="fold")
    for connector in connectors:
        status = "active rss" if connector.access == "public-rss" else "api-key ready"
        if connector.slug == "custom_news":
            status = "custom endpoint"
        table.add_row(
            connector.slug,
            connector.name,
            connector.access,
            connector.category,
            connector.env_key or "-",
            status,
        )
    if not connectors:
        table.add_row("-", "No news connectors matched.", "-", "-", "-", "-")
    table.caption = (
        "Use /news_model use <slug> for primary, /news_model priority a,b,c for fallback order, "
        "and /news_model key <slug> <api_key> for API-key providers."
    )
    return table


def _format_plugins(plugins: list[PluginManifest], status_only: bool = False) -> Table:
    table = Table(title="FinCLI Plugins" if not status_only else "FinCLI Plugin Status", expand=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Capabilities", overflow="fold")
    table.add_column("Commands", overflow="fold")
    if not status_only:
        table.add_column("Description", overflow="fold")
    for plugin in plugins:
        row = [
            plugin.name,
            plugin.version,
            plugin.status,
            ", ".join(plugin.capabilities) or "-",
            ", ".join(plugin.commands) or "-",
        ]
        if not status_only:
            row.append(plugin.description or "-")
        table.add_row(*row)
    if not plugins:
        empty = ["-", "-", "no plugins", "-", "-"]
        if not status_only:
            empty.append("Create ~/.fincli/plugins/<name>/plugin.json to register a local plugin.")
        table.add_row(*empty)
    table.caption = "Plugins are manifest-only; FinCLI does not execute plugin code yet."
    return table


def _format_plugin_validation(results: list[tuple[PluginManifest, list]]) -> Table:
    table = Table(title="Plugin Validation", expand=True)
    table.add_column("Plugin", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Errors", overflow="fold")
    for plugin, errors in results:
        if not errors:
            table.add_row(plugin.name, "[green]valid[/]", "-")
        else:
            error_text = "\n".join(f"- {e.field}: {e.message}" for e in errors)
            table.add_row(plugin.name, "[red]invalid[/]", error_text)
    if not results:
        table.add_row("-", "-", "No plugins found.")
    return table


def _format_transactions(rows: list[dict[str, object]]) -> Table:
    table = Table(title="Transaction Ledger", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Action")
    table.add_column("Symbol", style="cyan")
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Realized PnL", justify="right")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            str(row["id"]),
            str(row["action"]),
            str(row["symbol"]),
            _fmt(float(row["quantity"])),
            _fmt(float(row["price"])),
            _fmt(float(row["realized_pnl"])),
            str(row["created_at"]),
        )
    if not rows:
        table.add_row("-", "-", "-", "-", "-", "-", "No transactions yet. Use /tx add buy AAPL 10 100")
    return table


def _format_journal_stats(stats: JournalStats) -> Table:
    table = Table(title="Journal Stats", expand=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total Entries", str(stats.total_entries))
    table.add_row("Wins", str(stats.wins))
    table.add_row("Losses", str(stats.losses))
    table.add_row("Win Rate", _fmt_pct(stats.win_rate))
    table.add_row("Top Instrument", stats.top_instrument)
    table.add_row("Top Emotion", stats.top_emotion)
    table.add_row("Top Tags", ", ".join(stats.top_tags) if stats.top_tags else "N/A")
    return table


def _format_news(symbol: str, items: list[NewsItem]) -> str:
    if not items:
        return f"News: {symbol}\nNo news from active provider."
    lines = [f"News: {symbol}"]
    for index, item in enumerate(items, start=1):
        published = item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown time"
        url = f"\n   URL: {item.url}" if item.url else ""
        summary = f"\n   Summary: {item.summary}" if item.summary else ""
        lines.append(f"{index}. {item.title}\n   Source: {item.source} | Published: {published}{summary}{url}")
    return "\n".join(lines)


def _format_news_desk(desk: NewsDesk) -> Table:
    table = Table(title=f"News Desk: {desk.symbol}", expand=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("Headline", style="white", overflow="fold")
    table.add_column("Summary", overflow="fold")
    table.add_column("Analysis", overflow="fold")
    for item in desk.items:
        published = item.published_at.isoformat(timespec="minutes") if item.published_at else "unknown"
        table.add_row(published, item.source, item.title, item.summary or "-", _news_item_analysis(item))
    if not desk.items:
        table.add_row("-", "-", "No news from active providers.", desk.note, "-")
    lookback = f" | Lookback: {desk.lookback_days}d" if desk.lookback_days else ""
    quality = _news_data_quality(desk)
    errors = f" | Errors: {len(desk.errors)}" if desk.errors else ""
    table.caption = (
        f"Providers: {', '.join(desk.provider_chain)}{lookback} | "
        f"Reliability: {desk.reliability_status}{errors} | Data Quality: {quality.compact()} | {desk.note}"
    )
    return table


def _news_item_analysis(item: NewsItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    bullish_words = (
        "beat",
        "beats",
        "rise",
        "rises",
        "rally",
        "rallies",
        "higher",
        "growth",
        "upgrade",
        "bullish",
        "record",
    )
    bearish_words = (
        "miss",
        "falls",
        "falling",
        "lower",
        "sink",
        "sinks",
        "down",
        "cut",
        "downgrade",
        "bearish",
        "weak",
    )
    caution_words = ("risk", "uncertain", "probe", "lawsuit", "volatility", "warning", "recall", "delay")
    bullish = sum(1 for word in bullish_words if word in text)
    bearish = sum(1 for word in bearish_words if word in text)
    caution = sum(1 for word in caution_words if word in text)
    if caution and caution >= max(bullish, bearish):
        bias = "caution"
    elif bullish > bearish:
        bias = "bullish"
    elif bearish > bullish:
        bias = "bearish"
    else:
        bias = "neutral"
    if item.published_at is None:
        freshness = "date unknown"
    else:
        freshness = "fresh" if _news_age_days(item) <= 3 else "older context"
    return semantic_text(f"{bias} | {freshness} | keyword-based (approximate) | verify source before trading")


def _news_age_days(item: NewsItem) -> int:
    if item.published_at is None:
        return 999
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    from datetime import datetime

    return max((datetime.now(UTC) - published).days, 0)


def _news_data_quality(desk: NewsDesk) -> DataQualityReport:
    item_count = len(desk.items)
    score = 20
    if item_count >= 8:
        score = 85
    elif item_count >= 3:
        score = 70
    elif item_count >= 1:
        score = 55
    if desk.errors:
        score = max(20, score - min(30, len(desk.errors) * 10))
    missing = () if item_count else ("news",)
    tier = "strong" if score >= 85 else "usable" if score >= 65 else "partial" if score >= 40 else "weak"
    return DataQualityReport(
        score=score,
        quote="not_applicable",
        ohlcv="not_applicable",
        news=f"{item_count} item(s)",
        fundamentals="not_applicable",
        provider=", ".join(desk.provider_chain) or "unknown",
        tier=tier,
        freshness=f"{desk.lookback_days or 'latest'}d",
        reliability_status=desk.reliability_status,
        missing_fields=missing,
        label=f"{tier} | {desk.reliability_status}",
    )


def _format_web_results(query: str, results: list[WebSearchResult]) -> Table:
    table = Table(title=f"Web Research: {query}", expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Title", style="cyan", overflow="fold")
    table.add_column("Snippet / Extract", overflow="fold")
    table.add_column("URL", style="dim", overflow="fold")
    for index, result in enumerate(results, start=1):
        extract = result.content[:500] if result.content else result.snippet
        table.add_row(str(index), result.title, extract or "-", result.url)
    if not results:
        table.add_row("-", "No results", "Search providers returned no public context.", "-")
    table.caption = "Web context is public web data; verify source quality before using it for financial decisions."
    return table


def _format_fundamentals(snapshot: FundamentalSnapshot) -> str:
    return (
        f"Fundamental Snapshot: {snapshot.symbol}\n"
        f"Provider: {snapshot.provider}\n"
        f"Currency: {snapshot.currency}\n"
        f"Market Cap: {_fmt(snapshot.market_cap)}\n"
        f"P/E Ratio: {_fmt(snapshot.pe_ratio)}\n"
        f"EPS: {_fmt(snapshot.eps)}\n"
        f"Revenue: {_fmt(snapshot.revenue)}\n"
        f"Beta: {_fmt(snapshot.beta)}\n"
        f"Sector: {snapshot.sector or 'N/A'}\n"
        f"Industry: {snapshot.industry or 'N/A'}"
    )


def _format_yahoo_table(dataset: YahooTable) -> Table:
    table = Table(title=f"Yahoo Finance {dataset.section}: {dataset.symbol}", expand=True)
    for index, column in enumerate(dataset.columns):
        table.add_column(str(column), style="cyan" if index == 0 else "white", overflow="fold")

    for row in dataset.rows:
        normalized = [str(value) for value in row[: len(dataset.columns)]]
        normalized += [""] * max(0, len(dataset.columns) - len(normalized))
        table.add_row(*normalized)

    if not dataset.rows:
        table.add_row(*(["No data returned by yfinance/Yahoo."] + [""] * (len(dataset.columns) - 1)))

    note = dataset.note or "Data source: yfinance/Yahoo Finance. Realtime/delayed status depends on exchange coverage."
    table.caption = f"{note}\nSource: {dataset.source_url}"
    return table


def _format_news_context(items: list[NewsItem]) -> str:
    if not items:
        return "News: no recent news from active provider."
    lines = ["News:"]
    for item in items:
        published = item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown time"
        summary = f" - {item.summary}" if item.summary else ""
        lines.append(f"- {item.title} ({item.source}, {published}){summary}")
    return "\n".join(lines)


def _format_fundamental_context(snapshot: FundamentalSnapshot) -> str:
    return (
        "Fundamentals:\n"
        f"- Symbol: {snapshot.symbol}\n"
        f"- Currency: {snapshot.currency}\n"
        f"- Market Cap: {_fmt(snapshot.market_cap)}\n"
        f"- P/E Ratio: {_fmt(snapshot.pe_ratio)}\n"
        f"- EPS: {_fmt(snapshot.eps)}\n"
        f"- Revenue: {_fmt(snapshot.revenue)}\n"
        f"- Beta: {_fmt(snapshot.beta)}\n"
        f"- Sector: {snapshot.sector or 'N/A'}\n"
        f"- Industry: {snapshot.industry or 'N/A'}"
    )


def _format_ai_response(response: AIResponse) -> AIResponseView:
    return AIResponseView(response)


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.4f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.1f}%"


def _validate_symbol(symbol: str) -> str:
    """Validate and normalize a symbol. Raises CommandError on invalid input."""
    import re

    if not symbol or not symbol.strip():
        raise CommandError("Symbol cannot be empty.")
    normalized = symbol.strip().upper()
    # Reject path traversal and shell metacharacters
    dangerous = re.search(r"[.;|&`$!#~<>{}()\[\]\\]", normalized)
    if dangerous:
        raise CommandError(f"Symbol contains invalid character: '{dangerous.group()}'.")
    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise CommandError(f"Symbol cannot contain path separator: '{normalized}'.")
    if len(normalized) > 20:
        raise CommandError(f"Symbol too long (max 20 characters): '{normalized}'.")
    return normalized


def _split_command(raw: str) -> list[str]:
    parts = shlex.split(raw, posix=os.name != "nt")
    if os.name == "nt":
        return [_strip_wrapping_quotes(part) for part in parts]
    return parts


def _interactive_select(
    items: list[tuple[str, str]],
    title: str,
    current: str = "",
    console: Console | None = None,
) -> str | None:
    """Show numbered list, prompt user to select by number. Returns selected key or None."""
    con = console or Console()
    if not items:
        con.print("[dim]No items available.[/dim]")
        return None
    con.print(f"\n[bold cyan]{title}[/bold cyan]")
    for i, (key, label) in enumerate(items, 1):
        marker = " [green]● current[/green]" if key == current else ""
        con.print(f"  [bold]{i}.[/bold] {label}{marker}")
    con.print()
    try:
        raw = input("Select number (or Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        con.print("[dim]Cancelled.[/dim]")
        return None
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        con.print("[red]Invalid input. Enter a number.[/red]")
        return None
    if idx < 1 or idx > len(items):
        con.print(f"[red]Out of range (1-{len(items)}).[/red]")
        return None
    return items[idx - 1][0]


def _interactive_prompt(prompt: str, mask: bool = False) -> str | None:
    """Prompt user for text input. Returns value or None if cancelled."""
    try:
        if mask:
            value = getpass.getpass(f"{prompt}: ")
        else:
            value = input(f"{prompt}: ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        return None
    return value if value else None


def _doctor_live_symbol(args: list[str]) -> str:
    lowered = [arg.lower() for arg in args]
    if "--live" not in lowered:
        return "AAPL"
    index = lowered.index("--live")
    if len(args) > index + 1 and not args[index + 1].startswith("--"):
        return args[index + 1].upper()
    return "AAPL"


def _router_roots() -> set[str]:
    """Return slash command roots directly handled by CommandRouter."""

    return {
        "/agent",
        "/ai",
        "/ai_model",
        "/alert",
        "/analyze",
        "/backtest",
        "/cache",
        "/calendar",
        "/chart",
        "/clear",
        "/config",
        "/connector",
        "/dashboard",
        "/doctor",
        "/exit",
        "/export",
        "/help",
        "/history",
        "/journal",
        "/macro",
        "/market",
        "/mtf",
        "/news",
        "/news_model",
        "/notification",
        "/plugin",
        "/portfolio",
        "/profile",
        "/provider",
        "/report",
        "/research",
        "/scan",
        "/secrets",
        "/security",
        "/session",
        "/setup",
        "/symbol",
        "/technical",
        "/trading",
        "/tutorial",
        "/tx",
        "/watchlist",
        "/web",
        "/yahoo",
    }


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


# ---------------------------------------------------------------------------
# Tutorial helpers
# ---------------------------------------------------------------------------

TUTORIAL_LESSONS = {
    1: {
        "title": "Welcome & Setup",
        "subtitle": "Get started with FinCLI",
        "steps": [
            (
                "Set your profile",
                '/profile set "Your Name" 10000 USD 1:1 2',
                "Your profile helps FinCLI personalize risk calculations.",
            ),
            ("Check system health", "/doctor", "See if everything is configured correctly."),
            ("View setup guide", "/setup", "See recommended setup steps."),
        ],
        "tip": "You can skip API keys for now — FinCLI works with free providers like yfinance!",
    },
    2: {
        "title": "Market Data",
        "subtitle": "Quotes, overviews, and news",
        "steps": [
            ("Get a quick quote", "/market AAPL", "Get the latest price for any symbol."),
            ("Full market overview", "/market AAPL 1d", "See technicals, structure, and data quality."),
            ("Read latest news", "/news AAPL", "Get news from multiple sources."),
            ("Deep research", "/research AAPL --deep", "AI-powered research with cited sources."),
        ],
        "tip": "Use any symbol — stocks (AAPL), crypto (BTC-USD), forex (EURUSD=X), commodities (XAUUSD).",
    },
    3: {
        "title": "Technical Analysis",
        "subtitle": "Indicators, structure, and signals",
        "steps": [
            ("Technical analysis", "/technical AAPL 1d", "RSI, MACD, Bollinger, support/resistance."),
            ("Multi-timeframe", "/mtf AAPL 1d,1h,15m", "Check alignment across timeframes."),
            ("AI analysis", "/analyze AAPL 1d", "AI interprets the technicals for you."),
            ("Market structure", "/technical AAPL 1d", "BOS, CHoCH, liquidity zones."),
        ],
        "tip": "Technical analysis is educational, not financial advice. Always use confirmation.",
    },
    4: {
        "title": "Portfolio Management",
        "subtitle": "Track positions and risk",
        "steps": [
            ("Add a position", "/portfolio add AAPL 10 150", "Add 10 shares of AAPL at $150."),
            ("View portfolio", "/portfolio", "See all positions with PnL."),
            ("Check risk", "/portfolio risk", "Exposure, concentration, health score."),
            ("Save snapshot", "/portfolio snapshot", "Track portfolio value over time."),
            ("Benchmark", "/portfolio benchmark SPY", "Compare vs S&P 500."),
        ],
        "tip": "Use /portfolio whatif to test changes before committing!",
    },
    5: {
        "title": "Paper Trading",
        "subtitle": "Practice without risk",
        "steps": [
            ("Place a paper order", "/trading paper buy AAPL 1 market 150", "Simulate buying 1 share."),
            ("View positions", "/trading positions", "See aggregated paper positions."),
            ("Check risk guard", "/trading risk", "See daily PnL and limits."),
        ],
        "tip": "Paper trading uses risk guards to protect you. Use /trading kill to stop all orders.",
    },
    6: {
        "title": "Alerts & Monitoring",
        "subtitle": "Stay informed automatically",
        "steps": [
            ("Add price alert", "/alert add AAPL above 200", "Get notified when price hits $200."),
            ("Add to watchlist", "/watchlist add AAPL", "Track symbols in your watchlist."),
            ("Scan watchlist", "/scan watchlist rsi<30", "Find oversold stocks."),
            ("Start alert daemon", "/alert daemon start", "Background alert checking."),
        ],
        "tip": "You can set conditional alerts too: rsi_below, volume_above, macd_cross_up.",
    },
    7: {
        "title": "Export & Reports",
        "subtitle": "Save and share your research",
        "steps": [
            ("Export research", "/research AAPL --report --export md report.md", "Save research as Markdown."),
            ("Run backtest", "/backtest AAPL sma_cross 1d", "Test a strategy on historical data."),
            ("Export everything", "/export all json ./exports", "Batch export all your data."),
            ("View history", "/history", "See all commands you've run."),
        ],
        "tip": "Use /backtest --monte-carlo to test strategy robustness!",
    },
}


def _format_tutorial_menu() -> Table:
    table = Table(title="🎓 FinCLI Tutorial — Interactive Guide", expand=True)
    table.add_column("#", style="cyan", justify="center", width=3)
    table.add_column("Lesson", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Command", style="green")
    for num, lesson in TUTORIAL_LESSONS.items():
        table.add_row(str(num), lesson["title"], lesson["subtitle"], f"/tutorial {num}")
    table.caption = "Type /tutorial <number> to start a lesson. Use /tutorial next to go through them in order."
    return table


def _tutorial_lesson(num: int) -> Panel:
    lesson = TUTORIAL_LESSONS.get(num)
    if lesson is None:
        return Panel("Lesson not found. Use /tutorial to see available lessons.", title="Tutorial", border_style="red")

    lines = [
        f"[bold cyan]🎓 Tutorial: {lesson['title']} ({num}/7)[/bold cyan]",
        "",
        f"[dim]{lesson['subtitle']}[/dim]",
        "",
        "[bold]What you'll learn:[/bold]",
    ]
    for i, (step_title, cmd, explanation) in enumerate(lesson["steps"], 1):
        lines.append(f"  {i}. [bold]{step_title}[/bold]")
        lines.append(f"     [green]{cmd}[/green]")
        lines.append(f"     [dim]{explanation}[/dim]")
        lines.append("")

    lines.append(f"[bold yellow]💡 Tip:[/bold yellow] {lesson['tip']}")
    lines.append("")
    lines.append("[dim]Type /tutorial next for the next lesson, or /tutorial to see all lessons.[/dim]")

    return Panel("\n".join(lines), title=f"Tutorial: {lesson['title']}", border_style="cyan")


def _tutorial_next(router: object) -> Panel:
    if not hasattr(router, "_tutorial_progress"):
        router._tutorial_progress = 0
    router._tutorial_progress += 1
    if router._tutorial_progress > 7:
        router._tutorial_progress = 1
    return _tutorial_lesson(router._tutorial_progress)


class UnavailableAIProvider:
    """Default AI provider used until a concrete API client is configured."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: AIRequest) -> AIResponse:
        raise CommandError(
            f"AI provider {self.name} is not ready.",
            "Use /ai_model to select provider and /ai_model key <provider> <api_key> to save API key.",
        )
