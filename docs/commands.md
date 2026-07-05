# FinCLI Command Reference

Complete command reference for FinCLI v1.8.5. All commands start with `/` and are entered in the TUI input.

---

## General

| Command | Description | Example |
|---------|-------------|---------|
| `/help` | Show help, command list, and examples. | `/help` |
| `/dashboard` | Show compact FinCLI dashboard. | `/dashboard` |
| `/clear` | Clear terminal output. | `/clear` |
| `/exit` | Exit the application. | `/exit` |
| `/config` | Show active configuration without revealing API keys. | `/config` |
| `/setup` | Show recommended first-run setup guide. | `/setup` |

---

## Research

### /research

The central research command. Produces a source-aware research brief with signal, risk, context, trust gate, sources, and summary.

**Modes:**

- `--snapshot` (default) -- compact deterministic brief from available provider data.
- `--deep` -- grounded Research Engine prompt sent to the active AI provider, obeying the Data Trust Gate confidence cap.
- `--report` -- structured Research Engine v4 report with verified facts, inferences, missing-data severity, bull/base/bear scenario matrix, citation IDs, source scoring, and trust-capped confidence.

**Export:** `--export md <path>` or `--export json <path>`

```
/research AAPL
/research AAPL --snapshot
/research AAPL --deep
/research AAPL --report
/research AAPL --report --export md report.md
/research AAPL --report --export json report.json
/research AAPL 1h
```

### /macro

Macro dashboard with fallback and connector-ready context.

```
/macro Indonesia
/macro United States
```

### Hidden Macro Aliases

Direct access to specific macro indicators via AlphaVantage. These are hidden from `/help` but available as shortcuts.

```
/cpi us
/nfp us
/gdp us
/gdp per capita us
/fed funds us
/inflation us
/unemployment us
```

---

## Market Data

### /market

Compact professional market overview: quote, technical, structure, news, fundamentals, data quality, and source quality.

```
/market AAPL 1d
/market XAUUSD 4h
/market BTC-USD 1w
```

### /quote

Quick quote/price lookup.

```
/quote AAPL
/quote BBRI
/quote XAUUSD
```

### /technical

Full technical analysis with RSI, MACD, EMA/SMA, Bollinger Bands, ATR, support/resistance, market structure, and a bull/bear technical debate.

```
/technical AAPL 1d
/technical BTC-USD 4h
/technical XAUUSD 1h
```

### /structure

Market structure analysis without the full technical panel. Shows trend, BOS (Break of Structure), CHoCH (Change of Character), liquidity areas, and risk zones.

```
/structure AAPL 1d
/structure ETH-USD 4h
```

### /mtf

Multi-timeframe technical alignment analysis. Supports up to 6 comma-separated timeframes.

```
/mtf AAPL 1d,1h,15m
/mtf BTC-USD 1w,1d,4h
/mtf XAUUSD 1d,4h,1h,15m,5m
```

### /news

News and fundamental headlines for an instrument. Supports lookback from 1d to 30d.

```
/news AAPL
/news TSLA 7d
/news BBRI 14d
```

### /funda

Compact fundamental snapshot (market cap, P/E, EPS, revenue, beta, sector, industry).

```
/funda AAPL
/funda BBRI
```

### /yahoo

Yahoo Finance table views. Sections: `history`, `statistics`, `profile`, `financials`, `balance`, `cashflow`, `analysis`, `holders`, `news`.

```
/yahoo AAPL statistics
/yahoo BBRI history 1y 1d
/yahoo AAPL profile
/yahoo AAPL financials
/yahoo AAPL holders
/yahoo AAPL news
```

### /calendar

Economic calendar with provider/fallback. Supports country and impact filtering.

```
/calendar week US high
/calendar today
/calendar 2024-01-01 2024-01-31 country=US impact=high
/calendar export csv calendar.csv week US high
/calendar export json calendar.json today
```

### /scan

Watchlist scanner with indicator filters and export.

```
/scan watchlist
/scan watchlist rsi<30
/scan watchlist rsi>70 1d
/scan watchlist trend=bullish
/scan export csv scan.csv rsi<30 1d
/scan export json scan.json rsi>70
```

