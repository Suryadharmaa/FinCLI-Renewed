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
    CommandSpec("/news_model key", "Simpan API key market/news lokal.", "/news_model key finnhub <api_key>", "Provider"),
    CommandSpec("/market", "Ringkasan market profesional untuk instrumen.", "/market AAPL 1d", "Market"),
    CommandSpec("/news", "Tampilkan news/fundamental terbaru untuk instrumen.", "/news AAPL", "Market"),
    CommandSpec("/web", "Web search lalu AI merangkum jawaban.", "/web penyebab rupiah melemah hari ini", "Research"),
    CommandSpec("/web sources", "Tampilkan sumber mentah hasil web search.", "/web sources penyebab rupiah melemah hari ini", "Research"),
    CommandSpec("/technical", "Analisis teknikal instrumen.", "/technical BTC-USD 1d", "Analysis"),
    CommandSpec("/structure", "Analisis struktur pasar instrumen.", "/structure BTC-USD 1d", "Analysis"),
    CommandSpec("/funda", "Fundamental ringkas instrumen.", "/funda MSFT", "Market"),
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
    CommandSpec("/tx", "Tampilkan transaction ledger.", "/tx list", "Portfolio"),
    CommandSpec("/tx add", "Tambahkan transaksi buy/sell.", "/tx add buy AAPL 10 185", "Portfolio"),
    CommandSpec("/journal", "Tampilkan journal trading/investasi.", "/journal", "Journal"),
    CommandSpec("/journal add", "Tambahkan catatan journal singkat.", '/journal add BTC-USD bullish "Breakout gagal, tunggu konfirmasi"', "Journal"),
    CommandSpec("/journal stats", "Tampilkan statistik journal.", "/journal stats", "Journal"),
    CommandSpec("/journal review", "AI review kebiasaan journal.", "/journal review", "Journal"),
    CommandSpec("/history", "Tampilkan command history current session.", "/history", "History"),
    CommandSpec("/history sessions", "Tampilkan daftar session tersimpan.", "/history sessions", "History"),
    CommandSpec("/history show", "Tampilkan detail session tertentu.", "/history show <session_id>", "History"),
    CommandSpec("/history save", "Beri nama current session.", '/history save "Riset IHSG pagi"', "History"),
    CommandSpec("/history delete", "Hapus session tertentu.", "/history delete <session_id>", "History"),
    CommandSpec("/config", "Tampilkan konfigurasi aktif tanpa membocorkan API key.", "/config"),
    CommandSpec("/quote", "Tampilkan harga/quote instrumen.", "/quote NVDA", "Market"),
    CommandSpec("/scan", "Scanner watchlist dengan filter indikator.", "/scan watchlist rsi<30", "Market"),
    CommandSpec("/calendar", "Economic calendar provider/fallback.", "/calendar week US high", "Market"),
    CommandSpec("/provider status", "Tampilkan status provider aktif.", "/provider status", "Provider"),
    CommandSpec("/provider list", "Tampilkan semua provider market yang tersedia.", "/provider list", "Provider"),
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
