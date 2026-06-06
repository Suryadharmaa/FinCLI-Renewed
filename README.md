# FinCLI v0.2.0

FinCLI is a modern financial CLI/TUI terminal for market monitoring, technical analysis, AI-assisted research, portfolio tracking, watchlists, trading journals, and configurable market/news provider workflows.

Current status: FinCLI is an active MVP moving into v0.2 with a Textual TUI, provider chain, symbol normalization, AI assistance, web research, portfolio, journal, watchlist, exports, and local session history.

- Single-column Textual TUI with an inline command palette and scrollable command suggestions. The old sidebar has been removed so market output has more room.
- Slash command router for the core FinCLI v0.1 command system.
- Config system using optional `.env` values for local development, `~/.fincli/config.json` for non-secret preferences, and `~/.fincli/secrets.env` for API keys saved from commands.
- SQLite local storage for watchlist, portfolio, journal, transactions, session history, and persistent market cache.
- yfinance fallback for quote, OHLCV history, news, Yahoo tables, and fundamental snapshots.
- Finnhub provider for quotes, stock candles, company news, company profile, and economic calendar via `FINNHUB_API_KEY`.
- Twelve Data provider for multi-asset market data via `TWELVE_DATA_API_KEY`.
- Alpha Vantage provider for stock/FX quote, daily history, news sentiment, and company overview via `ALPHA_VANTAGE_API_KEY`.
- Symbol search and provider-specific normalization with `/symbol`.
- Provider entitlement and realtime/delayed labeling with `/provider entitlement`.
- Economic calendar through Finnhub when an API key is configured, with a local fallback when the provider is unavailable.
- Technical analysis: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, support/resistance, volume, trend bias, and technical signal scoring.
- Market structure analysis: HH/HL, LH/LL, break of structure, change of character, liquidity areas, and risk zones.
- Technical Debate engine for `/technical`: Bull Chooser, Bear Chooser, Caution Chooser, and Judge.
- Watchlist scanner: `/scan watchlist` with filters such as `rsi<30`, `rsi>70`, and `trend=bullish`.
- Persistent market cache for quote, OHLCV history, news, and fundamentals to reduce unnecessary API calls.
- `/ai` and `/analyze` use the active AI provider. `/ai` has a FinCLI-specific persona, anti-coding guardrails, optional market context, and optional web research context.
- AI HTTP clients for OpenAI-compatible APIs, Gemini, and Anthropic. OpenRouter, OpenAI, Together, Groq, and HuggingFace use OpenAI-compatible request flows.
- Portfolio view calculates current price, PnL, PnL percent, allocation, and transaction-ledger performance.
- Portfolio and journal export to CSV or JSON.
- Basic tests for command registry, router, config, storage, market providers, technical analysis, AI commands, TUI selectors, web research, and session history.

## Stack

- Python 3.11+
- Textual + Rich for the terminal UI
- SQLite for local storage
- python-dotenv for optional local `.env` support
- yfinance for fallback market/news/fundamental data
- httpx for provider APIs and lightweight web research
- pandas + numpy for analysis workflows
- pytest for tests
- npm wrapper for global installation through `npm install -g`

Textual was chosen because FinCLI needs an interactive terminal dashboard instead of a static CLI. Rich is still used for tables, panels, Markdown rendering, and structured output.

## Install

For local development:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Alternative:

```bash
pip install -r requirements.txt
```

## Global Install

The recommended Python CLI approach is `pipx`, because FinCLI dependencies are installed in an isolated environment while the `fincli` command remains globally available:

```bash
pip install pipx
pipx ensurepath
pipx install .
fincli
```

If the Python package is published to PyPI:

```bash
pipx install fincli
fincli
```

FinCLI also ships with an npm wrapper so users can follow a common "install once, run anywhere" CLI pattern:

```bash
npm install -g @drico2008/fincli
fincli
```

For local npm testing before publishing:

```bash
npm install -g .
fincli
```

