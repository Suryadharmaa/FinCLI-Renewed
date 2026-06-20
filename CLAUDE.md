# CLAUDE.md — FinCLI Development Guide

## Project Overview

FinCLI is a production-ready financial CLI/TUI terminal for market research, technical analysis, AI-assisted analysis, provider management, portfolio risk, journaling, watchlists, backtesting, paper trading, and local-first financial workflows.

- **Current Version:** v1.5.0
- **Python:** 3.11+
- **Framework:** Textual TUI + Rich
- **Entry Point:** `fincli.app.main:main`

---

## Architecture

```
fincli/
├── app/
│   ├── brokers/          # Live broker integrations (Alpaca, IBKR)
│   ├── cli/              # Command registry, router, autocomplete
│   ├── analysis/         # Technical analysis, AI prompts, backtest
│   ├── modules/          # Portfolio, trading, journal, alerts, scanner
│   ├── providers/        # AI & market data providers
│   ├── storage/          # SQLite DB, config, secrets, cache
│   ├── tui/              # Textual UI components
│   ├── utils/            # Security, formatting, crypto, errors
│   ├── connectors/       # News & data connectors
│   ├── agents/           # AI agent framework
│   └── diagnostics/      # Doctor, runtime checks
├── tests/
└── scripts/
```

---

## v1.1.0 Changelog (Completed)

### Phase 1: Command Consolidation
Removed 6 duplicate commands:
- `/quote` → `/market`
- `/structure` → `/technical`
- `/funda` → `/market`
- `/assistant` → `/ai`
- `/privacy status` → `/security status`
- `/privacy purge` → `/security purge`

### Phase 2: Live Trading with Alpaca
- Abstract broker interface (`fincli/app/brokers/base.py`)
- Alpaca integration (`fincli/app/brokers/alpaca.py`)
- Broker registry (`fincli/app/brokers/registry.py`)
- `LiveTradingEngine` with risk guard and audit log
- 9 new `/trading live` commands

### Phase 3: Security Hardening
- Broker key encryption (`fincli/app/utils/crypto.py`)
- PBKDF2-SHA256 (600k iterations) + HMAC-SHA256 integrity
- Session security status
- `/security encrypt-key|decrypt-key|session` commands

### Phase 4: New Features
- AI conversation context (last 3 questions remembered)
- `/portfolio rebalance` — equal-weight rebalancing suggestions
- `/export broker` — export live trading history
- Version bumped to v1.1.0

---

## v1.2.0 Changelog (Completed)

### Phase 5: Command UX Improvement
- Interactive model picker for `/ai_model` and `/news_model` (like Claude Code `/model`)
- Inline API key configuration during provider selection
- Removed redundant `key` subcommands (backward compatible with deprecation hint)

---

## v1.3.0 Changelog (Completed)

### Feature 1: Terminal Charting
**Goal:** ASCII candlestick chart rendering directly in terminal.

**Implementation:**
- `fincli/app/tui/chart.py` — ASCII candlestick renderer using Rich
- `/chart <symbol> [interval] [--overlay rsi,macd] [--width N] [--height N]`
- Candlestick bodies: `█` (bullish), `░` (bearish), `─` (doji)
- Wicks: `│`
- Volume bars below price chart
- RSI overlay with overbought/oversold zones (70/30)
- MACD overlay with signal line and histogram
- Price axis labels, OHLCV summary stats

**Files:**
- Create: `fincli/app/tui/chart.py`
- Modify: `fincli/app/cli/router.py` (add `/chart` route)
- Modify: `fincli/app/cli/commands.py` (register `/chart`)

### Feature 2: AI Context Sliding Window
**Goal:** Replace hard-coded 3-question history with token-based sliding window.

**Implementation:**
- `ConversationHistory` class uses character count estimation (~4 chars/token)
- Default budget: 4000 tokens (~16000 characters)
- Max turns: 20 (safety cap)
- Sliding window: evicts oldest turns when budget exceeded
- Response summary increased from 200 → 500 chars

**Files:**
- Modify: `fincli/app/analysis/assistant_context.py`

### Feature 3: Notification Webhooks
**Goal:** Push notifications for alerts via Discord and Telegram.

