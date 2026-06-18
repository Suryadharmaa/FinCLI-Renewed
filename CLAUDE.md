# CLAUDE.md

## FinCLI Project Handoff

FinCLI is a Python-based modern financial CLI/TUI terminal with an npm wrapper. It is designed as a professional research workspace for market data, news, technical analysis, AI-assisted analysis, portfolio tracking, journaling, watchlists, provider diagnostics, macro data, and local paper trading.

Current target version: `1.0.0`.

Current maturity: Production-ready non-MVP release. FinCLI has reached `1.0.0` with reliable data quality, stable commands, safe provider handling, tested workflows, and production-grade installation.

## Core Identity

FinCLI should feel like a focused financial terminal, not a generic chatbot or command demo.

Main principles:

- Slash commands start with `/`.
- Do not tell users to run `fincli --help` inside the TUI when they ask about commands.
- Prefer fewer, stronger command centers over command bloat.
- `/research` is the main research hub.
- `/provider` is the provider diagnostics and key/status hub.
- `/trading` is the trading and paper-trading hub.
- `/macro` is the macro hub, with some hidden direct aliases.
- AI output must be grounded in available data quality, provider reliability, missing data, and risk context.
- Never claim data is realtime unless the provider capability says it is realtime.
- Never expose API keys, secrets, local database contents, or user tokens.

## Current Architecture

Important paths:

- `fincli/app/main.py`  
  Entry point for the TUI app.

- `fincli/app/tui/layout.py`  
  Main Textual layout, input, output stream, autocomplete behavior, and command execution flow.

- `fincli/app/tui/theme.py`  
  Terminal theme and color rules.

- `fincli/app/cli/router.py`  
  Main slash command router.

- `fincli/app/cli/commands.py`  
  Command registry used by help/autocomplete.

- `fincli/app/providers/ai/`  
  AI provider adapters.

- `fincli/app/providers/market/`  
  Market provider adapters, symbol resolver, Finnhub, yfinance, custom providers.

- `fincli/app/providers/reliability.py`  
  Provider reliability status model.

- `fincli/app/services/market_data.py`  
  Market provider manager, fallback flow, timeout handling, circuit breaker, provider metrics.

- `fincli/app/services/data_quality.py`  
  Standardized data quality reporting.

- `fincli/app/services/data_trust.py`  
  Trust gate for AI/research conclusions.

- `fincli/app/services/macro_data.py`  
  AlphaVantage macro data service and hidden macro aliases.

- `fincli/app/services/news_aggregator.py`  
  News aggregation and fallback.

- `fincli/app/services/web_research.py`  
  Free web research/search fallback service.

- `fincli/app/modules/portfolio.py`  
  Portfolio model and PnL/allocation logic.

- `fincli/app/modules/transactions.py`  
  Transaction storage and realized/unrealized reporting.

- `fincli/app/modules/trading.py`  
  Realtime connector catalog, broker catalog, and local paper trading engine.

- `fincli/app/modules/journal.py`  
  Trading/investment journal.

- `fincli/app/modules/watchlist.py`  
  Watchlist storage and display.

- `fincli/app/modules/economic_calendar.py`  
  Economic calendar provider flow.

- `fincli/app/research/`  
  Research Engine modules.

- `scripts/prepublish_check.py`  
  Release safety check for secrets and packaging.

- `tests/`  
  Regression tests. Add focused tests for every non-trivial behavior change.

## Current Feature Scope

Implemented or scaffolded:

- Modern Textual CLI/TUI.
- Slash command routing and autocomplete.
- AI provider manager.
- Market provider manager.
- yfinance fallback.
- Finnhub integration.
- TwelveData and AlphaVantage key support.
- Custom market provider configuration.
- Provider reliability statuses and metrics.
- Data quality and data trust checks.
- Symbol normalization for common global symbols.
- News aggregation.
- Economic calendar.
- AlphaVantage macro aliases:
  - `/cpi us`
  - `/nfp us`
  - `/gdp us`
  - `/gdp per capita us`
  - `/fed funds us`
  - `/inflation us`
  - `/unemployment us`