Note: the npm wrapper still requires Python 3.11+ during installation. The postinstall script creates a local `.npm-python` virtual environment inside the installed package, installs the Python FinCLI package there, and the global `fincli` command runs `python -m fincli.app.main`.

## Setup

For local development, you may copy `.env.example`:

```bash
copy .env.example .env
```

Only fill API keys for providers you want to use. The yfinance fallback does not require an API key. FinCLI never prints full API keys in the terminal.

For global npm installs, users do not need to open the installed package folder or edit `.env`. Save API keys directly from FinCLI:

```text
/ai_model key groq <api_key>
/ai_model key openrouter <api_key>
/news_model key finnhub <api_key>
/news_model key twelvedata <api_key>
/news_model key custom <api_key> https://your-market-api.example.com
```

Keys are saved locally at:

```text
~/.fincli/secrets.env
```

The file is not printed in full by FinCLI. `/config` and `/provider key status` only show masked key status and safe source labels.

## Run

```bash
fincli
```

Or:

```bash
python -m fincli.app.main
```

## Main Commands

```text
/help
/dashboard
/config
/ai_model
/ai_model openrouter openai/gpt-4o-mini
/ai_model key groq <api_key>
/news_model
/news_model key finnhub <api_key>
/news_model key alphavantage <api_key>
/symbol XAUUSD
/symbol normalize BBRI
/market AAPL 1d
/provider status
/provider list
/provider entitlement
/provider test AAPL
/provider key status
/watchlist
/watchlist add AAPL
/watchlist remove AAPL
/portfolio
/portfolio add BTC-USD 0.05 65000
/portfolio remove BTC-USD
/portfolio performance
/tx add buy AAPL 10 185
/tx add sell AAPL 5 195
/tx list
/journal
/journal add BTC-USD bullish "Failed breakout, wait for confirmation"
/journal stats
/journal review
/alert
/alert add AAPL above 200
/alert check
/history
/history sessions
/history show <session_id>
/history save "Morning market research"
/history delete <session_id>
/quote AAPL
/technical BTC-USD 1d
/technical XAUUSD 1d
/technical EURUSD 1d
/mtf AAPL 1d,1h,15m
/backtest AAPL sma_cross 1d
/backtest EURUSD rsi_reversion 1h
/structure BTC-USD 1d
/news AAPL
/web why is the rupiah weakening today
/web sources why is the rupiah weakening today
/funda MSFT
/yahoo BBRI history 6mo 1d
/yahoo BBRI statistics
/yahoo BBRI profile
/yahoo BBRI financials
/yahoo BBRI analysis
/yahoo BBRI holders
/ai explain today's market risk
/analyze ETH-USD 4h
/scan watchlist rsi<30
/scan watchlist trend=bullish
/scan watchlist rsi>60 trend=bullish
/scan export csv scan.csv rsi<30 1d
/report market AAPL md report.md
/report market AAPL json report.json
/calendar
/calendar today
/calendar 2026-06-05 2026-06-12 country=US impact=high
/calendar export csv calendar.csv week US high
/export portfolio json C:\Users\MSI\Desktop\portfolio.json
/export journal csv C:\Users\MSI\Desktop\journal.csv
/cache stats
/cache clear
/clear
/exit
```

`/market`, `/quote`, `/technical`, `/structure`, `/news`, and `/funda` use the active provider chain. `/ai` and `/analyze` use the active AI provider from `/ai_model`. `/analyze` sends indicator, market structure, news, and fundamental context to the AI prompt. `/ai` can also attach quote, OHLCV/technical, structure, news, fundamental, and web context when the prompt asks for current information or mentions a clear symbol such as `AAPL`, `EURUSD`, or `XAUUSD`.

## AI Chat UX

Inside the TUI, regular input without a slash is treated as chat to the active AI assistant:

```text
hello
```

Output is rendered as a terminal chat:

```text
> hello
> Thinking: routing prompt to active AI provider...
* Provider: ...
```

Explicit command mode is still supported:

```text
/ai explain today's market risk
```

