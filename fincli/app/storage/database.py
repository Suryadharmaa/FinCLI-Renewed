"""SQLite storage for FinCLI local data."""

from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3
from typing import Iterable

from fincli.app.storage.config import APP_DIR
from fincli.app.utils.errors import StorageError


DB_FILE = APP_DIR / "fincli.db"


class FinCLIDatabase:
    """Small SQLite wrapper for watchlist, portfolio, and journal data."""

    def __init__(self, db_file: Path = DB_FILE) -> None:
        self.db_file = db_file
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_file)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        try:
            with closing(self.connect()) as db:
                with db:
                    db.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS watchlist (
                            symbol TEXT PRIMARY KEY,
                            group_name TEXT DEFAULT 'default',
                            notes TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS portfolio_positions (
                            symbol TEXT PRIMARY KEY,
                            quantity REAL NOT NULL,
                            average_price REAL NOT NULL,
                            currency TEXT DEFAULT 'USD',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS journal_entries (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            instrument TEXT NOT NULL,
                            bias TEXT DEFAULT '',
                            entry_reason TEXT DEFAULT '',
                            exit_reason TEXT DEFAULT '',
                            result TEXT DEFAULT '',
                            emotion TEXT DEFAULT '',
                            lesson TEXT DEFAULT '',
                            tags TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS portfolio_transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            action TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            quantity REAL NOT NULL,
                            price REAL NOT NULL,
                            currency TEXT DEFAULT 'USD',
                            realized_pnl REAL DEFAULT 0,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS market_cache (
                            namespace TEXT NOT NULL,
                            cache_key TEXT NOT NULL,
                            payload TEXT NOT NULL,
                            expires_at REAL NOT NULL,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (namespace, cache_key)
                        );

                        CREATE TABLE IF NOT EXISTS sessions (
                            id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS session_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            command TEXT NOT NULL,
                            status TEXT NOT NULL,
                            output_preview TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                        );

                        CREATE TABLE IF NOT EXISTS alerts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            symbol TEXT NOT NULL,
                            condition TEXT NOT NULL,
                            target REAL NOT NULL,
                            note TEXT DEFAULT '',
                            active INTEGER DEFAULT 1,
                            triggered_at TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS user_profile (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            name TEXT NOT NULL,
                            equity REAL NOT NULL,
                            currency TEXT NOT NULL,
                            leverage TEXT NOT NULL,
                            years_in_investment REAL NOT NULL,
                            gameplay TEXT NOT NULL,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS provider_metrics (
                            provider TEXT PRIMARY KEY,
                            calls INTEGER DEFAULT 0,
                            successes INTEGER DEFAULT 0,
                            errors INTEGER DEFAULT 0,
                            fallbacks INTEGER DEFAULT 0,
                            total_latency_ms REAL DEFAULT 0,
                            last_status TEXT DEFAULT 'not_called',
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS provider_operation_metrics (
                            provider TEXT NOT NULL,
                            operation TEXT NOT NULL,
                            calls INTEGER DEFAULT 0,
                            successes INTEGER DEFAULT 0,
                            errors INTEGER DEFAULT 0,
                            total_latency_ms REAL DEFAULT 0,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (provider, operation)
                        );

                        CREATE TABLE IF NOT EXISTS paper_orders (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            side TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            quantity REAL NOT NULL,
                            order_type TEXT NOT NULL,
                            price REAL,
                            stop_price REAL,
                            notional REAL DEFAULT 0,
                            status TEXT NOT NULL,
                            strategy TEXT DEFAULT 'manual',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS order_audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            order_id INTEGER,
                            action TEXT NOT NULL,
                            detail TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS kill_switch (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            active INTEGER NOT NULL DEFAULT 0,
                            reason TEXT DEFAULT '',
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            total_value REAL NOT NULL,
                            cost_basis REAL NOT NULL,
                            unrealized_pnl REAL NOT NULL,
                            realized_pnl REAL NOT NULL,
                            positions_json TEXT DEFAULT '{}',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS alert_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            alert_id INTEGER,
                            symbol TEXT NOT NULL,
                            condition TEXT NOT NULL,
                            target REAL NOT NULL,
                            actual_value REAL,
                            triggered INTEGER DEFAULT 1,
                            note TEXT DEFAULT '',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS security_audit (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            event_type TEXT NOT NULL,
                            detail TEXT NOT NULL DEFAULT '',
                            ip_address TEXT DEFAULT 'local',
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP
                        );
                        """
                    )
                    _migrate_user_profile_schema(db)
                    _migrate_paper_orders_schema(db)
                    _migrate_watchlist_notes(db)
        except sqlite3.Error as exc:
            raise StorageError("Database lokal gagal diinisialisasi.") from exc

    def execute(self, sql: str, params: Iterable[object] = ()) -> None:
        try:
            with closing(self.connect()) as db:
                with db:
                    db.execute(sql, tuple(params))
        except sqlite3.Error as exc:
            raise StorageError("Operasi database gagal.") from exc

    def query(self, sql: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
        try:
            with closing(self.connect()) as db:
                return list(db.execute(sql, tuple(params)).fetchall())
        except sqlite3.Error as exc:
            raise StorageError("Query database gagal.") from exc


def _migrate_paper_orders_schema(db: sqlite3.Connection) -> None:
    """Add stop_price column to paper_orders if missing (v0.7.0)."""
    columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(paper_orders)").fetchall()}
    if "stop_price" not in columns:
        db.execute("ALTER TABLE paper_orders ADD COLUMN stop_price REAL")


def _migrate_watchlist_notes(db: sqlite3.Connection) -> None:
    """Add notes column to watchlist if missing (v1.0.2)."""
    columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(watchlist)").fetchall()}
    if "notes" not in columns:
        db.execute("ALTER TABLE watchlist ADD COLUMN notes TEXT DEFAULT ''")


def _migrate_user_profile_schema(db: sqlite3.Connection) -> None:
    """Normalize older user_profile schemas to the v0.4.0 canonical shape."""

    columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(user_profile)").fetchall()}
    canonical = {"id", "name", "equity", "currency", "leverage", "years_in_investment", "gameplay", "updated_at"}
    if canonical.issubset(columns):
        return

    rows = list(db.execute("SELECT * FROM user_profile").fetchall())
    legacy_profile = _legacy_profile_payload(rows[0]) if rows else None
    db.execute("DROP TABLE user_profile")
    db.execute(
        """
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            equity REAL NOT NULL,
            currency TEXT NOT NULL,
            leverage TEXT NOT NULL,
            years_in_investment REAL NOT NULL,
            gameplay TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    if legacy_profile is None:
        return
    db.execute(
        """
        INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        legacy_profile,
    )


def _legacy_profile_payload(row: sqlite3.Row) -> tuple[object, ...]:
    keys = set(row.keys())
    name = row["name"] if "name" in keys else "User"
    equity = row["equity"] if "equity" in keys else row["equity_amount"] if "equity_amount" in keys else 0
    currency = row["currency"] if "currency" in keys else row["equity_currency"] if "equity_currency" in keys else "USD"
    leverage = row["leverage"] if "leverage" in keys else "1:1"
    years = (
        row["years_in_investment"]
        if "years_in_investment" in keys
        else row["experience_years"]
        if "experience_years" in keys
        else 0
    )
    gameplay = _normalize_legacy_gameplay(str(row["gameplay"])) if "gameplay" in keys else _classify_legacy_gameplay(float(equity))
    return (name, equity, currency, leverage, years, gameplay)


def _normalize_legacy_gameplay(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "scalper": "Scalper",
        "intra_day": "Intra day",
        "intraday": "Intra day",
        "day_trade": "Day trade",
        "day_trader": "Day trade",
        "swing": "Swing/Investor",
        "investor": "Swing/Investor",
    }.get(normalized, value.strip() or "Scalper")


def _classify_legacy_gameplay(equity: float) -> str:
    if equity <= 400:
        return "Scalper"
    if equity <= 1000:
        return "Intra day"
    if equity <= 5000:
        return "Day trade"
    return "Swing/Investor"
