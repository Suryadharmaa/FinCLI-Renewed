# CODE-REVIEW.md — FinCLI v1.4.0

Comprehensive code review covering all 100+ Python source files and 80+ test files.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2 |
| High | 5 |
| Medium | 8 |
| Low | 7 |
| **Total** | **22** |

---

## Critical Issues

### C1. `_format_order_confirmation()` — f-string ternary precedence (FIXED)
**File:** `fincli/app/cli/router.py` ~line 4631
**Status:** ✅ Fixed in v1.4.1 bug cleanup
**Description:** Python implicit string concatenation + ternary `if conf.price else ""` caused both branches to lose content. When price is truthy, text only showed up to Price line; when falsy, only showed Est. Cost onwards.

### C2. `BinanceBroker` — sync httpx.Client in async methods (FIXED)
**File:** `fincli/app/brokers/binance.py`
**Status:** ✅ Fixed in v1.4.1 bug cleanup
**Description:** `httpx.Client` (sync) used in `async def` methods blocked the event loop. Changed to `httpx.AsyncClient` with proper `await`.

---

## High Issues

### H1. `SecurityAuditLog.clear_old_events()` — stub implementation, never deletes
**File:** `fincli/app/storage/audit_log.py:104-109`
**Description:** Method calculates `cutoff` but never uses it. Always returns 0. Comment says "SQLite doesn't have great date math" but `datetime('now', '-90 days')` works fine in SQLite.
```python
def clear_old_events(self, days: int = 90) -> int:
    cutoff = datetime.now(timezone.utc).isoformat()
    # SQLite doesn't have great date math, so we'll just keep all for now
    return 0
```
**Fix:** Use SQLite date function: `DELETE FROM security_audit WHERE created_at < datetime('now', ?)` with `f'-{days} days'`.

### H2. `_router_roots()` missing commands (FIXED)
**File:** `fincli/app/cli/router.py` ~line 5335
**Status:** ✅ Fixed in v1.4.1 bug cleanup
**Description:** `/chart` and `/notification` missing from `_router_roots()` set, causing Doctor to report false "hidden" warnings.

### H3. `JournalService.edit()` — SQL injection via f-string
**File:** `fincli/app/modules/journal.py:55-57`
**Description:** Column names are interpolated via f-string into SQL. While values are parameterized, the column names come from `fields.keys()` which are validated against `allowed` set, so actual risk is low. However, the pattern is fragile.
```python
set_clause = ", ".join(f"{k} = ?" for k in updates)
self.db.execute(f"UPDATE journal_entries SET {set_clause} WHERE id = ?", values)
```
**Risk:** Low-exploitable because `allowed` set restricts keys. But pattern should use explicit mapping instead of f-string SQL.
**Fix:** Use explicit column whitelist mapping or ORM pattern.

### H4. `TransactionService._position()` — missing portfolio_name filter
**File:** `fincli/app/modules/transactions.py:79-84`
**Description:** Queries `portfolio_positions` without `portfolio_name` filter. In multi-portfolio setup, could return wrong position from different portfolio.
```python
def _position(self, symbol: str) -> dict[str, object] | None:
    rows = self.db.query(
        "SELECT symbol, quantity, average_price, currency FROM portfolio_positions WHERE symbol = ?",
        (symbol,),
    )
```
**Fix:** Add `AND portfolio_name = ?` filter, pass `self.portfolio.portfolio_name`.

### H5. `ProviderMetricsStore.record()` — read-modify-write race condition
**File:** `fincli/app/storage/provider_metrics.py:35-60`
**Description:** Reads current metrics, modifies in Python, then writes back. In concurrent scenarios (TUI workers), two writes could interleave and lose increments.
```python
current = self.snapshot().get(provider, ProviderRuntimeMetrics(provider))
current.record(success=success, latency_ms=latency_ms, fallback=fallback)
self.db.execute("INSERT ... ON CONFLICT ... DO UPDATE SET calls=excluded.calls ...")
```
**Fix:** Use SQL increment: `SET calls = calls + 1, successes = successes + ?` instead of read-modify-write.

