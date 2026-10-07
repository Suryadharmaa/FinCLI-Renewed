# FinCLI 3.0.0 connected workspace

## Running and upgrading

Install from this checkout with `python -m pip install -e ".[dev,web]"`, then run `fincli` and `/web start`. The Windows app uses the same local static UI and authenticated FastAPI backend. Build it with `scripts/build_desktop.ps1`. No v3 binary is bundled by this source change and no release tag is created automatically.

Existing portfolios, transactions, settings and sessions are preserved. Four `workspace_*` SQLite tables are created additively on first use for layouts, documents, runs and saved filters. Package, Python and desktop source versions are 3.0.0. The previous desktop API remains compatible; workspace results carry contract `3.0`.

## Connected panels

Research, Trading, Portfolio and Macro layouts are provided. Choose 1–8 panels, retain up to 12 ticker tabs and save a layout under a name of 1–40 letters, digits, underscores or dashes. Changing a symbol or timeframe cancels prior jobs cooperatively and discards stale responses. Chart bars have an OHLC hover readout and a visible-bar slider. Quotes carry their provider timestamp and status; data is not assumed to be exchange real-time. News is deduplicated by URL/title and displays its source/date.

A provider request already in progress cannot be forcibly terminated. Cancelling a job stops the next checkpoint and prevents publishing its result; screen/workflow/experiment persistence checks cancellation before saving. Jobs are local, bounded to three worker threads and 50 retained records; they do not survive a backend restart. Layouts, documents and successful runs do survive restarts.

## Company analysis and valuation

`/company AAPL` retrieves up to five annual income, balance-sheet and cash-flow periods via yfinance. Provider monetary units and financial currency are retained. Profile and company calendar are provider-reported, not independently verified. Consensus estimates are explicitly unavailable; historical actuals are never substituted for estimates.

Ratios use matching fiscal dates:

- Revenue growth compares the preceding reported annual period.
- Net/operating margin = corresponding income / revenue, in percent.
- Debt/equity = total debt / positive shareholder equity.
- ROE = net income / average current and prior equity, in percent.
- ROIC = operating income × (1 − effective tax rate) / average invested capital. Invested capital = equity + total debt − cash. Effective tax rate = tax provision / positive pretax income and must fall within 0–100%.

Missing denominators or prior periods produce null values. Peer comparison selects the latest exact common fiscal end date across 2–8 companies. It withholds metrics if periods do not align. Currencies remain visible; absolute monetary figures from different currencies are not normalized implicitly. This simple ROIC definition needs interpretation for banks and other financial companies.

`/valuation <unlevered FCF> <growth> <discount> <terminal> [cash] [debt] [shares]` uses explicit user inputs. Rates are decimal fractions, e.g. 0.10, and discount must exceed terminal growth. It discounts forecast FCF and a Gordon terminal value, then adds cash and subtracts debt. The UI adds a 3×3 growth/discount sensitivity grid. Use one currency/date for every monetary input. No automatic conversion of reported levered FCF into unlevered FCF is performed.

## Document evidence and AI

Import local files from CLI with `/document import "report.pdf" AAPL`. Browser and desktop command bridges reject local import/export paths; use upload/download controls instead. PDF/TXT/MD uploads are limited to 8 MiB, 400 pages and 1.5 million extracted characters. Text must be UTF-8. Scanned PDFs need external OCR and encrypted PDFs are rejected.

`/document search margin risks` performs lexical retrieval over the latest 50 matching documents, returning exact snippets, page numbers, offsets, content digests and citation IDs. `/document page <id> <page>` and the UI citation button display the extracted page. Retrieval is not semantic understanding or independent verification.

`/workflow Compare AAPL and MSFT and explain margin risk` asks the configured AI provider for at most six read-only steps. Allowed tools: company, peers, market, news, documents, portfolio and bounded historical backtest. The entire plan is checked before tools execute. Tools cannot route orders, execute code, write arbitrary files or operate TradingView. Each step keeps its result, missing data and provenance. Summary prompts treat document content as untrusted evidence and request citations to numbered tools/document IDs. Model summaries can still be wrong; inspect the underlying evidence. If the model is unavailable, explicit uppercase tickers allow a deterministic company plan and the tool results remain available without a generated summary.

Successful workflow evidence is saved locally and can be inspected/exported:

```text
/workspace runs
/workspace run <id>
/workspace export <id> evidence.json
/workspace job company '{"symbol":"AAPL"}'
/jobs show <job-id>
/jobs cancel <job-id>
```

## Screening and experiments

```text
/screen AAPL,MSFT --where "revenue_growth > 10% and rsi < 40"
/scan AAPL,MSFT --where "net_margin > 15% or roe > 20%"
/screen save quality revenue_growth > 10% and debt_to_equity < 1
/screen list
/screen run quality AAPL,MSFT
/workspace export <screen-run-id> screen.xlsx
/workspace job backtest '{"symbol":"AAPL","strategy":"sma_cross","period":"1y","asset_class":"equity"}'
```