The FinCLI assistant is customized for market workflows:

- It understands FinCLI as a financial terminal dashboard.
- It supports free chat for general questions, market research, portfolio workflows, journal review, provider setup, and risk analysis.
- It refuses coding, debugging, refactoring, and software-building requests inside the FinCLI assistant so the in-app assistant remains focused.
- If a prompt includes a clear market symbol, FinCLI attaches market context from the active provider chain before calling the AI provider.
- If a prompt needs recent public information, FinCLI can collect lightweight web context and pass it to the AI prompt.
- It never exposes API keys and never claims realtime data when the active provider is delayed or fallback-only.

Examples:

```text
what caused the rupiah to weaken today
latest BI rate news and possible impact on IHSG
```

Web research summarized by AI:

```text
/web why is the rupiah weakening today
/web gold price and dollar index update
```

Raw web sources without AI synthesis:

```text
/web sources why is the rupiah weakening today
```

FinCLI uses lightweight HTTP web research, not Chrome automation. This is more stable for global npm installs and does not open a browser in the background. Web-based output should still be verified because source quality can vary.

## Interactive AI Model Selector

```text
/ai_model
```

In the TUI, this opens a modern CLI-style selector:

- Select Provider
- Show current/configured provider status
- Use existing configuration or configure again
- Enter API key from the popup when the provider has no key
- Select Model
- Search model/provider
- Navigate with `up/down`, `Enter`, `Tab`, and `Esc`

Set a provider/model directly:

```text
/ai_model openrouter openai/gpt-4o-mini
```

Save a key directly:

```text
/ai_model key openrouter <api_key>
```

## Interactive Market/News Provider Selector

```text
/news_model
```

In the TUI, this opens a selector for market/news providers and fallback priority:

- Select Market/News Provider
- Choose `Twelve Data`, `Finnhub`, `Alpha Vantage`, `Custom API`, or `Yahoo Finance`
- Enter API keys directly from the popup when needed
- Choose a fallback preset: recommended, primary + yfinance, data API priority, or yfinance only
- Search provider/preset
- Navigate with `up/down`, `Enter`, `Tab`, and `Esc`

Practical default:

```text
Primary: twelvedata
Fallback: twelvedata -> finnhub -> custom -> yfinance
```

`yfinance` remains a free delayed/fallback provider. API providers such as Twelve Data, Finnhub, and Alpha Vantage depend on API key, plan, exchange entitlement, and rate limits.

## Economic Calendar

```text
/calendar
/calendar today
/calendar week US high
/calendar 2026-06-05 2026-06-12 country=US impact=high
/calendar export csv calendar.csv week US high
```

When `FINNHUB_API_KEY` is configured, FinCLI pulls actual economic calendar data from Finnhub. If the key is missing or the provider fails, FinCLI shows a local fallback list of important event categories such as central bank decisions, inflation releases, labor data, GDP/PMI, and retail sales. The fallback does not claim actual event dates.

Calendar output includes impact summary counts. `/calendar export` writes filtered events to CSV or JSON.

## Market Cache

FinCLI uses two cache layers:

- Runtime memory cache for repeated commands in the same TUI session.
- Persistent SQLite cache in `~/.fincli/fincli.db` for quotes, OHLCV history, news, and fundamentals.

Cache TTL follows `cache_ttl_seconds` from config. This reduces rate-limit pressure, speeds up watchlist/scanner workflows, and makes provider fallback more efficient.

Commands:

```text
/cache stats
/cache clear
```

`/cache clear` removes runtime cache and persistent market cache. API keys stay safe because market cache stores provider responses, not secrets.

## Dashboard

```text
/dashboard
```

The dashboard is designed as a compact first screen, not a stacked wall of panels. It includes:

- Provider chain
- Watchlist price snapshot
- Portfolio market value and PnL
- Journal win rate
- Command hints for next steps

## Market Overview

Use `/market` as a professional entry point for a symbol:

```text
/market AAPL 1d
```

Output includes:

