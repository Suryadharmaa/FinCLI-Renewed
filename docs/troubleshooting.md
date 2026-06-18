# FinCLI Troubleshooting

Common issues and solutions for FinCLI.

---

## Installation

### `fincli` command not found after npm install

The npm wrapper requires Python 3.11+ to be available on PATH.

**Solutions:**

1. Verify Python is installed and on PATH:
   ```bash
   python --version
   ```
2. Ensure Python 3.11+ is the default `python` (not `python3` only).
3. On Windows, check that Python was installed with "Add to PATH" selected.
4. Reinstall: `npm install -g @drico2008/fincli`
5. Try running directly: `python -m fincli`

### pip install fails with dependency errors

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
```

### FinCLI launches but shows errors immediately

Run the doctor command:

```
/doctor full
```

This checks Python version, database, providers, API keys, and command coverage.

---

## Provider Issues

### "No data returned" or "Provider unavailable"

1. Check provider status:
   ```
   /provider status
   /provider key status
   ```
2. Verify API key is set:
   ```
   /secrets status
   ```
3. Test a direct quote:
   ```
   /provider test AAPL
   ```
4. Check provider metrics for error counts:
   ```
   /provider metrics
   ```

### "auth_failed" status

Your API key is invalid or expired.

1. Verify the key at the provider's website.
2. Re-save the key:
   ```
   /news_model key finnhub <new_api_key>
   ```
3. Check the key status:
   ```
   /provider key status
   ```

### "rate_limited" status

You have exceeded the provider's rate limit.

1. Wait for the rate limit to reset (check provider docs).
2. Set up fallback providers:
   ```
   /provider priority finnhub,alphavantage,yfinance
   ```
3. Clear the cache to reduce redundant calls:
   ```
   /cache clear
   ```

### "entitlement_missing" status

Your API key/plan does not include access to the requested data.

1. Check entitlements:
   ```
   /provider entitlement
   ```
2. Upgrade your plan at the provider's website, or use a different provider.

### "circuit_open" status

The provider has failed multiple times and is temporarily disabled by the circuit breaker.

1. Wait for the cooldown period to expire (default: 60 seconds).
2. Check error details:
   ```
   /provider metrics
   ```
3. The circuit breaker resets automatically after the cooldown.

### yfinance data is delayed

yfinance is a delayed fallback by default. This is expected behavior.

1. For faster data, add a key-based provider:
   ```
   /news_model key finnhub <api_key>
   /provider priority finnhub,yfinance
   ```
2. yfinance data should never be described as realtime.

### Calendar shows "schedule_only" or fallback data

The Finnhub calendar endpoint requires a specific plan or may be rate-limited.

1. Check Finnhub plan entitlement at https://finnhub.io
2. Verify the key:
   ```
   /provider key status
   ```
3. Calendar fallback uses estimated event schedules. Verify critical events with official sources.

---

## AI Provider Issues

### "AI provider not ready" or AI commands fail

1. Check the current AI model:
   ```
   /ai_model
   ```
2. Set an AI provider and key:
   ```
   /ai_model key groq <api_key>
   /ai_model groq llama-3.3-70b-versatile
   ```
3. Test with a simple query:
   ```
   /ai hello
   ```

### AI responses are slow

1. Switch to a faster provider (Groq is typically fastest).
2. Use `--snapshot` mode instead of `--deep` for `/research`.

### AI gives generic or unhelpful answers

1. Set up your profile for better context:
   ```
   /profile set "Your Name" 10000 USD 1:100 2
   ```
2. Ensure market data providers are configured (AI grounding depends on data quality).
3. Use `/research --deep` for more thorough analysis.

---

## Data Quality

### Low data quality score

Check what data is missing:

```
/market AAPL 1d
```

The Data Quality line shows: quote, ohlcv, news, fundamentals, and missing fields.

Common fixes:

- **Missing news:** Set up news providers (`/news_model key ...`).
- **Missing fundamentals:** Ensure a market provider with fundamentals is active.
- **Missing quote:** Check provider status and API key.

### Trust Gate blocks AI conclusions

The Data Trust Gate limits AI confidence when data quality is low.

```
/market AAPL 1d   -- shows trust gate details
/provider status  -- shows provider health
```

Improve trust by:

1. Setting up multiple providers with fallback.
2. Ensuring API keys are valid.
3. Checking `/provider metrics` for success rates.

---

## Portfolio and Trading

### Paper order rejected by risk guard

The risk guard blocks orders that exceed safety limits.

1. Check risk status:
   ```
   /trading risk
   ```
2. Common reasons:
   - **Kill switch active:** Use `/trading resume`
   - **Position too large:** Reduce quantity.
   - **Daily loss limit hit:** Wait until next session or adjust via `/profile`.
3. Check risk configuration:
   ```
   /trading risk
   /profile
   ```

### Portfolio shows "N/A" prices

The market provider could not return a quote for the symbol.

1. Test the symbol:
   ```
   /provider test <SYMBOL>
   ```
2. Check symbol normalization:
   ```
   /symbol resolve <SYMBOL>
   ```
3. Ensure the provider supports the asset class.

### Portfolio risk shows warnings

Warnings indicate concentration, drawdown, or diversification issues.

1. Review risk details:
   ```
   /portfolio risk
   ```
2. Add positions to diversify:
   ```
   /portfolio add <SYMBOL> <qty> <price>
   ```
3. Check exposure breakdown in the risk table.

---

## Alerts

### Alerts not triggering

1. Check active alerts:
   ```
   /alert
   ```
2. Manually check alerts:
   ```
   /alert check
   ```
3. Start the background daemon:
   ```
   /alert daemon start
   ```
4. Verify the symbol has a working quote:
   ```
   /quote <SYMBOL>
   ```

### Alert daemon not running

```
/alert daemon status
/alert daemon start
```

The daemon checks alerts every 60 seconds by default.

---

## Cache and Performance

### Stale data displayed

Clear the cache:

```
/cache clear
/cache stats
```

### Commands feel slow

1. Check provider latency:
   ```
   /provider metrics
   ```
2. Reduce provider timeout (if using slow providers).
3. Use yfinance as a fast fallback:
   ```
   /provider priority yfinance
   ```

---

## Session History

### Lost session data

```
/history sessions
/history show <session_id>
```

Session history persists in the local database. If all history is lost:

1. Check database health:
   ```
   /doctor full
   ```
2. The database file is at `~/.fincli/fincli.db`.

---

## Privacy and Security

### How to clear all local data

```
/privacy purge
```

This clears: secrets, current session history, runtime cache, persistent market cache.

Portfolio, journal, alerts, and profile are preserved. To clear those too:

```
/portfolio remove <SYMBOL>   # for each position
/alert remove <ID>            # for each alert
/profile clear
/secrets clear
```

### Accidentally committed secrets

1. Immediately rotate the key at the provider's website.
2. Remove the file from git history:
   ```bash
   git rm --cached .env
   git rm --cached secrets.env
   ```
3. Add to `.gitignore` if not already present.
4. Run prepublish check:
   ```bash
   python scripts/prepublish_check.py
   ```

---

## NPM Package Issues

### `npm pack --dry-run` shows sensitive files

Run the prepublish checker:

```bash
python scripts/prepublish_check.py
npm run prepublish:safety
```

Ensure `.env`, `secrets.env`, `*.db`, `*.log`, and `__pycache__` are in `.gitignore` and `.npmignore`.

### Package install fails on clean machine

1. Verify Python 3.11+ is available.
2. Run: `npm run check`
3. Check the npm postinstall script for errors.
4. Try manual installation: `pip install -e ".[dev]"`

---

## Getting More Help

1. Run `/doctor full` for a comprehensive health check.
2. Run `/provider capabilities` to see which data each command needs.
3. Run `/config` to review your current settings.
4. Check the [command reference](commands.md) for correct syntax.
