# FinCLI Architecture

This document describes the codebase structure, key modules, and data flow in FinCLI.

---

## Directory Structure

```
fincli/
  app/
    main.py                      # TUI entry point
    cli/
      commands.py                # Command registry (CommandSpec, CommandRegistry)
      router.py                  # Command router (CommandRouter) -- all command handlers
    tui/
      layout.py                  # Textual layout, input, output, autocomplete
      components.py              # TUI components
      theme.py                   # Terminal theme and color rules
    providers/
      ai/
        base.py                  # AI provider base class
        manager.py               # AI provider manager (OpenRouter, Groq, etc.)
      market/
        base.py                  # Market provider base class (Quote, NewsItem, etc.)
        manager.py               # Market provider manager (fallback chain)
        symbols.py               # Symbol resolver and normalization
        yfinance_provider.py     # yfinance adapter
        finnhub_provider.py      # Finnhub adapter
        twelvedata_provider.py   # Twelve Data adapter
        alphavantage_provider.py # Alpha Vantage adapter
        custom_provider.py       # Custom market data provider
      reliability.py             # ProviderResult, reliability statuses, classification
    services/
      market_data.py             # MarketDataService: fallback, timeout, circuit breaker, metrics
      market_overview.py         # MarketOverview builder
      data_quality.py            # DataQualityReport scoring
      data_trust.py              # Data Trust Gate for AI grounding
      macro_data.py              # AlphaVantage macro data service
      news_aggregator.py         # News aggregation and fallback
      web_research.py            # Free web research/search fallback
      source_quality.py          # Source quality and freshness scoring
    analysis/
      analyzer.py                # Market analysis prompt builder
      indicators.py              # Technical indicators (RSI, MACD, EMA, Bollinger, etc.)
      market_structure.py        # Market structure analysis (BOS, CHoCH, trends)
      multi_timeframe.py         # Multi-timeframe analysis
      technical_debate.py        # Bull/bear debate engine
      technical_signal.py        # Signal generation
      backtest.py                # Backtesting engine
      gameplay_plan.py           # Gameplay/risk context builder
      assistant_context.py       # AI assistant prompt builder
    modules/
      portfolio.py               # Portfolio model and PnL
      portfolio_risk.py          # Portfolio Risk v3 engine
      portfolio_analytics.py     # Time-series snapshots, Sharpe/Sortino/Calmar, what-if, benchmark
      transactions.py            # Transaction storage and realized PnL
      trading.py                 # PaperTradingEngine, BrokerCatalog, RealtimeConnectorCatalog
      algo_engine.py             # Algo trading strategies
      broker_adapter.py          # Broker sandbox adapters (Alpaca, Tradier, IBKR)
      realtime_stream.py         # Realtime streaming adapters (Kraken WS, HyperLiquid WS)
      journal.py                 # Trading/investment journal
      journal_analytics.py       # Journal statistics and AI review
      watchlist.py               # Watchlist storage
      alerts.py                  # Alert service and daemon
      economic_calendar.py       # Economic calendar provider flow
      scanner.py                 # Watchlist scanner with indicator filters
      reports.py                 # Market report writer
      exporter.py                # Unified export (CSV/JSON)
      session_history.py         # Session history storage
      user_profile.py            # User profile management
    research/
      __init__.py                # ResearchEngine, format_research_brief, write_research_report
      engine.py                  # Research Engine v3 core
      models.py                  # Research brief models
      formatter.py               # Research output formatting
      prompt_builder.py          # Research AI prompt builder
      exporter.py                # Research export (MD/JSON)
    agents/
      registry.py                # Agent framework registry
    connectors/
      catalog.py                 # Connector catalog
      news_connectors.py         # News connector catalog and manager
    diagnostics/
      capabilities.py            # Command capability matrix
      runtime.py                 # Runtime environment checks
    plugins/
      loader.py                  # Plugin manifest loader
    storage/
      config.py                  # ConfigManager (JSON config)
      database.py                # FinCLIDatabase (SQLite)
      secrets.py                 # Secret storage (~/.fincli/secrets.env)
      cache.py                   # TTLCache (runtime)
      market_cache.py            # MarketCache (persistent SQLite)
      provider_metrics.py        # ProviderMetricsStore (persistent SQLite)
    utils/
      errors.py                  # Error classes (FinCLIError, CommandError, RateLimitError)
      formatting.py              # Rich formatting helpers (AIResponseView, MarkdownBlock, semantic_text)
  scripts/
    prepublish_check.py          # Prepublish safety scanner
tests/
  ...                            # Test suite
```

---

## Data Flow

### Command Execution

```
User Input (TUI)
  -> layout.py (input handler)
  -> CommandRouter.route(raw)
  -> _route() dispatches to handler method
  -> Handler calls service/provider
  -> CommandResult(renderable, status)
  -> layout.py renders output
```

### Market Data Request

```
Command handler
  -> MarketDataService.quote(symbol)
  -> Try primary provider (e.g., Finnhub)
  -> If fail: try next provider (e.g., yfinance)
  -> Circuit breaker tracks failures per provider
  -> Cache results (runtime TTL + persistent SQLite)
  -> Return Quote with provider, status, timestamp
```