- Research center through `/research`.
- Technical analysis and AI analysis.
- Multi-timeframe analysis.
- Portfolio, journal, watchlist.
- Alerts.
- Local paper trading.
- Broker catalog for Zerodha, Angel One, Upstox, Fyers, Dhan, Groww, Kotak, IIFL, 5paisa, AliceBlue, Shoonya, Motilal, IBKR, Alpaca, Tradier, and Saxo.
- Realtime connector catalog for Kraken and HyperLiquid WebSocket.
- Finnhub insider transactions and IPO calendar commands.

Important limitation: live broker execution is not enabled. Current trading support is catalog + local paper trading only.

## Command Philosophy

Avoid adding too many top-level commands. Prefer subcommands:

- Good:
  - `/research AAPL --deep`
  - `/provider status`
  - `/provider insider AAPL`
  - `/provider ipo week`
  - `/trading brokers`
  - `/trading paper buy AAPL 1 market 100`

- Avoid:
  - Adding a new top-level command for every small data endpoint.

Hidden utility aliases are acceptable when useful, but they should not clutter `/help`.

## Security Rules

Never commit:

- `.env`
- `secrets.env`
- `~/.fincli`
- SQLite databases
- logs
- `.tgz` package files
- `.npm-python`
- `.pytest_cache`
- `fincli.egg-info`
- `__pycache__`
- API keys or tokens in tests/docs/screenshots

API keys should be stored through FinCLI commands into local user storage, usually `~/.fincli/secrets.env`, and never printed directly. Display only masked values such as `abcd...wxyz`.

Before release, run:

```powershell
python scripts\prepublish_check.py
git status --short --ignored
```

If any secret-like file appears, remove it before publishing.

## Development Rules For Claude

When changing this project:

1. Read `README.md`, `pyproject.toml`, `package.json`, `fincli/app/cli/router.py`, and `fincli/app/cli/commands.py` first.
2. Audit existing structure before adding files.
3. Do not rewrite the whole app unless explicitly requested.
4. Preserve existing command behavior unless the change is intentional.
5. Add tests for new command behavior and provider fallbacks.
6. Use provider abstractions instead of direct API calls in command handlers.
7. Keep provider calls timeout-bound.
8. Use fallback and circuit breaker behavior for unstable providers.
9. Never make AI output aggressive buy/sell claims without data quality support.
10. If data is missing, say what is missing.
11. Do not expose raw tracebacks to users in the TUI.
12. Keep UI output compact, readable, and financial-terminal oriented.

## Local Development Commands

Install editable:

```powershell
python -m pip install -e .
```

Run TUI:

```powershell
fincli
```

Run tests:

```powershell
pytest -q
```

Compile check:

```powershell
python -m compileall fincli -q
```

NPM/package checks:

```powershell
npm run check
npm pack --dry-run
npm install -g .
```

Prepublish scan:

```powershell
python scripts\prepublish_check.py
```

Publish scoped package:

```powershell
npm publish --access=public
npm view @drico2008/fincli version --registry=https://registry.npmjs.org/
```

## Known Limitations In v0.4.0

- Trading is local paper trading only.
- Broker integrations are catalog/scaffold level, not live execution adapters.
- Web research depends on free sources and can be rate-limited or blocked.
- Finnhub economic calendar, IPO, and insider data depend on API plan entitlement.
- AlphaVantage free tier is rate-limited.
- Some connector lists are catalogs/plans, not full production adapters.
- Data quality differs by asset class and provider.
- The TUI is functional but still needs full design hardening before `1.0.0`.

## Roadmap To FinCLI 1.0.0 Non-MVP

### Phase 0.4.x - Stabilization

Focus:

- Fix critical bugs from real usage.
- Stabilize npm installation on Windows, macOS, and Linux.
- Keep prepublish checks strict.
- Improve README and command docs.
- Ensure no secret/history/cache files ship.

Exit criteria:

- All tests pass.
- `npm install -g @drico2008/fincli` works on a clean machine.
- No raw traceback from normal command errors.
- No secret files in package.

### Phase 0.5.0 - Provider/Data Reliability

Focus:

- Standardize all provider responses through one `ProviderResult` contract.
- Add granular status handling:
  - `ok`
  - `auth_failed`
  - `rate_limited`
  - `entitlement_missing`
  - `partial_data`
  - `delayed`
  - `fallback`
  - `circuit_open`
  - `unavailable`
- Add provider capability matrix per command.
- Improve symbol search and normalization UI.
- Persist provider metrics across sessions.
- Add source quality and freshness scoring.

Exit criteria:

- `/provider status`, `/market`, `/news`, `/calendar`, `/research`, and `/analyze` all show consistent data quality.
- Provider failures degrade gracefully.

### Phase 0.6.0 - Research Engine v3

Focus:

- Make `/research` the professional research center.
- Add compact modes:
  - snapshot
  - deep
  - report
  - export md/json
- Improve cited source summaries.
- Add stronger AI grounding guard.
- Improve web research fallback.
- Add sector/macro/news context blending.

Exit criteria:

- `/research AAPL --deep` produces concise, source-aware, useful output.
- `/research AAPL --report --export md report.md` is reliable.

### Phase 0.7.0 - Trading Safety Layer (done)

Focus:

- Keep live trading disabled by default.
- Add broker sandbox adapters first:
  - Alpaca paper (full HTTP)
  - Tradier sandbox (full HTTP)
  - IBKR paper (gateway scaffold)
- Add order validation.
- Add risk guard:
  - max position size
  - daily loss limit
  - kill switch
  - leverage warning
  - asset class restrictions
- Add immutable local order audit log.
- Add algo trading engine with 3 built-in strategies.
- Add realtime streaming adapters (Kraken WS, HyperLiquid WS, Equity polling).

Exit criteria:

- Paper trading behaves like a real broker simulator.
- No accidental live order path exists without explicit opt-in.

### Phase 0.8.0 - Portfolio And Backtesting (done)

Focus:

- Portfolio risk v3:
  - asset-class exposure
  - currency exposure
  - concentration risk
  - drawdown estimate
  - risk budget from user profile
  - Sharpe/Sortino/Calmar ratios
  - time-series snapshots
  - rebalancing suggestions
  - benchmark comparison
  - what-if analysis
- Backtesting engine:
  - fees/slippage/spread modeling
  - walk-forward split
  - position sizing (fixed fractional + Kelly)
  - 5 strategies (sma_cross, rsi_reversion, momentum, bollinger, multi_factor)
  - Sharpe/Sortino/Calmar ratios
  - Monte Carlo robustness
  - exportable reports (md/json/csv)
- Alert daemon:
  - background checking
  - conditional alerts (RSI, volume, MACD cross)
  - alert history
- Unified export system.

Exit criteria:

- Portfolio and backtesting outputs are decision-grade, not cosmetic.

### Phase 0.9.0 - Production Hardening

Focus:

- CI workflow.
- Cross-platform install validation.
- Crash/error reporting that does not leak secrets.
- Full command smoke tests.
- Release checklist automation.
- Documentation hardening.

Exit criteria:

- Clean release process with repeatable checks.

### Phase 1.0.0 - Non-MVP Release

FinCLI reaches `1.0.0` when:

- Commands are stable and documented.
- Core TUI is polished and predictable.
- Provider fallback is reliable.
- Data quality is visible to the user.
- Research, analysis, portfolio, journal, watchlist, and paper trading are usable end to end.
- NPM and pip installation are reliable.
- Security checks prevent accidental secret publication.
- Tests cover critical provider, command, storage, and release flows.
- No known critical bug remains in normal usage.

## Recommended Next Improvements

Highest priority:

1. Finish provider response standardization across all adapters.
2. Add cross-platform install CI.
3. Add full command smoke test for every visible `/help` command.
4. Add persistent provider metrics dashboard.
5. Harden `/research` output quality and exports.
6. Make TUI spacing and output rendering consistent.
7. Add setup wizard for first-run API keys and user profile.
8. Improve fallback behavior for `/calendar`, `/news`, and `/web`.
9. Add paper trading risk guard and audit log.
10. Prepare 1.0 command contract and freeze breaking changes.