**Implementation:**
- `fincli/app/connectors/webhooks.py` — Webhook notification system
- Discord: Rich embeds with severity colors, symbol, price fields
- Telegram: Markdown formatted messages via Bot API
- `/notification` command for configuration:
  - `/notification add discord <name> <webhook_url>`
  - `/notification add telegram <name> <bot_token> <chat_id>`
  - `/notification list` — show configured targets
  - `/notification test <target>` — send test notification
  - `/notification remove <target>` — remove target

**Files:**
- Create: `fincli/app/connectors/webhooks.py`
- Modify: `fincli/app/cli/router.py` (add `/notification` route)
- Modify: `fincli/app/cli/commands.py` (register `/notification`)

---

## v1.4.0 Changelog (Completed)

### Feature 1: Universe-Wide Screener
**Goal:** Scan entire market universes, not just watchlist.

**Implementation:**
- Predefined universes: sp500, nasdaq, crypto, forex, commodities
- Extended filter expressions: `rsi<30`, `rsi>70`, `trend=bullish`, `sma_cross`, `sma_death`, `above_support`, `below_resistance`
- Combined filters: `rsi<30 and trend=bullish`
- `/scan <universe> [filter] [interval] [--limit N]`

**Files:**
- Modify: `fincli/app/modules/scanner.py` (add universes, new filters)
- Modify: `fincli/app/cli/router.py` (update `/scan` route)

### Feature 2: Multi-Portfolio
**Goal:** Support multiple named portfolios.

**Implementation:**
- `portfolios` table for portfolio metadata
- `portfolio_name` column in `portfolio_positions` (composite key)
- Auto-migration for existing databases
- Commands:
  - `/portfolio portfolios` — list all portfolios
  - `/portfolio create <name> [description]` — create new
  - `/portfolio switch <name>` — switch active
  - `/portfolio compare <name>` — compare two portfolios
  - `/portfolio delete <name>` — delete (not main)

**Files:**
- Modify: `fincli/app/storage/database.py` (schema migration)
- Modify: `fincli/app/modules/portfolio.py` (multi-portfolio support)
- Modify: `fincli/app/cli/router.py` (new subcommands)

### Feature 3: Binance Crypto Broker
**Goal:** Add crypto trading via Binance exchange.

**Implementation:**
- Binance REST API integration (testnet + live)
- HMAC SHA256 request signing
- Account, positions, orders, quotes
- Auto symbol conversion: BTC-USD -> BTCUSDT

**Files:**
- Create: `fincli/app/brokers/binance.py`
- Modify: `fincli/app/brokers/registry.py` (add Binance to catalog)

---

## v1.5.0 Changelog (Completed)

### Feature 1: WebSocket Reconnect Logic
**Goal:** Automatic reconnection for realtime streaming adapters.

**Implementation:**
- `ReconnectConfig` dataclass with exponential backoff + jitter
- Base delay: 1s, max delay: 60s, jitter: ±20%
- Auto-resubscribe after successful reconnect
- Emits `reconnecting`/`reconnected`/`reconnect_failed` events
- Heartbeat timeout detection (30s)

**Files:**
- Modify: `fincli/app/modules/realtime_stream.py`

### Feature 2: Config Schema Validation
**Goal:** Prevent silent failures from config typos.

**Implementation:**
- `validate()` method on `FinCLISettings`
- "Did you mean?" suggestions using difflib
- Validates provider names, themes, numeric ranges
- Prints warnings on config load

**Files:**
- Modify: `fincli/app/storage/config.py`

### Feature 3: Proactive Provider Health Warnings
**Goal:** Warn users about degraded providers before they notice.

**Implementation:**
- `health_status()` method on `ProviderRuntimeMetrics`
- Checks error rate (threshold: 20%), avg latency (1500ms), circuit breaker
- `check_provider_health()` method on `MarketDataService`

**Files:**
- Modify: `fincli/app/services/market_data.py`

### Feature 4: ASCII Equity Curve for Backtest
**Goal:** Visual representation of backtest performance.

**Implementation:**
- `render_equity_curve()` function in chart.py
- ASCII line chart with value axis
- Shows initial, final, peak, max drawdown
- Integrated into backtest output

**Files:**
- Create: `fincli/app/tui/chart.py` (add equity curve renderer)
- Modify: `fincli/app/cli/router.py` (integrate into backtest output)

### Feature 5: Memory Optimization
**Goal:** Prevent memory bloat in long sessions.

**Implementation:**
- `cleanup_old_sessions()` method (keep 7 days, max 50 sessions)
- Auto-cleanup on router startup
- Output preview already truncated to 1200 chars

