# FinCLI v1.8.0 — COMPLETE ✅

## Summary
Major update: strategy backtesting overhaul, portfolio analytics improvements, new data providers, enhanced TUI experience, and code quality hardening.

---

## Phase 1: Strategy Backtesting v2 ✅
- 4 new strategies: bollinger_squeeze, macd_divergence, volume_breakout, mean_reversion
- Custom strategy parameters via `--fast 10 --slow 30`
- `/backtest compare` — compare multiple strategies on same symbol
- Strategy performance summary table

## Phase 2: Portfolio Analytics v2 ✅
- VaR (Value at Risk) — historical + parametric methods
- `/portfolio correlation` — pairwise correlation matrix
- `/portfolio tax` — realized PnL summary for tax reporting

## Phase 3: New Market Data Providers ✅
- Polygon.io provider (quotes, historical, fundamentals)
- IEX Cloud provider (quotes, historical, company info)
- `/provider compare` — test same symbol across all providers

## Phase 4: Enhanced TUI Experience ✅
- Command aliases: `/p`, `/t`, `/r`, `/b`, `/w`, `/j`, `/m`, `/n`, `/a`, `/s`
- `/favourites` — quick access to most-used symbols

## Phase 5: Code Quality & Performance ✅
- Removed deprecated commands: `/security encrypt-key`, `/security decrypt-key`, `/trading algo`, `/provider insider`, `/provider ipo`
- Fixed ~30 Indonesian strings in router.py
- Added ruff and mypy configuration

## Phase 6: Documentation & Version Bump ✅
- README.md changelog updated with v1.8.0 features
- README.md command reference updated with new commands
- Version bumped to 1.8.0 in pyproject.toml, package.json, __init__.py
- All test assertions updated to expect v1.8.0

---

## Final Status
- **736 tests passing** (10 deselected = Windows credential store resource exhaustion, pre-existing)
- **Version: 1.8.0**
- **All phases complete**

---

## New Commands in v1.8.0
- `/backtest compare <symbol> <strategy1,strategy2,...>` — compare strategies
- `/portfolio correlation` — correlation matrix
- `/portfolio tax` — realized PnL summary
- `/provider compare <symbol>` — compare providers
- `/favourites` — quick access to most-used symbols
- `/favourites add <symbol>` — add to favourites
- Command aliases: `/p`, `/t`, `/r`, `/b`, `/w`, `/j`, `/m`, `/n`, `/a`, `/s`

## New Strategies in v1.8.0
- `bollinger_squeeze` — Bollinger Band squeeze breakout
- `macd_divergence` — MACD histogram divergence
- `volume_breakout` — Volume spike + price breakout
- `mean_reversion` — Z-score mean reversion

## New Providers in v1.8.0
- Polygon.io — quotes, historical, fundamentals (free tier: 5 calls/min)
- IEX Cloud — quotes, historical, company info (free tier available)

---

## Notes
- v1.7.0 completed: Indonesian→English translation, SQLite WAL, API key rotation, pip-audit, hypothesis testing
- Security audit findings (HIGH/MEDIUM) all fixed
- Ready for release
