"""Slash command registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    example: str
    group: str = "General"


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("/help", "Tampilkan bantuan, command list, dan contoh.", "/help"),
    CommandSpec("/dashboard", "Tampilkan dashboard compact FinCLI.", "/dashboard", "General"),
    CommandSpec("/ai_model", "Lihat atau ganti AI provider/model.", "/ai_model openrouter openai/gpt-4o-mini", "AI"),
    CommandSpec("/ai_model key", "Simpan API key AI lokal.", "/ai_model key groq <api_key>", "AI"),
    CommandSpec("/news_model", "Buka selector provider market/news dan fallback.", "/news_model", "Provider"),
    CommandSpec("/news_model list", "Tampilkan 100+ news connector dan status akses.", "/news_model list", "Provider"),
    CommandSpec("/news_model search", "Cari connector news.", "/news_model search rss", "Provider"),
    CommandSpec("/news_model use", "Pilih primary news provider.", "/news_model use google_news_rss", "Provider"),
    CommandSpec("/news_model priority", "Atur fallback news provider.", "/news_model priority google_news_rss,yfinance,marketaux", "Provider"),
    CommandSpec("/news_model key", "Simpan API key news connector lokal.", "/news_model key marketaux <api_key>", "Provider"),
    CommandSpec("/symbol", "Search dan resolve symbol lintas provider.", "/symbol search BBRI", "Market"),
    CommandSpec("/symbol resolve", "Normalisasi symbol per provider.", "/symbol resolve XAUUSD --asset commodity", "Market"),
    CommandSpec("/research", "Research Engine v3: snapshot/deep/report dengan sumber, blending sektor/makro/news, dan export.", "/research AAPL --deep", "Research"),
    CommandSpec("/macro", "Dashboard macro fallback dan connector-ready context.", "/macro Indonesia", "Research"),
    CommandSpec("/profile", "Tampilkan profil dan gameplay risk lokal.", "/profile", "Profile"),
    CommandSpec("/profile set", "Simpan profil gameplay lokal.", '/profile set "Budi" 350 USD 1:100 1.5', "Profile"),
    CommandSpec("/doctor", "Cek kesehatan konfigurasi, provider, database, dan command inti.", "/doctor", "System"),
    CommandSpec("/doctor report", "Generate diagnostic report (no secrets).", "/doctor report", "System"),
    CommandSpec("/setup", "Setup wizard — cek konfigurasi dan panduan setup.", "/setup", "System"),
    CommandSpec("/setup check", "Cek detail konfigurasi saat ini.", "/setup check", "System"),
    CommandSpec("/setup keys", "Panduan setup API keys.", "/setup keys", "System"),
    CommandSpec("/setup profile", "Cek/setup user profile.", "/setup profile", "System"),
    CommandSpec("/setup theme", "Panduan setup tema.", "/setup theme", "System"),
    CommandSpec("/secrets status", "Audit status secret lokal tanpa menampilkan nilai.", "/secrets status", "Security"),
    CommandSpec("/secrets clear", "Hapus semua API key lokal dari secret store.", "/secrets clear", "Security"),
    CommandSpec("/security status", "Tampilkan status keamanan: secrets, redaction, validation, rate limiting.", "/security status", "Security"),
    CommandSpec("/security audit", "Tampilkan audit log event keamanan (immutable).", "/security audit", "Security"),
    CommandSpec("/security scan", "Scan untuk secret yang terekspos dan masalah keamanan.", "/security scan", "Security"),
    CommandSpec("/security lockdown", "Emergency: hapus semua secrets dan disable providers.", "/security lockdown", "Security"),
    CommandSpec("/privacy status", "Tampilkan ringkasan state lokal sensitif.", "/privacy status", "Security"),
    CommandSpec("/privacy purge", "Bersihkan secrets, history session, dan cache lokal.", "/privacy purge", "Security"),
    CommandSpec("/agent", "Lihat agent framework FinCLI.", "/agent list", "AI"),
    CommandSpec("/agent show", "Tampilkan detail agent framework.", "/agent show buffett", "AI"),
    CommandSpec("/connector", "Lihat catalog data connector.", "/connector list macro", "Provider"),
    CommandSpec("/connector search", "Cari connector data.", "/connector search yahoo", "Provider"),
    CommandSpec("/plugin", "Tampilkan plugin lokal FinCLI.", "/plugin list", "System"),
    CommandSpec("/plugin status", "Cek status manifest plugin lokal.", "/plugin status", "System"),
    CommandSpec("/plugin validate", "Validasi manifest plugin lokal.", "/plugin validate", "System"),
    CommandSpec("/market", "Ringkasan market profesional untuk instrumen.", "/market AAPL 1d", "Market"),
    CommandSpec("/quote", "Alias cepat untuk harga/quote instrumen.", "/quote AAPL", "Advanced"),
    CommandSpec("/news", "Tampilkan news/fundamental terbaru untuk instrumen.", "/news AAPL", "Market"),
    CommandSpec("/technical", "Analisis teknikal instrumen.", "/technical BTC-USD 1d", "Analysis"),
    CommandSpec("/structure", "Alias struktur pasar tanpa panel teknikal penuh.", "/structure AAPL 1d", "Advanced"),
    CommandSpec("/mtf", "Multi-timeframe technical alignment.", "/mtf AAPL 1d,1h,15m", "Analysis"),
    CommandSpec("/backtest", "Professional backtest: fees, slippage, ratios, Monte Carlo, walk-forward, export.", "/backtest AAPL sma_cross 1d --monte-carlo", "Analysis"),
    CommandSpec("/trading", "Trading layer: risk guard, broker catalog, paper trading, algo, audit.", "/trading", "Trading"),
    CommandSpec("/trading kill", "Aktifkan kill switch untuk blokir semua paper order.", "/trading kill", "Trading"),
    CommandSpec("/trading resume", "Nonaktifkan kill switch dan izinkan paper order kembali.", "/trading resume", "Trading"),
    CommandSpec("/trading risk", "Tampilkan status risk guard, daily PnL, dan konfigurasi.", "/trading risk", "Trading"),
    CommandSpec("/trading audit", "Tampilkan audit log order (immutable).", "/trading audit", "Trading"),
    CommandSpec("/trading cancel", "Batalkan paper order yang masih queued.", "/trading cancel 5", "Trading"),
    CommandSpec("/trading positions", "Tampilkan posisi paper trading teragregasi.", "/trading positions", "Trading"),
    CommandSpec("/trading broker use", "Aktifkan broker sandbox adapter.", "/trading broker use Alpaca", "Trading"),
    CommandSpec("/trading broker status", "Tampilkan status broker adapter.", "/trading broker status", "Trading"),
    CommandSpec("/trading stream", "Tampilkan status realtime connector stream.", "/trading stream", "Trading"),
    CommandSpec("/trading algo list", "Tampilkan strategi algo yang tersedia.", "/trading algo list", "Trading"),
    CommandSpec("/trading algo run", "Jalankan strategi algo dan place paper order.", "/trading algo run sma_cross AAPL 1d", "Trading"),
    CommandSpec("/yahoo", "Tampilkan tabel Yahoo Finance untuk history/statistics/profile/financials/analysis/holders.", "/yahoo BBRI statistics", "Market"),
    CommandSpec("/funda", "Alias compact untuk fundamental snapshot.", "/funda AAPL", "Advanced"),
    CommandSpec("/web", "Web research helper untuk pertanyaan berbasis sumber publik.", "/web penyebab rupiah melemah", "Advanced"),
    CommandSpec("/ai", "Free chat dengan AI assistant.", "/ai ringkas risiko AAPL", "AI"),
    CommandSpec("/analyze", "AI menganalisis struktur pasar instrumen.", "/analyze ETH-USD 4h", "Analysis"),
    CommandSpec("/watchlist", "Tampilkan watchlist.", "/watchlist", "Watchlist"),
    CommandSpec("/watchlist add", "Tambahkan instrumen ke watchlist.", "/watchlist add AAPL crypto \"breakout setup\"", "Watchlist"),
    CommandSpec("/watchlist remove", "Hapus instrumen dari watchlist.", "/watchlist remove AAPL", "Watchlist"),
    CommandSpec("/watchlist list", "Tampilkan watchlist, filter by group.", "/watchlist list crypto", "Watchlist"),
    CommandSpec("/watchlist note", "Tambah/catatan ke instrumen watchlist.", "/watchlist note AAPL \"breakout setup\"", "Watchlist"),
    CommandSpec("/watchlist groups", "Tampilkan daftar group watchlist.", "/watchlist groups", "Watchlist"),
    CommandSpec("/portfolio", "Tampilkan portfolio lokal.", "/portfolio", "Portfolio"),
    CommandSpec("/portfolio add", "Tambahkan posisi/aset.", "/portfolio add BTC-USD 0.05 65000", "Portfolio"),
    CommandSpec("/portfolio remove", "Hapus posisi/aset.", "/portfolio remove BTC-USD", "Portfolio"),
    CommandSpec("/portfolio update", "DCA: tambah posisi dengan weighted average.", "/portfolio update AAPL 5 160", "Portfolio"),
    CommandSpec("/portfolio performance", "Tampilkan performa portfolio.", "/portfolio performance", "Portfolio"),
    CommandSpec("/portfolio risk", "Portfolio Risk v3: exposure, concentration, PnL, health score, risk ratios.", "/portfolio risk", "Portfolio"),
    CommandSpec("/portfolio chart", "Portfolio performance chart dengan risk ratios (Sharpe/Sortino/Calmar).", "/portfolio chart", "Portfolio"),
    CommandSpec("/portfolio snapshot", "Simpan snapshot portfolio untuk tracking time-series.", "/portfolio snapshot", "Portfolio"),
    CommandSpec("/portfolio history", "Tampilkan history portfolio snapshots.", "/portfolio history", "Portfolio"),
    CommandSpec("/portfolio whatif", "What-if analysis: tambah/kurangi posisi, lihat impact sebelum commit.", "/portfolio whatif add AAPL 10 200", "Portfolio"),
    CommandSpec("/portfolio benchmark", "Bandingkan portfolio vs benchmark (SPY, QQQ, BTC, dll).", "/portfolio benchmark SPY", "Portfolio"),
    CommandSpec("/tx", "Tampilkan transaction ledger.", "/tx list", "Portfolio"),
    CommandSpec("/tx add", "Tambahkan transaksi buy/sell.", "/tx add buy AAPL 10 185", "Portfolio"),
    CommandSpec("/journal", "Tampilkan journal trading/investasi.", "/journal", "Journal"),
    CommandSpec("/journal add", "Tambahkan catatan journal singkat.", '/journal add BTC-USD bullish "Breakout gagal, tunggu konfirmasi"', "Journal"),
    CommandSpec("/journal edit", "Edit field journal entry.", "/journal edit 1 --bias bearish --result loss", "Journal"),
    CommandSpec("/journal delete", "Hapus journal entry.", "/journal delete 1", "Journal"),
    CommandSpec("/journal show", "Tampilkan detail journal entry.", "/journal show 1", "Journal"),
    CommandSpec("/journal stats", "Tampilkan statistik journal.", "/journal stats", "Journal"),
    CommandSpec("/journal review", "AI review kebiasaan journal.", "/journal review", "Journal"),
    CommandSpec("/alert", "Tampilkan alert harga lokal.", "/alert", "Alert"),
    CommandSpec("/alert add", "Tambahkan alert (price/RSI/volume/MACD).", "/alert add AAPL above 200", "Alert"),
    CommandSpec("/alert check", "Cek alert aktif memakai quote provider.", "/alert check", "Alert"),
    CommandSpec("/alert history", "Tampilkan history alert yang sudah triggered.", "/alert history", "Alert"),
    CommandSpec("/alert daemon", "Start/stop/status background alert checker.", "/alert daemon start", "Alert"),
    CommandSpec("/history", "Session picker — lihat dan resume session sebelumnya.", "/history", "History"),
    CommandSpec("/history resume", "Resume session terakhir atau session tertentu.", "/history resume <#|session_id>", "History"),
    CommandSpec("/history current", "Tampilkan command history current session.", "/history current", "History"),
    CommandSpec("/history show", "Tampilkan detail session tertentu.", "/history show <session_id>", "History"),
    CommandSpec("/history save", "Beri nama current session.", '/history save "Riset IHSG pagi"', "History"),
    CommandSpec("/history delete", "Hapus session tertentu.", "/history delete <session_id>", "History"),
    CommandSpec("/history clear", "Hapus semua session history.", "/history clear", "History"),
    CommandSpec("/config", "Tampilkan konfigurasi aktif tanpa membocorkan API key.", "/config"),
    CommandSpec("/theme", "Tampilkan tema aktif dan daftar tema tersedia.", "/theme", "Theme"),
    CommandSpec("/theme list", "Tampilkan semua tema dengan preview warna.", "/theme list", "Theme"),
    CommandSpec("/theme create", "Buat tema custom dari base tema.", "/theme create mytheme --base midnight", "Theme"),
    CommandSpec("/theme import", "Import tema dari file JSON.", "/theme import theme.json", "Theme"),
    CommandSpec("/theme export", "Export tema ke file JSON.", "/theme export midnight theme.json", "Theme"),
    CommandSpec("/scan", "Scanner watchlist dengan filter indikator.", "/scan watchlist rsi<30", "Market"),
    CommandSpec("/scan export", "Export hasil scanner watchlist ke CSV/JSON.", "/scan export csv scan.csv rsi<30 1d", "Market"),
    CommandSpec("/report market", "Export market report ke Markdown/JSON.", "/report market AAPL md report.md", "Export"),
    CommandSpec("/calendar", "Economic calendar provider/fallback.", "/calendar week US high", "Market"),
    CommandSpec("/calendar export", "Export economic calendar ke CSV/JSON.", "/calendar export csv calendar.csv week US high", "Market"),
    CommandSpec("/provider status", "Tampilkan status provider aktif.", "/provider status", "Provider"),
    CommandSpec("/provider metrics", "Tampilkan metric runtime provider aktif.", "/provider metrics", "Provider"),
    CommandSpec("/provider list", "Tampilkan semua provider market yang tersedia.", "/provider list", "Provider"),
    CommandSpec("/provider capabilities", "Tampilkan capability matrix per provider dan command.", "/provider capabilities", "Provider"),
    CommandSpec("/provider reset", "Reset circuit breaker provider.", "/provider reset finnhub", "Provider"),
    CommandSpec("/provider key rotate", "Cek/rotate API key provider.", "/provider key rotate finnhub", "Provider"),
    CommandSpec("/provider entitlement", "Tampilkan capability dan realtime/delayed label provider.", "/provider entitlement", "Provider"),
    CommandSpec("/provider test", "Test quote provider aktif untuk symbol.", "/provider test AAPL", "Provider"),
    CommandSpec("/provider key status", "Tampilkan status API key market provider.", "/provider key status", "Provider"),
    CommandSpec("/cache stats", "Tampilkan statistik cache market persistent.", "/cache stats", "System"),
    CommandSpec("/cache clear", "Bersihkan runtime dan persistent market cache.", "/cache clear", "System"),
    CommandSpec("/export journal", "Export journal ke CSV/JSON.", "/export journal csv journal.csv", "Export"),
    CommandSpec("/export portfolio", "Export portfolio ke CSV/JSON.", "/export portfolio json portfolio.json", "Export"),
    CommandSpec("/export alerts", "Export alert history ke CSV/JSON.", "/export alerts csv alerts.csv", "Export"),
    CommandSpec("/export all", "Batch export semua data (portfolio, journal, alerts, trades).", "/export all json ./exports", "Export"),
    CommandSpec("/tutorial", "Tutorial interaktif untuk pemula. Ketik /tutorial untuk mulai.", "/tutorial", "General"),
    CommandSpec("/tutorial next", "Lanjut ke lesson berikutnya.", "/tutorial next", "General"),
    CommandSpec("/tutorial reset", "Reset progress tutorial.", "/tutorial reset", "General"),
    CommandSpec("/clear", "Bersihkan output terminal.", "/clear"),
    CommandSpec("/exit", "Keluar dari aplikasi.", "/exit"),
)


class CommandRegistry:
    """Lookup and autocomplete slash commands."""

    def __init__(self, commands: tuple[CommandSpec, ...] = COMMANDS) -> None:
        self.commands = commands

    def suggest(self, query: str, limit: int = 8) -> list[CommandSpec]:
        normalized = query.strip().lower()
        if not normalized:
            return list(self.commands[:limit])
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"

        exact = [cmd for cmd in self.commands if cmd.name.lower().startswith(normalized)]
        fuzzy = [cmd for cmd in self.commands if normalized.replace("/", "") in cmd.name.lower().replace("/", "")]
        merged: list[CommandSpec] = []
        for cmd in [*exact, *fuzzy]:
            if cmd not in merged:
                merged.append(cmd)
        return merged[:limit]

    def all(self) -> tuple[CommandSpec, ...]:
        return self.commands
