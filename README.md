# FinCLI v0.1

FinCLI adalah financial CLI/TUI terminal modern untuk memantau market, mengelola watchlist, portfolio, journal, konfigurasi provider, dan menyiapkan integrasi AI market analysis secara modular.

Status saat ini: FinCLI MVP aktif dengan TUI, provider chain, AI assistance, web research, portfolio, journal, watchlist, export, dan session history lokal.

- Textual TUI satu kolom dengan command palette inline yang bisa discroll; sidebar lama sudah dihapus agar output market lebih lega.
- Slash command router dengan command wajib FinCLI v0.1.
- Config system berbasis `.env` untuk secret dan `~/.fincli/config.json` untuk preference non-secret.
- SQLite local storage untuk watchlist, portfolio, dan journal.
- yfinance fallback untuk quote, OHLCV history, news, dan fundamental snapshot.
- Finnhub provider untuk quote, stock candles, company news, dan company profile via `FINNHUB_API_KEY`.
- Twelve Data provider untuk multi-asset market data via `TWELVE_DATA_API_KEY`.
- Economic calendar lewat Finnhub jika API key tersedia, dengan fallback lokal jika provider belum dikonfigurasi.
- Technical analysis dasar: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, support/resistance, volume, trend bias.
- Market structure dasar: HH/HL, LH/LL, break of structure, change of character, liquidity area, risk zone.
- Watchlist scanner: `/scan watchlist` dengan filter `rsi<30`, `rsi>70`, atau `trend=bullish`.
- Persistent SQLite market cache untuk quote, OHLCV history, news, dan fundamental agar provider API tidak dipanggil berulang secara boros.
- `/ai` dan `/analyze` sudah lewat AI provider interface. `/ai` memakai persona FinCLI, guardrail anti-coding, dan market context otomatis jika prompt menyebut symbol eksplisit.
- AI HTTP clients untuk OpenAI-compatible APIs, Gemini, dan Anthropic. OpenRouter, OpenAI, Together, Groq, dan HuggingFace memakai jalur OpenAI-compatible.
- Portfolio view menghitung current price, PnL, dan PnL percent dari quote provider aktif.
- Export portfolio/journal ke CSV atau JSON.
- Basic tests untuk command registry, router, config, storage, market command, technical analysis, dan AI command injection.

## Stack

- Python 3.11+
- Textual + Rich untuk TUI
- SQLite untuk local database
- python-dotenv untuk `.env`
- yfinance untuk fallback market/news/fundamental data
- httpx disiapkan untuk provider API lanjutan
- pytest untuk test

Textual dipilih karena lebih cocok untuk dashboard terminal interaktif dibanding CLI statis. Rich tetap dipakai untuk table/panel renderable.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Alternatif:

```bash
pip install -r requirements.txt
```

## Global Install

Rekomendasi untuk Python CLI adalah `pipx`, karena dependency FinCLI dipasang di environment terisolasi tetapi command `fincli` tersedia global:

```bash
pip install pipx
pipx ensurepath
pipx install .
fincli
```

Jika sudah dipublish ke PyPI:

```bash
pipx install fincli
fincli
```

FinCLI juga punya npm wrapper agar bisa mengikuti pola “install once, run anywhere” seperti CLI Node:

```bash
npm install -g .
fincli
```

Setelah package npm dipublish:

```bash
npm install -g @drico2008/fincli
fincli
```

Catatan: npm wrapper tetap membutuhkan Python 3.11+ saat install. Script npm akan membuat virtualenv `.npm-python`, menginstall package Python FinCLI ke sana, lalu command global `fincli` menjalankan `python -m fincli.app.main`.

## Setup `.env`

```bash
copy .env.example .env
```

Isi API key hanya untuk provider yang ingin digunakan. yfinance fallback tidak butuh API key. Config membaca status key tanpa menampilkan secret.

Untuk install global lewat npm, user tidak perlu membuka folder package atau mengedit `.env`. Simpan API key lewat command FinCLI:

```text
/ai_model key groq <api_key>
/ai_model key openrouter <api_key>
/news_model key finnhub <api_key>
/news_model key twelvedata <api_key>
/news_model key custom <api_key> https://your-market-api.example.com
```

Key disimpan lokal di:

```text
~/.fincli/secrets.env
```

File ini tidak dicetak penuh di output terminal. `/config` dan `/provider key status` hanya menampilkan status/masked key.

## Run

```bash
fincli
```

Atau:

```bash
python -m fincli.app.main
```

## Command Utama

