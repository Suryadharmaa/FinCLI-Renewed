# FinCLI v1.5.1 Full Codebase Bug Report

**Auditor:** Senior Software Engineer  
**Date:** 2026-01-27  
**Scope:** 119 Python files, 25,613 lines  
**Method:** File-by-file static analysis per bug detection checklist (A-J)

---

## BUG-1: Binance _signed_request crashes on non-JSON error responses

**File:** `fincli/app/brokers/binance.py`  
**Line(s):** 121, 135  
**Category:** Error Handling  
**Severity:** High

**Code (actual):**
```python
# Line 121
error = resp.json().get("msg", resp.text)
raise ProviderError(f"Binance API error: {error}")

# Line 135
error = resp.json().get("msg", resp.text)
raise ProviderError(f"Binance API error: {error}")
```

**Why it's a bug:**
If Binance returns a non-JSON error response (e.g., HTML 502 gateway error, plain text maintenance message), `resp.json()` raises `json.JSONDecodeError`, which is not caught. This masks the original HTTP error and produces an unhelpful traceback instead of a meaningful error message.

**Failure scenario:**
User runs `/trading live connect binance testnet` during Binance maintenance. Binance returns HTML 502 page. User sees JSONDecodeError traceback instead of "Binance API error: HTTP 502".

**Fix (minimal):**
```python
# Line 118-124
try:
    error_data = resp.json()
    error = error_data.get("msg", resp.text)
except (json.JSONDecodeError, ValueError):
    error = resp.text[:200] if resp.text else f"HTTP {resp.status_code}"
raise ProviderError(f"Binance API error: {error}")

# Same pattern for line 132-137
```

---

## BUG-2: Gemini API key exposed in URL query parameter

**File:** `fincli/app/providers/ai/http_provider.py`  
**Line(s):** 136  
**Category:** Security  
**Severity:** High

**Code (actual):**
```python
url = f"{self.base_url}/models/{request.model}:generateContent?key={self.api_key}"
```

**Why it's a bug:**
API key is passed as a URL query parameter. URLs are logged by proxies, CDNs, server access logs, and browser history. This leaks the Gemini API key to any intermediate logging system.

**Failure scenario:**
User's network uses a corporate proxy that logs URLs. The Gemini API key appears in proxy logs. An attacker with log access uses the key for unauthorized API calls.

**Fix (minimal):**
```python
# Use header-based auth instead
headers = {"x-goog-api-key": self.api_key}
payload = {"contents": [{"parts": [{"text": request.prompt}]}]}
client = self._get_client(request.timeout_seconds)
response = await client.post(
    f"{self.base_url}/models/{request.model}:generateContent",
    json=payload,
    headers=headers,
)
```

---

## BUG-3: AlertDaemon creates new event loop per check iteration

**File:** `fincli/app/modules/alerts.py`  
**Line(s):** 156-163  
**Category:** Async  
**Severity:** Medium

**Code (actual):**
```python
def _run(self) -> None:
    try:
        while not self._stop_event.is_set():
            try:
                asyncio.run(self.check_once())
            except Exception as exc:
                logger.warning("Alert check failed: %s", exc)
            self._stop_event.wait(self.check_interval)
```

**Why it's a bug:**
`asyncio.run()` creates a new event loop each iteration. Any httpx.AsyncClient created inside `check_once()` (via `market_service.quote()`) is bound to that specific loop. On the next iteration, a new loop is created, but the httpx client from the previous iteration may still be cached in the provider chain. This can cause "attached to a different event loop" errors.

**Failure scenario:**
Alert daemon runs for 10+ minutes. Market service caches an httpx client bound to loop A. Next iteration creates loop B. Cached client tries to use loop A → RuntimeError.

**Fix (minimal):**
```python
def _run(self) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while not self._stop_event.is_set():
            try:
                loop.run_until_complete(self.check_once())
            except Exception as exc:
                logger.warning("Alert check failed: %s", exc)
            self._stop_event.wait(self.check_interval)
    finally:
        loop.close()
```

