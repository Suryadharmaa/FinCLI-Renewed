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
    CommandSpec("/symbol", "Search symbol dan tampilkan normalisasi per provider.", "/symbol XAUUSD", "Market"),
    CommandSpec("/research", "Pusat riset ringkas: market, technical, news, fundamental, dan AI deep mode.", "/research AAPL --quick", "Research"),
    CommandSpec("/macro", "Dashboard macro fallback dan connector-ready context.", "/macro Indonesia", "Research"),
    CommandSpec("/profile", "Tampilkan profil dan gameplay risk lokal.", "/profile", "Profile"),
    CommandSpec("/profile set", "Simpan profil gameplay lokal.", '/profile set "Budi" 350 USD 1:100 1.5', "Profile"),
    CommandSpec("/doctor", "Cek kesehatan konfigurasi, provider, database, dan command inti.", "/doctor", "System"),
    CommandSpec("/setup", "Panduan setup lokal untuk API key, provider, dan profile.", "/setup", "System"),
    CommandSpec("/secrets status", "Audit status secret lokal tanpa menampilkan nilai.", "/secrets status", "Security"),
    CommandSpec("/secrets clear", "Hapus semua API key lokal dari secret store.", "/secrets clear", "Security"),
    CommandSpec("/privacy status", "Tampilkan ringkasan state lokal sensitif.", "/privacy status", "Security"),
    CommandSpec("/privacy purge", "Bersihkan secrets, history session, dan cache lokal.", "/privacy purge", "Security"),
    CommandSpec("/agent", "Lihat agent framework FinCLI.", "/agent list", "AI"),
    CommandSpec("/agent show", "Tampilkan detail agent framework.", "/agent show buffett", "AI"),
    CommandSpec("/connector", "Lihat catalog data connector.", "/connector list macro", "Provider"),
    CommandSpec("/connector search", "Cari connector data.", "/connector search yahoo", "Provider"),
    CommandSpec("/plugin", "Tampilkan plugin lokal FinCLI.", "/plugin list", "System"),
    CommandSpec("/plugin status", "Cek status manifest plugin lokal.", "/plugin status", "System"),
    CommandSpec("/market", "Ringkasan market profesional untuk instrumen.", "/market AAPL 1d", "Market"),
    CommandSpec("/news", "Tampilkan news/fundamental terbaru untuk instrumen.", "/news AAPL", "Market"),
    CommandSpec("/technical", "Analisis teknikal instrumen.", "/technical BTC-USD 1d", "Analysis"),
    CommandSpec("/mtf", "Multi-timeframe technical alignment.", "/mtf AAPL 1d,1h,15m", "Analysis"),
    CommandSpec("/backtest", "Lightweight rule-based strategy backtest.", "/backtest AAPL sma_cross 1d", "Analysis"),
    CommandSpec("/yahoo", "Tampilkan tabel Yahoo Finance untuk history/statistics/profile/financials/analysis/holders.", "/yahoo BBRI statistics", "Market"),
    CommandSpec("/ai", "Free chat dengan AI assistant.", "/ai ringkas risiko AAPL", "AI"),
    CommandSpec("/analyze", "AI menganalisis struktur pasar instrumen.", "/analyze ETH-USD 4h", "Analysis"),
    CommandSpec("/watchlist", "Tampilkan watchlist.", "/watchlist", "Watchlist"),
    CommandSpec("/watchlist add", "Tambahkan instrumen ke watchlist.", "/watchlist add AAPL", "Watchlist"),
    CommandSpec("/watchlist remove", "Hapus instrumen dari watchlist.", "/watchlist remove AAPL", "Watchlist"),
    CommandSpec("/portfolio", "Tampilkan portfolio lokal.", "/portfolio", "Portfolio"),
    CommandSpec("/portfolio add", "Tambahkan posisi/aset.", "/portfolio add BTC-USD 0.05 65000", "Portfolio"),
    CommandSpec("/portfolio remove", "Hapus posisi/aset.", "/portfolio remove BTC-USD", "Portfolio"),
    CommandSpec("/portfolio performance", "Tampilkan performa portfolio.", "/portfolio performance", "Portfolio"),
    CommandSpec("/portfolio risk", "Portfolio Risk v2: exposure, concentration, PnL, dan health score.", "/portfolio risk", "Portfolio"),
    CommandSpec("/tx", "Tampilkan transaction ledger.", "/tx list", "Portfolio"),
    CommandSpec("/tx add", "Tambahkan transaksi buy/sell.", "/tx add buy AAPL 10 185", "Portfolio"),
    CommandSpec("/journal", "Tampilkan journal trading/investasi.", "/journal", "Journal"),
    CommandSpec("/journal add", "Tambahkan catatan journal singkat.", '/journal add BTC-USD bullish "Breakout gagal, tunggu konfirmasi"', "Journal"),
    CommandSpec("/journal stats", "Tampilkan statistik journal.", "/journal stats", "Journal"),
    CommandSpec("/journal review", "AI review kebiasaan journal.", "/journal review", "Journal"),
    CommandSpec("/alert", "Tampilkan alert harga lokal.", "/alert", "Alert"),
    CommandSpec("/alert add", "Tambahkan alert harga.", "/alert add AAPL above 200", "Alert"),
    CommandSpec("/alert check", "Cek alert aktif memakai quote provider.", "/alert check", "Alert"),
    CommandSpec("/history", "Tampilkan command history current session.", "/history", "History"),
    CommandSpec("/history sessions", "Tampilkan daftar session tersimpan.", "/history sessions", "History"),
    CommandSpec("/history show", "Tampilkan detail session tertentu.", "/history show <session_id>", "History"),
    CommandSpec("/history save", "Beri nama current session.", '/history save "Riset IHSG pagi"', "History"),
    CommandSpec("/history delete", "Hapus session tertentu.", "/history delete <session_id>", "History"),
    CommandSpec("/config", "Tampilkan konfigurasi aktif tanpa membocorkan API key.", "/config"),
    CommandSpec("/scan", "Scanner watchlist dengan filter indikator.", "/scan watchlist rsi<30", "Market"),
    CommandSpec("/scan export", "Export hasil scanner watchlist ke CSV/JSON.", "/scan export csv scan.csv rsi<30 1d", "Market"),
    CommandSpec("/report market", "Export market report ke Markdown/JSON.", "/report market AAPL md report.md", "Export"),
    CommandSpec("/calendar", "Economic calendar provider/fallback.", "/calendar week US high", "Market"),
    CommandSpec("/calendar export", "Export economic calendar ke CSV/JSON.", "/calendar export csv calendar.csv week US high", "Market"),
    CommandSpec("/provider status", "Tampilkan status provider aktif.", "/provider status", "Provider"),
    CommandSpec("/provider metrics", "Tampilkan metric runtime provider aktif.", "/provider metrics", "Provider"),
    CommandSpec("/provider list", "Tampilkan semua provider market yang tersedia.", "/provider list", "Provider"),
    CommandSpec("/provider entitlement", "Tampilkan capability dan realtime/delayed label provider.", "/provider entitlement", "Provider"),
    CommandSpec("/provider test", "Test quote provider aktif untuk symbol.", "/provider test AAPL", "Provider"),
    CommandSpec("/provider key status", "Tampilkan status API key market provider.", "/provider key status", "Provider"),
    CommandSpec("/cache stats", "Tampilkan statistik cache market persistent.", "/cache stats", "System"),
    CommandSpec("/cache clear", "Bersihkan runtime dan persistent market cache.", "/cache clear", "System"),
    CommandSpec("/export journal", "Export journal ke CSV/JSON.", "/export journal csv journal.csv", "Export"),
    CommandSpec("/export portfolio", "Export portfolio ke CSV/JSON.", "/export portfolio json portfolio.json", "Export"),
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