### /symbol

Symbol search and provider-specific normalization.

```
/symbol search BBRI
/symbol search gold
/symbol resolve XAUUSD --asset commodity
/symbol resolve AAPL
```

---

## Analysis

### /analyze

AI-powered market structure analysis with grounding guard. Combines technical, structure, news, fundamentals, data quality, and provider reliability into a single AI analysis.

```
/analyze AAPL 1d
/analyze ETH-USD 4h
/analyze XAUUSD 1h
```

### /backtest

Professional backtesting engine with fees/slippage/spread modeling, walk-forward split, position sizing, Monte Carlo robustness, and export.

**Strategies:** `sma_cross`, `rsi_reversion`, `momentum`, `bollinger`, `multi_factor`

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--asset <class>` | Asset class | `equity` |
| `--equity <amount>` | Initial equity | `10000` |
| `--sizing <method>` | `fixed_fractional` or `kelly` | `fixed_fractional` |
| `--fraction <pct>` | Position fraction | `0.02` |
| `--monte-carlo` | Run Monte Carlo robustness | off |
| `--walk-forward` | Run walk-forward split | off |
| `--export <md\|json\|csv> <path>` | Export report | off |

```
/backtest AAPL sma_cross 1d
/backtest BTC-USD rsi_reversion 1d --monte-carlo
/backtest AAPL momentum 1d --walk-forward --sizing kelly
/backtest AAPL multi_factor 1d --monte-carlo --export md report.md
/backtest XAUUSD bollinger 4h --equity 50000 --fraction 0.05
```

---

## AI

### /ai

Free chat with the AI assistant. Automatically detects market symbols and provides market context.

```
/ai What are the risks of AAPL?
/ai Explain the current macro environment
/ai Compare AAPL vs MSFT fundamentals
```

### /ai_model

View or change the active AI provider/model. Save API keys.

```
/ai_model
/ai_model openrouter openai/gpt-4o-mini
/ai_model groq llama-3.3-70b-versatile
/ai_model key groq <api_key>
/ai_model key openrouter <api_key>
```

Supported providers: OpenRouter, OpenAI, Groq, Together, HuggingFace, Gemini, Anthropic.

### /agent

View AI agent framework (thinking lenses for research).

```
/agent list
/agent list value
/agent show buffett
```

---

## Trading

### /trading

Trading layer overview with risk guard status, broker catalog, paper trading, algo engine, and audit log.

```
/trading
```

### /trading paper

Paper trading orders. Local simulation only -- no live orders are sent.

```
/trading paper
/trading paper orders
/trading paper positions
/trading paper buy AAPL 10 market
/trading paper buy AAPL 5 limit 180
/trading paper buy AAPL 5 stop_limit 180 --stop 185
/trading paper sell AAPL 3 market
```

### /trading kill / /trading resume

Kill switch to block or re-enable all paper orders.

```
/trading kill
/trading resume
```

### /trading risk

Risk guard status, daily PnL, and configuration.

```
/trading risk
```

### /trading audit

Immutable order audit log.

```
/trading audit
/trading audit 100
```

### /trading cancel

Cancel a queued paper order by ID.

```
/trading cancel 5
```

### /trading positions

Aggregated paper trading positions.

```
/trading positions
```

### /trading brokers

Broker catalog and adapter status.

```
/trading brokers
/trading broker use Alpaca
/trading broker status
```

### /trading stream

Realtime connector stream status.

```
/trading stream
```

### /trading realtime

Realtime connector catalog (Kraken WebSocket, HyperLiquid WebSocket, Equity polling).

```
/trading realtime
```

### /trading algo

Algorithmic trading engine with built-in strategies.

```
/trading algo list
/trading algo run sma_cross AAPL 1d
/trading algo run rsi_reversion BTC-USD 4h 2
/trading algo run momentum AAPL 1d 5
```

---

## Portfolio

### /portfolio

Portfolio management and risk analytics.

```
/portfolio
/portfolio add AAPL 10 185
/portfolio add BTC-USD 0.05 65000
/portfolio remove AAPL
/portfolio performance
/portfolio risk
/portfolio chart
/portfolio snapshot
/portfolio whatif add AAPL 10 200
/portfolio benchmark SPY
```

### /portfolio risk

Portfolio Risk v3: exposure by asset class and currency, concentration risk, drawdown estimate, risk budget from profile, realized/unrealized PnL, and portfolio health score.

```
/portfolio risk
```

### /portfolio chart

Portfolio performance chart with Sharpe/Sortino/Calmar ratios from saved snapshots.

```
/portfolio chart
```

### /portfolio snapshot

Save a portfolio time-series snapshot for performance tracking.

```
/portfolio snapshot
```

### /portfolio whatif

What-if analysis: add or reduce a position and see the impact before committing.

```
/portfolio whatif add AAPL 10 200
/portfolio whatif sell AAPL 5 190
```

### /portfolio benchmark

Compare portfolio vs a benchmark (SPY, QQQ, BTC, etc.). Requires at least 2 saved snapshots.

```
/portfolio benchmark SPY
/portfolio benchmark QQQ
/portfolio benchmark BTC-USD
```

### /tx

Transaction ledger for buy/sell records with realized PnL tracking.

```
/tx list
/tx add buy AAPL 10 185
/tx add sell AAPL 5 195
/tx add buy BTC-USD 0.05 65000 USD
```

---

## Journal

### /journal

Trading/investment journal with stats and AI review.

```
/journal
/journal add AAPL bullish "Breakout confirmed above 190"
/journal add BTC-USD bearish "Failed to hold 70000"
/journal AAPL
/journal stats
/journal review
```

`/journal stats` shows win rate, top instrument, top tags.
`/journal review` sends journal data to AI for habit analysis.

---

## Watchlist

### /watchlist

Watchlist management.

```
/watchlist
/watchlist add AAPL
/watchlist add BTC-USD
/watchlist remove AAPL
```

---

## Alerts

### /alert

Local price alerts with conditional triggers and background daemon.

**Conditions:** `above`, `below`, `rsi_below`, `rsi_above`, `volume_above`, `macd_cross_up`, `macd_cross_down`

```
/alert
/alert add AAPL above 200
/alert add BTC-USD below 60000
/alert add AAPL rsi_below 30
/alert add AAPL volume_above 50000000
/alert add AAPL macd_cross_up 0
/alert remove 3
/alert check
/alert history
/alert daemon start
/alert daemon stop
/alert daemon status
```

---

## Provider

### /provider

Provider diagnostics, status, key management, fallback priority, and provider comparison.

Supported market providers: yfinance, Finnhub, Twelve Data, Alpha Vantage, Polygon.io, IEX Cloud, and custom REST providers.

```
/provider status
/provider metrics
/provider trust
/provider list
/provider capabilities
/provider entitlement
/provider key status
/provider key rotate polygon
/provider test AAPL
/provider use polygon
/provider priority polygon,yfinance
/provider compare AAPL
```

### /provider capabilities

Shows the command capability matrix: which data each command needs from providers.

```
/provider capabilities
```

### /provider trust

Shows provider trust level, latest provider result, fallback/circuit state, recent errors, cache status, and the AI confidence limit used for market/AI output.

```
/provider trust
```

---

## News Providers

### /news_model

News provider selector, connector catalog, and fallback management.

```
/news_model
/news_model list
/news_model search rss
/news_model search yahoo
/news_model use google_news_rss
/news_model priority google_news_rss,yfinance,marketaux
/news_model key marketaux <api_key>
/news_model key finnhub <api_key>
/news_model key custom_news <api_key> <base_url>
```

---

## Reports and Export

### /report

Export market report to Markdown or JSON.

```
/report market AAPL md report.md
/report market AAPL json report.json
/report market BTC-USD md btc_report.md 4h
```

### /export

Batch and individual data export.

```
/export journal csv journal.csv
/export journal json journal.json
/export portfolio csv portfolio.csv
/export portfolio json portfolio.json
/export alerts csv alerts.csv
/export all json ./exports
/export all csv ./exports
```

---

## Web Research

### /web

Web research helper using public sources.

```
/web why is the dollar strengthening
/web sources AAPL earnings
/web market outlook 2024
```

`/web sources <query>` shows raw search results without AI synthesis.

---

## Connector Catalog

### /connector

Data connector catalog for market, macro, and other data sources.

```
/connector list
/connector list macro
/connector search yahoo
/connector search crypto
```

---

## Plugins

### /plugin

Local plugin management.

```
/plugin list
/plugin status
```

Plugins are manifest-first in v1.8.5. Create `~/.fincli/plugins/<name>/plugin.json` to register.

---

## System

### /doctor

Health check for configuration, providers, database, and commands.

```
/doctor
/doctor full
/doctor full --live
/doctor full --live AAPL
```

`/doctor full` checks local wiring, command coverage, database/cache, provider configuration, and capability matrix.
`/doctor full --live AAPL` also verifies a live quote from the active provider.

### /cache

Cache management (runtime TTL cache and persistent market cache).

```
/cache stats
/cache clear
```

### /history

Session history management.

```
/history
/history sessions
/history show <session_id>
/history save "Morning research session"
/history delete <session_id>
/history clear current
/history clear all
```

---

## Security

### /secrets

API key status and management. Values are never printed.

```
/secrets status
/secrets clear
```

### /privacy

Privacy state and purge.

```
/privacy status
/privacy purge
```

`/privacy purge` clears secrets, current session history, runtime cache, and persistent market cache. Portfolio, journal, alerts, and profile are preserved.

---

## User Profile

### /profile

User gameplay profile for risk-context analysis.

```
/profile
/profile set "Budi" 35000 USD 1:100 1.5
/profile clear
```

Parameters: `<name>` `<equity>` `<currency>` `<leverage>` `<years_of_investment>`

The profile is used by `/analyze` for SL/TP and risk-context wording, and by `/portfolio risk` for risk budget calculations.

---

## Command Groups Summary

| Group | Commands |
|-------|----------|
| General | `/help`, `/dashboard`, `/clear`, `/exit`, `/config`, `/setup` |
| Research | `/research`, `/macro`, `/cpi`, `/nfp`, `/gdp`, `/fed funds`, `/inflation`, `/unemployment` |
| Market | `/market`, `/quote`, `/news`, `/funda`, `/yahoo`, `/calendar`, `/scan`, `/symbol` |
| Analysis | `/technical`, `/structure`, `/mtf`, `/analyze`, `/backtest` |
| AI | `/ai`, `/ai_model`, `/agent` |
| Trading | `/trading`, `/trading paper`, `/trading kill`, `/trading resume`, `/trading risk`, `/trading audit`, `/trading cancel`, `/trading positions`, `/trading brokers`, `/trading broker use`, `/trading broker status`, `/trading stream`, `/trading realtime`, `/trading algo list`, `/trading algo run` |
| Portfolio | `/portfolio`, `/portfolio add`, `/portfolio remove`, `/portfolio performance`, `/portfolio risk`, `/portfolio chart`, `/portfolio snapshot`, `/portfolio whatif`, `/portfolio benchmark`, `/tx` |
| Journal | `/journal`, `/journal add`, `/journal stats`, `/journal review` |
| Watchlist | `/watchlist`, `/watchlist add`, `/watchlist remove` |
| Alert | `/alert`, `/alert add`, `/alert remove`, `/alert check`, `/alert history`, `/alert daemon` |
| Provider | `/provider`, `/provider status`, `/provider metrics`, `/provider trust`, `/provider list`, `/provider capabilities`, `/provider entitlement`, `/provider key status`, `/provider key rotate`, `/provider test`, `/provider compare`, `/news_model`, `/connector` |
| Export | `/report`, `/export` |
| Web | `/web` |
| System | `/doctor`, `/cache`, `/history`, `/plugin` |
| Security | `/secrets`, `/privacy` |
| Profile | `/profile` |