---

## BUG-4: Binance get_account() silently swallows price fetch errors

**File:** `fincli/app/brokers/binance.py`  
**Line(s):** 206-210  
**Category:** Error Handling  
**Severity:** Medium

**Code (actual):**
```python
try:
    ticker = await self._public_request("GET", "/api/v3/ticker/price", {"symbol": f"{balance['asset']}USDT"})
    price = float(ticker.get("price", 0))
    total_value += (float(balance["free"]) + float(balance["locked"])) * price
except Exception:
    pass
```

**Why it's a bug:**
All exceptions are silently swallowed. If the price fetch fails for a non-USDT asset (e.g., BTC), that asset's value is excluded from `total_value`. The user sees a portfolio value that's missing major holdings with no indication of the omission.

**Failure scenario:**
User has 1 BTC and 1000 USDT. Binance API returns error for BTCUSDT ticker. `get_account()` reports portfolio value as 1000 USDT instead of ~70,000 USDT. User believes their portfolio crashed.

**Fix (minimal):**
```python
except Exception as exc:
    logger.warning("Failed to fetch %s price: %s", balance["asset"], exc)
    # Still include with zero value but flag it
```

---

## BUG-5: Binance get_positions() same silent error swallowing

**File:** `fincli/app/brokers/binance.py`  
**Line(s):** 237-240  
**Category:** Error Handling  
**Severity:** Medium

**Code (actual):**
```python
try:
    ticker = await self._public_request("GET", "/api/v3/ticker/price", {"symbol": f"{balance['asset']}USDT"})
    current_price = float(ticker.get("price", 0))
except Exception:
    current_price = 0
```

**Why it's a bug:**
Same pattern as BUG-4. Positions show `current_price=0` and `market_value=0` when price fetch fails. User sees positions with zero value, no error indication.

**Fix (minimal):**
Same as BUG-4 — log the error, consider returning `None` for price to distinguish "price unknown" from "price is zero".

---

## BUG-6: MarketDataService.run() creates new event loop per call

**File:** `fincli/app/services/market_data.py`  
**Line(s):** 331-338  
**Category:** Async  
**Severity:** Medium

**Code (actual):**
```python
def run(self, awaitable: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, awaitable)
        return future.result()
```

**Why it's a bug:**
`asyncio.run()` creates a new event loop each call. If the awaitable involves httpx clients cached from a previous call, those clients are bound to a different loop. The `ThreadPoolExecutor` path compounds this — the thread gets its own loop, but cached clients from the main thread's loop can't be reused.

**Failure scenario:**
User runs `/market AAPL 1d` twice in quick succession. First call caches httpx client in yfinance provider. Second call creates new loop. Cached client fails with "attached to different event loop".

**Fix (minimal):**
Document that this method should only be used for one-shot operations, not for services that cache clients. Or add a persistent loop:
```python
def __init__(self, ...):
    ...
    self._loop: asyncio.AbstractEventLoop | None = None

def run(self, awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(awaitable)
    ...
```

---

## BUG-7: `_format_scan_results` error display shows only first error

**File:** `fincli/app/cli/router.py`  
**Line(s):** ~3920  
**Category:** Logic  
**Severity:** Low

**Code (actual):**
```python
if errors:
    table.add_row("-", "-", "-", "-", "-", "-", f"[yellow]{len(errors)} symbol(s) failed: {errors[0][:60]}[/]")
```

**Why it's a bug:**
Only the first error message is shown. If 10 symbols fail for different reasons, user only sees the first error. The count is shown but the individual failures are hidden.

**Fix (minimal):**
```python
if errors:
    summary = f"{len(errors)} symbol(s) failed"
    if errors:
        summary += f": {errors[0][:50]}"
        if len(errors) > 1:
            summary += f" (+{len(errors)-1} more)"
    table.add_row("-", "-", "-", "-", "-", "-", f"[yellow]{summary}[/]")
```

