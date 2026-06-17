# FinCLI v0.4.0

FinCLI is a modern financial CLI/TUI terminal for market research, technical analysis, AI-assisted analysis, provider management, portfolio risk, journaling, watchlists, and local-first financial workflows.

FinCLI is an active MVP. Data quality depends on provider availability, API keys, provider plan entitlement, exchange coverage, and rate limits. yfinance remains the default delayed fallback.

## Highlights

- Textual + Rich terminal UI with slash commands.
- Research-first workflow through `/research`.
- Provider fallback chain with granular reliability labels: `ok`, `auth_failed`, `rate_limited`, `entitlement_missing`, `partial_data`, `schedule_only`, `unavailable`.
- Provider metrics dashboard with runtime success rate, average latency, fallback count, and error count.
- Persistent provider metrics in SQLite so `/provider metrics` can show current session and all-time call totals.
- AI Grounding Guard for `/analyze`: AI prompts must consider data quality, provider reliability, missing data, and provider metrics before conclusions.
- Market data adapters: yfinance, Finnhub, Twelve Data, Alpha Vantage, and custom provider schema.
- 100+ news connector catalog with free RSS fallbacks and API-key-ready providers.
- AI providers: OpenRouter, OpenAI, Groq, Together, HuggingFace, Gemini, Anthropic, and compatible HTTP providers.
- Technical analysis: RSI, MACD, EMA/SMA, Bollinger Bands, ATR, support/resistance, market structure, and technical debate.
- Portfolio Risk v3: exposure by asset class/currency, concentration risk, drawdown estimate, risk budget, realized/unrealized PnL, and portfolio health score.
- Local-first storage: config, secrets, SQLite database, cache, sessions, watchlist, portfolio, journal, alerts.
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

## Research Engine v2

`/research` is the central research command. It returns a compact output:

- Snapshot
- Signal
- Risk
- Missing Data
- Source Quality
- Decision Points
- Final Summary

Deep mode sends a concise Research Engine v2 prompt to the active AI provider. Report mode adds report-oriented notes without creating another command surface.

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

### v0.4

- Strategy builder.
- Alert daemon and notification integrations.
- Backtesting with fees, slippage, and position sizing.
- Optional cloud sync.
- Plugin marketplace-style connector loading.
- Realtime streaming where provider plans support it.

## License

MIT