```text
/help
/dashboard
/config
/ai_model
/ai_model openrouter openai/gpt-4o-mini
/news_model
/market AAPL 1d
/provider status
/provider list
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
/journal add BTC-USD bullish "Breakout gagal, tunggu konfirmasi"
/journal stats
/journal review
/history
/history sessions
/history save "Riset market pagi"
/quote AAPL
/technical BTC-USD 1d
/technical XAUUSD 1d
/technical EURUSD 1d
/structure BTC-USD 1d
/news AAPL
/web penyebab rupiah melemah hari ini
/web sources penyebab rupiah melemah hari ini
/funda MSFT
/yahoo BBRI history 6mo 1d
/yahoo BBRI statistics
/yahoo BBRI profile
/yahoo BBRI financials
/yahoo BBRI analysis
/yahoo BBRI holders
/ai jelaskan risiko market hari ini
/analyze ETH-USD 4h
/scan watchlist rsi<30
/scan watchlist trend=bullish
/scan watchlist rsi>60 trend=bullish
/calendar
/calendar today
/calendar 2026-06-05 2026-06-12 country=US impact=high
/export portfolio json C:\Users\MSI\Desktop\portfolio.json
/export journal csv C:\Users\MSI\Desktop\journal.csv
/cache stats
/cache clear
/clear
/exit
```

Command `/market`, `/quote`, `/technical`, `/structure`, `/news`, dan `/funda` sudah memakai provider chain aktif. Command `/ai` dan `/analyze` sudah memakai AI provider aktif dari `/ai_model` dan `.env`. `/analyze` membawa konteks indikator, struktur pasar, news, dan fundamental ringkas ke prompt AI. `/ai` juga mengambil quote, OHLCV/technical, structure, news, dan fundamental saat user menyebut symbol seperti `AAPL`, `EURUSD`, atau `XAUUSD`.

## AI Chat UX

Di TUI, input biasa tanpa slash sekarang diperlakukan sebagai chat ke AI assistant aktif:

```text
hello
```

Output ditampilkan dengan format terminal chat:

```text
> hello
▸ Thinking: routing prompt to active AI provider...
* Provider: ...
```

Command eksplisit tetap bisa dipakai:

```text
/ai jelaskan risiko market hari ini
```

AI assistant di dalam FinCLI dipersonalisasi untuk market workflow:

- Mengenali FinCLI sebagai terminal financial dashboard.
- Boleh free chat untuk pertanyaan umum, market, portfolio, journal, provider, dan risk workflow.
- Menolak coding/debugging/refactor/pembuatan software di dalam assistant FinCLI agar fokus app tetap jelas.
- Jika prompt berisi symbol eksplisit, FinCLI menyisipkan market context dari provider chain aktif sebelum memanggil AI provider.
- Jika prompt membutuhkan info terkini, FinCLI dapat mengambil konteks web publik dan memasukkannya ke AI prompt.
- Tidak membocorkan API key dan tidak mengklaim realtime jika provider aktif hanya delayed/fallback.

Contoh web-aware freechat:

```text
apa yang menyebabkan penurunan rupiah terhadap semua mata uang hari ini
berita terbaru BI rate dan dampaknya ke IHSG
```

Untuk web search yang dirangkum oleh AI:

```text
/web penyebab rupiah melemah hari ini
/web update harga emas dan dollar index
```

Untuk melihat sumber mentah tanpa ringkasan AI:

```text
/web sources penyebab rupiah melemah hari ini
```

FinCLI memakai lightweight HTTP web research, bukan Chrome automation. Ini lebih stabil untuk npm global install dan tidak membuka browser di background. Output tetap harus diverifikasi karena kualitas sumber web bisa berbeda-beda.

## Interactive AI Model Selector

```text
/ai_model
```

Di TUI, command ini membuka selector seperti modern CLI:

- Select Provider
- Status provider current/configured
- Use existing configuration / configure again
- Configure API key jika provider belum punya key
- Select Model
- Search model/provider
- Navigasi `up/down`, `Enter`, `Tab`, dan `Esc`

Untuk set langsung tanpa selector:

```text
/ai_model openrouter openai/gpt-4o-mini
```

## Interactive Market/News Provider Selector

```text
/news_model
```

Di TUI, command ini membuka selector untuk provider market/news dan fallback priority:

- Select Market/News Provider
- Pilih `Twelve Data`, `Finnhub`, `Custom API`, atau `Yahoo Finance`
- Masukkan API key langsung dari popup jika provider belum dikonfigurasi
- Pilih preset fallback: recommended, primary + yfinance, data API priority, atau yfinance only
- Search provider/preset
- Navigasi `up/down`, `Enter`, `Tab`, dan `Esc`