### AI Analysis

```
/analyze AAPL 1d
  -> Get candles from MarketDataService
  -> Summarize technical indicators (RSI, MACD, EMA, Bollinger, ATR, S/R)
  -> Analyze market structure (BOS, CHoCH, trend, pattern)
  -> Get news context
  -> Build gameplay context from /profile
  -> Build AI grounding context (data quality, trust gate, provider metrics)
  -> Send grounded prompt to AI provider
  -> Return AIResponse wrapped in MarkdownBlock
```

### Research Engine

```
/research AAPL --deep
  -> ResearchEngine.build(symbol, timeframe, mode)
  -> Gather: quote, OHLCV, technical, structure, news, fundamentals, macro
  -> Build data quality report
  -> Build data trust gate
  -> If mode == "deep" or "report": send grounded prompt to AI
  -> If news missing: fall back to web research
  -> Format research brief with cited sources
  -> Return or export (md/json)
```

---

## Key Abstractions

### ProviderResult

Standard envelope for all provider calls:

```python
ProviderResult(
    provider="finnhub",
    operation="quote",
    status="ok",           # ok, auth_failed, rate_limited, entitlement_missing, etc.
    realtime_label="realtime",
    source="finnhub",
    data_quality="strong",
    missing_fields=(),
    message="ok",
)
```

### Reliability Statuses

| Status | Meaning |
|--------|---------|
| `ok` | Data returned successfully |
| `auth_failed` | API key invalid or missing |
| `rate_limited` | Rate limit exceeded |
| `entitlement_missing` | Plan does not cover this data |
| `partial_data` | Some fields missing |
| `delayed` | Data is not realtime |
| `fallback` | Using fallback provider |
| `schedule_only` | Estimated/schedule data only |
| `empty_data` | Provider returned no data |
| `network_error` | Network/connectivity issue |
| `unavailable` | Provider cannot serve request |
| `circuit_open` | Circuit breaker tripped |

### DataQualityReport

Scoring system for data completeness:

- **Score:** 0-100
- **Tier:** strong (85+), usable (65+), partial (40+), weak (<40)
- **Freshness:** How recent the data is
- **Missing fields:** List of absent data points

### Data Trust Gate

Controls AI output confidence based on data quality:

- **Trust levels:** strong, usable, partial, blocked
- **Confidence cap:** Limits AI confidence when data is weak
- **Signal strength:** Controls whether AI can give directional signals
- Injected into AI prompts so the model knows its constraints

---

## Provider Architecture

### Market Provider Chain

```
MarketProviderManager
  -> create_many(priority_list)
  -> MarketDataService
     -> providers: [Finnhub, TwelveData, AlphaVantage, YFinance]
     -> Try each in order
     -> Circuit breaker per provider
     -> Cache results
     -> Track metrics (session + persistent)
```

### AI Provider Chain

```
AIProviderManager
  -> create(provider_name)
  -> Returns: BaseAIProvider (OpenRouter, Groq, OpenAI, etc.)
  -> Used by: /ai, /analyze, /research --deep, /journal review
```

### News Provider Chain

```
NewsAggregator
  -> Uses MarketDataService for market news
  -> Uses NewsConnectorManager for RSS/API news
  -> Fallback priority from config
  -> Combines and deduplicates
```

---

## Storage Layer

### SQLite Database (`~/.fincli/fincli.db`)

Tables:

- `portfolio` -- portfolio positions
- `transactions` -- buy/sell ledger with realized PnL
- `journal` -- trading journal entries
- `watchlist` -- watchlist symbols
- `alerts` -- price alerts (price, RSI, volume, MACD conditions)
- `alert_history` -- triggered alert log
- `paper_orders` -- paper trading orders
- `audit_log` -- immutable order audit trail (never UPDATE/DELETE)
- `sessions` -- session history
- `session_events` -- command history per session
- `provider_metrics` -- persistent provider call metrics
- `portfolio_snapshots` -- time-series portfolio snapshots
- `user_profile` -- user gameplay profile

### Config (`~/.fincli/config.json`)

JSON file with:

- AI provider and model
- Market provider and priority chain
- News provider and priority chain
- Timezone, currency, cache TTL, provider timeout
- Circuit breaker thresholds
- Theme

### Secrets (`~/.fincli/secrets.env`)

Environment-style file with API keys. Never committed to git.

---

## Safety Mechanisms

### Circuit Breaker

- Tracks consecutive failures per provider.
- After N failures (configurable), opens the circuit.
- Provider is skipped for a cooldown period.
- Resets automatically after cooldown.

### Risk Guard (Paper Trading)

- Max position size (% of equity).
- Daily loss limit (% of equity).
- Kill switch (blocks all orders).
- Leverage warning.
- Asset class restrictions.

### AI Grounding Guard

- Data Trust Gate injected into every AI prompt.
- AI must acknowledge missing data, low quality, and provider status.
- Confidence capped when data is weak.
- Directional signals blocked when trust is too low.

### Prepublish Safety

`scripts/prepublish_check.py` scans for:

- `.env` and `secrets.env` files
- SQLite databases
- Log files
- Token-like strings in code
- Unsafe npm package contents