- Data Quality score
- Quote and provider status
- RSI, trend, MACD, ATR
- Support/resistance
- Market structure
- Fundamental snapshot
- Latest news
- Disclaimer

Use `/market` before moving into `/technical`, `/structure`, or `/analyze`.

## Instrument Coverage

Coverage depends on provider and symbol format:

- `yfinance`: stocks, ETFs, indices, forex, crypto, commodities, and mutual funds as long as Yahoo supports the symbol.
- `custom`: any instrument your API exposes through the FinCLI custom provider schema.
- `finnhub`: stock quotes/candles, forex candles, crypto candles, company news, company profile, and economic calendar depending on API plan.
- `twelvedata`: multi-asset stocks, forex, ETFs, indices, commodities, and crypto with more consistent global market symbol formatting.
- `alphavantage`: stocks and FX quote/history plus news sentiment and company overview, with strict free-plan rate limits.

Recommended provider priority for multi-asset usage:

```text
/provider priority twelvedata,finnhub,yfinance
```

With that setup:

- `twelvedata` is tried first for forex, indices, commodities, and global stocks.
- `finnhub` is used as fallback for stocks and selected news/fundamental data.
- `yfinance` remains the free delayed fallback if API providers fail.

Example yfinance symbols:

```text
AAPL
MSFT
SPY
^GSPC
BTC-USD
ETH-USD
EURUSD=X
GC=F
CL=F
```

FinCLI accepts common aliases and maps them into provider-specific formats:

```text
EURUSD   -> EURUSD=X for yfinance, EUR/USD for Twelve Data, OANDA:EUR_USD for Finnhub forex candles
XAUUSD   -> XAUUSD=X for yfinance, XAU/USD for Twelve Data
SPX      -> ^GSPC for yfinance
NASDAQ   -> ^IXIC for yfinance
DAX      -> ^GDAXI for yfinance
NIKKEI   -> ^N225 for yfinance
WTI      -> CL=F for yfinance
BRENT    -> BZ=F for yfinance
```

## Technical AI Summary

`/technical` includes a structured summary designed for AI assistance:

```text
/technical EURUSD 1d
/technical XAUUSD 1d
/technical SPX 1d
```

Output includes trend bias, RSI, MACD, support/resistance, ATR, market structure summary, signal, and risk notes. The signal is rule-based and transparent:

```text
Signal: BEST TO BUY | BEST TO SELL | CAUTION
Signal Score
Confidence
Signal Reasoning
Signal Risk Notes
Invalidation / Caution Level
```

The signal is not a guaranteed entry instruction. FinCLI uses scenario language, confirmation, invalidation, and risk notes instead of profit claims.

`/technical` also uses `Technical Debate`:

- `Bull Chooser`: finds buy-candidate arguments.
- `Bear Chooser`: finds sell-candidate arguments.
- `Caution Chooser`: finds conflicts, overextension, volatility risk, and weak confirmation.
- `Judge`: decides the final `BEST TO BUY`, `BEST TO SELL`, or `CAUTION`.

The debate result is also included in AI prompts so the assistant does not reason from only one side.

```text
/analyze EURUSD 1d
```

## Multi-Timeframe Analysis

```text
/mtf AAPL
/mtf EURUSD 1d,1h,15m
/mtf XAUUSD 1d,4h,1h
```

`/mtf` fetches multiple timeframes through the active provider chain, summarizes trend/structure/RSI/MACD/key levels for each timeframe, and returns an alignment label such as `aligned bullish`, `mostly bearish`, or `mixed`. The default timeframe set is `1d,1h,15m` for yfinance compatibility. Use `4h` when the active provider supports it.

## Lightweight Backtesting

```text
/backtest AAPL sma_cross 1d
/backtest EURUSD rsi_reversion 1h
```

The v0.2 lightweight backtester supports educational long-only rule-based strategies:

- `sma_cross`: enters on fast/slow SMA bullish cross and exits on bearish cross.
- `rsi_reversion`: enters below RSI 30 and exits above RSI 55.

