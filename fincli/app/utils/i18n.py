"""Internationalization (i18n) support for FinCLI.

Supports English (en) and Indonesian (id).
Default language: English
"""

from __future__ import annotations

from typing import Any

# Current language (set by config)
_current_language: str = "en"


def set_language(lang: str) -> None:
    """Set current language."""
    global _current_language
    _current_language = lang.lower() if lang.lower() in ("en", "id") else "en"


def get_language() -> str:
    """Get current language."""
    return _current_language


def t(key: str, **kwargs: Any) -> str:
    """Translate key using current language.

    Usage:
        t("error.command_not_found", cmd="/foo")
        t("help.title", version="1.5.0")
    """
    text = TRANSLATIONS.get(_current_language, {}).get(key)
    if text is None:
        # Fallback to English
        text = TRANSLATIONS.get("en", {}).get(key, key)
    return text.format(**kwargs) if kwargs else text


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # General
        "general.cancelled": "Cancelled.",
        "general.ready": "ready",
        "general.error": "Error",

        # Help
        "help.title": "FinCLI v{version} Commands",
        "help.hint": "Type /help to see commands.",

        # Errors
        "error.command_not_found": "Command not recognized: {cmd}",
        "error.command_empty": "Command is empty.",
        "error.must_start_slash": "Command must start with slash. Example: /help",
        "error.must_be_text": "Command must be text. Example: /help",
        "error.format_invalid": "Invalid command format: {error}\nUse quotes for long text.",
        "error.unexpected": "Unexpected command error: {type}: {error}\n\nCommand not fully executed. Use /doctor to check config or retry.",

        # Symbol
        "error.symbol_empty": "Symbol cannot be empty.",
        "error.symbol_too_long": "Symbol too long (max 20 characters).",
        "error.symbol_invalid_char": "Symbol contains invalid character.",
        "error.symbol_invalid_format": "Invalid symbol format: {symbol}",
        "error.symbol_path_separator": "Symbol cannot contain path separator: '{symbol}'.",

        # Market
        "error.candle_empty": "No candle data for {symbol} ({interval}).",
        "error.quote_invalid": "Provider returned invalid quote data.",
        "error.provider_all_failed": "All providers failed for {method}.",
        "error.provider_timeout": "Provider timeout — try again or reduce query load.",

        # Portfolio
        "error.portfolio_not_found": "Portfolio '{name}' not found. Create with /portfolio create {name}",
        "error.portfolio_cannot_delete_main": "Cannot delete 'main' portfolio.",
        "error.portfolio_already_exists": "Portfolio '{name}' already exists.",

        # Transaction
        "error.tx_action_invalid": "Transaction action must be buy or sell.",
        "error.tx_qty_price_positive": "Quantity and price must be greater than 0.",
        "error.tx_no_position": "No position {symbol} to sell.",
        "error.tx_qty_exceeds": "Sell quantity exceeds {symbol} position.",

        # Trading
        "error.risk_blocked": "Risk guard blocked: {reason}",
        "error.kill_switch_active": "Kill switch active. Use /trading resume to re-enable orders.",
        "error.broker_not_connected": "Broker not connected. Use /trading live connect <broker>.",
        "error.order_not_found": "Order not found: {id}",
        "error.order_cannot_cancel": "Order {id} cannot be cancelled (status: {status}).",

        # AI
        "error.ai_key_not_set": "API key for {provider} not set.\nUse /ai_model to select provider.",
        "error.ai_invalid_response": "AI provider returned invalid data.",
        "error.ai_coding_refusal": "I'm FinCLI AI Assistance for market, portfolio, journal, provider, and risk workflow. I don't handle coding, debugging, refactoring, or software creation. You can ask about market analysis, fundamental/technical setup, watchlist, portfolio, journal, or how to use FinCLI commands.",

        # Config
        "error.config_read_failed": "Local config failed to read.",
        "error.config_save_failed": "Local config failed to save.",
        "error.config_help": "Check ~/.fincli/config.json or delete file to use defaults.",

        # Secrets
        "error.secret_save_failed": "Local secret failed to save.",
        "error.secret_clear_failed": "Local secrets failed to clear.",
        "error.secret_key_empty": "Secret value is empty.",
        "error.secret_key_invalid": "Invalid environment key name: {key}",

        # Security
        "error.security_violation": "Security violation detected.",
        "error.path_traversal": "Path traversal detected.",
        "error.path_outside_dir": "Path outside allowed directory.",
        "error.rate_limit": "Rate limit reached for {group}.",
        "error.rate_limit_cooldown": "Wait {seconds} seconds before trying again.",

        # Webhook
        "webhook.test_success": "Test notification sent to {target} ✅",
        "webhook.test_failed": "Failed to send test notification to {target} ❌\n\nError: {error}",
        "webhook.added": "{type} webhook '{name}' configured.",
        "webhook.removed": "Removed {target}",
        "webhook.remove_failed": "Failed to remove {target}",
        "webhook.no_targets": "No notification targets configured.",
        "webhook.not_found": "{type} webhook '{name}' not found. Configure with /notification add {type} {name} <url>",

        # Session
        "session.saved": "Current session saved as: {title}",
        "session.cleared": "Current session history cleared.",
        "session.all_cleared": "All session history cleared. New session created.",
        "session.restored": "Session restored.",
        "session.no_unclean": "No unclean session found to restore.",

        # Tutorial
        "tutorial.reset": "Tutorial progress reset. Type /tutorial to start over.",
        "tutorial.not_found": "Lesson not found. Use /tutorial to see available lessons.",

        # Dashboard
        "dashboard.title": "FinCLI Dashboard",
        "dashboard.provider_chain": "Provider Chain",
        "dashboard.watchlist": "Watchlist",
        "dashboard.portfolio": "Portfolio",
        "dashboard.journal": "Journal",
        "dashboard.market": "Market",
        "dashboard.alerts": "Alerts",

        # Status bar
        "status.running": "running",
        "status.cancelled": "cancelled",
        "status.error": "error",
        "status.interrupted": "interrupted",
        "status.cleared": "cleared",
        "status.ready_ai": "ai chat",
        "status.ready_stream": "ai chat (streamed)",
        "status.state_saved": "state auto-saved",

        # Theme
        "theme.changed": "Theme changed to: {name} — {description}",
        "theme.unknown": "Unknown theme: {name}. Use /theme list.",
        "theme.created": "Theme '{name}' created at {path}. Edit JSON to customize colors.",
        "theme.imported": "Theme '{name}' imported and registered.",
        "theme.exported": "Theme '{name}' exported to {path}.",

        # Config display
        "config.ai_provider": "AI provider",
        "config.ai_model": "AI model",
        "config.market_provider": "Market provider",
        "config.news_provider": "News provider",
        "config.timezone": "Timezone",
        "config.default_currency": "Default currency",
        "config.cache_ttl": "Cache TTL",
        "config.provider_timeout": "Provider timeout",
        "config.circuit_breaker": "Circuit breaker",
        "config.theme": "Theme",
        "config.api_key_status": "API key status",

        # Doctor
        "doctor.title": "FinCLI Doctor",
        "doctor.full_title": "FinCLI Doctor Full",
        "doctor.version": "Version",
        "doctor.database": "Database",
        "doctor.market_provider": "Market Provider",
        "doctor.provider_timeout": "Provider Timeout",
        "doctor.circuit_breaker": "Circuit Breaker",
        "doctor.profile": "Profile",
        "doctor.ai_provider": "AI Provider",
        "doctor.missing": "missing",
        "doctor.ok": "ok",
        "doctor.warning": "warning",
        "doctor.error": "error",
    },
    "id": {
        # General
        "general.cancelled": "Dibatalkan.",
        "general.ready": "siap",
        "general.error": "Error",

        # Help
        "help.title": "FinCLI v{version} Command",
        "help.hint": "Ketik /help untuk melihat command.",

        # Errors
        "error.command_not_found": "Command tidak dikenal: {cmd}",
        "error.command_empty": "Command kosong.",
        "error.must_start_slash": "Command harus diawali slash. Contoh: /help",
        "error.must_be_text": "Command harus berupa teks. Contoh: /help",
        "error.format_invalid": "Format command tidak valid: {error}\nGunakan quote untuk teks panjang.",
        "error.unexpected": "Unexpected command error: {type}: {error}\n\nCommand tidak dieksekusi penuh. Gunakan /doctor untuk cek konfigurasi atau coba ulang command.",

        # Symbol
        "error.symbol_empty": "Symbol tidak boleh kosong.",
        "error.symbol_too_long": "Symbol terlalu panjang (max 20 karakter).",
        "error.symbol_invalid_char": "Symbol mengandung karakter tidak valid.",
        "error.symbol_invalid_format": "Format symbol tidak valid: {symbol}",
        "error.symbol_path_separator": "Symbol tidak boleh mengandung path separator: '{symbol}'.",

        # Market
        "error.candle_empty": "Data candle kosong untuk {symbol} ({interval}).",
        "error.quote_invalid": "Provider quote mengembalikan data tidak valid.",
        "error.provider_all_failed": "Semua provider gagal untuk {method}.",
        "error.provider_timeout": "Provider timeout — coba lagi atau kurangi beban query.",

        # Portfolio
        "error.portfolio_not_found": "Portfolio '{name}' tidak ditemukan. Buat dengan /portfolio create {name}",
        "error.portfolio_cannot_delete_main": "Tidak bisa menghapus portfolio 'main'.",
        "error.portfolio_already_exists": "Portfolio '{name}' sudah ada.",

        # Transaction
        "error.tx_action_invalid": "Action transaksi harus buy atau sell.",
        "error.tx_qty_price_positive": "Quantity dan price harus lebih besar dari 0.",
        "error.tx_no_position": "Tidak ada posisi {symbol} untuk dijual.",
        "error.tx_qty_exceeds": "Quantity sell melebihi posisi {symbol}.",

        # Trading
        "error.risk_blocked": "Risk guard blocked: {reason}",
        "error.kill_switch_active": "Kill switch active. Gunakan /trading resume untuk mengaktifkan kembali.",
        "error.broker_not_connected": "Broker belum terhubung. Gunakan /trading live connect <broker>.",
        "error.order_not_found": "Order tidak ditemukan: {id}",
        "error.order_cannot_cancel": "Order {id} tidak bisa dibatalkan (status: {status}).",

        # AI
        "error.ai_key_not_set": "API key untuk {provider} belum diatur.\nGunakan /ai_model untuk memilih provider.",
        "error.ai_invalid_response": "AI provider mengembalikan data tidak valid.",
        "error.ai_coding_refusal": "Aku FinCLI AI Assistance untuk market, portfolio, journal, provider, dan risk workflow. Aku tidak menangani coding, debugging, refactor, atau pembuatan software. Kamu bisa tanya analisis market, fundamental, technical setup, watchlist, portfolio, journal, atau cara memakai command FinCLI.",

        # Config
        "error.config_read_failed": "Config lokal gagal dibaca.",
        "error.config_save_failed": "Config lokal gagal disimpan.",
        "error.config_help": "Periksa ~/.fincli/config.json atau hapus file tersebut untuk memakai default.",

        # Secrets
        "error.secret_save_failed": "Secret lokal gagal disimpan.",
        "error.secret_clear_failed": "Secret lokal gagal dibersihkan.",
        "error.secret_key_empty": "Nilai secret kosong.",
        "error.secret_key_invalid": "Nama environment key tidak valid: {key}",

        # Security
        "error.security_violation": "Pelanggaran keamanan terdeteksi.",
        "error.path_traversal": "Path traversal terdeteksi.",
        "error.path_outside_dir": "Path di luar direktori yang diizinkan.",
        "error.rate_limit": "Rate limit tercapai untuk {group}.",
        "error.rate_limit_cooldown": "Tunggu {seconds} detik sebelum mencoba lagi.",

        # Webhook
        "webhook.test_success": "Test notification terkirim ke {target} ✅",
        "webhook.test_failed": "Gagal mengirim test notification ke {target} ❌\n\nError: {error}",
        "webhook.added": "Webhook {type} '{name}' dikonfigurasi.",
        "webhook.removed": "{target} dihapus",
        "webhook.remove_failed": "Gagal menghapus {target}",
        "webhook.no_targets": "Belum ada target notifikasi.",
        "webhook.not_found": "Webhook {type} '{name}' tidak ditemukan. Konfigurasi dengan /notification add {type} {name} <url>",

        # Session
        "session.saved": "Current session disimpan sebagai: {title}",
        "session.cleared": "Current session history dikosongkan.",
        "session.all_cleared": "Semua history session dihapus. Session baru dibuat.",
        "session.restored": "Session dipulihkan.",
        "session.no_unclean": "Tidak ada session yang perlu dipulihkan.",

        # Tutorial
        "tutorial.reset": "Progress tutorial direset. Ketik /tutorial untuk mulai lagi.",
        "tutorial.not_found": "Lesson tidak ditemukan. Gunakan /tutorial untuk melihat lesson yang tersedia.",

        # Dashboard
        "dashboard.title": "FinCLI Dashboard",
        "dashboard.provider_chain": "Provider Chain",
        "dashboard.watchlist": "Watchlist",
        "dashboard.portfolio": "Portfolio",
        "dashboard.journal": "Journal",
        "dashboard.market": "Market",
        "dashboard.alerts": "Alert",

        # Status bar
        "status.running": "berjalan",
        "status.cancelled": "dibatalkan",
        "status.error": "error",
        "status.interrupted": "terinterupsi",
        "status.cleared": "dibersihkan",
        "status.ready_ai": "ai chat",
        "status.ready_stream": "ai chat (streamed)",
        "status.state_saved": "state auto-saved",

        # Theme
        "theme.changed": "Tema diubah ke: {name} — {description}",
        "theme.unknown": "Tema tidak dikenal: {name}. Gunakan /theme list.",
        "theme.created": "Tema '{name}' dibuat di {path}. Edit JSON untuk kustomisasi warna.",
        "theme.imported": "Tema '{name}' di-import dan terdaftar.",
        "theme.exported": "Tema '{name}' di-export ke {path}.",

        # Config display
        "config.ai_provider": "AI provider",
        "config.ai_model": "AI model",
        "config.market_provider": "Market provider",
        "config.news_provider": "News provider",
        "config.timezone": "Timezone",
        "config.default_currency": "Default currency",
        "config.cache_ttl": "Cache TTL",
        "config.provider_timeout": "Provider timeout",
        "config.circuit_breaker": "Circuit breaker",
        "config.theme": "Theme",
        "config.api_key_status": "Status API key",

        # Doctor
        "doctor.title": "FinCLI Doctor",
        "doctor.full_title": "FinCLI Doctor Full",
        "doctor.version": "Versi",
        "doctor.database": "Database",
        "doctor.market_provider": "Market Provider",
        "doctor.provider_timeout": "Provider Timeout",
        "doctor.circuit_breaker": "Circuit Breaker",
        "doctor.profile": "Profil",
        "doctor.ai_provider": "AI Provider",
        "doctor.missing": "belum ada",
        "doctor.ok": "ok",
        "doctor.warning": "peringatan",
        "doctor.error": "error",
    },
}
