# Changelog

## v1.0.0 — Non-MVP Release (2026-06-18)

### Production Hardening
- GitHub Actions CI workflow with Python 3.11/3.12/3.13 × ubuntu/windows/macos matrix.
- Cross-platform install validation workflow.
- Structured error reporting with secret redaction (no API keys in logs/TUI).
- Full command smoke test suite covering all 103 registered commands.
- Release checklist automation script (`scripts/release_check.py`).
- TUI polish with consistent spacing, borders, and colors.
- Provider response standardization across all 5 market adapters.
- Interactive setup wizard for first-run API key configuration.
- Documentation hardening with `docs/` directory (commands, setup, troubleshooting, architecture).
- Security hardening with `--audit-secrets` flag and strengthened prepublish checks.
- Data quality visibility standardization across all data-producing commands.
- Critical path integration tests for provider fallback, circuit breaker, cache, secrets, DB migrations.

### Stats
- 456 tests passing
- 103 source files
- 80+ documented commands
- CI/CD on 9 platform combinations

---

## v0.9.0 — Production Hardening (2026-06-18)

- CI/CD workflows for testing and install validation.
- Structured error handling with sanitized stack traces.
- Full command smoke tests.
- Provider error handling standardization.
- Documentation hardening.
- Version bumped to 0.9.0.

---

## v0.8.0 — Portfolio & Backtesting (2026-06-18)

### Backtesting Engine (complete rewrite)
- Fees/slippage/spread modeling per asset class (equity, forex, crypto, commodity, index, ETF).
- Walk-forward split (70/30 in-sample/out-of-sample with overfit ratio).
- Position sizing: fixed fractional + Kelly criterion.
- 5 strategies: sma_cross, rsi_reversion, momentum, bollinger_breakout, multi_factor.
- Risk-adjusted ratios: Sharpe, Sortino, Calmar (annualized).
- Trade statistics: profit factor, expectancy, avg/largest win/loss, consecutive streaks.
- Monte Carlo robustness testing (5th/50th/95th percentile outcomes).
- Export: `/backtest --export md|json|csv`.

### Portfolio Analytics
- Time-series snapshots (`portfolio_snapshots` table).
- Risk ratios: Sharpe/Sortino/Calmar from daily returns.
- Rebalancing suggestions with concentration cap.
- Benchmark comparison (alpha, beta, correlation vs any symbol).
- What-if analysis: `/portfolio whatif add|sell <symbol> <qty> <price>`.

### Alert Daemon
- Background alert checking with configurable interval.
- Conditional alerts: rsi_below, rsi_above, volume_above, macd_cross_up, macd_cross_down.
- Alert history with immutable log.
- `/alert daemon start|stop|status`.

### Unified Export
- Batch export: `/export all json ./dir`.
- Backtest export with full metrics.
- Alert history export.

---

## v0.7.0 — Trading Safety Layer (2026-06-18)

### Risk Guard
- Max position size (20% equity default).
- Daily loss limit (5% equity default).
- Kill switch: `/trading kill` / `/trading resume`.
- Leverage warning (blocks orders exceeding equity).
- Order validation (side, type, quantity, price).

### Paper Trading Engine (enhanced)
- Cancel orders: `/trading cancel <id>`.
- Positions aggregation: `/trading positions`.
- Daily PnL tracking.
- Stop-limit orders.
- Immutable audit log for all order attempts.

### Broker Adapters
- AlpacaPaperAdapter: full HTTP against paper-api.alpaca.markets.
- TradierSandboxAdapter: full HTTP against sandbox.tradier.com.
- IBKRPaperAdapter: scaffold with setup instructions.
- BrokerAdapterRegistry for activation management.

### Realtime Streaming
- KrakenWebSocketAdapter: wss://ws.kraken.com for crypto.
- HyperLiquidWebSocketAdapter: wss://api.hyperliquid.xyz/ws for crypto/perps.
- EquityStreamingAdapter: polling-based using market providers.
- StreamManager for connection management.

### Algo Trading
- StrategyEngine with 3 built-in strategies: sma_cross, rsi_reversion, momentum.
- Auto-places paper orders when signal fires.
- Strategy audit logging.

---

## v0.6.0 — Research Engine v3 (2026-06-18)

### Research Engine v3
- Snapshot/deep/report modes with `--snapshot` as default.
- Cited sources (market, news, macro, fundamentals, web).
- Sector/macro/news context blending.
- Web research fallback when provider news unavailable.
- Stronger AI grounding guard tied to Data Trust Gate.

### Provider/Data Reliability
- New granular statuses: `delayed`, `fallback`.
- Source quality scoring (freshness score, source grade A–E).
- Command capability matrix via `/provider capabilities`.

---

## v0.5.0 — Provider/Data Reliability (2026-06-18)

- Standard `ProviderResult` envelope with granular statuses.
- Provider metrics dashboard with runtime stats.
- Persistent provider metrics in SQLite.
- AI Grounding Guard for `/analyze`.
- Source quality and freshness scoring.

---

## v0.4.0 — Feature Complete (2026-06-18)

### Trading Layer
- Broker catalog with 16 integrations.
- Realtime connector catalog (Kraken WS, HyperLiquid WS, Equity Feed).
- Local paper trading engine.

### Portfolio Risk v3
- Exposure by asset class and currency.
- Concentration risk analysis.
- Drawdown estimate.
- Risk budget from user profile.
- Health score.

### Research Engine v2
- Compact research briefs.
- Deep mode with AI.
- Report mode with export (md/json).

### Core Features
- Textual/Rich TUI with slash commands.
- Provider fallback chain with circuit breaker.
- Market data: yfinance, Finnhub, TwelveData, AlphaVantage.
- News aggregation with 100+ connector catalog.
- Technical analysis: RSI, MACD, EMA/SMA, Bollinger, ATR.
- Portfolio tracking with PnL.
- Journal with AI review.
- Watchlist with scanner.
- Alerts.
- Economic calendar.
- Session history.
- Macro data (AlphaVantage).

---

## v0.3.x — Hardening

- Provider runtime metrics.
- Persistent provider metrics.
- AI Grounding Guard.
- Portfolio Risk v3 (drawdown, currency grouping).
- Research report export.
- Provider-specific schema validation.

---

## v0.2.x — Early Features

- Market provider manager.
- yfinance fallback.
- Finnhub integration.
- News aggregation.
- Technical analysis.
- Portfolio and journal.

---

## v0.1.0 — Initial Release

- Basic TUI with slash commands.
- Market data from yfinance.
- Simple portfolio tracking.