Output includes candles, trades, total return, win rate, max drawdown, exposure, latest trade, and risk notes. The backtest ignores fees, slippage, spreads, liquidity, and execution constraints.

## Scanner

Examples:

```text
/scan watchlist
/scan watchlist rsi<30
/scan watchlist rsi>70
/scan watchlist trend=bullish
/scan watchlist trend=bearish 1d
/scan watchlist rsi>60 trend=bullish
/scan export csv scan.csv rsi<30 1d
/scan export json scan.json trend=bullish 1d
```

The scanner fetches history asynchronously in limited batches, calculates indicators, and only displays symbols that match the filter.

Scanner exports write matched scan rows from the current watchlist to CSV or JSON.

## Exportable Market Reports

```text
/report market AAPL md report.md
/report market AAPL json report.json
```

Market reports reuse the `/market` overview pipeline and export quote, data quality, technicals, market structure, fundamentals, latest news, and disclaimer to Markdown or JSON.

## Portfolio Transaction Ledger

Use the transaction ledger for more serious portfolio tracking:

```text
/tx add buy AAPL 10 185
/tx add sell AAPL 5 195
/tx list
/portfolio performance
```

Buy transactions update quantity and average price. Sell transactions reduce position size and record realized PnL. `/portfolio performance` shows cost basis, market value, unrealized PnL, realized PnL, and total PnL.

## Journal Analytics

```text
/journal stats
/journal review
```

`/journal stats` calculates total entries, wins/losses, win rate, dominant instrument, dominant emotion, and top tags. `/journal review` sends journal statistics and recent entries to the active AI provider for process review, repeated mistake detection, risk notes, and habit improvement. Output includes a non-financial-advice disclaimer.

## Session History

```text
/history
/history sessions
/history show <session_id>
/history save "Morning market research"
/history delete <session_id>
/history clear current
```

FinCLI stores local session events in SQLite so users can review previous terminal sessions. API key commands are redacted before being saved.

## Price Alerts

```text
/alert
/alert add AAPL above 200
/alert add EURUSD below 1.0800
/alert check
/alert remove <id>
```

Alerts are stored locally in SQLite. v0.2.0 checks alerts manually with `/alert check` using the active quote provider. Triggered alerts are marked inactive. This is not a background notification daemon yet.

## AI Providers

Supported provider keys:

- `openrouter`: `OPENROUTER_API_KEY`
- `openai`: `OPENAI_API_KEY`
- `groq`: `GROQ_API_KEY`
- `together`: `TOGETHER_API_KEY`
- `huggingface`: `HUGGINGFACE_API_KEY`
- `gemini`: `GEMINI_API_KEY`
- `anthropic`: `ANTHROPIC_API_KEY`

Examples:

```text
/ai_model openrouter openai/gpt-4o-mini
/ai_model key openrouter <api_key>
/ai explain NVDA market risk briefly
/analyze AAPL 1d
```

API keys are never printed in full.

## Realtime vs Delayed Data

FinCLI uses yfinance as the default fallback. yfinance data is usually delayed and must not be described as realtime. API providers may provide realtime data only if the provider, subscription plan, and exchange entitlement support it.

FinCLI displays provider status as realtime, delayed, fallback, or unavailable whenever the provider exposes that status.

## Yahoo Finance Tables

FinCLI uses yfinance for global equities available on Yahoo Finance. For non-US stocks, use the Yahoo exchange suffix when known, such as `BBRI.JK`, `HSBA.L`, `SHOP.TO`, or `0700.HK`. For common IDX tickers such as `BBRI`, `BBCA`, `BMRI`, `TLKM`, and `ASII`, FinCLI automatically maps them to `.JK`.

Commands:

```text
/quote BBRI
/technical BBRI 1d
/analyze BBRI 1d
/yahoo BBRI history 6mo 1d
/yahoo BBRI news
/yahoo BBRI statistics
/yahoo BBRI profile
/yahoo BBRI financials
/yahoo BBRI balance
/yahoo BBRI cashflow
/yahoo BBRI analysis
/yahoo BBRI holders
```