---

## Medium Issues

### M1. `_period_for_timeframe()` — missing "1wk" and "1mo" mappings
**File:** `fincli/app/analysis/multi_timeframe.py:132-138`
**Description:** Maps "1w"/"w" to "2y" but router's `_chart()` uses "1wk" and "1mo" which map to "6mo"/"5y". Inconsistent period mapping between MTF and chart.
```python
def _period_for_timeframe(timeframe: str) -> str:
    if normalized in {"1m", "5m", "15m", "30m", "1h", "4h"}:
        return "60d"
    if normalized in {"1w", "w"}:
        return "2y"
    return "1y"
```
**Fix:** Add "1wk" → "2y" and "1mo" → "5y" mappings, or use shared constant.

### M2. `build_command_reference()` — imports `COMMANDS` not `CommandRegistry`
**File:** `fincli/app/analysis/assistant_context.py:152`
**Description:** Imports `COMMANDS` from `fincli.app.cli.commands` but this is a module-level tuple. If commands are dynamically registered, this won't reflect them. Minor — current commands are static.

### M3. `scan_symbols()` — silently swallows exceptions
**File:** `fincli/app/modules/scanner.py:96-102`
**Description:** `asyncio.gather(return_exceptions=True)` catches all exceptions. Non-`ScanResult` exceptions (including `ProviderError`) are silently dropped. User sees fewer results with no explanation.
```python
scanned = await asyncio.gather(
    *[_scan_symbol(symbol, provider, filter_expression, interval) for symbol in batch],
    return_exceptions=True,
)
for item in scanned:
    if isinstance(item, ScanResult) and item.matched:
        results.append(item)
```
**Fix:** Log or collect exceptions, show warning to user about failed symbols.

### M4. `AlpacaBroker.get_quote()` — return type mismatch with base interface
**File:** `fincli/app/brokers/alpaca.py:324-336`
**Description:** Returns `float` but base interface `BaseBroker.get_quote()` also returns `float`. However, `BinanceBroker.get_quote()` originally returned `dict[str, float]` (fixed in v1.4.1). The `MarketDataService.quote()` expects `Quote` object, not `float`. The broker `get_quote()` is never called by `MarketDataService` — it's only used internally. Inconsistent API surface.

### M5. `BacktestEngine` — `random.seed()` not called for Monte Carlo reproducibility
**File:** `fincli/app/analysis/backtest.py`
**Description:** Monte Carlo simulation uses `random` module without seeding. Results are not reproducible across runs. For educational backtesting, this is acceptable but should be documented.

### M6. `WebResearchService._get_text()` — creates new client per request if none injected
**File:** `fincli/app/services/web_research.py:113-132`
**Description:** If `self._client` is None, creates a new `httpx.AsyncClient` per request and closes it after. This means no connection reuse, higher latency. For sequential research calls, this is wasteful.
```python
close_client = self._client is None
client = self._client or httpx.AsyncClient(...)
```
**Fix:** Create client lazily and reuse across calls (like AI providers do).

### M7. `NewsAggregator._fetch_provider()` — fragile provider matching
**File:** `fincli/app/services/news_aggregator.py:74-77`
**Description:** Checks `any(item.name == provider for item in self.market_service.providers)` but `item.name` is provider name like "yfinance", while `provider` is also "yfinance". This works but is fragile — if provider naming changes, news fetch breaks silently.
```python
async def _fetch_provider(self, provider: str, symbol: str, limit: int) -> list[NewsItem]:
    if provider == "yfinance" or any(item.name == provider for item in self.market_service.providers):
        return await self.market_service.news(symbol, limit=limit)
    return await self.news_connectors.fetch(provider, symbol, limit=limit)
```