Rekomendasi praktis:

```text
Primary: twelvedata
Fallback: twelvedata -> finnhub -> custom -> yfinance
```

`yfinance` tetap fallback gratis/delayed. Provider API seperti Twelve Data dan Finnhub tetap bergantung pada API key, plan, entitlement exchange, dan batas rate-limit.

## Economic Calendar

```text
/calendar
/calendar today
/calendar week US high
/calendar 2026-06-05 2026-06-12 country=US impact=high
```

Jika `FINNHUB_API_KEY` tersedia, FinCLI mengambil economic calendar aktual dari Finnhub. Jika API key kosong atau provider gagal, FinCLI tetap menampilkan fallback kategori event penting seperti central bank decision, inflation release, labor data, GDP/PMI, dan retail sales. Fallback ini tidak mengklaim tanggal aktual.

## Market Cache

FinCLI memakai dua lapis cache:

- Runtime cache di memori untuk command yang dipanggil berulang dalam sesi TUI.
- Persistent SQLite cache di `~/.fincli/fincli.db` untuk quote, OHLCV history, news, dan fundamentals.

Cache mengikuti `cache_ttl_seconds` dari config. Ini penting untuk mengurangi rate-limit, mempercepat scanner/watchlist, dan membuat provider chain lebih efisien.

Command:

```text
/cache stats
/cache clear
```

`/cache clear` menghapus runtime cache dan persistent market cache. API key tetap aman karena cache hanya menyimpan respons market data, bukan secret.

## Dashboard Compact

```text
/dashboard
```

Dashboard dibuat sebagai layar awal TUI yang tidak stacked dan tidak ramai. Ringkasannya mencakup:

- Provider chain
- Watchlist price snapshot
- Portfolio market value dan PnL
- Journal win rate
- Command hint untuk langkah berikutnya

## Market Overview

Command utama untuk melihat instrumen secara profesional:

```text
/market AAPL 1d
```

Output berisi:

- Data Quality score
- Quote dan provider status
- RSI, trend, MACD, ATR
- Support/resistance
- Market structure
- Fundamental snapshot
- Latest news
- Disclaimer

Gunakan `/market` sebagai entry point sebelum masuk ke `/technical`, `/structure`, atau `/analyze`.

## Coverage Instrumen

Coverage tergantung provider dan format symbol:

- `yfinance`: stocks, ETFs, indices, forex, crypto, commodities, dan mutual funds selama symbol Yahoo valid.
- `custom`: instrumen apa pun selama API kamu menyediakan endpoint FinCLI.
- `finnhub`: quote/candle saham, forex candle, crypto candle, company news, company profile, dan economic calendar sesuai plan API.
- `twelvedata`: multi-asset stocks, forex, ETFs, indices, commodities, dan crypto dengan format symbol yang lebih konsisten untuk market global.

Rekomendasi provider priority untuk multi-asset:

```text
/provider priority twelvedata,finnhub,yfinance
```

Dengan konfigurasi ini:

- `twelvedata` dicoba dulu untuk forex/indices/commodities/global stocks.
- `finnhub` menjadi fallback untuk saham dan news/fundamental tertentu.
- `yfinance` tetap fallback gratis/delayed jika provider API gagal.

Contoh symbol yfinance:

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

FinCLI juga menerima alias umum dan mengubahnya ke format provider:

```text
EURUSD   -> EURUSD=X untuk yfinance, EUR/USD untuk Twelve Data, OANDA:EUR_USD untuk Finnhub forex candle
XAUUSD   -> XAUUSD=X untuk yfinance, XAU/USD untuk Twelve Data
SPX      -> ^GSPC untuk yfinance
NASDAQ   -> ^IXIC untuk yfinance
DAX      -> ^GDAXI untuk yfinance
NIKKEI   -> ^N225 untuk yfinance
WTI      -> CL=F untuk yfinance
BRENT    -> BZ=F untuk yfinance
```

## Technical AI Summary

`/technical` sekarang menyertakan ringkasan khusus untuk AI assistance:

```text
/technical EURUSD 1d
/technical XAUUSD 1d
/technical SPX 1d
```

Output mencakup trend bias, RSI, MACD, support/resistance, ATR, market structure ringkas, signal, dan risk notes. Signal bersifat rule-based dan transparan:

```text
Signal: BEST TO BUY | BEST TO SELL | CAUTION
Signal Score
Confidence
Signal Reasoning
Signal Risk Notes
Invalidation / Caution Level
```

Signal tidak dianggap instruksi entry pasti. FinCLI tetap memakai bahasa skenario, confirmation, invalidation, dan risk notes agar cocok untuk AI assistance serta tidak memberi klaim profit. Ringkasan ini bisa langsung dipakai sebagai konteks sebelum menjalankan:

Selain signal langsung, `/technical` sekarang memakai `Technical Debate`:

- `Bull Chooser`: mencari argumen buy candidate.
- `Bear Chooser`: mencari argumen sell candidate.
- `Caution Chooser`: mencari konflik, overextension, volatilitas, dan kualitas konfirmasi.
- `Judge`: menentukan final `BEST TO BUY`, `BEST TO SELL`, atau `CAUTION`.

Debate ini juga dimasukkan ke prompt AI agar AI assistance tidak hanya membaca satu sisi argumen.

```text
/analyze EURUSD 1d
```

## Scanner

Contoh:

```text
/scan watchlist
/scan watchlist rsi<30
/scan watchlist rsi>70
/scan watchlist trend=bullish
/scan watchlist trend=bearish 1d
/scan watchlist rsi>60 trend=bullish
```

Scanner mengambil data history secara async dalam batch terbatas, menghitung indikator, lalu hanya menampilkan symbol yang match filter.

## Portfolio Transaction Ledger

Gunakan transaction ledger untuk portfolio yang lebih serius:

```text
/tx add buy AAPL 10 185
/tx add sell AAPL 5 195
/tx list
/portfolio performance
```

Buy transaction akan memperbarui quantity dan average price. Sell transaction akan mengurangi posisi dan mencatat realized PnL. `/portfolio performance` menampilkan cost basis, market value, unrealized PnL, realized PnL, dan total PnL.

## Journal Analytics

```text
/journal stats
/journal review
```

`/journal stats` menghitung total entry, win/loss, win rate, instrumen dominan, emosi dominan, dan tag teratas. `/journal review` mengirim statistik dan entry journal ke AI provider aktif untuk review proses, pola kesalahan, risk notes, dan perbaikan kebiasaan. Output tetap memakai disclaimer dan bukan nasihat keuangan.

## AI Provider

Provider yang disiapkan:

- `openrouter`: `OPENROUTER_API_KEY`
- `openai`: `OPENAI_API_KEY`
- `groq`: `GROQ_API_KEY`
- `together`: `TOGETHER_API_KEY`
- `huggingface`: `HUGGINGFACE_API_KEY`
- `gemini`: `GEMINI_API_KEY`
- `anthropic`: `ANTHROPIC_API_KEY`

Contoh:

```bash
/ai_model openrouter openai/gpt-4o-mini
/ai_model key openrouter <api_key>
/ai jelaskan risiko market NVDA secara singkat
/analyze AAPL 1d
```

API key tidak pernah dicetak penuh di output terminal.

## Data Realtime / Delayed

FinCLI saat ini memakai yfinance sebagai fallback. Data yfinance umumnya delayed dan tidak boleh diklaim realtime. Provider API key dapat ditambahkan untuk realtime jika provider tersebut mendukungnya.

## Yahoo Finance Tables

FinCLI memakai yfinance untuk akses saham global yang tersedia di Yahoo Finance. Untuk saham di luar US, gunakan suffix Yahoo bila tahu exchange-nya, misalnya `BBRI.JK`, `HSBA.L`, `SHOP.TO`, atau `0700.HK`. Untuk ticker IDX umum seperti `BBRI`, `BBCA`, `BMRI`, `TLKM`, `ASII`, FinCLI otomatis mengarahkannya ke suffix `.JK`.

Command:

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

Source URL yang dipakai mengikuti format Yahoo Finance, misalnya:

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

Catatan: availability news, analysis, holders, dan beberapa financial table bergantung coverage Yahoo untuk exchange/ticker tersebut.

## Finnhub Provider

Aktifkan lewat selector TUI:

```text
/news_model
```

Environment variable:

```env
FINNHUB_API_KEY=your-finnhub-key
```

Atau simpan dari FinCLI:

```text
/news_model key finnhub <api_key>
```

Endpoint Finnhub yang dipakai:

```text
GET /quote
GET /stock/candle
GET /forex/candle
GET /crypto/candle
GET /company-news
GET /stock/profile2
GET /calendar/economic
```

