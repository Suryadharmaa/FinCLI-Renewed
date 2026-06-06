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
                        """
                    )
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