**Files:**
- Modify: `fincli/app/modules/session_history.py`
- Modify: `fincli/app/cli/router.py`

### Bug Fixes (from CODE-REVIEW.md)
- Fix H1: `SecurityAuditLog.clear_old_events()` — implemented with SQLite date functions
- Fix H4: `TransactionService._position()` — added portfolio_name filter
- Fix H5: `ProviderMetricsStore.record()` — SQL increments instead of read-modify-write
- Fix M8: `set_market_provider_priority()` — removed unexpected news_provider side effect

---

## Roadmap: v1.6.0 (Future)

### Ollama Local LLM Support
- Add Ollama as AI provider
- Privacy-conscious alternative to cloud providers

### Options Chain
- Options data display (requires CBOE/Tradier API)
- Greeks calculation (delta, gamma, theta, vega)

### Tax & P&L Reporting
- Realized gains/losses calculation
- Export to tax formats (TurboTax, IRS 8949)

### Phase 5: Robustness & State Management

#### 5.1 Async I/O for Data Streaming
**Goal:** Prevent UI freeze during high-volatility market data streaming.

**Current:** Textual uses asyncio, but data fetching may block UI thread.
**Fix:** Ensure all market data fetching runs in worker threads, not main asyncio loop.

**Implementation:**
- Audit all `_run_async()` calls in `router.py`
- Ensure Kraken/HyperLiquid WebSocket handlers use `run_worker()` with `thread=True`
- Add timeout guards on all provider calls (prevent hang on unresponsive API)
- Test with simulated high-latency provider

#### 5.2 Auto-Save State Recovery
**Goal:** Resume session instantly after crash without losing layout or research buffer.

**Current:** Session history saved to SQLite, but UI state (layout, buffer) lost on crash.
**Fix:** Periodic auto-save of session state.

**Implementation:**
- Add `SessionStateManager` class in `fincli/app/storage/`
- Auto-save every 60 seconds:
  - Current command buffer
  - Output history (last N entries)
  - Active view/layout state
  - Open research panels
- On startup: detect unclean shutdown → offer resume
- Add `/session save|restore|clear` commands

**Files:**
- Create: `fincli/app/storage/session_state.py`
- Modify: `fincli/app/tui/layout.py` (auto-save hook)
- Modify: `fincli/app/cli/router.py` (resume command)

---

### Phase 6: AI & Data Layer Optimization

#### 6.1 Semantic Caching for AI Research
**Goal:** Reduce LLM API cost and latency for repeated/similar research queries.

**Decision: Start with hash-based cache, upgrade to semantic later.**

**MVP (v1.2.0):**
- Hash-based cache: exact prompt match → return cached response
- Cache TTL: 30 minutes
- Cache key: SHA-256(prompt + model + market_context)
- Store in SQLite table `ai_cache`

**Future (v1.3.0+):**
- Semantic cache with ChromaDB or sqlite-vss
- Embedding-based similarity threshold (cosine > 0.92 = cache hit)
- Requires `sentence-transformers` or OpenAI embeddings API

**Implementation:**
```python
# fincli/app/storage/ai_cache.py
class AICache:
    def get(self, prompt_hash: str) -> str | None
    def set(self, prompt_hash: str, response: str, ttl: int = 1800)
    def invalidate(self, pattern: str = "*")
```

**Files:**
- Create: `fincli/app/storage/ai_cache.py`
- Modify: `fincli/app/cli/router.py` (check cache before API call)
- Modify: `fincli/app/analysis/assistant_context.py` (cache key generation)

#### 6.2 Soft Error Detection in Circuit Breaker
**Goal:** Detect stale data and anomalies, not just HTTP errors.

**Current:** Circuit breaker triggers on HTTP 500/timeout.
**Enhanced:** Add soft error detection.

**New Detection Rules:**
1. **Stale Data:** `timestamp < now - cache_ttl * 2` → flag as stale
2. **Price Anomaly:** `abs(price_change) > 50%` in single candle → flag as anomaly
3. **Missing Fields:** `ProviderResponse` with critical fields null → flag
4. **Quality Score Drop:** `quality_score < 30` → trigger circuit breaker

**Implementation:**
```python
# Extend ProviderResponse
@dataclass
class ProviderResponse:
    ...
    staleness_score: float = 0.0    # 0=fresh, 1=stale
    anomaly_flags: list[str] = field(default_factory=list)
    data_freshness: datetime | None = None
```

