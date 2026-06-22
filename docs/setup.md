# FinCLI Setup Guide

This guide covers API key configuration, provider setup, and first-run steps for FinCLI.

---

## Quick Start

After installing FinCLI, run through these steps:

```
/profile set "Your Name" 10000 USD 1:100 2
/ai_model key groq <your_groq_api_key>
/news_model key finnhub <your_finnhub_api_key>
/provider priority finnhub,yfinance
/research AAPL --snapshot
```

---

## API Key Setup

All API keys are stored in the operating system credential store through `keyring`. Keys are never printed in the terminal -- only masked values like `abcd...wxyz` are shown. A legacy `~/.fincli/secrets.env` file is migrated on first read and removed after the credential-store write is verified.

### AI Provider Keys

AI providers power `/ai`, `/analyze`, `/research --deep`, `/research --report`, and `/journal review`.

| Provider | Command | Website |
|----------|---------|---------|
| Groq (free tier) | `/ai_model key groq <api_key>` | https://console.groq.com |
| OpenRouter | `/ai_model key openrouter <api_key>` | https://openrouter.ai |
| OpenAI | `/ai_model key openai <api_key>` | https://platform.openai.com |
| Together | `/ai_model key together <api_key>` | https://api.together.xyz |
| HuggingFace | `/ai_model key huggingface <api_key>` | https://huggingface.co |
| Gemini | `/ai_model key gemini <api_key>` | https://aistudio.google.com |
| Anthropic | `/ai_model key anthropic <api_key>` | https://console.anthropic.com |

**Recommended free starting point:** Groq with `llama-3.3-70b-versatile` (fast, free tier available).

To switch AI provider/model:

```
/ai_model groq llama-3.3-70b-versatile
/ai_model openrouter openai/gpt-4o-mini
```

### Market Data Provider Keys

Market providers power quotes, technical analysis, history, news, fundamentals, and calendar.

| Provider | Command | Website | Notes |
|----------|---------|---------|-------|
| Finnhub | `/news_model key finnhub <api_key>` | https://finnhub.io | Free tier: US stocks, forex, crypto, news, calendar, insider, IPO |
| Twelve Data | `/news_model key twelvedata <api_key>` | https://twelvedata.com | Free tier: 800 requests/day |
| Alpha Vantage | `/news_model key alphavantage <api_key>` | https://www.alphavantage.co | Free tier: 25 requests/day |
| yfinance | No key needed | -- | Default delayed fallback, always available |
| Custom | `/news_model key custom <api_key> <base_url>` | -- | For self-hosted market data APIs |

**Recommended starting point:** Finnhub (free tier covers stocks, forex, crypto, news, calendar, insider, IPO).

### News Provider Keys

News providers power `/news` and news context in `/research` and `/analyze`.

| Provider | Command | Website |
|----------|---------|---------|
| Marketaux | `/news_model key marketaux <api_key>` | https://marketaux.com |
| NewsData.io | `/news_model key newsdata <api_key>` | https://newsdata.io |
| Finnhub | `/news_model key finnhub <api_key>` | https://finnhub.io |
| Custom News | `/news_model key custom_news <api_key> <base_url>` | -- |

Free RSS-based news providers (no key needed): `google_news_rss`, `yahoo_finance_rss`, `yfinance`.

### Default News Fallback Chain

FinCLI uses a fallback chain for news. Set the priority order:

```
/news_model priority google_news_rss,yfinance,marketaux
```

Set a specific primary:

```
/news_model use google_news_rss
```

Browse available connectors:

```
/news_model list
/news_model search rss
```

---

## Provider Priority

FinCLI tries market providers in order and falls back automatically when one fails. Set the priority:

```
/provider priority finnhub,yfinance
/provider priority twelvedata,alphavantage,yfinance
```

Check current status:

```
/provider status
/provider metrics
/provider key status
/provider capabilities
/provider entitlement
```

---

## User Profile

The profile configures risk-context analysis for `/analyze` and portfolio risk calculations.

```
/profile set "Your Name" <equity> <currency> <leverage> <years>
```

Example:

```
/profile set "Budi" 35000 USD 1:100 1.5
```

Parameters:

- **Name:** Display name.
- **Equity:** Total portfolio equity in the specified currency.
- **Currency:** Base currency (USD, IDR, EUR, etc.).
- **Leverage:** Trading leverage (e.g., `1:100`, `1:50`, `1:1`).
- **Years:** Years of investment/trading experience.

---

## Verify Setup

Run the doctor command to check your configuration:

```
/doctor
/doctor full
/doctor full --live AAPL
```

This checks:

- Python version and environment
- Database connectivity
- Provider configuration and health
- API key status
- Command coverage
- Capability matrix
- Optional live quote verification

---

## Secrets Management

View stored secrets (values masked):

```
/secrets status
```

Clear all secrets:

```
/secrets clear
```

Full privacy purge (secrets + session history + cache):

```
/privacy status
/privacy purge
```

---

## Local Storage Locations

All data is stored locally under `~/.fincli/`:

| File | Content |
|------|---------|
| `~/.fincli/config.json` | User preferences and settings |
| OS credential store | API keys managed by `keyring` |
| `~/.fincli/fincli.db` | SQLite database (portfolio, journal, watchlist, alerts, metrics, etc.) |
| `~/.fincli/fincli.log` | Application log |

---

## First Research

After setup, test your configuration:

```
/research AAPL --snapshot
/market AAPL 1d
/news AAPL
/technical AAPL 1d
/analyze AAPL 1d
```

If data is missing or delayed, check `/provider status` and `/provider key status`.

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for common issues and solutions.
