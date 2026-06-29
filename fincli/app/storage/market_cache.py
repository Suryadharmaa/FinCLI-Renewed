"""Persistent SQLite cache for market provider responses."""

from __future__ import annotations

import json
from time import time
from typing import Any

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import StorageError


class MarketCache:
    """Provider response cache with TTL persisted in SQLite."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def get(self, namespace: str, cache_key: str) -> dict[str, Any] | list[Any] | None:
        rows = self.db.query(
            "SELECT payload, expires_at FROM market_cache WHERE namespace = ? AND cache_key = ?",
            (namespace, cache_key),
        )
        if not rows:
            return None

        row = rows[0]
        if float(row["expires_at"]) <= time():
            self.delete(namespace, cache_key)
            return None

        try:
            payload = json.loads(str(row["payload"]))
        except json.JSONDecodeError as exc:
            self.delete(namespace, cache_key)
            raise StorageError("Market cache payload corrupted and has been removed.") from exc

        if isinstance(payload, (dict, list)):
            return payload
        return None

    def set(self, namespace: str, cache_key: str, payload: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        encoded = json.dumps(payload, separators=(",", ":"))
        expires_at = time() + max(1, ttl_seconds)
        self.db.execute(
            """
            INSERT INTO market_cache (namespace, cache_key, payload, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, cache_key)
            DO UPDATE SET payload = excluded.payload, expires_at = excluded.expires_at, created_at = CURRENT_TIMESTAMP
            """,
            (namespace, cache_key, encoded, expires_at),
        )

    def delete(self, namespace: str, cache_key: str) -> None:
        self.db.execute(
            "DELETE FROM market_cache WHERE namespace = ? AND cache_key = ?",
            (namespace, cache_key),
        )

    def clear(self, namespace: str | None = None) -> int:
        if namespace:
            count = int(self.db.query("SELECT COUNT(*) AS total FROM market_cache WHERE namespace = ?", (namespace,))[0]["total"])
            self.db.execute("DELETE FROM market_cache WHERE namespace = ?", (namespace,))
            return count
        count = int(self.db.query("SELECT COUNT(*) AS total FROM market_cache")[0]["total"])
        self.db.execute("DELETE FROM market_cache")
        return count

    def prune_expired(self) -> int:
        count = int(self.db.query("SELECT COUNT(*) AS total FROM market_cache WHERE expires_at <= ?", (time(),))[0]["total"])
        self.db.execute("DELETE FROM market_cache WHERE expires_at <= ?", (time(),))
        return count

    def stats(self) -> dict[str, int]:
        self.prune_expired()
        rows = self.db.query(
            """
            SELECT namespace, COUNT(*) AS total
            FROM market_cache
            GROUP BY namespace
            ORDER BY namespace
            """
        )
        by_namespace = {str(row["namespace"]): int(row["total"]) for row in rows}
        return {
            "total": sum(by_namespace.values()),
            "quote": by_namespace.get("quote", 0),
            "history": by_namespace.get("history", 0),
            "news": by_namespace.get("news", 0),
            "fundamentals": by_namespace.get("fundamentals", 0),
        }