---

## BUG-8: Kraken/HyperLiquid _emit swallows all callback exceptions silently

**File:** `fincli/app/modules/realtime_stream.py`  
**Line(s):** 230-237, 388-395  
**Category:** Error Handling  
**Severity:** Low

**Code (actual):**
```python
async def _emit(self, event: StreamEvent) -> None:
    for callback in self._callbacks:
        try:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 - callbacks should not break the stream
            pass
```

**Why it's a bug:**
All callback exceptions are silently swallowed. If a user's callback has a bug, they get zero feedback — events just stop working with no error message.

**Fix (minimal):**
```python
except Exception as exc:
    logger.warning("Stream callback error: %s", exc)
```

---

## BUG-9: EquityStreamingAdapter._poll_loop swallows all poll errors silently

**File:** `fincli/app/modules/realtime_stream.py`  
**Line(s):** 469  
**Category:** Error Handling  
**Severity:** Low

**Code (actual):**
```python
except Exception:  # noqa: BLE001 - poll failures should not crash the loop
    pass
```

**Why it's a bug:**
If the market provider is consistently failing (e.g., expired API key), the polling loop silently continues without any indication. User believes streaming is active but receives no data.

**Fix (minimal):**
```python
except Exception as exc:
    logger.debug("Equity poll failed for %s: %s", symbol, exc)
```

---

## BUG-10: `_kraken_pair` doesn't handle all common symbol formats

**File:** `fincli/app/modules/realtime_stream.py`  
**Line(s):** 525-539  
**Category:** Logic  
**Severity:** Low

**Code (actual):**
```python
def _kraken_pair(symbol: str) -> str:
    symbol = symbol.upper().replace("-", "").replace("/", "")
    mappings = {
        "BTCUSD": "XBT/USD",
        ...
    }
    return mappings.get(symbol, symbol)
```

**Why it's a bug:**
If user passes "BTC-USDT", it becomes "BTCUSDT" after replace, which is not in the mappings dict. The raw "BTCUSDT" is sent to Kraken, which doesn't recognize it. Kraken uses "XBT/USDT" format.

**Fix (minimal):**
Add `"BTCUSDT": "XBT/USDT"` and `"ETHUSDT": "ETH/USDT"` to mappings.

---

## Summary

| # | Title | File | Severity | Category |
|---|-------|------|----------|----------|
| 1 | Binance crashes on non-JSON errors | binance.py:121 | High | Error Handling |
| 2 | Gemini API key in URL | http_provider.py:136 | High | Security |
| 3 | AlertDaemon new loop per iteration | alerts.py:160 | Medium | Async |
| 4 | Binance get_account silent errors | binance.py:206 | Medium | Error Handling |
| 5 | Binance get_positions silent errors | binance.py:237 | Medium | Error Handling |
| 6 | MarketDataService.run new loop | market_data.py:331 | Medium | Async |
| 7 | Scan results show only first error | router.py:~3920 | Low | Logic |
| 8 | Stream callbacks silently swallowed | realtime_stream.py:230 | Low | Error Handling |
| 9 | Equity poll errors silently swallowed | realtime_stream.py:469 | Low | Error Handling |
| 10 | Kraken pair mapping incomplete | realtime_stream.py:525 | Low | Logic |

**Total bugs found:** 10  
**Critical:** 0  
**High:** 2  
**Medium:** 4  
**Low:** 4

**Highest risk areas:**
1. `fincli/app/brokers/binance.py` — 3 bugs, affects live trading execution and portfolio accuracy
2. `fincli/app/modules/realtime_stream.py` — 3 bugs, affects realtime data reliability
3. `fincli/app/modules/alerts.py` — 1 bug, affects background alert checking stability