### M8. `config.py` — `set_market_provider_priority()` also sets `news_provider`
**File:** `fincli/app/storage/config.py:143-150`
**Description:** Setting market provider priority also overwrites `news_provider`. This is unexpected behavior — changing market priority shouldn't silently change news provider.
```python
def set_market_provider_priority(self, providers: list[str]) -> None:
    ...
    self.settings.market_provider_priority = normalized
    self.settings.market_provider = normalized[0]
    self.settings.news_provider = normalized[0]  # ← unexpected side effect
```
**Fix:** Remove `self.settings.news_provider = normalized[0]` line.

---

## Low Issues

### L1. Version string in `_format_trading_overview()` — hardcoded "v1.0.0"
**File:** `fincli/app/cli/router.py:4482`
**Description:** `table.add_row("Live Orders", "disabled", "No live broker orders are sent by FinCLI v1.0.0.")` — should use `__version__` or remove version reference.

### L2. `TUTORIAL_LESSONS` — stale tip references
**File:** `fincli/app/cli/router.py` ~line 5400-5468
**Description:** Tutorial tip says "You can skip API keys for now — FinCLI works with free providers like yfinance!" but doesn't mention the interactive picker or new provider options.

### L3. `FinCLISettings.safe_dict()` — reads env vars directly instead of from secrets store
**File:** `fincli/app/storage/config.py:45-72`
**Description:** `safe_dict()` reads `os.getenv()` for all API keys. If secrets are only in `~/.fincli/secrets.env` and not loaded into env, they'll show as "not set" even when configured. This is actually correct behavior since `load_local_secrets()` loads them into env at startup.

### L4. `_DuckDuckGoParser` — HTML parser may miss results on changed DOM
**File:** `fincli/app/services/web_research.py:190-226`
**Description:** Parser relies on specific CSS classes (`result__a`, `result__snippet`). DuckDuckGo may change their HTML structure, breaking search silently. No error reporting when 0 results found from DuckDuckGo.

### L5. `PluginSandbox.validate_path()` — no symlink resolution
**File:** `fincli/app/plugins/loader.py:245-251`
**Description:** Uses `path.resolve()` which does resolve symlinks, but the comparison `self.plugin_dir in resolved.parents` could be bypassed if plugin directory itself is a symlink pointing outside. Edge case.

### L6. `classify_provider_error()` — "api key" keyword match is too broad
**File:** `fincli/app/providers/reliability.py:122`
**Description:** `"api key" in text and "belum" in text` — the `and` condition means it only matches Indonesian "belum" (not yet). English error messages with "api key" + "missing" won't match `STATUS_AUTH_FAILED`.
```python
if "401" in text or "unauthorized" in text or "invalid key" in text or "api key" in text and "belum" in text:
```
**Fix:** Add `"missing" in text` or `"required" in text` as alternatives.

### L7. `_format_optional_number()` — `number.is_integer()` on float
**File:** `fincli/app/cli/router.py:4875-4884`
**Description:** `float.is_integer()` returns True for 1.0 but also for 1000000.0. The formatting `f"{number:,.0f}"` removes decimal but large numbers could be confusing without context. Minor cosmetic issue.

---

## Statistics

- **Files scanned:** 100+ Python source files, 80+ test files
- **Modules reviewed:** cli, storage, brokers, modules, analysis, providers, services, connectors, plugins, tui, utils, diagnostics, research, agents
- **Test coverage:** 758 tests passing
- **Pre-existing flaky tests:** 1 (test_phase21_ai_chat_tui — timing issue)

---

## Recommendations

1. **Fix H1 (audit log):** Implement proper cleanup with SQLite date functions
2. **Fix H4 (transactions):** Add portfolio_name filter for multi-portfolio correctness
3. **Fix H5 (metrics):** Use SQL increments instead of read-modify-write
4. **Fix M8 (config):** Remove unexpected news_provider side effect
5. **Add integration tests** for multi-portfolio transaction flows
6. **Add timeout to web research** client reuse (M6)
7. **Document** Monte Carlo non-reproducibility (M5)
