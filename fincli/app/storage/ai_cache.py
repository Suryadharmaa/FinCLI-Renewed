"""Hash-based AI response cache for FinCLI v1.2.0.

Caches AI responses to reduce API cost and latency for repeated queries.
Uses SHA-256 hash of prompt + model as cache key.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fincli.app.storage.database import FinCLIDatabase


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A cached AI response."""
    prompt_hash: str
    response: str
    model: str
    created_at: float
    ttl_seconds: int
    hit_count: int = 0


class AICache:
    """Hash-based cache for AI responses.

    Stores responses in SQLite with TTL-based expiration.
    """

    DEFAULT_TTL_SECONDS = 1800  # 30 minutes
    MAX_ENTRIES = 1000

    def __init__(self, db: FinCLIDatabase, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.db = db
        self._ttl = ttl_seconds
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create ai_cache table if not exists."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_hash TEXT NOT NULL UNIQUE,
                response TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        """)
        # Create index for faster lookups
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_cache_hash
            ON ai_cache(prompt_hash)
        """)

    @staticmethod
    def compute_hash(prompt: str, model: str, context: str = "") -> str:
        """Compute SHA-256 hash of prompt + model + context."""
        key = f"{prompt}|{model}|{context}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str, context: str = "") -> str | None:
        """Get cached response for a prompt.

        Returns None if not cached or expired.
        """
        prompt_hash = self.compute_hash(prompt, model, context)

        rows = self.db.query(
            "SELECT response, created_at, ttl_seconds FROM ai_cache WHERE prompt_hash = ?",
            (prompt_hash,),
        )

        if not rows:
            return None

        row = rows[0]
        created_at = float(row["created_at"])
        ttl = int(row["ttl_seconds"])

        # Check expiration
        if (time.time() - created_at) > ttl:
            # Expired, delete
            self.db.execute("DELETE FROM ai_cache WHERE prompt_hash = ?", (prompt_hash,))
            return None

        # Increment hit count
        self.db.execute(
            "UPDATE ai_cache SET hit_count = hit_count + 1 WHERE prompt_hash = ?",
            (prompt_hash,),
        )

        return str(row["response"])

    def set(
        self,
        prompt: str,
        model: str,
        response: str,
        context: str = "",
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache an AI response."""
        prompt_hash = self.compute_hash(prompt, model, context)
        ttl = ttl_seconds or self._ttl

        # Upsert
        self.db.execute(
            """INSERT INTO ai_cache (prompt_hash, response, model, created_at, ttl_seconds, hit_count)
               VALUES (?, ?, ?, ?, ?, 0)
               ON CONFLICT(prompt_hash) DO UPDATE SET
                 response = excluded.response,
                 model = excluded.model,
                 created_at = excluded.created_at,
                 ttl_seconds = excluded.ttl_seconds,
                 hit_count = 0""",
            (prompt_hash, response, model, time.time(), ttl),
        )

        # Enforce max entries
        self._evict_if_needed()

    def invalidate(self, pattern: str = "*") -> int:
        """Invalidate cache entries matching pattern.

        Returns number of entries deleted.
        """
        if pattern == "*":
            rows = self.db.query("SELECT COUNT(*) as cnt FROM ai_cache")
            count = int(rows[0]["cnt"]) if rows else 0
            self.db.execute("DELETE FROM ai_cache")
            return count

        # Pattern match on prompt hash
        rows = self.db.query(
            "SELECT COUNT(*) as cnt FROM ai_cache WHERE prompt_hash LIKE ?",
            (f"%{pattern}%",),
        )
        count = int(rows[0]["cnt"]) if rows else 0
        self.db.execute(
            "DELETE FROM ai_cache WHERE prompt_hash LIKE ?",
            (f"%{pattern}%",),
        )
        return count

    def clear_expired(self) -> int:
        """Remove all expired entries.

        Returns number of entries removed.
        """
        now = time.time()
        rows = self.db.query(
            "SELECT COUNT(*) as cnt FROM ai_cache WHERE (? - created_at) > ttl_seconds",
            (now,),
        )
        count = int(rows[0]["cnt"]) if rows else 0

        self.db.execute(
            "DELETE FROM ai_cache WHERE (? - created_at) > ttl_seconds",
            (now,),
        )
        return count

    def stats(self) -> dict:
        """Get cache statistics."""
        rows = self.db.query("""
            SELECT
                COUNT(*) as total_entries,
                SUM(hit_count) as total_hits,
                AVG(hit_count) as avg_hits
            FROM ai_cache
        """)
        if not rows:
            return {"total_entries": 0, "total_hits": 0, "avg_hits": 0.0}

        return {
            "total_entries": int(rows[0]["total_entries"] or 0),
            "total_hits": int(rows[0]["total_hits"] or 0),
            "avg_hits": float(rows[0]["avg_hits"] or 0.0),
        }

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if cache exceeds MAX_ENTRIES."""
        rows = self.db.query("SELECT COUNT(*) as cnt FROM ai_cache")
        count = int(rows[0]["cnt"]) if rows else 0

        if count > self.MAX_ENTRIES:
            # Delete oldest entries
            excess = count - self.MAX_ENTRIES
            self.db.execute(
                """DELETE FROM ai_cache WHERE id IN (
                       SELECT id FROM ai_cache ORDER BY created_at ASC LIMIT ?
                   )""",
                (excess,),
            )