**Files:**
- Modify: `fincli/app/providers/market/base.py` (extend ProviderResponse)
- Modify: `fincli/app/providers/market/manager.py` (soft error logic)
- Modify: `fincli/app/storage/market_cache.py` (staleness tracking)

---

### Phase 7: Developer Experience & Extensibility

#### 7.1 Plugin Sandbox Hardening
**Goal:** Prevent malicious plugins from accessing secrets or executing arbitrary code.

**Current:** Plugin sandbox validates paths, but plugins can still import `os`, `pathlib`, `open()`.
**Fix:** Restricted execution environment.

**Security Layers:**
1. **Import Whitelist:** Plugins can only import approved modules
2. **API Boundary:** Plugins access data through FinCLI API, not direct filesystem
3. **Secret Isolation:** `~/.fincli/secrets.env` not accessible to plugin code
4. **Resource Limits:** Max execution time, memory, API calls per plugin

**Implementation:**
```python
# fincli/app/plugins/sandbox.py
ALLOWED_IMPORTS = {
    "json", "math", "datetime", "typing", "dataclasses",
    "fincli.api",  # FinCLI public API only
}

BLOCKED_IMPORTS = {
    "os", "sys", "pathlib", "subprocess", "shutil",
    "socket", "http", "urllib", "requests",
}

class PluginSandbox:
    def execute(self, plugin_code: str, context: dict) -> dict:
        """Execute plugin code in restricted environment."""
        # 1. Parse AST, check imports
        # 2. Inject safe builtins only
        # 3. Provide FinCLI API context
        # 4. Execute with timeout
        # 5. Return result (no filesystem side effects)
```

**Files:**
- Modify: `fincli/app/plugins/sandbox.py` (add import whitelist)
- Modify: `fincli/app/plugins/loader.py` (validate plugin code)
- Create: `fincli/app/plugins/api.py` (public API for plugins)

#### 7.2 Plugin API Documentation
**Goal:** Clear API boundary for plugin developers.

**Public API exposed to plugins:**
```python
# fincli/app/plugins/api.py
class FinCLIPluginAPI:
    def get_quote(self, symbol: str) -> dict
    def get_portfolio(self) -> list[dict]
    def get_watchlist(self) -> list[dict]
    def add_alert(self, symbol: str, condition: str, value: float)
    def log(self, message: str)
    # No access to: secrets, database, filesystem, network
```

---

## Implementation Priority

### v1.3.0 (Completed)
| Feature | Effort | Impact | Status |
|---------|--------|--------|--------|
| Terminal Charting | Medium | High | ✅ Done |
| AI Context Sliding Window | Low | Medium | ✅ Done |
| Discord/Telegram Webhooks | Medium | High | ✅ Done |

### v1.4.0 (Planned)
| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| Multi-Broker (IBKR, Crypto) | High | High | **P0** |
| Screener Command | Medium | High | **P0** |
| Multi-Portfolio | Medium | Medium | P1 |
| Options Chain | High | Medium | P2 |

---

## Testing Strategy

### Existing Tests (747 passing):
- `tests/test_command_smoke.py` — All commands smoke tested
- `tests/test_v110_live_trading.py` — Live trading engine
- `tests/test_v110_security_crypto.py` — Encryption
- `tests/test_v110_new_features.py` — Conversation context, rebalance
- `tests/test_v120_session_state.py` — Auto-save/recovery
- `tests/test_v120_ai_cache.py` — Hash-based cache
- `tests/test_v120_soft_errors.py` — Anomaly detection
- `tests/test_v120_plugin_sandbox.py` — Import whitelist, API boundary

### New Tests Needed:
- `tests/test_v130_charting.py` — ASCII chart rendering, overlays
- `tests/test_v130_sliding_window.py` — Token-based conversation history
- `tests/test_v130_webhooks.py` — Discord/Telegram notification system

---

## Global Constraints

- Python 3.11+ required
- No external dependencies for core features (crypto uses stdlib)
- All secrets encrypted at rest
- All commands must pass smoke tests
- Version in sync: `pyproject.toml`, `package.json`, `fincli/__init__.py`

---

## PEMBERSIHAN BUG (v1.4.1)

Scan hasil review GLM 5.2 + verifikasi manual. 10 bug confirmed, 3 severity critical.

