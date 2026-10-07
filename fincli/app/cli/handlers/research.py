"""Command parsing and routing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel

from fincli.app.analysis.analyzer import build_technical_ai_summary
from fincli.app.analysis.backtest import BacktestResult, run_backtest
from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.analysis.market_structure import analyze_market_structure
from fincli.app.analysis.multi_timeframe import analyze_multi_timeframe
from fincli.app.analysis.technical_debate import run_technical_debate
from fincli.app.cli.handlers.common import (
    _calendar_fallback_note,
    _calendar_static_fallback_note,
    _extract_option_value,
    _format_backtest,
    _format_backtest_compare,
    _format_calendar,
    _format_macro_dashboard,
    _format_macro_indicator,
    _format_market_overview,
    _format_multi_timeframe,
    _format_news_desk,
    _format_scan_results,
    _format_technical,
    _format_yahoo_table,
    _macro_error_row,
    _parse_calendar_args,
    _parse_news_lookback,
    _parse_timeframes,
    _scan_result_rows,
)
from fincli.app.cli.result import CommandResult
from fincli.app.modules.economic_calendar import (
    EconomicCalendarService,
    EconomicEvent,
    PublicEconomicCalendarService,
    economic_event_rows,
    fallback_events,
    filter_events,
)
from fincli.app.modules.exporter import export_rows
from fincli.app.modules.reports import write_market_report
from fincli.app.modules.scanner import scan_symbols
from fincli.app.providers.market.base import (
    Quote,
)
from fincli.app.providers.market.yfinance_provider import YahooTable, YFinanceProvider
from fincli.app.research import ResearchEngine, format_research_brief, write_research_report
from fincli.app.services.market_overview import build_market_overview
from fincli.app.services.news_aggregator import NewsAggregator
from fincli.app.storage.secrets import read_secrets
from fincli.app.utils.errors import CommandError, FinCLIError

if TYPE_CHECKING:
    from datetime import date


logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class ResearchCommands:
    """Research command handlers."""

    def _research(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /research <symbol> [--deep|--report] [timeframe] [--export <md|json> <path>]")
        symbol = args[0].upper()
        export_format: str | None = None
        export_target: str | None = None
        if "--export" in args:
            export_index = args.index("--export")
            if len(args) <= export_index + 2:
                raise CommandError("Format export: /research <symbol> --report --export <md|json> <path>")
            export_format = args[export_index + 1]
            export_target = args[export_index + 2]
        flags = {arg.lower() for arg in args[1:] if arg.startswith("--")}
        if "--report" in flags:
            mode = "report"
        elif "--deep" in flags:
            mode = "deep"
        else:
            # --snapshot/--quick and no flag all resolve to the compact snapshot mode.
            mode = "snapshot"
        ignored: set[int] = set()
        if "--export" in args:
            export_index = args.index("--export")
            ignored.update({export_index, export_index + 1, export_index + 2})
        timeframe = next(
            (arg for index, arg in enumerate(args[1:], start=1) if index not in ignored and not arg.startswith("--")),
            "1d",
        )
        engine = ResearchEngine(
            self.market_service,
            self.ai_provider,
            self.config.settings.ai_model,
            macro_service=self.macro_data,
            web_research=self.web_research,
        )
        brief = self._run_async(engine.build(symbol, timeframe=timeframe, mode=mode))
        if export_format and export_target:
            written = write_research_report(brief, export_format, export_target)
            return CommandResult(
                Panel(f"Research export complete: {written}", title="Research Export", border_style="green")
            )
        return CommandResult(format_research_brief(brief))

    def _macro(self, args: list[str]) -> CommandResult:
        query = " ".join(args).strip()
        rows = self.macro_data.indicators(query)
        return CommandResult(_format_macro_dashboard(query or "global", rows))

    def _macro_indicator(self, indicator: str, args: list[str]) -> CommandResult:
        if indicator == "gdp" and args[:2] and " ".join(args[:2]).lower() == "per capita":
            indicator = "gdp_per_capita"
            args = args[2:]
        region = args[0] if args else "us"
        try:
            rows = self.macro_data.alpha_vantage_indicator(indicator, region)
        except FinCLIError as exc:
            rows = [_macro_error_row(indicator, region, exc)]
        return CommandResult(_format_macro_indicator(indicator, region, rows))

    def _technical(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /technical <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="6mo", interval=interval))
        if not candles:
            raise CommandError(f"No technical data for {symbol}.")
        summary = summarize_technical_indicators(candles)
        structure = analyze_market_structure(candles)
        debate = run_technical_debate(summary, structure, candles)
        signal = debate.judge_signal
        ai_summary = build_technical_ai_summary(symbol, interval, candles)
        return CommandResult(_format_technical(symbol, interval, summary, signal, ai_summary, debate))

    def _chart(self, args: list[str]) -> CommandResult:
        """Render ASCII candlestick chart with optional overlays."""
        from fincli.app.tui.chart import build_chart_output

        if not args:
            raise CommandError(
                "Format: /chart <symbol> [interval] [--overlay rsi,macd] [--width N] [--height N]\n"
                "Example: /chart AAPL 1d --overlay rsi,macd"
            )

        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 and not args[1].startswith("--") else "1d"

        # Parse options
        overlays_raw = _extract_option_value(args, "--overlay") or ""
        overlays = [o.strip() for o in overlays_raw.split(",") if o.strip()] if overlays_raw else []
        width = int(_extract_option_value(args, "--width") or "80")
        height = int(_extract_option_value(args, "--height") or "20")

        # Period mapping
        period_map = {
            "1d": "6mo",
            "1h": "1mo",
            "15m": "5d",
            "5m": "5d",
            "1wk": "2y",
            "1mo": "5y",
        }
        period = period_map.get(interval, "6mo")

        candles = self._run_async(self.market_service.history(symbol, period=period, interval=interval))
        if not candles:
            raise CommandError(f"Candle data is empty for {symbol} ({interval}).")

        panels = build_chart_output(candles, symbol, interval, overlays, width, height)
        return CommandResult(Group(*panels))

    def _mtf(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /mtf <symbol> [timeframes comma-separated]")
        symbol = args[0].upper()
        timeframes = _parse_timeframes(args[1] if len(args) >= 2 else "1d,1h,15m")
        analysis = self._run_async(analyze_multi_timeframe(symbol, self.market_service, timeframes=timeframes))
        return CommandResult(_format_multi_timeframe(analysis))

    def _backtest(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /backtest <symbol> [strategy] [interval] [--asset <class>] [--equity <amount>] "
                "[--sizing fixed_fractional|kelly] [--fraction <pct>] [--monte-carlo] [--walk-forward] [--export <md|json|csv> <path>]\n"
                "Compare: /backtest compare <symbol> <strategy1,strategy2,...> [interval]"
            )

        # Handle compare subcommand
        if args[0].lower() == "compare":
            return self._backtest_compare(args[1:])

        symbol = args[0].upper()
        strategy = args[1].lower() if len(args) >= 2 and not args[1].startswith("--") else "sma_cross"
        interval = args[2].lower() if len(args) >= 3 and not args[2].startswith("--") else "1d"

        # Parse options
        asset_class = _extract_option_value(args, "--asset") or "equity"
        initial_equity = float(_extract_option_value(args, "--equity") or "10000")
        position_method = _extract_option_value(args, "--sizing") or "fixed_fractional"
        position_fraction = float(_extract_option_value(args, "--fraction") or "0.02")
        include_mc = "--monte-carlo" in args or "--mc" in args
        walk_forward = "--walk-forward" in args or "--wf" in args
        export_format = None
        export_target = None
        if "--export" in args:
            export_index = args.index("--export")
            if len(args) > export_index + 2:
                export_format = args[export_index + 1]
                export_target = args[export_index + 2]

        # Parse custom strategy parameters (--param key=value)
        strategy_params = {}
        for arg in args:
            if arg.startswith("--") and "=" in arg[2:]:
                key, value = arg[2:].split("=", 1)
                try:
                    strategy_params[key] = float(value)
                except ValueError:
                    strategy_params[key] = value

        candles = self._run_async(self.market_service.history(symbol, period="2y", interval=interval))
        result = run_backtest(
            symbol,
            candles,
            strategy=strategy,
            interval=interval,
            asset_class=asset_class,
            initial_equity=initial_equity,
            position_method=position_method,
            position_fraction=position_fraction,
            include_monte_carlo=include_mc,
            walk_forward=walk_forward,
            strategy_params=strategy_params or None,
        )

        if export_format and export_target:
            from fincli.app.modules.exporter import export_backtest

            written = export_backtest(result, export_format, export_target)
            return CommandResult(
                Panel(f"Backtest export complete: {written}", title="Backtest Export", border_style="green")
            )

        return CommandResult(_format_backtest(result))

    def _backtest_compare(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError("Format: /backtest compare <symbol> <strategy1,strategy2,...> [interval]")

        symbol = args[0].upper()
        strategies = [s.strip().lower() for s in args[1].split(",") if s.strip()]
        interval = args[2].lower() if len(args) >= 3 and not args[2].startswith("--") else "1d"

        if len(strategies) < 2:
            raise CommandError("Provide at least 2 strategies to compare (comma-separated).")

        candles = self._run_async(self.market_service.history(symbol, period="2y", interval=interval))
        if not candles:
            raise CommandError(f"No candle data for {symbol}.")

        from fincli.app.analysis.backtest import run_backtest

        results: list[BacktestResult] = []
        for strategy in strategies:
            try:
                result = run_backtest(symbol, candles, strategy=strategy, interval=interval)
                results.append(result)
            except Exception:  # noqa: BLE001
                results.append(None)  # type: ignore

        return CommandResult(_format_backtest_compare(symbol, interval, strategies, results))

    def _market(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /market <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        overview = self._run_async(build_market_overview(symbol, self.market_service, interval))
        return CommandResult(_format_market_overview(overview))

    def _news(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /news <symbol> [1d-30d]")
        symbol = args[0].upper()
        lookback_days = _parse_news_lookback(args[1:]) if len(args) > 1 else None
        desk = self._run_async(
            NewsAggregator(
                self.market_service,
                self.news_connectors,
                self.config.settings.news_provider_priority,
            ).latest(symbol, limit=12, lookback_days=lookback_days)
        )
        return CommandResult(_format_news_desk(desk))

    def _yahoo(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /yahoo <symbol> [history|statistics|profile|financials|balance|cashflow|analysis|holders|news] [period] [interval]"
            )
        symbol = args[0].upper()
        section = args[1].lower() if len(args) >= 2 else "statistics"
        period = args[2] if len(args) >= 3 else "6mo"
        interval = args[3] if len(args) >= 4 else "1d"
        provider = YFinanceProvider()
        table = self._run_async(provider.yahoo_table(symbol, section, period=period, interval=interval))
        if not isinstance(table, YahooTable):
            raise CommandError("YFinance provider returned invalid table data.")
        return CommandResult(_format_yahoo_table(table))

    def _scan(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "export":
            return self._scan_export(args[1:])
        if not args:
            raise CommandError(
                "Format:\n"
                "  /scan watchlist [filter] [interval]\n"
                "  /scan <universe> [filter] [interval] [--limit N]\n\n"
                "Universes: sp500, nasdaq, crypto, forex, commodities\n"
                "Filters: rsi<30, rsi>70, trend=bullish, sma_cross, sma_death, above_support\n"
                "Example: /scan sp500 rsi<30 --limit 20"
            )

        source = args[0].lower()
        from fincli.app.modules.scanner import UNIVERSES, scan_universe

        # Parse --limit option
        limit = 50
        remaining_args = list(args[1:])
        for i, arg in enumerate(remaining_args):
            if arg == "--limit" and i + 1 < len(remaining_args):
                try:  # noqa: SIM105
                    limit = int(remaining_args[i + 1])
                except ValueError:
                    pass
                remaining_args = remaining_args[:i] + remaining_args[i + 2 :]
                break

        if source == "watchlist":
            rows = self.watchlist.list()
            symbols = [str(row["symbol"]) for row in rows]
            if not symbols:
                return CommandResult(Panel("Watchlist is empty. Use /watchlist add AAPL.", title="Scan"))
            filter_expression = remaining_args[0] if remaining_args else ""
            interval = remaining_args[1] if len(remaining_args) >= 2 else "1d"
            results, errors = self._run_async(
                scan_symbols(symbols, self.market_service, filter_expression, interval=interval)
            )
            return CommandResult(
                _format_scan_results(results, filter_expression or "all", interval, "watchlist", errors)
            )

        if source in UNIVERSES:
            filter_expression = remaining_args[0] if remaining_args else ""
            interval = remaining_args[1] if len(remaining_args) >= 2 else "1d"
            results, errors = self._run_async(
                scan_universe(source, self.market_service, filter_expression, interval, limit=limit)
            )
            return CommandResult(_format_scan_results(results, filter_expression or "all", interval, source, errors))

        raise CommandError(f"Unknown source: {source}. Use: watchlist, {', '.join(UNIVERSES.keys())}")

    def _scan_export(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError("Format: /scan export <csv|json> <path> [filter] [interval]")
        export_format = args[0].lower()
        target = args[1]
        filter_expression = args[2] if len(args) >= 3 else ""
        interval = args[3] if len(args) >= 4 else "1d"
        rows = self.watchlist.list()
        symbols = [str(row["symbol"]) for row in rows]
        if not symbols:
            raise CommandError("Watchlist is empty. Use /watchlist add AAPL.")
        results, _errors = self._run_async(
            scan_symbols(symbols, self.market_service, filter_expression, interval=interval)
        )
        written = export_rows(_scan_result_rows(results), export_format, target)
        return CommandResult(Panel(f"Scan export complete: {written}", title="Scan Export", border_style="green"))

    def _report(self, args: list[str]) -> CommandResult:
        if len(args) < 4 or args[0].lower() != "market":
            raise CommandError("Format: /report market <symbol> <md|json> <path> [interval]")
        symbol = args[1].upper()
        report_format = args[2].lower()
        target = args[3]
        interval = args[4] if len(args) >= 5 else "1d"
        overview = self._run_async(build_market_overview(symbol, self.market_service, interval))
        written = write_market_report(overview, report_format, target)
        return CommandResult(Panel(f"Market report complete: {written}", title="Market Report", border_style="green"))

    def _calendar(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "export":
            return self._calendar_export(args[1:])
        start, end, country, impact = _parse_calendar_args(args)
        secrets = read_secrets()
        service = EconomicCalendarService(api_key=secrets.get("FINNHUB_API_KEY"))
        source = "finnhub"
        note = "Actual data from Finnhub provider."
        try:
            events = self._run_async(service.events(start, end))
        except FinCLIError as exc:
            events, source, note = self._calendar_public_or_static_fallback(start, end, exc)
        events = filter_events(events, country=country, impact=impact)
        return CommandResult(_format_calendar(events, start, end, source, note))

    def _calendar_export(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError(
                "Format: /calendar export <csv|json> <path> [today|week|from to] [country=US] [impact=high]"
            )
        export_format = args[0].lower()
        target = args[1]
        start, end, country, impact = _parse_calendar_args(args[2:])
        secrets = read_secrets()
        service = EconomicCalendarService(api_key=secrets.get("FINNHUB_API_KEY"))
        try:
            events = self._run_async(service.events(start, end))
        except FinCLIError as exc:
            events, _, _ = self._calendar_public_or_static_fallback(start, end, exc)
        events = filter_events(events, country=country, impact=impact)
        written = export_rows(economic_event_rows(events), export_format, target)
        return CommandResult(
            Panel(f"Calendar export complete: {written}", title="Calendar Export", border_style="green")
        )

    def _calendar_public_or_static_fallback(
        self, start: date, end: date, provider_error: FinCLIError
    ) -> tuple[list[EconomicEvent], str, str]:
        secrets = read_secrets()
        if not secrets.get("FINNHUB_API_KEY"):
            return fallback_events(start, end), "fallback", _calendar_fallback_note(provider_error, False)
        try:
            events = self._run_async(PublicEconomicCalendarService().events(start, end))
            if events:
                return (
                    events,
                    "public",
                    (
                        "Finnhub calendar unavailable for the current key, plan, or rate limit. "
                        "Using public economic calendar fallback; verify critical events with official sources."
                    ),
                )
        except FinCLIError as public_error:
            note = _calendar_static_fallback_note(provider_error, public_error)
            return fallback_events(start, end), "fallback", note
        return fallback_events(start, end), "fallback", _calendar_static_fallback_note(provider_error, None)

    def _get_quote(self, symbol: str) -> Quote:
        normalized = symbol.upper()
        cache_key = f"quote:{normalized}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, Quote):
            return cached
        quote = self._run_async(self.market_service.quote(normalized))
        if not isinstance(quote, Quote):
            raise CommandError("Provider quote returned invalid data.")
        self.cache.set(cache_key, quote)
        return quote

    def _safe_quote(self, symbol: str) -> Quote | None:
        try:
            return self._get_quote(symbol)
        except FinCLIError:
            return None

    def _export(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /export <journal|portfolio|alerts|all> <csv|json> <path>")
        dataset = args[0].lower()

        if dataset == "all":
            if len(args) < 3:
                raise CommandError("Format: /export all <csv|json> <directory>")
            export_format = args[1].lower()
            target = args[2]
            from fincli.app.modules.exporter import export_all

            written = export_all(
                target,
                portfolio=self.portfolio.list(),
                journal=self.journal.list(limit=10_000),
                alerts=[dict(h.__dict__) if hasattr(h, "__dict__") else h for h in self.alerts.get_history()],
                trades=self.paper_trading.list_orders(limit=10_000),
                fmt=export_format,
            )
            return CommandResult(
                Panel(
                    f"Batch export complete: {len(written)} file(s) at {target}", title="Export", border_style="green"
                )
            )

        if dataset == "broker":
            if len(args) < 3:
                raise CommandError("Format: /export broker <csv|json> <path>")
            export_format = args[1].lower()
            target = args[2]
            # Get broker orders from live trading
            orders = self._run_async(self.live_trading.list_orders(limit=10_000))
            rows = [
                {
                    "broker_order_id": o.broker_order_id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "order_type": o.order_type,
                    "quantity": o.quantity,
                    "price": o.price,
                    "status": o.status,
                    "filled_quantity": o.filled_quantity,
                    "filled_price": o.filled_price,
                    "broker": o.broker,
                    "created_at": o.created_at.isoformat(),
                }
                for o in orders
            ]
            written = export_rows(rows, export_format, target)
            return CommandResult(
                Panel(f"Export broker orders complete: {written}", title="Export", border_style="green")
            )

        if len(args) < 3:
            raise CommandError("Format: /export <journal|portfolio|alerts> <csv|json> <path>")
        export_format = args[1].lower()
        target = args[2]
        if dataset == "journal":
            rows = self.journal.list(limit=10_000)
        elif dataset == "portfolio":
            rows = self.portfolio.list()
        elif dataset == "alerts":
            rows = [dict(h.__dict__) if hasattr(h, "__dict__") else h for h in self.alerts.get_history()]
        else:
            raise CommandError("Format: /export <journal|portfolio|alerts|all> <csv|json> <path>")
        written = export_rows(rows, export_format, target)
        return CommandResult(Panel(f"Export {dataset} complete: {written}", title="Export", border_style="green"))
