# FinCLI v1.0.0

FinCLI is a production-ready financial CLI/TUI terminal for market research, technical analysis, AI-assisted analysis, provider management, portfolio risk, journaling, watchlists, backtesting, paper trading, and local-first financial workflows.

Data quality depends on provider availability, API keys, provider plan entitlement, exchange coverage, and rate limits. yfinance remains the default delayed fallback.

## Highlights

- Textual + Rich terminal UI with slash commands.
- Research-first workflow through `/research`, now powered by Research Engine v3 (snapshot/deep/report, cited sources, sector/macro/news blending, web fallback).
- Provider fallback chain with granular reliability labels: `ok`, `auth_failed`, `rate_limited`, `entitlement_missing`, `partial_data`, `delayed`, `fallback`, `schedule_only`, `unavailable`, `circuit_open`.
- Source quality and freshness scoring (`freshness_score`, source grade A–E) surfaced in `/research` and `/market`.
- Command capability matrix exposed via `/provider capabilities`, showing which data each command needs.
- Provider metrics dashboard with runtime success rate, average latency, fallback count, and error count.
- Persistent provider metrics in SQLite so `/provider metrics` can show current session and all-time call totals.
- AI Grounding Guard for `/analyze` and `/research`: AI prompts must consider data quality, provider reliability, missing data, cited sources, and provider metrics before conclusions.
- Market data adapters: yfinance, Finnhub, Twelve Data, Alpha Vantage, and custom provider schema.
- 100+ news connector catalog with free RSS fallbacks and API-key-ready providers.
- AI providers: OpenRouter, OpenAI, Groq, Together, HuggingFace, Gemini, Anthropic, and compatible HTTP providers.
- Technical analysis: RSI, MACD, EMA/SMA, Bollinger Bands, ATR, support/resistance, market structure, and technical debate.
- Portfolio Risk v3: exposure by asset class/currency, concentration risk, drawdown estimate, risk budget, realized/unrealized PnL, and portfolio health score.
- Trading Safety Layer: risk guard (max position size, daily loss limit, kill switch, leverage warning), immutable audit log, paper trading with stop-limit orders, 3 built-in algo strategies (sma_cross, rsi_reversion, momentum).
- Broker sandbox adapters: Alpaca paper (full HTTP), Tradier sandbox (full HTTP), IBKR (gateway scaffold). 16 broker catalog entries.
- Realtime streaming: Kraken WebSocket, HyperLiquid WebSocket, Equity polling feed — all configurable adapters with `websockets` library.
- Professional backtesting: fees/slippage/spread modeling, walk-forward split, position sizing (fixed fractional + Kelly), 5 strategies (sma_cross, rsi_reversion, momentum, bollinger, multi_factor), Sharpe/Sortino/Calmar ratios, Monte Carlo robustness, export (md/json/csv).
- Portfolio analytics: time-series snapshots, Sharpe/Sortino/Calmar ratios, rebalancing suggestions, benchmark comparison (vs SPY/QQQ/BTC), what-if analysis.
- Alert daemon: background checking, conditional alerts (RSI, volume, MACD cross), alert history, notification hooks.
- Unified export: batch export all data (portfolio, journal, alerts, trades) to CSV/JSON.
- Local-first storage: config, secrets, SQLite database, cache, sessions, watchlist, portfolio, journal, alerts, audit log, portfolio snapshots.
- Prepublish safety checks for secrets, runtime artifacts, and npm package manifest.

## Install