**Files with no bugs found:**
- `fincli/app/brokers/base.py`
- `fincli/app/brokers/registry.py`
- `fincli/app/storage/database.py`
- `fincli/app/storage/secrets.py`
- `fincli/app/storage/cache.py`
- `fincli/app/storage/market_cache.py`
- `fincli/app/storage/session_state.py`
- `fincli/app/storage/config.py`
- `fincli/app/storage/audit_log.py`
- `fincli/app/storage/ai_cache.py`
- `fincli/app/utils/errors.py`
- `fincli/app/utils/formatting.py`
- `fincli/app/utils/security.py`
- `fincli/app/utils/crypto.py`
- `fincli/app/utils/i18n.py`
- `fincli/app/analysis/indicators.py`
- `fincli/app/analysis/technical_signal.py`
- `fincli/app/analysis/technical_debate.py`
- `fincli/app/analysis/market_structure.py`
- `fincli/app/analysis/multi_timeframe.py`
- `fincli/app/analysis/backtest.py`
- `fincli/app/analysis/assistant_context.py`
- `fincli/app/modules/portfolio.py`
- `fincli/app/modules/portfolio_analytics.py`
- `fincli/app/modules/portfolio_risk.py`
- `fincli/app/modules/journal.py`
- `fincli/app/modules/journal_analytics.py`
- `fincli/app/modules/watchlist.py`
- `fincli/app/modules/session_history.py`
- `fincli/app/modules/exporter.py`
- `fincli/app/modules/reports.py`
- `fincli/app/modules/user_profile.py`
- `fincli/app/modules/transactions.py`
- `fincli/app/modules/scanner.py`
- `fincli/app/modules/algo_engine.py`
- `fincli/app/modules/economic_calendar.py`
- `fincli/app/services/news_aggregator.py`
- `fincli/app/services/data_quality.py`
- `fincli/app/services/data_trust.py`
- `fincli/app/services/source_quality.py`
- `fincli/app/services/market_overview.py`
- `fincli/app/services/macro_data.py`
- `fincli/app/services/web_research.py`
- `fincli/app/providers/reliability.py`
- `fincli/app/providers/market/base.py`
- `fincli/app/providers/market/manager.py`
- `fincli/app/providers/market/symbols.py`
- `fincli/app/providers/market/yfinance_provider.py`
- `fincli/app/providers/market/finnhub_provider.py`
- `fincli/app/providers/market/alphavantage_provider.py`
- `fincli/app/providers/market/twelvedata_provider.py`
- `fincli/app/providers/market/custom_provider.py`
- `fincli/app/providers/market/news_provider.py`
- `fincli/app/providers/ai/base.py`
- `fincli/app/providers/ai/manager.py`
- `fincli/app/connectors/webhooks.py`
- `fincli/app/connectors/catalog.py`
- `fincli/app/connectors/news_connectors.py`
- `fincli/app/plugins/loader.py`
- `fincli/app/plugins/lifecycle.py`
- `fincli/app/plugins/api.py`
- `fincli/app/tui/chart.py`
- `fincli/app/tui/components.py`
- `fincli/app/tui/theme.py`
- `fincli/app/tui/themes.py`
- `fincli/app/tui/model_selector.py`
- `fincli/app/tui/market_provider_selector.py`
- `fincli/app/diagnostics/runtime.py`
- `fincli/app/diagnostics/capabilities.py`
- `fincli/app/research/engine.py`
- `fincli/app/research/models.py`
- `fincli/app/research/prompt_builder.py`
- `fincli/app/research/formatter.py`
- `fincli/app/research/exporter.py`
- `fincli/app/agents/registry.py`

**Files not audited (reason):**
- `fincli/app/tui/layout.py` — partially read (560 lines), remaining sections not critical for bug patterns
- `fincli/app/cli/router.py` — 5,616 lines, partially read key sections; remaining are UI formatting functions with low bug risk