The expression grammar permits bounded comparisons joined by `and`/`or` (`and` binds first), with no arbitrary Python/JavaScript evaluation. Missing fields never satisfy a comparison and are listed explicitly. Supported fields include revenue growth, margins, leverage, ROE/ROIC, FCF, PE, market cap, price, RSI, SMA and ATR. Ratios expressed in percent use percentage points; RSI is a 0–100 score. Screens cover up to 50 explicit or watchlist symbols. Financial data currently comes from yfinance; technical data follows configured providers.

Screens save their expression, periods, metrics and reasons. Excel export includes a provenance sheet and escapes formula-like strings. JSON export is available for every saved run.

Strategy experiments reuse the existing deterministic backtester for SMA cross, RSI reversion or momentum, over 6 months/1 year/2 years of daily candles. Choose the appropriate equity/ETF/crypto/forex/commodity/index fee profile. Input candles, parameters and computed result are saved together. There is no automatic optimization, future performance guarantee or order execution.

## Portfolio intelligence

Use the Portfolio layout or pass explicit inputs:

```text
/portfolio intelligence '{"base_currency":"USD","fx":{"EUR":1.2},"entry_fx":{"EUR":1.1},"shock":-0.2,"fx_shock":-0.1,"fee_bps":10}'
```

FX means units of base currency per one unit of position currency. Same-currency rates are one. Cross-currency rates are never guessed. Missing prices/FX withhold the complete portfolio total and rebalance. Price currency from a provider must agree with the stored position currency. Entry FX is required for historical unrealized PnL attribution. For quantity q, current price P, cost C, entry rate r0 and current rate r1:

- Price contribution = q × (P − C) × r0.
- FX contribution = q × P × (r1 − r0).
- Their sum equals q × (P × r1 − C × r0).

This is attribution of unrealized PnL since average cost, excluding realized trades, dividends and cash flows. Stress applies explicit uniform price and FX shocks; FX shocks apply only to foreign-currency holdings. Equal-weight rebalance is a fractional-quantity preview before fees; estimated fees use gross buy+sell turnover × basis points / 10,000. It does not send orders or reserve fee cash.

Optional benchmark comparison accepts `benchmark`, `period`, `start_fx` and `fx`. It uses the first and last shared historical close dates, fixed current holding quantities, and benchmark price return in the same base currency. Missing endpoint FX/currency withholds the comparison. `start_fx` belongs to the window's start date and is distinct from average-cost `entry_fx`. Provider adjustment conventions may incorporate splits/dividends; there is no separate dividend cash ledger. It is not realized, cash-flow-adjusted portfolio performance.

## Optional TradingView bridge

FinCLI integrates a small allowlist from [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp), inspected at commit `c05b8f5755ed8e64ea242de88ddbf46aa24d56a4`. Install that external project separately, following its README, and connect your own TradingView Desktop session via a local debug interface. Set `FINCLI_TV_CLI` to the absolute path of its `src/cli/index.js` and ensure Node is installed. FinCLI does not install the bridge, obtain credentials or open a debug port for you. Debug access must remain on localhost.

```text
/tv capabilities
/tv status
/tv chart
/tv symbol NASDAQ:AAPL --confirm
/tv timeframe D --confirm
/tv indicator RSI --confirm
/tv draw 185 --confirm
/tv pine --confirm
/tv replay --confirm
/tv screenshot --confirm
```

`pine` compiles current editor content; it does not author, inject or cloud-save Pine scripts. `replay` advances the current replay by one step. Screenshot invokes the bridge's local chart capture and reports its saved file. Chart changes require explicit CLI or UI confirmation. Arbitrary UI evaluation, OHLCV extraction, credentials and orders are excluded. Nothing returned by the bridge feeds FinCLI valuation, backtesting, portfolio risk or order routing. Internal TradingView UI APIs are unofficial and can change; account permissions and TradingView data terms apply. A live TradingView session is required to verify end-to-end operation.

## Architecture and validation

`fincli/app/workspace/` owns structured results, financial calculations, evidence retrieval, storage, jobs, screening and the optional connector. Domain command handlers live in `fincli/app/cli/handlers/`; `CommandRouter` composes them and retains its public command interface. The local web API authenticates every workspace operation and retains CSRF checks for mutations. No workspace endpoint accepts arbitrary filesystem output paths.

Validation commands:

```bash
python -m pytest -q
python -m ruff check fincli tests scripts
python -m mypy fincli/app/web fincli/app/workspace fincli/app/utils/security_scan.py scripts/prepublish_check.py
python -m compileall fincli -q
npm ci
npm run check
npm run test:workspace-ui
python scripts/prepublish_check.py
```

Unit/regression tests use isolated credentials and deterministic provider fixtures. DOM tests exercise linked symbols, stale-response cancellation, escaping, citation inspection, layouts and analysis forms. These do not replace a native Windows/WebView2 visual check or testing a user-authorized live TradingView session. Pull requests trigger the existing multi-OS Python matrix plus a Windows desktop build/smoke check. FinCLI does not claim Bloomberg's proprietary datasets, exchange entitlements, news licensing, messaging network or professional terminal certification.