Local development:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
fincli
```

Global npm wrapper:

```bash
npm install -g @drico2008/fincli
fincli
```

The npm wrapper requires Python 3.11+ on the user machine. It creates an isolated `.npm-python` environment inside the installed package.

## API Key Setup

Global users do not need to edit `.env`. Save keys from inside FinCLI:

```text
/ai_model key groq <api_key>
/ai_model key openrouter <api_key>
/news_model key finnhub <api_key>
/news_model key twelvedata <api_key>
/news_model key alphavantage <api_key>
```

Keys are stored locally in:

```text
~/.fincli/secrets.env
```

FinCLI masks keys in terminal output. Use `/secrets status`, `/secrets clear`, `/privacy status`, and `/privacy purge` for local security hygiene.

## Core Commands

Research and market:

```text
/research AAPL
/research AAPL --snapshot
/research AAPL --deep
/research AAPL --report
/research AAPL --report --export md report.md
/research AAPL --report --export json report.json
/market AAPL 1d
/news AAPL 7d
/technical AAPL 1d
/analyze AAPL 1d
/mtf AAPL 1d,1h,15m
/calendar week US high
```

Providers:

```text
/news_model
/news_model list
/news_model priority google_news_rss,yfinance,yahoo_finance_rss
/provider status
/provider metrics
/provider list
/provider capabilities
/provider entitlement
/provider key status
/provider test AAPL
```

Portfolio and risk:

```text
/portfolio
/portfolio add AAPL 10 185
/portfolio performance
/portfolio risk
/tx add buy AAPL 10 185
/tx add sell AAPL 5 195
```

Workflow:

```text
/watchlist add AAPL
/scan watchlist rsi<30
/journal add AAPL bullish "Breakout failed, wait for confirmation"
/journal stats
/journal review
/alert add AAPL above 200
/history
/cache stats
/cache clear
```

Security and release:

```text
/secrets status
/privacy status
npm run prepublish:safety
python scripts/prepublish_check.py
```

## Research Engine v3

`/research` is the central research command. It returns a compact, source-aware output:

- Snapshot
- Signal
- Risk
- Context (sector + macro + news blend)
- Trust Gate
- Missing Data
- Source Quality (with freshness score and source grade)
- Decision Points
- Sources (cited market, news, macro, fundamentals, and web entries)
- Final Summary

Modes:

- `--snapshot` (default): compact brief from available provider data.
- `--deep`: sends a grounded Research Engine v3 prompt to the active AI provider, obeying the Data Trust Gate confidence cap.
- `--report`: adds report-oriented notes and macro/source sections without creating another command surface.

When provider news is missing, deep/report modes can fall back to public web research for current context. Exports (`--export md|json`) include the cited sources, macro context, and context blend.

## Portfolio Risk v3

`/portfolio risk` calculates:

- Exposure by asset class
- Currency exposure
- Concentration risk
- Drawdown estimate
- Asset-class cap warning
- Risk budget from `/profile`
- Realized PnL
- Unrealized PnL
- Total PnL
- Portfolio health score

The health score is a local analytical score, not financial advice. It penalizes high concentration, missing prices, weak diversification, and drawdown.

## Data Notes

- yfinance is a delayed fallback and should not be described as realtime.
- Finnhub, Twelve Data, Alpha Vantage, and other providers may require API keys, paid plans, and exchange entitlements.
- Public RSS/news sources can change or fail without notice.
- Calendar fallback may be `schedule_only` if actual provider data is unavailable.
- AI output is informational and must not be treated as guaranteed signal or financial advice.

## Local Storage

FinCLI stores local data under:

```text
~/.fincli/config.json
~/.fincli/secrets.env
~/.fincli/fincli.db
~/.fincli/fincli.log
```

Do not commit `.env`, local secrets, logs, databases, cache folders, or npm/python virtual environments.

## Prepublish Safety

Before publishing to npm or GitHub:

```bash
python -m pytest -q
python -m compileall fincli tests scripts
npm run check
npm run prepublish:safety
```

The prepublish checker scans for `.env`, `secrets.env`, logs, SQLite databases, token-like strings, and unsafe `npm pack --dry-run` contents.

## Roadmap

### v0.3.x Hardening

- Provider runtime metrics by provider started in `/provider metrics`.
- Persistent provider metrics started in v0.3.0.
- AI Grounding Guard started in `/analyze`.
- Richer portfolio analytics: drawdown estimate and currency grouping started in Portfolio Risk v3.
- Better research reports with Markdown/JSON export from `/research --report` started in v0.3.0.
- Provider-specific schema validation for custom data APIs.
- Improved AI grounding and citations for web/news-assisted answers.

### v0.5.0 Provider/Data Reliability (done)

- Standard `ProviderResult` envelope with granular statuses, including `delayed` and `fallback`.
- Command capability matrix exposed via `/provider capabilities`.
- Source quality and freshness scoring across `/research` and `/market`.
- Persistent provider metrics across sessions.

### v0.6.0 Research Engine v3 (done)

- Snapshot/deep/report modes with Markdown/JSON export.
- Cited source summaries (market, news, macro, fundamentals, web).
- Sector/macro/news context blending in every brief.
- Stronger AI grounding guard tied to the Data Trust Gate.
- Public web research fallback when provider news is unavailable.

### v0.7.0 Trading Safety Layer (done)

- Risk guard with max position size, daily loss limit, kill switch, leverage warning, asset class restrictions.
- Immutable order audit log (never UPDATE/DELETE).
- Paper trading engine with stop-limit orders, cancel, positions aggregation, daily PnL.
- Broker sandbox adapters: Alpaca paper (full HTTP), Tradier sandbox (full HTTP), IBKR (gateway scaffold).
- 16 broker catalog entries with correct API endpoints and modes.
- Realtime streaming: Kraken WebSocket, HyperLiquid WebSocket, Equity polling feed.
- Algo trading engine with 3 built-in strategies: sma_cross, rsi_reversion, momentum.
- New commands: /trading kill, resume, risk, audit, cancel, positions, broker use/status, stream, algo list/run.

### v0.8.0 Portfolio & Backtesting (done)

- Professional backtesting: fees/slippage/spread, walk-forward split, position sizing (fixed fractional + Kelly), 5 strategies, Sharpe/Sortino/Calmar, Monte Carlo robustness.
- Portfolio time-series snapshots with risk ratios (Sharpe/Sortino/Calmar).
- Rebalancing suggestions and benchmark comparison (vs SPY, QQQ, BTC, etc.).
- What-if analysis for portfolio changes.
- Alert daemon with conditional alerts (RSI, volume, MACD cross), alert history.
- Unified export: batch export all data to CSV/JSON.
- New commands: /backtest --export --monte-carlo --walk-forward, /portfolio chart/snapshot/whatif/benchmark, /alert daemon/history, /export all.

### v0.9.0 Production Hardening (done)

- GitHub Actions CI workflow (Python 3.11/3.12/3.13 × ubuntu/windows/macos).
- Cross-platform install validation workflow.
- Structured error reporting with secret redaction.
- Full command smoke test suite (103 commands tested).
- Release checklist automation script.
- TUI polish with consistent spacing and rendering.
- Provider response standardization across all adapters.
- Setup wizard for first-run configuration.
- Documentation hardening (docs/ directory with guides).
- Security hardening with audit-secrets flag.
- Data quality visibility standardization.
- Critical path integration tests.

### v1.0.0 — Non-MVP Release

FinCLI v1.0.0 is the stable production release:

- ✅ Commands are stable and documented.
- ✅ Core TUI is polished and predictable.
- ✅ Provider fallback is reliable with granular status labels.
- ✅ Data quality is visible to the user.
- ✅ Research, analysis, portfolio, journal, watchlist, and paper trading are usable end to end.
- ✅ NPM and pip installation are reliable.
- ✅ Security checks prevent accidental secret publication.
- ✅ Tests cover critical provider, command, storage, and release flows (456 tests).
- ✅ CI/CD pipeline validates on every push/PR.
- ✅ No known critical bug remains in normal usage.

## License

MIT