### Bug #1 — CRITICAL: f-string Ternary Precedence di `_format_order_confirmation()`
**File:** `fincli/app/cli/router.py` ~line 4631-4644
**Problem:** Ternary `if conf.price else ""` pada f-string concatenation menyebabkan precedence salah. Python parser meng-join semua adjacent string literals sebelum evaluate ternary. Hasil:
- `conf.price` truthy → text hanya sampai Price line, hilang Est. Cost/Risk Check/Broker/Mode/confirm
- `conf.price` falsy → text hanya Est. Cost dst, hilang Symbol/Side/Quantity/Order Type
**Fix:** Pecah jadi 2 bagian: base text + conditional price line.

### Bug #2 — CRITICAL: BinanceBroker pakai sync httpx.Client di async methods
**File:** `fincli/app/brokers/binance.py`
**Problem:** `_signed_request()` dan `_public_request()` pakai `self._client.request()` (sync) tapi dipanggil dari `async def`. Blocks event loop.
**Fix:** Ganti `httpx.Client` → `httpx.AsyncClient`, pakai `await self._client.request()`.

### Bug #3 — CRITICAL: `_router_roots()` missing `/chart` dan `/notification`
**File:** `fincli/app/cli/router.py` ~line 5335-5378
**Problem:** Set `_router_roots()` tidak update untuk command `/chart` dan `/notification` (v1.3.0). Doctor check akan report false "hidden" warnings.
**Fix:** Tambah `/chart` dan `/notification` ke set.

### Bug #4 — HIGH: Tutorial references removed commands
**File:** `fincli/app/cli/router.py` ~line 5406, 5420
**Problem:** Tutorial lesson 2 pakai `/quote AAPL` (removed v1.1.0, should `/market`). Lesson 3 pakai `/structure AAPL 1d` (removed v1.1.0, should `/technical`).
**Fix:** Update tutorial text.

### Bug #5 — HIGH: Response summary truncation inconsistency
**File:** `fincli/app/cli/router.py` ~line 2503
**Problem:** Caller truncate `response.content[:200]` tapi `ConversationHistory.add()` allow 500 chars. Changelog says "200 → 500" tapi caller masih 200.
**Fix:** Ganti `[:200]` → `[:500]` di caller.

### Bug #6 — HIGH: Hardcoded version strings di assistant_context.py
**File:** `fincli/app/analysis/assistant_context.py` ~line 159, 168
**Problem:** `build_command_reference()` hardcoded "v1.1.0", `build_fincli_feature_context()` hardcoded "v1.0.5". Harusnya pakai `__version__`.
**Fix:** Import `__version__` dari `fincli`, pakai f-string.

### Bug #7 — MEDIUM: Typo "ATLVRTX" di scanner universe
**File:** `fincli/app/modules/scanner.py` ~line 31
**Problem:** "ATLVRTX" bukan ticker valid. Harusnya "VRTX" (Vertex Pharmaceuticals).
**Fix:** Ganti "ATLVRTX" → "VRTX".

### Bug #8 — MEDIUM: Unused import di webhooks.py
**File:** `fincli/app/connectors/webhooks.py` ~line 246
**Problem:** `remove_webhook()` import `clear_secrets` tapi tidak dipakai.
**Fix:** Hapus import.

### Bug #9 — MEDIUM: Typo "menganot" di _validate_symbol
**File:** `fincli/app/cli/router.py` ~line 5263
**Problem:** "menganot" should be "mengandung".
**Fix:** Correct typo.

### Bug #10 — MEDIUM: BinanceBroker.cancel_order() always raises
**File:** `fincli/app/brokers/binance.py` ~line 286-290
**Problem:** `cancel_order()` selalu raise `ProviderError`. Tidak bisa cancel order.
**Fix:** Implement proper cancel dengan symbol parameter atau store order→symbol mapping.

---

### Implementasi Fix

| # | Bug | File | Effort |
|---|-----|------|--------|
| 1 | f-string ternary precedence | router.py | Low |
| 2 | Binance sync→async | binance.py | Medium |
| 3 | Missing router roots | router.py | Low |
| 4 | Tutorial stale commands | router.py | Low |
| 5 | Summary truncation | router.py | Low |
| 6 | Hardcoded versions | assistant_context.py | Low |
| 7 | Scanner typo | scanner.py | Low |
| 8 | Unused import | webhooks.py | Low |
| 9 | Typo validate_symbol | router.py | Low |
| 10 | Cancel order stub | binance.py | Medium |