Catatan: Finnhub menyediakan REST/WebSocket untuk stocks, currencies/forex, dan crypto, plus fundamental/news sesuai plan. Di FinCLI, news/fundamental tetap paling kuat untuk saham; forex/crypto dipakai untuk candle/technical.

## Twelve Data Provider

Aktifkan lewat selector TUI:

```text
/news_model
```

Environment variable:

```env
TWELVE_DATA_API_KEY=your-twelve-data-key
```

Atau simpan dari FinCLI:

```text
/news_model key twelvedata <api_key>
```

Endpoint Twelve Data yang dipakai:

```text
GET /quote
GET /time_series
```

Twelve Data paling cocok untuk symbol multi-asset seperti forex (`EURUSD`), metals (`XAUUSD`), indices global, ETF, crypto, dan saham populer US/Eropa/Asia. Tetap cek plan dan exchange entitlement provider untuk realtime vs delayed.

## Provider Commands

```text
/news_model
/provider list
/provider status
/provider test AAPL
/provider test finnhub AAPL
/provider key status
```

`/news_model` adalah flow resmi untuk memilih provider market/news dan fallback chain di TUI. `/provider status` menampilkan provider aktif, fallback chain, dan health message dari provider utama. `/provider test <symbol>` melakukan quote test lewat provider aktif. `/provider test <provider> <symbol>` mengetes provider tertentu tanpa mengganti provider aktif.

Command manual `/provider use ...` dan `/provider priority ...` masih tersedia sebagai advanced CLI fallback, tetapi tidak lagi ditampilkan sebagai flow utama di command palette.

Contoh fallback chain yang disimpan selector:

```text
twelvedata -> finnhub -> custom -> yfinance
```

Dengan contoh di atas, FinCLI mencoba Twelve Data lebih dulu. Jika gagal, FinCLI mencoba provider berikutnya dan memakai yfinance delayed sebagai fallback terakhir.

## Custom Market Provider

Aktifkan lewat selector TUI:

```text
/news_model
```

Environment variable:

```env
MARKET_DATA_API_KEY=your-key
MARKET_DATA_BASE_URL=https://your-market-api.example.com
```

Atau simpan dari FinCLI:

```text
/news_model key custom <api_key> https://your-market-api.example.com
```

FinCLI akan memanggil endpoint:

```text
GET /quote/{symbol}
GET /history/{symbol}?period=6mo&interval=1d
GET /news/{symbol}?limit=5
GET /fundamentals/{symbol}
```

Header dikirim sebagai `X-API-Key` dan `Authorization: Bearer <key>`. API key tidak ditampilkan di terminal.

Contoh payload quote:

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

FinCLI menyimpan data lokal di:

```text
~/.fincli/config.json
~/.fincli/fincli.db
~/.fincli/fincli.log
```

API key tidak disimpan di output terminal. Untuk install global via npm, jalur utama adalah command FinCLI:

```text
/ai_model key groq <api_key>
/news_model key twelvedata <api_key>
```

Key disimpan lokal di `~/.fincli/secrets.env`, dipakai otomatis untuk semua session FinCLI berikutnya, dan tidak perlu dikonfigurasi ulang. Jika `.env` lokal berisi nilai kosong, FinCLI tetap memakai secret lokal yang sudah tersimpan.

## Test

```bash
pytest
```

Hasil terakhir di environment ini:

```text
97 passed
```

## Troubleshooting

- `fincli` tidak dikenali: jalankan `pip install -e .` dari root project.
- TUI tidak tampil rapi: perbesar terminal desktop.
- API key tidak terbaca: gunakan `/ai_model key <provider> <api_key>` atau `/news_model key <provider> <api_key>`, lalu cek `/config` atau `/provider key status`.
- `/quote` gagal karena yfinance belum ada: jalankan `pip install -e ".[dev]"` atau `pip install -r requirements.txt`.
- Config rusak: hapus `~/.fincli/config.json` untuk kembali ke default.

## Roadmap Lanjutan

- Scanner export dan filter expression parser yang lebih lengkap.
- Market structure lebih lanjut: pivot strength, multi-timeframe structure, liquidity sweep detection.
- AI market analysis dengan ranking data quality dan confidence scoring.
- Custom provider schema validation yang lebih ketat dan adapter untuk provider populer.
- Provider adapter lanjutan untuk entitlement exchange, symbol search, dan realtime streaming.
- Economic calendar lanjutan, screener, alert dasar, dan multi-timeframe analysis.

## Roadmap v0.3

- Plugin system.
- Strategy builder.
- Advanced portfolio analytics.
- Notification integration.
- Optional cloud sync.
