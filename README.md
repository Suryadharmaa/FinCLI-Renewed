# FinCLI v1.5.1

[![npm version](https://img.shields.io/npm/v/@drico2008/fincli)](https://www.npmjs.com/package/@drico2008/fincli)
[![npm downloads](https://img.shields.io/npm/dm/@drico2008/fincli?label=npm%20downloads)](https://www.npmjs.com/package/@drico2008/fincli)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Node](https://img.shields.io/badge/Node.js-18+-green)
[![Socket Badge](https://badge.socket.dev/npm/package/@drico2008/fincli/1.0.5)](https://badge.socket.dev/npm/package/@drico2008/fincli/1.0.5)

FinCLI is a production-ready financial CLI/TUI terminal for market research, technical analysis, AI-assisted analysis, provider management, portfolio risk, journaling, watchlists, backtesting, paper trading, and local-first financial workflows.

Data quality depends on provider availability, API keys, provider plan entitlement, exchange coverage, and rate limits. yfinance remains the default delayed fallback.

## Terminal Preview

![FinCLI startup dashboard](img/image.png)

## Highlights

- Textual + Rich terminal UI with slash commands.
- Research-first workflow through `/research`, powered by Research Engine v3 (snapshot/deep/report, cited sources, sector/macro/news blending, web fallback).
- Provider System v2: formal capability declarations, `ProviderResponse` envelope with quality scoring (0-100), per-operation metrics, manual circuit breaker reset via `/provider reset`.
- **Live Trading**: Real broker integration with Alpaca (paper + live) and Binance (crypto). Order confirmation, risk guard, kill switch.
- **AI Assistant**: Context-aware assistant with token-based sliding window (4k tokens), command knowledge, and response caching.
- **Terminal Charting**: ASCII candlestick charts with RSI/MACD overlays via `/chart`.
- **Notification Webhooks**: Discord and Telegram alert notifications.
- **Universe-Wide Screener**: Scan sp500, nasdaq, crypto, forex, commodities universes with filter expressions.
- **Multi-Portfolio**: Create, switch, compare multiple named portfolios.
- **WebSocket Reconnect**: Automatic reconnection with exponential backoff + jitter for realtime streams.
- **Config Validation**: Schema validation with "did you mean?" suggestions for typos.
- **Proactive Health Warnings**: Provider latency and error rate monitoring with automatic alerts.
- **ASCII Equity Curve**: Visual backtest performance chart.
- **Session Recovery**: Auto-save state every 60 seconds. Instant resume after crash.
- **Security Hardening**: Broker key encryption (PBKDF2-SHA256), plugin sandbox with import whitelist, soft error detection.
- Provider fallback chain with granular reliability labels and circuit breaker visibility.
- Source quality and freshness scoring in `/research` and `/market`.
- Provider metrics dashboard with per-operation breakdown and persistent all-time storage.
- AI Grounding Guard: prompts consider data quality, provider reliability, missing data, and trust gate.
- Market data adapters: yfinance, Finnhub, Twelve Data, Alpha Vantage, and custom provider schema.
- 100+ news connector catalog with free RSS fallbacks.
- AI providers: OpenRouter, OpenAI, Groq, Together, HuggingFace, Gemini, Anthropic.
- Technical analysis: RSI, MACD, EMA/SMA, Bollinger Bands, ATR, support/resistance, market structure.
- Portfolio Risk v3: exposure, concentration, drawdown, risk budget, PnL, health score.
- Trading Safety Layer: risk guard, immutable audit log, paper trading, 3 algo strategies.
- Broker sandbox adapters and realtime streaming (Kraken, HyperLiquid, equity polling).
- Professional backtesting: fees/slippage, walk-forward, position sizing, Monte Carlo, export.
- Portfolio analytics: snapshots, risk ratios, rebalancing, benchmark comparison, what-if analysis.
- Alert daemon with conditional alerts and alert history.
- Streaming AI output with separate display container (no conversation history loss).
- Theme system with 7 presets and custom theme support (create, import, export).
- Error classification, crash context, and `/doctor report` for diagnostics.
- Plugin system with manifest validation, sandbox, and lifecycle hooks.
- Security: OS credential-store secrets, token pattern scanning, input validation, `/security scan`.
- Automated CI/CD: GitHub Actions tests on 3 OSes, auto-publish to npm/PyPI on tag.
- Session history with resume support.
- Local-first storage: SQLite database, OS credential-store secrets, cache, sessions, audit log.

---

## Installation Guide

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for npm wrapper only)

### Step 1: Install Python

Check if installed:

```bash
python --version
```

If not installed or version < 3.11:

**Windows:** Download from [python.org/downloads](https://www.python.org/downloads/). Check "Add Python to PATH".

**macOS:** `brew install python@3.12` or download from [python.org](https://www.python.org/downloads/).

**Linux (Ubuntu/Debian):** `sudo apt install python3.11 python3.11-venv python3-pip -y`

**Linux (Fedora):** `sudo dnf install python3.11 python3-pip -y`

**Linux (Arch):** `sudo pacman -S python python-pip`

### Step 2: Install Node.js (npm wrapper only)

**Windows/macOS:** Download LTS from [nodejs.org](https://nodejs.org/).

**Linux (Ubuntu/Debian):**
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs -y
```

### Step 3: Install FinCLI

**Option A: npm (recommended for users)**
```bash
npm install -g @drico2008/fincli
fincli setup
fincli
```

**Option B: pip (recommended for developers)**
```bash
git clone https://github.com/your-username/fincli.git
cd fincli
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
fincli
```

### Step 4: Verify

```bash
fincli
/help
/doctor
```

### Step 5: API Keys (Optional)

Interactive picker (recommended):
```text
/ai_model                           # Select AI provider and model interactively
/news_model                         # Select market/news provider interactively
```

Or set directly:
```text
/ai_model key groq <api_key>
/news_model key finnhub <api_key>
/news_model key twelvedata <api_key>
/news_model key alphavantage <api_key>
```

Free key sources: [Groq](https://console.groq.com/), [OpenRouter](https://openrouter.ai/), [Finnhub](https://finnhub.io/), [Twelve Data](https://twelvedata.com/), [Alpha Vantage](https://www.alphavantage.co/)

### Step 6: Live Trading (Optional)

For live trading with Alpaca:

```bash
# Set environment variables
export ALPACA_API_KEY=<your_key>
export ALPACA_SECRET_KEY=<your_secret>

# Or encrypt keys for secure storage
/security encrypt-key alpaca
```

Free paper trading: [Alpaca](https://alpaca.markets/)

---

## Quick Start

```text
/research AAPL              # Market snapshot
/research AAPL --deep       # AI deep analysis
/market AAPL 1d             # Quote + news + technical
/chart AAPL 1d --overlay rsi,macd  # ASCII candlestick chart
/portfolio add AAPL 10 185  # Track a position
/portfolio create crypto    # Create new portfolio
/scan sp500 rsi<30          # Scan S&P 500 for oversold stocks
/watchlist add AAPL         # Add to watchlist
/journal add AAPL bullish   # Log a trade idea
/alert add AAPL above 200   # Price alert
/history                    # Browse sessions
```

---

## Core Commands

Research and market:

```text
/research AAPL [--snapshot|--deep|--report] [--export md|json path]
/market AAPL 1d
/news AAPL
/technical AAPL 1d
/analyze AAPL 1d
/mtf AAPL 1d,1h,15m
/chart AAPL 1d [--overlay rsi,macd] [--width 80] [--height 20]
/calendar week US high
```

Providers:

```text
/provider status
/provider metrics
/provider capabilities
/provider reset <provider>
/provider key status
/provider key rotate <provider>
/provider test AAPL
```

Portfolio and risk:

```text
/portfolio
/portfolio add AAPL 10 185
/portfolio update AAPL 5 160       # DCA
/portfolio history                  # Snapshot history
/portfolio risk
/portfolio benchmark SPY
/portfolio rebalance                # Equal-weight rebalancing suggestions
/portfolio portfolios               # List all portfolios
/portfolio create crypto            # Create new portfolio
/portfolio switch crypto            # Switch active portfolio
/portfolio compare main             # Compare two portfolios
/portfolio delete crypto            # Delete portfolio (not main)
```

Live trading:

```text
/trading live status                # Connection status
/trading live connect alpaca paper  # Connect to Alpaca (paper mode)
/trading live connect alpaca live   # Connect to Alpaca (live mode)
/trading live buy AAPL 10 --confirm # Place buy order
/trading live sell AAPL 5 --confirm # Place sell order
/trading live positions             # Show broker positions
/trading live orders                # Show order history
/trading live account               # Show account info
/trading live disconnect            # Disconnect from broker
```

Trading safety:

```text
/trading kill                       # Emergency stop (blocks all orders)
/trading resume                     # Re-enable orders
/trading risk                       # Risk guard status
/trading audit                      # Order audit log
```

Workflow:

```text
/watchlist add AAPL [group] [notes]
/watchlist list <group>
/scan watchlist rsi<30
/scan sp500 rsi<30 --limit 20       # Scan S&P 500 universe
/scan crypto sma_cross              # Golden cross in crypto
/journal add AAPL bullish "setup"
/journal stats
/journal review
/alert add AAPL above 200
/history
```

Session management:

```text
/session save                       # Save current state
/session restore                    # Restore last unclean session
/session status                     # Show session state
```

AI assistant:

```text
/ai                                 # Show AI status
/ai What is RSI?                    # Ask a question
/ai How do I use /backtest?         # Command help
```

Themes:

```text
/theme list
/theme ocean
/theme create mytheme --base midnight
/theme import theme.json
/theme export midnight theme.json
```

Security:

```text
/security status                    # Security overview
/security scan                      # Token pattern scan
/security encrypt-key alpaca        # Encrypt broker API key
/security decrypt-key alpaca        # Decrypt broker API key
/security session                   # Session security status
/security lockdown                  # Emergency secret wipe
/security purge                     # Clear secrets, history, cache
```

Export:

```text
/export journal csv journal.csv
/export portfolio json portfolio.json
/export alerts csv alerts.csv
/export broker csv broker_trades.csv
/export all json ./exports
```

System:

```text
/doctor
/doctor report                      # Diagnostic dump (no secrets)
/setup                              # First-run wizard
/secrets status
/plugin list
/plugin validate
/cache stats
/cache clear
```

Notifications:

```text
/notification add discord alerts <webhook_url>    # Add Discord webhook
/notification add telegram alerts <bot_token> <chat_id>  # Add Telegram
/notification list                                # List configured targets
/notification test discord:alerts                 # Send test notification
/notification remove discord:alerts               # Remove target
```

---

## Research Engine v3

`/research` returns a compact, source-aware output:

- Snapshot, Signal, Risk, Context (sector + macro + news blend)
- Trust Gate, Missing Data, Source Quality, Decision Points
- Sources (cited market, news, macro, fundamentals, web)
- Final Summary

Modes: `--snapshot` (default), `--deep` (AI-powered), `--report` (report-oriented). Exports: `--export md|json`.

## Portfolio Risk v3

`/portfolio risk` calculates: exposure by asset class, currency exposure, concentration risk, drawdown estimate, risk budget, realized/unrealized PnL, portfolio health score.

## Live Trading

FinCLI supports live trading through broker integrations:

- **Alpaca**: US equity broker (paper + live trading)
- **Binance**: Crypto exchange (testnet + live trading)
- **Order Confirmation**: All live orders require `--confirm` flag
- **Risk Guard**: Same safety checks as paper trading
- **Kill Switch**: `/trading kill` blocks both paper AND live orders
- **Audit Log**: All orders logged immutably

Safety features:
- Position size limit (20% of equity)
- Daily loss limit (5% of equity)
- No leverage in paper mode
- Auto-disconnect on suspicious activity

## AI Assistant

The AI assistant understands FinCLI commands and features:

- Ask questions about market analysis, trading, portfolio
- Get help with FinCLI commands and features
- Conversation context (token-based sliding window, 4k tokens)
- Response caching (30-minute TTL, reduces API cost)
- Coding boundary (refuses programming questions)

## Session Recovery

FinCLI auto-saves session state every 60 seconds:

- Command buffer
- Output history (last 100 entries)
- Status bar state

On crash recovery:
- Detects unclean shutdown on startup
- Shows recovery summary
- `/session restore` to recover previous state

## Plugin System

Plugins extend FinCLI with custom commands:

- Manifest-based (`plugin.json`)
- Import whitelist (only safe modules allowed)
- Public API boundary (no direct filesystem/network access)
- Lifecycle hooks: `on_startup`, `on_shutdown`, `on_command`

Security:
- Blocked imports: `os`, `sys`, `subprocess`, `socket`, etc.
- Blocked calls: `exec()`, `eval()`, `open()`, etc.
- All data access through `FinCLIPluginAPI`

## Data Notes

- yfinance is delayed fallback, not realtime.
- Providers may require API keys and paid plans.
- AI output is informational, not financial advice.

## Local Storage

```text
~/.fincli/config.json
OS credential store          # API keys; legacy secrets.env migrates on first read
~/.fincli/fincli.db          # SQLite database
~/.fincli/themes/            # Custom themes
~/.fincli/plugins/           # Plugin directory
```

## Changelog

### v1.5.1
- Deep code review: 17 bug fixes across codebase
- Fix operator precedence in provider error classification
- Fix frozen dataclass mutability (lists → tuples)
- Fix AlertDaemon silent exception swallowing
- Fix RiskGuard net notional calculation (buy - sell)
- Translate all remaining Indonesian text to English
- Case-insensitive provider matching in news aggregator
- Remove deleted /quote command from verb map

### v1.5.0
- WebSocket reconnect logic with exponential backoff + jitter
- Config schema validation with "did you mean?" suggestions
- Proactive provider health warnings (latency, error rate)
- ASCII equity curve chart for backtest results
- Memory optimization (session cleanup, 7-day retention)
- Bug fixes: audit log cleanup, portfolio_name filter, metrics race condition

### v1.4.0
- Universe-wide screener (sp500, nasdaq, crypto, forex, commodities)
- Multi-portfolio support (create, switch, compare, delete)
- Binance crypto broker integration (testnet + live)
- Extended scan filters: sma_cross, sma_death, above_support, below_resistance

### v1.3.0
- Terminal charting: ASCII candlestick with RSI/MACD overlays
- AI context sliding window (token-based, 4k tokens)
- Notification webhooks: Discord and Telegram
- Interactive model picker for `/ai_model` and `/news_model`

### v1.2.0
- Session state auto-save and crash recovery
- Hash-based AI response cache (30-minute TTL)
- Soft error detection (staleness, price anomalies)
- Plugin sandbox hardening (import whitelist, code validation)
- Plugin public API (`FinCLIPluginAPI`)

### v1.1.0
- Live trading with Alpaca (paper + live)
- Broker key encryption (PBKDF2-SHA256)
- Command consolidation (removed 6 duplicates)
- AI conversation context (last 3 questions)
- `/portfolio rebalance` command
- `/export broker` command
- Session security status

### v1.0.5
- Research Engine v3
- Provider System v2
- Portfolio Risk v3
- Trading Safety Layer
- Plugin system
- Theme system

## License

MIT