Yahoo Finance URL examples:

```text
https://finance.yahoo.com/quote/BBRI.JK/
https://finance.yahoo.com/quote/BBRI.JK/news/
https://finance.yahoo.com/quote/BBRI.JK/key-statistics/
https://finance.yahoo.com/quote/BBRI.JK/history/
https://finance.yahoo.com/quote/BBRI.JK/profile/
https://finance.yahoo.com/quote/BBRI.JK/financials/
https://finance.yahoo.com/quote/BBRI.JK/analysis/
https://finance.yahoo.com/quote/BBRI.JK/holders/
```

Availability of news, analysis, holders, and financial tables depends on Yahoo coverage for the exchange/ticker.

## Finnhub Provider

Open the provider selector:

```text
/news_model
```

Environment variable:

```env
FINNHUB_API_KEY=your-finnhub-key
```

Or save it from FinCLI:

```text
/news_model key finnhub <api_key>
```

Finnhub endpoints used:

```text
GET /quote
GET /stock/candle
GET /forex/candle
GET /crypto/candle
GET /company-news
GET /stock/profile2
GET /calendar/economic
```

Finnhub provides REST/WebSocket data for stocks, currencies/forex, and crypto, plus fundamental/news data depending on plan. In FinCLI, news/fundamental support is strongest for equities; forex/crypto are mainly used for candles and technical analysis.

## Twelve Data Provider

Open the provider selector:

```text
/news_model
```

Environment variable:

```env
TWELVE_DATA_API_KEY=your-twelve-data-key
```

Or save it from FinCLI:

```text
/news_model key twelvedata <api_key>
```

Twelve Data endpoints used:

```text
GET /quote
GET /time_series
```

Twelve Data is useful for multi-asset symbols such as forex (`EURUSD`), metals (`XAUUSD`), global indices, ETFs, crypto, and popular US/Europe/Asia stocks. Always check provider plan and exchange entitlement for realtime vs delayed access.

## Alpha Vantage Provider

Open the provider selector:

```text
/news_model
```

Environment variable:

```env
ALPHA_VANTAGE_API_KEY=your-alpha-vantage-key
```

Or save it from FinCLI:

```text
/news_model key alphavantage <api_key>
```

Alpha Vantage functions used:

```text
GLOBAL_QUOTE
TIME_SERIES_DAILY_ADJUSTED
CURRENCY_EXCHANGE_RATE
FX_DAILY
NEWS_SENTIMENT
OVERVIEW
```

Alpha Vantage is useful as an additional stocks/FX adapter. Free plans are rate-limited, and realtime/delayed availability depends on provider plan and exchange coverage.

## Provider Commands

```text
/news_model
/provider list
/provider status
/provider test AAPL
/provider test finnhub AAPL
/provider key status
```

`/news_model` is the main TUI flow for selecting market/news providers and fallback priority. `/provider status` shows the active provider, fallback chain, and health message. `/provider test <symbol>` tests the active provider. `/provider test <provider> <symbol>` tests a specific provider without changing the active provider.

Manual commands such as `/provider use ...` and `/provider priority ...` are still available as advanced CLI fallback commands, but they are not the primary command-palette flow.

Example fallback chain saved by the selector:

```text
twelvedata -> finnhub -> custom -> yfinance
```

With this chain, FinCLI tries Twelve Data first. If it fails, it tries the next provider and finally uses delayed yfinance fallback.

## Symbol Search and Normalization

```text
/symbol apple
/symbol XAUUSD
/symbol normalize EURUSD
/symbol normalize BBRI
```

`/symbol` searches the local symbol catalog and displays provider-specific symbol mappings for yfinance, Twelve Data, Finnhub, and custom providers. `/symbol normalize <symbol>` works for any input and shows how FinCLI will normalize the symbol before sending it to each provider.

Examples:

```text
EURUSD -> EURUSD=X for yfinance, EUR/USD for Twelve Data, OANDA:EUR_USD for Finnhub
XAUUSD -> XAUUSD=X for yfinance, XAU/USD for Twelve Data
BBRI   -> BBRI.JK for yfinance
```

Normalization does not guarantee provider entitlement. Check `/provider entitlement` and your provider plan for realtime/delayed access and supported exchanges.

## Custom Market Provider

Open the provider selector:

```text
/news_model
```

Environment variables:

```env
MARKET_DATA_API_KEY=your-key
MARKET_DATA_BASE_URL=https://your-market-api.example.com
```

Or save from FinCLI:

```text
/news_model key custom <api_key> https://your-market-api.example.com
```

FinCLI calls:

```text
GET /quote/{symbol}
GET /history/{symbol}?period=6mo&interval=1d
GET /news/{symbol}?limit=5
GET /fundamentals/{symbol}
```

Headers are sent as `X-API-Key` and `Authorization: Bearer <key>`. API keys are not displayed in the terminal.

Quote payload example:

```json
{
  "symbol": "AAPL",
  "price": 123.45,
  "currency": "USD",
  "timestamp": "2026-06-04T12:00:00",
  "status": "realtime"
}
```

## Local Storage

FinCLI stores local data at:

```text
~/.fincli/config.json
~/.fincli/fincli.db
~/.fincli/fincli.log
~/.fincli/secrets.env
```

API keys are not stored in command output. For global npm installs, the main setup path is:

```text
/ai_model key groq <api_key>
/news_model key twelvedata <api_key>
```

Keys are stored in `~/.fincli/secrets.env`, automatically loaded for future FinCLI sessions, and do not need to be configured again. If a local `.env` contains an empty value, FinCLI still uses the saved local secret.

## Security Notes

- Do not commit `.env`.
- Do not publish `~/.fincli/secrets.env`.
- FinCLI masks keys in `/config` and `/provider key status`.
- Session history redacts `/ai_model key ...` and `/news_model key ...` commands.
- If an API key was ever exposed in a screenshot, npm package, log, or public repository, revoke and rotate it from the provider dashboard.

## Test

```bash
pytest
```

Latest local verification:

```text
113 passed
```

NPM wrapper check:

```bash
npm run check
npm pack --dry-run
```

## Troubleshooting

- `fincli` is not recognized: reinstall with `pip install -e .`, `pipx install .`, or `npm install -g .` from the project root.
- The TUI looks cramped: increase terminal size.
- API key is not detected: use `/ai_model key <provider> <api_key>` or `/news_model key <provider> <api_key>`, then check `/config` or `/provider key status`.
- `/quote` fails because yfinance is missing: run `pip install -e ".[dev]"` or `pip install -r requirements.txt`.
- Config is corrupted: delete `~/.fincli/config.json` to return to defaults.
- Market data fails for a symbol: check the symbol format for the active provider and try `/provider test <symbol>`.

## Roadmap v0.2

- More provider adapters. Alpha Vantage started in v0.2.0.
- Symbol search and provider-specific symbol normalization UI. Started in v0.2.0 through `/symbol`.
- Economic calendar improvements. Summary counts and export started in v0.2.0.
- Screener and scanner export. Scanner export started in v0.2.0 through `/scan export`.
- Lightweight backtesting. Started in v0.2.0 through `/backtest`.
- Alert system. Started in v0.2.0 through local price alerts and `/alert check`.
- Exportable market reports. Started in v0.2.0 through `/report market`.
- Multi-timeframe analysis. Started in v0.2.0 through `/mtf`.
- Stronger custom provider schema validation. Started in v0.2.0.
- Provider entitlement handling and realtime/delayed labeling improvements. Started in v0.2.0 through `/provider entitlement`.

## Roadmap v0.3

- Plugin system.
- Strategy builder.
- Advanced portfolio analytics.
- Notification integrations.
- Optional cloud sync.
- Realtime streaming where supported by provider plans.
